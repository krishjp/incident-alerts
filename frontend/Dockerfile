FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# npm ci runs the postinstall `prisma generate` script, which needs the schema
# present before install — not just at the later COPY . . in the builder stage.
COPY prisma ./prisma
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npx prisma generate
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder /app/prisma ./prisma
COPY --from=builder /app/node_modules/.prisma ./node_modules/.prisma

USER nextjs
EXPOSE 3000
ENV PORT=3000
# The standalone server.js binds to $HOSTNAME, which Docker sets to the container
# id. Resolving that fails with EAI_AGAIN when the container restarts before
# Docker's DNS is ready (e.g. after Docker Desktop restarts), so bind to all
# interfaces instead of looking anything up.
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
