import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { encryptPhone, decryptPhone } from "@/lib/crypto";
import { rateLimit, tooManyRequests } from "@/lib/rate-limit";
import { NextResponse } from "next/server";

export async function GET() {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const user = await prisma.user.findUnique({ where: { email: session.user.email } });
    return NextResponse.json({ phone: user?.phone ? decryptPhone(user.phone) : "" });
}

export async function POST(req: Request) {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    // The saved number is where the worker sends SMS, so rapid re-pointing is
    // a way to aim alerts (and Twilio spend) at numbers the caller doesn't own.
    const limit = await rateLimit("user:phone", session.user.email, {
        limit: 5,
        windowSeconds: 300,
    });
    if (!limit.allowed) return tooManyRequests(limit);

    let json: unknown;
    try {
        json = await req.json();
    } catch {
        return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const { phone } = (json ?? {}) as Record<string, unknown>;
    let normalized: string | null = null;
    if (phone !== undefined && phone !== null && phone !== "") {
        normalized = normalizeUsPhone(phone);
        if (!normalized) {
            return NextResponse.json(
                { error: "Enter a valid US phone number, e.g. +1 234 567 8900." },
                { status: 400 },
            );
        }
    }

    const updatedUser = await prisma.user.update({
        where: { email: session.user.email },
        data: { phone: normalized ? encryptPhone(normalized) : null }
    });
    return NextResponse.json({ phone: updatedUser.phone ? decryptPhone(updatedUser.phone) : "" });
}

/**
 * Normalizes a US number to E.164 (+1XXXXXXXXXX), the form Twilio sends to,
 * or returns null. Restricting to US numbers (with a valid area code and
 * exchange) also keeps premium-rate international destinations — the target
 * of SMS-pumping fraud — out of the send list.
 */
function normalizeUsPhone(value: unknown): string | null {
    if (typeof value !== "string" || value.length > 32) return null;
    const digits = value.replace(/[\s().+-]/g, "");
    if (!/^\d+$/.test(digits)) return null;
    const national = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
    if (!/^[2-9]\d{2}[2-9]\d{6}$/.test(national)) return null;
    return `+1${national}`;
}
