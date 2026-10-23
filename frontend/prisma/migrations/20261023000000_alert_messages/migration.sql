-- CreateTable
CREATE TABLE "AlertMessage" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "subscriptionId" TEXT NOT NULL,
    "routeLabel" TEXT NOT NULL,
    "incidentNumber" TEXT NOT NULL,
    "kind" TEXT NOT NULL,
    "matchMethod" TEXT,
    "distanceMiles" DOUBLE PRECISION,
    "location" TEXT,
    "message" TEXT NOT NULL,
    "delivery" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AlertMessage_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "AlertMessage_userId_createdAt_idx" ON "AlertMessage"("userId", "createdAt");

-- AddForeignKey
ALTER TABLE "AlertMessage" ADD CONSTRAINT "AlertMessage_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

