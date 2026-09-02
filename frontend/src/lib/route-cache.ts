import { createHash } from "crypto";
import { prisma } from "./prisma";
import {
    fetchGooglePolyline,
    fetchOsrmPolyline,
    NoRouteError,
} from "./routing";

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
 * Normalizes an address for cache-key purposes: case-insensitive, whitespace-
 * and punctuation-insensitive. "100 Main St., LA" and "100 main st  la" share
 * an entry; anything more aggressive risks collapsing genuinely distinct
 * addresses, so the raw strings are stored alongside for inspection.
 */
function normalizeAddress(address: string): string {
    return address
        .toLowerCase()
        .replace(/[.,]/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}

function cacheKey(
    origin: string,
    destination: string,
    provider: RouteProvider,
): string {
    const raw = `${normalizeAddress(origin)}|${normalizeAddress(destination)}|${provider}`;
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
    origin: string,
    destination: string,
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
            create: { key, origin, destination, provider, polyline },
            update: { polyline },
        });
    } catch (e) {
        console.error("[RouteCache] Write failed (route still returned):", e);
    }

    return { polyline, provider, cached: false };
}
