import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
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

    let encodedPolyline = "dummy_polyline";
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
        // Use OSRM turn-by-turn driving route via OpenStreetMap Nominatim geocoding
        try {
            const headers = { "User-Agent": "IncidentAlerts/1.0" };
            
            // Geocode origin
            const originRes = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(origin)}&format=json&limit=1`, { headers });
            const originData = await originRes.json();
            if (!originData || originData.length === 0) {
                return NextResponse.json({ error: `Could not geocode origin: ${origin}` }, { status: 400 });
            }
            const originLat = parseFloat(originData[0].lat);
            const originLon = parseFloat(originData[0].lon);

            // Geocode destination
            const destRes = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(destination)}&format=json&limit=1`, { headers });
            const destData = await destRes.json();
            if (!destData || destData.length === 0) {
                return NextResponse.json({ error: `Could not geocode destination: ${destination}` }, { status: 400 });
            }
            const destLat = parseFloat(destData[0].lat);
            const destLon = parseFloat(destData[0].lon);

            // Fetch driving polyline from OSRM
            const osrmUrl = `http://router.project-osrm.org/route/v1/driving/${originLon},${originLat};${destLon},${destLat}?overview=full&geometries=polyline`;
            const osrmRes = await fetch(osrmUrl, { headers });
            const osrmData = await osrmRes.json();

            if (osrmData.routes && osrmData.routes.length > 0) {
                // OSRM returns Google polyline format string when geometries=polyline
                encodedPolyline = osrmData.routes[0].geometry;
            } else {
                return NextResponse.json({ error: "No road driving route found between specified locations." }, { status: 400 });
            }
        } catch (e: any) {
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
