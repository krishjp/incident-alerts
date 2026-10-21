// Seeds a handful of demo accounts at different stages of the setup funnel,
// for manual QA and demos. Not run automatically by any build/deploy step —
// invoke explicitly with `npm run seed:demo` against a local/dev database
// only (it is a no-op guard away from ever running against production).
//
// Reuses the real Torrance -> Huntington Beach polyline already sitting in
// the dev DB (from backend/fixtures/torrance_hb_405_test.kml's paired test
// subscription) for the "active" accounts, so running the worker against
// that fixture produces real matches/alerts for these accounts too, without
// hitting Nominatim/OSRM or an API key.
require("dotenv").config();
const crypto = require("crypto");
const { PrismaClient } = require("@prisma/client");
const bcrypt = require("bcryptjs");

const prisma = new PrismaClient();

const DEMO_PASSWORD = "DemoPass123!";
const DEMO_PHONE = "+15559876543";

// Mirrors src/lib/crypto.ts's encryptPhone exactly (this script runs outside
// Next.js's module resolution, so it can't import the TS path alias directly).
function encryptPhone(phone, hexKey) {
    const key = Buffer.from(hexKey, "hex");
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
    const ciphertext = Buffer.concat([cipher.update(phone, "utf8"), cipher.final()]);
    const tag = cipher.getAuthTag();
    return [iv, tag, ciphertext].map((b) => b.toString("base64")).join(":");
}

async function main() {
    if (process.env.ENVIRONMENT && !["development", "dev", "test", "local"].includes(process.env.ENVIRONMENT.toLowerCase())) {
        throw new Error(`Refusing to seed demo accounts with ENVIRONMENT=${process.env.ENVIRONMENT}`);
    }

    const key = process.env.PHONE_ENCRYPTION_KEY;
    if (!key || key.length !== 64) {
        throw new Error("PHONE_ENCRYPTION_KEY must be set (see frontend/.env.example).");
    }

    const hashedPassword = await bcrypt.hash(DEMO_PASSWORD, 10);
    const encryptedPhone = encryptPhone(DEMO_PHONE, key);

    // Borrow the real, already-routed polyline from the existing 405 test
    // subscription (created against the live OSRM/Directions API) so the
    // "active" demo accounts match backend/fixtures/torrance_hb_405_test.kml
    // without a network call here.
    const referenceSub = await prisma.routeSubscription.findFirst({
        where: { origin: "Torrance, CA", destination: "Huntington Beach, CA" },
    });
    const demoPolyline = referenceSub?.polyline ?? null;
    if (!demoPolyline) {
        console.warn(
            "[seed-demo] No existing Torrance->Huntington Beach subscription found to copy a polyline from — " +
            "the 'active' demo accounts will be created without a route match. Create that subscription first " +
            "(see backend/README.md's Local Testing with Injected Incidents) to get live-matching demo accounts."
        );
    }

    const accounts = [
        {
            email: "demo-just-signed-up@incidentalerts.demo",
            name: "Jamie (Just Signed Up)",
            stage: "Registered only — no phone, no route yet. Shows the empty dashboard state.",
            phone: null,
            subscriptions: [],
        },
        {
            email: "demo-route-no-phone@incidentalerts.demo",
            name: "Riley (Route Added, No Phone)",
            stage: "Added a route but never saved a phone number — can't actually receive alerts yet.",
            phone: null,
            subscriptions: demoPolyline
                ? [{ origin: "Torrance, CA", destination: "Huntington Beach, CA", area: "Los Angeles", startTime: "07:00", endTime: "09:00", isActive: true, polyline: demoPolyline }]
                : [],
        },
        {
            email: "demo-paused@incidentalerts.demo",
            name: "Morgan (Fully Set Up, Paused)",
            stage: "Phone + route configured, but the route is paused (e.g. on vacation).",
            phone: DEMO_PHONE,
            subscriptions: demoPolyline
                ? [{ origin: "Torrance, CA", destination: "Huntington Beach, CA", area: "Los Angeles", startTime: "07:00", endTime: "09:00", isActive: false, polyline: demoPolyline }]
                : [],
        },
        {
            email: "demo-fully-active@incidentalerts.demo",
            name: "Casey (Fully Active)",
            stage: "Phone + active route, open 24/7 so it matches backend/fixtures/torrance_hb_405_test.kml immediately — good for a live worker-run demo.",
            phone: DEMO_PHONE,
            subscriptions: demoPolyline
                ? [{ origin: "Torrance, CA", destination: "Huntington Beach, CA", area: "Los Angeles", startTime: "00:00", endTime: "23:59", isActive: true, polyline: demoPolyline }]
                : [],
        },
        {
            email: "demo-power-user@incidentalerts.demo",
            name: "Taylor (Power User)",
            stage: "Phone + multiple routes, one active (live-matching) and one paused — shows the dashboard at scale.",
            phone: DEMO_PHONE,
            subscriptions: demoPolyline
                ? [
                    { origin: "Torrance, CA", destination: "Huntington Beach, CA", area: "Los Angeles", startTime: "00:00", endTime: "23:59", isActive: true, polyline: demoPolyline },
                    { origin: "San Diego, CA", destination: "Los Angeles, CA", area: "San Diego", startTime: "16:00", endTime: "19:00", isActive: false, polyline: demoPolyline },
                ]
                : [],
        },
    ];

    for (const acct of accounts) {
        const user = await prisma.user.upsert({
            where: { email: acct.email },
            update: {
                name: acct.name,
                password: hashedPassword,
                phone: acct.phone ? encryptedPhone : null,
            },
            create: {
                email: acct.email,
                name: acct.name,
                password: hashedPassword,
                phone: acct.phone ? encryptedPhone : null,
            },
        });

        // Idempotent re-runs: drop this user's prior demo subscriptions before
        // recreating them, rather than accumulating duplicates on each run.
        await prisma.routeSubscription.deleteMany({ where: { userId: user.id } });
        for (const sub of acct.subscriptions) {
            await prisma.routeSubscription.create({ data: { ...sub, userId: user.id } });
        }

        console.log(`[seed-demo] ${acct.email} — ${acct.stage}`);
    }

    console.log(`\nAll demo accounts share the password: ${DEMO_PASSWORD}`);
    console.log(`Phone-enabled accounts use: ${DEMO_PHONE}`);
}

main()
    .catch((err) => {
        console.error("[seed-demo] Failed:", err);
        process.exitCode = 1;
    })
    .finally(() => prisma.$disconnect());
