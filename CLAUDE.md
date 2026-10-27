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
docker compose up -d        # Postgres on host port 5434, Redis on host port 6381 (mapped to container 6379)
```

### Frontend (`frontend/`)
```bash
npm install
npx prisma migrate deploy   # apply prisma/migrations (NOT `db push` — see below)
npm run dev                 # Next.js dev server, http://localhost:3000
npm run build
npm run lint
npm run typecheck
npm run seed:demo           # seeds 5 demo accounts at different setup stages — see below
```

### Backend (`backend/`, managed with `uv`)
```bash
uv venv
uv sync
uv run python main.py       # single poll pass, then exit — there is no long-lived loop mode
./scripts/run-worker-loop.sh   # (or .ps1) repeats that on an interval, imitating Cloud Scheduler locally

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
- `backend/` (`main.py`) runs a single `check_and_notify()` pass and exits — there is no long-lived loop mode
  and **no HTTP API**. It reads the same Postgres tables directly via SQLAlchemy (`backend/models.py`).
  Something external calls it repeatedly: Cloud Scheduler invoking a Cloud Run Job in production, or
  `scripts/run-worker-loop.sh`/`.ps1` (`docker compose run --rm worker` on a timer) locally.
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

### Worker pass (`backend/main.py: check_and_notify`)
1. `models.get_active_subscriptions()` — pulls `RouteSubscription` rows with `isActive=True` whose
   `startTime`/`endTime` window (PST) contains the current time (handles cross-midnight windows).
2. The full statewide Caltrans feed is fetched once per pass (`caltrans_client.fetch_caltrans_incidents()`,
   no area filter) — not per subscription or per `area` value. `RouteSubscription.area` is a user-facing label only;
   it does not gate matching, since a route can cross CHP-area/county boundaries and dispatch station is unpredictable.
3. Each incident is matched against a subscription's route via `route_utils.is_within_range_pure`: an O(1)
   bounding-box pre-filter over the decoded polyline, then exact Haversine distance to every route point
   (default 3-mile buffer, `MATCH_RADIUS_MILES`) — this spatial check is the sole gate on relevance. If the incident has no lat/lon,
   falls back to a naive origin/destination substring match against the incident location text.
4. Matches are de-duplicated/updated via a fingerprint stored in `NotifiedIncident` (`id = "{subId}_{incidentNumber}"`,
   `state` = stringified incident details) — a changed `state` on an already-notified incident triggers an
   "UPDATE" alert instead of being skipped. After matching, each subscription's previously-notified incidents
   that no longer appear among the current matches (dropped from the feed or moved out of range) get a
   one-time "Resolved" alert and `state` is set to the sentinel `"RESOLVED"`, so a user is only ever re-alerted
   for a genuine content change or a resolution — never for the same unchanged, still-open incident.
   A subscription outside its time window is never polled, so its open incidents can't be known to have
   cleared: `mark_stale_incidents` (run first each pass) prefixes their `state` with `STALE:` and logs a
   `STALE` message (log only, never SMS) instead of leaving them looking active. If the incident is still on the
   board the next time the route is polled, the prefix is dropped, an `ACTIVE` log entry is written, and it is
   treated as an ordinary unchanged/updated incident; if it's gone it simply stays stale — no "Resolved" SMS.
   On top of that, `alert_dedupe.is_similar_summary` suppresses SMS whose summary is only a rewording of one
   already sent. A flip in injury/fatal/closed/cleared/fire/hazmat facts (regex) always sends; word-overlap ≥
   `SUMMARY_SIMILARITY_THRESHOLD` suppresses with no model call; only below that is a Vercel AI Gateway decision
   model (`DEDUPE_MODEL`, default `convaiinnovations/laya`, via `POST /v1/evaluate`) asked, suppressing at
   probability ≥ `DEDUPE_MIN_PROBABILITY`. No `AI_GATEWAY_API_KEY`, a failed call, or a 401/402/403/429 (which
   disables the model for the rest of the pass; Laya is limited to 5 req/min) means send. Model answers are
   cached in Redis for 24h by unordered summary pair (`dedupe:decision:*`), so a pair is asked once across all
   routes, users and passes; failures aren't stored. Comparisons: an UPDATE is compared to the *sent* summary (cache key = stored `state`, which is left at the sent
   version), and within a pass to everything already queued to that phone. An incident suppressed as a
   near-duplicate of another number is stored as `"DUPLICATE:" + state` and stays silent for life, including
   its resolution. The previous-summary lookup needs the Redis cache; with the in-memory fallback it misses
   and the update is sent.
5. Incident summaries for SMS text are generated by Gemini (`gemini-2.5-flash`) and cached through
   `cache_handler.global_incident_cache` (Redis with 24h TTL, falling back transparently to an in-memory dict if
   Redis is unreachable) to avoid duplicate LLM calls for the same incident content.
6. Outbound SMS isn't sent inline — it's handed to `notification_queue.global_notification_queue.enqueue(...)`
   and only actually dispatched when `process_queue()` runs at the end of the pass. The queue does
   exponential backoff retries (`backoff_factor * 2^(attempts-1)`) and moves tasks to a Dead Letter Queue after
   `max_retries`; DLQ tasks need explicit `retry_dlq_task()` to re-enter the pending queue.
   Pending and DLQ tasks are mirrored into Redis (`TaskStore`) and restored on the next invocation, so
   undelivered alerts survive the process exiting between passes. Persistence is **opt-in per instance**
   (`NotificationQueue(persist=True)`, set only on the global singleton) so tests and ad-hoc instances never
   inherit a developer's local Redis state.
   Every enqueued alert is also written to `AlertMessage` (same session as the fingerprint, so a rollback
   removes it too) with its route label, kind, and how it matched (`spatial` + distance, or `text` fallback).
   The dashboard's **Live Messages** page (`/dashboard/messages` → `GET /api/messages?since=`) polls it as a
   live tail, the stand-in SMS inbox until Twilio is configured. Suppressed near-duplicates aren't logged.
   A phone number is only needed for SMS: users without one are still matched, and their alerts are logged
   with `delivery = "none"` and never queued.
   After each pass `prune_message_log()` deletes messages older than `ALERT_LOG_MAX_AGE_HOURS` (48).

### Route polyline generation happens in two unrelated places
- The frontend generates the polyline at subscription-creation time
  (`frontend/src/app/api/subscriptions/route.ts` → `src/lib/route-cache.ts`), calling the legacy Directions API
  (`maps.googleapis.com/maps/api/directions/json`) with an API key (`GOOGLE_MAPS_API_KEY`, restricted to the
  Directions API) if set, otherwise falling back to free Nominatim geocoding + OSRM routing
  (`frontend/src/lib/routing.ts`) for the actual origin/destination.
  Endpoints are resolved to coordinates *before* routing: the dashboard's address autocomplete
  (`/api/geocode`, backed by Photon because Nominatim's policy forbids autocomplete) sends the picked
  suggestion's lat/lon, and hand-typed text is geocoded with Nominatim bounded to North America.
  `src/lib/geo.ts: validateRoute` then rejects the route unless both points are in North America and the
  polyline starts/ends within 3 miles of them without an absurd detour. The matched place names are stored in
  `originDisplayName`/`destinationDisplayName` and shown on the dashboard.
  Both paths go through the `RouteCache` table first (keyed by a hash of the resolved coordinates + provider),
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
Upstash Redis over REST when `UPSTASH_REDIS_REST_URL`/`_TOKEN` (or Vercel's `KV_REST_API_URL`/`_TOKEN`) are set and per-instance in-memory counters
otherwise, and **fails open** on limiter errors. The in-memory fallback is per serverless instance, so
production deploys should configure Upstash.

### Demo accounts
`frontend/scripts/seed-demo-accounts.js` (`npm run seed:demo`) seeds 5 accounts spanning the setup funnel —
no phone/no route, route-but-no-phone, phone+route paused, phone+route active, and a multi-route power
user — all sharing password `DemoPass123!`. It's idempotent (upserts + replaces subscriptions rather than
duplicating on re-run) and refuses to run unless `ENVIRONMENT` is development/dev/test/local/unset. The
"active" accounts copy the polyline off an existing Torrance→Huntington Beach subscription in the dev DB
(rather than calling Nominatim/OSRM) so they line up with `backend/fixtures/torrance_hb_405_test.kml` for a
live worker-run demo.

### Ports/env gotchas
- `docker-compose.yml` publishes Redis on host port **6381** (container port 6379 is untouched). Set
  `REDIS_PORT=6381` in `backend/.env` for a host-side worker run; inside the compose network the worker uses
  6379. If cache connections silently fall back to in-memory mode, check this first. In deployed environments,
  prefer `REDIS_URL` (a single `rediss://` string), which takes precedence over host/port.
- `docker compose restart <service>` does **not** reread that service's `env_file` — it reuses the
  environment captured at container creation. After editing `backend/.env`/`frontend/.env`, use
  `docker compose up -d --force-recreate <service>` to pick up the change.
- `docker compose up -d` also builds and starts a **production-mode** (`NODE_ENV=production`) `frontend`
  container on port 3000 — it isn't just datastores. Stop it (`docker compose stop frontend`) before running
  `npm run dev`, which binds the same port for hot-reload development.
- `frontend/src/lib/env.ts` rejects `NEXTAUTH_SECRET`/`PHONE_ENCRYPTION_KEY` values on its known-weak-placeholder
  list (e.g. `"super-secret-key"`) unconditionally, not just in production — every request 500s until a real
  `openssl rand -hex 32` value replaces it.
- `frontend/Dockerfile`'s `deps` stage must `COPY prisma ./prisma` **before** `RUN npm ci`: `package.json`'s
  `postinstall` runs `prisma generate`, which needs the schema present at install time, not just later when
  the builder stage does `COPY . .`.

### Deployment
See `DEPLOYMENT.md`. Frontend → Vercel; datastores → Neon (Postgres) + Upstash (Redis); worker → a **Cloud Run
Job** run once a minute by Cloud Scheduler, rather than an always-on service — the worker exits between passes,
and a service would bill an always-allocated vCPU for the idle time in between. Locally,
`scripts/run-worker-loop.sh`/`.ps1` imitate the same schedule by looping `docker compose run --rm worker`.

The worker **fails closed on Redis and Postgres**: `main.check_dependencies()` runs before the pass (exit 1, nothing
fetched or sent) and again in `dispatch_queue()` right before SMS go out (exit 1, queued alerts held in Redis and
sent by the first run after recovery). `single_run_lock` raises `DependencyUnavailable` instead of running unlocked,
and the worker's queue singleton uses `TaskStore(strict=True)`, so a failed Redis write rolls back that
subscription's `NotifiedIncident` changes and withdraws its queued alerts rather than marking them sent. Only the
summary cache still falls back to memory. Locally, `docker compose run` restarts stopped dependencies — use
`--no-deps` to reproduce an outage.

Because the process exits between passes, three things carry state across invocations and must stay that way:
the Redis-backed notification queue (pending retries), the Redis summary cache (avoids re-billing Gemini), and
`single_run_lock()` in `redis_client.py`. That lock matters because Cloud Scheduler does not wait for the
previous execution — two concurrent runs would race on the `NotifiedIncident` fingerprint row. Keep
`--task-timeout` and `RUN_LOCK_TTL_SECONDS` aligned. Only ever run one worker at a time until the distributed
queue in `HANDOFF.md` exists.
