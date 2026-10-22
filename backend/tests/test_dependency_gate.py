import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import main
from notification_queue import NotificationQueue, TaskStore
from redis_client import DependencyUnavailable


class BrokenRedis:
    def hset(self, *a, **k):
        raise ConnectionError("redis down")

    def hdel(self, *a, **k):
        raise ConnectionError("redis down")

    def hgetall(self, *a, **k):
        raise ConnectionError("redis down")


class TestStrictTaskStore:
    def test_raises_when_redis_errors(self):
        queue = NotificationQueue(store=TaskStore(client=BrokenRedis(), strict=True))
        with pytest.raises(DependencyUnavailable):
            queue.enqueue("+15551234567", "hello")
        # The task never entered the in-process queue either.
        assert queue.pending_tasks == []

    def test_raises_when_redis_missing(self):
        store = TaskStore(client=None, strict=True)
        store.client = None  # get_redis_client() may have found a real local Redis
        queue = NotificationQueue(store=store)
        with pytest.raises(DependencyUnavailable):
            queue.enqueue("+15551234567", "hello")

    def test_non_strict_store_still_degrades(self):
        queue = NotificationQueue(store=TaskStore(client=BrokenRedis()))
        queue.enqueue("+15551234567", "hello")
        assert len(queue.pending_tasks) == 1


class TestMainRefusesToRun:
    def test_exits_nonzero_without_polling_when_a_dependency_is_down(self, monkeypatch):
        monkeypatch.setattr(main, "check_dependencies", lambda: ["Redis unreachable"])
        monkeypatch.setattr(main, "check_and_notify", lambda: pytest.fail("must not poll"))
        with pytest.raises(SystemExit) as exc:
            main.main()
        assert exc.value.code == 1

    def test_dispatch_holds_alerts_when_a_dependency_is_down(self, monkeypatch):
        queue = SimpleNamespace(pending_tasks=[object()],
                                process_queue=lambda: pytest.fail("must not send"))
        monkeypatch.setattr(main, "global_notification_queue", queue)
        monkeypatch.setattr(main, "check_dependencies", lambda: ["Postgres unreachable"])
        with pytest.raises(DependencyUnavailable):
            main.dispatch_queue()


class _TransactionalDb:
    """Buffers adds and only keeps them if the session_scope block succeeds."""

    def __init__(self):
        self.committed = {}
        self._staged = {}

    def query(self, _model):
        rows = list(self.committed.values())
        return SimpleNamespace(filter=lambda *_: SimpleNamespace(all=lambda: rows))

    def add(self, record):
        self._staged[record.id] = record


def test_queue_write_failure_rolls_back_fingerprints_and_sends_nothing(monkeypatch):
    db = _TransactionalDb()

    @contextmanager
    def session_scope():
        db._staged = {}
        yield db
        db.committed.update(db._staged)  # only reached when the block didn't raise

    sent = []
    queue = NotificationQueue(sender_func=lambda p, m: sent.append(m) or True,
                              store=TaskStore(client=BrokenRedis(), strict=True))
    sub = SimpleNamespace(id="sub1", origin="A", destination="B", polyline="x")
    incident = {"number": "LA01", "location": "I-405", "location_desc": "",
                "details": {"lat_lon": "33.8 -118.3", "full_text_blob": "collision"}}

    monkeypatch.setattr(main, "get_active_subscriptions",
                        lambda: [{"sub": sub, "phone": "+15551234567", "user": "u"}])
    monkeypatch.setattr(main, "fetch_caltrans_incidents", lambda: [incident])
    monkeypatch.setattr(main, "is_within_range", lambda *a, **k: True)
    monkeypatch.setattr(main, "summarize_incident", lambda inc: "Collision on I-405.")
    monkeypatch.setattr(main, "session_scope", session_scope)
    monkeypatch.setattr(main, "global_notification_queue", queue)
    monkeypatch.setattr(main, "check_dependencies", lambda: [])

    with pytest.raises(DependencyUnavailable):
        main.check_and_notify()

    # Not fingerprinted, so the first pass after Redis recovers alerts again...
    assert db.committed == {}
    # ...and nothing was sent or left queued in the meantime.
    assert sent == []
    assert queue.pending_tasks == []
