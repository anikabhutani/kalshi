"""M7: Sportsbook overlay. Local only: this module never sends a request to Kalshi.

- Datasets: a CSV upload (template columns: timestamp_utc, book, event, market,
  odds_american, odds_decimal) is validated and stored with implied and two-way no-vig
  probabilities (``app.analysis.sportsbook``). Generated test data is stored with
  ``is_dummy`` set and "DUMMY DATA" in its book, event and outcome names.
- Overlay: one outcome of a dataset is matched against one price series of a stored M3
  Timestamp Lab run with ``price_at``; gaps are Kalshi minus sportsbook probability.
"""

from __future__ import annotations

import json
import uuid
import zlib
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analysis.sportsbook import (
    DUMMY_LABEL,
    TEMPLATE_CSV,
    CsvError,
    KalshiSeries,
    ParsedCsv,
    dummy_csv,
    overlay,
    parse_csv,
)
from app.analysis.timestamps import iso, stored_utc_iso
from app.models import SportsbookDataset
from app.modules.m3_timestamps import MODULE as LAB_MODULE
from app.modules.m3_timestamps import RUN_KIND as LAB_KIND
from app.modules.m3_timestamps import price_series
from app.services import Services, get_services

router = APIRouter(prefix="/api/m7", tags=["M7 sportsbook"])

MAX_CHART_POINTS = 20_000


class UploadBody(BaseModel):
    """A CSV file's text and a display name."""

    name: str = Field(min_length=1, max_length=200)
    csv_text: str = Field(min_length=1, max_length=2_100_000)


class DummyBody(BaseModel):
    """Which Timestamp Lab run's window the dummy data should cover."""

    lab_job_id: str = Field(min_length=1, max_length=36)


class OverlayBody(BaseModel):
    """Overlay selection."""

    dataset_id: str = Field(min_length=1, max_length=36)
    lab_job_id: str = Field(min_length=1, max_length=36)
    selection: str = Field(min_length=1, max_length=500)
    series_id: str = Field(min_length=1, max_length=100)
    max_staleness_s: float = Field(default=300.0, gt=0, le=7 * 86_400)


def _summary(row: SportsbookDataset) -> dict[str, Any]:
    rows: list[dict[str, Any]] = json.loads(row.rows_json)
    ts = [r["ts"] for r in rows]
    return {
        "id": row.id,
        "name": row.name,
        "is_dummy": row.is_dummy,
        "source_job_id": row.source_job_id,
        "created_at": stored_utc_iso(row.created_at),
        "rows": len(rows),
        "error_count": row.error_count,
        "books": sorted({r["book"] for r in rows}),
        "events": sorted({r["event"] for r in rows}),
        "markets": sorted({r["market"] for r in rows}),
        "first_ts": iso(min(ts)) if ts else None,
        "last_ts": iso(max(ts)) if ts else None,
    }


def _store(services: Services, name: str, parsed: ParsedCsv, is_dummy: bool, source_job_id: str | None) -> dict[str, Any]:
    dataset = SportsbookDataset(
        id=str(uuid.uuid4()),
        name=name,
        is_dummy=is_dummy,
        source_job_id=source_job_id,
        created_at=datetime.now(UTC),
        rows_json=json.dumps(parsed.rows),
        errors_json=json.dumps(parsed.errors),
        notes_json=json.dumps(parsed.notes),
        error_count=parsed.error_count,
    )
    with services.db.session() as session:
        session.add(dataset)
    return {**_summary(dataset), "errors": parsed.errors, "notes": parsed.notes}


def _dataset(services: Services, dataset_id: str) -> SportsbookDataset:
    with services.db.session() as session:
        row = session.get(SportsbookDataset, dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return row


def _lab_result(services: Services, job_id: str) -> dict[str, Any]:
    job = services.jobs.get_job(job_id)
    if job is None or job["module"] != LAB_MODULE or job["kind"] != LAB_KIND or not isinstance(job.get("result"), dict):
        raise HTTPException(status_code=404, detail="No stored Timestamp Lab result for that job.")
    return job["result"]


def _series(result: dict[str, Any]) -> list[KalshiSeries]:
    return [
        KalshiSeries(id=f"{key}:{field}", label=f"{key} · {label}", note=note, points=points)
        for key, field, label, note, points in price_series(result.get("sources") or {})
        if key != "orderbook"
    ]


@router.get("/template", response_class=PlainTextResponse)
def template() -> PlainTextResponse:
    """Downloadable CSV template (example rows are labelled DUMMY)."""
    return PlainTextResponse(
        TEMPLATE_CSV,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sportsbook_template.csv"'},
    )


@router.get("/datasets")
def list_datasets(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    """Stored datasets, newest first."""
    with services.db.session() as session:
        rows = list(session.scalars(select(SportsbookDataset).order_by(SportsbookDataset.created_at.desc())))
    return [_summary(r) for r in rows]


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    """One dataset with its parsed rows and line errors."""
    row = _dataset(services, dataset_id)
    return {
        **_summary(row),
        "rows_data": json.loads(row.rows_json),
        "errors": json.loads(row.errors_json),
        "notes": json.loads(row.notes_json),
    }


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, services: Services = Depends(get_services)) -> dict[str, bool]:
    """Remove a stored dataset (local data only)."""
    with services.db.session() as session:
        row = session.get(SportsbookDataset, dataset_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Dataset not found.")
        session.delete(row)
    return {"deleted": True}


@router.post("/datasets")
def upload(body: UploadBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Validate and store an uploaded CSV. Lines with problems are skipped and reported."""
    try:
        parsed = parse_csv(body.csv_text)
    except CsvError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _store(services, body.name.strip(), parsed, is_dummy=False, source_job_id=None)


@router.post("/datasets/dummy")
def generate_dummy(body: DummyBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Generate labelled DUMMY DATA covering a stored Timestamp Lab run's window."""
    result = _lab_result(services, body.lab_job_id)
    params = result.get("params") or {}
    start, end = params.get("start_ts"), params.get("end_ts")
    ticker = str(params.get("market_ticker") or "market")
    if not isinstance(start, int | float) or not isinstance(end, int | float) or end <= start:
        raise HTTPException(status_code=422, detail="That run has no usable time window.")
    text = dummy_csv(float(start), float(end), ticker, seed=zlib.crc32(ticker.encode()))
    parsed = parse_csv(text)
    return _store(services, f"{DUMMY_LABEL} for {ticker}", parsed, is_dummy=True, source_job_id=body.lab_job_id)


@router.get("/lab_runs/{job_id}/series")
def lab_series(job_id: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Kalshi price series available in a stored Timestamp Lab run."""
    result = _lab_result(services, job_id)
    params = result.get("params") or {}
    return {
        "job_id": job_id,
        "market_ticker": params.get("market_ticker"),
        "window": {"start": iso(params.get("start_ts")), "end": iso(params.get("end_ts"))},
        "series": [
            {"id": s.id, "label": s.label, "note": s.note, "points": sum(1 for p in s.points if p.price is not None)}
            for s in _series(result)
        ],
    }


@router.post("/overlay")
def compute_overlay(body: OverlayBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Sportsbook vs Kalshi probabilities at matched timestamps (no requests are sent)."""
    dataset = _dataset(services, body.dataset_id)
    rows: list[dict[str, Any]] = json.loads(dataset.rows_json)
    if not any(r["market"] == body.selection for r in rows):
        raise HTTPException(status_code=422, detail=f"No rows for outcome {body.selection!r} in this dataset.")
    result = _lab_result(services, body.lab_job_id)
    series = next((s for s in _series(result) if s.id == body.series_id), None)
    if series is None:
        raise HTTPException(status_code=422, detail="That price series is not in the chosen run.")
    out = overlay(rows, body.selection, series, body.max_staleness_s)
    selected_ts = [r["ts"] for r in out["rows"]]
    lo, hi = (min(selected_ts), max(selected_ts)) if selected_ts else (0.0, 0.0)
    pad = max(600.0, (hi - lo) * 0.05)
    kalshi_points = [
        {"ts": p.ts, "price": p.price}
        for p in series.points
        if p.price is not None and lo - pad <= p.ts <= hi + pad
    ][:MAX_CHART_POINTS]
    return {
        **out,
        "dataset": _summary(dataset),
        "is_dummy": dataset.is_dummy,
        "market_ticker": (result.get("params") or {}).get("market_ticker"),
        "series": {"id": series.id, "label": series.label, "note": series.note},
        "kalshi_points": kalshi_points,
        "params": body.model_dump(),
    }
