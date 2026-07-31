import os
import hashlib
import json
from typing import Optional, Any

try:
    import redis
except ImportError:
    redis = None

class IncidentCache:
    """
    Cache handler for AI incident summaries and operational states.
    Uses Redis when available with automatic 24-hour TTL expiration.
    Falls back transparently to an in-memory dictionary if Redis is offline/unreachable.
    """

    def __init__(self, redis_host: Optional[str] = None, redis_port: int = 6379, redis_db: int = 0, default_ttl: int = 86400):
        self.redis_host = redis_host or os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", redis_port))
        self.redis_db = int(os.getenv("REDIS_DB", redis_db))
        self.default_ttl = default_ttl
        self.redis_client = None
        self._memory_cache = {}

        self._connect()

    def _connect(self):
        """Attempts to establish connection to Redis server."""
        if redis is None:
            print("[Cache Warning] redis python package not installed. Using in-memory fallback.")
            return

        try:
            client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                socket_timeout=1.0,
                decode_responses=True
            )
            # Ping Redis server to confirm connection
            if client.ping():
                self.redis_client = client
                print(f"[Cache Info] Connected to Redis at {self.redis_host}:{self.redis_port}")
        except Exception:
            # Fall back silently to in-memory cache if Redis is not running locally
            self.redis_client = None

    def _generate_cache_key(self, incident_number: str, raw_details: str) -> str:
        """Generates a deterministic Redis key based on incident ID and details hash."""
        details_hash = hashlib.sha256(raw_details.encode("utf-8")).hexdigest()[:16]
        return f"incident:summary:{incident_number}:{details_hash}"

    def get_summary(self, incident_number: str, raw_details: str) -> Optional[str]:
        """Retrieves cached incident summary from Redis or in-memory fallback."""
        key = self._generate_cache_key(incident_number, raw_details)

        if self.redis_client:
            try:
                val = self.redis_client.get(key)
                if val:
                    return val
            except Exception as e:
                print(f"[Redis Get Error] {e}")

        return self._memory_cache.get(key)

    def set_summary(self, incident_number: str, raw_details: str, summary: str, ttl: Optional[int] = None) -> bool:
        """Stores incident summary in Redis with TTL expiration (default 24h) or in-memory fallback."""
        key = self._generate_cache_key(incident_number, raw_details)
        expire_seconds = ttl if ttl is not None else self.default_ttl

        # Always update in-memory fallback
        self._memory_cache[key] = summary

        if self.redis_client:
            try:
                self.redis_client.set(key, summary, ex=expire_seconds)
                return True
            except Exception as e:
                print(f"[Redis Set Error] {e}")
                return False

        return True

    def clear(self):
        """Clears memory fallback and flushes Redis db if connected."""
        self._memory_cache.clear()
        if self.redis_client:
            try:
                self.redis_client.flushdb()
            except Exception:
                pass


# Global cache instance for backend application
global_incident_cache = IncidentCache()
