import type { Adapter } from "next-auth/adapters";
import { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";
import { PrismaAdapter } from "@auth/prisma-adapter";
import { prisma } from "@/lib/prisma";
import { rateLimit } from "@/lib/rate-limit";
import { LOGIN_RATE_LIMITED, validateEmail, validateLoginPassword } from "@/lib/validation";
import bcrypt from "bcryptjs";

export const authOptions: NextAuthOptions = {
    // Cast: @auth/prisma-adapter targets the Auth.js v5 Adapter shape, which is
    // structurally compatible with next-auth v4's but not nominally assignable.
    adapter: PrismaAdapter(prisma) as unknown as Adapter,
    session: { strategy: "jwt" },
    pages: {
        signIn: '/login',
    },
    providers: [
        GoogleProvider({
            clientId: process.env.GOOGLE_CLIENT_ID || "dummy",
            clientSecret: process.env.GOOGLE_CLIENT_SECRET || "dummy",
        }),
        CredentialsProvider({
            name: "Credentials",
            credentials: {
                email: { label: "Email", type: "email", placeholder: "test@example.com" },
                password: { label: "Password", type: "password" }
            },
            async authorize(credentials) {
                if (!credentials?.email || !credentials?.password) return null;
                // Malformed input can't match an account; rejecting it here also
                // keeps oversized passwords away from bcrypt.
                if (validateEmail(credentials.email) || validateLoginPassword(credentials.password)) {
                    return null;
                }

                // Throttle per email address, so a stolen password list can't be
                // sprayed against one account. Fails open if the limiter is down.
                const limit = await rateLimit(
                    "auth:login",
                    credentials.email.trim().toLowerCase(),
                    { limit: 10, windowSeconds: 300 },
                );
                // Thrown (not null) so the login page can say "try again later"
                // instead of "invalid credentials" — next-auth passes the message
                // through as the signIn() error.
                if (!limit.allowed) throw new Error(LOGIN_RATE_LIMITED);

                // Registration stores emails lowercased; the exact-match lookup
                // first keeps any pre-existing mixed-case rows working.
                const user =
                    (await prisma.user.findUnique({ where: { email: credentials.email } })) ??
                    (await prisma.user.findUnique({
                        where: { email: credentials.email.trim().toLowerCase() },
                    }));
                if (!user || !user.password) return null;

                const isValid = await bcrypt.compare(credentials.password, user.password);
                if (!isValid) return null;

                return { id: user.id, email: user.email, name: user.name };
            }
        })
    ],
    callbacks: {
        session: ({ session, token }) => {
            if (token && session.user) {
                session.user.id = token.sub as string;
            }
            return session;
        }
    }
};
