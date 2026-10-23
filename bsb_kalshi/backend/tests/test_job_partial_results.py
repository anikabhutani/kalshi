"""Jobs stopped by a 429 or the kill switch keep the results collected so far."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from app.errors import RateLimited
from app.jobs import JobContext
from tests.conftest import Handler, Stack


async def _wait_finished(stack: Stack, job_id: str) -> dict[str, Any]:
    for _ in range(200):
        job = stack.jobs.get_job(job_id)
        if job is not None and job["status"] != "running":
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("job did not finish")


async def test_rate_limited_job_stores_partial_result(make_stack: Callable[[Handler], Stack]) -> None:
    stack = make_stack(lambda _: httpx.Response(429, json={"error": "too many requests"}))

    async def runner(ctx: JobContext) -> dict[str, Any]:
        ctx.save_partial({"rows": [1, 2]})
        await stack.client.call("GET", "/exchange/status", job_id=ctx.id)
        return {"rows": [1, 2, 3]}

    job_id = stack.jobs.start("M1", "test", {}, runner, max_requests=5)
    job = await _wait_finished(stack, job_id)
    assert job["status"] == "failed"
    assert RateLimited("/exchange/status", 2).user_message.split(".")[0] in job["error_reason"]
    assert job["result"] == {"rows": [1, 2], "partial": True}


async def test_latest_with_result_skips_jobs_without_results(
    make_stack: Callable[[Handler], Stack],
) -> None:
    stack = make_stack(lambda _: httpx.Response(200, json={}))

    async def ok(_: JobContext) -> dict[str, Any]:
        return {"value": 1}

    async def boom(_: JobContext) -> dict[str, Any]:
        raise RuntimeError("no result")

    first = stack.jobs.start("M3", "kind", {}, ok, max_requests=1)
    await _wait_finished(stack, first)
    second = stack.jobs.start("M3", "kind", {}, boom, max_requests=1)
    await _wait_finished(stack, second)
    latest = stack.jobs.latest_with_result("M3", "kind")
    assert latest is not None and latest["id"] == first
    assert all(j["result"] is None for j in stack.jobs.list_jobs(module="M3"))
