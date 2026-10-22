import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Callable, Any

from config import settings
from redis_client import DependencyUnavailable, get_redis_client

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
            "backoff_factor": self.backoff_factor,
            "status": self.status.value,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_attempt_at": self.next_attempt_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotificationTask":
        """Rebuilds a task persisted by to_dict (see TaskStore)."""
        return cls(
            task_id=data["task_id"],
            to_phone=data.get("to_phone", ""),
            message=data.get("message", ""),
            max_retries=data.get("max_retries", 3),
            attempts=data.get("attempts", 0),
            backoff_factor=data.get("backoff_factor", 1.0),
            status=TaskStatus(data.get("status", TaskStatus.PENDING.value)),
            last_error=data.get("last_error"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            next_attempt_at=data.get("next_attempt_at", time.time()),
        )


class TaskStore:
    """
    Redis-backed durability layer for the notification queue.

    Without it, an alert that is enqueued but not yet delivered (waiting out an
    exponential-backoff window, or sitting in the DLQ) is lost when the worker
    restarts — which in a deployed environment happens on every redeploy,
    scale-to-zero, and instance replacement. Pending and DLQ tasks are mirrored
    into two Redis hashes so a restarted worker resumes exactly where it left off.

    By default it degrades to a no-op when Redis is unreachable: the queue still
    works, it just loses the cross-restart guarantee. With strict=True (the
    worker's singleton) a failed save raises DependencyUnavailable instead, so
    the caller can roll back rather than record an alert as sent that only
    exists in this process's memory.
    """

    PENDING_KEY = "notifications:pending"
    DLQ_KEY = "notifications:dlq"

    def __init__(self, client=None, strict: bool = False):
        self.client = client if client is not None else get_redis_client()
        self.strict = strict

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def save(self, task: NotificationTask, dlq: bool = False) -> None:
        if not self.enabled:
            if self.strict:
                raise DependencyUnavailable("Redis unavailable - cannot persist notification task.")
            return
        try:
            self.client.hset(
                self.DLQ_KEY if dlq else self.PENDING_KEY,
                task.task_id,
                json.dumps(task.to_dict()),
            )
        except Exception as exc:
            print(f"[Queue Persist Error] Could not save task {task.task_id[:8]}: {exc}")
            if self.strict:
                raise DependencyUnavailable(f"Could not persist notification task: {exc}") from exc

    def remove(self, task_id: str, dlq: bool = False) -> None:
        if not self.enabled:
            return
        try:
            self.client.hdel(self.DLQ_KEY if dlq else self.PENDING_KEY, task_id)
        except Exception as exc:
            print(f"[Queue Persist Error] Could not remove task {task_id[:8]}: {exc}")

    def load(self, dlq: bool = False) -> List[NotificationTask]:
        if not self.enabled:
            return []
        try:
            raw = self.client.hgetall(self.DLQ_KEY if dlq else self.PENDING_KEY)
        except Exception as exc:
            print(f"[Queue Persist Error] Could not load persisted tasks: {exc}")
            return []

        tasks = []
        for task_id, payload in raw.items():
            try:
                tasks.append(NotificationTask.from_dict(json.loads(payload)))
            except Exception as exc:
                print(f"[Queue Persist Error] Dropping unreadable task {task_id}: {exc}")
                self.remove(task_id, dlq=dlq)
        return tasks

def default_twilio_sender(to_phone: str, message: str) -> bool:
    """
    Default Twilio SMS dispatch function.
    Sends a real SMS via the Twilio REST API when TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN
    are configured with non-placeholder values; otherwise falls back to mock console logging.
    """
    twilio_phone = settings.twilio_phone_number

    if settings.sms_enabled:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException

        try:
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            client.messages.create(body=message, from_=twilio_phone, to=to_phone)
            return True
        except TwilioRestException as e:
            print(f"[Twilio Error] Failed to send SMS to {to_phone}: {e}")
            return False

    print(f"\n[MOCK DISPATCH SMS to {to_phone}]")
    print(f"From: {twilio_phone}")
    print(f"Message: {message}\n")
    return True

class NotificationQueue:
    """
    Asynchronous / Batched Notification Queue for Twilio SMS dispatch.
    Implements retry logic with exponential backoff and a Dead Letter Queue (DLQ)
    to handle transient network failures or undeliverable alerts.
    """

    def __init__(
        self,
        sender_func: Optional[Callable[[str, str], bool]] = None,
        persist: bool = False,
        store: Optional[TaskStore] = None,
    ):
        """
        persist=True mirrors pending/DLQ tasks to Redis and restores them at
        construction, so undelivered alerts survive a worker restart. It is
        opt-in (the deployed singleton below sets it) so that tests and ad-hoc
        instances never pick up state from a developer's local Redis.
        """
        self.sender_func = sender_func or default_twilio_sender
        self.pending_tasks: List[NotificationTask] = []
        self.completed_tasks: List[NotificationTask] = []
        self.dlq_tasks: List[NotificationTask] = []
        self.store = store if store is not None else (TaskStore() if persist else None)

        if self.store and self.store.enabled:
            self.pending_tasks = self.store.load()
            self.dlq_tasks = self.store.load(dlq=True)
            if self.pending_tasks or self.dlq_tasks:
                print(
                    f"[Queue Restored] {len(self.pending_tasks)} pending and "
                    f"{len(self.dlq_tasks)} DLQ task(s) recovered from Redis."
                )

    def _persist(self, task: NotificationTask, dlq: bool = False) -> None:
        if self.store:
            self.store.save(task, dlq=dlq)

    def _forget(self, task_id: str, dlq: bool = False) -> None:
        if self.store:
            self.store.remove(task_id, dlq=dlq)

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
        # Persist first: with a strict store a failure raises here, before the
        # task exists anywhere, so the caller's rollback leaves nothing behind.
        self._persist(task)
        self.pending_tasks.append(task)
        print(f"[Queue Enqueued] Task {task.task_id[:8]} for {to_phone}")
        return task

    def discard(self, task: NotificationTask) -> None:
        """Withdraws a not-yet-sent task, e.g. when the DB work that produced it rolled back."""
        if task in self.pending_tasks:
            self.pending_tasks.remove(task)
        self._forget(task.task_id)

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
                    self._forget(task.task_id)
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
                    self._persist(task)
                    stats["retried"] += 1
                    print(f"[Queue Retry] Task {task.task_id[:8]} scheduled to retry in {delay:.2f}s.")
                else:
                    # Max retries exhausted -> Move to Dead Letter Queue (DLQ)
                    task.status = TaskStatus.DLQ
                    self.dlq_tasks.append(task)
                    self._forget(task.task_id)
                    self._persist(task, dlq=True)
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
                self._forget(task_id, dlq=True)
                self._persist(task)
                print(f"[Queue Re-queued] Task {task_id[:8]} restored from DLQ to pending queue.")
                return True
        return False

    def clear_dlq(self) -> int:
        """Clears all tasks in the Dead Letter Queue."""
        count = len(self.dlq_tasks)
        for task in self.dlq_tasks:
            self._forget(task.task_id, dlq=True)
        self.dlq_tasks.clear()
        return count


# Global singleton queue instance for the background worker. persist=True so an
# alert enqueued just before a redeploy is still delivered after it.
global_notification_queue = NotificationQueue(persist=True, store=TaskStore(strict=True))
