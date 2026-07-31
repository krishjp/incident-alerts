import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from route_generator import fetch_osrm_polyline
from route_utils import encode_polyline, is_within_range_pure as is_within_range
from caltrans_client import fetch_caltrans_incidents

# --- Fixtures ---

@pytest.fixture
def sample_route_polyline():
    coords = [
        (34.1867, -118.4489), # Point A: Van Nuys
        (34.1550, -118.4720), # Sepulveda Pass / I-405
        (34.0900, -118.4680), # Bel Air / Getty Center area
        (34.0500, -118.4550), # Westwood / Wilshire Blvd
        (34.0259, -118.4754)  # Point B: Santa Monica
    ]
    return encode_polyline(coords)

@pytest.fixture(scope="module")
def van_nuys_to_santa_monica_route():
    origin = "14410 Sylvan St, Van Nuys, CA 91401"
    dest = "1685 Main St, Santa Monica, CA 90401"
    origin_coords, dest_coords, polyline_str = fetch_osrm_polyline(origin, dest)
    return {
        "origin_coords": origin_coords,
        "dest_coords": dest_coords,
        "polyline": polyline_str
    }

@pytest.fixture(scope="module")
def golf_commute_route():
    origin = "Meadowlark Golf Club, Huntington Beach, CA"
    dest = "Alondra Golf Course, Lawndale, CA"
    origin_coords, dest_coords, polyline_str = fetch_osrm_polyline(origin, dest)
    return {
        "origin_coords": origin_coords,
        "dest_coords": dest_coords,
        "polyline": polyline_str
    }


# --- Point to Point Spatial Buffer Tests ---

def test_incident_directly_on_route(sample_route_polyline):
    incident_lat_lon = "34.0550 -118.4520"
    assert is_within_range(incident_lat_lon, sample_route_polyline, max_miles=2.0)

def test_incident_near_route_within_buffer(sample_route_polyline):
    incident_lat_lon = "34.0600 -118.4350"
    assert is_within_range(incident_lat_lon, sample_route_polyline, max_miles=2.0)

def test_incident_far_from_route(sample_route_polyline):
    incident_lat_lon = "34.1478 -118.1445"
    assert not is_within_range(incident_lat_lon, sample_route_polyline, max_miles=2.0)

def test_chp_colon_formatted_lat_lon(sample_route_polyline):
    incident_lat_lon = "34.0905:-118.4685"
    assert is_within_range(incident_lat_lon, sample_route_polyline, max_miles=1.0)

def test_bounding_box_fast_rejection(sample_route_polyline):
    # Latitude 40.0 (San Francisco area) -> Should be immediately rejected by bounding box pre-filter without geodesic loop
    far_away_incident = "40.0000 -122.0000"
    assert not is_within_range(far_away_incident, sample_route_polyline, max_miles=5.0)

def test_summary_caching():
    from main import summarize_incident, _SUMMARY_CACHE
    test_data = {
        "number": "9999",
        "location": "I-405 S",
        "type": "Traffic Hazard",
        "details": {"full_text_blob": "Lanes blocked due to debris."}
    }
    sum1 = summarize_incident(test_data)
    cache_key = ("9999", str(test_data["details"]))
    assert cache_key in _SUMMARY_CACHE
    sum2 = summarize_incident(test_data)
    assert sum1 == sum2



# --- Street Address Geocoding & Routing Tests ---

def test_origin_street_address_incident(van_nuys_to_santa_monica_route):
    coords = van_nuys_to_santa_monica_route["origin_coords"]
    polyline_str = van_nuys_to_santa_monica_route["polyline"]
    inc_lat_lon = f"{coords[0]} {coords[1]}"
    assert is_within_range(inc_lat_lon, polyline_str, max_miles=1.0)

def test_destination_street_address_incident(van_nuys_to_santa_monica_route):
    coords = van_nuys_to_santa_monica_route["dest_coords"]
    polyline_str = van_nuys_to_santa_monica_route["polyline"]
    inc_lat_lon = f"{coords[0]} {coords[1]}"
    assert is_within_range(inc_lat_lon, polyline_str, max_miles=1.0)

def test_mid_route_sepulveda_pass_incident(van_nuys_to_santa_monica_route):
    polyline_str = van_nuys_to_santa_monica_route["polyline"]
    inc_lat_lon = "34.1275 -118.4830"
    assert is_within_range(inc_lat_lon, polyline_str, max_miles=2.0)

def test_distant_downtown_la_incident(van_nuys_to_santa_monica_route):
    polyline_str = van_nuys_to_santa_monica_route["polyline"]
    inc_lat_lon = "34.0537 -118.2427"
    assert not is_within_range(inc_lat_lon, polyline_str, max_miles=2.0)


# --- Golf Course Commute Tests (I-405 Route) ---

def test_origin_meadowlark_incident(golf_commute_route):
    coords = golf_commute_route["origin_coords"]
    polyline_str = golf_commute_route["polyline"]
    inc_lat_lon = f"{coords[0]} {coords[1]}"
    assert is_within_range(inc_lat_lon, polyline_str, max_miles=1.5)

def test_destination_alondra_incident(golf_commute_route):
    coords = golf_commute_route["dest_coords"]
    polyline_str = golf_commute_route["polyline"]
    inc_lat_lon = f"{coords[0]} {coords[1]}"
    assert is_within_range(inc_lat_lon, polyline_str, max_miles=1.5)

def test_i405_north_long_beach_incident(golf_commute_route):
    polyline_str = golf_commute_route["polyline"]
    inc_lat_lon = "33.8050 -118.1500"
    assert is_within_range(inc_lat_lon, polyline_str, max_miles=2.0)

def test_i405_north_carson_incident(golf_commute_route):
    polyline_str = golf_commute_route["polyline"]
    inc_lat_lon = "33.8480 -118.2830"
    assert is_within_range(inc_lat_lon, polyline_str, max_miles=2.0)

def test_off_route_anaheim_incident(golf_commute_route):
    polyline_str = golf_commute_route["polyline"]
    inc_lat_lon = "33.8121 -117.9190"
    assert not is_within_range(inc_lat_lon, polyline_str, max_miles=2.0)


# --- Live Scraper Integration Test ---

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.network
def test_live_chp_scrape_against_route(golf_commute_route):
    polyline_str = golf_commute_route["polyline"]
    incidents = fetch_caltrans_incidents("Los Angeles")
    
    assert isinstance(incidents, list)
    assert len(incidents) > 0
    
    matched_count = 0
    for inc in incidents:
        assert "number" in inc
        assert "location" in inc
        lat_lon = inc.get("details", {}).get("lat_lon")
        if is_within_range(lat_lon, polyline_str, max_miles=3.0):
            matched_count += 1
            
    print(f"\n[pytest integration] Found {matched_count}/{len(incidents)} live incidents near route.")
