"""
Turns raw snapshots from collector.py into two cost tables. Safe to rerun any time:
it rebuilds the CSVs from raw data, so changing a formula never means re-collecting.

  output/taker_costs.csv  HEADLINE comparison: cost to buy now, walking the book if the order
                          is bigger than what's at the best ask
  output/maker_costs.csv  CONTEXT only: best case for a resting order at the best bid, ASSUMES IT FILLS

One row per (snapshot, market side, order size).

Usage:
  python compute_costs.py                          # all raw data, sizes 1 5 10 25 100
  python compute_costs.py --sizes 1 3 10 50        # different order sizes
  python compute_costs.py --day 2026-10-11         # one day only
  python compute_costs.py --no-maker               # skip the maker file
"""

import argparse
import csv
import glob
import json
import math
import os
from decimal import Decimal

TAKER_RATE = Decimal("0.07")
MAKER_RATE = Decimal("0.0175")  # 25% of taker. Check which markets actually charge maker fees.
DEPTH_WINDOW = Decimal("0.05")
RAW_DIR = "raw_snapshots"
OUT_DIR = "output"

COMMON_COLS = [
    "pass_id", "pass_started_utc", "requested_utc", "received_utc",
    "series", "ticker", "event_ticker", "title", "side", "book_status",
    "best_bid", "best_ask", "spread", "mid", "half_spread",
    "size_at_best_bid", "size_at_best_ask",
    "bid_levels", "total_bid_contracts", "bid_depth_5c",
    "ask_levels", "total_ask_contracts", "ask_depth_5c",
    "volume", "open_interest", "order_size",
]
TAKER_COLS = COMMON_COLS + [
    "fill_status", "levels_used", "avg_fill_price", "price_impact",
    "fee_rate", "fee_total", "fee_per_contract",
    "all_in_cost_per_contract", "all_in_cost_pct_of_price",
]
MAKER_COLS = COMMON_COLS + [
    "assumes_fill", "price_posted", "queue_ahead",
    "fee_rate", "fee_total", "fee_per_contract",
    "spread_earned_per_contract", "net_cost_per_contract", "net_cost_pct_of_price",
]


def round_up_cent(x):
    return Decimal(math.ceil(x * 100)) / 100


def depth(levels, best):
    total = Decimal(0)
    for price, count in reversed(levels):
        if best - Decimal(price) <= DEPTH_WINDOW:
            total += Decimal(count)
        else:
            break
    return total


def side_stats(own_bids, other_bids):
    """Book stats for buying one side. The other side's bids are this side's asks (ask = 1 - price)."""
    s = {
        "bid_levels": len(own_bids),
        "total_bid_contracts": sum((Decimal(c) for _, c in own_bids), Decimal(0)),
        "ask_levels": len(other_bids),
        "total_ask_contracts": sum((Decimal(c) for _, c in other_bids), Decimal(0)),
    }
    if not own_bids and not other_bids:
        s["book_status"] = "empty"
    elif not other_bids:
        s["book_status"] = "no_asks"
    elif not own_bids:
        s["book_status"] = "no_bids"
    else:
        s["book_status"] = "ok"
    if own_bids:
        s["best_bid"] = Decimal(own_bids[-1][0])
        s["size_at_best_bid"] = own_bids[-1][1]
        s["bid_depth_5c"] = depth(own_bids, s["best_bid"])
    if other_bids:
        best_other = Decimal(other_bids[-1][0])
        s["best_ask"] = 1 - best_other
        s["size_at_best_ask"] = other_bids[-1][1]
        s["ask_depth_5c"] = depth(other_bids, best_other)
    if s["book_status"] == "ok":
        s["spread"] = s["best_ask"] - s["best_bid"]
        s["mid"] = (s["best_ask"] + s["best_bid"]) / 2
        s["half_spread"] = s["spread"] / 2
    return s


def walk_asks(other_bids, size):
    """
    Buy `size` contracts by taking asks from cheapest up.
    Fee is summed across the levels filled, then rounded up to the cent once for the order.
    Returns None if the book isn't deep enough.
    """
    remaining, cost, raw_fee, used = size, Decimal(0), Decimal(0), 0
    for p, c in reversed(other_bids):  # highest opposite bid = cheapest ask
        price, avail = 1 - Decimal(p), Decimal(c)
        take = min(remaining, avail)
        cost += take * price
        raw_fee += TAKER_RATE * take * price * (1 - price)
        remaining -= take
        used += 1
        if remaining == 0:
            return cost / size, round_up_cent(raw_fee), used
    return None


def taker_row(base, s, other_bids, size):
    row = dict(base, **s, order_size=size, fee_rate=TAKER_RATE)
    if s["book_status"] != "ok":
        row["fill_status"] = s["book_status"]
        return row
    result = walk_asks(other_bids, size)
    if result is None:
        row["fill_status"] = "not_enough_depth"
        return row
    avg, fee, used = result
    per = fee / size
    all_in = (avg - s["mid"]) + per  # = half-spread + price impact + fee
    row.update(fill_status="filled", levels_used=used, avg_fill_price=avg,
               price_impact=avg - s["best_ask"], fee_total=fee, fee_per_contract=per,
               all_in_cost_per_contract=all_in,
               all_in_cost_pct_of_price=round(all_in / avg * 100, 3))
    return row


def maker_row(base, s, size):
    row = dict(base, **s, order_size=size, fee_rate=MAKER_RATE, assumes_fill=True)
    if s["book_status"] != "ok":
        return row
    price = s["best_bid"]
    fee = round_up_cent(MAKER_RATE * size * price * (1 - price))
    per = fee / size
    net = per - s["half_spread"]  # negative = ahead of mid, only if the order actually fills
    row.update(price_posted=price, queue_ahead=s["size_at_best_bid"], fee_total=fee,
               fee_per_contract=per, spread_earned_per_contract=s["half_spread"],
               net_cost_per_contract=net, net_cost_pct_of_price=round(net / price * 100, 3))
    return row


def raw_files(day):
    pattern = os.path.join(RAW_DIR, day or "*", "pass_*.jsonl")
    return sorted(glob.glob(pattern))


def write_csv(path, cols, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="+", type=Decimal, default=[Decimal(x) for x in (1, 5, 10, 25, 100)])
    ap.add_argument("--day", help="only process raw_snapshots/<day>/")
    ap.add_argument("--no-maker", action="store_true")
    args = ap.parse_args()

    files = raw_files(args.day)
    if not files:
        print(f"No raw files found under {RAW_DIR}/. Run collector.py first.")
        return

    taker_rows, maker_rows, skipped = [], [], 0
    for path in files:
        with open(path) as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("error") or not rec.get("orderbook"):
                    skipped += 1
                    continue
                m = rec["market"]
                book = rec["orderbook"].get("orderbook_fp", {})
                yes, no = book.get("yes_dollars") or [], book.get("no_dollars") or []
                base = {k: rec[k] for k in ("pass_id", "pass_started_utc", "requested_utc",
                                            "received_utc", "series", "ticker")}
                base.update(event_ticker=m.get("event_ticker", ""), title=m.get("title", ""),
                            volume=m.get("volume_fp", m.get("volume", "")),
                            open_interest=m.get("open_interest_fp", m.get("open_interest", "")))
                for side, own, other in (("yes", yes, no), ("no", no, yes)):
                    s = side_stats(own, other)
                    b = dict(base, side=side)
                    for size in args.sizes:
                        taker_rows.append(taker_row(b, s, other, size))
                        if not args.no_maker:
                            maker_rows.append(maker_row(b, s, size))

    os.makedirs(OUT_DIR, exist_ok=True)
    write_csv(os.path.join(OUT_DIR, "taker_costs.csv"), TAKER_COLS, taker_rows)
    print(f"{len(files)} raw files, {skipped} snapshots skipped (errors)")
    print(f"Wrote {len(taker_rows)} rows to {OUT_DIR}/taker_costs.csv")
    if not args.no_maker:
        write_csv(os.path.join(OUT_DIR, "maker_costs.csv"), MAKER_COLS, maker_rows)
        print(f"Wrote {len(maker_rows)} rows to {OUT_DIR}/maker_costs.csv")


if __name__ == "__main__":
    main()