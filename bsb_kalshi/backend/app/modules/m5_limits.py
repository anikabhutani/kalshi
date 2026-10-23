"""M5: Limits Tester. Documented limits next to measured behavior.

- Documentation: values parsed from specs/rate_limits.md (see ``app.analysis.limits``).
- Account limits: ``GET /account/limits`` (authenticated) and ``GET /account/endpoint_costs``.
- Ramp test: one cheap GET endpoint at increasing request rates, recording latency and any
  rate-limit-like response headers; it stops at the first HTTP 429 and never exceeds the
  global limiter (the step rates must not exceed the rate set in Settings).
- Pagination analyzer: default/maximum/over-maximum page sizes and a cursor walk with
  duplicate and last-page detection.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.analysis.limits import (
    end_signal,
    identity,
    list_key,
    parse_rate_doc,
    ramp_rates,
    rate_headers,
    step_metrics,
)
from app.errors import RateLimited
from app.evidence import is_account_path
from app.jobs import JobContext
from app.services import Services, get_services
from app.spec_loader import EndpointSpec, OpenApiSpec

router = APIRouter(prefix="/api/m5", tags=["M5 limits"])

MODULE = "M5"
RAMP_HARD_CAP = 200
RETRY_HEADROOM = 4
SIZE_PARAMS = ("limit", "page_size")


def ramp_choices(spec: OpenApiSpec) -> list[str]:
    """Non-account GET endpoints that need no path or required query parameters."""
    return [
        e.path
        for e in spec.get_endpoints()
        if not is_account_path(e.path) and not e.path_params and not e.required_query_params
    ]


def _size_param(endpoint: EndpointSpec) -> str | None:
    return next((n for n in SIZE_PARAMS if endpoint.param(n) is not None), None)


def pagination_choices(spec: OpenApiSpec) -> list[dict[str, Any]]:
    """Cursor-paginated, non-account GET endpoints without path parameters, with spec page sizes."""
    choices: list[dict[str, Any]] = []
    for e in spec.get_endpoints():
        size = _size_param(e)
        if is_account_path(e.path) or e.path_params or e.param("cursor") is None or size is None:
            continue
        if any(p.name != size for p in e.required_query_params):
            continue
        size_spec = e.param(size)
        assert size_spec is not None
        cursor_spec = e.param("cursor")
        choices.append(
            {
                "path": e.path,
                "size_param": size,
                "size_default": size_spec.default,
                "size_minimum": size_spec.minimum,
                "size_maximum": size_spec.maximum,
                "size_description": size_spec.description,
                "cursor_description": cursor_spec.description if cursor_spec else None,
                "filter_params": [
                    p.name for p in e.params if p.location == "query" and p.name not in ("cursor", size)
                ],
                "list_keys": spec.response_array_keys(e.path),
            }
        )
    return choices


@router.get("/doc")
def rate_doc(services: Services = Depends(get_services)) -> dict[str, Any]:
    """Parsed rate_limits.md, client limiter settings, and endpoint choices (no requests sent)."""
    text = (services.config.specs_dir / "rate_limits.md").read_text(encoding="utf-8")
    current = services.settings.get()
    return {
        **parse_rate_doc(text),
        "client_limiter": {"rate_limit_rps": current.rate_limit_rps, "rate_limit_burst": current.rate_limit_burst},
        "ramp_choices": ramp_choices(services.spec),
        "pagination_choices": pagination_choices(services.spec),
        "credentials_configured": services.config.credentials_configured,
    }


@router.post("/account/run")
async def run_account_limits(services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: read the account's tier/bucket limits and the list of non-default endpoint costs."""
    client = services.client
    credentials = services.config.credentials_configured
    spec = services.spec

    async def runner(ctx: JobContext) -> dict[str, Any]:
        result: dict[str, Any] = {"limits": None, "endpoint_costs": None, "calls": []}
        for index, path in enumerate(("/account/limits", "/account/endpoint_costs")):
            endpoint = spec.find("GET", path)
            auth = bool(endpoint and endpoint.auth_required)
            ctx.progress(index, 2, f"GET {path}")
            if auth and not credentials:
                result["calls"].append({"path": path, "auth": auth, "status": None, "note": "skipped: no API key configured"})
                continue
            res = await client.call("GET", path, auth=auth, job_id=ctx.id)
            body = res.json() if res.ok else None
            result["calls"].append(
                {"path": path, "auth": auth, "status": res.status_code, "request_id": res.request_id, "error": res.error}
            )
            key = "limits" if path == "/account/limits" else "endpoint_costs"
            result[key] = body if isinstance(body, dict) else None
            ctx.log(f"GET {path}: HTTP {res.status_code}")
        ctx.progress(2, 2, "Done")
        return result

    job_id = services.jobs.start(MODULE, "account_limits", {}, runner, max_requests=6)
    return {"job_id": job_id}


class RampParams(BaseModel):
    """Ramp test configuration."""

    path: str = "/exchange/status"
    auth: bool = False
    start_rps: float = Field(default=1.0, gt=0, le=20)
    step_rps: float = Field(default=0.5, gt=0, le=10)
    max_rps: float = Field(default=2.0, gt=0, le=20)
    requests_per_step: int = Field(default=10, ge=3, le=50)


def _check_ramp(params: RampParams, services: Services) -> list[float]:
    if params.path not in ramp_choices(services.spec):
        raise HTTPException(status_code=422, detail="Choose a listed endpoint (no path or required parameters).")
    if params.auth and not services.config.credentials_configured:
        raise HTTPException(status_code=422, detail="No API key configured, so the ramp cannot use authentication.")
    limit = services.settings.get().rate_limit_rps
    if params.max_rps > limit + 1e-9:
        raise HTTPException(
            status_code=422,
            detail=(
                f"The highest step ({params.max_rps} req/s) is above the global rate limit in Settings "
                f"({limit} req/s). Lower the maximum, or raise the limit in Settings first."
            ),
        )
    if params.start_rps > params.max_rps:
        raise HTTPException(status_code=422, detail="Start rate must not exceed the maximum rate.")
    rates = ramp_rates(params.start_rps, params.step_rps, params.max_rps)
    if len(rates) * params.requests_per_step > RAMP_HARD_CAP:
        raise HTTPException(
            status_code=422,
            detail=f"This ramp would send {len(rates) * params.requests_per_step} requests; the hard cap is {RAMP_HARD_CAP}.",
        )
    return rates


def _ramp_estimate(rates: list[float], params: RampParams) -> dict[str, int]:
    total = len(rates) * params.requests_per_step
    return {"steps": len(rates), "per_step": params.requests_per_step, "total": total, "cap": total + RETRY_HEADROOM}


@router.post("/ramp/plan")
def ramp_plan(params: RampParams, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Step rates and request estimate (no requests sent)."""
    rates = _check_ramp(params, services)
    return {"rates": rates, "estimate": _ramp_estimate(rates, params)}


@router.post("/ramp/run")
async def ramp_run(params: RampParams, services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: send ``requests_per_step`` requests at each step rate; stop at the first 429."""
    rates = _check_ramp(params, services)
    estimate = _ramp_estimate(rates, params)
    client = services.client
    limiter = services.settings.get()
    other_jobs = services.jobs.running_count()

    async def runner(ctx: JobContext) -> dict[str, Any]:
        started = datetime.now(UTC)
        requests: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        header_names: set[str] = set()
        rate_header_names: set[str] = set()
        first_429: dict[str, Any] | None = None
        result: dict[str, Any] = {
            "params": params.model_dump(),
            "rates": rates,
            "limiter": {"rate_limit_rps": limiter.rate_limit_rps, "rate_limit_burst": limiter.rate_limit_burst},
            "other_running_jobs_at_start": other_jobs,
            "started_at": started.isoformat(),
            "requests": requests,
            "steps": steps,
        }
        ctx.save_partial(result)
        for step_index, rate in enumerate(rates):
            ctx.progress(step_index, len(rates), f"Step {step_index + 1}/{len(rates)}: {rate} req/s")
            step_rows: list[dict[str, Any]] = []
            step_start = time.monotonic()
            for i in range(params.requests_per_step):
                delay = step_start + i / rate - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    res = await client.call("GET", params.path, auth=params.auth, job_id=ctx.id)
                except RateLimited as exc:
                    t_s = (datetime.now(UTC) - started).total_seconds()
                    first_429 = {"step": step_index, "target_rps": rate, "index": i, "t_s": round(t_s, 3), "message": exc.user_message}
                    step_rows.append({"step": step_index, "target_rps": rate, "index": i, "t_s": t_s, "latency_ms": None, "status": 429})
                    ctx.log(f"HTTP 429 at step {step_index + 1} ({rate} req/s), request {i + 1}. Stopping.", "warn")
                    break
                header_names.update(k.lower() for k in res.headers)
                found = rate_headers(res.headers)
                rate_header_names.update(found)
                step_rows.append(
                    {
                        "step": step_index,
                        "target_rps": rate,
                        "index": i,
                        "t_s": round((res.sent_at - started).total_seconds(), 4),
                        "latency_ms": res.latency_ms,
                        "status": res.status_code,
                        "rate_headers": found,
                        "request_id": res.request_id,
                        "error": res.error,
                    }
                )
            requests.extend(step_rows)
            metrics = step_metrics(step_rows, rate)
            steps.append(metrics)
            ctx.log(
                f"Step {step_index + 1}: target {rate} req/s, achieved {metrics['achieved_rps']} req/s, "
                f"median latency {metrics['latency_median_ms']} ms"
            )
            if first_429 is not None:
                break
        result.update(
            {
                "first_429": first_429,
                "stopped_reason": "first HTTP 429" if first_429 else None,
                "header_names_seen": sorted(header_names),
                "rate_header_names_seen": sorted(rate_header_names),
            }
        )
        ctx.progress(len(rates), len(rates), "Done")
        return result

    job_id = services.jobs.start(MODULE, "ramp", params.model_dump(), runner, max_requests=estimate["cap"])
    return {"job_id": job_id}


class PaginationParams(BaseModel):
    """Pagination analyzer configuration."""

    path: str = "/markets"
    filters: dict[str, str] = Field(default_factory=dict, max_length=8)
    walk_size: int | None = Field(default=None, ge=1, le=10_000)
    page_cap: int = Field(default=5, ge=1, le=30)
    boundary_tests: bool = True

    @field_validator("filters")
    @classmethod
    def _clean(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned = {k.strip(): v.strip() for k, v in value.items() if k.strip() and v.strip()}
        if any(len(v) > 128 for v in cleaned.values()):
            raise ValueError("filter values must be at most 128 characters")
        return cleaned


def _pagination_setup(params: PaginationParams, spec: OpenApiSpec) -> dict[str, Any]:
    choice = next((c for c in pagination_choices(spec) if c["path"] == params.path), None)
    if choice is None:
        raise HTTPException(status_code=422, detail="Choose a listed cursor-paginated endpoint.")
    unknown = sorted(set(params.filters) - set(choice["filter_params"]))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Not query parameters of GET {params.path}: {', '.join(unknown)}.")
    return choice


def _boundary_cases(choice: dict[str, Any]) -> list[tuple[str, int | None]]:
    cases: list[tuple[str, int | None]] = [("No size parameter (server default)", None)]
    maximum, minimum = choice["size_maximum"], choice["size_minimum"]
    if maximum is not None:
        cases += [("Spec maximum", int(maximum)), ("Spec maximum + 1", int(maximum) + 1)]
    if minimum is not None:
        cases.append(("Spec minimum", int(minimum)))
    return cases


def _pagination_estimate(params: PaginationParams, choice: dict[str, Any]) -> dict[str, int]:
    boundary = len(_boundary_cases(choice)) if params.boundary_tests else 0
    total = boundary + params.page_cap
    return {"boundary": boundary, "walk_pages": params.page_cap, "total": total, "cap": total + RETRY_HEADROOM}


@router.post("/pagination/plan")
def pagination_plan(params: PaginationParams, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Spec page-size facts and request estimate (no requests sent)."""
    choice = _pagination_setup(params, services.spec)
    return {"choice": choice, "estimate": _pagination_estimate(params, choice)}


@router.post("/pagination/run")
async def pagination_run(params: PaginationParams, services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: boundary page-size tests, then a cursor walk with duplicate/last-page detection."""
    choice = _pagination_setup(params, services.spec)
    estimate = _pagination_estimate(params, choice)
    client = services.client
    size_param: str = choice["size_param"]
    walk_size = params.walk_size or (int(choice["size_default"]) if choice["size_default"] else 100)
    if choice["size_maximum"] is not None:
        walk_size = min(walk_size, int(choice["size_maximum"]))

    async def runner(ctx: JobContext) -> dict[str, Any]:
        boundary: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        result: dict[str, Any] = {
            "params": params.model_dump(),
            "spec": choice,
            "walk_size": walk_size,
            "boundary": boundary,
            "pages": pages,
        }
        ctx.save_partial(result)
        total_steps = (len(_boundary_cases(choice)) if params.boundary_tests else 0) + params.page_cap
        done = 0

        async def fetch(size: int | None, cursor: str | None) -> tuple[Any, Any, str | None, list[Any]]:
            query: dict[str, Any] = {**params.filters, size_param: size, "cursor": cursor}
            res = await client.call("GET", params.path, params=query, job_id=ctx.id, store_raw=True)
            body = res.json()
            key = list_key(body, choice["list_keys"])
            items = body.get(key) if key is not None and isinstance(body, dict) else []
            return res, body, key, items if isinstance(items, list) else []

        if params.boundary_tests:
            for label, size in _boundary_cases(choice):
                ctx.progress(done, total_steps, label)
                res, body, key, items = await fetch(size, None)
                boundary.append(
                    {
                        "case": label,
                        "size_sent": size,
                        "status": res.status_code,
                        "items": len(items) if res.ok else None,
                        "list_key": key,
                        "cursor_returned": end_signal(body) is None if res.ok else None,
                        "error_sample": None if res.ok else (res.body or b"")[:300].decode("utf-8", errors="replace"),
                        "request_id": res.request_id,
                    }
                )
                done += 1

        seen: dict[str, int] = {}
        cursors: set[str] = set()
        cursor: str | None = None
        identity_key: str | None = None
        for page in range(params.page_cap):
            ctx.progress(done, total_steps, f"Cursor walk page {page + 1}")
            res, body, key, items = await fetch(walk_size, cursor)
            done += 1
            duplicates = 0
            for item in items:
                id_key, value = identity(item)
                identity_key = identity_key or id_key
                if value in seen:
                    duplicates += 1
                else:
                    seen[value] = page
            signal = end_signal(body) if res.ok else None
            next_cursor = body.get("cursor") if res.ok and signal is None and isinstance(body, dict) else None
            pages.append(
                {
                    "page": page + 1,
                    "status": res.status_code,
                    "items": len(items),
                    "duplicates_of_earlier_pages": duplicates,
                    "cursor_length": len(next_cursor) if isinstance(next_cursor, str) else None,
                    "cursor_prefix": next_cursor[:12] if isinstance(next_cursor, str) else None,
                    "cursor_repeated": isinstance(next_cursor, str) and next_cursor in cursors,
                    "end_signal": signal,
                    "list_key": key,
                    "request_id": res.request_id,
                }
            )
            if not res.ok or next_cursor is None or next_cursor in cursors:
                break
            cursors.add(next_cursor)
            cursor = next_cursor

        last = pages[-1] if pages else None
        result["summary"] = {
            "identity_key": identity_key,
            "unique_items": len(seen),
            "duplicate_items": sum(p["duplicates_of_earlier_pages"] for p in pages),
            "pages_fetched": len(pages),
            "last_page_reached": last is not None and last["end_signal"] is not None,
            "last_page_signal": last["end_signal"] if last else None,
            "last_page_items": last["items"] if last else None,
            "last_page_smaller_than_size": last is not None and last["end_signal"] is not None and last["items"] < walk_size,
        }
        ctx.progress(total_steps, total_steps, "Done")
        return result

    job_id = services.jobs.start(MODULE, "pagination", params.model_dump(), runner, max_requests=estimate["cap"])
    return {"job_id": job_id}
