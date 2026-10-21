import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json

from notification_queue import NotificationQueue, NotificationTask, TaskStore, TaskStatus


class FakeRedis:
    """Minimal in-process stand-in for the Redis hash commands TaskStore uses."""

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))


class FlakyRedis(FakeRedis):
    def hset(self, key, field, value):
        raise ConnectionError("redis went away")


def make_queue(redis, sender):
    return NotificationQueue(sender_func=sender, store=TaskStore(client=redis))


def always_fails(to_phone, message):
    raise RuntimeError("carrier rejected")


def always_succeeds(to_phone, message):
    return True


class TestTaskRoundTrip:
    def test_to_dict_from_dict_preserves_retry_state(self):
        original = NotificationTask(
            to_phone="+15551234567",
            message="Incident Alert",
            max_retries=5,
            attempts=2,
            backoff_factor=2.5,
            status=TaskStatus.FAILED,
            last_error="timeout",
            next_attempt_at=1234.5,
        )
        restored = NotificationTask.from_dict(json.loads(json.dumps(original.to_dict())))

        assert restored.task_id == original.task_id
        assert restored.attempts == 2
        # backoff_factor must survive: without it a restored task restarts its
        # backoff schedule from the default and can hammer a failing carrier.
        assert restored.backoff_factor == 2.5
        assert restored.status == TaskStatus.FAILED
        assert restored.next_attempt_at == 1234.5


class TestDurability:
    def test_pending_task_survives_restart(self):
        redis = FakeRedis()
        queue = make_queue(redis, always_fails)
        task = queue.enqueue("+15551234567", "Alert", max_retries=3, backoff_factor=10.0)

        # First attempt fails and schedules a retry well in the future.
        queue.process_queue(now=task.next_attempt_at)
        assert task.attempts == 1

        # Simulate a redeploy: brand new process, same Redis.
        restarted = make_queue(redis, always_succeeds)
        assert len(restarted.pending_tasks) == 1
        restored = restarted.pending_tasks[0]
        assert restored.task_id == task.task_id
        assert restored.attempts == 1
        assert restored.message == "Alert"

        # The retry is delivered after the restart rather than being lost.
        stats = restarted.process_queue(now=restored.next_attempt_at)
        assert stats["succeeded"] == 1
        assert redis.hashes.get(TaskStore.PENDING_KEY) in (None, {})

    def test_delivered_task_is_not_replayed_after_restart(self):
        redis = FakeRedis()
        sent = []
        queue = make_queue(redis, lambda p, m: sent.append((p, m)) or True)
        queue.enqueue("+15551234567", "Alert")
        queue.process_queue()

        restarted = make_queue(redis, lambda p, m: sent.append((p, m)) or True)
        restarted.process_queue()

        # A duplicate here would mean users get the same SMS again on every deploy.
        assert len(sent) == 1
        assert restarted.pending_tasks == []

    def test_dlq_task_survives_restart_and_can_be_requeued(self):
        redis = FakeRedis()
        queue = make_queue(redis, always_fails)
        task = queue.enqueue("+15550001111", "Alert", max_retries=1, backoff_factor=0.1)
        queue.process_queue()
        assert len(queue.get_dlq()) == 1

        restarted = make_queue(redis, always_succeeds)
        assert len(restarted.get_dlq()) == 1
        assert restarted.pending_tasks == []

        assert restarted.retry_dlq_task(task.task_id) is True
        assert restarted.get_dlq() == []
        assert redis.hashes.get(TaskStore.DLQ_KEY) in (None, {})
        assert restarted.process_queue()["succeeded"] == 1

    def test_clear_dlq_clears_persisted_copies(self):
        redis = FakeRedis()
        queue = make_queue(redis, always_fails)
        queue.enqueue("+15550001111", "A", max_retries=1)
        queue.enqueue("+15550002222", "B", max_retries=1)
        queue.process_queue()
        assert queue.clear_dlq() == 2

        assert make_queue(redis, always_succeeds).get_dlq() == []


class TestDegradation:
    def test_queue_works_without_redis(self):
        # store=None is the no-Redis path: alerts must still be delivered, just
        # without the cross-restart guarantee.
        queue = NotificationQueue(sender_func=always_succeeds, store=None)
        queue.enqueue("+15551234567", "Alert")
        assert queue.process_queue()["succeeded"] == 1

    def test_persistence_failure_does_not_break_delivery(self):
        queue = make_queue(FlakyRedis(), always_succeeds)
        queue.enqueue("+15551234567", "Alert")
        assert queue.process_queue()["succeeded"] == 1

    def test_unreadable_persisted_task_is_dropped_not_fatal(self):
        redis = FakeRedis()
        redis.hset(TaskStore.PENDING_KEY, "corrupt", "{not json")
        queue = make_queue(redis, always_succeeds)

        assert queue.pending_tasks == []
        assert "corrupt" not in redis.hashes.get(TaskStore.PENDING_KEY, {})
