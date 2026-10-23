"""M8 export builder: Markdown appendix and CSV tables from logged evidence and stored results.

Everything here is a pure transformation of stored data. The only prose in the output is fixed
template text (headings, column names, a provenance statement); every findings field is the
user's own note text, with an explicit placeholder where nothing has been written yet.
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Settings

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_CHART_BYTES = 8 * 1024 * 1024
MAX_CHARTS = 40
CHART_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
NOTE_PLACEHOLDER = "_[No notes written yet.]_"
NOT_CONFIRMED = "_[not confirmed by the user]_"
NO_DATA = "_No stored results for this module yet._"
PEM_MARKERS = ("-----BEGIN", "PRIVATE KEY-----")
_PEM_LINE_MIN = 24


class ExportError(ValueError):
    """Invalid export input or a detected secret; the message is safe to show the user."""


@dataclass(frozen=True)
class Table:
    """One exported table: written as ``csv/<name>.csv`` and rendered in the appendix."""

    name: str
    title: str
    columns: list[str]
    rows: list[list[Any]]
    source: str = ""


@dataclass(frozen=True)
class Chart:
    """A validated PNG chart image supplied by the frontend (Plotly image export)."""

    name: str
    png: bytes


@dataclass
class ExportData:
    """Everything the appendix needs. Contains no credentials."""

    generated_at: datetime
    openapi_title: str
    openapi_version: str
    asyncapi_version: str
    settings: Mapping[str, Any]
    questions: Sequence[Mapping[str, Any]]
    notes: Mapping[str, str]
    requests: Sequence[Mapping[str, Any]]
    jobs: Sequence[Mapping[str, Any]]
    ratings: Sequence[Mapping[str, Any]]
    spec_auth: Mapping[str, bool]
    rate_doc: Mapping[str, Any]
    latest: Mapping[str, Mapping[str, Any] | None] = field(default_factory=dict)
    ws_spec_rows: Sequence[Mapping[str, str]] = field(default_factory=list)


def decode_charts(items: Iterable[Mapping[str, str]]) -> list[Chart]:
    """Validate chart names and PNG payloads (base64, magic bytes, size)."""
    charts: list[Chart] = []
    seen: set[str] = set()
    for item in items:
        name = item.get("name", "")
        if not CHART_NAME_RE.match(name) or name in seen:
            raise ExportError(f"Invalid or duplicate chart name: {name[:64]!r}.")
        payload = item.get("png_base64", "")
        if payload.startswith("data:image/png;base64,"):
            payload = payload.removeprefix("data:image/png;base64,")
        try:
            png = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise ExportError(f"Chart {name} is not valid base64.") from None
        if not png.startswith(PNG_MAGIC):
            raise ExportError(f"Chart {name} is not a PNG image.")
        if len(png) > MAX_CHART_BYTES:
            raise ExportError(f"Chart {name} is larger than {MAX_CHART_BYTES // (1024 * 1024)} MB.")
        seen.add(name)
        charts.append(Chart(name, png))
    if len(charts) > MAX_CHARTS:
        raise ExportError(f"At most {MAX_CHARTS} charts can be exported at once.")
    return charts


def pem_fragments(private_key_text: str | None) -> list[str]:
    """Body lines of a PEM key, used only to check that no key material reached the export."""
    if not private_key_text:
        return []
    return [
        line.strip()
        for line in private_key_text.splitlines()
        if len(line.strip()) >= _PEM_LINE_MIN and not line.startswith("-----")
    ]


def secret_values(config: Settings) -> list[str]:
    """The key id and private-key body lines: what a written file must never contain."""
    key_id = config.kalshi_key_id
    values = [key_id.get_secret_value()] if key_id is not None else []
    return values + pem_fragments(config.private_key_text())


def find_leaks(files: Mapping[str, str], secrets: Iterable[str]) -> list[str]:
    """File names (never the secret itself) containing a secret value or PEM marker."""
    secret_values = [s for s in secrets if s]
    hits: list[str] = []
    for name, text in files.items():
        if any(s in text for s in secret_values) or any(m in text for m in PEM_MARKERS):
            hits.append(name)
    return hits


def md_cell(value: Any) -> str:
    """Render a value for a Markdown table cell (pipes escaped, newlines flattened)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    elif isinstance(value, dict | list):
        text = json.dumps(value, separators=(",", ":"), default=str)
    else:
        text = str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def md_table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """A GitHub-flavored Markdown table."""
    lines = [
        "| " + " | ".join(md_cell(c) for c in columns) + " |",
        "|" + "|".join(" --- " for _ in columns) + "|",
    ]
    lines += ["| " + " | ".join(md_cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def csv_text(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """CSV with a header row; dicts/lists are JSON-encoded."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(
            [
                json.dumps(v, separators=(",", ":"), default=str) if isinstance(v, dict | list) else v
                for v in row
            ]
        )
    return buffer.getvalue()


def _result(data: ExportData, key: str) -> tuple[dict[str, Any] | None, str]:
    job = data.latest.get(key)
    if not job or not isinstance(job.get("result"), dict):
        return None, ""
    partial = " (partial result)" if job["result"].get("partial") else ""
    return job["result"], f"Job {job.get('id')}, finished {job.get('finished_at') or '-'}{partial}"


def requests_table(data: ExportData) -> Table:
    """Every logged request."""
    cols = ["id", "timestamp_utc", "module", "job_id", "method", "endpoint", "url", "auth_used", "status_code", "latency_ms", "response_bytes", "error"]
    rows = [
        [r.get("id"), r.get("timestamp_utc"), r.get("module"), r.get("job_id"), r.get("method"), r.get("path_template"), r.get("url"), r.get("auth_used"), r.get("status_code"), r.get("latency_ms"), r.get("response_bytes"), r.get("error")]
        for r in data.requests
    ]
    return Table("requests", "Every request", cols, rows)


def jobs_table(data: ExportData) -> Table:
    """Every job run."""
    cols = ["id", "module", "kind", "status", "started_at", "finished_at", "request_count", "max_requests", "error_reason", "params"]
    rows = [
        [j.get("id"), j.get("module"), j.get("kind"), j.get("status"), j.get("started_at"), j.get("finished_at"), j.get("request_count"), j.get("max_requests"), j.get("error_reason"), j.get("params")]
        for j in data.jobs
    ]
    return Table("jobs", "Jobs", cols, rows)


def auth_matrix_table(data: ExportData) -> Table:
    """M1 auth probe: per endpoint, status without and with the key, and the spec's auth flag."""
    result, source = _result(data, "m1_auth_probe")
    cols = ["endpoint", "spec_requires_auth", "concrete_path", "status_no_key", "status_with_key", "classification", "mismatch_vs_spec", "note"]
    rows: list[list[Any]] = []
    for r in (result or {}).get("results", []):
        auth = r.get("auth") or {}
        rows.append([r.get("endpoint_id"), data.spec_auth.get(r.get("endpoint_id", "")), r.get("concrete_path"), (r.get("no_auth") or {}).get("status"), auth.get("status"), r.get("classification"), r.get("mismatch"), r.get("note")])
    for s in (result or {}).get("skipped", []):
        rows.append([s.get("endpoint_id"), data.spec_auth.get(s.get("endpoint_id", "")), None, None, None, s.get("classification"), None, s.get("note")])
    return Table("auth_matrix", "Auth matrix (M1)", cols, rows, source)


def ratings_table(data: ExportData) -> Table:
    """User-typed endpoint usefulness ratings."""
    cols = ["endpoint", "rating_1_to_5", "reason (user-typed)", "updated_at"]
    rows = [[r.get("endpoint_id"), r.get("rating"), r.get("reason"), r.get("updated_at")] for r in data.ratings]
    return Table("endpoint_ratings", "Endpoint ratings (user-typed, M1)", cols, rows)


def notes_table(data: ExportData) -> Table:
    """User notes per research question (empty where nothing was written)."""
    cols = ["question", "title", "notes (user-typed)"]
    rows = [[q["id"], q["title"], data.notes.get(q["id"], "")] for q in data.questions]
    return Table("notes", "Notes per question", cols, rows)


def m2_fields_table(data: ExportData) -> Table:
    """M2 observed field dictionary per entity, annotated with spec presence."""
    result, source = _result(data, "m2_pull_game")
    cols = ["entity", "path", "types", "present_in", "samples", "null_count", "timestamp_format", "in_spec", "spec_type", "spec_format", "example"]
    rows: list[list[Any]] = []
    for entity, block in ((result or {}).get("entities") or {}).items():
        for f in block.get("fields", []):
            rows.append([entity, f.get("path"), f.get("types"), f.get("present_in"), f.get("samples"), f.get("null_count"), f.get("timestamp_format"), f.get("in_spec"), f.get("spec_type"), f.get("spec_format"), f.get("example")])
    return Table("m2_fields", "Observed fields (M2)", cols, rows, source)


def m3_sources_table(data: ExportData) -> Table:
    """M3 per-source coverage metrics."""
    result, source = _result(data, "m3_price_sources")
    cols = ["source", "kind", "endpoint", "records", "first_ts", "last_ts", "covered_s", "finest_granularity_s", "median_delta_s", "max_delta_s", "empty_or_missing_slots", "timestamp_field"]
    rows: list[list[Any]] = []
    for key, src in ((result or {}).get("sources") or {}).items():
        m = src.get("metrics") or {}
        gaps = m.get("missing_periods") or m.get("empty_buckets") or {}
        endpoint = src.get("endpoint") or ", ".join(src.get("endpoints") or [])
        if src.get("kind") == "orderbook":
            rows.append([key, "orderbook", endpoint, (src.get("yes_levels") or 0) + (src.get("no_levels") or 0), None, None, None, None, None, None, None, "none (local receive time)"])
            continue
        rows.append([key, src.get("kind"), endpoint, m.get("records"), m.get("first_ts"), m.get("last_ts"), m.get("covered_s"), m.get("finest_granularity_s"), m.get("median_delta_s"), m.get("max_delta_s"), gaps.get("empty_slots") if isinstance(gaps, dict) else None, m.get("timestamp_field")])
    return Table("m3_source_metrics", "Timestamp sources (M3)", cols, rows, source)


def m4_depth_table(data: ExportData) -> Table:
    """M4 oldest/newest record found per endpoint."""
    result, source = _result(data, "m4_depth_archive")
    cols = ["target", "endpoint", "mode", "timestamp_field", "filters", "oldest_utc", "newest_utc", "bracket_lo", "bracket_hi", "requests", "stop_reason"]
    rows: list[list[Any]] = []
    for t in (result or {}).get("targets", []):
        probes = len(t.get("probes") or t.get("pages") or [])
        rows.append([t.get("label"), t.get("path"), t.get("mode"), t.get("ts_field"), t.get("filters_applied"), t.get("oldest_utc"), t.get("newest_utc"), t.get("bracket_lo"), t.get("bracket_hi"), probes, t.get("stop_reason")])
    return Table("m4_depth", "Depth per endpoint (M4)", cols, rows, source)


def m4_cutoff_table(data: ExportData) -> Table:
    """M4 historical cutoff values as returned by GET /historical/cutoff."""
    result, source = _result(data, "m4_depth_archive")
    cols = ["field", "raw", "utc"]
    rows = [[k, v.get("raw"), v.get("utc")] for k, v in ((result or {}).get("cutoff") or {}).items()]
    return Table("m4_cutoff", "Historical cutoff (M4)", cols, rows, source)


def m4_matrix_table(data: ExportData) -> Table:
    """M4 archive matrix: per sample market and endpoint, HTTP status and record count."""
    result, source = _result(data, "m4_depth_archive")
    cols = ["sample", "ticker", "market_status", "settlement_ts", "cutoff_side", "check", "endpoint", "http_status", "records", "note"]
    rows: list[list[Any]] = []
    for s in (((result or {}).get("matrix") or {}).get("samples") or []):
        for c in s.get("cells", []):
            rows.append([s.get("label"), s.get("ticker"), s.get("status"), s.get("settlement_ts"), s.get("cutoff_side"), c.get("check"), c.get("endpoint"), c.get("status"), c.get("records"), c.get("note")])
    return Table("m4_archive_matrix", "Archive matrix (M4)", cols, rows, source)


def m5_doc_table(data: ExportData) -> Table:
    """Tier budgets parsed from specs/rate_limits.md."""
    cols = ["tier", "read_budget_tokens_per_s", "write_budget_tokens_per_s"]
    rows = [[t.get("tier"), t.get("read_budget"), t.get("write_budget")] for t in data.rate_doc.get("tiers", [])]
    return Table("m5_documented_tiers", "Documented tiers (specs/rate_limits.md)", cols, rows, "specs/rate_limits.md")


def m5_account_table(data: ExportData) -> Table:
    """GET /account/limits and /account/endpoint_costs responses as returned."""
    result, source = _result(data, "m5_account_limits")
    cols = ["endpoint", "http_status", "field", "value"]
    rows: list[list[Any]] = []
    for call in (result or {}).get("calls", []):
        key = "limits" if call.get("path") == "/account/limits" else "endpoint_costs"
        body = (result or {}).get(key)
        if isinstance(body, dict) and body:
            rows += [[call.get("path"), call.get("status"), k, v] for k, v in body.items()]
        else:
            rows.append([call.get("path"), call.get("status"), None, call.get("note") or call.get("error")])
    return Table("m5_account_limits", "Account limits as returned by the API (M5)", cols, rows, source)


def m5_ramp_steps_table(data: ExportData) -> Table:
    """Ramp test per-step metrics."""
    result, source = _result(data, "m5_ramp")
    cols = ["target_rps", "requests", "achieved_rps", "latency_median_ms", "latency_p95_ms", "latency_max_ms", "status_counts", "rate_limited"]
    rows = [[s.get(c) for c in cols] for s in (result or {}).get("steps", [])]
    if result and result.get("first_429"):
        source += f"; first 429: {json.dumps(result['first_429'], default=str)}"
    return Table("m5_ramp_steps", "Ramp test steps (M5)", cols, rows, source)


def m5_ramp_requests_table(data: ExportData) -> Table:
    """Ramp test per-request rows (CSV only; also summarized per step)."""
    result, source = _result(data, "m5_ramp")
    cols = ["step", "target_rps", "index", "t_s", "latency_ms", "status", "rate_headers", "request_id"]
    rows = [[r.get(c) for c in cols] for r in (result or {}).get("requests", [])]
    return Table("m5_ramp_requests", "Ramp test requests (M5)", cols, rows, source)


def m5_pagination_table(data: ExportData) -> Table:
    """Pagination analyzer: boundary page sizes, then the cursor walk."""
    result, source = _result(data, "m5_pagination")
    cols = ["part", "case_or_page", "size_sent", "http_status", "items", "duplicates", "cursor_returned_or_length", "end_signal"]
    rows: list[list[Any]] = []
    for b in (result or {}).get("boundary", []):
        rows.append(["boundary", b.get("case"), b.get("size_sent"), b.get("status"), b.get("items"), None, b.get("cursor_returned"), None])
    for p in (result or {}).get("pages", []):
        rows.append(["walk", p.get("page"), (result or {}).get("walk_size"), p.get("status"), p.get("items"), p.get("duplicates_of_earlier_pages"), p.get("cursor_length"), p.get("end_signal")])
    if result:
        source += f"; endpoint GET {(result.get('spec') or {}).get('path')}"
    return Table("m5_pagination", "Pagination analyzer (M5)", cols, rows, source)


def m6_spec_table(data: ExportData) -> Table:
    """REST vs WebSocket comparison filled only from the spec files."""
    cols = ["aspect", "rest", "rest_source", "websocket", "websocket_source"]
    rows = [[r.get("aspect"), r.get("rest"), r.get("rest_source"), r.get("websocket"), r.get("ws_source")] for r in data.ws_spec_rows]
    return Table("m6_spec_comparison", "REST vs WebSocket per the specs (M6)", cols, rows, "specs/*.yaml, specs/*.md")


def m6_summary_table(data: ExportData) -> Table:
    """M6 recorder metrics as metric/value rows."""
    result, source = _result(data, "m6_recorder")
    cols = ["metric", "value"]
    if not result:
        return Table("m6_recorder_metrics", "REST vs WebSocket recorder (M6)", cols, [], source)
    ws, rest, cmp, trades = result.get("ws") or {}, result.get("rest") or {}, result.get("comparison") or {}, result.get("trades") or {}
    p = result.get("params") or {}
    rows: list[list[Any]] = [
        ["market_ticker", p.get("market_ticker")],
        ["channels", p.get("channels")],
        ["poll_interval_s", p.get("poll_interval_s")],
        ["planned_duration_s", result.get("planned_duration_s")],
        ["recorded_s", result.get("recorded_s")],
        ["stopped_reason", result.get("stopped_reason")],
        ["ws_url", result.get("ws_url")],
        ["ws_connections", len(result.get("connections") or [])],
        ["ws_reconnects", result.get("reconnects")],
        ["ws_disconnects", len(result.get("disconnects") or [])],
        ["ws_error_messages", len(ws.get("errors") or [])],
        ["ws_messages", ws.get("messages")],
        ["ws_message_counts", ws.get("message_counts")],
        ["ws_ticker_price_changes", ws.get("price_changes")],
        ["rest_polls", rest.get("polls")],
        ["rest_ok_polls", rest.get("ok_polls")],
        ["rest_price_changes", rest.get("price_changes")],
        ["rest_latency_ms", rest.get("latency_ms")],
        ["rest_clock_offset_median_s", rest.get("clock_offset_median_s")],
        ["poll_intervals", cmp.get("intervals")],
        ["ws_changes_between_polls", cmp.get("ws_changes_between_polls")],
        ["rest_changes_detected", cmp.get("rest_changes")],
        ["rest_missed_changes", cmp.get("rest_missed_changes")],
        ["intervals_ws_changed_rest_unchanged", cmp.get("intervals_ws_changed_rest_unchanged")],
        ["intervals_rest_changed_ws_unchanged", cmp.get("intervals_rest_changed_ws_unchanged")],
        ["intervals_multiple_ws_changes", cmp.get("intervals_multiple_ws_changes")],
        ["trades_ws", trades.get("ws_trades")],
        ["trades_rest", trades.get("rest_trades")],
        ["trades_matched", trades.get("matched")],
        ["trades_ws_only", trades.get("ws_only")],
        ["trades_rest_only", trades.get("rest_only")],
        ["trades_rest_delay_after_ws_ms", trades.get("rest_delay_after_ws_ms")],
    ]
    for kind, lat in (ws.get("latency") or {}).items():
        rows.append([f"latency_{kind}_recv_minus_ts_ms", lat.get("recv_minus_ts_ms")])
        rows.append([f"latency_{kind}_recv_minus_sending_ts_ms", lat.get("recv_minus_sending_ts_ms")])
    for s in ws.get("sequence") or []:
        rows.append([f"sequence_sid_{s.get('sid')}", {k: s.get(k) for k in ("types", "messages", "missing", "out_of_order")}])
    return Table("m6_recorder_metrics", "REST vs WebSocket recorder (M6)", cols, rows, source)


def m6_intervals_table(data: ExportData) -> Table:
    """M6 per poll interval: WS changes inside it, REST change, misses (CSV only)."""
    result, source = _result(data, "m6_recorder")
    cols = ["start_ms", "end_ms", "ws_changes", "rest_changed", "missed"]
    rows = [[i.get(c) for c in cols] for i in ((result or {}).get("comparison") or {}).get("per_interval", [])]
    return Table("m6_poll_intervals", "REST poll intervals (M6)", cols, rows, source)


def build_tables(data: ExportData) -> list[Table]:
    """All exported tables, in appendix order."""
    return [
        notes_table(data),
        auth_matrix_table(data),
        ratings_table(data),
        m2_fields_table(data),
        m3_sources_table(data),
        m4_cutoff_table(data),
        m4_depth_table(data),
        m4_matrix_table(data),
        m5_doc_table(data),
        m5_account_table(data),
        m5_ramp_steps_table(data),
        m5_ramp_requests_table(data),
        m5_pagination_table(data),
        m6_spec_table(data),
        m6_summary_table(data),
        m6_intervals_table(data),
        jobs_table(data),
        requests_table(data),
    ]


_APPENDIX_SECTIONS: list[tuple[str, list[str]]] = [
    ("Authentication and endpoints (M1)", ["auth_matrix", "endpoint_ratings"]),
    ("Data organization (M2)", ["m2_fields"]),
    ("Timestamps (M3)", ["m3_source_metrics"]),
    ("Depth and archive (M4)", ["m4_cutoff", "m4_depth", "m4_archive_matrix"]),
    ("Limits (M5)", ["m5_documented_tiers", "m5_account_limits", "m5_ramp_steps", "m5_pagination"]),
    ("REST vs WebSocket (M6)", ["m6_spec_comparison", "m6_recorder_metrics"]),
]


def _section(table: Table) -> list[str]:
    lines = [f"### {table.title}", ""]
    if table.source:
        lines += [f"Source: {md_cell(table.source)}", ""]
    lines.append(md_table(table.columns, table.rows) if table.rows else NO_DATA)
    return lines + [""]


def build_appendix(data: ExportData, tables: Sequence[Table], files: Sequence[str]) -> str:
    """The Markdown appendix: header, user notes Q1-Q6, auth matrix, metrics, jobs, requests."""
    by_name = {t.name: t for t in tables}
    s = data.settings
    by_module: dict[str, int] = {}
    for r in data.requests:
        by_module[str(r.get("module"))] = by_module.get(str(r.get("module")), 0) + 1
    header = [
        ["Generated (UTC)", data.generated_at.isoformat(timespec="seconds")],
        ["Date checked (user-confirmed)", s.get("date_checked") or NOT_CONFIRMED],
        ["API version in specs/openapi.yaml (info.version)", data.openapi_version],
        ["API version confirmed by the user", s.get("api_version") or NOT_CONFIRMED],
        ["OpenAPI title", data.openapi_title],
        ["AsyncAPI version (specs/asyncapi.yaml)", data.asyncapi_version],
        ["Base URL", s.get("base_url")],
        ["Client rate limit", f"{s.get('rate_limit_rps')} req/s, burst {s.get('rate_limit_burst')}"],
        ["Requests logged", f"{len(data.requests)} ({', '.join(f'{m}: {n}' for m, n in sorted(by_module.items())) or 'none'})"],
        ["Jobs run", len(data.jobs)],
    ]
    lines = [
        "# Kalshi Predictions API: evidence appendix",
        "",
        md_table(["Item", "Value"], header),
        "",
        "This appendix was assembled by the Kalshi Recon tool from its request log and stored job "
        "results. Tables contain logged requests and computed metrics only. All findings text was "
        "typed by the user; empty placeholders mark questions without notes.",
        "",
        "## Research questions and notes",
        "",
    ]
    for q in data.questions:
        text = data.notes.get(q["id"], "").strip()
        lines += [f"### {q['id']}. {q['title']}", "", f"Question: {q['prompt']}", "", text or NOTE_PLACEHOLDER, ""]
    for title, names in _APPENDIX_SECTIONS:
        lines += [f"## {title}", ""]
        for name in names:
            lines += _section(by_name[name])
    lines += ["## Jobs", ""] + _section(by_name["jobs"])[2:]
    requests = by_name["requests"]
    md_cols = ["id", "timestamp_utc", "module", "job_id", "method", "endpoint", "auth_used", "status_code", "latency_ms"]
    idx = [requests.columns.index(c) for c in md_cols]
    lines += [
        "## Every request",
        "",
        "Full URLs, response sizes, and errors are in csv/requests.csv.",
        "",
        md_table(md_cols, [[row[i] for i in idx] for row in requests.rows]) if requests.rows else NO_DATA,
        "",
        "## Files in this export",
        "",
    ]
    lines += [f"- `{name}`" for name in files]
    return "\n".join(lines) + "\n"
