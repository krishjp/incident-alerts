"""
Shared Redis connection factory.

Both the AI-summary cache (`cache_handler`) and the durable notification queue
(`notification_queue`) talk to the same Redis instance, so connection details
live here rather than being re-derived from the environment in each module.

`get_redis_client` returns None when Redis is unreachable. The summary cache
tolerates that (in-memory fallback), but the worker as a whole does not: Redis
holds the run lock and the durable notification queue, so main.py refuses to
run — and refuses to send — unless both Redis and Postgres are reachable. See
`DependencyUnavailable`.
"""

import uuid
from contextlib import contextmanager
from typing import Optional

from config import settings

try:
    import redis
except ImportError:  # pragma: no cover - redis is a declared dependency
    redis = None

_client = None
_connect_attempted = False


class DependencyUnavailable(RuntimeError):
    """Redis or Postgres is unreachable, so the worker must stop without sending."""


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
        print("[Redis] python 'redis' package not installed - using in-memory fallbacks.")
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
        print(f"[Redis] Unavailable ({type(exc).__name__}: {exc}) - using in-memory fallbacks.")
        _client = None

    return _client


# Distinguishes "caller didn't specify a client" (look one up) from an explicit
# client=None meaning "there is no Redis" — which tests need to exercise.
_UNSET = object()


@contextmanager
def single_run_lock(name: str, ttl_seconds: int, client=_UNSET):
    """
    Best-effort mutual exclusion across processes, yielding True when acquired.

    Needed because Cloud Scheduler fires the worker Job on a fixed interval and
    does not wait for the previous execution to finish. Two concurrent runs
    would both match every subscription and race on the `NotifiedIncident`
    fingerprint row — the same reason a long-lived deployment is pinned to one
    instance. A slow run (a stalled Caltrans fetch, a slow Gemini call) is
    exactly when overlap happens, so this is not a theoretical case.

    SET NX EX gives atomic acquire-with-expiry, so a run that dies without
    releasing the lock cannot wedge every future run — the key expires on its
    own after ttl_seconds. Set the TTL above the worst-case run time and below
    the point where skipping cycles matters.

    Fails closed: raises DependencyUnavailable when Redis is unreachable rather
    than running without overlap protection, since an unprotected overlap is
    exactly what double-sends alerts.
    """
    redis = get_redis_client() if client is _UNSET else client

    if redis is None:
        raise DependencyUnavailable("Redis unavailable - cannot take the run lock.")

    key = f"lock:{name}"
    token = str(uuid.uuid4())
    acquired = False

    try:
        acquired = bool(redis.set(key, token, nx=True, ex=ttl_seconds))
    except Exception as exc:
        raise DependencyUnavailable(
            f"Could not acquire run lock ({type(exc).__name__}: {exc})."
        ) from exc

    if not acquired:
        yield False
        return

    try:
        yield True
    finally:
        try:
            # Only delete the lock if it is still ours: a run that overran its
            # TTL must not delete the lock a later run legitimately holds.
            if redis.get(key) == token:
                redis.delete(key)
        except Exception as exc:
            print(f"[Lock] Could not release ({type(exc).__name__}: {exc}); it expires in {ttl_seconds}s.")


def reset_for_tests() -> None:
    """Clears the memoized client so a test can re-run connection logic."""
    global _client, _connect_attempted
    _client = None
    _connect_attempted = False
