"""
Continuous Kalshi orderbook collector. Saves RAW data only; costs are computed later by compute_costs.py.

Every pass:
  1. Lists open markets in each series
  2. Pulls every orderbook in parallel (rate limited), so a pass finishes fast
  3. Writes one JSONL file: raw_snapshots/YYYY-MM-DD/pass_HHMMSS.jsonl
     Each line = one market, with its own request/response timestamps and the pass it belongs to
Then it waits until the next interval and repeats. Errors are logged, and the loop keeps going.

Usage:
  python collector.py --once                 # one pass, then exit (good for testing)
  python collector.py                        # run forever, every 5 minutes
  python collector.py --interval 120 --rps 8 # every 2 minutes, up to 8 requests/second
"""

import argparse
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from kalshi_auth import auth_enabled, auth_headers

BASE = "https://external-api.kalshi.com/trade-api/v2"
API_PREFIX = urlparse(BASE).path
DEFAULT_SERIES = ["KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL"]
RAW_DIR = "raw_snapshots"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("collector.log"), logging.StreamHandler()],
)
log = logging.getLogger("collector")


def now_utc():
    return datetime.now(timezone.utc).isoformat()


class RateLimiter:
    """Spaces requests evenly so all threads together stay under `rps` requests per second."""

    def __init__(self, rps):
        self.interval = 1.0 / rps
        self.lock = threading.Lock()
        self.next_time = time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_time)
            self.next_time = slot + self.interval
        time.sleep(max(0.0, slot - now))


_local = threading.local()


def session():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def fetch(limiter, path, params=None, retries=5):
    for attempt in range(retries):
        limiter.wait()
        try:
            r = session().get(BASE + path, params=params,
                              headers=auth_headers("GET", API_PREFIX + path), timeout=15)
        except requests.RequestException as e:
            log.warning(f"network error on {path}: {e}")
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            log.warning(f"{r.status_code} on {path}, backing off")
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"gave up on {path} after {retries} tries")


def open_markets(limiter, series):
    markets, cursor = [], None
    while True:
        params = {"series_ticker": series, "status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = fetch(limiter, "/markets", params)
        markets += [dict(m, _series=series) for m in data.get("markets", [])]
        cursor = data.get("cursor")
        if not cursor:
            return markets


def snapshot(limiter, pass_id, pass_started, m):
    ticker = m["ticker"]
    requested = now_utc()
    try:
        ob = fetch(limiter, f"/markets/{ticker}/orderbook")
        error = None
    except Exception as e:
        ob, error = None, str(e)
    return {
        "pass_id": pass_id,
        "pass_started_utc": pass_started,
        "requested_utc": requested,
        "received_utc": now_utc(),
        "series": m["_series"],
        "ticker": ticker,
        "market": {k: v for k, v in m.items() if k != "_series"},  # full market record, as listed
        "orderbook": ob,
        "error": error,
    }


def run_pass(limiter, series_list, workers):
    started = datetime.now(timezone.utc)
    pass_id = started.strftime("%Y%m%dT%H%M%SZ")
    t0 = time.monotonic()

    markets = []
    for s in series_list:
        markets += open_markets(limiter, s)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(lambda m: snapshot(limiter, pass_id, started.isoformat(), m), markets))

    day_dir = os.path.join(RAW_DIR, started.strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, f"pass_{started.strftime('%H%M%S')}.jsonl")
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    errors = sum(1 for r in records if r["error"])
    secs = time.monotonic() - t0
    log.info(f"pass {pass_id}: {len(records)} markets, {errors} errors, {secs:.1f}s -> {path}")
    return secs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", nargs="+", default=DEFAULT_SERIES)
    ap.add_argument("--interval", type=int, default=300, help="seconds between pass starts")
    ap.add_argument("--rps", type=float, default=5, help="max requests per second, all threads combined")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    log.info(f"starting: series={args.series} interval={args.interval}s rps={args.rps} "
             f"auth={'on' if auth_enabled() else 'off'}")
    limiter = RateLimiter(args.rps)

    while True:
        start = time.monotonic()
        try:
            secs = run_pass(limiter, args.series, args.workers)
            if secs > args.interval:
                log.warning(f"pass took {secs:.0f}s, longer than the {args.interval}s interval. "
                            f"Raise --rps (if your tier allows) or --interval.")
        except Exception:
            log.exception("pass failed, will retry next interval")
        if args.once:
            break
        time.sleep(max(0, args.interval - (time.monotonic() - start)))


if __name__ == "__main__":
    main()