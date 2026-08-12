"""Background jobs with a pollable progress endpoint.

A thread pool runs long parses off the request path. Job state is written to the
database on every meaningful progress step, so /api/jobs/{id} works from any
worker and survives a client reconnect.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .db import JobRecord, session_scope

log = logging.getLogger(__name__)

# Progress updates are throttled so a 100k-entity parse does not turn into
# 100k database writes.
PROGRESS_WRITE_STEP = 0.01


class JobHandle:
    """Passed into worker functions so they can report progress."""

    def __init__(self, job_id: str) -> None:
        self.id = job_id
        self._last_written = -1.0
        self._lock = threading.Lock()
        self.cancelled = False

    def progress(self, fraction: float, message: str = "") -> None:
        fraction = max(0.0, min(1.0, float(fraction)))
        with self._lock:
            if fraction - self._last_written < PROGRESS_WRITE_STEP and fraction < 1.0:
                return
            self._last_written = fraction
        _update(self.id, progress=fraction, message=message or None)


def _update(job_id: str, **fields: Any) -> None:
    try:
        with session_scope() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                return
            for key, value in fields.items():
                if value is not None:
                    setattr(job, key, value)
    except Exception:
        log.exception("failed to update job %s", job_id)


class JobManager:
    def __init__(self, max_workers: int = 2) -> None:
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ifcsched"
        )
        self._handles: dict[str, JobHandle] = {}
        self.is_shutdown = False

    def submit(
        self,
        kind: str,
        project_id: int,
        worker: Callable[[JobHandle], dict[str, Any]],
    ) -> str:
        job_id = uuid.uuid4().hex[:16]
        with session_scope() as session:
            session.add(
                JobRecord(
                    id=job_id,
                    project_id=project_id,
                    kind=kind,
                    status="queued",
                    progress=0.0,
                    message="Queued",
                )
            )
        handle = JobHandle(job_id)
        self._handles[job_id] = handle
        self.executor.submit(self._run, handle, worker)
        return job_id

    def _run(self, handle: JobHandle, worker: Callable[[JobHandle], dict[str, Any]]) -> None:
        _update(handle.id, status="running", message="Started")
        try:
            result = worker(handle) or {}
            _update(handle.id, status="done", progress=1.0, message="Complete", result=result)
        except Exception as exc:
            log.exception("job %s failed", handle.id)
            _update(
                handle.id,
                status="failed",
                message="Failed",
                error=f"{exc}\n{traceback.format_exc(limit=8)}",
            )
        finally:
            self._handles.pop(handle.id, None)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with session_scope() as session:
            job = session.get(JobRecord, job_id)
            return job.as_dict() if job else None

    def shutdown(self) -> None:
        self.is_shutdown = True
        self.executor.shutdown(wait=False, cancel_futures=True)


_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    """A shut-down executor cannot accept work again, so a new app lifespan
    (a restart, or a second app in the same process) gets a fresh manager."""
    global _manager
    if _manager is None or _manager.is_shutdown:
        _manager = JobManager()
    return _manager
