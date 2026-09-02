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
                    │  Neon — Postgres         │  the ONLY link between halves
                    └────────────▲─────────────┘
                                 │ SQLAlchemy (pooled)
   Cloud Scheduler ─┐ ┌──────────┴─────────────┐
   (every minute)   └▶│  Cloud Run Job — worker │──▶ Twilio SMS
   Caltrans KML ───▶ │  (backend/, RUN_ONCE)   │
   Gemini       ───▶ └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  Upstash — Redis         │  summary cache, durable
                    └────────────▲─────────────┘  queue, run lock
                                 │ REST
                    (Vercel: API rate limiting)
```

The two runtimes never call each other. They share a database, and that is the
entire integration surface — which is why the schema lives in two hand-kept
places (`frontend/prisma/schema.prisma` and `backend/models.py`) and why the
migrations CI job exists.

## Why the worker is a Cloud Run *Job*, not an always-on service

The worker sleeps for most of every poll interval. Running it as a Cloud Run
service means `--min-instances=1 --no-cpu-throttling` — an always-allocated
vCPU, billed continuously, for a process that does a few seconds of real work a
minute. Running it as a **Job** triggered by Cloud Scheduler bills only the
seconds it actually runs, which at this workload is a rounding error by
comparison.

`RUN_ONCE=true` (`backend/config.py`) is that shape: one `check_and_notify()`
pass, then exit. Three things make it safe:

- **The notification queue is Redis-backed.** The process dies between cycles,
  so an in-memory retry queue would drop every pending alert once a minute.
  Pending and dead-lettered tasks are restored on the next execution.
- **The Gemini summary cache is in Redis too**, so exiting doesn't throw away
  the cache and re-bill the same summaries.
- **A Redis lock prevents overlap.** Cloud Scheduler does not wait for the
  previous execution to finish. Two concurrent runs would both match every
  subscription and race on the `NotifiedIncident` fingerprint row — so
  `single_run_lock()` makes a run that finds the lock held exit 0 immediately.
  `--task-timeout` and `RUN_LOCK_TTL_SECONDS` should stay aligned (both 300s by
  default): the timeout caps a wedged execution, the TTL stops a dead one from
  wedging its successors.

The long-lived loop is still fully supported — leave `RUN_ONCE` unset and the
worker runs `while True` and serves `/healthz` (`backend/health.py`), which
reports **stalled** rather than merely "process alive". That's what
`docker compose up` uses locally, and what you'd deploy to a VM or to Render's
Background Worker. Under `RUN_ONCE` the health server is skipped: nothing probes
a task that lives for seconds, and a non-zero exit is the failure signal instead.

Either way, one worker at a time. Horizontal scale-out needs the distributed
queue described in `HANDOFF.md` first.

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

## 4. Worker as a Cloud Run Job

One-time setup in the existing GCP project:

```bash
PROJECT=incident-alerts-routes
REGION=us-west2

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com cloudscheduler.googleapis.com

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

### Deploying the Job

Pushes to `main` that touch `backend/**` trigger
`.github/workflows/deploy-worker.yml`. It authenticates with **Workload Identity
Federation**, so no GCP key ever lives in this repository. Configure these
GitHub *repository variables* (Settings → Secrets and variables → Actions →
Variables):

`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SERVICE_ACCOUNT`,
`GCP_WORKLOAD_IDENTITY_PROVIDER`, and optionally `CLOUD_SQL_INSTANCE`.

Manual deploy, if you'd rather not wire CI up yet:

```bash
gcloud run jobs deploy incident-alerts-worker \
  --source ./backend --region "$REGION" \
  --cpu=1 --memory=512Mi \
  --task-timeout=300s --max-retries=0 \
  --set-env-vars=ENVIRONMENT=production,RUN_ONCE=true,RUN_LOCK_TTL_SECONDS=300 \
  --set-secrets=DATABASE_URL=incident-alerts-database-url:latest,PHONE_ENCRYPTION_KEY=incident-alerts-phone-key:latest,REDIS_URL=incident-alerts-redis-url:latest
```

`ENVIRONMENT=production` is not cosmetic: it activates the extra checks in
`backend/config.py` that refuse to start on default `postgres/postgres`
credentials, a `localhost` database URL, or half-configured Twilio credentials.

`--max-retries=0` is deliberate: a failed cycle is picked up by the next
scheduled run a minute later, and per-alert retries are already handled by the
notification queue's backoff. Retrying the whole cycle just duplicates work.

### Scheduling it

```bash
# Service account Scheduler uses to invoke the Job.
gcloud iam service-accounts create incident-alerts-scheduler \
    --display-name="Invokes the incident-alerts worker job"

SCHEDULER_SA="incident-alerts-scheduler@$PROJECT.iam.gserviceaccount.com"

gcloud run jobs add-iam-policy-binding incident-alerts-worker \
    --region="$REGION" \
    --member="serviceAccount:$SCHEDULER_SA" \
    --role="roles/run.invoker"

gcloud scheduler jobs create http incident-alerts-worker-tick \
    --location="$REGION" \
    --schedule="* * * * *" \
    --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/incident-alerts-worker:run" \
    --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA"
```

`* * * * *` is once a minute, matching the old in-process loop. Cost scales
linearly with frequency and the Caltrans feed doesn't change second-to-second —
`*/5 * * * *` cuts the bill ~5x if a five-minute alert delay is acceptable.

### Verifying

```bash
# Run one cycle immediately and wait for it.
gcloud run jobs execute incident-alerts-worker --region "$REGION" --wait

# Recent executions and their exit status.
gcloud run jobs executions list --job=incident-alerts-worker --region "$REGION" --limit=5

# Logs from the most recent execution.
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=incident-alerts-worker' \
  --limit=50 --format='value(textPayload)'
```

A healthy execution prints the redacted config block from `settings.describe()`,
then `Checking active subscriptions...`, then exits 0. `Previous poll cycle
still running — skipping this execution.` is also a success: it means the run
lock did its job, and a *sustained* run of those means cycles are taking longer
than the schedule interval.

### If you'd rather run it long-lived

The `while True` loop is still supported and is what `docker compose` runs
locally. On a VM, or on a platform with a first-class background-worker type
(Render, Fly), leave `RUN_ONCE` unset, expose `PORT`, and point the platform's
health check at `/healthz` — it returns 503 once the loop misses three poll
intervals, which a bare process check would never catch.

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
  Redis Streams) before concurrent executions are safe; until then the run lock
  serializes them.
- **Public routing services.** Nominatim and the OSRM demo server are
  rate-limited and SLA-free. The `RouteCache` table plus the 1 req/s throttle
  keep normal usage well inside their limits, but a self-hosted OSRM (or a
  Google Maps key) is the real answer for production traffic.
- **No alerting on the worker itself.** `/healthz` reports a stalled loop, but
  nothing pages anyone. Add a Cloud Monitoring uptime check against it.
