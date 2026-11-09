"""Task 7 Part 1, step 6 (college): the Odds API timestamp list and credit estimate. Arithmetic only, no API
calls. Run after swings.py, with the same flags.

    python timestamp_list.py                    # reads output/swings_ncaaf.csv
    python timestamp_list.py --k-pct 97.5       # reads output/k_p97.5/

Every kept swing contributes its before time and its after time. One historical Odds API call returns every
game live at that moment, so entries (from any game) that would get the same snapshot share one call.

Which snapshot a time gets: the Odds API returns the snapshot at or before the requested time; historical
snapshots are every 5 minutes and, in our odds file, land ~37 s after each 5-minute mark. Our times are minute
ends (10:05:00 = the minute 10:04-10:05), so the slot of a time is the 5-minute slot of the minute's start
(time - 60 s, rounded down to 5 minutes), the same rule as the NFL list. The call is made at the earliest time
in the slot; every entry in the slot then gets the snapshot at slot + ~37 s, which lies inside each entry's 5
steady minutes.

Budget: unique calls x 10 credits <= 18,000. If over, swings are ranked by size (|before -> after move| x Kalshi
volume in the 10 minutes around t) and the smallest are dropped, before and after together, until it fits.
"""

import argparse
import json
import os
import sys

import pandas as pd

import config as C
from common import iso


def slot_of(ts):
    return ((ts - 60) // C.SLOT_S) * C.SLOT_S


def entries(sw):
    rows = [{"swing_id": r.swing_id, "season": r.season, "kind": kind, "ts": int(getattr(r, f"{kind}_ts"))}
            for r in sw.itertuples() for kind in ("before", "after")]
    e = pd.DataFrame(rows, columns=["swing_id", "season", "kind", "ts"])
    e["slot"] = slot_of(e["ts"])
    return e


def fit_budget(sw, max_calls):
    """Drop the smallest swings until the unique slots fit. Returns the kept swings and the dropped ids."""
    keep = sw.sort_values(["rank_score", "swing_id"], ascending=[False, True]).reset_index(drop=True)
    dropped = []
    while len(keep) and entries(keep)["slot"].nunique() > max_calls:
        dropped.append(keep.iloc[-1]["swing_id"])
        keep = keep.iloc[:-1]
    return keep, dropped


def run(k_pct, steady_range):
    out = C.out_dir(k_pct, steady_range)
    path = os.path.join(out, f"swings_{C.LEAGUE}.csv")
    if not os.path.exists(path):
        sys.exit(f"{path} is missing: run swings.py first (same flags).")
    sw = pd.read_csv(path)
    sw["drop_reason"] = sw["drop_reason"].fillna("")
    was_budget = sw["drop_reason"] == "budget"     # rerun: undo an earlier budget cut first
    sw.loc[was_budget, ["status", "drop_reason"]] = ["kept", ""]
    kept = sw[sw["status"] == "kept"]
    max_calls = C.BUDGET_CREDITS // C.CREDITS_PER_CALL
    before_cut = entries(kept)
    fit, dropped = fit_budget(kept, max_calls)
    sw.loc[sw["swing_id"].isin(dropped), ["status", "drop_reason"]] = ["dropped", "budget"]
    sw["on_list"] = sw["swing_id"].isin(set(fit["swing_id"]))
    sw.to_csv(path, index=False)

    e = entries(fit)
    lst = (e.groupby("slot")
             .agg(request_ts=("ts", "min"), season=("season", "min"),
                  kinds=("kind", lambda k: "+".join(sorted(set(k)))),
                  swing_ids=("swing_id", lambda s: "|".join(sorted(set(s)))), n_entries=("ts", "size"))
             .reset_index().sort_values("request_ts"))
    lst.insert(0, "request_time_utc", [iso(t) for t in lst["request_ts"]])
    lst.insert(1, "slot_utc", [iso(t) for t in lst["slot"]])
    lst.insert(2, "odds_api_sport", C.ODDS_SPORT_KEY)
    lst.insert(3, "league", C.LEAGUE)
    lst["n_swings"] = lst["swing_ids"].str.count(r"\|") + 1
    lst = lst.drop(columns=["slot"])
    lst.to_csv(os.path.join(out, f"timestamp_list_{C.LEAGUE}.csv"), index=False)

    by_season = {}
    for yr in C.SEASONS:
        b = entries(kept[kept["season"] == yr])
        n = int((lst["season"] == yr).sum())
        by_season[str(yr)] = {
            "swings_kept_before_budget": int((kept["season"] == yr).sum()), "entries_before_dedupe": int(len(b)),
            "unique_timestamps_before_budget": int(b["slot"].nunique()),
            "swings_dropped_for_budget": int(sw.loc[sw["swing_id"].isin(dropped), "season"].eq(yr).sum()),
            "swings_on_list": int((fit["season"] == yr).sum()), "unique_timestamps": n,
            "credits": n * C.CREDITS_PER_CALL}
    total = {"swings_kept_before_budget": int(len(kept)), "entries_before_dedupe": int(len(before_cut)),
             "unique_timestamps_before_budget": int(before_cut["slot"].nunique()),
             "credits_before_budget": int(before_cut["slot"].nunique() * C.CREDITS_PER_CALL),
             "swings_dropped_for_budget": len(dropped), "swings_on_list": int(len(fit)),
             "entries_on_list": int(len(e)), "unique_timestamps": int(len(lst)),
             "credits": int(len(lst) * C.CREDITS_PER_CALL),
             "calls_shared_by_2plus_swings": int((lst["n_swings"] > 1).sum())}
    est = {"league": C.LEAGUE, "odds_api_sport": C.ODDS_SPORT_KEY, "k": f"p{k_pct:g}",
           "credits_per_call": C.CREDITS_PER_CALL, "budget_credits": C.BUDGET_CREDITS, "by_season": by_season,
           "total": total, "assumes": "one region (us) and one market (h2h) per historical call; 10 credits per call"}
    json.dump(est, open(os.path.join(out, f"credit_estimate_{C.LEAGUE}.json"), "w"), indent=2)
    rows = "".join(f"| {yr} | {v['swings_on_list']} | {v['entries_before_dedupe']} | {v['unique_timestamps']} | "
                   f"{v['credits']:,} | {v['swings_dropped_for_budget']} |\n" for yr, v in by_season.items())
    md = (f"# Credit estimate (college, {C.ODDS_SPORT_KEY}, k = p{k_pct:g})\n\n"
          f"| Season | Swings on list | Before + after times | Unique timestamps | Credits | Dropped for budget |\n"
          f"|---|---|---|---|---|---|\n{rows}"
          f"| **Total** | {total['swings_on_list']} | {total['entries_on_list']} | {total['unique_timestamps']} | "
          f"{total['credits']:,} | {total['swings_dropped_for_budget']} |\n\n"
          f"Budget {C.BUDGET_CREDITS:,} credits. Calls covering 2+ swings: {total['calls_shared_by_2plus_swings']}. "
          f"Assumes {est['assumes']}.\n")
    open(os.path.join(out, f"credit_estimate_{C.LEAGUE}.md"), "w", encoding="utf-8").write(md)
    print(md)


def main():
    ap = argparse.ArgumentParser(description="Task 7 step 6: Odds API timestamp list and credit estimate (college)")
    ap.add_argument("--k-pct", type=float, default=C.K_PCT)
    ap.add_argument("--steady-range", type=float, default=C.STEADY_RANGE)
    a = ap.parse_args()
    run(a.k_pct, a.steady_range)


if __name__ == "__main__":
    main()
