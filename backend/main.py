import sys

from google import genai
from google.genai import types
from config import settings
from alert_dedupe import is_similar_summary
from redis_client import DependencyUnavailable, get_redis_client, single_run_lock
from route_utils import distance_to_route_miles, is_within_range_pure as is_within_range

# Initialize Gemini. Without a key, summarize_incident falls back to a templated
# mock string rather than failing the poll cycle.
gemini_client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_enabled else None

from cache_handler import global_incident_cache

# NotifiedIncident.state prefix for an incident whose alert was suppressed as a
# near-duplicate of another incident's. It stays silent for its whole life: the
# incident that did alert carries the updates and the "cleared" message.
DUPLICATE_PREFIX = "DUPLICATE:"

# NotifiedIncident.state prefix for an incident whose route left its time window
# while it was open (the previous state follows the prefix). A route outside its
# window is never polled, so nothing can tell whether the incident cleared; it is
# parked here, silently, instead of being left looking active. It comes back only
# if the incident is still on the board when the route is next polled.
STALE_PREFIX = "STALE:"

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
            contents=f"Summarize this traffic incident for a quick SMS alert (max 150 chars): {incident_data}",
            # Deterministic output keeps rewordings of unchanged details to a
            # minimum; alert_dedupe catches the ones that still slip through.
            config=types.GenerateContentConfig(temperature=0),
        )
        summary = response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        summary = f"Incident at {incident_data['location']}: {incident_data['type']}"

    global_incident_cache.set_summary(inc_num, raw_details, summary)
    return summary

from sqlalchemy import text

from models import (
    engine, get_active_subscriptions, prune_alert_messages, session_scope,
    AlertMessage, NotifiedIncident, RouteSubscription,
)
from caltrans_client import fetch_caltrans_incidents
from notification_queue import global_notification_queue


def check_dependencies():
    """
    Returns a list of problems with Redis/Postgres; empty means both are up.

    Both are hard requirements: Postgres holds subscriptions and the "already
    alerted" fingerprints, Redis holds the run lock and the durable send queue.
    Running with either missing risks duplicate or silently lost alerts.
    """
    problems = []
    client = get_redis_client()
    try:
        if client is None or not client.ping():
            problems.append("Redis unreachable")
    except Exception as exc:
        problems.append(f"Redis unreachable ({type(exc).__name__}: {exc})")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        problems.append(f"Postgres unreachable ({type(exc).__name__}: {exc})")
    return problems


def dispatch_queue():
    """Sends queued SMS, but only after re-confirming Redis and Postgres are up."""
    problems = check_dependencies()
    if problems:
        # Nothing is lost by stopping here: every queued task was persisted to
        # Redis when enqueued (or its subscription's DB work rolled back), so the
        # first run after recovery restores and sends it.
        raise DependencyUnavailable(
            f"{'; '.join(problems)} - holding "
            f"{len(global_notification_queue.pending_tasks)} queued alert(s) until resolved."
        )
    global_notification_queue.process_queue()

def mark_stale_incidents(active_sub_ids):
    """
    Parks open incidents of routes that are not being polled this pass (outside
    their window, paused, or deleted). Logged for the dashboard, never texted.
    """
    try:
        with session_scope() as db:
            open_records = [
                record for record in db.query(NotifiedIncident).filter(
                    NotifiedIncident.state != "RESOLVED",
                    ~NotifiedIncident.state.like(f"{STALE_PREFIX}%"),
                    ~NotifiedIncident.state.like(f"{DUPLICATE_PREFIX}%"),
                ).all()
                if record.id.split("_", 1)[0] not in active_sub_ids
                and record.state != "RESOLVED"
                and not record.state.startswith((STALE_PREFIX, DUPLICATE_PREFIX))
            ]
            if not open_records:
                return
            sub_ids = {record.id.split("_", 1)[0] for record in open_records}
            subs = {
                sub.id: sub for sub in db.query(RouteSubscription).filter(
                    RouteSubscription.id.in_(list(sub_ids))
                ).all()
            }
            for record in open_records:
                sub_id, inc_number = record.id.split("_", 1)
                record.state = STALE_PREFIX + record.state
                sub = subs.get(sub_id)
                if sub is None:
                    continue  # deleted route: nothing left to show it under
                route_label = f"{sub.origin}->{sub.destination}"
                print(f"  Incident {inc_number} on {route_label} is stale (route outside its window).")
                db.add(AlertMessage(
                    userId=sub.userId,
                    subscriptionId=sub.id,
                    routeLabel=route_label,
                    incidentNumber=inc_number,
                    kind="STALE",
                    message=(
                        f"No longer tracking Incident {inc_number} for {route_label}: the route "
                        "is outside its alert window. Tracking resumes if it is still reported "
                        "the next time the route is checked."
                    ),
                    delivery="none",
                ))
    except Exception as e:
        print(f"Stale incident sweep failed (retried next run): {e}")


def check_and_notify():
    print("Checking active subscriptions...")
    # Summaries already sent to each user this pass. CHP regularly files one
    # collision under two incident numbers, and a user with overlapping routes
    # matches the same incident twice — either way they should get one SMS.
    sent_this_pass = {}
    active_subs = get_active_subscriptions()
    mark_stale_incidents({s["sub"].id for s in active_subs})
    if not active_subs:
        print("No active subscriptions for the current time window.")
        # Process any pending retries in the notification queue
        dispatch_queue()
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
        # How each match was made ("spatial" or "text"), so the dashboard's
        # message log can show which check let an alert through.
        match_methods = {}
        for inc in all_incidents:
            lat_lon_val = inc['details'].get('lat_lon')

            # Polyline geography check
            is_match = is_within_range(
                lat_lon_val, sub.polyline, max_miles=settings.match_radius_miles
            )
            method = "spatial"

            # Fallback naive check if no lat/lon from the feed but names match
            if not is_match and not lat_lon_val:
                origin_lower = sub.origin.lower()
                dest_lower = sub.destination.lower()
                loc_lower = inc["location"].lower()
                desc_lower = inc["location_desc"].lower()
                if origin_lower in loc_lower or dest_lower in loc_lower or origin_lower in desc_lower or dest_lower in desc_lower:
                    is_match = True
                    method = "text"

            # The feed can repeat a placemark; a second copy would enqueue a
            # duplicate SMS and then collide on the NotifiedIncident primary key.
            if is_match and inc["number"] not in {m["number"] for m in matches}:
                matches.append(inc)
                match_methods[inc["number"]] = method

        matched_numbers = {inc["number"] for inc in matches}
        print(f"  {route_label}: {len(matches)} incident(s) within {settings.match_radius_miles} miles.")

        # One session per subscription covering both new/updated matches and the
        # resolved sweep, so each subscription is a single atomic unit of work.
        # Alerts queued for it are withdrawn if that unit rolls back, so the
        # fingerprints and the send queue never disagree.
        enqueued = []

        def deliver(db, kind, inc_number, message, inc=None, sms=True):
            """Logs the alert for the dashboard, and queues an SMS if the user has a phone."""
            if phone and sms:
                # Enqueue outbound SMS alert with retries & DLQ handling
                enqueued.append(global_notification_queue.enqueue(to_phone=phone, message=message))
                delivery = "twilio" if settings.sms_enabled else "mock"
            else:
                delivery = "none"
            method = match_methods.get(inc_number) if inc else None
            db.add(AlertMessage(
                userId=sub.userId,
                subscriptionId=sub.id,
                routeLabel=route_label,
                incidentNumber=inc_number,
                kind=kind,
                matchMethod=method,
                distanceMiles=(
                    distance_to_route_miles(inc["details"].get("lat_lon"), sub.polyline)
                    if method == "spatial" else None
                ),
                location=inc["location"] if inc else None,
                message=message,
                delivery=delivery,
            ))

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

                    if notified_record and notified_record.state.startswith(STALE_PREFIX):
                        # Still on the board after the route was parked: tracking
                        # resumes. The restored state means an unchanged incident
                        # stays silent, and a changed one alerts as a normal UPDATE.
                        notified_record.state = notified_record.state[len(STALE_PREFIX):]
                        print(f"    Incident {inc['number']}: still reported, tracking resumed.")
                        deliver(
                            db, "ACTIVE", inc["number"],
                            f"Tracking resumed for {route_label}: Incident {inc['number']} is still reported.",
                            inc, sms=False,
                        )

                    if notified_record and notified_record.state == current_state:
                        continue  # already alerted, nothing changed

                    if notified_record and notified_record.state.startswith(DUPLICATE_PREFIX):
                        notified_record.state = DUPLICATE_PREFIX + current_state
                        continue

                    is_update = notified_record is not None
                    summary = summarize_incident(inc)
                    threshold = settings.summary_similarity_threshold

                    if is_update and notified_record.state != "RESOLVED":
                        # Compare against the summary that was actually sent (its
                        # cache key is the stored state), not the previous poll's
                        # details: the state is left at the sent version below,
                        # so small edits can't drift into a big unannounced one.
                        sent_summary = global_incident_cache.get_summary(
                            inc["number"], notified_record.state
                        )
                        if sent_summary and is_similar_summary(sent_summary, summary, threshold):
                            print(f"    Incident {inc['number']}: details changed but summary is a near-duplicate; no SMS.")
                            continue

                    user_sent = sent_this_pass.setdefault(sub.userId, [])
                    duplicate = any(is_similar_summary(prev, summary, threshold) for prev in user_sent)
                    if duplicate:
                        print(f"    Incident {inc['number']}: near-duplicate of an alert already queued to this user this pass; no SMS.")
                        current_state = DUPLICATE_PREFIX + current_state
                    else:
                        print(f"*** Match for {user} ({route_label}): Incident {inc['number']} (Update: {is_update})")
                        prefix = "Incident UPDATE Alert" if is_update else "Incident Alert"
                        message = f"{prefix} for {route_label}: {summary}"
                        deliver(db, "UPDATE" if is_update else "NEW", inc["number"], message, inc)
                        user_sent.append(summary)

                    # Recorded even when the SMS was suppressed, so the duplicate
                    # incident number doesn't alert on a later pass either.
                    if notified_record:
                        notified_record.state = current_state
                    else:
                        db.add(NotifiedIncident(id=inc_id, state=current_state))

                # Incidents previously alerted for this subscription that no longer
                # match (dropped out of the feed or moved out of range) are treated
                # as resolved. The RESOLVED sentinel makes the cleared alert fire
                # exactly once.
                for record_id, record in previously_notified.items():
                    if record.state == "RESOLVED" or record.state.startswith(STALE_PREFIX):
                        continue
                    inc_number = record_id[len(id_prefix):]
                    if inc_number in matched_numbers:
                        continue
                    if record.state.startswith(DUPLICATE_PREFIX):
                        record.state = "RESOLVED"
                        continue
                    print(f"*** Incident resolved for {user} ({route_label}): {inc_number}")
                    message = f"Incident Resolved for {route_label}: Incident {inc_number} has cleared."
                    deliver(db, "RESOLVED", inc_number, message)
                    record.state = "RESOLVED"
        except Exception as e:
            for task in enqueued:
                global_notification_queue.discard(task)
            if isinstance(e, DependencyUnavailable):
                raise
            # One subscription's database failure must not abandon the rest of
            # the poll cycle; the dependency check before dispatch decides
            # whether anything gets sent.
            print(f"DB Error while processing subscription {sub.id}: {e}")

    # Process all queued notifications (with retries and DLQ dispatch)
    dispatch_queue()

def prune_message_log():
    """Retention for the dashboard's message log. Best effort: alerts already went out."""
    try:
        with session_scope() as db:
            deleted = prune_alert_messages(db)
        if deleted:
            print(f"Pruned {deleted} old dashboard message(s).")
    except Exception as e:
        print(f"Message log cleanup failed (retried next run): {e}")

def main():
    # Importing config already validated every required/typed setting; this
    # just records what the process actually resolved to.
    print("Starting Incident Notification Worker...")
    print(settings.describe())

    problems = check_dependencies()
    if problems:
        # Non-zero exit so the scheduler records a failed execution and alerting
        # fires; the next scheduled run retries once the outage is over.
        print(f"[Worker] Not running: {'; '.join(problems)}. No alerts will be sent until resolved.")
        sys.exit(1)

    # One check_and_notify() pass, then exit — the Cloud Run Job / cron shape.
    # Undelivered retries survive via the Redis-backed notification queue, so
    # nothing is lost between invocations.
    try:
        with single_run_lock("worker:poll", ttl_seconds=settings.run_lock_ttl_seconds) as acquired:
            if not acquired:
                # A previous execution is still running (the scheduler that invokes
                # this process does not wait for the prior run to finish). Exiting 0
                # (not an error) keeps the scheduler's failure alerting meaningful.
                print("Previous poll cycle still running - skipping this execution.")
                return
            check_and_notify()
            prune_message_log()
    except DependencyUnavailable as exc:
        # Raised by the lock, a strict queue write, or the pre-dispatch check.
        print(f"[Worker] Stopped: {exc}. No alerts were sent; they go out on the first run after recovery.")
        sys.exit(1)


if __name__ == "__main__":
    main()

