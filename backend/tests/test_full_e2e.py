import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from caltrans_client import fetch_caltrans_incidents
from route_generator import fetch_osrm_polyline
from route_utils import is_within_range_pure as is_within_range
from main import summarize_incident
from notification_queue import NotificationQueue, TaskStatus

@pytest.mark.integration
@pytest.mark.network
def test_full_live_pipeline_e2e():
    """
    Full End-to-End Integration Test:
    1. Geocodes origin & destination street addresses to fetch an OSRM route polyline.
    2. Ingests live real-time traffic incident feeds from Caltrans API.
    3. Runs bounding-box pre-filtering & spatial buffer evaluation.
    4. Formats AI incident summaries using Gemini.
    5. Enqueues outbound SMS alerts to NotificationQueue.
    6. Processes the queue and verifies successful delivery.
    """
    print("\n--- Starting Full Live E2E Pipeline Test ---")

    # Step 1: Generate real turn-by-turn route polyline along I-405
    origin = "Meadowlark Golf Club, Huntington Beach, CA"
    dest = "Alondra Golf Course, Lawndale, CA"
    print(f"Step 1: Geocoding route ({origin} -> {dest})...")
    origin_coords, dest_coords, polyline_str = fetch_osrm_polyline(origin, dest)
    
    assert origin_coords is not None
    assert dest_coords is not None
    assert polyline_str is not None
    print(f"  Polyline generated (length: {len(polyline_str)} chars).")

    # Step 2: Fetch live incidents via Caltrans API Client
    print("Step 2: Fetching live Caltrans XML feed...")
    incidents = fetch_caltrans_incidents("Los Angeles")
    assert isinstance(incidents, list)
    assert len(incidents) > 0
    print(f"  Fetched {len(incidents)} live traffic incidents.")

    # Step 3: Evaluate incidents against route polyline with bounding box filter
    print("Step 3: Evaluating spatial matches...")
    matched_incidents = []
    for inc in incidents:
        lat_lon = inc.get("details", {}).get("lat_lon")
        if is_within_range(lat_lon, polyline_str, max_miles=5.0):
            matched_incidents.append(inc)

    print(f"  Matched {len(matched_incidents)} incidents within 5 miles of route.")

    # Step 4 & 5: AI Summarization & Queue Enqueueing
    sent_dispatches = []
    def mock_sender(to_phone, msg):
        sent_dispatches.append((to_phone, msg))
        return True

    test_queue = NotificationQueue(sender_func=mock_sender)

    target_inc = matched_incidents[0] if matched_incidents else incidents[0]
    
    print(f"Step 4: Generating AI summary for Incident {target_inc['number']}...")
    summary = summarize_incident(target_inc)
    assert summary is not None
    assert len(summary) > 0
    print(f"  Summary generated: '{summary[:80]}...'")

    message = f"Incident Alert for {origin}->{dest}: {summary}"

    print("Step 5: Enqueueing SMS task to NotificationQueue...")
    task = test_queue.enqueue("+15551234567", message)
    assert task.status == TaskStatus.PENDING

    # Step 6: Process Queue & Verify Delivery
    print("Step 6: Processing notification queue...")
    stats = test_queue.process_queue()
    assert stats["succeeded"] == 1
    assert len(sent_dispatches) == 1
    assert sent_dispatches[0][0] == "+15551234567"
    assert "Incident Alert" in sent_dispatches[0][1]

    print("--- Full Live E2E Pipeline Test Passed Successfully! ---\n")
