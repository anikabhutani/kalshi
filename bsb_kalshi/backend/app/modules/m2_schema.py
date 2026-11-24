"""M2: browse sports series/events/markets and build a field dictionary for one game.

Sports are discovered from the API (``/search/tags_by_categories`` and
``/search/filters_by_sport``); no category or sport name is hardcoded. Browse routes send
one logged request each (briefly cached in memory); the "pull game" job stores raw JSON.
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.analysis.flatten import FieldEntry, flatten_samples
from app.errors import RateLimited, ReconError
from app.jobs import JobContext
from app.kalshi_client import CallResult
from app.services import Services, get_services
from app.spec_loader import OpenApiSpec, SpecProperty

router = APIRouter(prefix="/api/m2", tags=["M2 schema"])

MODULE = "M2"
PULL_KIND = "pull_game"
_CACHE_TTL_S = 600.0
_SPORT_NAME_RE = re.compile(r"sport", re.IGNORECASE)
_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}


class PullRequest(BaseModel):
    """Which game to pull."""

    series_ticker: str = Field(min_length=1, max_length=128)
    event_ticker: str = Field(min_length=1, max_length=128)


async def _browse_json(
    services: Services, path: str, params: dict[str, Any] | None = None
) -> Any:
    """One logged GET for a browse route, cached briefly; errors become readable HTTP errors."""
    key = (path, tuple(sorted((params or {}).items())))
    cached = _cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    try:
        result = await services.client.call("GET", path, params=params, module=MODULE)
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=exc.user_message) from None
    except ReconError as exc:
        raise HTTPException(status_code=400, detail=exc.user_message) from None
    if not result.ok:
        detail = result.error or f"Kalshi returned HTTP {result.status_code} for GET {path}."
        raise HTTPException(status_code=502, detail=detail)
    body = result.json()
    _cache[key] = (time.monotonic(), body)
    return body


@router.get("/categories")
async def categories(services: Services = Depends(get_services)) -> dict[str, Any]:
    """Series categories and their tags, plus the sport list, as returned by the API."""
    tags_body = await _browse_json(services, "/search/tags_by_categories")
    sports_body = await _browse_json(services, "/search/filters_by_sport")
    mapping = (tags_body or {}).get("tags_by_categories") or {}
    cats = [{"name": name, "tags": tags or []} for name, tags in mapping.items()]
    suggested = next((c["name"] for c in cats if _SPORT_NAME_RE.search(c["name"])), None)
    events_endpoint = services.spec.find("GET", "/events")
    status_param = events_endpoint.param("status") if events_endpoint is not None else None
    return {
        "categories": cats,
        "suggested_category": suggested,
        "sport_ordering": (sports_body or {}).get("sport_ordering") or [],
        "event_statuses": (status_param.enum if status_param is not None else None) or [],
    }


@router.get("/series")
async def series_list(
    category: str = Query(min_length=1),
    tag: str | None = None,
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    """Series in a category (optionally one tag), compacted for the picker."""
    params: dict[str, Any] = {"category": category}
    if tag:
        params["tags"] = tag
    body = await _browse_json(services, "/series", params)
    return [
        {
            "ticker": s.get("ticker"),
            "title": s.get("title"),
            "frequency": s.get("frequency"),
            "category": s.get("category"),
            "tags": s.get("tags") or [],
        }
        for s in (body or {}).get("series") or []
    ]


@router.get("/events")
async def events_list(
    series_ticker: str = Query(min_length=1),
    status: str | None = None,
    cursor: str | None = None,
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """One page (max size per spec) of events in a series, compacted for the picker."""
    endpoint = services.spec.find("GET", "/events")
    limit_param = endpoint.param("limit") if endpoint is not None else None
    limit = int(limit_param.maximum) if limit_param and limit_param.maximum else None
    params: dict[str, Any] = {"series_ticker": series_ticker, "limit": limit}
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    body = await _browse_json(services, "/events", params) or {}
    return {
        "events": [
            {
                "event_ticker": e.get("event_ticker"),
                "title": e.get("title"),
                "sub_title": e.get("sub_title"),
                "strike_date": e.get("strike_date"),
                "last_updated_ts": e.get("last_updated_ts"),
            }
            for e in body.get("events") or []
        ],
        "cursor": body.get("cursor") or None,
    }


def _annotate(
    rows: list[FieldEntry], spec_props: dict[str, SpecProperty]
) -> list[dict[str, Any]]:
    """Add spec comparison columns to top-level fields (nested fields are left unannotated)."""
    annotated: list[dict[str, Any]] = []
    for row in rows:
        data = row.to_dict()
        top_level = "." not in row.path and "[]" not in row.path
        prop = spec_props.get(row.path) if top_level else None
        data["in_spec"] = (prop is not None) if top_level else None
        data["spec_type"] = prop.type if prop else None
        data["spec_format"] = prop.format if prop else None
        data["spec_nullable"] = prop.nullable if prop else None
        data["spec_required"] = prop.required if prop else None
        data["spec_enum"] = prop.enum if prop else None
        data["values_outside_spec_enum"] = (
            [v for v in row.distinct_values if v not in prop.enum] if prop and prop.enum else []
        )
        data["spec_description"] = prop.description if prop else None
        annotated.append(data)
    return annotated


def _entity(
    spec: OpenApiSpec,
    samples: list[Any],
    spec_path: str,
    spec_key: str,
    request_id: int | None,
    omitted: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Field dictionary for one entity; ``omitted`` keys were split out on purpose."""
    spec_props = spec.response_object_properties(spec_path, spec_key)
    rows = flatten_samples(samples)
    observed_top = {r.path for r in rows if "." not in r.path and "[]" not in r.path}
    return {
        "samples": len(samples),
        "spec_source": f"GET {spec_path} -> {spec_key}",
        "request_id": request_id,
        "fields": _annotate(rows, spec_props),
        "spec_fields_not_observed": sorted(set(spec_props) - observed_top - omitted),
        "omitted_fields": sorted(omitted),
    }


def _links(
    series: dict[str, Any], event: dict[str, Any], markets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fields whose values equal the parent's identifier (checked on every record)."""
    series_ticker = series.get("ticker")
    event_ticker = event.get("event_ticker")
    links: list[dict[str, Any]] = []
    for name, value in event.items():
        if series_ticker and value == series_ticker:
            links.append(
                {"child": f"event.{name}", "parent": "series.ticker", "records": 1, "matching": 1}
            )
    if markets and event_ticker:
        for name in sorted({k for m in markets for k in m}):
            matching = sum(1 for m in markets if m.get(name) == event_ticker)
            if matching:
                links.append(
                    {
                        "child": f"market.{name}",
                        "parent": "event.event_ticker",
                        "records": len(markets),
                        "matching": matching,
                    }
                )
    return links


@router.post("/pull")
async def pull_game(body: PullRequest, services: Services = Depends(get_services)) -> dict[str, str]:
    """Job: pull series -> event -> markets for one game, store raw JSON, build dictionaries."""
    client = services.client
    spec = services.spec
    endpoint = spec.find("GET", "/markets")
    limit_param = endpoint.param("limit") if endpoint is not None else None
    markets_limit = int(limit_param.maximum) if limit_param and limit_param.maximum else None

    async def runner(ctx: JobContext) -> dict[str, Any]:
        steps = 4

        async def get(label: str, path: str, params: dict[str, Any] | None = None) -> CallResult:
            result = await client.call("GET", path, params=params, job_id=ctx.id, store_raw=True)
            ctx.log(f"{label}: GET {path} -> HTTP {result.status_code} ({result.latency_ms:.0f} ms)")
            return result

        ctx.progress(0, steps, "Series")
        series_res = await get("Series", f"/series/{body.series_ticker}")
        series_obj = (series_res.json() or {}).get("series") if series_res.ok else None
        if not isinstance(series_obj, dict):
            raise ReconError(f"Could not load series {body.series_ticker} (HTTP {series_res.status_code}).")

        ctx.progress(1, steps, "Event with nested markets")
        event_res = await get(
            "Event", f"/events/{body.event_ticker}", {"with_nested_markets": "true"}
        )
        event_body = event_res.json() if event_res.ok else None
        event_obj = (event_body or {}).get("event")
        if not isinstance(event_obj, dict):
            raise ReconError(f"Could not load event {body.event_ticker} (HTTP {event_res.status_code}).")
        nested = [m for m in event_obj.get("markets") or [] if isinstance(m, dict)]

        ctx.progress(2, steps, "Markets list")
        markets_params = {"event_ticker": body.event_ticker, "limit": markets_limit}
        markets_res = await get("Markets", "/markets", markets_params)
        markets = [m for m in ((markets_res.json() or {}).get("markets") or []) if isinstance(m, dict)]
        markets_source, markets_spec_path, markets_req = "/markets", "/markets", markets_res
        if not markets:
            ctx.progress(3, steps, "Historical markets list")
            ctx.log("Live /markets returned no markets; trying /historical/markets.", "warn")
            hist_res = await get("Historical markets", "/historical/markets", markets_params)
            markets = [
                m for m in ((hist_res.json() or {}).get("markets") or []) if isinstance(m, dict)
            ]
            markets_source, markets_spec_path, markets_req = (
                "/historical/markets",
                "/historical/markets",
                hist_res,
            )

        event_core = {k: v for k, v in event_obj.items() if k != "markets"}
        nested_tickers = {m.get("ticker") for m in nested}
        list_tickers = {m.get("ticker") for m in markets}
        ctx.progress(steps, steps, "Done")
        return {
            "series_ticker": body.series_ticker,
            "event_ticker": body.event_ticker,
            "markets_source": markets_source,
            "entities": {
                "series": _entity(spec, [series_obj], "/series/{series_ticker}", "series", series_res.request_id),
                "event": _entity(
                    spec,
                    [event_core],
                    "/events/{event_ticker}",
                    "event",
                    event_res.request_id,
                    omitted=frozenset({"markets"}),
                ),
                "market": _entity(spec, markets, markets_spec_path, "markets", markets_req.request_id),
            },
            "tree": {
                "series": {"ticker": series_obj.get("ticker"), "title": series_obj.get("title")},
                "event": {
                    "event_ticker": event_obj.get("event_ticker"),
                    "series_ticker": event_obj.get("series_ticker"),
                    "title": event_obj.get("title"),
                    "sub_title": event_obj.get("sub_title"),
                },
                "markets": [
                    {
                        "ticker": m.get("ticker"),
                        "event_ticker": m.get("event_ticker"),
                        "yes_sub_title": m.get("yes_sub_title"),
                        "status": m.get("status"),
                        "open_time": m.get("open_time"),
                        "close_time": m.get("close_time"),
                    }
                    for m in markets
                ],
            },
            "links": _links(series_obj, event_core, markets),
            "nested_vs_list": {
                "nested_count": len(nested),
                "list_count": len(markets),
                "only_in_nested": sorted(str(t) for t in nested_tickers - list_tickers),
                "only_in_list": sorted(str(t) for t in list_tickers - nested_tickers),
            },
        }

    job_id = services.jobs.start(MODULE, PULL_KIND, body.model_dump(), runner, max_requests=8)
    return {"job_id": job_id}
