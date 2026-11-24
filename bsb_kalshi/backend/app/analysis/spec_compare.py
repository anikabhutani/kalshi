"""M6 spec comparison: REST vs WebSocket, filled only with text taken from the spec files.

Every cell is either quoted (or listed) from specs/openapi.yaml, specs/asyncapi.yaml,
specs/auth_notes.md or specs/rate_limits.md, or the literal ``NOT_STATED`` marker. Nothing is
paraphrased or judged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.spec_loader import AsyncApiSpec, OpenApiSpec

NOT_STATED = "Not stated in the specs."
REST_PATHS = ("/markets/{ticker}", "/markets/trades", "/markets/{ticker}/orderbook")
WS_CHANNELS = ("ticker", "trade", "orderbook_delta")


def _row(aspect: str, rest: str, rest_source: str, ws: str, ws_source: str) -> dict[str, str]:
    return {"aspect": aspect, "rest": rest, "rest_source": rest_source, "websocket": ws, "ws_source": ws_source}


def _lines_starting(text: str, prefix: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith(prefix)]


def _sentence_with(text: str, needle: str) -> str | None:
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return None


def _first_paragraph(text: str) -> str:
    return " ".join(text.strip().split("\n\n", 1)[0].split())


def _section(sections: Sequence[Mapping[str, str]], heading: str) -> str | None:
    return next((s["text"] for s in sections if s["heading"] == heading), None)


def comparison_rows(
    spec: OpenApiSpec,
    asyncspec: AsyncApiSpec,
    auth_notes: str,
    rate_sections: Sequence[Mapping[str, str]],
    base_url: str,
    ws_url: str | None,
) -> list[dict[str, str]]:
    """Rows of (aspect, REST cell, REST source, WebSocket cell, WebSocket source)."""
    rows: list[dict[str, str]] = []
    rows.append(
        _row(
            "Server URLs",
            f"{', '.join(spec.server_urls)} (configured: {base_url})",
            "openapi.yaml servers; Settings",
            f"{', '.join(s['url'] for s in asyncspec.servers)} (paired with the configured REST host: "
            f"{ws_url or 'no pair found in auth_notes.md'})",
            "asyncapi.yaml servers; auth_notes.md REST/WebSocket tables",
        )
    )

    auth_rest = "; ".join(
        f"GET {p}: {'security requirement declared' if (e := spec.find('GET', p)) and e.auth_required else 'no security requirement declared'}"
        for p in REST_PATHS
    )
    root = asyncspec.channel("root")
    auth_ws = " ".join(
        t
        for t in (
            _sentence_with(root.description, "Authentication is required") if root else None,
            asyncspec.security_description(),
        )
        if t
    )
    rows.append(_row("Authentication", auth_rest, "openapi.yaml operation security", auth_ws or NOT_STATED, "asyncapi.yaml channels.root, securitySchemes"))

    channel_groups = _lines_starting(auth_notes, "- Private channels") + _lines_starting(auth_notes, "- Public market-data channels")
    rows.append(
        _row(
            "Channels / endpoints",
            "; ".join(f"GET {p}: {e.summary}" for p in REST_PATHS if (e := spec.find("GET", p))),
            "openapi.yaml operation summaries",
            f"subscribe accepts: {', '.join(asyncspec.subscribe_channels())}. " + " ".join(channel_groups),
            "asyncapi.yaml subscribeCommandPayload; auth_notes.md Quick Start: WebSockets",
        )
    )

    delivery_ws = []
    for name in WS_CHANNELS:
        ch = asyncspec.channel(name)
        if ch is None:
            continue
        lines = _lines_starting(ch.description, "- Updates sent") + _lines_starting(ch.description, "- Sends ")
        delivery_ws.append(f"{name}: {' '.join(l.lstrip('- ') for l in lines) or ch.title}")
    trades = spec.find("GET", "/markets/trades")
    cursor = trades.param("cursor") if trades else None
    rows.append(
        _row(
            "Delivery",
            f"GET /markets/trades cursor: {cursor.description}" if cursor and cursor.description else NOT_STATED,
            "openapi.yaml parameters",
            "; ".join(delivery_ws) or NOT_STATED,
            "asyncapi.yaml channel descriptions",
        )
    )

    market_props = spec.response_object_properties("/markets/{ticker}", "market")
    trade_props = spec.response_object_properties("/markets/trades", "trades")
    rest_ts = [
        f"market.{name}: {market_props[name].description or '(no description)'}"
        for name in ("updated_time",)
        if name in market_props
    ] + [
        f"trades[].{name}: {trade_props[name].description or '(no description)'} (format {trade_props[name].format})"
        for name in ("created_time",)
        if name in trade_props
    ]
    ws_ts = [
        f"{label}: {desc}"
        for label, desc in (
            ("ticker msg.ts_ms", asyncspec.field_description("tickerPayload", "msg", "ts_ms")),
            ("trade msg.ts_ms", asyncspec.field_description("tradePayload", "msg", "ts_ms")),
            ("sending_ts_ms", asyncspec.field_description("tickerPayload", "sending_ts_ms")),
        )
        if desc
    ]
    rows.append(
        _row(
            "Timestamp fields",
            "; ".join(rest_ts) or NOT_STATED,
            "openapi.yaml response schemas",
            "; ".join(ws_ts) or NOT_STATED,
            "asyncapi.yaml payload schemas",
        )
    )

    seq = asyncspec.field_description("tradePayload", "seq")
    rows.append(_row("Sequence / completeness", NOT_STATED, "-", seq or NOT_STATED, "asyncapi.yaml sequenceNumber"))

    keepalive = asyncspec.channel("control_frames")
    rows.append(
        _row(
            "Keep-alive",
            NOT_STATED,
            "-",
            _first_paragraph(keepalive.description.split("\n", 1)[-1]) if keepalive else NOT_STATED,
            "asyncapi.yaml channels.control_frames",
        )
    )

    token = _section(rate_sections, "Token-based limits")
    buckets = _section(rate_sections, "Read and Write buckets")
    rest_limits = " ".join(
        t for t in (_first_paragraph(token) if token else None, _sentence_with(buckets or "", "REST and FIX")) if t
    )
    ws_codes = [c for c in asyncspec.error_codes() if c["code"] in (26, 27)]
    ws_limits = "specs/rate_limits.md does not mention WebSocket. " + " ".join(
        f"Error {c['code']} {c['name']}: {c['description']}." for c in ws_codes
    )
    rows.append(
        _row(
            "Rate limits",
            rest_limits or NOT_STATED,
            "rate_limits.md",
            ws_limits,
            "rate_limits.md; asyncapi.yaml x-error-codes",
        )
    )
    return rows


def spec_summary(asyncspec: AsyncApiSpec) -> dict[str, Any]:
    """Channel list and error codes for display next to the table."""
    return {
        "asyncapi_version": asyncspec.version,
        "channels": [
            {"name": c.name, "title": c.title, "messages": c.message_names}
            for c in asyncspec.channels
            if c.name not in ("root", "control_frames")
        ],
        "error_codes": asyncspec.error_codes(),
    }
