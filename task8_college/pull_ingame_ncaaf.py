"""Task 8 Part 1 (college): pull The Odds API historical h2h odds for every timestamp on the Task 7 list.

    python pull_ingame_ncaaf.py              # pull everything not yet on disk
    python pull_ingame_ncaaf.py --limit 5    # pull at most 5 new timestamps (testing)
    python pull_ingame_ncaaf.py --dry-run    # print what would be called and the credit cost, call nothing

Input:  ../task7_college/output/timestamp_list_ncaaf.csv (Task 7, read as is, never edited)
Output: ingame_raw_ncaaf/<YYYYmmddTHHMMSSZ>.json   one raw response per request time
        credit_log_ncaaf.csv                         one row per HTTP call (credits from response headers)

Each call: GET /v4/historical/sports/americanfootball_ncaaf/odds, regions=us, markets=h2h,
bookmakers=fanduel,draftkings, date=<request_time_utc>. Two bookmakers count as one region, so a call costs
10 credits (10 x 1 market x 1 region), confirmed by the first test call (x-requests-last = 10).

Rules:
* A request whose raw file already exists is skipped (no call, no credits).
* Credits remaining is logged after every call.
* Hard stop: before each call, if credits used by this pull + the cost of one more call would exceed
  BUDGET_CREDITS (18,000), stop and print a message to post in the group channel.
* The API key is read from ODDS_API_KEY in task8_college/.env or ../task7_college/.env and never written out.
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
TASK7_OUT = os.path.join(HERE, "..", "task7_college", "output")
TIMESTAMP_LIST = os.path.join(TASK7_OUT, "timestamp_list_ncaaf.csv")
RAW_DIR = os.path.join(HERE, "ingame_raw_ncaaf")
CREDIT_LOG = os.path.join(HERE, "credit_log_ncaaf.csv")

SPORT = "americanfootball_ncaaf"
URL = f"https://api.the-odds-api.com/v4/historical/sports/{SPORT}/odds"
PARAMS = {"regions": "us", "markets": "h2h", "bookmakers": "fanduel,draftkings",
          "oddsFormat": "american", "dateFormat": "iso"}
CREDITS_PER_CALL = 10
BUDGET_CREDITS = 18_000
SLEEP_S = 0.25
MAX_TRIES = 4

LOG_COLS = ["call_n", "called_at_utc", "request_time_utc", "http_status", "credits_last", "credits_used_header",
            "credits_remaining", "credits_this_pull", "snapshot_time_utc", "n_events", "raw_file", "note"]


def load_key():
    for p in (os.path.join(HERE, ".env"), os.path.join(HERE, "..", "task7_college", ".env")):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                if line.strip().startswith("ODDS_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    if os.environ.get("ODDS_API_KEY"):
        return os.environ["ODDS_API_KEY"].strip()
    sys.exit("ODDS_API_KEY not found in task8_college/.env, task7_college/.env or the environment.")


def raw_name(request_time_utc):
    return pd.Timestamp(request_time_utc).strftime("%Y%m%dT%H%M%SZ") + ".json"


def read_log():
    if not os.path.exists(CREDIT_LOG):
        return pd.DataFrame(columns=LOG_COLS)
    return pd.read_csv(CREDIT_LOG)


def append_log(row):
    new = not os.path.exists(CREDIT_LOG)
    with open(CREDIT_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LOG_COLS})


def call(key, request_time_utc):
    """One historical call with retries on 429 / 5xx. Returns (status, headers, json or None)."""
    params = dict(PARAMS, apiKey=key, date=request_time_utc)
    for attempt in range(MAX_TRIES):
        r = requests.get(URL, params=params, timeout=60)
        hdr = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-requests")}
        if r.status_code == 200:
            return r.status_code, hdr, r.json()
        if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_TRIES - 1:
            time.sleep(2 ** attempt * 2)
            continue
        return r.status_code, hdr, {"error_text": r.text[:500]}
    return None, {}, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=None, help="pull at most this many new timestamps")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    ts = pd.read_csv(TIMESTAMP_LIST)
    os.makedirs(RAW_DIR, exist_ok=True)
    todo = [t for t in ts["request_time_utc"] if not os.path.exists(os.path.join(RAW_DIR, raw_name(t)))]
    log = read_log()
    used = int(pd.to_numeric(log["credits_last"], errors="coerce").fillna(0).sum()) if len(log) else 0
    print(f"{len(ts)} timestamps on the list, {len(ts) - len(todo)} already on disk, {len(todo)} to pull. "
          f"Credits used so far by this pull: {used:,}. Worst-case cost of the rest: "
          f"{len(todo) * CREDITS_PER_CALL:,} -> {used + len(todo) * CREDITS_PER_CALL:,} of {BUDGET_CREDITS:,}.")
    if a.dry_run:
        return
    if a.limit is not None:
        todo = todo[:a.limit]

    key = load_key()
    call_n = int(log["call_n"].max()) if len(log) else 0
    for i, t in enumerate(todo, 1):
        if used + CREDITS_PER_CALL > BUDGET_CREDITS:
            print(f"\nHARD STOP: next call would bring college credits to {used + CREDITS_PER_CALL:,} "
                  f"(> {BUDGET_CREDITS:,}). {len(todo) - i + 1} timestamps not pulled. Post in the group channel.")
            sys.exit(2)
        status, hdr, body = call(key, t)
        call_n += 1
        last = int(hdr.get("x-requests-last", 0) or 0)
        used += last
        row = {"call_n": call_n, "called_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "request_time_utc": t, "http_status": status, "credits_last": last,
               "credits_used_header": hdr.get("x-requests-used", ""),
               "credits_remaining": hdr.get("x-requests-remaining", ""), "credits_this_pull": used}
        if status == 200:
            fn = raw_name(t)
            out = {"request": {"url": URL, "params": dict(PARAMS, date=t)}, "headers": hdr, "response": body}
            tmp = os.path.join(RAW_DIR, fn + ".tmp")
            json.dump(out, open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, os.path.join(RAW_DIR, fn))
            row.update(snapshot_time_utc=body.get("timestamp", ""), n_events=len(body.get("data") or []), raw_file=fn)
        else:
            row["note"] = f"error: {json.dumps(body)[:200]}"
        append_log(row)
        print(f"[{i}/{len(todo)}] {t} -> {status} snap={row.get('snapshot_time_utc', '')} "
              f"events={row.get('n_events', '')} credits={last} remaining={row['credits_remaining']} "
              f"pull_total={used:,}", flush=True)
        if status in (401, 403):
            sys.exit("Auth error: check ODDS_API_KEY.")
        if status == 422 or (status != 200 and status not in (429,)):
            pass  # logged; the align step reports requests without a raw file
        time.sleep(SLEEP_S)
    print(f"Done. Credits used by this pull: {used:,} of {BUDGET_CREDITS:,}.")


if __name__ == "__main__":
    main()
