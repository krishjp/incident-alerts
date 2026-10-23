import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { getRoutePolyline, RoutingUnavailableError } from "@/lib/route-cache";
import { geocodeAddress, NoRouteError } from "@/lib/routing";
import { decodePolyline, isInNorthAmerica, isValidLatLon, validateRoute, type Place } from "@/lib/geo";
import { rateLimit, tooManyRequests } from "@/lib/rate-limit";
import { NextResponse } from "next/server";

const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;
const MAX_ADDRESS_LENGTH = 200;
const MAX_SUBSCRIPTIONS_PER_USER = 20;

async function requireUser() {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) return null;
    return prisma.user.findUnique({ where: { email: String(session.user.email) } });
}

export async function GET() {
    const user = await requireUser();
    if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const subs = await prisma.routeSubscription.findMany({
        where: { userId: user.id },
        orderBy: { createdAt: "asc" },
    });
    return NextResponse.json(subs);
}

export async function POST(req: Request) {
    const user = await requireUser();
    if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    // Keyed by user id rather than IP: this endpoint is authenticated, and each
    // request can trigger an external geocode/routing call (a billed one when a
    // Google Maps key is configured).
    const limit = await rateLimit("subscriptions:create", user.id, {
        limit: 10,
        windowSeconds: 60,
    });
    if (!limit.allowed) return tooManyRequests(limit);

    let json: unknown;
    try {
        json = await req.json();
    } catch {
        return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const { origin, destination, area, startTime, endTime, originPlace, destinationPlace } =
        (json ?? {}) as Record<string, unknown>;

    const validationError = validateSubscriptionInput({
        origin,
        destination,
        area,
        startTime,
        endTime,
    });
    if (validationError) {
        return NextResponse.json({ error: validationError }, { status: 400 });
    }

    const existingCount = await prisma.routeSubscription.count({
        where: { userId: user.id },
    });
    if (existingCount >= MAX_SUBSCRIPTIONS_PER_USER) {
        return NextResponse.json(
            { error: `You can monitor at most ${MAX_SUBSCRIPTIONS_PER_USER} routes.` },
            { status: 400 },
        );
    }

    let route: BuiltRoute;
    try {
        route = await buildRoute(
            { label: "Origin", text: String(origin), picked: originPlace },
            { label: "Destination", text: String(destination), picked: destinationPlace },
        );
    } catch (e) {
        return routeErrorResponse(e);
    }
    const { polyline, originPt, destPt } = route;

    const sub = await prisma.routeSubscription.create({
        data: {
            userId: user.id,
            origin: String(origin).trim(),
            destination: String(destination).trim(),
            originDisplayName: originPt.displayName.slice(0, 500),
            destinationDisplayName: destPt.displayName.slice(0, 500),
            area: String(area),
            polyline,
            startTime: String(startTime),
            endTime: String(endTime),
        },
    });
    return NextResponse.json(sub);
}

/**
 * Edits a subscription in place: pause/resume, time window, area, and either
 * endpoint. Changing an endpoint rebuilds the route; the side left unchanged
 * keeps its routed point (the polyline's first/last point), so it isn't
 * re-geocoded from text that may resolve somewhere else this time.
 */
export async function PATCH(req: Request) {
    const user = await requireUser();
    if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    let json: unknown;
    try {
        json = await req.json();
    } catch {
        return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const { id, isActive, startTime, endTime, area, origin, destination, originPlace, destinationPlace } =
        (json ?? {}) as Record<string, unknown>;
    if (typeof id !== "string" || !id) {
        return NextResponse.json({ error: "Missing subscription id." }, { status: 400 });
    }

    // userId scopes the lookup to rows this user owns, so a guessed/leaked id
    // from another account matches nothing.
    const existing = await prisma.routeSubscription.findFirst({ where: { id, userId: user.id } });
    if (!existing) {
        return NextResponse.json({ error: "Subscription not found." }, { status: 404 });
    }

    const data: Record<string, unknown> = {};
    if (typeof isActive === "boolean") data.isActive = isActive;
    if (startTime !== undefined) {
        if (!isValidTime(startTime)) {
            return NextResponse.json({ error: "startTime must be HH:MM." }, { status: 400 });
        }
        data.startTime = startTime;
    }
    if (endTime !== undefined) {
        if (!isValidTime(endTime)) {
            return NextResponse.json({ error: "endTime must be HH:MM." }, { status: 400 });
        }
        data.endTime = endTime;
    }
    if ((data.startTime ?? existing.startTime) === (data.endTime ?? existing.endTime)) {
        return NextResponse.json({ error: "Start and end times must differ." }, { status: 400 });
    }
    for (const [label, key, value] of [
        ["Area", "area", area],
        ["Origin", "origin", origin],
        ["Destination", "destination", destination],
    ] as const) {
        if (value === undefined) continue;
        if (typeof value !== "string" || value.trim().length === 0) {
            return NextResponse.json({ error: `${label} is required.` }, { status: 400 });
        }
        if (value.length > MAX_ADDRESS_LENGTH) {
            return NextResponse.json(
                { error: `${label} must be under ${MAX_ADDRESS_LENGTH} characters.` },
                { status: 400 },
            );
        }
        data[key] = value.trim();
    }
    if (Object.keys(data).length === 0) {
        return NextResponse.json({ error: "Nothing to update." }, { status: 400 });
    }

    // An endpoint counts as changed when its text differs or a new suggestion
    // was picked; resaving the same text keeps the existing route.
    const originChanged =
        (data.origin !== undefined && data.origin !== existing.origin) || isValidLatLon(originPlace);
    const destChanged =
        (data.destination !== undefined && data.destination !== existing.destination) ||
        isValidLatLon(destinationPlace);
    const rerouted = originChanged || destChanged;

    if (rerouted) {
        // Same budget as creation: a reroute costs the same geocode/routing calls.
        const limit = await rateLimit("subscriptions:create", user.id, { limit: 10, windowSeconds: 60 });
        if (!limit.allowed) return tooManyRequests(limit);

        // An undecodable stored polyline just means the unchanged side is
        // geocoded from its text again, like a new route.
        let points: ReturnType<typeof decodePolyline> = [];
        try {
            points = decodePolyline(existing.polyline);
        } catch {}
        const first = points[0];
        const last = points[points.length - 1];

        let route: BuiltRoute;
        try {
            route = await buildRoute(
                {
                    label: "Origin",
                    text: String(data.origin ?? existing.origin),
                    picked: originPlace,
                    known: !originChanged && first
                        ? { ...first, displayName: existing.originDisplayName ?? existing.origin }
                        : undefined,
                },
                {
                    label: "Destination",
                    text: String(data.destination ?? existing.destination),
                    picked: destinationPlace,
                    known: !destChanged && last
                        ? { ...last, displayName: existing.destinationDisplayName ?? existing.destination }
                        : undefined,
                },
            );
        } catch (e) {
            return routeErrorResponse(e);
        }
        data.polyline = route.polyline;
        data.originDisplayName = route.originPt.displayName.slice(0, 500);
        data.destinationDisplayName = route.destPt.displayName.slice(0, 500);
    }

    const updated = await prisma.routeSubscription.update({ where: { id: existing.id }, data });

    if (rerouted) {
        // The worker's "already alerted" rows describe incidents on the old
        // route; left in place, they'd fire "resolved" alerts for that route.
        await clearNotifiedIncidents(existing.id);
    }

    return NextResponse.json(updated);
}

export async function DELETE(req: Request) {
    const user = await requireUser();
    if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const url = new URL(req.url);
    const id = url.searchParams.get("id");
    if (!id) return NextResponse.json({ error: "Missing id" }, { status: 400 });

    // deleteMany scoped by userId, not delete({ where: { id } }): the previous
    // version deleted any subscription by id, so any signed-in user could
    // delete another account's route by guessing or replaying its id.
    const result = await prisma.routeSubscription.deleteMany({
        where: { id, userId: user.id },
    });
    if (result.count === 0) {
        return NextResponse.json({ error: "Subscription not found." }, { status: 404 });
    }

    // Clear the worker's per-subscription notification bookkeeping so a future
    // subscription can't inherit this one's "already alerted" rows.
    await clearNotifiedIncidents(id);

    return NextResponse.json({ success: true });
}

async function clearNotifiedIncidents(subscriptionId: string) {
    await prisma.notifiedIncident
        .deleteMany({ where: { id: { startsWith: `${subscriptionId}_` } } })
        .catch((e) => console.error("[Subscriptions] NotifiedIncident cleanup failed:", e));
}

type Endpoint = {
    label: string;
    text: string;
    /** Coordinates from a picked autocomplete suggestion, if any. */
    picked?: unknown;
    /** An already-resolved point that is reused as is (an edit's unchanged side). */
    known?: Place;
};

type BuiltRoute = { polyline: string; originPt: Place; destPt: Place };

/**
 * Resolves both endpoints and builds a validated route between them. Throws
 * NoRouteError for a bad input and RoutingUnavailableError for a provider
 * failure; routeErrorResponse maps either to an HTTP response.
 */
async function buildRoute(origin: Endpoint, destination: Endpoint): Promise<BuiltRoute> {
    // Sequential, not Promise.all: typed (unpicked) addresses go through the
    // 1 req/s Nominatim gate anyway.
    const originPt = origin.known ?? (await resolvePlace(origin.label, origin.text, origin.picked));
    const destPt = destination.known ?? (await resolvePlace(destination.label, destination.text, destination.picked));

    // Cache-first: a repeated origin/destination pair never re-hits the
    // routing provider. See src/lib/route-cache.ts.
    const { polyline } = await getRoutePolyline(originPt, destPt);

    const routeError = validateRoute(polyline, originPt, destPt);
    if (routeError) throw new NoRouteError(routeError);
    return { polyline, originPt, destPt };
}

function routeErrorResponse(e: unknown) {
    if (e instanceof NoRouteError) {
        return NextResponse.json({ error: e.message }, { status: 400 });
    }
    if (e instanceof RoutingUnavailableError) {
        console.error("Routing error:", e);
        return NextResponse.json(
            {
                error: `Routing service error: ${e.message}. Please check your addresses or try again later.`,
            },
            { status: 503 },
        );
    }
    console.error("Unexpected routing failure:", e);
    return NextResponse.json({ error: "Could not build a route." }, { status: 500 });
}

/**
 * Turns one side of the route form into coordinates. A picked autocomplete
 * suggestion already carries them; anything typed by hand is geocoded here.
 * Either way the point must lie in North America.
 */
async function resolvePlace(label: string, text: string, picked: unknown): Promise<Place> {
    let place: Place;
    if (isValidLatLon(picked)) {
        place = { lat: picked.lat, lon: picked.lon, displayName: text.trim() };
    } else {
        try {
            place = await geocodeAddress(text);
        } catch (e) {
            if (e instanceof NoRouteError) throw e;
            throw new RoutingUnavailableError(
                e instanceof Error ? e.message : "Geocoding service unavailable",
            );
        }
    }
    if (!isInNorthAmerica(place)) {
        throw new NoRouteError(`${label} must be a location in North America.`);
    }
    return place;
}

function isValidTime(value: unknown): value is string {
    return typeof value === "string" && TIME_PATTERN.test(value);
}

function validateSubscriptionInput(input: {
    origin: unknown;
    destination: unknown;
    area: unknown;
    startTime: unknown;
    endTime: unknown;
}): string | null {
    const { origin, destination, area, startTime, endTime } = input;

    for (const [label, value] of [
        ["Origin", origin],
        ["Destination", destination],
        ["Area", area],
    ] as const) {
        if (typeof value !== "string" || value.trim().length === 0) {
            return `${label} is required.`;
        }
        if (value.length > MAX_ADDRESS_LENGTH) {
            return `${label} must be under ${MAX_ADDRESS_LENGTH} characters.`;
        }
    }

    if (!isValidTime(startTime) || !isValidTime(endTime)) {
        return "Start and end times must be in HH:MM format.";
    }
    if (startTime === endTime) {
        return "Start and end times must differ.";
    }

    return null;
}
