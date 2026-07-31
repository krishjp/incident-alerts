# CHP Incident Notification System - Backend Worker

A Python-based automation worker that ingests live incident data feeds from **Caltrans QuickMap & CHP CAD** to identify traffic incidents. The system filters these incidents against user-defined subscribed routes and commute time windows to send targeted SMS notifications via an asynchronous retry-enabled queue.

---

## 🌟 Key Features

* **Caltrans API Client Handler ([caltrans_client.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/caltrans_client.py))**: Ingests live CHP traffic incidents directly from Caltrans QuickMap XML/KML feeds (`https://quickmap.dot.ca.gov/data/chp-only.kml`) via HTTP (< 0.1s execution time), completely replacing legacy Selenium browser scraping.
* **Asynchronous Notification Queue with DLQ ([notification_queue.py](file:///C:/Users/kpatel/Documents/sideRunners/incident-alerts/backend/notification_queue.py))**: Manages outbound Twilio SMS alert tasks asynchronously with exponential backoff retries and Dead Letter Queue (DLQ) isolation for failed dispatches.
* **$O(1)$ Bounding Box Spatial Filtering**: Filters incidents using spatial bounding boxes before calculating exact geodesic distances along turn-by-turn polyline routes.
* **AI Summary Caching**: Uses Gemini `gemini-2.5-flash` with an in-memory summary cache (`_SUMMARY_CACHE`) to format concise SMS notifications without duplicate LLM API calls.
* **Structured Data Modeling**: Custom `Incident` and `IncidentDetails` classes with SQLAlchemy database persistence (`NotifiedIncident`).

---

## 🏗️ Backend Module Structure

* **`caltrans_client.py`**: The core API handler fetching and parsing Caltrans QuickMap KML feeds into structured incident records.
* **`notification_queue.py`**: Asynchronous notification queue for SMS alert delivery with exponential retry backoff and Dead Letter Queue (DLQ).
* **`scrapper.py`**: Deprecated legacy wrapper module forwarding calls to `caltrans_client.py`.
* **`route_generator.py`**: Interacts with Nominatim OpenStreetMap geocoding and OSRM routing APIs to build driving polylines.
* **`route_utils.py`**: Handles polyline decoding, bounding box pre-filtering, and geodesic distance evaluation.
* **`main.py`**: Background worker loop checking active PostgreSQL subscriptions, processing feeds, and managing notification queues.
* **`models.py`**: Defines SQLAlchemy models (`User`, `RouteSubscription`, `NotifiedIncident`) aligned with Prisma schema tables.
* **`tests/`**: Pytest test suite covering API feeds, notification queue retries/DLQ, and route matching (`23 passed in 7.41s`).

---

## 🚀 Execution & Testing

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Backend Worker**:
   ```bash
   python main.py
   ```

3. **Run Test Suite**:
   ```bash
   pytest
   ```