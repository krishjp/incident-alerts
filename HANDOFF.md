# Project Handoff Document: CHP Incident Alerts 🚗⚠️

**Last Updated:** July 29, 2026

## 🎯 Project Goals
The goal of **CHP Incident Alerts** is to provide real-time, automated traffic incident alerts to users based on their specific commute routes and active hours.

Key capabilities:
1. **Route Subscriptions**: Users configure specific routes (e.g., origin/destination/polyline), areas (e.g., "Los Angeles"), phone numbers, and time windows (e.g., `07:00` - `09:00`).
2. **Automated Scraping**: Python backend continuously scrapes live CHP (California Highway Patrol) Computer Aided Dispatch (CAD) traffic data via headless Selenium.
3. **Spatial & Temporal Matching**: Evaluates live incident lat/lon coordinates against polyline route boundaries within the scheduled time windows.
4. **AI-Powered Incident Summarization**: Generates brief, digestible SMS summaries using Gemini (`gemini-2.5-flash`) with fallback text generation.
5. **Mock/Real SMS Alerts**: Dispatches SMS notifications to subscribed phone numbers using Twilio (with console mock support for local testing).

---

## ✅ Completed Tasks

- [x] **Project Structure & Architecture**: Established full-stack structure with Next.js frontend, Python backend worker, and Docker PostgreSQL container.
- [x] **Database & Infrastructure**:
  - `docker-compose.yml` created and running PostgreSQL on port `5433` (container `incident-alerts-postgres-1`).
  - `.env` files generated for both `frontend/` and `backend/`.
  - Prisma schema (`prisma/schema.prisma`) defined for Users, RouteSubscriptions, Accounts, Sessions, and NotifiedIncidents.
  - SQLAlchemy models (`backend/models.py`) aligned with Prisma schema tables.
- [x] **CHP Scraper Engine**: `backend/scrapper.py` created with Selenium WebDriver to automate navigation and data extraction from CHP CAD portal.
- [x] **Worker & Evaluation Loop**:
  - `backend/main.py` created to filter active route subscriptions by time window and location polyline distance (`geopy`/`polyline`).
  - Incident fingerprint tracking via `NotifiedIncident` table to prevent duplicate notifications for unchanged incident logs.
- [x] **Mock Notification Mechanism**: Included console fallback logging in `send_sms()` so the application runs locally without needing live Twilio keys.

- [x] **Point A to Point B Street Address Polyline Route Matching**:
  - Built [backend/route_generator.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/route_generator.py) using Nominatim OpenStreetMap geocoding and the OSRM (Open Source Routing Machine) API to generate exact turn-by-turn driving polylines for specific street addresses.
  - Implemented spatial buffer matching (`is_within_range`) calculating Haversine/geodesic distance from scraped CHP incident lat/lon coordinates to decoded polyline route paths.
  - Configured `pytest` framework ([backend/pytest.ini](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/pytest.ini)) and consolidated test suite ([backend/tests/test_routes.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_routes.py)) using `pytest` fixtures for:
    - Point-to-point spatial buffer checks & CHP lat/lon format parsing.
    - Specific street address turn-by-turn routes (Van Nuys City Hall -> Santa Monica City Hall).
    - Golf course commute routes (Meadowlark Golf Club -> Alondra Golf Course along I-405 N/S).
- [x] **Documentation & Git Ignore Configuration**:
  - Updated [.gitignore](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/.gitignore) to exclude `.codegraph/`, `.pytest_cache/`, environment files, and logs.
  - Comprehensive local development & deployment instructions added to [README.md](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/README.md) (Docker, PostgreSQL 5433, Prisma, Next.js, Python worker, Pytest).

---

## 🚧 Pending & Next Steps

1. **Local Twilio Mock Service**:
   - Build a lightweight local HTTP mock service (or simple Express/Flask server) to capture and visualize outbound Twilio webhooks/API calls locally.
2. **Frontend UI Integration**:
   - Finalize Prisma client generation and migrations (`npx prisma db push`).
   - Implement route subscription management UI forms & dashboard.
3. **End-to-End Verification**:
   - Seed sample subscription data in PostgreSQL and run `python main.py` in `backend/` to verify scraping and alert output against live CHP CAD entries.

