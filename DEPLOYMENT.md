# Deployment

How this system goes to production, and why each piece is where it is.

## Topology

```
                    ┌──────────────────────────┐
   browser ────────▶│  Vercel — Next.js app    │  auth, subscription CRUD
                    │  (frontend/)             │  polyline generation
                    └────────────┬─────────────┘
                                 │ Prisma (pooled)
                                 ▼
                    ┌──────────────────────────┐
                    │  Managed Postgres        │  the ONLY link between halves
                    └────────────▲─────────────┘
                                 │ SQLAlchemy (pooled)
                    ┌────────────┴─────────────┐
   Caltrans KML ───▶│  Cloud Run — worker      │──▶ Twilio SMS
   Gemini       ───▶│  (backend/, always-on)   │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  Managed Redis (Upstash) │  summary cache + durable
                    └────────────▲─────────────┘  notification queue
                                 │ REST
                    (Vercel: API rate limiting)
```

The two runtimes never call each other. They share a database, and that is the
entire integration surface — which is why the schema lives in two hand-kept
places (`frontend/prisma/schema.prisma` and `backend/models.py`) and why the
migrations CI job exists.

## Why the worker is a Cloud Run *service*, not a Job or a Lambda

The worker is a `while True` loop, not a request handler. That rules out
anything request-triggered by default, and it constrains Cloud Run specifically:

- `--min-instances=1` — without it the service scales to zero and stops polling.
- `--no-cpu-throttling` — Cloud Run throttles CPU to near-zero between requests
  by default. A loop that only sleeps and polls receives no requests, so with
  throttling on it makes almost no progress and alerts silently stop.
- `--max-instances=1` — two instances would both match every subscription
  against every incident. They wouldn't *duplicate* SMS (the `NotifiedIncident`
  fingerprint row is the de-dupe key), but they would race on it and waste
  Gemini calls. Horizontal scale-out needs the distributed queue described at
  the bottom of `HANDOFF.md` first.

The container listens on `$PORT` purely to satisfy Cloud Run's contract and to
expose `/healthz` (`backend/health.py`), which reports **stalled** — not merely
"process alive" — when the loop stops completing cycles.

If you would rather not pay for an always-on instance, the alternative is
already supported: set `RUN_ONCE=true` and deploy as a **Cloud Run Job** on a
Cloud Scheduler trigger every minute. This is why the notification queue is
Redis-backed — under `RUN_ONCE` the process exits between cycles, and in-memory
retries would be lost every minute.

---

## 1. Database

Any Postgres 15 the two runtimes can both reach. Neon is the smoothest fit for a
Vercel frontend (serverless driver, connection pooling, generous free tier);
Cloud SQL is the choice if you want everything inside the existing
`incident-alerts-routes` GCP project.

Whichever you pick, you need **two connection strings**:

| Variable | Used by | Should be |
|---|---|---|
| `DATABASE_URL` | app runtime | the **pooled** endpoint |
| `DIRECT_URL` | `prisma migrate` only | the **direct** endpoint |

Migrations run DDL and take advisory locks, which transaction-mode poolers
(PgBouncer, Neon's `-pooler` host, Supabase's port 6543) cannot carry.

Append connection caps to the runtime URL:

```
postgresql://user:pass@host/incidentsdb?sslmode=require&connection_limit=5&pool_timeout=20
```

**Budget your connections.** Every Vercel serverless instance opens its own
Prisma pool, and the worker opens `DB_POOL_SIZE + DB_MAX_OVERFLOW` (default 10)
more. Keep the total under the instance's `max_connections`, and prefer a pooled
endpoint over raising the cap.

### Apply the schema

The repository now carries a real migration history
(`frontend/prisma/migrations/`), so production never needs `prisma db push`:

```bash
cd frontend
DIRECT_URL="<direct connection string>" npx prisma migrate deploy
```

`npm run vercel-build` does this automatically on every Vercel deploy.

> When you change `schema.prisma`, generate a migration (`npx prisma migrate dev
> --name <what-changed>`) **and** update `backend/models.py` by hand. Nothing
> links the two — the `migrations` CI job catches an un-migrated schema edit,
> but nothing catches SQLAlchemy drift.

---

## 2. Redis

One instance serves both halves, for different jobs:

- **Worker** (`REDIS_URL`, a `rediss://` connection string) — caches Gemini
  summaries for 24h and makes the notification queue durable, so an alert
  enqueued moments before a redeploy is still delivered afterwards.
- **Frontend** (`UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`) — backs
  API rate limiting. Upstash is used over the REST API here because Vercel's
  serverless runtime cannot hold a TCP connection pool between invocations.

Upstash covers both protocols from one database, which is why it's the default
recommendation. Memorystore works for the worker but requires a VPC connector
and can't serve Vercel at all.

Both are optional and both degrade gracefully — but *do* configure the frontend
one: without it, rate limiting falls back to per-instance in-memory counters,
which concurrent serverless instances bypass trivially.

---

## 3. Frontend on Vercel

1. **New Project** → import the repo → set **Root Directory** to `frontend`.
   `frontend/vercel.json` supplies the rest (build command, install command).
2. Set environment variables (Production *and* Preview):

   | Variable | Notes |
   |---|---|
   | `DATABASE_URL` | pooled endpoint |
   | `DIRECT_URL` | direct endpoint, for migrations |
   | `NEXTAUTH_SECRET` | `openssl rand -hex 32` |
   | `NEXTAUTH_URL` | exact deployed origin, e.g. `https://incident-alerts.vercel.app` |
   | `PHONE_ENCRYPTION_KEY` | `openssl rand -hex 32` — **must equal the worker's** |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | optional, for Google login |
   | `GOOGLE_MAPS_API_KEY` | optional; falls back to Nominatim/OSRM |
   | `UPSTASH_REDIS_REST_URL` / `_TOKEN` | rate limiting |
   | `OSRM_URL` / `NOMINATIM_URL` | only if self-hosting the routing stack |

3. If you use Google login, add `https://<domain>/api/auth/callback/google` to
   the OAuth client's authorized redirect URIs.

`PHONE_ENCRYPTION_KEY` mismatch is the failure mode to watch for: the frontend
will happily encrypt phone numbers the worker cannot decrypt, and the worker
silently treats an undecryptable value as plaintext — so SMS goes nowhere and
nothing errors. Set it once, from one generated value, in both places.

---

## 4. Worker on Cloud Run

One-time setup in the existing GCP project:

```bash
PROJECT=incident-alerts-routes
REGION=us-west2

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com

gcloud artifacts repositories create incident-alerts \
    --repository-format=docker --location="$REGION"
```

Store runtime secrets in Secret Manager (the names match
`.github/workflows/deploy-worker.yml`):

```bash
for pair in \
  "incident-alerts-database-url" \
  "incident-alerts-phone-key" \
  "incident-alerts-redis-url" \
  "incident-alerts-gemini-key" \
  "incident-alerts-twilio-sid" \
  "incident-alerts-twilio-token" \
  "incident-alerts-twilio-number"
do
  gcloud secrets create "$pair" --replication-policy=automatic
done

# then, per secret:
printf '%s' "<value>" | gcloud secrets versions add incident-alerts-database-url --data-file=-
```

Grant the Cloud Run runtime service account `roles/secretmanager.secretAccessor`
(and `roles/cloudsql.client` if you're on Cloud SQL).

### Deploying

Pushes to `main` that touch `backend/**` trigger
`.github/workflows/deploy-worker.yml`. It authenticates with **Workload Identity
Federation**, so no GCP key ever lives in this repository. Configure these
GitHub *repository variables* (Settings → Secrets and variables → Actions →
Variables):

`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SERVICE_ACCOUNT`,
`GCP_WORKLOAD_IDENTITY_PROVIDER`, and optionally `CLOUD_SQL_INSTANCE`.

Manual deploy, if you'd rather not wire CI up yet:

```bash
gcloud run deploy incident-alerts-worker \
  --source ./backend --region "$REGION" \
  --no-allow-unauthenticated \
  --min-instances=1 --max-instances=1 --no-cpu-throttling \
  --set-env-vars=ENVIRONMENT=production \
  --set-secrets=DATABASE_URL=incident-alerts-database-url:latest,PHONE_ENCRYPTION_KEY=incident-alerts-phone-key:latest
```

`ENVIRONMENT=production` is not cosmetic: it activates the extra checks in
`backend/config.py` that refuse to start on default `postgres/postgres`
credentials, a `localhost` database URL, or half-configured Twilio credentials.

### Verifying

```bash
gcloud run services logs read incident-alerts-worker --region "$REGION" --limit 50
```

A healthy start prints the redacted config block from `settings.describe()`,
then `Checking active subscriptions...` once per `POLL_INTERVAL_SECONDS`.
`/healthz` returns 503 once the loop misses three consecutive cycles.

---

## 5. Twilio (when you're ready)

SMS dispatch is already implemented and inert: with `TWILIO_ACCOUNT_SID` /
`TWILIO_AUTH_TOKEN` unset or left as placeholders, every alert is console-logged
instead of sent (`backend/notification_queue.py`). To switch it on, add the real
values to Secret Manager and redeploy — no code change.

Before going live: pay-as-you-go accounts can only text **verified** numbers
until the account is upgraded, and US A2P 10DLC registration is required for
application-initiated SMS to US numbers. Until both are done, delivery failures
land in the queue's Dead Letter Queue rather than reaching users.

---

## Rollback

- **Frontend** — Vercel dashboard → Deployments → *Promote to Production* on the
  previous build. Note that a rollback does **not** revert a migration; write
  migrations to be backwards-compatible with the previous release.
- **Worker** — redeploy a previous image tag (they're tagged by commit SHA):

  ```bash
  gcloud run deploy incident-alerts-worker \
    --image "$REGION-docker.pkg.dev/$PROJECT/incident-alerts/worker:<sha>" \
    --region "$REGION"
  ```

## Known gaps before this carries real users

Tracked in `HANDOFF.md`; the ones that matter most at deploy time:

- **Single worker instance.** Scale-out needs the distributed queue (Celery /
  Redis Streams) before `--max-instances` can rise above 1.
- **Public routing services.** Nominatim and the OSRM demo server are
  rate-limited and SLA-free. The `RouteCache` table plus the 1 req/s throttle
  keep normal usage well inside their limits, but a self-hosted OSRM (or a
  Google Maps key) is the real answer for production traffic.
- **No alerting on the worker itself.** `/healthz` reports a stalled loop, but
  nothing pages anyone. Add a Cloud Monitoring uptime check against it.
