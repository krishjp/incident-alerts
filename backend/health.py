"""
Minimal liveness/readiness HTTP endpoint for the worker.

The worker is a polling loop with no HTTP API, but container platforms need
something to probe: Cloud Run will not consider a revision healthy unless the
container listens on $PORT, and orchestrators generally want a liveness URL.
This serves that and nothing else, on a daemon thread so it never keeps the
process alive on its own.

Endpoints:
  GET /healthz  -> 200 while the poll loop is running on schedule, 503 if it has
                   gone longer than the stall threshold without completing a pass
  GET /         -> same as /healthz
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

# Updated by the worker at the end of every successful poll cycle. A liveness
# probe that only checks "is the process up" would keep a wedged worker in
# service, so /healthz fails once the loop stops making progress.
_last_success_at: Optional[float] = None
_started_at = time.time()
_lock = threading.Lock()

# How many missed poll cycles before the worker is reported unhealthy.
STALL_MULTIPLIER = 3


def mark_cycle_complete() -> None:
    """Called by the worker after each completed poll cycle."""
    global _last_success_at
    with _lock:
        _last_success_at = time.time()


def health_snapshot(poll_interval: int) -> tuple[bool, dict]:
    with _lock:
        last = _last_success_at

    now = time.time()
    stall_threshold = poll_interval * STALL_MULTIPLIER

    if last is None:
        # Still starting up: healthy until the first cycle is overdue.
        healthy = (now - _started_at) < stall_threshold
        age = None
    else:
        age = round(now - last, 1)
        healthy = age < stall_threshold

    return healthy, {
        "status": "ok" if healthy else "stalled",
        "uptime_seconds": round(now - _started_at, 1),
        "seconds_since_last_cycle": age,
        "poll_interval_seconds": poll_interval,
    }


class _HealthHandler(BaseHTTPRequestHandler):
    poll_interval = 60

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path.split("?")[0] not in ("/", "/healthz", "/health"):
            self.send_response(404)
            self.end_headers()
            return

        healthy, payload = health_snapshot(self.poll_interval)
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200 if healthy else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Silences per-request logging — probes would otherwise flood the logs."""
        return


def start_health_server(port: int, poll_interval: int = 60):
    """Starts the health server on a daemon thread. Never raises."""
    _HealthHandler.poll_interval = poll_interval
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    except OSError as exc:
        # A bound port shouldn't take down the worker — alerting still works.
        print(f"[Health] Could not bind port {port}: {exc}. Continuing without health endpoint.")
        return None

    thread = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
    thread.start()
    print(f"[Health] Liveness endpoint listening on :{port}/healthz")
    return server
