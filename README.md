# Incident Notification System 🚗⚠️

A full-stack Next.js and Python web application that dynamically checks **Caltrans QuickMap & Traffic CAD** API data feeds to identify traffic incidents. The Next.js frontend allows users to configure subscribed commute routes (defined by turn-by-turn driving polylines between specific street addresses) and scheduled active hours, while the Python backend worker monitors incidents on those routes using a lightweight XML/KML API client, summarizes them with Gemini AI, caches responses in Redis, and dispatches SMS alerts via an asynchronous retry-enabled notification queue.

---

## 🌟 Features

* **Point A to Point B Street Address Subscriptions**: Users subscribe to precise origin and destination street addresses. Address geocoding (OpenStreetMap / Nominatim) and turn-by-turn routing (OSRM) build an encoded polyline path.
* **Spatial Polyline Distance Buffer & Bounding Box Rejection**: Fast $O(1)$ bounding box pre-filtering followed by exact Haversine/geodesic distance calculations from incident coordinates to the commute polyline path.
* **Caltrans API Client Handler ([backend/caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/caltrans_client.py))**: Direct XML/KML HTTP feed parser (`https://quickmap.dot.ca.gov/data/chp-only.kml`) replacing heavy Selenium browser overhead (< 0.1s execution time).
* **Redis AI Summary Cache ([backend/cache_handler.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/cache_handler.py))**: Redis-backed summary caching with 24-hour TTL expiration (`EXPIRE`) and in-memory fallback to avoid duplicate Gemini AI API calls across distributed processes.
* **Asynchronous Notification Queue with Retries & DLQ ([backend/notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/notification_queue.py))**: Decoupled task queue supporting exponential backoff retries and Dead Letter Queue (DLQ) isolation for failed SMS dispatches.
* **Real-Time Next.js Dashboard**: Modern web application to register routes, set active commute hours (e.g. `07:00` - `09:00`), and manage phone numbers.
* **Database & Infrastructure (PostgreSQL + Redis)**: Docker containerized PostgreSQL on host port `5434` and Redis on host port `6381` (container port `6379` is unchanged; set `REDIS_PORT=6381` in `backend/.env` for local, non-Docker worker runs).
* **Pytest Testing Suite**: Fully configured pytest suite (**26 passed in 8.5s**) covering Redis cache get/set/hashing, Caltrans API parsing, area filtering, notification queue retries, DLQ handling, bounding box rejection, and street address route matching.

---

## 🏗️ Project Structure

* **`docker-compose.yml`**: PostgreSQL (`5434`) and Redis (`6381`); the `worker` service sits behind a `job`
  profile, so it isn't started by `docker compose up -d` — invoke it with `docker compose run --rm worker`
  or via `scripts/run-worker-loop.sh`/`.ps1`.
* **`scripts/`**: `run-worker-loop.sh` / `.ps1` — loop `docker compose run --rm worker` on an interval,
  imitating Cloud Scheduler locally instead of running an always-on worker container.
* **`frontend/`**: Next.js client application containing:
  * `prisma/schema.prisma`: Data models for User, Account, Session, RouteSubscription, and NotifiedIncident.
  * `src/app/`: Next.js App Router layout, authentication, and subscription UI.
  * `scripts/seed-demo-accounts.js`: Seeds demo accounts at different setup-funnel stages for local QA/demos
    (`npm run seed:demo`).
* **`backend/`**: Background Python worker containing:
  * `main.py`: Single-pass entrypoint — checks active subscriptions, ingests feeds via the Caltrans client, and queues alerts, then exits. There is no long-lived loop mode; something external (Cloud Scheduler, or `scripts/run-worker-loop.sh`/`.ps1` locally) invokes it repeatedly.
  * `caltrans_client.py`: API Handler fetching and parsing live Caltrans QuickMap XML/KML feeds.
  * `cache_handler.py`: Redis cache module with 24h TTL and graceful in-memory fallback.
  * `notification_queue.py`: Task queue for SMS dispatching with exponential backoff retries and Dead Letter Queue.
  * `scrapper.py`: Deprecated legacy wrapper forwarding calls to `caltrans_client.py`.
  * `route_generator.py`: Geocodes street addresses and fetches OSRM driving polylines.
  * `route_utils.py`: Decodes polylines, computes bounding box filters, and calculates spatial distances.
  * `models.py`: SQLAlchemy database models connected to PostgreSQL.
  * `fixtures/injected_incidents.kml`: Editable sample feed for local testing with injected incidents.
  * `tests/`: Pytest test suite (`test_cache_handler.py`, `test_caltrans_client.py`, `test_notification_queue.py`, `test_routes.py`, `test_full_e2e.py`).

---

## 🚀 Getting Started

For full local setup instructions (Docker, environment variables, database migrations, demo accounts, running
the worker, and tests), see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## 🚢 Deploying

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full runbook: Next.js on Vercel,
the Python worker as a scheduled Cloud Run Job, Neon Postgres, Upstash Redis,
secrets, CI/CD, and rollback.

---

## 🏗️ Architecture & Security Considerations (Roadmap)

Done:

- ✅ **Routing rate limits & caching** — polylines are cached permanently in the
  `RouteCache` table, and Nominatim calls are throttled to its 1 req/s policy
  with retry/backoff (`frontend/src/lib/route-cache.ts`, `src/lib/routing.ts`).
- ✅ **Connection pooling** — explicit SQLAlchemy pool sizing with pre-ping and
  recycle (`backend/models.py`); `connection_limit` guidance for Prisma in
  DEPLOYMENT.md.
- ✅ **Environment validation** — fail-fast, typed config on both sides
  (`backend/config.py`, `frontend/src/lib/env.ts`), with extra production checks.
- ✅ **API rate limiting** — Upstash-backed (in-memory fallback) limits on
  subscription creation, registration, and login (`frontend/src/lib/rate-limit.ts`).
- ✅ **Durable notifications** — pending and dead-lettered SMS survive a worker
  restart via Redis (`backend/notification_queue.py`).

Remaining:

1. **Distributed queue architecture** — scale the task queue into distributed
   worker pools (Celery / Redis Streams) so more than one worker instance can
   run. Until then exactly one worker runs at a time, enforced by the Redis run
   lock in `backend/redis_client.py`.
2. **Self-hosted routing** — the public Nominatim/OSRM endpoints have no SLA;
   run the `osrm` service in `docker-compose.yml` for real traffic.
3. **Worker alerting** — a failed pass surfaces only as a non-zero exit in
   Cloud Run's execution history; nothing pages anyone on it yet.
</content>
