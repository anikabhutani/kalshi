"""Flatten JSON objects into a field dictionary (path, type, example, nullability, timestamps).

Paths use dots for object keys and ``[]`` for array elements, e.g. ``markets[].ticker``.
When the same path is seen in several samples (e.g. every market in an event), statistics
are aggregated: types seen, how often the field was null, and how often it was absent.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.analysis.timestamps import detect_timestamp_format
from app.spec_loader import TIMESTAMP_NAME_RE

_EXAMPLE_MAX_CHARS = 120
MAX_DISTINCT_VALUES = 10


def json_type(value: Any) -> str:
    """JSON type name of a Python value decoded from JSON."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


@dataclass
class _FieldAcc:
    types: set[str] = field(default_factory=set)
    present: int = 0
    nulls: int = 0
    example: Any = None
    has_example: bool = False
    timestamp_formats: set[str] = field(default_factory=set)
    distinct: list[str | int | bool] = field(default_factory=list)
    distinct_overflow: bool = False


@dataclass(frozen=True)
class FieldEntry:
    """One row of the field dictionary."""

    path: str
    types: list[str]
    example: str | None
    present_in: int
    samples: int
    null_count: int
    nullable_observed: bool
    timestamp_format: str | None
    name_looks_like_timestamp: bool
    distinct_values: list[str | int | bool]
    distinct_values_truncated: bool

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation."""
        return {
            "path": self.path,
            "types": self.types,
            "example": self.example,
            "present_in": self.present_in,
            "samples": self.samples,
            "null_count": self.null_count,
            "nullable_observed": self.nullable_observed,
            "timestamp_like": self.timestamp_format is not None,
            "timestamp_format": self.timestamp_format,
            "name_looks_like_timestamp": self.name_looks_like_timestamp,
            "distinct_values": self.distinct_values,
            "distinct_values_truncated": self.distinct_values_truncated,
        }


def _walk(value: Any, path: str, acc: dict[str, _FieldAcc], seen: set[str]) -> None:
    if path:
        entry = acc.setdefault(path, _FieldAcc())
        if path not in seen:
            entry.present += 1
            seen.add(path)
        entry.types.add(json_type(value))
        if value is None:
            entry.nulls += 1
        elif not isinstance(value, dict | list):
            if not entry.has_example:
                entry.example, entry.has_example = value, True
            if isinstance(value, str | int | bool) and value not in entry.distinct:
                if len(entry.distinct) < MAX_DISTINCT_VALUES:
                    entry.distinct.append(value)
                else:
                    entry.distinct_overflow = True
        fmt = detect_timestamp_format(value)
        if fmt is not None:
            entry.timestamp_formats.add(fmt)

    if isinstance(value, dict):
        for key, child in value.items():
            _walk(child, f"{path}.{key}" if path else key, acc, seen)
    elif isinstance(value, list):
        for item in value:
            _walk(item, f"{path}[]", acc, seen)


def flatten_samples(samples: Iterable[Any]) -> list[FieldEntry]:
    """Build a field dictionary aggregated over several JSON samples of the same entity."""
    acc: dict[str, _FieldAcc] = {}
    count = 0
    for sample in samples:
        count += 1
        _walk(sample, "", acc, set())
    rows: list[FieldEntry] = []
    for path, entry in acc.items():
        leaf = path.rsplit(".", 1)[-1].removesuffix("[]")
        example = None
        if entry.has_example:
            text = entry.example if isinstance(entry.example, str) else json.dumps(entry.example)
            example = text[:_EXAMPLE_MAX_CHARS]
        rows.append(
            FieldEntry(
                path=path,
                types=sorted(entry.types),
                example=example,
                present_in=entry.present,
                samples=count,
                null_count=entry.nulls,
                nullable_observed=entry.nulls > 0,
                timestamp_format=" | ".join(sorted(entry.timestamp_formats)) or None,
                name_looks_like_timestamp=bool(TIMESTAMP_NAME_RE.search(leaf)),
                distinct_values=list(entry.distinct),
                distinct_values_truncated=entry.distinct_overflow,
            )
        )
    return rows
