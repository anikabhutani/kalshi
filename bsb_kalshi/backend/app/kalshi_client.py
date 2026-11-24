"""The single choke point for every Kalshi REST request.

``KalshiClient.call`` enforces, in order:
1. GET-only (anything else raises ReadOnlyViolation; an httpx request hook double-checks).
2. The path must match a GET operation in specs/openapi.yaml (SpecViolation otherwise).
3. Job cancellation and the job's hard request cap.
4. Serialization (one request in flight at a time) and the global token bucket.
5. Signing per specs/auth_notes.md when ``auth=True``.
6. Retries only for network errors / 5xx; never for 4xx. The first 429 raises RateLimited.
7. Every attempt is written to the evidence log with secrets redacted.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import textwrap
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.config import Settings
from app.errors import (
    AuthNotConfigured,
    JobCancelled,
    RateLimited,
    ReadOnlyViolation,
    SpecViolation,
)
from app.evidence import EvidenceLog, RequestRecord, redact_headers
from app.jobs import JobManager
from app.settings_store import SettingsStore
from app.spec_loader import OpenApiSpec

SigningKey = RSAPrivateKey | Ed25519PrivateKey

_MAX_429_COOLDOWN_S = 60.0
_MAX_RETRY_AFTER_S = 300.0


_PEM_BLOCK_RE = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----(.*?)-----END \1-----", re.DOTALL)
_HEADERLESS_LABELS = ("RSA PRIVATE KEY", "PRIVATE KEY")


def pem_candidates(raw: str) -> list[bytes]:
    """Normalize pasted key text into well-formed PEM candidates.

    Accepts a normal multi-line PEM, a PEM collapsed onto one line (spaces instead of
    newlines), literal ``\\n`` escapes, surrounding quotes, or just the base64 body without
    BEGIN/END lines (then both PKCS#1 and PKCS#8 labels are tried).
    """
    text = raw.strip().strip("\"'").replace("\\n", "\n")
    match = _PEM_BLOCK_RE.search(text)
    if match is not None:
        labels: tuple[str, ...] = (match.group(1),)
        body = match.group(2)
    else:
        labels, body = _HEADERLESS_LABELS, text
    b64 = "".join(body.split())
    wrapped = "\n".join(textwrap.wrap(b64, 64))
    return [f"-----BEGIN {lb}-----\n{wrapped}\n-----END {lb}-----\n".encode() for lb in labels]


def load_private_key(raw: str) -> SigningKey:
    """Load an unencrypted private key (RSA or Ed25519) from pasted or file PEM text."""
    for candidate in pem_candidates(raw):
        try:
            key = serialization.load_pem_private_key(candidate, password=None)
        except (ValueError, TypeError):
            continue
        if not isinstance(key, RSAPrivateKey | Ed25519PrivateKey):
            raise ValueError("Unsupported private key type; expected RSA or Ed25519.")
        return key
    raise ValueError("Could not parse the private key text as PEM.")


def signing_path(base_url: str, path: str) -> str:
    """Full URL path from the API root, without host or query (auth_notes: Request Signing)."""
    return urlparse(base_url.rstrip("/") + path).path


def build_sign_message(timestamp_ms: str, method: str, path: str) -> bytes:
    """Pre-sign text: timestamp + METHOD + path-without-query, UTF-8 encoded."""
    return f"{timestamp_ms}{method}{path.split('?')[0]}".encode()


def sign_message(private_key: SigningKey, message: bytes) -> str:
    """Base64 signature: RSA-PSS/SHA-256 (salt = digest length) for RSA, raw for Ed25519."""
    if isinstance(private_key, Ed25519PrivateKey):
        signature = private_key.sign(message)
    else:
        signature = private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    return base64.b64encode(signature).decode("utf-8")


def auth_headers(key_id: str, private_key: SigningKey, method: str, path: str) -> dict[str, str]:
    """The three KALSHI-ACCESS-* headers for one request."""
    timestamp_ms = str(int(time.time() * 1000))
    signature = sign_message(private_key, build_sign_message(timestamp_ms, method, path))
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
    }


async def _reject_non_get(request: httpx.Request) -> None:
    """httpx request hook: defense in depth for the read-only guarantee."""
    if request.method != "GET":
        raise ReadOnlyViolation(request.method, request.url.path)


class TokenBucket:
    """Client-side token bucket: ``rate`` tokens/s refill, up to ``capacity``. 1 token/request."""

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._updated = time.monotonic()
        self._cooldown_until = 0.0
        self._recent: deque[float] = deque()

    def configure(self, rate: float, capacity: int) -> None:
        """Change rate/capacity; current tokens are clamped to the new capacity."""
        self._refill()
        self._rate = rate
        self._capacity = float(capacity)
        self._tokens = min(self._tokens, self._capacity)

    def cooldown(self, seconds: float) -> None:
        """Block all acquisitions for ``seconds`` (used after a 429)."""
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    async def acquire(self) -> None:
        """Wait until a token is available (and any cooldown has passed), then take it."""
        while True:
            now = time.monotonic()
            if now < self._cooldown_until:
                await asyncio.sleep(self._cooldown_until - now)
                continue
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._recent.append(time.monotonic())
                return
            await asyncio.sleep((1.0 - self._tokens) / self._rate)

    def snapshot(self) -> dict[str, float]:
        """Current state for the UI rate meter."""
        self._refill()
        now = time.monotonic()
        while self._recent and now - self._recent[0] > 60.0:
            self._recent.popleft()
        return {
            "tokens": round(self._tokens, 3),
            "capacity": self._capacity,
            "rate_per_s": self._rate,
            "cooldown_remaining_s": round(max(0.0, self._cooldown_until - now), 2),
            "requests_last_60s": float(len(self._recent)),
        }

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
        self._updated = now


@dataclass(frozen=True)
class CallResult:
    """Outcome of one request attempt as seen by callers. Headers are redacted."""

    request_id: int
    url: str
    path_template: str
    status_code: int | None
    headers: dict[str, str]
    body: bytes | None
    latency_ms: float
    sent_at: datetime
    received_at: datetime
    error: str | None

    @property
    def ok(self) -> bool:
        """True for HTTP 2xx."""
        return self.status_code is not None and 200 <= self.status_code < 300

    def json(self) -> Any:
        """Parsed JSON body, or None if absent/invalid."""
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except ValueError:
            return None

    @property
    def server_date(self) -> datetime | None:
        """Server time from the ``Date`` response header (1-second resolution)."""
        raw = next((v for k, v in self.headers.items() if k.lower() == "date"), None)
        if raw is None:
            return None
        try:
            return parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None

    @property
    def clock_offset_s(self) -> float | None:
        """Server Date minus the local midpoint between send and receive, in seconds."""
        server = self.server_date
        if server is None:
            return None
        midpoint = self.sent_at + (self.received_at - self.sent_at) / 2
        return (server - midpoint).total_seconds()


class KalshiClient:
    """Read-only, rate-limited, evidence-logging Kalshi REST client."""

    def __init__(
        self,
        config: Settings,
        spec: OpenApiSpec,
        settings: SettingsStore,
        evidence: EvidenceLog,
        jobs: JobManager,
        bucket: TokenBucket,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._spec = spec
        self._settings = settings
        self._evidence = evidence
        self._jobs = jobs
        self._bucket = bucket
        self._serial = asyncio.Lock()
        self._consecutive_429 = 0
        self._private_key: SigningKey | None = None
        self._http = httpx.AsyncClient(
            timeout=config.request_timeout_s,
            transport=transport,
            event_hooks={"request": [_reject_non_get]},
            headers={"Accept": "application/json", "User-Agent": "kalshi-recon/1.0"},
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()

    async def call(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        auth: bool = False,
        job_id: str | None = None,
        module: str = "M0",
        store_raw: bool = False,
    ) -> CallResult:
        """Send one logical GET request (plus transport retries) and return the result.

        ``path`` is relative to the base URL, e.g. ``/markets/ABC``. Non-2xx responses are
        returned, not raised, except 429 which raises RateLimited.
        """
        method = method.upper()
        if method != "GET":
            raise ReadOnlyViolation(method, path)
        endpoint = self._spec.match_get(path)
        if endpoint is None:
            raise SpecViolation(path)
        if auth and not self._config.credentials_configured:
            raise AuthNotConfigured()

        ctx = None
        if job_id is not None:
            ctx = self._jobs.context(job_id)
            if ctx is None:
                raise JobCancelled()
            module = ctx.module

        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        attempt = 0
        async with self._serial:
            while True:
                if ctx is not None:
                    ctx.consume_request()
                await self._bucket.acquire()
                result = await self._send_once(
                    path, endpoint.path, clean_params, auth, job_id, module, store_raw
                )
                if result.status_code == 429:
                    cooldown = self._cooldown_after_429(result.headers)
                    self._bucket.cooldown(cooldown)
                    raise RateLimited(path, cooldown)
                if result.status_code is not None and result.status_code < 500:
                    self._consecutive_429 = 0
                    return result
                if attempt >= self._config.max_transport_retries:
                    return result
                attempt += 1
                await asyncio.sleep(0.5 * 2**attempt)

    async def _send_once(
        self,
        path: str,
        path_template: str,
        params: dict[str, Any],
        auth: bool,
        job_id: str | None,
        module: str,
        store_raw: bool,
    ) -> CallResult:
        base_url = self._settings.get().base_url.rstrip("/")
        url = httpx.URL(base_url + path, params=params)
        headers = self._auth_headers(signing_path(base_url, path)) if auth else {}

        sent_at = datetime.now(UTC)
        started = time.perf_counter()
        status: int | None = None
        body: bytes | None = None
        resp_headers: dict[str, str] = {}
        error: str | None = None
        try:
            response = await self._http.get(url, headers=headers)
            status, body, resp_headers = response.status_code, response.content, dict(
                response.headers
            )
        except httpx.TimeoutException:
            error = f"Timed out after {self._config.request_timeout_s:.0f}s"
        except httpx.TransportError as exc:
            error = f"Network error: {type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000
        received_at = datetime.now(UTC)

        request_id = self._evidence.record(
            RequestRecord(
                job_id=job_id,
                module=module,
                timestamp_utc=sent_at,
                method="GET",
                url=str(url),
                path=path,
                path_template=path_template,
                params=params,
                auth_used=auth,
                status_code=status,
                latency_ms=round(latency_ms, 2),
                response_headers=resp_headers,
                body=body,
                error=error,
            ),
            store_raw=store_raw,
        )
        return CallResult(
            request_id=request_id,
            url=str(url),
            path_template=path_template,
            status_code=status,
            headers=redact_headers(resp_headers),
            body=body,
            latency_ms=round(latency_ms, 2),
            sent_at=sent_at,
            received_at=received_at,
            error=error,
        )

    def websocket_headers(self, ws_path: str) -> dict[str, str]:
        """Handshake headers for the WebSocket: ``timestamp + "GET" + ws_path`` signed like REST.

        The values never leave the backend; the WebSocket client passes them straight to the
        handshake and logs only redacted copies.
        """
        return self._auth_headers(ws_path)

    async def acquire_token(self) -> None:
        """Take one token from the global bucket (WebSocket handshakes and commands use it too)."""
        await self._bucket.acquire()

    def _auth_headers(self, sign_path: str) -> dict[str, str]:
        if not self._config.credentials_configured:
            raise AuthNotConfigured()
        if self._private_key is None:
            key_text = self._config.private_key_text()
            assert key_text is not None
            try:
                self._private_key = load_private_key(key_text)
            except (ValueError, TypeError):
                raise AuthNotConfigured(
                    "Could not parse the private key. Paste the full key (including the "
                    "-----BEGIN ...----- and -----END ...----- lines) into KALSHI_PRIVATE_KEY "
                    "in .env, then restart the backend."
                ) from None
        assert self._config.kalshi_key_id is not None
        return auth_headers(
            self._config.kalshi_key_id.get_secret_value(), self._private_key, "GET", sign_path
        )

    def _cooldown_after_429(self, headers: Mapping[str, str]) -> float:
        """Honor Retry-After if present; otherwise exponential backoff (2s, 4s, ... 60s)."""
        self._consecutive_429 += 1
        retry_after = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
        if retry_after is not None:
            try:
                return min(max(0.0, float(retry_after)), _MAX_RETRY_AFTER_S)
            except ValueError:
                try:
                    delta = parsedate_to_datetime(retry_after) - datetime.now(UTC)
                    return min(max(0.0, delta.total_seconds()), _MAX_RETRY_AFTER_S)
                except (TypeError, ValueError):
                    pass
        return min(2.0**self._consecutive_429, _MAX_429_COOLDOWN_S)
