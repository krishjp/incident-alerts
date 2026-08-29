import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { encryptPhone, decryptPhone } from "@/lib/crypto";
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

    const json = await req.json();
    const updatedUser = await prisma.user.update({
        where: { email: session.user.email },
        data: { phone: json.phone ? encryptPhone(json.phone) : null }
    });
    return NextResponse.json({ phone: updatedUser.phone ? decryptPhone(updatedUser.phone) : "" });
}
