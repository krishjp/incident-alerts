# CHP Incident Notification System 🚗⚠️

A full-stack Next.js and Python web application that dynamically checks the **CHP CAD (Computer Aided Dispatch)** portal to identify traffic incidents. The Next.js frontend allows users to configure subscribed commute routes (defined by turn-by-turn driving polylines between specific street addresses) and scheduled active hours, while the Python backend worker monitors incidents on those routes using Selenium, summarizes them with Gemini AI, and dispatches SMS alerts.

---

## 🌟 Features

* **Point A to Point B Street Address Subscriptions**: Users subscribe to precise origin and destination street addresses. Address geocoding (OpenStreetMap / Nominatim) and turn-by-turn routing (OSRM) build an encoded polyline path.
* **Spatial Polyline Distance Buffer**: Calculates exact Haversine/geodesic distance from scraped CHP incident coordinates to the commute polyline path, triggering alerts only for incidents within the user's buffer (e.g. 2.0 miles).
* **Real-Time Next.js Dashboard**: Modern web application to register routes, set active commute hours (e.g. `07:00` - `09:00`), and manage phone numbers.
* **Database & Auth (Auth.js / Prisma)**: PostgreSQL + Prisma schema storing User accounts, RouteSubscriptions, and NotifiedIncidents logs.
* **Intelligent Scraping Engine**: Headless Selenium worker scraping live dispatch payloads across CHP Communication Centers (e.g. "Los Angeles").
* **AI-Powered Incident Summaries**: Utilizes `gemini-2.5-flash` to condense detailed dispatch logs into concise SMS notifications (with console mock fallback when running locally).
* **Pytest Testing Suite**: Fully configured pytest suite with markers (`slow`, `network`, `integration`) for fast local unit testing and live scraping verification.

---

## 🏗️ Project Structure

* **`docker-compose.yml`**: Local PostgreSQL container configuration running on port `5433`.
* **`frontend/`**: Next.js client application containing:
  * `prisma/schema.prisma`: Data models for User, Account, Session, RouteSubscription, and NotifiedIncident.
  * `src/app/`: Next.js App Router layout, authentication, and subscription UI.
* **`backend/`**: Background Python worker containing:
  * `main.py`: Main execution loop checking active subscriptions, scraping CHP, and triggering alerts.
  * `scrapper.py`: Headless Selenium engine extracting live incident records.
  * `route_generator.py`: Geocodes street addresses and fetches OSRM driving polylines.
  * `route_utils.py`: Decodes polylines and computes geodesic spatial distances.
  * `models.py`: SQLAlchemy database models connected to PostgreSQL.
  * `pytest.ini` & `tests/test_routes.py`: Consolidated Pytest testing suite.

---

## 🚀 Local Development & Deployment Instructions

### Prerequisites
- [Docker & Docker Desktop](https://www.docker.com/)
- [Node.js (v18+)](https://nodejs.org/) & `npm`
- [Python 3.10+](https://www.python.org/)
- Google Chrome browser (for headless Selenium scraper)

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

Run all fast local unit tests (skipping long network/scraping test):
```bash
cd backend
pytest -m "not slow"
```

Run the complete test suite including live CHP scraper integration:
```bash
cd backend
pytest
```

---

## 📝 Usage Flow

1. **Sign In**: Access the Web App at `http://localhost:3000`.
2. **Subscribe Route**: Enter an Origin street address (e.g. `Meadowlark Golf Club, Huntington Beach, CA`) and Destination street address (e.g. `Alondra Golf Course, Lawndale, CA`), select area `Los Angeles`, enter active hours (e.g. `07:00` - `09:00`), and input your phone number.
3. **Automated Alerting**: The backend worker continuously evaluates active subscriptions during matching time windows, scrapes live CHP CAD incidents, checks polyline distance, and outputs SMS alerts.
