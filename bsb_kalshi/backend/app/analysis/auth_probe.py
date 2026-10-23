"""Auth-probe planning and classification (pure functions; the runner lives in M1).

Planning rules:
- Only GET operations from the spec are probed.
- Path parameters are filled only with IDs auto-discovered from public list endpoints:
  market/event/series tickers, an archived market ticker, milestone ids, structured target
  ids, and multivariate collection tickers. ``{ticker}`` is resolved by the preceding path
  segment (``markets`` -> market ticker, ``events`` -> event ticker, ``series`` -> series
  ticker); under ``/historical/markets/`` it is an archived market ticker.
- Required query parameters are filled only when a safe value exists (page size 1, a recent
  3-hour time range, a period_interval from the spec enum, or a discovered ticker/id).
  Anything else is skipped with a stated reason instead of guessed.
- Optional ``limit``/``page_size`` parameters are set to 1 to keep responses small.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.evidence import is_account_path
from app.spec_loader import EndpointSpec, OpenApiSpec, ParamSpec

IdKind = Literal[
    "market_ticker",
    "historical_market_ticker",
    "event_ticker",
    "series_ticker",
    "milestone_id",
    "structured_target_id",
    "collection_ticker",
]

_DIRECT_PATH_KINDS: dict[str, IdKind] = {
    "series_ticker": "series_ticker",
    "event_ticker": "event_ticker",
    "milestone_id": "milestone_id",
    "structured_target_id": "structured_target_id",
    "collection_ticker": "collection_ticker",
}
_TICKER_BY_SEGMENT: dict[str, IdKind] = {
    "markets": "market_ticker",
    "events": "event_ticker",
    "series": "series_ticker",
}
_QUERY_ID_KINDS: dict[str, IdKind] = {
    "tickers": "market_ticker",
    "market_tickers": "market_ticker",
    "milestone_ids": "milestone_id",
}
_PAGE_SIZE_PARAMS = ("limit", "page_size")
PROBE_WINDOW_S = 3 * 3600


def endpoint_id(endpoint: EndpointSpec) -> str:
    """Stable identifier used for ratings and probe results."""
    return f"{endpoint.method} {endpoint.path}"


def path_param_kind(path: str, name: str) -> IdKind | None:
    """Which discoverable ID fills a path parameter, or None if it cannot be discovered."""
    if name in _DIRECT_PATH_KINDS:
        return _DIRECT_PATH_KINDS[name]
    if name == "ticker":
        if path.startswith("/historical/markets/"):
            return "historical_market_ticker"
        segments = path.split("/")
        index = segments.index("{ticker}")
        return _TICKER_BY_SEGMENT.get(segments[index - 1]) if index > 0 else None
    return None


@dataclass(frozen=True)
class QueryFill:
    """How to fill one query parameter: a discovered ID, a constant, or a time bound."""

    kind: Literal["id", "const", "start_ts", "end_ts"]
    id_kind: IdKind | None = None
    value: int | None = None


@dataclass(frozen=True)
class ProbeTarget:
    """A GET endpoint that can be probed, with how to build its request."""

    endpoint: EndpointSpec
    path_kinds: dict[str, IdKind]
    query: dict[str, QueryFill]

    @property
    def needs(self) -> set[IdKind]:
        """Discovered IDs this target requires."""
        kinds: set[IdKind] = set(self.path_kinds.values())
        kinds.update(q.id_kind for q in self.query.values() if q.id_kind is not None)
        return kinds


@dataclass(frozen=True)
class SkippedEndpoint:
    """A GET endpoint that is not probed, with the reason."""

    endpoint: EndpointSpec
    reason: str


@dataclass
class ProbePlan:
    """Targets to probe and endpoints skipped."""

    targets: list[ProbeTarget] = field(default_factory=list)
    skipped: list[SkippedEndpoint] = field(default_factory=list)

    @property
    def needed_ids(self) -> set[IdKind]:
        """Union of discovered IDs needed by all targets."""
        kinds: set[IdKind] = set()
        for target in self.targets:
            kinds |= target.needs
        return kinds


def _period_interval(param: ParamSpec) -> int | None:
    if not param.enum:
        return 60
    numeric = [v for v in param.enum if isinstance(v, int) and v > 0]
    if 60 in numeric:
        return 60
    return numeric[0] if numeric else None


def _required_query_fill(param: ParamSpec) -> QueryFill | None:
    if param.name in _QUERY_ID_KINDS:
        return QueryFill("id", id_kind=_QUERY_ID_KINDS[param.name])
    if param.name in _PAGE_SIZE_PARAMS:
        return QueryFill("const", value=max(1, int(param.minimum or 1)))
    if param.name == "start_ts":
        return QueryFill("start_ts")
    if param.name == "end_ts":
        return QueryFill("end_ts")
    if param.name == "period_interval":
        interval = _period_interval(param)
        return QueryFill("const", value=interval) if interval is not None else None
    return None


def plan_probe(spec: OpenApiSpec, include_account: bool) -> ProbePlan:
    """Decide which GET endpoints can be probed and how, per the module rules."""
    plan = ProbePlan()
    for endpoint in spec.get_endpoints():
        if not include_account and is_account_path(endpoint.path):
            plan.skipped.append(SkippedEndpoint(endpoint, "Account endpoint (excluded by option)."))
            continue
        path_kinds: dict[str, IdKind] = {}
        reason: str | None = None
        for param in endpoint.path_params:
            kind = path_param_kind(endpoint.path, param.name)
            if kind is None:
                reason = f"Path parameter '{param.name}' cannot be auto-discovered."
                break
            path_kinds[param.name] = kind
        query: dict[str, QueryFill] = {}
        if reason is None:
            for param in endpoint.required_query_params:
                fill = _required_query_fill(param)
                if fill is None:
                    reason = f"Required query parameter '{param.name}' has no safe default."
                    break
                query[param.name] = fill
        if reason is not None:
            plan.skipped.append(SkippedEndpoint(endpoint, reason))
            continue
        for name in _PAGE_SIZE_PARAMS:
            optional = endpoint.param(name)
            if optional is not None and optional.location == "query" and name not in query:
                query[name] = QueryFill("const", value=max(1, int(optional.minimum or 1)))
        plan.targets.append(ProbeTarget(endpoint, path_kinds, query))
    return plan


def build_request(
    target: ProbeTarget, ids: dict[IdKind, str], now_s: int
) -> tuple[str, dict[str, str | int]] | None:
    """Concrete path and query for a target, or None if a needed ID was not discovered."""
    if any(kind not in ids for kind in target.needs):
        return None
    path = target.endpoint.path
    for name, kind in target.path_kinds.items():
        path = path.replace("{" + name + "}", ids[kind])
    params: dict[str, str | int] = {}
    for name, fill in target.query.items():
        if fill.kind == "id" and fill.id_kind is not None:
            params[name] = ids[fill.id_kind]
        elif fill.kind == "const" and fill.value is not None:
            params[name] = fill.value
        elif fill.kind == "start_ts":
            params[name] = now_s - PROBE_WINDOW_S
        elif fill.kind == "end_ts":
            params[name] = now_s
    return path, params


Classification = Literal[
    "public", "key required", "denied even with key", "inconclusive", "error", "not probed"
]


@dataclass(frozen=True)
class ProbeVerdict:
    """Objective classification of a probe pair, compared with the spec's claim."""

    classification: Classification
    mismatch: bool | None
    note: str


def _is_2xx(status: int | None) -> bool:
    return status is not None and 200 <= status < 300


def classify_probe(
    no_auth_status: int | None, auth_status: int | None, spec_auth_required: bool
) -> ProbeVerdict:
    """Classify observed statuses and flag disagreement with the spec.

    ``mismatch`` is True when the observation contradicts the spec, False when it agrees,
    and None when the statuses do not allow a conclusion either way.
    """
    denied = (401, 403)
    if no_auth_status is None:
        return ProbeVerdict("error", None, "No HTTP response without the key.")
    if _is_2xx(no_auth_status):
        return ProbeVerdict(
            "public",
            spec_auth_required,
            "Spec says a key is required, but the call succeeded without one."
            if spec_auth_required
            else "Works without a key, as the spec says.",
        )
    if no_auth_status in denied and _is_2xx(auth_status):
        return ProbeVerdict(
            "key required",
            not spec_auth_required,
            "Spec says public, but the call needed the key."
            if not spec_auth_required
            else "Needs the key, as the spec says.",
        )
    if no_auth_status in denied and auth_status in denied:
        return ProbeVerdict(
            "denied even with key",
            None,
            f"HTTP {no_auth_status} without key and HTTP {auth_status} with key.",
        )
    if no_auth_status in denied and auth_status is None:
        return ProbeVerdict(
            "inconclusive", None, f"HTTP {no_auth_status} without key; authenticated call not made."
        )
    return ProbeVerdict(
        "inconclusive",
        None,
        f"HTTP {no_auth_status} without key"
        + (f" and HTTP {auth_status} with key." if auth_status is not None else "."),
    )
