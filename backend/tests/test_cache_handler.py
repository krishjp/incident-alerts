import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import uuid

import pytest
from cache_handler import IncidentCache

def test_cache_get_and_set():
    cache = IncidentCache()

    # Unique per run: set_summary writes through to Redis with a 24h TTL when one
    # is reachable, so a fixed key makes the cache-miss assertion below pass only
    # on the first run of the day.
    incident_num = f"TEST-{uuid.uuid4().hex[:12]}"
    details = "Debris in lanes 1 and 2"
    summary = "Traffic Hazard on I-405 S: Debris in lanes."

    # Cache Miss
    assert cache.get_summary(incident_num, details) is None

    # Cache Set
    cache.set_summary(incident_num, details, summary)

    # Cache Hit
    cached = cache.get_summary(incident_num, details)
    assert cached == summary

def test_cache_key_hashing():
    cache = IncidentCache()
    key1 = cache._generate_cache_key("1001", "Details A")
    key2 = cache._generate_cache_key("1001", "Details B")
    
    assert key1 != key2
    assert "1001" in key1
