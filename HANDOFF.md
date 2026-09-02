# Project Handoff Document: Incident Alerts 🚗⚠️

**Last Updated:** September 2, 2026

## 🎯 Project Goals
The goal of **Incident Alerts** is to provide real-time, automated traffic incident alerts to users based on their specific commute routes and active hours.

Key capabilities:
1. **Route Subscriptions**: Users configure specific routes (e.g., origin/destination/polyline), areas (e.g., "Los Angeles"), phone numbers, and time windows (e.g., `07:00` - `09:00`).
2. **Real-Time Caltrans API Client**: Python backend worker fetches live Caltrans QuickMap traffic feeds via fast lightweight XML/KML HTTP endpoints ([backend/caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/caltrans_client.py)), replacing legacy headless Selenium scraping.
3. **Spatial & Temporal Matching**: Evaluates live incident lat/lon coordinates against polyline route boundaries within the scheduled time windows using an $O(1)$ bounding box pre-filter and Haversine/geodesic distance checks.
4. **Redis-Backed AI Summary Caching**: Uses Redis ([backend/cache_handler.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/cache_handler.py)) with 24-hour TTL expiration (and fallback in-memory dictionary) to eliminate redundant Gemini AI calls for identical incidents across worker nodes.
5. **Asynchronous Notification Queue with Retries & DLQ**: Enqueues outbound SMS alerts to an asynchronous queue ([backend/notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/notification_queue.py)) with exponential backoff retries and Dead Letter Queue (DLQ) isolation for failed dispatches.

---

## ✅ Completed Tasks

- [x] **Project Structure & Architecture**: Established full-stack structure with Next.js frontend, Python backend worker, PostgreSQL database, and Redis cache.
- [x] **Database & Infrastructure**:
  - `docker-compose.yml` updated with PostgreSQL (port `5433`) and Redis (port `6379`).
  - `.env` files generated for both `frontend/` and `backend/`.
  - Prisma schema (`prisma/schema.prisma`) defined for Users, RouteSubscriptions, Accounts, Sessions, and NotifiedIncidents.
  - SQLAlchemy models (`backend/models.py`) aligned with Prisma schema tables.
- [x] **Caltrans API Client Handler ([backend/caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/caltrans_client.py))**:
  - Replaced legacy headless Selenium browser automation with a dedicated `CaltransAPIClient` fetching XML/KML feed data from `https://quickmap.dot.ca.gov/data/chp-only.kml`.
  - Reduced feed fetch & parsing time from 15+ seconds (with Chrome dependency) to **< 0.1 seconds** using native Python standard libraries (`urllib`, `xml.etree.ElementTree`, `re`).
  - Extracted 100% guaranteed latitude/longitude coordinates, incident IDs, title types, timestamped locations, area mappings, and raw dispatch logs.
- [x] **Redis Summary Cache Handler ([backend/cache_handler.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/cache_handler.py))**:
  - Implemented `IncidentCache` using Redis key-value storage with 24-hour TTL (`EXPIRE`), ensuring shared cache state across distributed workers and surviving process restarts.
  - Includes graceful fallback to in-memory caching when Redis is offline.
- [x] **Deprecation of Legacy Scraper ([backend/scrapper.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/scrapper.py))**:
  - Deprecated legacy scraping functions with a `DeprecationWarning` and fallback wrapper forwarding to `caltrans_client.fetch_caltrans_incidents()`.
- [x] **Asynchronous Notification Queue & Dead Letter Queue ([backend/notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/notification_queue.py))**:
  - Implemented decoupled `NotificationTask` queue replacing inline synchronous SMS sending in `main.py`.
  - Added exponential backoff retry scheduling (`backoff_factor * 2^(attempts-1)`).
  - Added Dead Letter Queue (DLQ) isolation for failed tasks exceeding `max_retries` with manual re-queueing (`retry_dlq_task()`).
- [x] **Worker & Spatial Evaluation Optimizations**:
  - Built [backend/route_generator.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/route_generator.py) using Nominatim OpenStreetMap geocoding and OSRM turn-by-turn routing.
  - Added $O(1)$ bounding box pre-filter (`get_bounding_box`) in [backend/route_utils.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/route_utils.py#L68-L86) for fast spatial rejection of distant incidents before running distance loops.
  - Incident fingerprint tracking via `NotifiedIncident` table to prevent duplicate notifications.
- [x] **Testing & Verification Suite**:
  - Expanded Pytest suite across five test modules ([backend/tests/test_cache_handler.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_cache_handler.py), [backend/tests/test_routes.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_routes.py), [backend/tests/test_caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_caltrans_client.py), [backend/tests/test_notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_notification_queue.py), [backend/tests/test_full_e2e.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_full_e2e.py)).
  - Verified 26 automated tests covering Redis cache set/get/hashing, bounding box fast rejection, summary caching, geocoded route matching, live feed fetching, retry backoff, and DLQ handling (**26 passed in 8.5s**).
- [x] **PII Encryption at Rest**:
  - `User.phone` is encrypted with AES-256-GCM via a shared `PHONE_ENCRYPTION_KEY` (`frontend/src/lib/crypto.ts` for writes, `backend/models.py` for reads); the key must match exactly between `frontend/.env` and `backend/.env`.
  - `frontend/src/lib/env.ts` fails fast on startup if required env vars are missing or `NEXTAUTH_SECRET`/`PHONE_ENCRYPTION_KEY` are weak/malformed.
- [x] **Google Maps Directions API Integration**:
  - `incident-alerts-routes` GCP project created, linked to billing account `019711-E766A9-AC72C0`, and moved under org `229395848094`.
  - Directions API enabled; `GOOGLE_MAPS_API_KEY` (restricted to `directions-backend.googleapis.com`) generated and set in `frontend/.env` for `frontend/src/app/api/subscriptions/route.ts`. Falls back to free Nominatim/OSRM routing if unset.
- [x] **Typed, Fail-Fast Backend Configuration ([backend/config.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/config.py))**:
  - `pydantic-settings` `Settings` model validates every worker env var at process start — mirroring `frontend/src/lib/env.ts` — and converts pydantic's traceback into a single readable `SystemExit`.
  - Rejects a malformed `PHONE_ENCRYPTION_KEY` (must be 64 hex chars), an unsupported `DATABASE_URL` scheme, and a sub-1s poll interval.
  - When `ENVIRONMENT` is anything but development/test, additionally rejects default `postgres/postgres` credentials, a `localhost` database URL, and half-configured Twilio credentials (a placeholder SID silently downgrades every alert to a console print).
  - `settings.describe()` logs a credential-redacted config summary at boot.
- [x] **Database Connection Pooling ([backend/models.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/models.py))**:
  - Explicit `pool_size` / `max_overflow` / `pool_timeout` / `pool_recycle` (env-tunable), plus `pool_pre_ping` so a connection dropped by a managed proxy while the worker slept isn't handed out dead.
  - Added a `session_scope()` context manager and reworked `check_and_notify` to take **one session per subscription** instead of one per matched incident.
  - Replaced the N+1 per-subscription `User` lookup in `get_active_subscriptions()` with a single join; extracted the cross-midnight window logic into a testable `is_in_time_window()`.
- [x] **Durable Notification Queue ([backend/notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/notification_queue.py))**:
  - Pending and dead-lettered tasks are mirrored into Redis hashes (`TaskStore`) and restored at startup, so an alert enqueued just before a redeploy, scale-to-zero, or instance replacement is still delivered afterwards.
  - Persistence is opt-in per instance (`persist=True` on the deployed singleton) so tests never inherit a developer's local Redis state; every Redis failure degrades to in-process-only behaviour.
  - Connection details centralized in [backend/redis_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/redis_client.py), which also adds `REDIS_URL` support (`rediss://`) for managed providers.
- [x] **Worker Liveness Endpoint ([backend/health.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/health.py))**:
  - `/healthz` on `$PORT`, served from a daemon thread — satisfies Cloud Run's "must listen on PORT" contract for a process that has no HTTP API.
  - Reports **stalled** (503) once the loop misses three poll intervals, so a wedged-but-alive worker is taken out of service rather than silently failing to alert.
  - Added `RUN_ONCE=true` for a single-pass invocation (Cloud Run Job / cron shape).
- [x] **Route Polyline Caching & External Rate-Limit Protection**:
  - New `RouteCache` Prisma model: origin+destination+provider → polyline, keyed by a normalized-address hash, so a repeated commute never re-hits the routing provider ([frontend/src/lib/route-cache.ts](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/frontend/src/lib/route-cache.ts)).
  - Nominatim calls are serialized through a 1 req/s gate (its published policy — exceeding it gets the egress IP blocked, and on Vercel that IP is shared) with exponential-backoff retry on 429/5xx.
  - Cache read/write failures never block subscription creation.
- [x] **API Rate Limiting ([frontend/src/lib/rate-limit.ts](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/frontend/src/lib/rate-limit.ts))**:
  - Upstash Redis (REST) backend when configured, per-instance in-memory fixed window otherwise; fails **open** so a limiter outage can't take down signups.
  - Applied to subscription creation (10/min, keyed by user id), registration (5/5min, keyed by IP), and credentials login (10/5min, keyed by email).
- [x] **Subscription API Hardening & Dashboard Completion**:
  - **Fixed an IDOR**: `DELETE /api/subscriptions` deleted by `id` with no ownership check, so any signed-in user could delete another account's route. Delete and the new `PATCH` are both scoped by `userId`.
  - Added input validation (HH:MM times, address length, per-user subscription cap), a `PATCH` endpoint for pause/resume, `NotifiedIncident` cleanup on delete, and generic error messages on the unauthenticated register route.
  - Dashboard gained pause/resume controls, paused-state styling, inline error/success banners (replacing `alert()`), and optimistic updates with rollback.
- [x] **Deployment Path ([DEPLOYMENT.md](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/DEPLOYMENT.md))**:
  - Prisma **migration history** (`frontend/prisma/migrations/`) replacing `db push`, with `directUrl` for pooler-incompatible DDL.
  - Vercel config for the frontend (`frontend/vercel.json`, `vercel-build` script running `migrate deploy`); build-time env validation skipped via `NEXT_PHASE` so builds don't require runtime secrets.
  - Worker deployed as a **Cloud Run Job** driven by Cloud Scheduler (`RUN_ONCE=true`) rather than an always-on service — the loop sleeps through most of each interval, and a service bills an always-allocated vCPU for that idle time. Secret Manager wiring; non-root, healthchecked Docker image.
  - `single_run_lock()` (Redis `SET NX EX`) stops two scheduled executions overlapping, since Cloud Scheduler does not wait for the previous run and two concurrent runs would race on the `NotifiedIncident` fingerprint row.
  - CI (`.github/workflows/ci.yml`): pytest, lint, typecheck, build, plus a job that applies migrations to a fresh Postgres and **fails on schema drift**. Deploy workflow uses Workload Identity Federation — no GCP key in the repo.
- [x] **Test Suite Expansion**: 23 → 68 offline tests, covering config validation and redaction, queue persistence/restart-replay behaviour, health stall detection, and cross-midnight time windows.

---

## 🚧 Pending & Next Steps

### 1. Distributed Worker Queue Architecture
- *Current State*: The notification queue is now Redis-durable, but subscription evaluation in `main.py` is still sequential and single-process. Exactly one worker runs at a time, enforced by the Redis run lock.
- *Why it's still pinned*: Two instances wouldn't send duplicate SMS (the `NotifiedIncident` fingerprint row de-dupes), but they would race on that row and duplicate Gemini calls.
- *Next Step*: Move subscription evaluation onto a distributed task queue (Celery + Redis Streams) so executions can safely run concurrently, then relax the run lock.

### 2. Self-Hosted Routing
- *Current State*: `RouteCache` plus the 1 req/s throttle keeps normal usage well inside Nominatim/OSRM limits.
- *Next Step*: The public demo servers still have no SLA. Stand up the `osrm` service already scaffolded in `docker-compose.yml` (needs a pre-processed California OSM extract), or rely on the Google Directions key.

### 3. Observability
- *Current State*: `/healthz` reports a stalled loop; logs are plain `print()` to stdout.
- *Next Step*: Add a Cloud Monitoring uptime check against `/healthz` with an alerting policy, and move the worker to structured (JSON) logging so Cloud Logging can index fields like subscription id and incident number.

### 4. Twilio Go-Live
- *Current State*: Dispatch is implemented and inert — unset/placeholder credentials console-log instead of sending. Deliberately deferred until the deployment is settled.
- *Next Step*: Add real credentials to Secret Manager and redeploy (no code change). Note that pay-as-you-go accounts can only text **verified** numbers until upgraded, and US A2P 10DLC registration is required for application-initiated SMS — until both are done, failures accumulate in the DLQ.

### 5. Nice-to-Haves
- **Local Twilio mock service**: a small Express/Flask receiver to display outbound messages locally. The console-log fallback covers most of this need today.
- **DLQ visibility**: `retry_dlq_task()` exists but there is no operator interface for it — dead-lettered alerts are currently only visible in logs.
