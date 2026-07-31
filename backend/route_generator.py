import requests
from route_utils import encode_polyline

def geocode_address(address_str: str):
    """Geocodes a street address to (lat, lon) using OpenStreetMap Nominatim."""
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "IncidentAlerts/1.0"}
    params = {
        "q": address_str,
        "format": "json",
        "limit": 1
    }
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    data = resp.json()
    if not data:
        raise ValueError(f"Could not geocode address: {address_str}")
    
    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return lat, lon

def fetch_osrm_polyline(origin_address: str, dest_address: str):
    """
    Fetches driving polyline between origin and destination street addresses
    using OpenSourceRoutingMachine (OSRM) API.
    """
    origin_lat, origin_lon = geocode_address(origin_address)
    dest_lat, dest_lon = geocode_address(dest_address)

    # OSRM expects coordinates in lon,lat order: lon1,lat1;lon2,lat2
    osrm_url = f"http://router.project-osrm.org/route/v1/driving/{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
    params = {
        "overview": "full",
        "geometries": "geojson"
    }
    headers = {"User-Agent": "IncidentAlerts/1.0"}
    resp = requests.get(osrm_url, params=params, headers=headers, timeout=10)
    data = resp.json()

    if "routes" not in data or not data["routes"]:
        raise ValueError(f"No route found between {origin_address} and {dest_address}")

    # OSRM GeoJSON geometry returns [lon, lat] list
    coordinates_lon_lat = data["routes"][0]["geometry"]["coordinates"]
    
    # Convert to (lat, lon) list for polyline encoding
    route_points_lat_lon = [(pt[1], pt[0]) for pt in coordinates_lon_lat]
    
    # Encode as polyline string
    polyline_str = encode_polyline(route_points_lat_lon)

    return (origin_lat, origin_lon), (dest_lat, dest_lon), polyline_str
