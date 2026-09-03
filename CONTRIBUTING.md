# Contributing

This guide covers local development setup, running the app and tests, and conventions to follow when
submitting changes. See [README.md](README.md) for a project overview and [DEPLOYMENT.md](DEPLOYMENT.md) for
the production deployment runbook.

## Prerequisites
- [Docker & Docker Desktop](https://www.docker.com/)
- [Node.js (v18+)](https://nodejs.org/) & `npm`
- [Python 3.10+](https://www.python.org/) with [`uv`](https://docs.astral.sh/uv/)

---

## Local Development Setup

### Step 1: Database & Cache Initialization
Spin up PostgreSQL, Redis, and a production-build frontend container:
```bash
docker compose up -d
```
* PostgreSQL: `127.0.0.1:5434`
* Redis: `127.0.0.1:6381` (container port `6379` is unchanged — see `docker-compose.yml`)
* Frontend: `127.0.0.1:3000` (built from `frontend/Dockerfile`, `NODE_ENV=production`)

The `worker` service is **not** started by this — see Step 5.

If you're actively developing the frontend, stop the container and use `npm run dev` instead (Step 3) so
you get hot reload; running both binds port 3000 twice:
```bash
docker compose stop frontend
```
After editing `frontend/.env`, `docker compose restart frontend` reuses the environment baked in at
container creation — it does **not** reread `env_file`. Use `docker compose up -d --force-recreate frontend`
to pick up `.env` changes.

---

### Step 2: Environment Configuration

Copy the example env files and fill in real values:
```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

At minimum, for local dev:
- `backend/.env`: set `REDIS_PORT=6381` (matches the Docker mapping above); `GEMINI_API_KEY` can be left
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

The schema is managed by a checked-in migration history rather than `prisma db push`. After editing
`prisma/schema.prisma`, run `npx prisma migrate dev --name <what-changed>` to generate the migration — and
update `backend/models.py` by hand to match.

> **Already have a database created with `db push`?** Baseline it once:
> `npx prisma migrate resolve --applied 00000000000000_init`.

Start the Next.js development server:
```bash
npm run dev
```
Access the dashboard at [http://localhost:3000](http://localhost:3000).

---

### Step 4: Seed Demo Accounts (optional)

For manual QA or demos, seed five accounts covering different points in the setup funnel — a fresh signup
with nothing configured, a route added but no phone, a fully-configured-but-paused route, a fully active
route, and a multi-route power user:
```bash
cd frontend
npm run seed:demo
```
All seeded accounts share the password `DemoPass123!`. The script is idempotent (safe to re-run) and
refuses to run against anything but a development/test database (`ENVIRONMENT` check). The "active" accounts
reuse a real polyline already in the dev DB so they match `backend/fixtures/torrance_hb_405_test.kml` without
a live routing-API call — see `frontend/scripts/seed-demo-accounts.js` for the full account list.

---

### Step 5: Backend Worker Setup & Execution
```bash
cd backend
uv venv
uv sync
uv run python main.py          # single pass, then exit — there is no long-lived loop mode
```

The worker prints a redacted configuration summary at startup and refuses to
start on invalid config (see `backend/config.py`), then does one poll pass and
exits. Something external calls it repeatedly — Cloud Scheduler invoking a
Cloud Run Job in production, or locally:

```bash
./scripts/run-worker-loop.sh          # or scripts/run-worker-loop.ps1 on Windows
```

which loops `docker compose run --rm worker` on an interval (default 60s),
imitating the production schedule instead of running an always-on container.

---

### Step 6: Running Tests

Frontend:
```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

Backend (Pytest):
```bash
cd backend
uv run pytest                                        # full suite
uv run pytest tests/test_caltrans_client.py           # one file
uv run pytest tests/test_routes.py::TestClassName::test_name  # one test
uv run pytest -m "not network and not integration and not slow"  # skip tests needing live network/external services
```
Markers (`network`, `integration`, `slow`, declared in `pyproject.toml`) are not auto-skipped — pass `-m`
explicitly if you want to avoid hitting live external services (Caltrans, Nominatim/OSRM, Gemini).

Run the relevant suite(s) before opening a PR for changes touching that half of the app.

---

### Step 7: Local Testing with Injected Incidents

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

## Conventions

- The two runtimes (`frontend/`, `backend/`) only communicate through the shared Postgres database — never
  add in-process coupling between them.
- `backend/models.py` (SQLAlchemy) is hand-maintained to mirror `frontend/prisma/schema.prisma`; there is no
  codegen link. When you change one schema, update the other by hand.
- Database schema changes go through the Prisma migration history (`frontend/prisma/migrations/`), not
  `db push` — CI fails on a schema edit with no corresponding migration.
- Subscription mutations must stay scoped by `userId` (see `frontend/src/app/api/subscriptions/route.ts`) —
  an earlier IDOR let any signed-in user delete another account's route by id.

See [CLAUDE.md](CLAUDE.md) for a deeper architectural walkthrough.
</content>
