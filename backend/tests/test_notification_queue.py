import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from notification_queue import NotificationQueue, TaskStatus

def test_enqueue_and_successful_process():
    sent_messages = []
    def mock_sender(to_phone, msg):
        sent_messages.append((to_phone, msg))
        return True

    queue = NotificationQueue(sender_func=mock_sender)
    task = queue.enqueue("+15551234567", "Test Incident Alert")
    assert task.status == TaskStatus.PENDING
    assert len(queue.pending_tasks) == 1

    stats = queue.process_queue()
    assert stats["processed"] == 1
    assert stats["succeeded"] == 1
    assert len(sent_messages) == 1
    assert len(queue.completed_tasks) == 1
    assert len(queue.pending_tasks) == 0
    assert len(queue.dlq_tasks) == 0

def test_retry_mechanism_and_exponential_backoff():
    attempt_count = 0
    def failing_sender(to_phone, msg):
        nonlocal attempt_count
        attempt_count += 1
        raise ConnectionError("Simulated network timeout")

    queue = NotificationQueue(sender_func=failing_sender)
    task = queue.enqueue("+15559998888", "Failing Alert", max_retries=3, backoff_factor=10.0)

    start_time = time.time()

    # Attempt 1: Fails -> Schedules retry with 10s delay
    stats1 = queue.process_queue(now=start_time)
    assert stats1["processed"] == 1
    assert stats1["retried"] == 1
    assert task.attempts == 1
    assert task.status == TaskStatus.FAILED
    assert task.next_attempt_at == start_time + 10.0

    # Attempt 2 (Too early): Task should be skipped because backoff time hasn't elapsed
    stats2 = queue.process_queue(now=start_time + 2.0)
    assert stats2["processed"] == 0

    # Attempt 2 (On time): Fails -> Schedules retry with 20s delay (10 * 2^1)
    stats3 = queue.process_queue(now=start_time + 10.1)
    assert stats3["processed"] == 1
    assert stats3["retried"] == 1
    assert task.attempts == 2
    assert task.next_attempt_at == (start_time + 10.1) + 20.0

def test_dead_letter_queue_on_max_retries():
    def failing_sender(to_phone, msg):
        raise RuntimeError("Twilio Invalid Phone Number Error")

    queue = NotificationQueue(sender_func=failing_sender)
    task = queue.enqueue("+15550001111", "Dead Letter Alert", max_retries=2, backoff_factor=0.1)

    t0 = time.time()
    
    # Attempt 1 -> Failed, retried
    queue.process_queue(now=t0)
    assert task.attempts == 1
    assert len(queue.dlq_tasks) == 0

    # Attempt 2 (Max retries = 2 reached) -> Moved to DLQ
    queue.process_queue(now=t0 + 1.0)
    assert task.attempts == 2
    assert task.status == TaskStatus.DLQ
    assert len(queue.dlq_tasks) == 1
    assert len(queue.pending_tasks) == 0

def test_dlq_requeueing():
    def failing_sender(to_phone, msg):
        raise RuntimeError("Fail")

    queue = NotificationQueue(sender_func=failing_sender)
    task = queue.enqueue("+15552223333", "DLQ Requeue Test", max_retries=1, backoff_factor=0.1)
    
    # Send to DLQ
    queue.process_queue()
    assert len(queue.get_dlq()) == 1

    # Re-queue task from DLQ
    restored = queue.retry_dlq_task(task.task_id)
    assert restored is True
    assert len(queue.get_dlq()) == 0
    assert len(queue.pending_tasks) == 1
    assert queue.pending_tasks[0].status == TaskStatus.PENDING
