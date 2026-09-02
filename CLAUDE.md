# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Full-stack traffic incident notification system. A Next.js frontend lets users manage commute route
subscriptions; a standalone Python worker polls the Caltrans QuickMap KML feed, matches incidents against
subscribed routes, and dispatches SMS alerts. The two halves are **not** in-process coupled — they only
communicate through the shared PostgreSQL database.

## Commands

### Infra (run first)
```bash
docker compose up -d        # Postgres on host port 5433, Redis on host port 6380 (mapped to container 6379)
```

### Frontend (`frontend/`)
```bash
npm install
npx prisma migrate deploy   # apply prisma/migrations (NOT `db push` — see below)
npm run dev                 # Next.js dev server, http://localhost:3000
npm run build
npm run lint
npm run typecheck
```

### Backend (`backend/`, managed with `uv`)
```bash
uv venv
uv sync
uv run python main.py       # long-lived polling worker (60s loop) — run as a separate process from the frontend
RUN_ONCE=true uv run python main.py   # single poll pass, then exit

uv run pytest                                        # full suite
uv run pytest tests/test_caltrans_client.py           # one file
uv run pytest tests/test_routes.py::TestClassName::test_name  # one test
uv run pytest -m "not network and not integration and not slow"  # skip tests needing live network/external services
```
Markers (`network`, `integration`, `slow`, declared in `pyproject.toml`) are not auto-skipped — pass `-m` explicitly
if you want to avoid hitting live external services (Caltrans, Nominatim/OSRM, Gemini).

## Architecture

### Two independent runtimes, one database
- `frontend/` (Next.js App Router) owns user auth, route subscription CRUD, and writes to Postgres via Prisma
  (`frontend/prisma/schema.prisma`).
- `backend/` (`main.py`) is a plain `while True: ... sleep(POLL_INTERVAL_SECONDS)` loop with **no HTTP API** —
  it reads the same Postgres tables directly via SQLAlchemy (`backend/models.py`). It does serve one endpoint,
  `/healthz` on `$PORT` (`backend/health.py`), purely to satisfy container-platform liveness probes; that
  endpoint reports 503 when the loop stalls, not merely when the process dies.
- **The SQLAlchemy models in `backend/models.py` are hand-maintained to mirror `frontend/prisma/schema.prisma`**
  (table names use Prisma's PascalCase, e.g. `"RouteSubscription"`). There is no codegen link between them —
  when you change one schema, update the other by hand.
- The database schema is managed by a **Prisma migration history** (`frontend/prisma/migrations/`), not
  `db push`. After editing `schema.prisma`, run `npx prisma migrate dev --name <what-changed>`; CI fails on
  a schema edit with no corresponding migration. `directUrl`/`DIRECT_URL` must be set (it's what migrations
  connect through) — locally it's just a copy of `DATABASE_URL`.

### Configuration
- Both halves validate their environment at startup and refuse to run on bad config:
  `backend/config.py` (pydantic-settings; import `settings` rather than reading `os.getenv` in new code) and
  `frontend/src/lib/env.ts`. Setting `ENVIRONMENT` to anything but development/test turns on extra backend
  checks (no default `postgres/postgres` credentials, no `localhost` database, no half-configured Twilio).
- `frontend/src/lib/env.ts` deliberately **skips validation during `next build`** (`NEXT_PHASE`): Next.js
  imports every route module to collect page data, so validating there would make builds require production
  runtime secrets.

### Worker loop (`backend/main.py: check_and_notify`)
1. `models.get_active_subscriptions()` — pulls `RouteSubscription` rows with `isActive=True` whose
   `startTime`/`endTime` window (PST) contains the current time (handles cross-midnight windows).
2. The full statewide Caltrans feed is fetched once per loop iteration (`caltrans_client.fetch_caltrans_incidents()`,
   no area filter) — not per subscription or per `area` value. `RouteSubscription.area` is a user-facing label only;
   it does not gate matching, since a route can cross CHP-area/county boundaries and dispatch station is unpredictable.
3. Each incident is matched against a subscription's route via `route_utils.is_within_range_pure`: an O(1)
   bounding-box pre-filter over the decoded polyline, then exact Haversine distance to every route point
   (default 5-mile buffer) — this spatial check is the sole gate on relevance. If the incident has no lat/lon,
   falls back to a naive origin/destination substring match against the incident location text.
4. Matches are de-duplicated/updated via a fingerprint stored in `NotifiedIncident` (`id = "{subId}_{incidentNumber}"`,
   `state` = stringified incident details) — a changed `state` on an already-notified incident triggers an
   "UPDATE" alert instead of being skipped. After matching, each subscription's previously-notified incidents
   that no longer appear among the current matches (dropped from the feed or moved out of range) get a
   one-time "Resolved" alert and `state` is set to the sentinel `"RESOLVED"`, so a user is only ever re-alerted
   for a genuine content change or a resolution — never for the same unchanged, still-open incident.
5. Incident summaries for SMS text are generated by Gemini (`gemini-2.5-flash`) and cached through
   `cache_handler.global_incident_cache` (Redis with 24h TTL, falling back transparently to an in-memory dict if
   Redis is unreachable) to avoid duplicate LLM calls for the same incident content.
6. Outbound SMS isn't sent inline — it's handed to `notification_queue.global_notification_queue.enqueue(...)`
   and only actually dispatched when `process_queue()` runs at the end of the loop iteration. The queue does
   exponential backoff retries (`backoff_factor * 2^(attempts-1)`) and moves tasks to a Dead Letter Queue after
   `max_retries`; DLQ tasks need explicit `retry_dlq_task()` to re-enter the pending queue.
   Pending and DLQ tasks are mirrored into Redis (`TaskStore`) and restored on startup, so undelivered alerts
   survive a restart. Persistence is **opt-in per instance** (`NotificationQueue(persist=True)`, set only on the
   global singleton) so tests and ad-hoc instances never inherit a developer's local Redis state.

### Route polyline generation happens in two unrelated places
- The frontend generates the polyline at subscription-creation time
  (`frontend/src/app/api/subscriptions/route.ts` → `src/lib/route-cache.ts`), calling the legacy Directions API
  (`maps.googleapis.com/maps/api/directions/json`) with an API key (`GOOGLE_MAPS_API_KEY`, restricted to the
  Directions API) if set, otherwise falling back to free Nominatim geocoding + OSRM routing
  (`frontend/src/lib/routing.ts`) for the actual origin/destination.
  Both paths go through the `RouteCache` table first (keyed by a normalized origin/destination/provider hash),
  and Nominatim calls are serialized through a 1 req/s gate with retry/backoff — its usage policy is a hard
  limit, and exceeding it blocks the egress IP rather than just throttling.
- `backend/route_generator.py` (Nominatim geocoding + OSRM routing) exists as a separate, self-contained
  utility but is **not called from `main.py`** — it's currently only exercised by tests. Don't assume it's part
  of the live request path.
- `backend/scrapper.py` is a deprecated shim that forwards to `caltrans_client.fetch_caltrans_incidents()`
  with a `DeprecationWarning`; new code should call `caltrans_client` directly.

### Auth
NextAuth (`frontend/src/lib/auth.ts`) with JWT sessions, supporting both Google OAuth and credentials
(bcrypt-hashed password) login, backed by the Prisma adapter against the same `User`/`Account`/`Session` tables.
`src/types/next-auth.d.ts` must keep its `import "next-auth"` line: without an import, its `declare module`
block *replaces* next-auth's types instead of augmenting them, and every `getServerSession` call stops typechecking.

### API authorization
Subscription routes scope every mutation by `userId` (`deleteMany`/`updateMany` with `{ id, userId }`, not
`delete({ where: { id } })`). Keep new endpoints to that pattern — the unscoped form previously let any signed-in
user delete another account's route by id.

### Rate limiting
`frontend/src/lib/rate-limit.ts` fronts subscription creation, registration, and credentials login. It uses
Upstash Redis over REST when `UPSTASH_REDIS_REST_URL`/`_TOKEN` are set and per-instance in-memory counters
otherwise, and **fails open** on limiter errors. The in-memory fallback is per serverless instance, so
production deploys should configure Upstash.

### Ports/env gotcha
`docker-compose.yml` publishes Redis on host port **6380** (container port 6379 is untouched). Set
`REDIS_PORT=6380` in `backend/.env` for a host-side worker run; inside the compose network the worker uses
6379. If cache connections silently fall back to in-memory mode, check this first. In deployed environments,
prefer `REDIS_URL` (a single `rediss://` string), which takes precedence over host/port.

### Deployment
See `DEPLOYMENT.md`. Frontend → Vercel; worker → Cloud Run, which needs `--min-instances=1`,
`--no-cpu-throttling` (a polling loop receives no requests, so throttled CPU stops it making progress) and
`--max-instances=1` (multiple instances would race on the `NotifiedIncident` fingerprint row).
