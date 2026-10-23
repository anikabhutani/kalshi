"""Token bucket: bursts up to capacity, then paces at the refill rate."""

from __future__ import annotations

import time

from app.kalshi_client import TokenBucket


async def test_burst_then_paced() -> None:
    bucket = TokenBucket(rate=20.0, capacity=2)
    start = time.monotonic()
    for _ in range(4):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    assert 0.08 <= elapsed < 0.5
    assert bucket.snapshot()["requests_last_60s"] == 4


async def test_cooldown_blocks_acquire() -> None:
    bucket = TokenBucket(rate=100.0, capacity=5)
    bucket.cooldown(0.15)
    start = time.monotonic()
    await bucket.acquire()
    assert time.monotonic() - start >= 0.14


def test_configure_clamps_tokens() -> None:
    bucket = TokenBucket(rate=1.0, capacity=10)
    bucket.configure(rate=2.0, capacity=3)
    snap = bucket.snapshot()
    assert snap["capacity"] == 3 and snap["tokens"] <= 3 and snap["rate_per_s"] == 2.0
