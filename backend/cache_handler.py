import hashlib
from typing import Optional

from config import settings
from redis_client import get_redis_client

class IncidentCache:
    """
    Cache handler for AI incident summaries and operational states.
    Uses Redis when available with automatic 24-hour TTL expiration.
    Falls back transparently to an in-memory dictionary if Redis is offline/unreachable.
    """

    def __init__(self, default_ttl: int = 86400, client: Optional[object] = None):
        self.redis_host = settings.redis_host
        self.redis_port = settings.redis_port
        self.redis_db = settings.redis_db
        self.default_ttl = default_ttl
        # Connection details (including a managed provider's REDIS_URL) and the
        # connect-once-and-remember behaviour live in redis_client.
        self.redis_client = client if client is not None else get_redis_client()
        self._memory_cache = {}

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
