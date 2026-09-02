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
* **Database & Infrastructure (PostgreSQL + Redis)**: Docker containerized PostgreSQL on host port `5433` and Redis on host port `6380` (container port `6379` is unchanged; set `REDIS_PORT=6380` in `backend/.env` for local, non-Docker worker runs).
* **Pytest Testing Suite**: Fully configured pytest suite (**26 passed in 8.5s**) covering Redis cache get/set/hashing, Caltrans API parsing, area filtering, notification queue retries, DLQ handling, bounding box rejection, and street address route matching.

---

## 🏗️ Project Structure

* **`docker-compose.yml`**: PostgreSQL (`5433`) and Redis (`6379`) container configuration.
* **`frontend/`**: Next.js client application containing:
  * `prisma/schema.prisma`: Data models for User, Account, Session, RouteSubscription, and NotifiedIncident.
  * `src/app/`: Next.js App Router layout, authentication, and subscription UI.
* **`backend/`**: Background Python worker containing:
  * `main.py`: Main execution loop checking active subscriptions, ingesting feeds via Caltrans client, and queuing alerts.
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

## 🚀 Local Development & Deployment Instructions

### Prerequisites
- [Docker & Docker Desktop](https://www.docker.com/)
- [Node.js (v18+)](https://nodejs.org/) & `npm`
- [Python 3.10+](https://www.python.org/)

---

### Step 1: Database & Cache Initialization
Spin up PostgreSQL and Redis containers:
```bash
docker compose up -d
```
* PostgreSQL: `127.0.0.1:5433`
* Redis: `127.0.0.1:6380` (container port `6379` is unchanged — see `docker-compose.yml`)

---

### Step 2: Environment Configuration

Copy the example env files and fill in real values:
```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

At minimum, for local dev:
- `backend/.env`: set `REDIS_PORT=6380` (matches the Docker mapping above); `GEMINI_API_KEY` can be left
  unset (falls back to a templated mock summary).
- `frontend/.env`: set `NEXTAUTH_SECRET` (>=32 chars, e.g. `openssl rand -hex 32`) and
  `PHONE_ENCRYPTION_KEY` (64-char hex, `openssl rand -hex 32`) — this key **must match** the same value in
  `backend/.env` exactly, or phone numbers written by the frontend can't be decrypted by the worker.
  `GOOGLE_CLIENT_ID`/`SECRET` and `GOOGLE_MAPS_API_KEY` are optional (Google OAuth login and Directions API
  routing respectively both have working fallbacks — credentials login, and free Nominatim/OSRM routing).

See `backend/.env.example` and `frontend/.env.example` for the full list of variables and what each does.

---

### Step 3: Frontend Setup & Database Migration
```bash
cd frontend
npm install
npx prisma migrate deploy   # applies prisma/migrations to the database
```

The schema is now managed by a checked-in migration history rather than
`prisma db push`. After editing `prisma/schema.prisma`, run
`npx prisma migrate dev --name <what-changed>` to generate the migration — and
update `backend/models.py` by hand to match.

> **Already have a database created with `db push`?** Baseline it once:
> `npx prisma migrate resolve --applied 00000000000000_init`.

Start the Next.js development server:
```bash
npm run dev
```
Access the dashboard at [http://localhost:3000](http://localhost:3000).

---

### Step 4: Backend Worker Setup & Execution
```bash
cd backend
uv venv
uv sync
uv run python main.py          # long-lived polling loop
RUN_ONCE=true uv run python main.py   # single pass, then exit (useful for debugging)
```

The worker prints a redacted configuration summary at startup and refuses to
start on invalid config (see `backend/config.py`). It also serves a liveness
endpoint on `PORT` (default 8080):

```bash
curl http://localhost:8080/healthz
```

which returns 503 — not just "process is up" — once the poll loop stops
completing cycles.

---

### Step 5: Running Tests (Pytest)

Run all unit and integration tests:
```bash
cd backend
uv run pytest
```

---

### Step 6: Local Testing with Injected Incidents

To exercise the full worker pipeline (spatial matching, dedup/update alerts, Gemini summaries, the
notification queue) without waiting for a real Caltrans incident, point the backend at a local KML fixture
instead of the live feed:
```env
# backend/.env
CALTRANS_FEED_URL="file:///absolute/path/to/backend/fixtures/injected_incidents.kml"
```
Edit `backend/fixtures/injected_incidents.kml` to add incidents, and ensure a matching `RouteSubscription`
exists (active window, matching `area`, polyline within 5 miles). See
[backend/README.md § Local Testing with Injected Incidents](backend/README.md#-local-testing-with-injected-incidents)
for full requirements and steps.

---

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
3. **Worker alerting** — `/healthz` reports a stalled loop, but nothing pages
   anyone on it yet.
