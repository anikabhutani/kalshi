"""M0: connection status, settings, notes, evidence rows, jobs (+SSE), rate meter, home."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.analysis.export import secret_values
from app.errors import AuthNotConfigured, RateLimited, ReconError
from app.jobs import JobContext
from app.kalshi_client import CallResult
from app.models import Note
from app.notes_file import all_notes, write_notes_file
from app.questions import QUESTION_IDS, QUESTIONS
from app.services import Services, get_services
from app.settings_store import RuntimeSettings, SettingsPatch

router = APIRouter(prefix="/api", tags=["core"])

ConnectionState = Literal[
    "not_configured", "ok", "unauthorized", "forbidden", "rate_limited", "offline", "error"
]

_STATUS_CACHE_S = 60.0
_status_lock = asyncio.Lock()
_status_cache: dict[str, Any] = {}


class ConnectionStatus(BaseModel):
    """Result of the authenticated read-only connection check."""

    state: ConnectionState
    http_status: int | None
    latency_ms: float | None
    path: str
    checked_at: str
    message: str


class NoteBody(BaseModel):
    """User-typed note text."""

    text: str = Field(max_length=100_000)


@router.get("/meta")
def get_meta(services: Services = Depends(get_services)) -> dict[str, Any]:
    """Spec versions, servers, current settings. Never includes credentials."""
    return {
        "openapi": {
            "title": services.spec.title,
            "version": services.spec.version,
            "servers": services.spec.servers,
            "endpoint_count": len(services.spec.endpoints),
            "get_endpoint_count": len(services.spec.get_endpoints()),
        },
        "asyncapi": {
            "title": services.asyncspec.title,
            "version": services.asyncspec.version,
            "servers": services.asyncspec.servers,
            "channels": [c.name for c in services.asyncspec.channels],
        },
        "credentials_configured": services.config.credentials_configured,
        "settings": services.settings.get().model_dump(),
        "auth_check_choices": services.settings.auth_check_choices(),
    }


@router.put("/settings")
def update_settings(
    patch: SettingsPatch, services: Services = Depends(get_services)
) -> RuntimeSettings:
    """Update user-editable settings (API version confirmation, base URL, rate limits)."""
    try:
        updated = services.settings.update(patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    _status_cache.clear()
    return updated


@router.get("/status")
async def get_status(
    refresh: bool = False, services: Services = Depends(get_services)
) -> ConnectionStatus:
    """Authenticated read-only call to the configured auth-check endpoint (cached 60s)."""
    async with _status_lock:
        cached = _status_cache.get("value")
        if cached is not None and not refresh and time.monotonic() - _status_cache["at"] < (
            _STATUS_CACHE_S
        ):
            return ConnectionStatus(**cached)
        status = await _check_connection(services)
        _status_cache.update(value=status.model_dump(), at=time.monotonic())
        return status


async def _check_connection(services: Services) -> ConnectionStatus:
    path = services.settings.get().auth_check_path
    checked_at = datetime.now(UTC).isoformat()
    if not services.config.credentials_configured:
        return ConnectionStatus(
            state="not_configured",
            http_status=None,
            latency_ms=None,
            path=path,
            checked_at=checked_at,
            message="No API key configured in .env.",
        )
    try:
        result = await services.client.call("GET", path, auth=True, module="M0")
    except RateLimited as exc:
        return ConnectionStatus(
            state="rate_limited",
            http_status=429,
            latency_ms=None,
            path=path,
            checked_at=checked_at,
            message=exc.user_message,
        )
    except ReconError as exc:
        return ConnectionStatus(
            state="error",
            http_status=None,
            latency_ms=None,
            path=path,
            checked_at=checked_at,
            message=exc.user_message,
        )
    state, message = _classify(result)
    return ConnectionStatus(
        state=state,
        http_status=result.status_code,
        latency_ms=result.latency_ms,
        path=path,
        checked_at=checked_at,
        message=message,
    )


def _classify(result: CallResult) -> tuple[ConnectionState, str]:
    if result.status_code is None:
        return "offline", result.error or "No response."
    if result.ok:
        return "ok", "Authenticated read call succeeded."
    if result.status_code == 401:
        return "unauthorized", "401 Unauthorized: check the key id, key file, and environment."
    if result.status_code == 403:
        return "forbidden", "403 Forbidden: the key is valid but lacks access to this endpoint."
    return "error", f"Unexpected HTTP {result.status_code}."


@router.get("/ratelimit")
def get_rate_limit(services: Services = Depends(get_services)) -> dict[str, float]:
    """Local token-bucket state for the top-bar meter."""
    return {**services.bucket.snapshot(), "running_jobs": float(services.jobs.running_count())}


@router.get("/notes")
def list_notes(services: Services = Depends(get_services)) -> dict[str, dict[str, str | None]]:
    """All user notes keyed by question id (empty text where nothing was written)."""
    return all_notes(services.db)


@router.put("/notes/{question_id}")
def save_note(
    question_id: str, body: NoteBody, services: Services = Depends(get_services)
) -> dict[str, str | bool]:
    """Autosave target for the per-question notes textarea; also refreshes the tracked notes file.

    ``file_saved`` is False when the text contains a secret, so the tracked copy was left unchanged.
    """
    if question_id not in QUESTION_IDS:
        raise HTTPException(status_code=404, detail="Unknown question id.")
    now = datetime.now(UTC)
    with services.db.session() as session:
        note = session.get(Note, question_id)
        if note is None:
            session.add(Note(question_id=question_id, text=body.text, updated_at=now))
        else:
            note.text, note.updated_at = body.text, now
    file_saved = write_notes_file(services.config.notes_file, all_notes(services.db), secret_values(services.config))
    return {"question_id": question_id, "updated_at": now.isoformat(), "file_saved": file_saved}


@router.get("/requests")
def list_requests(
    job_id: str | None = None,
    module: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    """Redacted evidence-log rows, newest first."""
    return services.evidence.list_requests(job_id=job_id, module=module, limit=limit, offset=offset)


@router.get("/requests/{request_id}/raw")
def raw_request_body(request_id: int, services: Services = Depends(get_services)) -> Any:
    """Stored full response body (only kept for selected, non-account, HTTP 200 responses)."""
    body = services.evidence.raw_body(request_id)
    if body is None:
        raise HTTPException(status_code=404, detail="No raw body stored for this request.")
    return body


@router.get("/jobs")
def list_jobs(
    module: str | None = None,
    kind: str | None = None,
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    """Recent jobs (summaries without results), optionally filtered by module and kind."""
    return services.jobs.list_jobs(module=module, kind=kind)


@router.get("/jobs/latest")
def latest_job(
    module: str, kind: str, services: Services = Depends(get_services)
) -> dict[str, Any] | None:
    """Most recent job of a kind that stored results, so pages can re-display them."""
    return services.jobs.latest_with_result(module, kind)


@router.post("/jobs/stop-all")
async def stop_all_jobs(services: Services = Depends(get_services)) -> dict[str, int]:
    """Global kill switch."""
    return {"stopped": services.jobs.stop_all()}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    """One job including its stored result."""
    job = services.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str, services: Services = Depends(get_services)) -> dict[str, bool]:
    """Stop one running job."""
    return {"stopped": services.jobs.stop(job_id)}


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, services: Services = Depends(get_services)) -> EventSourceResponse:
    """Server-Sent Events stream of a job's progress, logs, and final status."""

    async def stream() -> AsyncIterator[dict[str, str]]:
        async for event in services.jobs.subscribe(job_id):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(stream())


@router.get("/home")
def home(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    """Per-question progress counters: jobs run and evidence rows from feeding modules."""
    jobs_by_module = services.jobs.count_by_module()
    evidence_by_module = services.evidence.count_by_module()
    with services.db.session() as session:
        notes = {n.question_id: bool(n.text.strip()) for n in session.scalars(select(Note))}
    return [
        {
            **q,
            "jobs_run": sum(jobs_by_module.get(m, 0) for m in q["modules"]),
            "evidence_count": sum(evidence_by_module.get(m, 0) for m in q["modules"]),
            "has_notes": notes.get(q["id"], False),
        }
        for q in QUESTIONS
    ]


@router.post("/sanity/run")
async def run_sanity_check(services: Services = Depends(get_services)) -> dict[str, str]:
    """Two-request job: one public GET and one authenticated GET, both logged as evidence."""
    public_path = "/exchange/status"
    auth_path = services.settings.get().auth_check_path

    async def runner(ctx: JobContext) -> dict[str, Any]:
        checks = [("Public call", public_path, False), ("Authenticated call", auth_path, True)]
        rows: list[dict[str, Any]] = []
        for index, (label, path, auth) in enumerate(checks):
            ctx.progress(index, len(checks), f"{label}: GET {path}")
            row: dict[str, Any] = {"label": label, "path": path, "auth": auth}
            try:
                result = await services.client.call("GET", path, auth=auth, job_id=ctx.id)
            except AuthNotConfigured as exc:
                ctx.log(f"{label}: {exc.user_message}", "warn")
                rows.append({**row, "status_code": None, "error": exc.user_message})
                continue
            offset = result.clock_offset_s
            ctx.log(f"{label}: HTTP {result.status_code} in {result.latency_ms:.0f} ms")
            rows.append(
                {
                    **row,
                    "status_code": result.status_code,
                    "latency_ms": result.latency_ms,
                    "server_date": result.server_date.isoformat() if result.server_date else None,
                    "local_received_at": result.received_at.isoformat(),
                    "clock_offset_s": round(offset, 3) if offset is not None else None,
                    "request_id": result.request_id,
                    "error": result.error,
                }
            )
        ctx.progress(len(checks), len(checks), "Done")
        return {"checks": rows}

    job_id = services.jobs.start("M0", "sanity_check", {}, runner, max_requests=6)
    return {"job_id": job_id}
