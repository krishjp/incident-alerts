
---

# CHP Incident Notification System

A Python-based automation tool that scrapes the **CHP CAD (Computer Aided Dispatch)** portal to identify traffic incidents. The system filters these incidents against user-defined "subscribed routes" and "subscribed times" to send targeted notifications, ensuring users only receive alerts relevant to their commute.

## Features

* **Real-Time Web Scraping:** Uses **Selenium** to navigate the [CHP Traffic Incident Information Page](https://cad.chp.ca.gov/).
* **Dynamic Data Extraction:** Handles JavaScript-heavy elements, including selecting specific Communication Centers (e.g., Los Angeles) and extracting deep-level "Detail Information" for every incident.
* **Route Subscription Logic:** Filters raw incident data by matching "Location" and "Area" fields against a user's specific travel path.
* **Temporal Filtering:** Allows users to set notification windows (e.g., 8:00 AM – 9:00 AM) so they are only alerted during their active commute.
* **Structured Data Modeling:** Utilizes a custom `Incident` class to store incident numbers, timestamps, types, locations, and granular dispatch logs.

## Project Structure

* **`scraper.py`**: The core engine that automates the browser, interacts with dropdowns, and handles the "Details" expansion for each incident row.
* **`models.py`**: Defines the `Incident` class and data structures for users and their subscriptions.
* **`notifier.py`**: (Target for development) Logic to trigger SMS, Email, or Push notifications when a match is found.

## Installation

1. **Clone the repository:**
```bash
git clone https://github.com/your-username/chp-incident-alerts.git
cd chp-incident-alerts

```


2. **Install dependencies:**
```bash
pip install selenium webdriver-manager

```


3. **Drivers:**
The project uses `webdriver-manager` to automatically handle Chrome driver binaries. Ensure you have Google Chrome installed.

## Usage

### 1. Configure Subscriptions

Define your routes and times in a configuration file (e.g., `config.json`):

```json
{
  "user_subscriptions": [
    {
      "route": "I-405 S",
      "area": "West LA",
      "start_time": "17:00",
      "end_time": "18:30"
    }
  ]
}

```

### 2. Run the Scraper

```python
python scraper.py

```

## Data Flow

The system follows a linear path to ensure data accuracy:

1. **Selection:** Selects the relevant Communication Center from the `ddlComCenter` dropdown.
2. **Collection:** Iterates through the `gvIncidents` table rows.
3. **Expansion:** For each row, clicks the **"Details"** link to reveal the dispatch log (lat/lon, specific hazards, etc.).
4. **Matching:** Compares the location and time against the user's `subscribed route`.
5. **Alerting:** Dispatches a notification if a match is detected.

## Disclaimer

This project is for educational and personal use. Please respect the CHP's website terms of service and avoid aggressive scraping intervals that may stress their servers. The site naturally refreshes every 60 seconds.