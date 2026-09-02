"""
Shared Redis connection factory.

Both the AI-summary cache (`cache_handler`) and the durable notification queue
(`notification_queue`) talk to the same Redis instance, so connection details
live here rather than being re-derived from the environment in each module.

Every caller must tolerate `None` — Redis is a performance/durability
optimization in this system, never a hard dependency. When it is unreachable
the cache falls back to an in-memory dict and the notification queue falls back
to in-process-only durability.
"""

from typing import Optional

from config import settings

try:
    import redis
except ImportError:  # pragma: no cover - redis is a declared dependency
    redis = None

_client = None
_connect_attempted = False


def get_redis_client(force_reconnect: bool = False):
    """
    Returns a connected Redis client, or None when Redis is unavailable.

    The connection is attempted once per process; a failure is cached so every
    cache lookup in the polling loop doesn't pay a fresh connection timeout.
    """
    global _client, _connect_attempted

    if force_reconnect:
        _client = None
        _connect_attempted = False

    if _connect_attempted:
        return _client

    _connect_attempted = True

    if redis is None:
        print("[Redis] python 'redis' package not installed — using in-memory fallbacks.")
        return None

    try:
        if settings.redis_url:
            # Managed providers (Upstash, Memorystore, Redis Cloud) hand out a
            # single redis:// or rediss:// URL carrying host, port, and password.
            client = redis.Redis.from_url(
                settings.redis_url,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                decode_responses=True,
            )
            target = "REDIS_URL"
        else:
            client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                decode_responses=True,
            )
            target = f"{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"

        if client.ping():
            print(f"[Redis] Connected ({target}).")
            _client = client
    except Exception as exc:
        print(f"[Redis] Unavailable ({type(exc).__name__}: {exc}) — using in-memory fallbacks.")
        _client = None

    return _client


def reset_for_tests() -> None:
    """Clears the memoized client so a test can re-run connection logic."""
    global _client, _connect_attempted
    _client = None
    _connect_attempted = False
