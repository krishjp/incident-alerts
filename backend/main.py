import os
import time
from dotenv import load_dotenv
from google import genai
from route_utils import is_within_range_pure as is_within_range

load_dotenv()

# Initialize Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY != "dummy_gemini" else None

# Mock Twilio
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")

from cache_handler import global_incident_cache

def summarize_incident(incident_data):
    inc_num = incident_data.get('number', 'unknown')
    raw_details = str(incident_data.get('details', ''))
    
    # Check Redis/in-memory cache for existing summary with TTL
    cached_summary = global_incident_cache.get_summary(inc_num, raw_details)
    if cached_summary:
        return cached_summary

    if not gemini_client:
        summary = f"[Mock Summary] Incident {inc_num} at {incident_data['location']}. Details: {incident_data['details']['full_text_blob'][:50]}..."
        global_incident_cache.set_summary(inc_num, raw_details, summary)
        return summary
    
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"Summarize this traffic incident for a quick SMS alert (max 150 chars): {incident_data}"
        )
        summary = response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        summary = f"Incident at {incident_data['location']}: {incident_data['type']}"

    global_incident_cache.set_summary(inc_num, raw_details, summary)
    return summary

from models import get_active_subscriptions, SessionLocal, NotifiedIncident
from caltrans_client import fetch_caltrans_incidents
from notification_queue import global_notification_queue

def check_and_notify():
    print("Checking active subscriptions...")
    active_subs = get_active_subscriptions()
    if not active_subs:
        print("No active subscriptions for the current time window.")
        # Process any pending retries in the notification queue
        global_notification_queue.process_queue()
        return

    # Group by area to avoid fetching same area multiple times
    areas_to_fetch = set(sub["sub"].area for sub in active_subs)
    
    incidents_by_area = {}
    for area in areas_to_fetch:
        print(f"Fetching Caltrans API feed for area: {area}...")
        incidents = fetch_caltrans_incidents(area)
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
                        prefix = "Incident UPDATE Alert" if is_update else "Incident Alert"
                        message = f"{prefix} for {sub.origin}->{sub.destination}: {summary}"
                        
                        # Enqueue outbound SMS alert to notification queue with retries & DLQ handling
                        global_notification_queue.enqueue(to_phone=phone, message=message)
                        
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

    # Process all queued notifications (with retries and DLQ dispatch)
    global_notification_queue.process_queue()

if __name__ == "__main__":
    print("Starting Incident Notification Worker...")
    while True:
        try:
            check_and_notify()
        except Exception as e:
            print(f"Worker error: {e}")
        
        print("Sleeping for 60 seconds...")
        time.sleep(60)

