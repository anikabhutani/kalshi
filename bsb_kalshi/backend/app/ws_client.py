"""Subscribe-only Kalshi WebSocket client (specs/asyncapi.yaml, specs/auth_notes.md).

Read-only enforcement:
1. The only command this module can encode is ``subscribe`` (``encode_outgoing``); anything
   else raises WsCommandBlocked before a byte is sent.
2. Only market-data channels in ``RECORDABLE_CHANNELS`` that also appear in the spec's
   ``subscribe`` channel enum are allowed, and a market ticker is always required.
3. The session is closed by dropping the connection; no unsubscribe/update commands exist here.

Authentication follows auth_notes "Quick Start: WebSockets": the handshake carries the three
KALSHI-ACCESS-* headers, with the signature over ``timestamp + "GET" + "/trade-api/ws/v2"``.
The handshake and every subscribe command are written to the evidence log (headers redacted).
"""

from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import certifi
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from app.errors import WsCommandBlocked
from app.evidence import EvidenceLog, RequestRecord

RECORDABLE_CHANNELS = ("ticker", "trade", "orderbook_delta")
ALLOWED_COMMANDS = frozenset({"subscribe"})
HANDSHAKE_TEMPLATE = "WS handshake"
SUBSCRIBE_TEMPLATE = "WS subscribe"
ACK_TIMEOUT_S = 10.0
OPEN_TIMEOUT_S = 15.0
MAX_MESSAGE_BYTES = 4 * 1024 * 1024

_TABLE_ROW_RE = re.compile(r"^\|\s*(Production|Demo)\s*\|(.+)\|\s*$", re.MULTILINE)
_URL_RE = re.compile(r"(?:https|wss)://\S+?(?=\s*(?:\||$))")


class WsConnection(Protocol):
    """The subset of a WebSocket connection the recorder uses."""

    async def send(self, message: str) -> None:
        """Send one text frame."""

    async def recv(self) -> str | bytes:
        """Receive one message."""

    async def close(self) -> None:
        """Close the connection."""


@dataclass(frozen=True)
class Handshake:
    """Outcome of one connection attempt."""

    connection: WsConnection | None
    status_code: int | None
    headers: dict[str, str]
    latency_ms: float
    error: str | None
    request_id: int


Connector = Callable[[str, dict[str, str]], Awaitable[tuple[WsConnection, int | None, dict[str, str]]]]


async def default_connector(
    url: str, headers: dict[str, str]
) -> tuple[WsConnection, int | None, dict[str, str]]:
    """Open a real connection; returns it with the handshake status and response headers.

    TLS uses certifi's CA bundle, the same trust store httpx uses for REST, because some
    Python builds (e.g. the python.org macOS installer) ship without system CA certificates.
    """
    tls = ssl.create_default_context(cafile=certifi.where()) if url.startswith("wss://") else None
    conn = await connect(
        url, additional_headers=headers, open_timeout=OPEN_TIMEOUT_S, max_size=MAX_MESSAGE_BYTES, ssl=tls
    )
    response = conn.response
    status = response.status_code if response is not None else None
    resp_headers = dict(response.headers.raw_items()) if response is not None else {}
    return conn, status, resp_headers


def _section(text: str, heading: str) -> str:
    start = text.find(f"### {heading}")
    if start < 0:
        return ""
    rest = text[start + len(heading) + 4 :]
    ends = [i for i in (rest.find("\n### "), rest.find("\n## "), rest.find("\n---")) if i >= 0]
    return rest[: min(ends)] if ends else rest


def _rows(section: str) -> dict[str, list[str]]:
    return {
        m.group(1): _URL_RE.findall(m.group(2))
        for m in _TABLE_ROW_RE.finditer(section)
    }


def ws_url_table(auth_notes: str) -> dict[str, str]:
    """REST host -> WebSocket URL, pairing the auth_notes REST and WebSocket tables by
    environment and column (recommended with recommended, also-supported with also-supported)."""
    rest = _rows(_section(auth_notes, "REST API"))
    ws = _rows(_section(auth_notes, "WebSocket API"))
    mapping: dict[str, str] = {}
    for env, rest_urls in rest.items():
        for index, url in enumerate(rest_urls):
            if index < len(ws.get(env, [])):
                mapping[urlparse(url).netloc] = ws[env][index]
    return mapping


def ws_url_for(base_url: str, table: Mapping[str, str]) -> str | None:
    """WebSocket URL for the configured REST base URL, or None if auth_notes has no pair."""
    return table.get(urlparse(base_url).netloc)


def subscribe_command(
    command_id: int,
    channels: Sequence[str],
    market_tickers: Sequence[str],
    spec_channels: Sequence[str],
) -> dict[str, Any]:
    """Build a ``subscribe`` command (asyncapi subscribeCommandPayload) after validation."""
    if not channels:
        raise WsCommandBlocked("No channel was selected.")
    not_in_spec = [c for c in channels if c not in spec_channels]
    if not_in_spec:
        raise WsCommandBlocked(f"Not in the spec's subscribe channel list: {', '.join(not_in_spec)}.")
    not_allowed = [c for c in channels if c not in RECORDABLE_CHANNELS]
    if not_allowed:
        raise WsCommandBlocked(f"Not a market-data channel this app records: {', '.join(not_allowed)}.")
    tickers = [t for t in market_tickers if t]
    if not tickers:
        raise WsCommandBlocked("A market ticker is required so only the chosen market is streamed.")
    params: dict[str, Any] = {"channels": list(channels)}
    if len(tickers) == 1:
        params["market_ticker"] = tickers[0]
    else:
        params["market_tickers"] = tickers
    return {"id": command_id, "cmd": "subscribe", "params": params}


def encode_outgoing(payload: Mapping[str, Any]) -> str:
    """Serialize an outgoing message, refusing anything but a market-data subscribe."""
    cmd = payload.get("cmd")
    if cmd not in ALLOWED_COMMANDS:
        raise WsCommandBlocked(f"Refused to send cmd={cmd!r}.")
    params = payload.get("params")
    channels = params.get("channels") if isinstance(params, Mapping) else None
    if not isinstance(channels, list) or not all(c in RECORDABLE_CHANNELS for c in channels):
        raise WsCommandBlocked(f"Refused channels {channels!r}.")
    return json.dumps(payload)


def _now_ms() -> float:
    return time.time() * 1000.0


class MarketDataSocket:
    """One WebSocket session: signed handshake, one subscribe, then receive-only."""

    def __init__(
        self,
        url: str,
        headers_factory: Callable[[str], dict[str, str]],
        evidence: EvidenceLog,
        job_id: str | None,
        module: str,
        connector: Connector = default_connector,
    ) -> None:
        self._url = url
        self._path = urlparse(url).path
        self._headers_factory = headers_factory
        self._evidence = evidence
        self._job_id = job_id
        self._module = module
        self._connector = connector
        self._conn: WsConnection | None = None
        self._next_id = 1

    @property
    def path(self) -> str:
        """URL path that is signed and logged (e.g. /trade-api/ws/v2)."""
        return self._path

    async def open(self) -> Handshake:
        """Connect with signed headers; logs one evidence row (HTTP 101 on success)."""
        headers = self._headers_factory(self._path)
        sent_at = datetime.now(UTC)
        started = time.perf_counter()
        conn: WsConnection | None = None
        status: int | None = None
        resp_headers: dict[str, str] = {}
        error: str | None = None
        try:
            conn, status, resp_headers = await self._connector(self._url, headers)
        except InvalidStatus as exc:
            status = exc.response.status_code
            resp_headers = dict(exc.response.headers.raw_items())
            error = f"Handshake rejected with HTTP {status}"
        except (OSError, TimeoutError) as exc:
            error = f"Connection failed: {type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - any handshake failure is recorded, not raised
            error = f"Handshake failed: {type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        request_id = self._evidence.record(
            RequestRecord(
                job_id=self._job_id,
                module=self._module,
                timestamp_utc=sent_at,
                method="GET",
                url=self._url,
                path=self._path,
                path_template=HANDSHAKE_TEMPLATE,
                params={},
                auth_used=True,
                status_code=status,
                latency_ms=latency_ms,
                response_headers=resp_headers,
                body=None,
                error=error,
            )
        )
        self._conn = conn
        return Handshake(conn, status, resp_headers, latency_ms, error, request_id)

    async def subscribe(
        self, channels: Sequence[str], market_tickers: Sequence[str], spec_channels: Sequence[str]
    ) -> tuple[list[dict[str, Any]], list[tuple[float, str]]]:
        """Send one subscribe and wait for its acknowledgements.

        Returns (acks, other messages received meanwhile). One ``subscribed`` (or ``error``)
        response per channel is expected; waiting stops after ACK_TIMEOUT_S. One evidence row
        is written with the acknowledgements as its body.
        """
        if self._conn is None:
            raise RuntimeError("subscribe() called before a successful open()")
        payload = subscribe_command(self._next_id, channels, market_tickers, spec_channels)
        command_id = self._next_id
        self._next_id += 1
        text = encode_outgoing(payload)
        sent_at = datetime.now(UTC)
        started = time.perf_counter()
        await self._conn.send(text)

        acks: list[dict[str, Any]] = []
        other: list[tuple[float, str]] = []
        deadline = time.monotonic() + ACK_TIMEOUT_S
        while len(acks) < len(channels):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(self._conn.recv(), timeout=remaining)
            except TimeoutError:
                break
            recv_ms = _now_ms()
            message = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            parsed = _loads(message)
            if parsed is not None and parsed.get("id") == command_id and parsed.get("type") in ("subscribed", "error"):
                acks.append(parsed)
            else:
                other.append((recv_ms, message))
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        errors = [a for a in acks if a.get("type") == "error"]
        error_text: str | None = None
        if errors:
            error_text = "; ".join(
                f"code {(e.get('msg') or {}).get('code')}: {(e.get('msg') or {}).get('msg')}" for e in errors
            )
        elif len(acks) < len(channels):
            error_text = f"{len(acks)} of {len(channels)} acknowledgements within {ACK_TIMEOUT_S:.0f}s"
        self._evidence.record(
            RequestRecord(
                job_id=self._job_id,
                module=self._module,
                timestamp_utc=sent_at,
                method="WS_SEND",
                url=self._url,
                path=self._path,
                path_template=SUBSCRIBE_TEMPLATE,
                params=payload,
                auth_used=True,
                status_code=None,
                latency_ms=latency_ms,
                response_headers={},
                body=json.dumps(acks).encode(),
                error=error_text,
            )
        )
        return acks, other

    async def receive(self, timeout_s: float) -> tuple[float, str] | None:
        """Next message as (local receive ms, text), or None on timeout."""
        if self._conn is None:
            raise RuntimeError("receive() called before a successful open()")
        try:
            raw = await asyncio.wait_for(self._conn.recv(), timeout=timeout_s)
        except TimeoutError:
            return None
        recv_ms = _now_ms()
        return recv_ms, raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw

    async def close(self) -> None:
        """Drop the connection (no commands are sent)."""
        if self._conn is not None:
            conn, self._conn = self._conn, None
            try:
                await conn.close()
            except Exception:  # noqa: BLE001 - closing a broken socket must not fail the job
                pass


def _loads(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
