"""M1: endpoint catalog from the spec, auth probe job, and user-typed usefulness ratings."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analysis.auth_probe import (
    IdKind,
    ProbePlan,
    build_request,
    classify_probe,
    endpoint_id,
    plan_probe,
)
from app.errors import AuthNotConfigured
from app.evidence import is_account_path
from app.jobs import JobContext
from app.kalshi_client import CallResult, KalshiClient
from app.models import EndpointRating
from app.services import Services, get_services
from app.spec_loader import EndpointSpec

router = APIRouter(prefix="/api/m1", tags=["M1 endpoints"])

MODULE = "M1"
PROBE_KIND = "auth_probe"
PROBE_REQUEST_CAP = 150


class ProbeOptions(BaseModel):
    """Auth-probe options chosen in the control panel."""

    include_account: bool = False


class RatingBody(BaseModel):
    """User-typed usefulness rating for one endpoint."""

    endpoint_id: str = Field(max_length=256)
    rating: int | None = Field(default=None, ge=1, le=5)
    reason: str = Field(default="", max_length=5000)


def _first(body: Any, list_key: str, field: str) -> str | None:
    """``body[list_key][0][field]`` as a string, if present."""
    if not isinstance(body, dict):
        return None
    items = body.get(list_key)
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    value = items[0].get(field)
    return str(value) if value not in (None, "") else None


def _discovery_count(needed: set[IdKind]) -> int:
    count = 0
    if needed & {"market_ticker", "event_ticker", "series_ticker"}:
        count += 1
    if "series_ticker" in needed:
        count += 1
    count += sum(
        k in needed
        for k in (
            "historical_market_ticker",
            "milestone_id",
            "structured_target_id",
            "collection_ticker",
        )
    )
    return count


def _estimate(plan: ProbePlan, auth_available: bool) -> dict[str, int]:
    per_target = 2 if auth_available else 1
    discovery = _discovery_count(plan.needed_ids)
    probes = per_target * len(plan.targets)
    total = discovery + probes
    return {"discovery": discovery, "probes": probes, "total": total, "cap": PROBE_REQUEST_CAP}


def _catalog_row(endpoint: EndpointSpec) -> dict[str, Any]:
    return {
        "id": endpoint_id(endpoint),
        "method": endpoint.method,
        "path": endpoint.path,
        "category": endpoint.tags[0] if endpoint.tags else "untagged",
        "tags": endpoint.tags,
        "summary": endpoint.summary,
        "auth_required_spec": endpoint.auth_required,
        "params": [p.name for p in endpoint.params],
        "path_params": [p.name for p in endpoint.path_params],
        "required_query_params": [p.name for p in endpoint.required_query_params],
        "pagination_params": endpoint.pagination_params,
        "time_range_params": endpoint.time_range_params,
        "timestamp_fields": [f.path for f in endpoint.timestamp_fields],
        "historical_signals": endpoint.historical_signals,
        "account_specific": is_account_path(endpoint.path),
    }


@router.get("/catalog")
def catalog(services: Services = Depends(get_services)) -> dict[str, Any]:
    """Every spec operation with objective signals, latest probe results, and user ratings."""
    latest = services.jobs.latest_with_result(MODULE, PROBE_KIND)
    probes: dict[str, Any] = {}
    if latest is not None and latest["result"] is not None:
        probes = {r["endpoint_id"]: r for r in latest["result"].get("results", [])}
        probes.update({s["endpoint_id"]: s for s in latest["result"].get("skipped", [])})
    with services.db.session() as session:
        ratings = {
            r.endpoint_id: {"rating": r.rating, "reason": r.reason}
            for r in session.scalars(select(EndpointRating))
        }
    rows = []
    for endpoint in services.spec.endpoints:
        row = _catalog_row(endpoint)
        row["probe"] = probes.get(row["id"])
        row["user"] = ratings.get(row["id"], {"rating": None, "reason": ""})
        rows.append(row)
    return {
        "spec_version": services.spec.version,
        "endpoints": rows,
        "probe_job": None
        if latest is None
        else {
            "id": latest["id"],
            "status": latest["status"],
            "finished_at": latest["finished_at"],
            "partial": bool(latest["result"] and latest["result"].get("partial")),
            "discovered_ids": (latest["result"] or {}).get("discovered_ids", {}),
        },
    }


@router.put("/ratings")
def save_rating(body: RatingBody, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Autosave target for the per-endpoint rating and reason (user-typed)."""
    known = {endpoint_id(e) for e in services.spec.endpoints}
    if body.endpoint_id not in known:
        raise HTTPException(status_code=404, detail="Unknown endpoint id.")
    now = datetime.now(UTC)
    with services.db.session() as session:
        row = session.get(EndpointRating, body.endpoint_id)
        if row is None:
            session.add(
                EndpointRating(
                    endpoint_id=body.endpoint_id,
                    rating=body.rating,
                    reason=body.reason,
                    updated_at=now,
                )
            )
        else:
            row.rating, row.reason, row.updated_at = body.rating, body.reason, now
    return {"endpoint_id": body.endpoint_id, "updated_at": now.isoformat()}


@router.post("/probe/plan")
def probe_plan(options: ProbeOptions, services: Services = Depends(get_services)) -> dict[str, Any]:
    """What the probe would do, and how many requests it would send (no requests sent)."""
    plan = plan_probe(services.spec, options.include_account)
    return {
        "targets": len(plan.targets),
        "skipped": len(plan.skipped),
        "needed_ids": sorted(plan.needed_ids),
        "credentials_configured": services.config.credentials_configured,
        "estimate": _estimate(plan, services.config.credentials_configured),
    }


async def _discover_ids(
    client: KalshiClient, ctx: JobContext, needed: set[IdKind]
) -> dict[IdKind, str]:
    """Pull IDs from public list endpoints so path parameters can be filled."""
    ids: dict[IdKind, str] = {}

    async def fetch(path: str, params: dict[str, Any]) -> Any:
        result = await client.call("GET", path, params=params, job_id=ctx.id)
        ctx.log(f"Discovery GET {path}: HTTP {result.status_code}")
        return result.json() if result.ok else None

    if needed & {"market_ticker", "event_ticker", "series_ticker"}:
        body = await fetch("/markets", {"limit": 1, "status": "open", "mve_filter": "exclude"})
        if (ticker := _first(body, "markets", "ticker")) is not None:
            ids["market_ticker"] = ticker
        if (event := _first(body, "markets", "event_ticker")) is not None:
            ids["event_ticker"] = event
    if "series_ticker" in needed and "event_ticker" in ids:
        body = await fetch(f"/events/{ids['event_ticker']}", {})
        event = body.get("event") if isinstance(body, dict) else None
        if isinstance(event, dict) and event.get("series_ticker"):
            ids["series_ticker"] = str(event["series_ticker"])
    if "historical_market_ticker" in needed:
        body = await fetch("/historical/markets", {"limit": 1})
        if (archived := _first(body, "markets", "ticker")) is not None:
            ids["historical_market_ticker"] = archived
    if "milestone_id" in needed:
        body = await fetch("/milestones", {"limit": 1})
        if (milestone := _first(body, "milestones", "id")) is not None:
            ids["milestone_id"] = milestone
    if "structured_target_id" in needed:
        body = await fetch("/structured_targets", {"page_size": 1})
        if (target := _first(body, "structured_targets", "id")) is not None:
            ids["structured_target_id"] = target
    if "collection_ticker" in needed:
        body = await fetch("/multivariate_event_collections", {"limit": 1})
        if (coll := _first(body, "multivariate_contracts", "collection_ticker")) is not None:
            ids["collection_ticker"] = coll
    return ids


def _call_summary(result: CallResult) -> dict[str, Any]:
    return {
        "status": result.status_code,
        "latency_ms": result.latency_ms,
        "request_id": result.request_id,
        "error": result.error,
    }


@router.post("/probe/run")
async def run_probe(options: ProbeOptions, services: Services = Depends(get_services)) -> dict[str, str]:
    """Start the auth probe: each probe-able GET once without and once with the key."""
    plan = plan_probe(services.spec, options.include_account)
    auth_available = services.config.credentials_configured
    client = services.client

    async def runner(ctx: JobContext) -> dict[str, Any]:
        skipped = [
            {
                "endpoint_id": endpoint_id(s.endpoint),
                "classification": "not probed",
                "note": s.reason,
            }
            for s in plan.skipped
        ]
        results: list[dict[str, Any]] = []
        snapshot: dict[str, Any] = {"results": results, "skipped": skipped, "discovered_ids": {}}
        ctx.save_partial(snapshot)
        if not auth_available:
            ctx.log("No API key configured: only unauthenticated calls will be made.", "warn")

        ids = await _discover_ids(client, ctx, plan.needed_ids)
        snapshot["discovered_ids"] = dict(ids)
        ctx.log(f"Discovered IDs: {ids or 'none'}")
        now_s = int(time.time())
        total = len(plan.targets)
        for index, target in enumerate(plan.targets):
            eid = endpoint_id(target.endpoint)
            ctx.progress(index, total, eid)
            request = build_request(target, ids, now_s)
            if request is None:
                missing = sorted(target.needs - set(ids))
                skipped.append(
                    {
                        "endpoint_id": eid,
                        "classification": "not probed",
                        "note": f"Could not discover: {', '.join(missing)}.",
                    }
                )
                continue
            path, params = request
            no_auth = await client.call("GET", path, params=params, job_id=ctx.id)
            auth: CallResult | None = None
            if auth_available:
                try:
                    auth = await client.call("GET", path, params=params, auth=True, job_id=ctx.id)
                except AuthNotConfigured as exc:
                    ctx.log(exc.user_message, "warn")
            verdict = classify_probe(
                no_auth.status_code,
                auth.status_code if auth is not None else None,
                target.endpoint.auth_required,
            )
            results.append(
                {
                    "endpoint_id": eid,
                    "concrete_path": path,
                    "params": params,
                    "no_auth": _call_summary(no_auth),
                    "auth": _call_summary(auth) if auth is not None else None,
                    "classification": verdict.classification,
                    "mismatch": verdict.mismatch,
                    "note": verdict.note,
                }
            )
            ctx.log(
                f"{eid}: no key {no_auth.status_code}, "
                f"key {auth.status_code if auth is not None else 'n/a'} -> {verdict.classification}"
                + (" (MISMATCH vs spec)" if verdict.mismatch else ""),
                "warn" if verdict.mismatch else "info",
            )
        ctx.progress(total, total, "Done")
        return snapshot

    job_id = services.jobs.start(
        MODULE,
        PROBE_KIND,
        options.model_dump(),
        runner,
        max_requests=PROBE_REQUEST_CAP,
    )
    return {"job_id": job_id}
