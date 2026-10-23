"""M8: Evidence and Export. Builds a Markdown appendix, CSVs, and chart PNGs in data/exports/.

The export contains no credentials (the evidence log is already redacted; every text file is
also checked for the key id, private-key lines, and PEM markers before anything is written)
and no generated conclusions (see ``app.analysis.export``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analysis.auth_probe import endpoint_id
from app.analysis.export import (
    ExportData,
    ExportError,
    build_appendix,
    build_tables,
    csv_text,
    decode_charts,
    find_leaks,
    secret_values,
)
from app.analysis.limits import parse_rate_doc
from app.analysis.timestamps import stored_utc_iso
from app.models import EndpointRating, Note
from app.modules import m6_rest_ws
from app.questions import QUESTIONS
from app.services import Services, get_services

router = APIRouter(prefix="/api/m8", tags=["M8 export"])

EXPORT_PREFIX = "kalshi-recon-export-"
LATEST_KINDS: dict[str, tuple[str, str]] = {
    "m1_auth_probe": ("M1", "auth_probe"),
    "m2_pull_game": ("M2", "pull_game"),
    "m3_price_sources": ("M3", "price_sources"),
    "m4_depth_archive": ("M4", "depth_archive"),
    "m5_account_limits": ("M5", "account_limits"),
    "m5_ramp": ("M5", "ramp"),
    "m5_pagination": ("M5", "pagination"),
    "m6_recorder": (m6_rest_ws.MODULE, m6_rest_ws.RUN_KIND),
}


class ChartImage(BaseModel):
    """One chart rendered by the frontend with Plotly's image export."""

    name: str = Field(max_length=64)
    png_base64: str = Field(max_length=12 * 1024 * 1024)


class ExportBody(BaseModel):
    """Export request: chart images to include (may be empty)."""

    charts: list[ChartImage] = Field(default_factory=list, max_length=40)


def _notes(services: Services) -> dict[str, str]:
    with services.db.session() as session:
        return {n.question_id: n.text for n in session.scalars(select(Note))}


def _ratings(services: Services) -> list[dict[str, Any]]:
    with services.db.session() as session:
        return [
            {"endpoint_id": r.endpoint_id, "rating": r.rating, "reason": r.reason, "updated_at": stored_utc_iso(r.updated_at)}
            for r in session.scalars(select(EndpointRating).order_by(EndpointRating.endpoint_id))
            if r.rating is not None or r.reason.strip()
        ]


def _latest(services: Services) -> dict[str, dict[str, Any] | None]:
    return {key: services.jobs.latest_with_result(m, k) for key, (m, k) in LATEST_KINDS.items()}


def _gather(services: Services) -> ExportData:
    rate_text = (services.config.specs_dir / "rate_limits.md").read_text(encoding="utf-8")
    return ExportData(
        generated_at=datetime.now(UTC),
        openapi_title=services.spec.title,
        openapi_version=services.spec.version,
        asyncapi_version=services.asyncspec.version,
        settings=services.settings.get().model_dump(),
        questions=QUESTIONS,
        notes=_notes(services),
        requests=services.evidence.all_requests(),
        jobs=services.jobs.list_jobs(limit=100_000),
        ratings=_ratings(services),
        spec_auth={endpoint_id(e): e.auth_required for e in services.spec.endpoints},
        rate_doc=parse_rate_doc(rate_text),
        latest=_latest(services),
        ws_spec_rows=m6_rest_ws.spec_comparison(services),
    )


def _export_dirs(services: Services) -> list[Path]:
    root = services.config.exports_dir
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith(EXPORT_PREFIX)), reverse=True)


def _describe(folder: Path) -> dict[str, Any]:
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    return {
        "name": folder.name,
        "path": str(folder),
        "created_at": datetime.fromtimestamp(folder.stat().st_mtime, UTC).isoformat(),
        "files": [{"path": p.relative_to(folder).as_posix(), "bytes": p.stat().st_size} for p in files],
    }


@router.get("/summary")
def summary(services: Services = Depends(get_services)) -> dict[str, Any]:
    """What an export would contain right now (counts only; no requests sent)."""
    notes = _notes(services)
    latest = _latest(services)
    current = services.settings.get()
    return {
        "openapi_version": services.spec.version,
        "asyncapi_version": services.asyncspec.version,
        "api_version_confirmed": current.api_version,
        "date_checked": current.date_checked,
        "base_url": current.base_url,
        "requests_by_module": services.evidence.count_by_module(),
        "jobs_by_module": services.jobs.count_by_module(),
        "notes_written": sorted(q for q, t in notes.items() if t.strip()),
        "questions": [q["id"] for q in QUESTIONS],
        "latest_results": {
            key: None if job is None else {"id": job["id"], "finished_at": job["finished_at"], "status": job["status"]}
            for key, job in latest.items()
        },
        "exports": len(_export_dirs(services)),
    }


@router.post("/export")
def create_export(body: ExportBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Write appendix.md, csv/*.csv, and charts/*.png into a new folder under data/exports/."""
    try:
        charts = decode_charts(c.model_dump() for c in body.charts)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    data = _gather(services)
    tables = build_tables(data)
    texts = {f"csv/{t.name}.csv": csv_text(t.columns, t.rows) for t in tables}
    chart_files = [f"charts/{c.name}.png" for c in charts]
    files = ["appendix.md", *texts, *chart_files]
    texts["appendix.md"] = build_appendix(data, tables, files)

    leaks = find_leaks(texts, secret_values(services.config))
    if leaks:
        raise HTTPException(
            status_code=422,
            detail=(
                "Export aborted: credential material was found in "
                + ", ".join(sorted(leaks))
                + ". Nothing was written. Check your notes and ratings for pasted keys."
            ),
        )

    root = services.config.exports_dir
    root.mkdir(parents=True, exist_ok=True)
    stamp = data.generated_at.strftime("%Y%m%dT%H%M%SZ")
    folder = root / f"{EXPORT_PREFIX}{stamp}"
    suffix = 1
    while folder.exists():
        suffix += 1
        folder = root / f"{EXPORT_PREFIX}{stamp}-{suffix}"
    (folder / "csv").mkdir(parents=True)
    if charts:
        (folder / "charts").mkdir()
    for name, text in texts.items():
        (folder / name).write_text(text, encoding="utf-8")
    for chart in charts:
        (folder / "charts" / f"{chart.name}.png").write_bytes(chart.png)
    return _describe(folder)


@router.get("/exports")
def list_exports(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    """Previous exports, newest first."""
    return [_describe(p) for p in _export_dirs(services)]


@router.get("/exports/{name}/files/{file_path:path}")
def download_export_file(name: str, file_path: str, services: Services = Depends(get_services)) -> FileResponse:
    """One file from an export folder (paths outside the folder are rejected)."""
    if not name.startswith(EXPORT_PREFIX) or "/" in name or "\\" in name:
        raise HTTPException(status_code=404, detail="Export not found.")
    root = services.config.exports_dir.resolve()
    folder = (root / name).resolve()
    target = (folder / file_path).resolve()
    if folder.parent != root or not target.is_relative_to(folder) or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(target, filename=target.name)
