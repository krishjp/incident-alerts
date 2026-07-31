# Project Handoff Document: Incident Alerts 🚗⚠️

**Last Updated:** July 31, 2026

## 🎯 Project Goals
The goal of **Incident Alerts** is to provide real-time, automated traffic incident alerts to users based on their specific commute routes and active hours.

Key capabilities:
1. **Route Subscriptions**: Users configure specific routes (e.g., origin/destination/polyline), areas (e.g., "Los Angeles"), phone numbers, and time windows (e.g., `07:00` - `09:00`).
2. **Real-Time Caltrans API Client**: Python backend worker fetches live Caltrans QuickMap traffic feeds via fast lightweight XML/KML HTTP endpoints ([backend/caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/caltrans_client.py)), replacing legacy headless Selenium scraping.
3. **Spatial & Temporal Matching**: Evaluates live incident lat/lon coordinates against polyline route boundaries within the scheduled time windows using an $O(1)$ bounding box pre-filter and Haversine/geodesic distance checks.
4. **AI-Powered Incident Summarization**: Generates brief, digestible SMS summaries using Gemini (`gemini-2.5-flash`) with an in-memory summary cache (`_SUMMARY_CACHE`) and fallback text generation.
5. **Asynchronous Notification Queue with Retries & DLQ**: Enqueues outbound SMS alerts to an asynchronous queue ([backend/notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/notification_queue.py)) with exponential backoff retries and Dead Letter Queue (DLQ) isolation for failed dispatches.

---

## ✅ Completed Tasks

- [x] **Project Structure & Architecture**: Established full-stack structure with Next.js frontend, Python backend worker, and Docker PostgreSQL container.
- [x] **Database & Infrastructure**:
  - `docker-compose.yml` created and running PostgreSQL on port `5433` (container `incident-alerts-postgres-1`).
  - `.env` files generated for both `frontend/` and `backend/`.
  - Prisma schema (`prisma/schema.prisma`) defined for Users, RouteSubscriptions, Accounts, Sessions, and NotifiedIncidents.
  - SQLAlchemy models (`backend/models.py`) aligned with Prisma schema tables.
- [x] **Caltrans API Client Handler ([backend/caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/caltrans_client.py))**:
  - Replaced legacy headless Selenium browser automation with a dedicated `CaltransAPIClient` fetching XML/KML feed data from `https://quickmap.dot.ca.gov/data/chp-only.kml`.
  - Reduced feed fetch & parsing time from 15+ seconds (with Chrome dependency) to **< 0.1 seconds** using native Python standard libraries (`urllib`, `xml.etree.ElementTree`, `re`).
  - Extracted 100% guaranteed latitude/longitude coordinates, incident IDs, title types, timestamped locations, area mappings, and raw dispatch logs.
- [x] **Deprecation of Legacy Scraper ([backend/scrapper.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/scrapper.py))**:
  - Deprecated legacy scraping functions with a `DeprecationWarning` and fallback wrapper forwarding to `caltrans_client.fetch_caltrans_incidents()`.
- [x] **Asynchronous Notification Queue & Dead Letter Queue ([backend/notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/notification_queue.py))**:
  - Implemented decoupled `NotificationTask` queue replacing inline synchronous SMS sending in `main.py`.
  - Added exponential backoff retry scheduling (`backoff_factor * 2^(attempts-1)`).
  - Added Dead Letter Queue (DLQ) isolation for failed tasks exceeding `max_retries` with manual re-queueing (`retry_dlq_task()`).
- [x] **Worker & Spatial Evaluation Optimizations**:
  - Built [backend/route_generator.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/route_generator.py) using Nominatim OpenStreetMap geocoding and OSRM turn-by-turn routing.
  - Added $O(1)$ bounding box pre-filter (`get_bounding_box`) in [backend/route_utils.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/route_utils.py#L68-L86) for fast spatial rejection of distant incidents before running distance loops.
  - Implemented Gemini AI summary caching (`_SUMMARY_CACHE`) in [backend/main.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/main.py#L17-L45) to eliminate duplicate LLM API calls for identical incidents across multiple user subscriptions.
  - Incident fingerprint tracking via `NotifiedIncident` table to prevent duplicate notifications.
- [x] **Testing & Verification Suite**:
  - Expanded Pytest suite across four test modules ([backend/tests/test_routes.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_routes.py), [backend/tests/test_caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_caltrans_client.py), [backend/tests/test_notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_notification_queue.py), [backend/tests/test_full_e2e.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/tests/test_full_e2e.py)).
  - Verified 24 automated tests covering bounding box fast rejection, summary caching, geocoded route matching, live feed fetching, retry backoff, and DLQ handling (**24 passed in 5.10s**).

---

## 🚧 Pending & Next Steps (Addressing Architecture & Security Flaws)

### 1. Scaling & Infrastructure Remediation
- **Distributed Worker Queue Architecture**:
  - *Current State*: In-memory task queue in `notification_queue.py` and sequential evaluation in `main.py`.
  - *Next Step*: Scale out to distributed task queues (e.g., Celery + Redis or AWS SQS) to evaluate spatial subscriptions concurrently across worker nodes.
- **External API Rate Limiting & Polyline Caching**:
  - *Current Flaw*: Direct calls to public Nominatim and OSRM routing servers can trigger 429 Rate Limit errors under concurrent route creation.
  - *Next Step*: Cache route polylines permanently in PostgreSQL upon subscription creation and introduce a self-hosted OSRM Docker container or fallback router.
- **Database Connection Pooling**:
  - *Current Flaw*: Unmanaged database connections between Next.js Prisma client API calls and SQLAlchemy worker loops.
  - *Next Step*: Configure explicit connection pooling thresholds (e.g. PgBouncer or SQLAlchemy pool sizes) to prevent database connection exhaustion under load.

### 2. Security & Data Protection
- **Secrets Management & Environment Validation**:
  - *Current Flaw*: Potential exposure of weak default keys (`super-secret-key`, default Postgres credentials).
  - *Next Step*: Enforce strict environment variable validation on startup using `pydantic-settings` in Python and `zod` in Next.js; require strong entropy for production secrets.
- **API Endpoint Rate Limiting**:
  - *Current Flaw*: Frontend route creation endpoints lack request rate limiting.
  - *Next Step*: Add middleware rate limiting (e.g. Upstash Redis / Next.js middleware) on route subscription endpoints to prevent Denial of Service (DoS).
- **PII Encryption at Rest**:
  - *Current Flaw*: Phone numbers stored in plain text in PostgreSQL.
  - *Next Step*: Implement column-level encryption (e.g. `pgcrypto` or application-level AES encryption) for user phone numbers and contact details.

### 3. Frontend & Mock Integrations
- **Local Twilio Mock Service**:
  - Build a lightweight local Express/Flask mock service to capture and display outbound Twilio webhooks locally.
- **Frontend UI Dashboard**:
  - Run Prisma database push (`npx prisma db push`) and finish route subscription management forms in Next.js.
