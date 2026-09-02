import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { getRoutePolyline, RoutingUnavailableError } from "@/lib/route-cache";
import { NoRouteError } from "@/lib/routing";
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

    const { origin, destination, area, startTime, endTime } = (json ?? {}) as Record<
        string,
        unknown
    >;

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

    let polyline: string;
    try {
        // Cache-first: a repeated origin/destination pair never re-hits the
        // routing provider. See src/lib/route-cache.ts.
        ({ polyline } = await getRoutePolyline(String(origin), String(destination)));
    } catch (e) {
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

    const sub = await prisma.routeSubscription.create({
        data: {
            userId: user.id,
            origin: String(origin).trim(),
            destination: String(destination).trim(),
            area: String(area),
            polyline,
            startTime: String(startTime),
            endTime: String(endTime),
        },
    });
    return NextResponse.json(sub);
}

/**
 * Pause/resume a subscription (and edit its time window) without deleting it —
 * the worker only considers rows with isActive=true inside their window.
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

    const { id, isActive, startTime, endTime } = (json ?? {}) as Record<string, unknown>;
    if (typeof id !== "string" || !id) {
        return NextResponse.json({ error: "Missing subscription id." }, { status: 400 });
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
    if (Object.keys(data).length === 0) {
        return NextResponse.json({ error: "Nothing to update." }, { status: 400 });
    }

    // userId in the where clause scopes the update to rows this user owns, so a
    // guessed/leaked id from another account matches nothing.
    const result = await prisma.routeSubscription.updateMany({
        where: { id, userId: user.id },
        data,
    });
    if (result.count === 0) {
        return NextResponse.json({ error: "Subscription not found." }, { status: 404 });
    }

    const updated = await prisma.routeSubscription.findUnique({ where: { id } });
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
    await prisma.notifiedIncident
        .deleteMany({ where: { id: { startsWith: `${id}_` } } })
        .catch((e) => console.error("[Subscriptions] NotifiedIncident cleanup failed:", e));

    return NextResponse.json({ success: true });
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
