import { createHash } from "crypto";
import { prisma } from "./prisma";
import {
    fetchGooglePolyline,
    fetchOsrmPolyline,
    NoRouteError,
} from "./routing";
import type { Place } from "./geo";

/**
 * Persistent origin/destination -> polyline cache (the RouteCache table).
 *
 * Route geometry for a given address pair is effectively static, but every
 * subscription created without this cache paid a fresh geocode + routing call.
 * Against the public Nominatim/OSRM endpoints that is the fastest way to earn a
 * 429 (or an IP block); against the Google Directions API it is a billed
 * request per attempt. Caching in Postgres rather than in memory means the
 * savings survive redeploys and are shared across serverless instances.
 */

export type RouteProvider = "google" | "osrm";

/**
 * Keyed by resolved coordinates rather than address text: by the time a route
 * is requested both endpoints are already geocoded, and "100 Main St, LA" vs
 * "100 Main Street, Los Angeles" are the same trip. Four decimals is ~11 m,
 * well inside the distance a router snaps an address to the nearest road.
 * The display names are stored alongside for inspection.
 */
function coordKey({ lat, lon }: Place): string {
    return `${lat.toFixed(4)},${lon.toFixed(4)}`;
}

function cacheKey(origin: Place, destination: Place, provider: RouteProvider): string {
    const raw = `${coordKey(origin)}|${coordKey(destination)}|${provider}`;
    return createHash("sha256").update(raw).digest("hex");
}

export class RoutingUnavailableError extends Error {}

/**
 * Returns an encoded polyline for the route, from cache when possible.
 *
 * Cache failures are never fatal — a missing or unwritable RouteCache row
 * degrades to the old behaviour (call the upstream service) rather than
 * blocking subscription creation.
 */
export async function getRoutePolyline(
    origin: Place,
    destination: Place,
): Promise<{ polyline: string; provider: RouteProvider; cached: boolean }> {
    const apiKey = process.env.GOOGLE_MAPS_API_KEY;
    const useGoogle = Boolean(apiKey) && apiKey !== "dummy_map_key";
    const provider: RouteProvider = useGoogle ? "google" : "osrm";
    const key = cacheKey(origin, destination, provider);

    try {
        const hit = await prisma.routeCache.findUnique({ where: { key } });
        if (hit) {
            // Fire-and-forget: a hit counter is not worth failing a request or
            // adding latency for.
            prisma.routeCache
                .update({ where: { key }, data: { hits: { increment: 1 } } })
                .catch(() => undefined);
            return { polyline: hit.polyline, provider, cached: true };
        }
    } catch (e) {
        console.error("[RouteCache] Lookup failed, falling through to provider:", e);
    }

    let polyline: string;
    try {
        polyline = useGoogle
            ? await fetchGooglePolyline(origin, destination, apiKey!)
            : await fetchOsrmPolyline(origin, destination);
    } catch (e) {
        if (e instanceof NoRouteError) throw e;
        const message = e instanceof Error ? e.message : "Routing service unavailable";
        throw new RoutingUnavailableError(message);
    }

    try {
        // upsert, not create: two concurrent requests for the same new route
        // would otherwise race on the primary key.
        await prisma.routeCache.upsert({
            where: { key },
            create: {
                key,
                origin: origin.displayName,
                destination: destination.displayName,
                provider,
                polyline,
            },
            update: { polyline },
        });
    } catch (e) {
        console.error("[RouteCache] Write failed (route still returned):", e);
    }

    return { polyline, provider, cached: false };
}
