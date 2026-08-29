import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from typing import List, Dict, Any, Optional

from data_classes import Incident, IncidentDetails

# Area prefix mapping to resolve CAD incident number prefixes to region names
AREA_PREFIXES = {
    "LA": "Los Angeles",
    "SA": "Sacramento",
    "IN": "Inland",
    "GG": "Golden Gate",
    "SD": "San Diego",
    "OR": "Orange County",
    "CC": "Central",
    "BORDER": "Border"
}

class CaltransAPIClient:
    """
    API Handler for Caltrans QuickMap real-time traffic incident XML/KML feeds.
    Replaces legacy Selenium web scraping with lightweight direct HTTP feed fetching.
    """

    DEFAULT_KML_URL = "https://quickmap.dot.ca.gov/data/chp-only.kml"

    def __init__(self, feed_url: str = DEFAULT_KML_URL, timeout: int = 10):
        self.feed_url = feed_url
        self.timeout = timeout

    def fetch_raw_feed(self) -> bytes:
        """Fetches the raw KML XML payload from Caltrans QuickMap endpoint."""
        req = urllib.request.Request(
            self.feed_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) IncidentAlertsClient/2.0'}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return response.read()

    def get_incidents(self, area_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Parses live traffic incidents from the Caltrans KML feed.
        Optional area_name filters incidents matching specific regions (e.g. 'Los Angeles').
        Returns list of incident dictionaries aligned with Incident data_class format.
        """
        try:
            content = self.fetch_raw_feed()
        except Exception as e:
            print(f"[Caltrans API Error] Failed to fetch feed from {self.feed_url}: {e}")
            return []

        try:
            root = ET.fromstring(content)
        except Exception as e:
            print(f"[Caltrans API Error] Failed to parse XML structure: {e}")
            return []

        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        placemarks = root.findall('.//kml:Placemark', ns)

        incidents_list = []
        for p in placemarks:
            coord_elem = p.find('.//kml:coordinates', ns)
            desc_elem = p.find('kml:description', ns)
            if coord_elem is None or desc_elem is None:
                continue

            # Parse coordinates (KML stores as longitude, latitude, altitude)
            coords_text = coord_elem.text.strip()
            parts = coords_text.split(',')
            if len(parts) >= 2:
                lon, lat = parts[0].strip(), parts[1].strip()
                lat_lon_val = f"{lat} {lon}"
            else:
                lat_lon_val = None

            desc_html = desc_elem.text or ""

            # Extract Incident Number (e.g. "CHP Incident 260731LA0100" or "Incident 260731LA0100")
            num_match = re.search(r'(?:CHP\s+)?Incident\s+([A-Za-z0-9]+)', desc_html, re.IGNORECASE)
            number = num_match.group(1) if num_match else "UNKNOWN"

            # Determine area from incident ID prefix
            detected_area = "All California"
            for prefix, area in AREA_PREFIXES.items():
                if prefix in number:
                    detected_area = area
                    break

            # Filter by area if requested
            if area_name and area_name.lower() not in ("all", "all california"):
                if area_name.lower() not in detected_area.lower() and detected_area != "All California":
                    continue

            # Extract Incident Type
            title_match = re.search(r'<h2 class="iw-title">(.*?)</h2>', desc_html, re.DOTALL)
            inc_type = unescape(title_match.group(1).strip()) if title_match else "Traffic Incident"

            # Extract Time & Location details
            text_paragraphs = re.findall(r'<p class="iw-text">(.*?)</p>', desc_html, re.DOTALL)
            timestamp, location = "", ""
            details_blob = ""
            raw_logs = []

            if text_paragraphs:
                first_p = text_paragraphs[0]
                first_p_clean = re.sub(r'<br\s*/?>', '\n', first_p, flags=re.IGNORECASE)
                p_lines = [unescape(re.sub(r'<.*?>', '', line).strip('> ').strip()) for line in first_p_clean.split('\n') if line.strip()]
                if len(p_lines) >= 2:
                    timestamp = p_lines[0]
                    location = p_lines[1]
                elif len(p_lines) == 1:
                    timestamp = p_lines[0]

                if len(text_paragraphs) > 1:
                    details_html = text_paragraphs[1]
                    details_clean = re.sub(r'<br\s*/?>', '\n', details_html, flags=re.IGNORECASE)
                    raw_lines = details_clean.split('\n')
                    for rl in raw_lines:
                        clean_line = unescape(re.sub(r'<.*?>', '', rl).strip('> ').strip())
                        if clean_line:
                            raw_logs.append(clean_line)
                    details_blob = "\n".join(raw_logs)

            incident_obj = Incident(
                number=number,
                timestamp=timestamp,
                type=inc_type,
                location=location,
                location_desc="",
                area=detected_area,
                details=IncidentDetails(
                    raw_log=raw_logs,
                    lat_lon=lat_lon_val,
                    full_text_blob=f"Type: {inc_type}\nLocation: {location}\nDetails:\n{details_blob}"
                )
            )

            incidents_list.append(incident_obj.to_dict())

        return incidents_list


# Singleton / Convenience helper function.
# CALTRANS_FEED_URL lets local testing point at a fixture KML file (e.g.
# "file:///abs/path/to/injected_incidents.kml") instead of the live feed —
# urllib.request.urlopen natively supports file:// URLs. Unset in production.
_client = CaltransAPIClient(feed_url=os.getenv("CALTRANS_FEED_URL", CaltransAPIClient.DEFAULT_KML_URL))

def fetch_caltrans_incidents(area_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Helper function to fetch Caltrans incidents using the API client."""
    return _client.get_incidents(area_name=area_name)
