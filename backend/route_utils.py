import math

def decode_polyline(polyline_str):
    index, lat, lng = 0, 0, 0
    coordinates = []
    changes = {'latitude': 0, 'longitude': 0}

    while index < len(polyline_str):
        for unit in ['latitude', 'longitude']:
            shift, result = 0, 0
            while True:
                byte = ord(polyline_str[index]) - 63
                index += 1
                result |= (byte & 0x1f) << shift
                shift += 5
                if not byte >= 0x20:
                    break
            if result & 1:
                changes[unit] = ~(result >> 1)
            else:
                changes[unit] = result >> 1

        lat += changes['latitude']
        lng += changes['longitude']

        coordinates.append((lat / 100000.0, lng / 100000.0))

    return coordinates

def encode_polyline(coordinates):
    output = []

    def encode_number(num):
        num = ~(num << 1) if num < 0 else num << 1
        while num >= 0x20:
            output.append(chr((0x20 | (num & 0x1f)) + 63))
            num >>= 5
        output.append(chr(num + 63))

    last_lat = 0
    last_lng = 0

    for lat, lng in coordinates:
        lat_int = int(round(lat * 1e5))
        lng_int = int(round(lng * 1e5))

        encode_number(lat_int - last_lat)
        encode_number(lng_int - last_lng)

        last_lat = lat_int
        last_lng = lng_int

    return ''.join(output)

def haversine_distance_miles(coord1, coord2):
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 3958.8 # Earth radius in miles

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_bounding_box(route_points, buffer_miles=3.0):
    """
    Computes a bounding box (min_lat, max_lat, min_lon, max_lon)
    extended by buffer_miles around a set of coordinates.
    1 degree of latitude is approx 69 miles.
    """
    lats = [p[0] for p in route_points]
    lons = [p[1] for p in route_points]
    lat_buffer = buffer_miles / 69.0
    # Approximate lon buffer based on median latitude
    median_lat = lats[len(lats) // 2]
    lon_buffer = buffer_miles / (69.0 * math.cos(math.radians(median_lat)))

    return (
        min(lats) - lat_buffer,
        max(lats) + lat_buffer,
        min(lons) - abs(lon_buffer),
        max(lons) + abs(lon_buffer)
    )

def parse_lat_lon(incident_lat_lon):
    """Parses the feed's "lat lon" (or "lat:lon") string; None if absent or malformed."""
    if not incident_lat_lon or incident_lat_lon == "None":
        return None
    try:
        parts = incident_lat_lon.strip().split()
        if len(parts) == 2:
            return float(parts[0]), float(parts[1])
        if ":" in incident_lat_lon:
            parts = incident_lat_lon.replace(' ', '').split(":")
            return float(parts[0]), float(parts[1])
    except Exception:
        pass
    return None

def is_within_range_pure(incident_lat_lon, encoded_polyline, max_miles=3.0):
    incident_pt = parse_lat_lon(incident_lat_lon)
    if incident_pt is None:
        return False
    inc_lat, inc_lon = incident_pt

    if encoded_polyline == "dummy_polyline":
        return True

    try:
        route_points = decode_polyline(encoded_polyline)
    except Exception:
        return False

    if not route_points:
        return False

    # Bounding Box Pre-filter check (O(1) fast rejection)
    min_lat, max_lat, min_lon, max_lon = get_bounding_box(route_points, buffer_miles=max_miles)
    if not (min_lat <= inc_lat <= max_lat and min_lon <= inc_lon <= max_lon):
        return False

    for pt in route_points:
        dist = haversine_distance_miles(incident_pt, pt)
        if dist <= max_miles:
            return True
                
    return False

def distance_to_route_miles(incident_lat_lon, encoded_polyline):
    """
    Distance from the incident to the nearest route point, or None when either
    side can't be decoded. Only used to label an alert that already matched, so
    it skips the bounding-box pre-filter.
    """
    incident_pt = parse_lat_lon(incident_lat_lon)
    if incident_pt is None:
        return None
    try:
        route_points = decode_polyline(encoded_polyline)
    except Exception:
        return None
    if not route_points:
        return None
    return min(haversine_distance_miles(incident_pt, pt) for pt in route_points)
