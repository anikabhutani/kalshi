"""
Kalshi API exploration script.

Market data endpoints are public, so this runs with no API key.
Steps:
  1. Find football-related series
  2. List open markets in one series
  3. Read one market's orderbook and compute spread + fee
  4. Pull recent trades for that market
Every raw response is saved to ./raw_explore/ so you can open the JSON and see all fields.

Usage:
  python explore_kalshi.py                 # discover series, then explore the first match
  python explore_kalshi.py --series KXNFLGAME   # skip discovery, use a series you already know
"""

import argparse
import json
import math
import os
import time
from decimal import Decimal

import requests

BASE = "https://external-api.kalshi.com/trade-api/v2"
# If that host gives you trouble, the older host also serves all markets:
# BASE = "https://api.elections.kalshi.com/trade-api/v2"

OUT = "raw_explore"
os.makedirs(OUT, exist_ok=True)


from urllib.parse import urlparse

from kalshi_auth import auth_enabled, auth_headers

API_PREFIX = urlparse(BASE).path  # "/trade-api/v2", needed for signing


def get(path, params=None):
    headers = auth_headers("GET", API_PREFIX + path)
    r = requests.get(BASE + path, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    time.sleep(0.2)  # stay well under rate limits while exploring
    return r.json()


def save(name, data):
    with open(os.path.join(OUT, name + ".json"), "w") as f:
        json.dump(data, f, indent=2)


def find_football_series():
    data = get("/series", {"category": "Sports"})
    save("series_sports", data)
    hits = []
    for s in data.get("series", []):
        title = (s.get("title") or "").lower()
        if "nfl" in title or "football" in title or "pro football" in title:
            hits.append(s)
    print(f"\nFound {len(hits)} football series:")
    for s in hits:
        print(f"  {s['ticker']:<25} {s.get('title')}")
    return hits


def list_markets(series_ticker):
    markets, cursor = [], None
    while True:
        params = {"series_ticker": series_ticker, "status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = get("/markets", params)
        markets += data.get("markets", [])
        cursor = data.get("cursor")
        if not cursor:
            break
    save(f"markets_{series_ticker}", {"markets": markets})
    print(f"\n{len(markets)} open markets in {series_ticker}:")
    for m in markets[:15]:
        print(f"  {m['ticker']:<40} vol={m.get('volume_fp', m.get('volume'))}  {m.get('title')}")
    if len(markets) > 15:
        print(f"  ... and {len(markets) - 15} more (see {OUT}/markets_{series_ticker}.json)")
    return markets


def kalshi_fee(price, contracts, rate=Decimal("0.07")):
    """Taker fee: rate * C * P * (1 - P), rounded up to the cent. Check against the live fee schedule."""
    raw = rate * contracts * price * (1 - price)
    return Decimal(math.ceil(raw * 100)) / 100


def read_orderbook(ticker):
    data = get(f"/markets/{ticker}/orderbook")
    save(f"orderbook_{ticker}", data)
    ob = data.get("orderbook_fp", {})
    yes, no = ob.get("yes_dollars") or [], ob.get("no_dollars") or []
    print(f"\nOrderbook for {ticker}: {len(yes)} YES bid levels, {len(no)} NO bid levels")
    if not yes or not no:
        print("  One side is empty, so there's no two-sided spread right now.")
        return
    best_yes_bid = Decimal(yes[-1][0])          # arrays are ascending, best is last
    best_yes_ask = 1 - Decimal(no[-1][0])       # YES ask is implied by the best NO bid
    spread = best_yes_ask - best_yes_bid
    mid = (best_yes_bid + best_yes_ask) / 2
    print(f"  Best YES bid {best_yes_bid}  (size {yes[-1][1]})")
    print(f"  Best YES ask {best_yes_ask}  (size {no[-1][1]})")
    print(f"  Spread {spread}   Mid {mid}   Half-spread {spread / 2}")
    fee_100 = kalshi_fee(best_yes_ask, Decimal(100))
    print(f"  Taker fee to buy 100 YES at the ask: ${fee_100} "
          f"(${fee_100 / 100:.4f} per contract)")
    print(f"  All-in cost per contract vs mid: {spread / 2 + fee_100 / 100:.4f}")


def recent_trades(ticker):
    data = get("/markets/trades", {"ticker": ticker, "limit": 20})
    save(f"trades_{ticker}", data)
    trades = data.get("trades", [])
    print(f"\nLast {len(trades)} trades on {ticker}:")
    for t in trades[:10]:
        print(f"  {t.get('created_time')}  yes={t.get('yes_price_dollars', t.get('yes_price'))}"
              f"  count={t.get('count_fp', t.get('count'))}  taker={t.get('taker_side')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", help="series ticker to explore, skips discovery")
    args = ap.parse_args()

    if auth_enabled():
        bal = get("/portfolio/balance")
        print(f"Key works. Signed in, balance response: {bal}")
    else:
        print("No key set, using public endpoints only.")

    series = args.series
    if not series:
        hits = find_football_series()
        if not hits:
            print("No football series matched. Open raw_explore/series_sports.json and pick one.")
            return
        series = hits[0]["ticker"]

    markets = list_markets(series)
    if not markets:
        print("No open markets. Try another series from the list above.")
        return

    # Pick the most traded open market so the orderbook is interesting
    def vol(m):
        return float(m.get("volume_fp") or m.get("volume") or 0)
    top = max(markets, key=vol)
    read_orderbook(top["ticker"])
    recent_trades(top["ticker"])
    print(f"\nRaw JSON saved in ./{OUT}/. Open those files to see every field the API returns.")


if __name__ == "__main__":
    main()