"""The client must refuse anything but GET, and only call GET paths present in the spec."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from app.errors import (
    RateLimited,
    ReadOnlyViolation,
    RequestBudgetExceeded,
    SpecViolation,
)
from app.jobs import JobContext
from app.kalshi_client import _reject_non_get
from tests.conftest import Handler, Stack


def _ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"exchange_active": True})


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "post", "HEAD"])
async def test_non_get_methods_are_blocked_before_any_network_io(
    make_stack: Callable[[Handler], Stack], method: str
) -> None:
    stack = make_stack(_ok)
    with pytest.raises(ReadOnlyViolation):
        await stack.client.call(method, "/portfolio/orders", auth=True)
    assert stack.sent == []
    assert stack.evidence.list_requests() == []


async def test_paths_not_in_spec_are_blocked(make_stack: Callable[[Handler], Stack]) -> None:
    stack = make_stack(_ok)
    with pytest.raises(SpecViolation):
        await stack.client.call("GET", "/definitely/not/a/kalshi/endpoint")
    assert stack.sent == []


async def test_httpx_hook_rejects_non_get_requests() -> None:
    request = httpx.Request("POST", "https://example.invalid/trade-api/v2/portfolio/orders")
    with pytest.raises(ReadOnlyViolation):
        await _reject_non_get(request)
    await _reject_non_get(httpx.Request("GET", "https://example.invalid/x"))


async def test_public_get_is_sent_and_logged(make_stack: Callable[[Handler], Stack]) -> None:
    stack = make_stack(_ok)
    result = await stack.client.call("GET", "/exchange/status", module="M1")
    assert result.status_code == 200
    assert [r.method for r in stack.sent] == ["GET"]
    assert "kalshi-access-key" not in {k.lower() for k in stack.sent[0].headers}
    rows = stack.evidence.list_requests()
    assert len(rows) == 1 and rows[0]["module"] == "M1" and rows[0]["auth_used"] is False


async def test_4xx_is_not_retried(make_stack: Callable[[Handler], Stack]) -> None:
    stack = make_stack(lambda _: httpx.Response(404, json={"error": "not found"}))
    result = await stack.client.call("GET", "/markets/NOPE")
    assert result.status_code == 404
    assert len(stack.sent) == 1


async def test_5xx_is_retried_up_to_the_limit(
    make_stack: Callable[[Handler], Stack], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    stack = make_stack(lambda _: httpx.Response(503))
    result = await stack.client.call("GET", "/exchange/status")
    assert result.status_code == 503
    assert len(stack.sent) == 3
    assert len(stack.evidence.list_requests()) == 3


async def test_first_429_raises_and_sets_cooldown(make_stack: Callable[[Handler], Stack]) -> None:
    stack = make_stack(lambda _: httpx.Response(429, json={"error": "too many requests"}))
    with pytest.raises(RateLimited) as excinfo:
        await stack.client.call("GET", "/exchange/status")
    assert len(stack.sent) == 1
    assert excinfo.value.cooldown_s == 2.0
    assert stack.bucket.snapshot()["cooldown_remaining_s"] > 0


async def test_retry_after_header_is_honored(make_stack: Callable[[Handler], Stack]) -> None:
    stack = make_stack(lambda _: httpx.Response(429, headers={"Retry-After": "7"}))
    with pytest.raises(RateLimited) as excinfo:
        await stack.client.call("GET", "/exchange/status")
    assert excinfo.value.cooldown_s == 7.0


async def test_job_request_cap_is_enforced(make_stack: Callable[[Handler], Stack]) -> None:
    stack = make_stack(_ok)

    async def runner(ctx: JobContext) -> dict[str, int]:
        for _ in range(5):
            await stack.client.call("GET", "/exchange/status", job_id=ctx.id)
        return {}

    job_id = stack.jobs.start("M5", "cap_test", {}, runner, max_requests=2)
    events = [event async for event in stack.jobs.subscribe(job_id)]
    assert events[-1]["status"] == "failed"
    assert len(stack.sent) == 2
    job = stack.jobs.get_job(job_id)
    assert job is not None
    assert job["error_reason"] == RequestBudgetExceeded(2).user_message


async def test_stop_all_cancels_running_jobs(make_stack: Callable[[Handler], Stack]) -> None:
    stack = make_stack(_ok)

    async def runner(ctx: JobContext) -> dict[str, int]:
        await asyncio.sleep(30)
        return {}

    job_id = stack.jobs.start("M4", "long", {}, runner, max_requests=10)
    await asyncio.sleep(0)
    assert stack.jobs.stop_all() == 1
    events = [event async for event in stack.jobs.subscribe(job_id)]
    assert events[-1]["status"] == "cancelled"
