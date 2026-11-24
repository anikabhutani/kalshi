"""Parse specs/openapi.yaml and specs/asyncapi.yaml into typed catalogs.

Everything the rest of the app knows about endpoints, parameters, auth requirements, and
WebSocket channels comes from here. Nothing is hardcoded from memory. Heuristic signals
(timestamp-like fields, time-range params, historical hints) are rule-based and the rules
are documented on each function so a reader can audit them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

HTTP_METHODS = ("get", "post", "put", "delete", "patch")

TIMESTAMP_NAME_RE = re.compile(
    r"(^ts$|_ts$|^time$|_time$|_time_ms$|^date$|_date$|_datetime$|_at$|timestamp)",
    re.IGNORECASE,
)
TIME_RANGE_PARAM_RE = re.compile(r"(^|_)(ts|from|to|date|last_sec|range)$", re.IGNORECASE)
PAGINATION_PARAM_NAMES = frozenset({"cursor", "limit", "page_size"})


@dataclass(frozen=True)
class ParamSpec:
    """A single resolved operation parameter."""

    name: str
    location: str
    required: bool
    type: str | None
    format: str | None
    enum: list[Any] | None
    default: Any
    minimum: float | None
    maximum: float | None
    description: str


@dataclass(frozen=True)
class TimestampField:
    """A response-schema property whose name or format looks like a timestamp."""

    path: str
    type: str | None
    format: str | None


@dataclass(frozen=True)
class SpecProperty:
    """A declared property of a response object, as written in the spec."""

    type: str | None
    format: str | None
    nullable: bool
    required: bool
    enum: list[Any] | None
    description: str


@dataclass(frozen=True)
class EndpointSpec:
    """A resolved OpenAPI operation with objective, spec-derived signals."""

    operation_id: str
    method: str
    path: str
    tags: list[str]
    summary: str
    description: str
    params: list[ParamSpec]
    auth_required: bool
    auth_schemes: list[list[str]]
    pagination_params: list[str]
    time_range_params: list[str]
    timestamp_fields: list[TimestampField]
    historical_signals: list[str]
    path_regex: re.Pattern[str] = field(repr=False, compare=False)

    @property
    def path_params(self) -> list[ParamSpec]:
        """Parameters that must be substituted into the URL path."""
        return [p for p in self.params if p.location == "path"]

    @property
    def required_query_params(self) -> list[ParamSpec]:
        """Query parameters the spec marks as required."""
        return [p for p in self.params if p.location == "query" and p.required]

    def param(self, name: str) -> ParamSpec | None:
        """Look up a parameter by name."""
        return next((p for p in self.params if p.name == name), None)


class OpenApiSpec:
    """Loaded OpenAPI document with a GET-path matcher used by the read-only guard."""

    def __init__(self, document: dict[str, Any]) -> None:
        self._doc = document
        self.version: str = str(document.get("info", {}).get("version", ""))
        self.title: str = str(document.get("info", {}).get("title", ""))
        self.servers: list[dict[str, str]] = [
            {"url": s["url"], "description": s.get("description", "")}
            for s in document.get("servers", [])
        ]
        self.endpoints: list[EndpointSpec] = self._build_endpoints()

    @classmethod
    def load(cls, path: Path) -> OpenApiSpec:
        """Load and parse an OpenAPI YAML file."""
        with path.open("r", encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    @property
    def server_urls(self) -> list[str]:
        """All base URLs declared in the spec, in spec order."""
        return [s["url"] for s in self.servers]

    def get_endpoints(self) -> list[EndpointSpec]:
        """All GET operations."""
        return [e for e in self.endpoints if e.method == "GET"]

    def find(self, method: str, path_template: str) -> EndpointSpec | None:
        """Find an operation by method and exact path template."""
        method = method.upper()
        return next(
            (e for e in self.endpoints if e.method == method and e.path == path_template), None
        )

    def match_get(self, concrete_path: str) -> EndpointSpec | None:
        """Match a concrete path (e.g. /markets/ABC) to a GET operation in the spec.

        Literal templates win over parameterized ones so that /markets/trades does not
        match /markets/{ticker}.
        """
        concrete_path = concrete_path.split("?", 1)[0]
        candidates = [e for e in self.get_endpoints() if e.path_regex.fullmatch(concrete_path)]
        if not candidates:
            return None
        return min(candidates, key=lambda e: e.path.count("{"))

    def resolve(self, node: Any) -> Any:
        """Resolve a local $ref (one level). Non-ref nodes are returned unchanged."""
        if isinstance(node, dict) and "$ref" in node:
            ref: str = node["$ref"]
            if not ref.startswith("#/"):
                return {}
            target: Any = self._doc
            for part in ref[2:].split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            return target
        return node

    def response_object_properties(self, path: str, key: str) -> dict[str, SpecProperty]:
        """Declared properties of ``response[key]`` (or its array items) for GET ``path``.

        Used to compare observed fields with what the spec declares. Returns an empty dict
        if the operation, key, or schema cannot be resolved.
        """
        op = self._doc.get("paths", {}).get(path, {}).get("get")
        if op is None:
            return {}
        root = self.resolve(self._raw_200_schema(op))
        node = self.resolve((root.get("properties") or {}).get(key, {}))
        if node.get("type") == "array":
            node = self.resolve(node.get("items", {}))
        required = set(node.get("required") or [])
        props: dict[str, SpecProperty] = {}
        for name, raw in (node.get("properties") or {}).items():
            base = self.resolve(raw)
            merged = {k: v for k, v in base.items() if k != "allOf"}
            for sub in base.get("allOf", []):
                merged = {**self.resolve(sub), **merged}
            local = raw if isinstance(raw, dict) else {}
            props[name] = SpecProperty(
                type=merged.get("type"),
                format=merged.get("format"),
                nullable=bool(merged.get("nullable") or local.get("nullable")),
                required=name in required,
                enum=merged.get("enum"),
                description=(local.get("description") or merged.get("description") or "").strip(),
            )
        return props

    def response_array_keys(self, path: str) -> list[str]:
        """Top-level properties of GET ``path``'s 200 response that the spec types as arrays."""
        op = self._doc.get("paths", {}).get(path, {}).get("get")
        if op is None:
            return []
        root = self.resolve(self._raw_200_schema(op))
        return [
            name
            for name, prop in (root.get("properties") or {}).items()
            if self.resolve(prop).get("type") == "array"
        ]

    def _build_endpoints(self) -> list[EndpointSpec]:
        endpoints: list[EndpointSpec] = []
        for path, item in self._doc.get("paths", {}).items():
            shared = item.get("parameters", [])
            for method in HTTP_METHODS:
                op = item.get(method)
                if op is None:
                    continue
                params = [self._param(p) for p in shared + op.get("parameters", [])]
                endpoints.append(self._endpoint(path, method, op, params))
        return endpoints

    def _param(self, raw: dict[str, Any]) -> ParamSpec:
        p = self.resolve(raw)
        schema = self.resolve(p.get("schema", {}))
        return ParamSpec(
            name=p.get("name", ""),
            location=p.get("in", ""),
            required=bool(p.get("required", False)),
            type=schema.get("type"),
            format=schema.get("format"),
            enum=schema.get("enum"),
            default=schema.get("default"),
            minimum=schema.get("minimum"),
            maximum=schema.get("maximum"),
            description=(p.get("description") or "").strip(),
        )

    def _endpoint(
        self, path: str, method: str, op: dict[str, Any], params: list[ParamSpec]
    ) -> EndpointSpec:
        security = op.get("security") or []
        auth_schemes = [sorted(req.keys()) for req in security]
        description = (op.get("description") or "").strip()
        return EndpointSpec(
            operation_id=op.get("operationId", f"{method}:{path}"),
            method=method.upper(),
            path=path,
            tags=list(op.get("tags", [])),
            summary=(op.get("summary") or "").strip(),
            description=description,
            params=params,
            auth_required=bool(auth_schemes) and all(auth_schemes),
            auth_schemes=auth_schemes,
            pagination_params=[p.name for p in params if p.name in PAGINATION_PARAM_NAMES],
            time_range_params=[p.name for p in params if _is_time_range_param(p)],
            timestamp_fields=_collect_timestamp_fields(self, self._raw_200_schema(op), "", set()),
            historical_signals=_historical_signals(path, description, params),
            path_regex=_template_regex(path),
        )

    def _raw_200_schema(self, op: dict[str, Any]) -> dict[str, Any]:
        response = self.resolve(op.get("responses", {}).get("200", {}))
        content = response.get("content", {}).get("application/json", {})
        return content.get("schema", {})


def _template_regex(path: str) -> re.Pattern[str]:
    pattern = re.sub(r"\\\{[^/]+?\\\}", r"[^/]+", re.escape(path))
    return re.compile(pattern)


def _is_time_range_param(p: ParamSpec) -> bool:
    """Rule: query param named *_ts / from / to / *_date / last_sec / range, or date-time."""
    if p.location != "query":
        return False
    return bool(TIME_RANGE_PARAM_RE.search(p.name)) or p.format in ("date-time", "date")


def _historical_signals(path: str, description: str, params: list[ParamSpec]) -> list[str]:
    """Rule: path under /historical, a show_historical param, or 'historical'/'archiv' text."""
    signals: list[str] = []
    if path.startswith("/historical"):
        signals.append("path is under /historical")
    if any(p.name == "show_historical" for p in params):
        signals.append("has show_historical parameter")
    lowered = description.lower()
    if "historical" in lowered or "archiv" in lowered:
        signals.append("description mentions historical/archived data")
    return signals


def _collect_timestamp_fields(
    spec: OpenApiSpec, node: Any, prefix: str, seen: set[str]
) -> list[TimestampField]:
    """Walk a response schema and collect timestamp-like properties.

    Rule: a property is timestamp-like if its schema format is date-time/date, or its name
    matches TIMESTAMP_NAME_RE (ts, *_ts, *_time, *_date, *_datetime, *_at, *timestamp*).
    """
    if isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref in seen:
            return []
        seen = seen | {ref}
    node = spec.resolve(node)
    if not isinstance(node, dict):
        return []

    found: list[TimestampField] = []
    for combinator in ("allOf", "oneOf", "anyOf"):
        for sub in node.get(combinator, []):
            found.extend(_collect_timestamp_fields(spec, sub, prefix, seen))

    if node.get("type") == "array" or "items" in node:
        found.extend(_collect_timestamp_fields(spec, node.get("items", {}), f"{prefix}[]", seen))

    for name, prop in (node.get("properties") or {}).items():
        child_path = f"{prefix}.{name}" if prefix else name
        resolved = spec.resolve(prop)
        fmt = resolved.get("format") if isinstance(resolved, dict) else None
        typ = resolved.get("type") if isinstance(resolved, dict) else None
        if fmt in ("date-time", "date") or (
            TIMESTAMP_NAME_RE.search(name) and typ in ("string", "integer", "number")
        ):
            found.append(TimestampField(path=child_path, type=typ, format=fmt))
        found.extend(_collect_timestamp_fields(spec, prop, child_path, seen))
    return found


@dataclass(frozen=True)
class ChannelSpec:
    """A WebSocket channel declared in the AsyncAPI document."""

    name: str
    address: str | None
    title: str
    description: str
    message_names: list[str]


class AsyncApiSpec:
    """Loaded AsyncAPI document (WebSocket). Used for display and by the WS recorder."""

    def __init__(self, document: dict[str, Any]) -> None:
        self._doc = document
        self.version: str = str(document.get("info", {}).get("version", ""))
        self.title: str = str(document.get("info", {}).get("title", ""))
        self.servers: list[dict[str, str]] = [
            {
                "name": name,
                "url": f"{s.get('protocol', 'wss')}://{s.get('host', '')}{s.get('pathname', '')}",
                "pathname": s.get("pathname", ""),
                "description": s.get("description", ""),
            }
            for name, s in (document.get("servers") or {}).items()
        ]
        self.channels: list[ChannelSpec] = [
            ChannelSpec(
                name=name,
                address=ch.get("address"),
                title=ch.get("title", ""),
                description=(ch.get("description") or "").strip(),
                message_names=sorted((ch.get("messages") or {}).keys()),
            )
            for name, ch in (document.get("channels") or {}).items()
        ]

    @classmethod
    def load(cls, path: Path) -> AsyncApiSpec:
        """Load and parse an AsyncAPI YAML file."""
        with path.open("r", encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    def channel(self, name: str) -> ChannelSpec | None:
        """A declared channel by name."""
        return next((c for c in self.channels if c.name == name), None)

    def schema(self, name: str) -> dict[str, Any]:
        """Raw ``components.schemas[name]`` (empty dict if absent)."""
        schemas = (self._doc.get("components") or {}).get("schemas") or {}
        node = schemas.get(name)
        return node if isinstance(node, dict) else {}

    def field_description(self, schema_name: str, *path: str) -> str | None:
        """Description of a nested property, e.g. ``("msg", "ts_ms")`` in ``tickerPayload``.

        A property that is only a ``$ref`` falls back to the referenced schema's description.
        """
        node: Any = self.schema(schema_name)
        for part in path:
            props = node.get("properties") if isinstance(node, dict) else None
            node = props.get(part) if isinstance(props, dict) else None
            if node is None:
                return None
        if not isinstance(node, dict):
            return None
        description = node.get("description")
        ref = node.get("$ref")
        if not description and isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            description = self.schema(ref.rsplit("/", 1)[-1]).get("description")
        return str(description).strip() if description else None

    def subscribe_channels(self) -> list[str]:
        """Channel names the ``subscribe`` command accepts (its ``channels`` enum)."""
        node = self.schema("subscribeCommandPayload")
        channels = (((node.get("properties") or {}).get("params") or {}).get("properties") or {}).get(
            "channels"
        ) or {}
        return [str(c) for c in (channels.get("items") or {}).get("enum") or []]

    def error_codes(self) -> list[dict[str, Any]]:
        """The ``x-error-codes`` list: code, name, description."""
        block = self._doc.get("x-error-codes") or {}
        return [
            {"code": c.get("code"), "name": c.get("name", ""), "description": c.get("description", "")}
            for c in block.get("codes") or []
            if isinstance(c, dict)
        ]

    def security_description(self) -> str | None:
        """Description of the WebSocket security scheme."""
        schemes = (self._doc.get("components") or {}).get("securitySchemes") or {}
        texts = [str(s.get("description", "")).strip() for s in schemes.values() if isinstance(s, dict)]
        return " ".join(t for t in texts if t) or None
