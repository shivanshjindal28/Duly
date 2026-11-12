"""Background job interface (spec 14): one place where slow work is handed off.

Today `InProcessQueue` runs each job at once, inside the caller's request and database
transaction, so behaviour is identical to a direct call and the demo needs no worker. In
production the same `enqueue` calls go to a queue worker (for example Celery or RQ on Redis,
or Azure Service Bus) by swapping the queue object: callers do not change. Jobs that would move
out of the request: document extraction (OCR / AI), re-matching invoices after a goods receipt,
and processing emailed attachments.

Every job is recorded (name, timings, status, error) in a small in-memory ring so the
Architecture page can show what ran.
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Job:
    id: int
    name: str
    status: str = "queued"  # queued | running | done | failed
    queued_at: float = field(default_factory=time.time)
    duration_ms: float | None = None
    error: str | None = None
    result: Any = None


class JobQueue(Protocol):
    name: str

    def enqueue(self, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Job: ...


class InProcessQueue:
    """Runs the job immediately in the calling thread. Errors propagate to the caller (same as a direct call)."""

    name = "in-process"

    def __init__(self, keep: int = 200):
        self._ids = itertools.count(1)
        self._recent: deque[Job] = deque(maxlen=keep)
        self._lock = threading.Lock()

    def enqueue(self, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Job:
        with self._lock:
            job = Job(next(self._ids), name)
            self._recent.append(job)
        start = time.perf_counter()
        job.status = "running"
        try:
            job.result = fn(*args, **kwargs)
            job.status = "done"
        except Exception as e:
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"[:300]
            raise
        finally:
            job.duration_ms = round((time.perf_counter() - start) * 1000, 1)
        return job

    def recent(self, n: int = 20) -> list[Job]:
        with self._lock:
            return list(self._recent)[-n:][::-1]


_queue: InProcessQueue = InProcessQueue()


def enqueue(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Job:
    """Hand work to the job queue. With the in-process queue the job has finished when this returns."""
    return _queue.enqueue(name, fn, *args, **kwargs)


def status() -> dict:
    jobs = _queue.recent()
    return {"queue": _queue.name,
            "recent": [{"id": j.id, "name": j.name, "status": j.status, "duration_ms": j.duration_ms, "error": j.error}
                       for j in jobs]}
