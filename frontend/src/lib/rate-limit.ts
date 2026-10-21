/**
 * Request rate limiting for the API routes.
 *
 * The subscription-creation endpoint fans out to external geocoding/routing
 * services and writes to Postgres, so an unauthenticated flood (or one
 * misbehaving client) is both a denial-of-service vector and, with a Google
 * Maps key configured, a billing one. Registration is limited too, to slow
 * account-enumeration and bulk-signup attempts.
 *
 * Two backends:
 *   - Upstash Redis over its REST API when UPSTASH_REDIS_REST_URL/TOKEN are set
 *     (or KV_REST_API_URL/TOKEN, the names Vercel's Upstash Marketplace
 *     integration injects). This is the correct choice for a deployment on
 *     Vercel, where each serverless instance is a separate process and
 *     in-memory counters are per-instance (and therefore trivially bypassed by
 *     concurrency).
 *   - An in-memory fixed-window counter otherwise, so local development and
 *     single-instance deploys still get basic protection with no extra infra.
 */

const UPSTASH_URL = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const UPSTASH_TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;

export const rateLimitBackend: "upstash" | "memory" =
    UPSTASH_URL && UPSTASH_TOKEN ? "upstash" : "memory";

export type RateLimitResult = {
    allowed: boolean;
    remaining: number;
    /** Seconds until the current window resets. */
    retryAfter: number;
};

type Window = { count: number; resetAt: number };

// Module-level so it survives between requests within one instance. Bounded by
// pruneExpired() below to keep a long-lived instance from growing unboundedly.
const memoryWindows = new Map<string, Window>();

function pruneExpired(now: number) {
    if (memoryWindows.size < 10_000) return;
    for (const [key, window] of memoryWindows) {
        if (window.resetAt <= now) memoryWindows.delete(key);
    }
}

function memoryLimit(key: string, limit: number, windowSeconds: number): RateLimitResult {
    const now = Date.now();
    pruneExpired(now);

    const existing = memoryWindows.get(key);
    if (!existing || existing.resetAt <= now) {
        memoryWindows.set(key, { count: 1, resetAt: now + windowSeconds * 1000 });
        return { allowed: true, remaining: limit - 1, retryAfter: windowSeconds };
    }

    existing.count += 1;
    const retryAfter = Math.max(1, Math.ceil((existing.resetAt - now) / 1000));
    return {
        allowed: existing.count <= limit,
        remaining: Math.max(0, limit - existing.count),
        retryAfter,
    };
}

async function upstashLimit(
    key: string,
    limit: number,
    windowSeconds: number,
): Promise<RateLimitResult> {
    // INCR then EXPIRE-on-first-hit is a fixed window: one round trip in the
    // common case, and the key expires itself so there is nothing to clean up.
    const res = await fetch(`${UPSTASH_URL}/pipeline`, {
        method: "POST",
        headers: {
            Authorization: `Bearer ${UPSTASH_TOKEN}`,
            "Content-Type": "application/json",
        },
        body: JSON.stringify([
            ["INCR", key],
            ["EXPIRE", key, String(windowSeconds), "NX"],
            ["TTL", key],
        ]),
        cache: "no-store",
    });

    if (!res.ok) {
        throw new Error(`Upstash responded ${res.status}`);
    }

    const results = (await res.json()) as Array<{ result: number }>;
    const count = Number(results[0]?.result ?? 0);
    const ttl = Number(results[2]?.result ?? windowSeconds);

    return {
        allowed: count <= limit,
        remaining: Math.max(0, limit - count),
        retryAfter: ttl > 0 ? ttl : windowSeconds,
    };
}

/**
 * Consumes one unit from `identifier`'s budget for `name`.
 *
 * Fails open: if the limiter backend itself errors, the request is allowed
 * through. An outage of the rate limiter should not take down signups.
 */
export async function rateLimit(
    name: string,
    identifier: string,
    { limit, windowSeconds }: { limit: number; windowSeconds: number },
): Promise<RateLimitResult> {
    const key = `ratelimit:${name}:${identifier}`;

    if (rateLimitBackend === "upstash") {
        try {
            return await upstashLimit(key, limit, windowSeconds);
        } catch (e) {
            console.error("[RateLimit] Upstash unavailable, allowing request:", e);
            return { allowed: true, remaining: limit, retryAfter: windowSeconds };
        }
    }

    return memoryLimit(key, limit, windowSeconds);
}

/**
 * Best-effort client identity for anonymous endpoints.
 *
 * x-forwarded-for is client-controllable in general, but on Vercel (and behind
 * any proxy that rewrites it) the left-most entry is the real client. Prefer an
 * authenticated identifier — a user id or email — wherever one is available.
 */
export function clientIdentifier(req: Request): string {
    const forwarded = req.headers.get("x-forwarded-for");
    if (forwarded) return forwarded.split(",")[0].trim();
    return req.headers.get("x-real-ip") ?? "unknown";
}

/** Standard 429 response carrying Retry-After. */
export function tooManyRequests(result: RateLimitResult): Response {
    return new Response(
        JSON.stringify({
            error: "Too many requests. Please slow down and try again shortly.",
        }),
        {
            status: 429,
            headers: {
                "Content-Type": "application/json",
                "Retry-After": String(result.retryAfter),
            },
        },
    );
}
