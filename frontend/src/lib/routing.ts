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
const NOMINATIM_URL =
    process.env.NOMINATIM_URL || "https://nominatim.openstreetmap.org";

// Nominatim's usage policy is a hard maximum of 1 request/second per client.
// Exceeding it gets the deploy's egress IP blocked, not just throttled — and on
// Vercel that IP is shared. Every geocode goes through this serialized gate.
const NOMINATIM_MIN_INTERVAL_MS = 1100;

const USER_AGENT =
    process.env.GEOCODER_USER_AGENT ||
    "IncidentAlerts/1.0 (traffic incident alert service)";

let nominatimChain: Promise<unknown> = Promise.resolve();
let lastNominatimAt = 0;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Serializes calls and spaces them at least NOMINATIM_MIN_INTERVAL_MS apart.
 *
 * Note this is per-instance state: on a serverless platform each concurrent
 * instance keeps its own gate, so this bounds a burst from one instance rather
 * than guaranteeing a global rate. The RouteCache lookup in front of it is what
 * keeps total call volume low; this handles the rest.
 */
function throttleNominatim<T>(fn: () => Promise<T>): Promise<T> {
    const result = nominatimChain.then(async () => {
        const wait = lastNominatimAt + NOMINATIM_MIN_INTERVAL_MS - Date.now();
        if (wait > 0) await sleep(wait);
        lastNominatimAt = Date.now();
        return fn();
    });
    // Keep the chain alive even when a link rejects, so one failed geocode
    // doesn't wedge every subsequent request behind a rejected promise.
    nominatimChain = result.catch(() => undefined);
    return result;
}

/** Retries a request on 429/5xx with exponential backoff. */
async function fetchWithRetry(
    url: string,
    init: RequestInit,
    { attempts = 3, baseDelayMs = 500 } = {},
): Promise<Response> {
    let lastError: unknown;

    for (let attempt = 1; attempt <= attempts; attempt++) {
        try {
            const res = await fetch(url, init);
            if (res.status !== 429 && res.status < 500) return res;
            lastError = new Error(`Upstream responded ${res.status}`);
        } catch (e) {
            lastError = e;
        }

        if (attempt < attempts) {
            await sleep(baseDelayMs * 2 ** (attempt - 1));
        }
    }

    throw lastError instanceof Error
        ? lastError
        : new Error("Upstream request failed");
}

async function geocodeAddress(address: string): Promise<{ lat: number; lon: number }> {
    const url = new URL("/search", NOMINATIM_URL);
    url.searchParams.set("q", address);
    url.searchParams.set("format", "json");
    url.searchParams.set("limit", "1");

    const res = await throttleNominatim(() =>
        fetchWithRetry(url.toString(), {
            headers: { "User-Agent": USER_AGENT },
        }),
    );

    if (!res.ok) {
        throw new Error(`Geocoding service returned ${res.status}`);
    }

    const data = await res.json();
    if (!Array.isArray(data) || data.length === 0) {
        throw new Error(`Could not geocode address: ${address}`);
    }
    return { lat: parseFloat(data[0].lat), lon: parseFloat(data[0].lon) };
}

/**
 * Geocodes origin/destination addresses and fetches a driving route between them
 * using OSRM, returning an encoded polyline.
 */
export async function fetchOsrmPolyline(origin: string, destination: string): Promise<string> {
    // Sequential, not Promise.all: the two geocodes share the 1 req/s Nominatim
    // gate anyway, and issuing them in parallel only queues them behind it.
    const originPt = await geocodeAddress(origin);
    const destPt = await geocodeAddress(destination);

    const osrmUrl = `${OSRM_URL}/route/v1/driving/${originPt.lon},${originPt.lat};${destPt.lon},${destPt.lat}?overview=full&geometries=polyline`;
    const res = await fetchWithRetry(osrmUrl, { headers: { "User-Agent": USER_AGENT } });

    if (!res.ok) {
        throw new Error(`Routing service returned ${res.status}`);
    }

    const data = await res.json();
    if (!data.routes || data.routes.length === 0) {
        throw new Error(`No route found between ${origin} and ${destination}`);
    }

    // OSRM already returns a Google-format encoded polyline when geometries=polyline.
    return data.routes[0].geometry;
}

/**
 * Fetches a route polyline from the Google Directions API.
 * Throws a NoRouteError when the addresses are valid but unroutable, so the
 * caller can distinguish user error (400) from a service outage (503).
 */
export class NoRouteError extends Error {}

export async function fetchGooglePolyline(
    origin: string,
    destination: string,
    apiKey: string,
): Promise<string> {
    const url =
        `https://maps.googleapis.com/maps/api/directions/json` +
        `?origin=${encodeURIComponent(origin)}` +
        `&destination=${encodeURIComponent(destination)}` +
        `&key=${apiKey}`;

    const res = await fetchWithRetry(url, {});
    const data = await res.json();

    if (!data.routes || data.routes.length === 0) {
        throw new NoRouteError(
            "Could not find a valid route between these locations.",
        );
    }
    return data.routes[0].overview_polyline.points;
}
