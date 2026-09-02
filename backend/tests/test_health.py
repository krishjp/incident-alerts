import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time

import health


class TestHealthSnapshot:
    def setup_method(self):
        health._last_success_at = None
        health._started_at = time.time()

    def test_healthy_during_startup_before_first_cycle(self):
        healthy, payload = health.health_snapshot(poll_interval=60)
        assert healthy is True
        assert payload["seconds_since_last_cycle"] is None

    def test_unhealthy_if_first_cycle_never_completes(self):
        # Started long ago, no cycle ever recorded — a worker wedged on startup.
        health._started_at = time.time() - 500
        healthy, payload = health.health_snapshot(poll_interval=60)
        assert healthy is False
        assert payload["status"] == "stalled"

    def test_healthy_after_recent_cycle(self):
        health.mark_cycle_complete()
        healthy, payload = health.health_snapshot(poll_interval=60)
        assert healthy is True
        assert payload["status"] == "ok"
        assert payload["seconds_since_last_cycle"] < 1

    def test_unhealthy_once_cycles_stop(self):
        # Liveness must fail on a stalled loop, not just a dead process:
        # a hung worker that still answers HTTP would otherwise stay in service.
        health.mark_cycle_complete()
        health._last_success_at = time.time() - (60 * health.STALL_MULTIPLIER + 5)

        healthy, payload = health.health_snapshot(poll_interval=60)
        assert healthy is False
        assert payload["status"] == "stalled"

    def test_threshold_scales_with_poll_interval(self):
        health.mark_cycle_complete()
        health._last_success_at = time.time() - 200

        # Stale against a 60s loop, fine against a 600s one.
        assert health.health_snapshot(poll_interval=60)[0] is False
        assert health.health_snapshot(poll_interval=600)[0] is True
