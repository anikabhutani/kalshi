"""Background job runner with progress events (streamed to the UI over SSE)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.db import Database
from app.errors import JobCancelled, ReconError, RequestBudgetExceeded
from app.evidence import scrub
from app.models import Job

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
_MAX_BUFFERED_JOBS = 50


class JobContext:
    """Handle passed to a job runner: progress/log emitters, cancellation, request cap."""

    def __init__(self, job_id: str, module: str, max_requests: int, manager: JobManager) -> None:
        self.id = job_id
        self.module = module
        self.max_requests = max_requests
        self.requests_made = 0
        self.cancel_event = asyncio.Event()
        self.partial_result: dict[str, Any] | None = None
        self._manager = manager

    @property
    def cancelled(self) -> bool:
        """True once the user asked this job to stop."""
        return self.cancel_event.is_set()

    @property
    def remaining_requests(self) -> int:
        """Requests left before the hard cap."""
        return max(0, self.max_requests - self.requests_made)

    def check_cancelled(self) -> None:
        """Raise JobCancelled if a stop was requested."""
        if self.cancelled:
            raise JobCancelled()

    def consume_request(self) -> None:
        """Account for one outgoing request, enforcing cancellation and the cap."""
        self.check_cancelled()
        if self.requests_made >= self.max_requests:
            raise RequestBudgetExceeded(self.max_requests)
        self.requests_made += 1

    def log(self, message: str, level: str = "info") -> None:
        """Emit a log line to the UI stream."""
        self._manager.emit(self.id, {"type": "log", "level": level, "message": message})

    def progress(self, done: int, total: int, message: str = "") -> None:
        """Emit a progress update to the UI stream."""
        self._manager.emit(
            self.id, {"type": "progress", "done": done, "total": total, "message": message}
        )

    def save_partial(self, result: dict[str, Any]) -> None:
        """Keep results collected so far; stored if the job is stopped or fails midway."""
        self.partial_result = result


JobRunner = Callable[[JobContext], Awaitable[dict[str, Any]]]


class JobManager:
    """Starts, tracks, stops, and persists background jobs."""

    def __init__(self, db: Database, secrets: Iterable[str]) -> None:
        self._db = db
        self._secrets = tuple(s for s in secrets if s)
        self._contexts: dict[str, JobContext] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._mark_orphans_failed()

    def start(
        self,
        module: str,
        kind: str,
        params: dict[str, Any],
        runner: JobRunner,
        max_requests: int,
    ) -> str:
        """Create a job row, schedule the runner, and return the job id.

        Must be called from the event loop thread (i.e. from an ``async def`` route).
        """
        job_id = str(uuid.uuid4())
        ctx = JobContext(job_id, module, max_requests, self)
        task = asyncio.get_running_loop().create_task(self._run(ctx, runner))
        with self._db.session() as session:
            session.add(
                Job(
                    id=job_id,
                    module=module,
                    kind=kind,
                    status="running",
                    params_json=json.dumps(params, default=str),
                    max_requests=max_requests,
                    started_at=datetime.now(UTC),
                )
            )
        self._contexts[job_id] = ctx
        self._tasks[job_id] = task
        self._events[job_id] = []
        self._trim_buffers()
        self.emit(job_id, {"type": "status", "status": "running"})
        return job_id

    def context(self, job_id: str) -> JobContext | None:
        """Context of a running job, or None if it is not running."""
        return self._contexts.get(job_id)

    def running_count(self) -> int:
        """Number of jobs currently running."""
        return len(self._contexts)

    def stop(self, job_id: str) -> bool:
        """Request a single job to stop. Returns False if it is not running."""
        ctx = self._contexts.get(job_id)
        if ctx is None:
            return False
        ctx.cancel_event.set()
        task = self._tasks.get(job_id)
        if task is not None:
            task.cancel()
        return True

    def stop_all(self) -> int:
        """Kill switch: stop every running job. Returns how many were signalled."""
        return sum(self.stop(job_id) for job_id in list(self._contexts))

    def emit(self, job_id: str, event: dict[str, Any]) -> None:
        """Buffer an event and fan it out to live subscribers."""
        event = {**event, "ts": datetime.now(UTC).isoformat()}
        if "message" in event:
            event["message"] = scrub(str(event["message"]), self._secrets)
        self._events.setdefault(job_id, []).append(event)
        for queue in self._subscribers.get(job_id, set()):
            queue.put_nowait(event)

    async def subscribe(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        """Replay buffered events, then stream live ones until the job finishes."""
        if job_id not in self._events:
            job = self.get_job(job_id)
            if job is not None:
                yield {"type": "status", "status": job["status"], "reason": job["error_reason"]}
            return

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(job_id, set()).add(queue)
        try:
            for event in list(self._events[job_id]):
                yield event
                if _is_terminal(event):
                    return
            while True:
                event = await queue.get()
                yield event
                if _is_terminal(event):
                    return
        finally:
            self._subscribers.get(job_id, set()).discard(queue)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Job row as a dict (including stored results)."""
        with self._db.session() as session:
            job = session.get(Job, job_id)
            return _job_to_dict(job) if job is not None else None

    def list_jobs(
        self, module: str | None = None, kind: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Most recent jobs (without their stored results), optionally filtered."""
        stmt = select(Job).order_by(Job.started_at.desc()).limit(limit)
        if module is not None:
            stmt = stmt.where(Job.module == module)
        if kind is not None:
            stmt = stmt.where(Job.kind == kind)
        with self._db.session() as session:
            return [_job_to_dict(j, include_result=False) for j in session.scalars(stmt)]

    def latest_with_result(self, module: str, kind: str) -> dict[str, Any] | None:
        """Most recent finished job of a kind that stored a (possibly partial) result."""
        stmt = (
            select(Job)
            .where(Job.module == module, Job.kind == kind, Job.result_json.is_not(None))
            .order_by(Job.started_at.desc())
            .limit(1)
        )
        with self._db.session() as session:
            job = session.scalars(stmt).first()
            return _job_to_dict(job) if job is not None else None

    def count_by_module(self) -> dict[str, int]:
        """Number of jobs ever run per module."""
        stmt = select(Job.module, func.count()).group_by(Job.module)
        with self._db.session() as session:
            return {module: count for module, count in session.execute(stmt)}

    async def _run(self, ctx: JobContext, runner: JobRunner) -> None:
        status, reason, result = "succeeded", None, None
        try:
            result = await runner(ctx)
        except asyncio.CancelledError:
            status, reason = "cancelled", JobCancelled.user_message
        except JobCancelled as exc:
            status, reason = "cancelled", exc.user_message
        except ReconError as exc:
            status, reason = "failed", exc.user_message
        except Exception as exc:  # noqa: BLE001 - a job must never crash the server
            status, reason = "failed", f"Unexpected error: {type(exc).__name__}: {exc}"
        reason = scrub(reason, self._secrets)
        if result is None and ctx.partial_result is not None:
            result = {**ctx.partial_result, "partial": True}

        with self._db.session() as session:
            job = session.get(Job, ctx.id)
            if job is not None:
                job.status = status
                job.error_reason = reason
                job.request_count = ctx.requests_made
                job.result_json = json.dumps(result, default=str) if result is not None else None
                job.finished_at = datetime.now(UTC)
        self._contexts.pop(ctx.id, None)
        self._tasks.pop(ctx.id, None)
        if reason:
            self.emit(ctx.id, {"type": "log", "level": "error", "message": reason})
        self.emit(ctx.id, {"type": "status", "status": status, "reason": reason})

    def _trim_buffers(self) -> None:
        finished = [j for j in self._events if j not in self._contexts]
        for job_id in finished[: max(0, len(self._events) - _MAX_BUFFERED_JOBS)]:
            self._events.pop(job_id, None)

    def _mark_orphans_failed(self) -> None:
        """Jobs left 'running' by a previous process can never finish; mark them failed."""
        with self._db.session() as session:
            for job in session.scalars(select(Job).where(Job.status == "running")):
                job.status = "failed"
                job.error_reason = "Backend restarted while this job was running."
                job.finished_at = datetime.now(UTC)


def _is_terminal(event: dict[str, Any]) -> bool:
    return event.get("type") == "status" and event.get("status") in TERMINAL_STATUSES


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _job_to_dict(job: Job, include_result: bool = True) -> dict[str, Any]:
    return {
        "id": job.id,
        "module": job.module,
        "kind": job.kind,
        "status": job.status,
        "params": json.loads(job.params_json or "{}"),
        "result": json.loads(job.result_json) if include_result and job.result_json else None,
        "error_reason": job.error_reason,
        "request_count": job.request_count,
        "max_requests": job.max_requests,
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
    }
