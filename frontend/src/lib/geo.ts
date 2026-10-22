// Geometry helpers for validating a route before it is saved. The worker only
// ever sees the stored polyline, so a route that geocoded to the wrong city (or
// the wrong continent) would silently match the wrong incidents forever.

export type LatLon = { lat: number; lon: number };

/** A resolved route endpoint: coordinates plus the place name they came from. */
export type Place = LatLon & { displayName: string };

/** An autocomplete result, as returned by /api/geocode. */
export type Suggestion = { label: string; lat: number; lon: number };

// Generous box around North America (Alaska to Panama, Pacific to Newfoundland).
// It deliberately over-includes some ocean and Caribbean; its job is to reject
// a geocode that landed on another continent, not to draw borders.
export const NORTH_AMERICA_BOUNDS = {
    minLat: 7,
    maxLat: 84,
    minLon: -170,
    maxLon: -52,
};

/** Nominatim/Photon-style "minLon,minLat,maxLon,maxLat" string for the box. */
export const NORTH_AMERICA_BBOX = [
    NORTH_AMERICA_BOUNDS.minLon,
    NORTH_AMERICA_BOUNDS.minLat,
    NORTH_AMERICA_BOUNDS.maxLon,
    NORTH_AMERICA_BOUNDS.maxLat,
].join(",");

export function isInNorthAmerica({ lat, lon }: LatLon): boolean {
    const b = NORTH_AMERICA_BOUNDS;
    return lat >= b.minLat && lat <= b.maxLat && lon >= b.minLon && lon <= b.maxLon;
}

export function isValidLatLon(value: unknown): value is LatLon {
    if (!value || typeof value !== "object") return false;
    const { lat, lon } = value as Record<string, unknown>;
    return (
        typeof lat === "number" &&
        typeof lon === "number" &&
        Number.isFinite(lat) &&
        Number.isFinite(lon) &&
        Math.abs(lat) <= 90 &&
        Math.abs(lon) <= 180
    );
}

/** Decodes a standard precision-5 encoded polyline (Google/OSRM format). */
export function decodePolyline(encoded: string): LatLon[] {
    const points: LatLon[] = [];
    let index = 0;
    let lat = 0;
    let lon = 0;

    while (index < encoded.length) {
        for (const axis of ["lat", "lon"] as const) {
            let result = 0;
            let shift = 0;
            let byte: number;
            do {
                if (index >= encoded.length) throw new Error("Truncated polyline");
                byte = encoded.charCodeAt(index++) - 63;
                result |= (byte & 0x1f) << shift;
                shift += 5;
            } while (byte >= 0x20);
            const delta = result & 1 ? ~(result >> 1) : result >> 1;
            if (axis === "lat") lat += delta;
            else lon += delta;
        }
        points.push({ lat: lat / 1e5, lon: lon / 1e5 });
    }
    return points;
}

export function haversineMiles(a: LatLon, b: LatLon): number {
    const R = 3958.8;
    const toRad = (d: number) => (d * Math.PI) / 180;
    const dLat = toRad(b.lat - a.lat);
    const dLon = toRad(b.lon - a.lon);
    const h =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
}

// How far the route's first/last point may sit from the geocoded address.
// Routers snap to the nearest drivable road, which for a rural address or a
// large venue (an airport) can be a couple of miles away.
const MAX_ENDPOINT_SNAP_MILES = 3;
// A driving route is longer than the straight line, but not wildly so. The
// additive slack keeps short trips around a bay or freeway interchange legal.
const MAX_DETOUR_RATIO = 4;
const DETOUR_SLACK_MILES = 15;

/**
 * Returns a user-facing reason the route looks wrong, or null if it is sane:
 * both endpoints in North America, a decodable polyline that starts near the
 * origin and ends near the destination, and no absurd detour.
 */
export function validateRoute(
    polyline: string,
    origin: LatLon,
    destination: LatLon,
): string | null {
    if (!isInNorthAmerica(origin)) {
        return "The origin address resolved to a location outside North America.";
    }
    if (!isInNorthAmerica(destination)) {
        return "The destination address resolved to a location outside North America.";
    }

    let points: LatLon[];
    try {
        points = decodePolyline(polyline);
    } catch {
        return "The routing service returned an unreadable route.";
    }
    if (points.length < 2) {
        return "The routing service returned an empty route.";
    }
    if (!points.every(isInNorthAmerica)) {
        return "The computed route leaves North America.";
    }

    const start = points[0];
    const end = points[points.length - 1];
    if (haversineMiles(start, origin) > MAX_ENDPOINT_SNAP_MILES) {
        return "No road route starts near the origin address. Try a more specific address.";
    }
    if (haversineMiles(end, destination) > MAX_ENDPOINT_SNAP_MILES) {
        return "No road route ends near the destination address. Try a more specific address.";
    }

    let length = 0;
    for (let i = 1; i < points.length; i++) {
        length += haversineMiles(points[i - 1], points[i]);
    }
    const direct = haversineMiles(origin, destination);
    if (length > direct * MAX_DETOUR_RATIO + DETOUR_SLACK_MILES) {
        return "The computed route is far longer than the distance between the addresses. Check both addresses.";
    }

    return null;
}
