import os
import time
from dotenv import load_dotenv
from google import genai
from models import get_active_subscriptions, SessionLocal, NotifiedIncident
from scrapper import scrape_chp_area
from collections import defaultdict
import polyline
from geopy.distance import geodesic

load_dotenv()

# Initialize Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY != "dummy_gemini" else None

# Mock Twilio
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")

def summarize_incident(incident_data):
    if not gemini_client:
        return f"[Mock Summary] Incident {incident_data['number']} at {incident_data['location']}. Details: {incident_data['details']['full_text_blob'][:50]}..."
    
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"Summarize this traffic incident for a quick SMS alert (max 150 chars): {incident_data}"
        )
        return response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        return f"Incident at {incident_data['location']}: {incident_data['type']}"

def send_sms(to_phone, message):
    print(f"\n[TEXT MESSAGE to {to_phone}]")
    print(f"From: {TWILIO_PHONE}")
    print(f"Message: {message}\n")

def is_within_range(incident_lat_lon, encoded_polyline, max_miles=5.0):
    if not incident_lat_lon or incident_lat_lon == "None":
        return False
    
    # CHP Lat_Lon formatted as usually "34.1234 -118.1234"
    try:
        parts = incident_lat_lon.strip().split()
        if len(parts) == 2:
            inc_lat, inc_lon = float(parts[0]), float(parts[1])
        elif ":" in incident_lat_lon:
            parts = incident_lat_lon.replace(' ', '').split(":")
            inc_lat, inc_lon = float(parts[0]), float(parts[1])
        else:
            return False
    except Exception as e:
        print(f"Failed to parse incident lat long: {incident_lat_lon}")
        return False

    if encoded_polyline == "dummy_polyline":
        return True # if dummy polyline, pass all to show functionality

    try:
        route_points = polyline.decode(encoded_polyline) # List of (lat, lon)
    except Exception as e:
        print("Failed to decode polyline", e)
        return False

    if not route_points:
        return False

    incident_pt = (inc_lat, inc_lon)
    min_dist = float('inf')

    # Find shortest distance to any point on the polyline path
    for pt in route_points:
        dist = geodesic(incident_pt, pt).miles
        if dist < min_dist:
            min_dist = dist
            if min_dist <= max_miles:
                return True
                
    return False

def check_and_notify():
    print("Checking active subscriptions...")
    active_subs = get_active_subscriptions()
    if not active_subs:
        print("No active subscriptions for the current time window.")
        return

    # Group by area to avoid scraping same area multiple times
    areas_to_scrape = set(sub["sub"].area for sub in active_subs)
    
    incidents_by_area = {}
    for area in areas_to_scrape:
        print(f"Scraping area: {area}...")
        incidents = scrape_chp_area(area)
        incidents_by_area[area] = incidents
        print(f"Found {len(incidents)} incidents in {area}.")

    for sub_data in active_subs:
        sub = sub_data["sub"]
        phone = sub_data["phone"]
        user = sub_data["user"]
        
        incidents = incidents_by_area.get(sub.area, [])
        for inc in incidents:
            lat_lon_val = inc['details'].get('lat_lon')
            print(f"Checking incident {inc['number']} at {lat_lon_val} against route polyline for {sub.origin} -> {sub.destination}")
            
            # Polyline geography check
            is_match = is_within_range(lat_lon_val, sub.polyline, max_miles=5.0)
            
            # Fallback naive check if no lat/lon from scraper but names match
            if not is_match and not lat_lon_val:
                origin_lower = sub.origin.lower()
                dest_lower = sub.destination.lower()
                loc_lower = inc["location"].lower()
                desc_lower = inc["location_desc"].lower()
                if origin_lower in loc_lower or dest_lower in loc_lower or origin_lower in desc_lower or dest_lower in desc_lower:
                    is_match = True

            if is_match:
                inc_id = f"{sub.id}_{inc['number']}"
                # Create a fingerprint from the incident details to detect updates
                current_state = str(inc.get('details', ''))
                
                db = SessionLocal()
                try:
                    notified_record = db.query(NotifiedIncident).filter(NotifiedIncident.id == inc_id).first()
                    if not notified_record or notified_record.state != current_state:
                        is_update = notified_record is not None
                        print(f"*** Match found for {user} ({sub.origin}->{sub.destination}): Incident {inc['number']} (Update: {is_update})")
                        summary = summarize_incident(inc)
                        prefix = "CHP UPDATE Alert" if is_update else "CHP Alert"
                        message = f"{prefix} for {sub.origin}->{sub.destination}: {summary}"
                        send_sms(phone, message)
                        
                        if not notified_record:
                            new_record = NotifiedIncident(id=inc_id, state=current_state)
                            db.add(new_record)
                        else:
                            notified_record.state = current_state
                        db.commit()
                except Exception as e:
                    print(f"DB Error while processing incident {inc_id}: {e}")
                    db.rollback()
                finally:
                    db.close()

if __name__ == "__main__":
    print("Starting CHP Notification Worker...")
    while True:
        try:
            check_and_notify()
        except Exception as e:
            print(f"Worker error: {e}")
        
        print("Sleeping for 60 seconds...")
        time.sleep(60)

