"""M5 helpers: rate_limits.md parsing, rate-limit header capture, ramp metrics, pagination checks.

Parsing rules for specs/rate_limits.md (pasted documentation, not interpreted):
- The tier table is the Markdown table whose header row contains "Tier" and "Read budget".
  Numbers keep their documented values; thousands separators are removed.
- The default request cost is the integer in the sentence "... the default of N tokens".
- Every other section is returned verbatim with its heading so the UI can quote it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections.abc import Iterable, Mapping
from typing import Any

RATE_HEADER_RE = re.compile(r"rate|limit|remaining|retry|reset|quota|throttl", re.IGNORECASE)
_DEFAULT_COST_RE = re.compile(r"default of (\d+) tokens", re.IGNORECASE)
_IDENTITY_KEYS = (
    "trade_id",
    "ticker",
    "event_ticker",
    "series_ticker",
    "collection_ticker",
    "id",
    "milestone_id",
)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _number(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_rate_doc(text: str) -> dict[str, Any]:
    """Tier budgets, default cost, and verbatim sections from rate_limits.md."""
    lines = text.splitlines()
    tiers: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        header = _cells(line) if line.lstrip().startswith("|") else []
        if "Tier" in header and any("Read budget" in h for h in header):
            read_col = next(j for j, h in enumerate(header) if "Read budget" in h)
            write_col = next((j for j, h in enumerate(header) if "Write budget" in h), None)
            for row_line in lines[i + 2 :]:
                if not row_line.lstrip().startswith("|"):
                    break
                cells = _cells(row_line)
                if len(cells) < len(header):
                    continue
                tiers.append(
                    {
                        "tier": cells[0],
                        "read_budget": _number(cells[read_col]),
                        "write_budget": _number(cells[write_col]) if write_col is not None else None,
                    }
                )
            break

    match = _DEFAULT_COST_RE.search(text)
    sections: list[dict[str, str]] = []
    heading: str | None = None
    body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if heading is not None:
                sections.append({"heading": heading, "text": "\n".join(body).strip()})
            heading, body = line[3:].strip(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections.append({"heading": heading, "text": "\n".join(body).strip()})
    return {
        "tiers": tiers,
        "default_cost_tokens": int(match.group(1)) if match else None,
        "sections": sections,
    }


def rate_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Response headers whose name looks rate-limit related (whatever the API returns)."""
    return {k.lower(): v for k, v in headers.items() if RATE_HEADER_RE.search(k)}


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (pct in 0..100); None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(pct / 100 * len(ordered))))
    return ordered[rank - 1]


def describe(values: Iterable[float]) -> dict[str, float | int | None]:
    """Count, min, median, p95 (nearest rank) and max."""
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0] if ordered else None,
        "median": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "max": ordered[-1] if ordered else None,
    }


def step_metrics(rows: list[dict[str, Any]], target_rps: float) -> dict[str, Any]:
    """Achieved rate, latency distribution, and status counts for one ramp step.

    ``rows`` carry ``t_s`` (send time, seconds since job start), ``latency_ms`` and ``status``.
    Achieved rate is (n - 1) / (last send - first send).
    """
    sends = sorted(r["t_s"] for r in rows if r.get("t_s") is not None)
    span = sends[-1] - sends[0] if len(sends) >= 2 else 0.0
    latencies = [float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]
    statuses: dict[str, int] = {}
    for r in rows:
        key = str(r.get("status")) if r.get("status") is not None else "error"
        statuses[key] = statuses.get(key, 0) + 1
    return {
        "target_rps": target_rps,
        "requests": len(rows),
        "achieved_rps": round((len(sends) - 1) / span, 3) if span > 0 else None,
        "latency_median_ms": round(statistics.median(latencies), 2) if latencies else None,
        "latency_p95_ms": percentile(latencies, 95),
        "latency_max_ms": max(latencies) if latencies else None,
        "status_counts": statuses,
        "rate_limited": statuses.get("429", 0),
    }


def ramp_rates(start: float, step: float, maximum: float) -> list[float]:
    """start, start+step, ... up to and including maximum (rounded to 3 decimals)."""
    rates: list[float] = []
    current = start
    while current <= maximum + 1e-9:
        rates.append(round(current, 3))
        current += step
    return rates


def list_key(body: Any, preferred: Iterable[str] = ()) -> str | None:
    """Name of the list of records in a page: a preferred key if present, else the first list."""
    if not isinstance(body, dict):
        return None
    for key in preferred:
        if isinstance(body.get(key), list):
            return key
    return next((k for k, v in body.items() if isinstance(v, list)), None)


def identity(record: Any) -> tuple[str, str]:
    """(key used, value) identifying a record for duplicate detection across pages."""
    if isinstance(record, dict):
        for key in _IDENTITY_KEYS:
            value = record.get(key)
            if value not in (None, ""):
                return key, str(value)
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()
    return "json-hash", digest[:16]


def end_signal(body: Any) -> str | None:
    """How a page says there is no next page: None if a non-empty cursor was returned."""
    if not isinstance(body, dict):
        return "no JSON body"
    if "cursor" not in body:
        return "cursor field missing"
    value = body["cursor"]
    if value is None:
        return "cursor is null"
    if value == "":
        return "cursor is an empty string"
    return None
