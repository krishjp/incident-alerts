---

# CHP Incident Notification System 🚗⚠️

A full-stack Next.js and Python web application that dynamically checks the **CHP CAD (Computer Aided Dispatch)** portal to identify traffic incidents. The Next.js frontend allows users to configure "subscribed routes" and "subscribed times", while the Python backend monitors incidents on those routes using Selenium, summarizes them with Gemini, and dispatches mock Twilio SMS alerts.

## 🌟 Features

* **Real-Time Next.js Dashboard**: User friendly web application (Tailwind) to register routes and update notification phone numbers.
* **Database & Auth (Auth.js)**: Integrates PostgreSQL + Prisma for reliable data storage. Allows login via email credentials.
* **Intelligent Scraping**: A headless Selenium scraper grabs raw dispatch payloads across specific geographical regions on the CHP website.
* **AI-Powered Summaries**: Utilizes `gemini-2.5-flash` to condense complex police dispatch logs into a short, impactful text message.
* **Temporal Route Matching**: Filters incoming live traffic data against the specific start/end times and route IDs configured by the user.

## 🏗️ Project Structure

* **`docker-compose.yml`**: Spins up a local PostgreSQL database for storing user accounts and route subscriptions.
* **`frontend/`**: The Next.js client. Contains NextAuth logic, routing, layout pages, Prisma config, and API endpoints. 
* **`backend/`**: The background Python worker. Contains:
  * `main.py`: The worker loop that checks active subscriptions.
  * `scrapper.py`: Runs a headless Chrome instance to scrape live CHP details.
  * `models.py`: Connects to PostgreSQL directly via SQLAlchemy to read subscriptions created by the Next.js app.

## 🚀 Installation & Setup

### 1. Database Initialization
This project uses Docker to run PostgreSQL locally.
```bash
docker compose up -d
```
The database exposed on `127.0.0.1:5433` avoids conflicts with existing local postgres setups.

### 2. Frontend Configuration
```bash
cd frontend
npm install
npx prisma db push
```

Start the Next.js development server:
```bash
npm run dev
```
You can access the frontend at [http://localhost:3000](http://localhost:3000). To test quickly, sign in using an email layout such as `test@example.com` and password `password`.

### 3. Backend Worker Configuration
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Set up your `.env` file under `backend/`. If testing without a real Gemini key, leave it as `dummy_gemini` to receive a mock notification layout instead.

Start the background service:
```bash
python main.py
```

## 📝 Usage Flow

1. **Sign In**: Navigate to the Web App to sign in or sign up.
2. **Subscribe**: Create a new subscription for your route (e.g. Area: `Los Angeles`, Route: `I-405 S`, Times: `07:00` - `09:00`). Enter a valid phone number.
3. **Wait & Alert**: The backend worker continuously evaluates if the current time matches any subscription. It performs scraping tasks dynamically matching active routes and area regions. When a crash occurs, Gemini writes a summary and an SMS trigger is printed.
