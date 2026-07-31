# CHP Incident Notification System 🚗⚠️

A full-stack Next.js and Python web application that dynamically checks **Caltrans QuickMap & CHP CAD** API data feeds to identify traffic incidents. The Next.js frontend allows users to configure subscribed commute routes (defined by turn-by-turn driving polylines between specific street addresses) and scheduled active hours, while the Python backend worker monitors incidents on those routes using a lightweight XML/KML API client, summarizes them with Gemini AI, and dispatches SMS alerts via an asynchronous retry-enabled notification queue.

---

## 🌟 Features

* **Point A to Point B Street Address Subscriptions**: Users subscribe to precise origin and destination street addresses. Address geocoding (OpenStreetMap / Nominatim) and turn-by-turn routing (OSRM) build an encoded polyline path.
* **Spatial Polyline Distance Buffer & Bounding Box Rejection**: Fast $O(1)$ bounding box pre-filtering followed by exact Haversine/geodesic distance calculations from CHP incident coordinates to the commute polyline path.
* **Caltrans API Client Handler ([backend/caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/caltrans_client.py))**: Direct XML/KML HTTP feed parser (`https://quickmap.dot.ca.gov/data/chp-only.kml`) replacing heavy Selenium browser overhead (< 0.1s execution time).
* **Asynchronous Notification Queue with Retries & DLQ ([backend/notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/notification_queue.py))**: Decoupled task queue supporting exponential backoff retries and Dead Letter Queue (DLQ) isolation for failed SMS dispatches.
* **Real-Time Next.js Dashboard**: Modern web application to register routes, set active commute hours (e.g. `07:00` - `09:00`), and manage phone numbers.
* **Database & Auth (Auth.js / Prisma)**: PostgreSQL + Prisma schema storing User accounts, RouteSubscriptions, and NotifiedIncidents logs.
* **AI-Powered Incident Summaries with Caching**: Utilizes `gemini-2.5-flash` with in-memory summary caching (`_SUMMARY_CACHE`) to condense detailed dispatch logs into concise SMS notifications without duplicate LLM API calls.
* **Pytest Testing Suite**: Fully configured pytest suite (**23 passed in 7.41s**) covering Caltrans API parsing, area filtering, notification queue retries, DLQ handling, bounding box rejection, and street address route matching.

---

## 🏗️ Project Structure

* **`docker-compose.yml`**: Local PostgreSQL container configuration running on port `5433`.
* **`frontend/`**: Next.js client application containing:
  * `prisma/schema.prisma`: Data models for User, Account, Session, RouteSubscription, and NotifiedIncident.
  * `src/app/`: Next.js App Router layout, authentication, and subscription UI.
* **`backend/`**: Background Python worker containing:
  * `main.py`: Main execution loop checking active subscriptions, ingesting CHP feeds via Caltrans client, and queuing alerts.
  * `caltrans_client.py`: API Handler fetching and parsing live Caltrans QuickMap XML/KML feeds.
  * `notification_queue.py`: Task queue for SMS dispatching with exponential backoff retries and Dead Letter Queue.
  * `scrapper.py`: Deprecated legacy wrapper forwarding calls to `caltrans_client.py`.
  * `route_generator.py`: Geocodes street addresses and fetches OSRM driving polylines.
  * `route_utils.py`: Decodes polylines, computes bounding box filters, and calculates spatial distances.
  * `models.py`: SQLAlchemy database models connected to PostgreSQL.
  * `tests/`: Pytest test suite (`test_caltrans_client.py`, `test_notification_queue.py`, `test_routes.py`).

---

## 🚀 Local Development & Deployment Instructions

### Prerequisites
- [Docker & Docker Desktop](https://www.docker.com/)
- [Node.js (v18+)](https://nodejs.org/) & `npm`
- [Python 3.10+](https://www.python.org/)

---

### Step 1: Database Initialization
Spin up the PostgreSQL database container:
```bash
docker compose up -d
```
The database will run on `127.0.0.1:5433` (avoiding port collisions with local default Postgres installations on 5432).

---

### Step 2: Environment Configuration

Create `backend/.env`:
```env
DATABASE_URL="postgresql://postgres:postgres@localhost:5433/chbdb"
GEMINI_API_KEY="dummy_gemini"
TWILIO_PHONE_NUMBER="+15550000000"
```

Create `frontend/.env`:
```env
DATABASE_URL="postgresql://postgres:postgres@localhost:5433/chbdb"
NEXTAUTH_SECRET="super-secret-key"
NEXTAUTH_URL="http://localhost:3000"
```

---

### Step 3: Frontend Setup & Database Push
```bash
cd frontend
npm install
npx prisma@5 db push
```

Start the Next.js development server:
```bash
npm run dev
```
Access the dashboard at [http://localhost:3000](http://localhost:3000).

---

### Step 4: Backend Worker Setup & Execution
```bash
cd backend
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

Start the Python worker:
```bash
python main.py
```

---

### Step 5: Running Tests (Pytest)

Run all unit and integration tests:
```bash
cd backend
pytest
```

---

## 🏗️ Architecture & Security Considerations (Roadmap)

1. **Distributed Queue Architecture**: Scale the in-memory task queue in `notification_queue.py` into distributed worker pools (Celery / Redis / SQS) to handle subscription scaling.
2. **Routing Rate Limits & Caching**: Cache turn-by-turn polylines permanently in PostgreSQL; fallback to self-hosted OSRM to protect against external rate limits.
3. **Connection Pooling**: Enforce PgBouncer / SQLAlchemy pool sizes to avoid database connection exhaustion.
4. **Security & PII Encryption**: Enforce environment variable validation and encrypt sensitive user phone numbers at rest in PostgreSQL.
