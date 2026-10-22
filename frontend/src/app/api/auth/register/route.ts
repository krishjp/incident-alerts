import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { clientIdentifier, rateLimit, tooManyRequests } from "@/lib/rate-limit";
import { validateEmail, validateName, validateNewPassword } from "@/lib/validation";
import bcrypt from "bcryptjs";

export async function POST(req: Request) {
    // Unauthenticated endpoint, so the limit is keyed by client IP. Bulk signup
    // attempts are both a spam vector and a way to probe which emails exist.
    const limit = await rateLimit("auth:register", clientIdentifier(req), {
        limit: 5,
        windowSeconds: 300,
    });
    if (!limit.allowed) return tooManyRequests(limit);

    try {
        const { name, email, password } = await req.json();

        const validationError =
            validateName(name) ?? validateEmail(email) ?? validateNewPassword(password);
        if (validationError) {
            return NextResponse.json({ error: validationError }, { status: 400 });
        }

        const normalizedEmail = email.trim().toLowerCase();
        const exists = await prisma.user.findUnique({ where: { email: normalizedEmail } });
        if (exists) {
            return NextResponse.json({ error: "User already exists." }, { status: 400 });
        }

        const hashedPassword = await bcrypt.hash(password, 10);
        const user = await prisma.user.create({
            data: {
                name: name.trim(),
                email: normalizedEmail,
                password: hashedPassword,
            },
        });

        return NextResponse.json({ success: true, user: { id: user.id, email: user.email } });
    } catch (error) {
        // Log the detail, return a generic message: the raw error text can
        // expose schema/driver internals to an unauthenticated caller.
        console.error("[Register] Failed:", error);
        return NextResponse.json({ error: "Could not create account." }, { status: 500 });
    }
}
