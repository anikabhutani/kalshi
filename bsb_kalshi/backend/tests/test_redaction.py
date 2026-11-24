"""Secrets must never reach the evidence log, job events, or raw files."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from app.evidence import REDACTED, is_account_path, redact_headers, scrub
from app.jobs import JobContext
from tests.conftest import TEST_KEY_ID, Handler, Stack


def test_redact_headers_masks_auth_and_cookies() -> None:
    redacted = redact_headers(
        {
            "KALSHI-ACCESS-KEY": "abc",
            "kalshi-access-signature": "sig",
            "Kalshi-Access-Timestamp": "1",
            "Set-Cookie": "session=1",
            "Authorization": "Bearer x",
            "Date": "Thu, 01 Oct 2026 07:00:00 GMT",
        }
    )
    assert redacted["Date"] == "Thu, 01 Oct 2026 07:00:00 GMT"
    for name in (
        "KALSHI-ACCESS-KEY",
        "kalshi-access-signature",
        "Kalshi-Access-Timestamp",
        "Set-Cookie",
        "Authorization",
    ):
        assert redacted[name] == REDACTED


def test_scrub_replaces_every_occurrence_and_ignores_empty_secrets() -> None:
    assert scrub("a KEY b KEY", ["KEY", ""]) == f"a {REDACTED} b {REDACTED}"
    assert scrub(None, ["KEY"]) is None


def test_account_paths_are_recognised() -> None:
    assert is_account_path("/portfolio/balance")
    assert is_account_path("/historical/fills")
    assert not is_account_path("/historical/trades")
    assert not is_account_path("/markets/ABC")


async def test_evidence_row_contains_no_secret_material(
    make_stack: Callable[[Handler], Stack], tmp_path: Path
) -> None:
    def echo_key(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"balance": 123, "echo": request.headers["KALSHI-ACCESS-KEY"]},
            headers={"Set-Cookie": "s=1", "X-Echo-Key": request.headers["KALSHI-ACCESS-KEY"]},
        )

    stack = make_stack(echo_key)
    await stack.client.call("GET", "/portfolio/balance", auth=True, store_raw=True)
    signature = stack.sent[0].headers["KALSHI-ACCESS-SIGNATURE"]

    rows = stack.evidence.list_requests()
    serialized = json.dumps(rows)
    assert TEST_KEY_ID not in serialized
    assert signature not in serialized
    assert rows[0]["response_body_sample"] == "[omitted: account-specific response body]"
    assert rows[0]["raw_path"] is None
    assert list((tmp_path / "raw").iterdir()) == []


async def test_public_body_is_sampled_and_raw_saved(
    make_stack: Callable[[Handler], Stack], tmp_path: Path
) -> None:
    stack = make_stack(lambda _: httpx.Response(200, json={"exchange_active": True}))
    await stack.client.call("GET", "/exchange/status", store_raw=True)
    row = stack.evidence.list_requests()[0]
    assert row["response_body_sample"] == '{"exchange_active":true}'
    assert row["raw_path"] is not None
    assert (tmp_path / "raw" / row["raw_path"]).read_text() == '{"exchange_active":true}'


async def test_job_events_and_failure_reasons_are_scrubbed(
    make_stack: Callable[[Handler], Stack],
) -> None:
    stack = make_stack(lambda _: httpx.Response(200))

    async def runner(ctx: JobContext) -> dict[str, str]:
        ctx.log(f"leaking {TEST_KEY_ID}")
        raise RuntimeError(f"boom {TEST_KEY_ID}")

    job_id = stack.jobs.start("M0", "leak_test", {}, runner, max_requests=1)
    events = [event async for event in stack.jobs.subscribe(job_id)]
    assert TEST_KEY_ID not in json.dumps(events)
    assert TEST_KEY_ID not in json.dumps(stack.jobs.get_job(job_id))
