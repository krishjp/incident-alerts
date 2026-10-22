import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { NORTH_AMERICA_BBOX, type Suggestion } from "@/lib/geo";
import { rateLimit, tooManyRequests } from "@/lib/rate-limit";
import { NextResponse } from "next/server";

// Address suggestions for the route form. Backed by Photon (OSM data, built for
// search-as-you-type) rather than Nominatim, whose usage policy forbids
// autocomplete outright. PHOTON_URL can point at a self-hosted instance; the
// public one asks for fair use, which the client-side debounce plus the
// per-user limit below keep us within.
const PHOTON_URL = process.env.PHOTON_URL || "https://photon.komoot.io";
const MIN_QUERY_LENGTH = 3;
const MAX_QUERY_LENGTH = 200;
const MAX_SUGGESTIONS = 5;

type PhotonFeature = {
    geometry?: { coordinates?: [number, number] };
    properties?: Record<string, string | undefined>;
};

function formatLabel(p: Record<string, string | undefined>): string {
    const street = [p.housenumber, p.street].filter(Boolean).join(" ");
    // A named place (a business, airport, park) leads with its name; a plain
    // address leads with the street line instead of repeating it.
    const head = p.name && p.name !== street ? p.name : null;
    const region = [p.state, p.postcode].filter(Boolean).join(" ");
    const parts = [head, street, p.city ?? p.town ?? p.district, region, p.countrycode?.toUpperCase()];
    // Drop adjacent repeats ("Springfield, Springfield, Illinois" for a city).
    return parts.filter((part, i) => part && part !== parts[i - 1]).join(", ");
}

export async function GET(req: Request) {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const limit = await rateLimit("geocode:suggest", session.user.email, {
        limit: 60,
        windowSeconds: 60,
    });
    if (!limit.allowed) return tooManyRequests(limit);

    const q = new URL(req.url).searchParams.get("q")?.trim() ?? "";
    if (q.length < MIN_QUERY_LENGTH) return NextResponse.json([]);
    if (q.length > MAX_QUERY_LENGTH) {
        return NextResponse.json({ error: "Query too long." }, { status: 400 });
    }

    const url = new URL("/api/", PHOTON_URL);
    url.searchParams.set("q", q);
    url.searchParams.set("limit", String(MAX_SUGGESTIONS));
    url.searchParams.set("lang", "en");
    url.searchParams.set("bbox", NORTH_AMERICA_BBOX);

    try {
        const res = await fetch(url, {
            headers: { "User-Agent": process.env.GEOCODER_USER_AGENT || "IncidentAlerts/1.0" },
            signal: AbortSignal.timeout(5000),
        });
        if (!res.ok) throw new Error(`Photon responded ${res.status}`);
        const data = (await res.json()) as { features?: PhotonFeature[] };

        const seen = new Set<string>();
        const suggestions: Suggestion[] = [];
        for (const f of data.features ?? []) {
            const coords = f.geometry?.coordinates;
            if (!coords || !f.properties) continue;
            const label = formatLabel(f.properties);
            if (!label || seen.has(label)) continue;
            seen.add(label);
            suggestions.push({ label, lon: coords[0], lat: coords[1] });
        }
        return NextResponse.json(suggestions);
    } catch (e) {
        // Suggestions are a convenience: the form still accepts typed addresses,
        // which the subscriptions endpoint geocodes itself.
        console.error("[Geocode] Suggestion lookup failed:", e);
        return NextResponse.json([], { status: 200 });
    }
}
