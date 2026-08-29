import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { fetchOsrmPolyline } from "@/lib/routing";
import { NextResponse } from "next/server";

export async function GET() {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const subs = await prisma.routeSubscription.findMany({
        where: { user: { email: String(session.user.email) } }
    });
    return NextResponse.json(subs);
}

export async function POST(req: Request) {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const user = await prisma.user.findUnique({ where: { email: session.user.email } });
    if (!user) return NextResponse.json({ error: "User not found" }, { status: 404 });

    const json = await req.json();
    const { origin, destination, area, startTime, endTime } = json;

    let encodedPolyline: string;
    const apiKey = process.env.GOOGLE_MAPS_API_KEY;

    if (apiKey && apiKey !== "dummy_map_key") {
        try {
            const res = await fetch(`https://maps.googleapis.com/maps/api/directions/json?origin=${encodeURIComponent(origin)}&destination=${encodeURIComponent(destination)}&key=${apiKey}`);
            const data = await res.json();
            if (data.routes && data.routes.length > 0) {
                encodedPolyline = data.routes[0].overview_polyline.points;
            } else {
                return NextResponse.json({ error: "Could not find a valid route between these locations." }, { status: 400 });
            }
        } catch (e) {
            console.error(e);
            return NextResponse.json({ error: "Map API Error" }, { status: 500 });
        }
    } else {
        // No Google key configured: geocode + route via free Nominatim/OSRM services
        // so every user still gets a real polyline for their actual origin/destination
        // (previously this path returned the same hardcoded LA polyline for everyone).
        try {
            encodedPolyline = await fetchOsrmPolyline(origin, destination);
        } catch (e) {
            console.error("OSRM Routing Error:", e);
            const errorMessage = e instanceof Error ? e.message : "Routing service unavailable";
            return NextResponse.json(
                { error: `Routing service error: ${errorMessage}. Please check your addresses or try again later.` },
                { status: 503 }
            );
        }
    }

    const sub = await prisma.routeSubscription.create({
        data: {
            userId: user.id,
            origin,
            destination,
            area,
            polyline: encodedPolyline,
            startTime,
            endTime,
        }
    });
    return NextResponse.json(sub);
}

export async function DELETE(req: Request) {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const url = new URL(req.url);
    const id = url.searchParams.get("id");
    if (!id) return NextResponse.json({ error: "Missing id" }, { status: 400 });

    await prisma.routeSubscription.delete({ where: { id } });
    return NextResponse.json({ success: true });
}
