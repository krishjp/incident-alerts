import { PrismaClient } from "@prisma/client"
import { assertValidEnv } from "./env"

assertValidEnv()

const globalForPrisma = global as unknown as { prisma: PrismaClient }

// Query logging is development-only: in production it writes every statement
// (including parameter values from user rows) to the platform log stream.
//
// Connection pool size is set on the DATABASE_URL itself via Prisma's
// `connection_limit` parameter rather than in code — see DEPLOYMENT.md. On
// serverless each instance opens its own pool, so that value must stay small
// enough that instances + the Python worker fit inside the database's
// max_connections.
export const prisma =
  globalForPrisma.prisma ||
  new PrismaClient({
    log: process.env.NODE_ENV === "production" ? ["error", "warn"] : ["query", "error", "warn"],
  })

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma
