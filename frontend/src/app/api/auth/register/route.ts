import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { clientIdentifier, rateLimit, tooManyRequests } from "@/lib/rate-limit";
import { validateIdentifier, validateName, validateNewPassword } from "@/lib/validation";
import { Prisma } from "@prisma/client";
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
            validateName(name) ?? validateIdentifier(email) ?? validateNewPassword(password);
        if (validationError) {
            return NextResponse.json({ error: validationError }, { status: 400 });
        }

        const normalizedEmail = email.trim().toLowerCase();
        // Case-insensitive so a pre-existing mixed-case row still counts as taken.
        const exists = await prisma.user.findFirst({
            where: { email: { equals: normalizedEmail, mode: "insensitive" } },
            select: { id: true },
        });
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
        // Two simultaneous signups can both pass the check above; the unique
        // index on User.email is what actually decides, so report it the same way.
        if (error instanceof Prisma.PrismaClientKnownRequestError && error.code === "P2002") {
            return NextResponse.json({ error: "User already exists." }, { status: 400 });
        }
        // Log the detail, return a generic message: the raw error text can
        // expose schema/driver internals to an unauthenticated caller.
        console.error("[Register] Failed:", error);
        return NextResponse.json({ error: "Could not create account." }, { status: 500 });
    }
}
