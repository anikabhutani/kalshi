"""Timestamp-like value detection and parsing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.analysis.timestamps import detect_timestamp_format, parse_timestamp, to_epoch


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-01T05:05:45.23224Z", "ISO 8601 (UTC 'Z', 5 fractional digits)"),
        ("2026-10-01T05:05:45Z", "ISO 8601 (UTC 'Z')"),
        ("2026-10-01T05:05:45+02:00", "ISO 8601 (offset +02:00)"),
        ("2026-10-01T05:05", "ISO 8601 (no timezone)"),
        ("2026-10-01", "ISO 8601 date"),
        (1_790_560_560, "unix seconds (integer)"),
        (1_790_560_560_123, "unix milliseconds (integer)"),
        (1_790_560_560.5, "unix seconds (float)"),
    ],
)
def test_detects_formats(value: object, expected: str) -> None:
    assert detect_timestamp_format(value) == expected


@pytest.mark.parametrize("value", ["0.5600", "1790560560", "KXMLBGAME", 42, 0.56, True, None, [], {}])
def test_rejects_non_timestamps(value: object) -> None:
    assert detect_timestamp_format(value) is None


def test_parses_iso_with_variable_fraction_to_utc() -> None:
    parsed = parse_timestamp("2026-10-01T05:05:45.23224Z")
    assert parsed == datetime(2026, 10, 1, 5, 5, 45, 232240, tzinfo=UTC)


def test_parses_offsets_and_nanoseconds() -> None:
    assert parse_timestamp("2026-10-01T07:00:00+02:00") == datetime(2026, 10, 1, 5, tzinfo=UTC)
    assert parse_timestamp("2026-10-01T05:00:00.123456789Z") == datetime(
        2026, 10, 1, 5, 0, 0, 123456, tzinfo=UTC
    )


def test_parses_epochs_by_magnitude() -> None:
    assert to_epoch(1_790_560_560) == 1_790_560_560
    assert to_epoch(1_790_560_560_000) == 1_790_560_560
    assert parse_timestamp("not a time") is None
    assert parse_timestamp(None) is None
