import time
from google import genai
from config import settings
from health import mark_cycle_complete, start_health_server
from redis_client import single_run_lock
from route_utils import is_within_range_pure as is_within_range

# Initialize Gemini. Without a key, summarize_incident falls back to a templated
# mock string rather than failing the poll cycle.
gemini_client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_enabled else None

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

from models import get_active_subscriptions, session_scope, NotifiedIncident
from caltrans_client import fetch_caltrans_incidents
from notification_queue import global_notification_queue

def check_and_notify():
    print("Checking active subscriptions...")
    active_subs = get_active_subscriptions()
    if not active_subs:
        print("No active subscriptions for the current time window.")
        # Process any pending retries in the notification queue
        global_notification_queue.process_queue()
        mark_cycle_complete()
        return

    # The Caltrans feed is one statewide snapshot per HTTP call; fetch_caltrans_incidents(area)
    # only filters it client-side afterward. Routes can cross county/CHP-area boundaries, and
    # the dispatching station for a given incident is unpredictable, so match every subscription
    # against the unfiltered statewide feed using spatial distance alone.
    print("Fetching statewide Caltrans API feed...")
    all_incidents = fetch_caltrans_incidents()
    print(f"Found {len(all_incidents)} incidents statewide.")

    for sub_data in active_subs:
        sub = sub_data["sub"]
        phone = sub_data["phone"]
        user = sub_data["user"]
        route_label = f"{sub.origin}->{sub.destination}"

        # Spatial matching is pure computation over the already-fetched feed, so
        # it runs outside any database session — the previous version opened and
        # closed a fresh session per matched incident, which meant a pooled
        # connection checkout for every alert.
        matches = []
        for inc in all_incidents:
            lat_lon_val = inc['details'].get('lat_lon')

            # Polyline geography check
            is_match = is_within_range(
                lat_lon_val, sub.polyline, max_miles=settings.match_radius_miles
            )

            # Fallback naive check if no lat/lon from the feed but names match
            if not is_match and not lat_lon_val:
                origin_lower = sub.origin.lower()
                dest_lower = sub.destination.lower()
                loc_lower = inc["location"].lower()
                desc_lower = inc["location_desc"].lower()
                if origin_lower in loc_lower or dest_lower in loc_lower or origin_lower in desc_lower or dest_lower in desc_lower:
                    is_match = True

            if is_match:
                matches.append(inc)

        matched_numbers = {inc["number"] for inc in matches}
        print(f"  {route_label}: {len(matches)} incident(s) within {settings.match_radius_miles} miles.")

        # One session per subscription covering both new/updated matches and the
        # resolved sweep, so each subscription is a single atomic unit of work.
        try:
            with session_scope() as db:
                id_prefix = f"{sub.id}_"
                previously_notified = {
                    record.id: record
                    for record in db.query(NotifiedIncident).filter(
                        NotifiedIncident.id.like(f"{id_prefix}%")
                    ).all()
                }

                for inc in matches:
                    inc_id = f"{sub.id}_{inc['number']}"
                    # Fingerprint of the incident details, used to detect updates
                    current_state = str(inc.get('details', ''))
                    notified_record = previously_notified.get(inc_id)

                    if notified_record and notified_record.state == current_state:
                        continue  # already alerted, nothing changed

                    is_update = notified_record is not None
                    print(f"*** Match for {user} ({route_label}): Incident {inc['number']} (Update: {is_update})")
                    summary = summarize_incident(inc)
                    prefix = "Incident UPDATE Alert" if is_update else "Incident Alert"
                    message = f"{prefix} for {route_label}: {summary}"

                    # Enqueue outbound SMS alert with retries & DLQ handling
                    global_notification_queue.enqueue(to_phone=phone, message=message)

                    if notified_record:
                        notified_record.state = current_state
                    else:
                        db.add(NotifiedIncident(id=inc_id, state=current_state))

                # Incidents previously alerted for this subscription that no longer
                # match (dropped out of the feed or moved out of range) are treated
                # as resolved. The RESOLVED sentinel makes the cleared alert fire
                # exactly once.
                for record_id, record in previously_notified.items():
                    if record.state == "RESOLVED":
                        continue
                    inc_number = record_id[len(id_prefix):]
                    if inc_number in matched_numbers:
                        continue
                    print(f"*** Incident resolved for {user} ({route_label}): {inc_number}")
                    message = f"Incident Resolved for {route_label}: Incident {inc_number} has cleared."
                    global_notification_queue.enqueue(to_phone=phone, message=message)
                    record.state = "RESOLVED"
        except Exception as e:
            # One subscription's database failure must not abandon the rest of
            # the poll cycle (or the queued notifications below).
            print(f"DB Error while processing subscription {sub.id}: {e}")

    # Process all queued notifications (with retries and DLQ dispatch)
    global_notification_queue.process_queue()
    mark_cycle_complete()

def main():
    # Importing config already validated every required/typed setting; this
    # just records what the process actually resolved to.
    print("Starting Incident Notification Worker...")
    print(settings.describe())

    if settings.run_once:
        # RUN_ONCE=true is the Cloud Run Job / cron shape: one pass, then exit.
        # Undelivered retries survive via the Redis-backed notification queue.
        #
        # No health server here — nothing probes a task that lives for seconds,
        # and the scheduler treats a non-zero exit as the failure signal instead.
        with single_run_lock("worker:poll", ttl_seconds=settings.run_lock_ttl_seconds) as acquired:
            if not acquired:
                # The previous execution is still running. Exiting 0 (not an
                # error) keeps the scheduler's failure alerting meaningful.
                print("Previous poll cycle still running - skipping this execution.")
                return
            check_and_notify()
        return

    # Long-lived mode: container platforms expect the process to answer on $PORT.
    # The worker has no HTTP API, so this serves liveness/readiness only.
    if settings.health_server_enabled:
        start_health_server(settings.health_port, settings.poll_interval_seconds)

    while True:
        try:
            check_and_notify()
        except Exception as e:
            print(f"Worker error: {e}")

        print(f"Sleeping for {settings.poll_interval_seconds} seconds...")
        time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    main()

