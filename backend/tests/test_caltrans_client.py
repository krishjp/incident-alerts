import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from caltrans_client import CaltransAPIClient, fetch_caltrans_incidents, resolve_feed_url

SAMPLE_KML_PAYLOAD = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>CHP Incidents</name>
<Placemark>
  <name> </name>
  <description><![CDATA[
<div class="infowindow-content">
    <div class="iw-header">
        <div class="iw-header-left">CHP Incident 260731LA0100</div>
    </div>
    <div class="iw-body">
        <h2 class="iw-title">1183-Trfc Collision-Unkn Inj</h2>
        <p class="iw-text">Jul 31 2026 09:00AM <br> I-405 S / Wilshire Blvd</p>
        <p class="iw-text">Jul 31 2026 09:01AM [2] VEHICLE OFF SHOULDER<br />Jul 31 2026 09:00AM [1] 2 VEH TC</p>
    </div>
</div>
  ]]></description>
  <Point><coordinates>-118.4550,34.0500,0</coordinates></Point>
</Placemark>
<Placemark>
  <name> </name>
  <description><![CDATA[
<div class="infowindow-content">
    <div class="iw-header">
        <div class="iw-header-left">CHP Incident 260731SA0200</div>
    </div>
    <div class="iw-body">
        <h2 class="iw-title">1182-Trfc Collision-No Inj</h2>
        <p class="iw-text">Jul 31 2026 09:10AM <br> Watt Ave / I-80</p>
        <p class="iw-text">Jul 31 2026 09:10AM [1] MINOR FENDER BENDER</p>
    </div>
</div>
  ]]></description>
  <Point><coordinates>-121.3800,38.6000,0</coordinates></Point>
</Placemark>
</Document>
</kml>
"""

class MockCaltransClient(CaltransAPIClient):
    def fetch_raw_feed(self) -> bytes:
        return SAMPLE_KML_PAYLOAD

def test_mock_kml_parsing():
    client = MockCaltransClient()
    incidents = client.get_incidents()
    assert len(incidents) == 2
    
    inc1 = incidents[0]
    assert inc1["number"] == "260731LA0100"
    assert inc1["type"] == "1183-Trfc Collision-Unkn Inj"
    assert inc1["location"] == "I-405 S / Wilshire Blvd"
    assert inc1["area"] == "Los Angeles"
    assert inc1["details"]["lat_lon"] == "34.0500 -118.4550"
    assert len(inc1["details"]["raw_log"]) == 2

def test_area_filtering():
    client = MockCaltransClient()
    la_incidents = client.get_incidents(area_name="Los Angeles")
    assert len(la_incidents) == 1
    assert la_incidents[0]["number"] == "260731LA0100"

    sac_incidents = client.get_incidents(area_name="Sacramento")
    assert len(sac_incidents) == 1
    assert sac_incidents[0]["number"] == "260731SA0200"

@pytest.mark.network
def test_live_caltrans_fetch():
    incidents = fetch_caltrans_incidents()
    assert isinstance(incidents, list)
    assert len(incidents) > 0
    first = incidents[0]
    assert "number" in first
    assert "details" in first
    assert "lat_lon" in first["details"]


class TestResolveFeedUrl:
    def test_unset_or_empty_uses_live_feed(self):
        assert resolve_feed_url(None) == CaltransAPIClient.DEFAULT_KML_URL
        assert resolve_feed_url("") == CaltransAPIClient.DEFAULT_KML_URL

    def test_url_with_scheme_is_unchanged(self):
        assert resolve_feed_url("https://example.com/feed.kml") == "https://example.com/feed.kml"

    def test_relative_path_resolves_against_backend_dir(self):
        backend_dir = Path(__file__).resolve().parent.parent
        expected = backend_dir / "fixtures" / "torrance_hb_405_test.kml"
        assert resolve_feed_url("fixtures/torrance_hb_405_test.kml") == expected.as_uri()

