// Free geocoding (Nominatim) + driving-route (OSRM) fallback used when no
// GOOGLE_MAPS_API_KEY is configured. Requests geometries=polyline so OSRM
// returns an already-encoded standard (precision-5) polyline string, matching
// the format backend/route_utils.py's decode_polyline expects.
//
// OSRM_URL defaults to the public OSRM demo server, which has no SLA and rate
// -limits aggressively — fine for development, not for real traffic. Point it
// at a self-hosted OSRM instance (see docker-compose.yml's `osrm` service) in
// any environment with real users.
const OSRM_URL = process.env.OSRM_URL || "http://router.project-osrm.org";

async function geocodeAddress(address: string): Promise<{ lat: number; lon: number }> {
    const url = new URL("https://nominatim.openstreetmap.org/search");
    url.searchParams.set("q", address);
    url.searchParams.set("format", "json");
    url.searchParams.set("limit", "1");

    const res = await fetch(url.toString(), {
        headers: { "User-Agent": "IncidentAlerts/1.0" },
    });
    const data = await res.json();
    if (!Array.isArray(data) || data.length === 0) {
        throw new Error(`Could not geocode address: ${address}`);
    }
    return { lat: parseFloat(data[0].lat), lon: parseFloat(data[0].lon) };
}

/**
 * Geocodes origin/destination addresses and fetches a driving route between them
 * using the public OSRM demo server, returning an encoded polyline.
 */
export async function fetchOsrmPolyline(origin: string, destination: string): Promise<string> {
    const [originPt, destPt] = await Promise.all([
        geocodeAddress(origin),
        geocodeAddress(destination),
    ]);

    const osrmUrl = `${OSRM_URL}/route/v1/driving/${originPt.lon},${originPt.lat};${destPt.lon},${destPt.lat}?overview=full&geometries=polyline`;
    const res = await fetch(osrmUrl, { headers: { "User-Agent": "IncidentAlerts/1.0" } });
    const data = await res.json();

    if (!data.routes || data.routes.length === 0) {
        throw new Error(`No route found between ${origin} and ${destination}`);
    }

    // OSRM already returns a Google-format encoded polyline when geometries=polyline.
    return data.routes[0].geometry;
}
