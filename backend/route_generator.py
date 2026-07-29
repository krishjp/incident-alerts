import urllib.parse
import urllib.request
import json
import math
from route_utils import encode_polyline

def fetch_osrm_polyline(origin_address: str, destination_address: str):
    """
    Geocodes origin and destination street addresses via Nominatim (OpenStreetMap),
    then fetches the exact turn-by-turn routing polyline from OSRM.
    Returns: (origin_coords, dest_coords, encoded_polyline)
    """
    headers = {"User-Agent": "CHPIncidentAlerts/1.0"}

    def geocode(address):
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(address)}&format=json&limit=1"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
            raise ValueError(f"Could not geocode address: '{address}'")

    origin_lat, origin_lon = geocode(origin_address)
    dest_lat, dest_lon = geocode(destination_address)

    # Fetch OSRM route polyline (lon,lat order for OSRM API)
    osrm_url = f"http://router.project-osrm.org/route/v1/driving/{origin_lon},{origin_lat};{dest_lon},{dest_lat}?overview=full&geometries=polyline"
    req_osrm = urllib.request.Request(osrm_url, headers=headers)
    
    with urllib.request.urlopen(req_osrm) as resp:
        osrm_data = json.loads(resp.read().decode('utf-8'))
        if osrm_data.get("code") == "Ok" and osrm_data.get("routes"):
            polyline_str = osrm_data["routes"][0]["geometry"]
            return (origin_lat, origin_lon), (dest_lat, dest_lon), polyline_str

    raise RuntimeError("OSRM route lookup failed")
