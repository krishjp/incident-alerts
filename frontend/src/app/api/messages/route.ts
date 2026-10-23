import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { NextResponse } from "next/server";

const MAX_MESSAGES = 200;

async function requireUser() {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) return null;
    return prisma.user.findUnique({ where: { email: String(session.user.email) } });
}

// Alerts the worker queued for the signed-in user, newest first. The dashboard's
// live tail polls with ?since=<createdAt of the newest row it has>; the bound is
// inclusive because rows from one worker pass can share a millisecond, and the
// client de-duplicates by id.
export async function GET(req: Request) {
    const user = await requireUser();
    if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const sinceParam = new URL(req.url).searchParams.get("since");
    const since = sinceParam ? new Date(sinceParam) : null;
    if (since && Number.isNaN(since.getTime())) {
        return NextResponse.json({ error: "Invalid since timestamp." }, { status: 400 });
    }

    const messages = await prisma.alertMessage.findMany({
        where: { userId: user.id, ...(since ? { createdAt: { gte: since } } : {}) },
        orderBy: { createdAt: "desc" },
        take: MAX_MESSAGES,
    });
    return NextResponse.json(messages);
}
