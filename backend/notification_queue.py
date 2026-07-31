import os
import time
import uuid
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Callable, Any

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DLQ = "DEAD_LETTER_QUEUE"

@dataclass
class NotificationTask:
    """Represents a queued outbound SMS notification task."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    to_phone: str = ""
    message: str = ""
    max_retries: int = 3
    attempts: int = 0
    backoff_factor: float = 1.0  # Base retry delay multiplier in seconds
    status: TaskStatus = TaskStatus.PENDING
    last_error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    next_attempt_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "to_phone": self.to_phone,
            "message": self.message,
            "max_retries": self.max_retries,
            "attempts": self.attempts,
            "status": self.status.value,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_attempt_at": self.next_attempt_at,
        }

def default_twilio_sender(to_phone: str, message: str) -> bool:
    """
    Default Twilio SMS dispatch function.
    Uses mock console logging if real Twilio credentials are not configured.
    """
    twilio_phone = os.getenv("TWILIO_PHONE_NUMBER", "+15550000000")
    print(f"\n[DISPATCH SMS to {to_phone}]")
    print(f"From: {twilio_phone}")
    print(f"Message: {message}\n")
    return True

class NotificationQueue:
    """
    Asynchronous / Batched Notification Queue for Twilio SMS dispatch.
    Implements retry logic with exponential backoff and a Dead Letter Queue (DLQ)
    to handle transient network failures or undeliverable alerts.
    """

    def __init__(self, sender_func: Optional[Callable[[str, str], bool]] = None):
        self.sender_func = sender_func or default_twilio_sender
        self.pending_tasks: List[NotificationTask] = []
        self.completed_tasks: List[NotificationTask] = []
        self.dlq_tasks: List[NotificationTask] = []

    def enqueue(self, to_phone: str, message: str, max_retries: int = 3, backoff_factor: float = 1.0) -> NotificationTask:
        """Enqueues a new SMS alert task."""
        task = NotificationTask(
            to_phone=to_phone,
            message=message,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            status=TaskStatus.PENDING,
            next_attempt_at=time.time()
        )
        self.pending_tasks.append(task)
        print(f"[Queue Enqueued] Task {task.task_id[:8]} for {to_phone}")
        return task

    def process_queue(self, now: Optional[float] = None) -> Dict[str, int]:
        """
        Processes pending tasks eligible for execution based on retry backoff schedules.
        Moves successfully delivered tasks to completed_tasks and permanently failed tasks to DLQ.
        """
        current_time = now if now is not None else time.time()
        stats = {"processed": 0, "succeeded": 0, "retried": 0, "dlq": 0}

        remaining_pending: List[NotificationTask] = []

        for task in self.pending_tasks:
            if task.next_attempt_at > current_time:
                # Task is waiting for exponential backoff retry window
                remaining_pending.append(task)
                continue

            stats["processed"] += 1
            task.attempts += 1
            task.status = TaskStatus.PROCESSING
            task.updated_at = current_time

            try:
                success = self.sender_func(task.to_phone, task.message)
                if success:
                    task.status = TaskStatus.SUCCESS
                    task.updated_at = current_time
                    self.completed_tasks.append(task)
                    stats["succeeded"] += 1
                    print(f"[Queue Success] Task {task.task_id[:8]} delivered on attempt {task.attempts}.")
                else:
                    raise RuntimeError("Sender function returned False")
            except Exception as e:
                task.last_error = str(e)
                task.updated_at = current_time
                print(f"[Queue Error] Task {task.task_id[:8]} failed on attempt {task.attempts}/{task.max_retries}: {e}")

                if task.attempts < task.max_retries:
                    # Calculate exponential backoff delay: backoff_factor * (2 ^ (attempts - 1))
                    delay = task.backoff_factor * (2 ** (task.attempts - 1))
                    task.status = TaskStatus.FAILED
                    task.next_attempt_at = current_time + delay
                    remaining_pending.append(task)
                    stats["retried"] += 1
                    print(f"[Queue Retry] Task {task.task_id[:8]} scheduled to retry in {delay:.2f}s.")
                else:
                    # Max retries exhausted -> Move to Dead Letter Queue (DLQ)
                    task.status = TaskStatus.DLQ
                    self.dlq_tasks.append(task)
                    stats["dlq"] += 1
                    print(f"[Queue DLQ] Task {task.task_id[:8]} moved to Dead Letter Queue after {task.attempts} attempts.")

        self.pending_tasks = remaining_pending
        return stats

    def get_dlq(self) -> List[NotificationTask]:
        """Returns all tasks currently stored in the Dead Letter Queue."""
        return list(self.dlq_tasks)

    def retry_dlq_task(self, task_id: str) -> bool:
        """Re-queues a failed task from the Dead Letter Queue for execution."""
        for i, task in enumerate(self.dlq_tasks):
            if task.task_id == task_id:
                task.status = TaskStatus.PENDING
                task.attempts = 0
                task.last_error = None
                task.next_attempt_at = time.time()
                task.updated_at = time.time()
                
                # Move back to pending queue
                self.dlq_tasks.pop(i)
                self.pending_tasks.append(task)
                print(f"[Queue Re-queued] Task {task_id[:8]} restored from DLQ to pending queue.")
                return True
        return False

    def clear_dlq(self) -> int:
        """Clears all tasks in the Dead Letter Queue."""
        count = len(self.dlq_tasks)
        self.dlq_tasks.clear()
        return count


# Global singleton queue instance for background worker application
global_notification_queue = NotificationQueue()
