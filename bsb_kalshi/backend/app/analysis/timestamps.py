"""Detect and parse timestamp-like values found in API responses.

Detection rules (documented so they can be audited):
- Strings matching ISO 8601 (``YYYY-MM-DD`` optionally followed by ``THH:MM[:SS[.fff]]`` and
  ``Z`` or ``+HH:MM``) are timestamp-like; the format label records the timezone designator
  and the number of fractional-second digits.
- Integers/floats (not booleans) inside a plausible epoch window (years 2000-2100) are
  timestamp-like as unix seconds, milliseconds, microseconds, or nanoseconds by magnitude.
- Numeric strings are not treated as timestamps (they are usually prices or counts here).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

_ISO_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:[T ](?P<time>\d{2}:\d{2}(?::\d{2})?)(?:\.(?P<frac>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?)?$"
)

_EPOCH_MIN_S = 946_684_800  # 2000-01-01T00:00:00Z
_EPOCH_MAX_S = 4_102_444_800  # 2100-01-01T00:00:00Z
_EPOCH_SCALES: tuple[tuple[str, int], ...] = (
    ("unix seconds", 1),
    ("unix milliseconds", 1_000),
    ("unix microseconds", 1_000_000),
    ("unix nanoseconds", 1_000_000_000),
)


def detect_timestamp_format(value: Any) -> str | None:
    """Return a human-readable format label if ``value`` looks like a timestamp, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = _ISO_RE.match(value.strip())
        if match is None:
            return None
        if match.group("time") is None:
            return "ISO 8601 date"
        tz = match.group("tz")
        tz_label = "UTC 'Z'" if tz == "Z" else (f"offset {tz}" if tz else "no timezone")
        frac = match.group("frac")
        frac_label = f", {len(frac)} fractional digits" if frac else ""
        return f"ISO 8601 ({tz_label}{frac_label})"
    if isinstance(value, int | float):
        for label, scale in _EPOCH_SCALES:
            if _EPOCH_MIN_S * scale <= value <= _EPOCH_MAX_S * scale:
                return label + (" (integer)" if isinstance(value, int) else " (float)")
    return None


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 string or unix epoch number into an aware UTC datetime."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        match = _ISO_RE.match(value.strip())
        if match is None:
            return None
        frac = (match.group("frac") or "")[:6]
        tz = match.group("tz") or ""
        tz = "+00:00" if tz == "Z" else tz
        text = match.group("date")
        if match.group("time") is not None:
            clock = match.group("time")
            text += "T" + (clock if clock.count(":") == 2 else clock + ":00")
            text += f".{frac.ljust(6, '0')}" if frac else ""
        try:
            parsed = datetime.fromisoformat(text + tz)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    if isinstance(value, int | float):
        for _, scale in _EPOCH_SCALES:
            if _EPOCH_MIN_S * scale <= value <= _EPOCH_MAX_S * scale:
                return datetime.fromtimestamp(value / scale, tz=UTC)
    return None


def to_epoch(value: Any) -> float | None:
    """Unix seconds for a timestamp-like value, or None."""
    parsed = parse_timestamp(value)
    return parsed.timestamp() if parsed is not None else None


def iso(epoch_s: float | None) -> str | None:
    """ISO 8601 UTC string for unix seconds (None passes through)."""
    if epoch_s is None:
        return None
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def stored_utc_iso(value: datetime) -> str:
    """ISO 8601 with offset for a datetime read back from SQLite, which drops tzinfo (stored as UTC)."""
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
