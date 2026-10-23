"""Evidence log: every outgoing request is written to SQLite with secrets redacted.

Redaction rules:
- Any header whose name starts with ``kalshi-access-`` or is a credential/cookie header is
  replaced with ``[REDACTED]``.
- Free text (URLs, error messages, body samples) is scrubbed of the configured secret
  values (the API key id).
- Response bodies from account-specific endpoints (portfolio, FCM, API keys,
  communications, personal historical fills/orders/positions) are never stored, only their
  size, because they describe the user's account rather than the market.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.db import Database
from app.models import RequestLog

REDACTED = "[REDACTED]"
BODY_SAMPLE_BYTES = 2048

_CREDENTIAL_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
)
_ACCOUNT_PATH_PREFIXES = (
    "/portfolio",
    "/fcm",
    "/api_keys",
    "/communications",
    "/historical/fills",
    "/historical/orders",
    "/historical/positions",
)


def is_secret_header(name: str) -> bool:
    """True if a header carries credentials or signing material."""
    lowered = name.lower()
    return lowered.startswith("kalshi-access-") or lowered in _CREDENTIAL_HEADERS


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of headers with credential/signature values replaced."""
    return {k: (REDACTED if is_secret_header(k) else v) for k, v in headers.items()}


def scrub(text: str | None, secrets: Iterable[str]) -> str | None:
    """Replace every occurrence of any non-empty secret value in text."""
    if text is None:
        return None
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def is_account_path(path: str) -> bool:
    """True for endpoints whose bodies describe the user's own account."""
    return path.startswith(_ACCOUNT_PATH_PREFIXES)


@dataclass(frozen=True)
class RequestRecord:
    """Everything known about one request attempt, before redaction."""

    job_id: str | None
    module: str
    timestamp_utc: datetime
    method: str
    url: str
    path: str
    path_template: str | None
    params: Mapping[str, Any]
    auth_used: bool
    status_code: int | None
    latency_ms: float | None
    response_headers: Mapping[str, str]
    body: bytes | None
    error: str | None


class EvidenceLog:
    """Writes and reads redacted request rows and optional raw body files."""

    def __init__(self, db: Database, raw_dir: Path, secrets: Iterable[str]) -> None:
        self._db = db
        self._raw_dir = raw_dir
        self._secrets = tuple(s for s in secrets if s)

    def record(self, rec: RequestRecord, store_raw: bool = False) -> int:
        """Persist one request attempt and return its row id."""
        account = is_account_path(rec.path)
        body_sample: str | None = None
        if rec.body is not None:
            if account:
                body_sample = "[omitted: account-specific response body]"
            else:
                body_sample = rec.body[:BODY_SAMPLE_BYTES].decode("utf-8", errors="replace")

        row = RequestLog(
            job_id=rec.job_id,
            module=rec.module,
            timestamp_utc=rec.timestamp_utc,
            method=rec.method,
            url=scrub(rec.url, self._secrets) or "",
            path_template=rec.path_template,
            params_json=scrub(json.dumps(dict(rec.params), default=str), self._secrets) or "{}",
            auth_used=rec.auth_used,
            status_code=rec.status_code,
            latency_ms=rec.latency_ms,
            response_bytes=len(rec.body) if rec.body is not None else None,
            response_headers_json=scrub(
                json.dumps(redact_headers(rec.response_headers)), self._secrets
            )
            or "{}",
            response_body_sample=scrub(body_sample, self._secrets),
            error=scrub(rec.error, self._secrets),
        )
        with self._db.session() as session:
            session.add(row)
            session.flush()
            row_id = row.id
            if store_raw and rec.body is not None and not account and rec.status_code == 200:
                raw_path = self._raw_dir / f"{row_id}.json"
                raw_path.write_bytes(rec.body)
                row.raw_path = raw_path.name
        return row_id

    def list_requests(
        self,
        job_id: str | None = None,
        module: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return redacted rows, newest first, optionally filtered."""
        stmt = select(RequestLog).order_by(RequestLog.id.desc()).limit(limit).offset(offset)
        if job_id is not None:
            stmt = stmt.where(RequestLog.job_id == job_id)
        if module is not None:
            stmt = stmt.where(RequestLog.module == module)
        with self._db.session() as session:
            return [_row_to_dict(r) for r in session.scalars(stmt)]

    def all_requests(self) -> list[dict[str, Any]]:
        """Every redacted row, oldest first (for exports)."""
        with self._db.session() as session:
            return [_row_to_dict(r) for r in session.scalars(select(RequestLog).order_by(RequestLog.id))]

    def raw_body(self, request_id: int) -> Any:
        """Parsed stored raw body for a request, or None if no raw file was kept."""
        with self._db.session() as session:
            row = session.get(RequestLog, request_id)
            raw_name = row.raw_path if row is not None else None
        if raw_name is None:
            return None
        raw_file = self._raw_dir / raw_name
        if not raw_file.is_file():
            return None
        try:
            return json.loads(raw_file.read_bytes())
        except ValueError:
            return None

    def count_by_module(self) -> dict[str, int]:
        """Number of logged requests per module."""
        stmt = select(RequestLog.module, func.count()).group_by(RequestLog.module)
        with self._db.session() as session:
            return {module: count for module, count in session.execute(stmt)}

    def requests_since(self, since: datetime) -> int:
        """Number of requests logged at or after a UTC timestamp."""
        stmt = select(func.count()).where(RequestLog.timestamp_utc >= since)
        with self._db.session() as session:
            return int(session.scalar(stmt) or 0)


def _row_to_dict(r: RequestLog) -> dict[str, Any]:
    ts = r.timestamp_utc if r.timestamp_utc.tzinfo else r.timestamp_utc.replace(tzinfo=UTC)
    return {
        "id": r.id,
        "job_id": r.job_id,
        "module": r.module,
        "timestamp_utc": ts.isoformat(),
        "method": r.method,
        "url": r.url,
        "path_template": r.path_template,
        "params": json.loads(r.params_json or "{}"),
        "auth_used": r.auth_used,
        "status_code": r.status_code,
        "latency_ms": r.latency_ms,
        "response_bytes": r.response_bytes,
        "response_headers": json.loads(r.response_headers_json or "{}"),
        "response_body_sample": r.response_body_sample,
        "raw_path": r.raw_path,
        "error": r.error,
    }
