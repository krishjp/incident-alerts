#!/bin/sh
# Build command for Vercel (frontend/vercel.json -> `npm run vercel-build`).
set -eu

# `prisma migrate deploy` needs a direct (non-pooled) connection in DIRECT_URL.
# Vercel's Neon integration doesn't set that name; it injects the unpooled
# string as DATABASE_URL_UNPOOLED (older integrations: POSTGRES_URL_NON_POOLING).
# Deriving it here, rather than pasting DIRECT_URL into Vercel by hand, keeps
# migrations pointed at the same database the deployment actually uses: when
# Neon gives preview deployments their own database branch, it overrides these
# per-preview, whereas a hand-set DIRECT_URL would migrate production instead.
DIRECT_URL="${DIRECT_URL:-${DATABASE_URL_UNPOOLED:-${POSTGRES_URL_NON_POOLING:-}}}"
if [ -z "$DIRECT_URL" ]; then
    echo "vercel-build: no direct database URL. Connect Neon to this Vercel environment" >&2
    echo "(it provides DATABASE_URL_UNPOOLED) or set DIRECT_URL." >&2
    exit 1
fi
export DIRECT_URL

prisma generate
prisma migrate deploy
next build
