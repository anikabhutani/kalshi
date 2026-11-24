"""Task 7 Part 1, step 6: the Odds API timestamp list and credit estimate (arithmetic only, no API calls).

Every kept swing contributes its before time and its after time. One historical Odds API call returns every
game live at that moment, so entries from different games that would get the same snapshot are merged.

Which snapshot a time gets: the Odds API returns the snapshot at or before the requested time. Its
historical snapshots are taken every 5 minutes and, in our own odds file, land 36-40 seconds after each
5-minute mark (e.g. 15:55:36). Our times are minute ends (10:05:00 = the minute 10:04-10:05), so a time
exactly on a mark gets the previous snapshot. The slot of a time is therefore the 5-minute slot of the
minute's start (time - 60 s, rounded down to 5 minutes), and the request is sent at the earliest time in
the slot. Every entry in the slot then gets the same snapshot (slot + ~37 s), which falls inside each
entry's 5 steady minutes.

Budget: unique requests x 10 credits (one region, one market: h2h). NFL 30,000 credits, college 18,000. If over,
swings are ranked by size (|move| x Kalshi volume in the 10 minutes around t) and the smallest are dropped,
before and after together, until the list fits.

    cd backend && .venv/bin/python -m app.ingame.timestamp_list --league nfl
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd

from app.ingame.swing_data import DATA

CREDITS_PER_CALL = 10
BUDGET = {"ncaaf": 18_000, "nfl": 30_000}
SPORT_KEY = {"ncaaf": "americanfootball_ncaaf", "nfl": "americanfootball_nfl"}
SLOT = 300


def slot_of(ts: np.ndarray) -> np.ndarray:
    return ((ts - 60) // SLOT) * SLOT


def entries(sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in sw.iterrows():
        for kind in ("before", "after"):
            rows.append({"swing_id": r["swing_id"], "kind": kind, "ts": int(r[f"{kind}_ts"])})
    e = pd.DataFrame(rows, columns=["swing_id", "kind", "ts"])
    e["slot"] = slot_of(e["ts"].to_numpy())
    return e


def fit_budget(sw: pd.DataFrame, max_calls: int) -> tuple[pd.DataFrame, list[str]]:
    """Drop the smallest swings until the unique slots fit. Returns the kept swings and the dropped ids."""
    keep = sw.sort_values(["rank_score", "swing_id"], ascending=[False, True]).reset_index(drop=True)
    dropped: list[str] = []
    while len(keep) and entries(keep)["slot"].nunique() > max_calls:
        dropped.append(keep.iloc[-1]["swing_id"])
        keep = keep.iloc[:-1]
    return keep, dropped


def iso(ts: int) -> str:
    return pd.Timestamp(int(ts), unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def run(league: str = "nfl") -> int:
    out = DATA / "ingame" / league / "out"
    path = out / f"swings_{league}.csv"
    if not path.exists():
        print(f"{path} is missing: run app.ingame.swings first.", file=sys.stderr)
        return 2
    sw = pd.read_csv(path)
    # reruns: undo an earlier budget cut before cutting again
    was_budget = sw["drop_reason"].fillna("") == "budget"
    sw.loc[was_budget, ["status", "drop_reason"]] = ["kept", ""]
    kept = sw[sw["status"] == "kept"]
    max_calls = BUDGET[league] // CREDITS_PER_CALL
    before_cut = entries(kept)
    fit, dropped = fit_budget(kept, max_calls)
    sw["drop_reason"] = sw["drop_reason"].fillna("")
    sw.loc[sw["swing_id"].isin(dropped), ["status", "drop_reason"]] = ["dropped", "budget"]
    sw["on_list"] = sw["swing_id"].isin(set(fit["swing_id"]))
    sw.to_csv(path, index=False)

    e = entries(fit)
    lst = (e.groupby("slot")
             .agg(request_ts=("ts", "min"), kinds=("kind", lambda k: "+".join(sorted(set(k)))),
                  swing_ids=("swing_id", lambda s: "|".join(sorted(set(s)))), n_entries=("ts", "size"))
             .reset_index().sort_values("request_ts"))
    lst.insert(0, "request_time_utc", [iso(t) for t in lst["request_ts"]])
    lst.insert(1, "slot_utc", [iso(t) for t in lst["slot"]])
    lst.insert(2, "odds_api_sport", SPORT_KEY[league])
    lst.insert(3, "league", league)
    lst["n_swings"] = lst["swing_ids"].str.count(r"\|") + 1
    lst = lst.drop(columns=["slot"])
    lst.to_csv(out / f"timestamp_list_{league}.csv", index=False)

    by_season = {}
    seasons = sorted(sw["season"].dropna().astype(int).unique()) if "season" in sw else []
    slot_season = e.merge(sw[["swing_id", "season"]], on="swing_id").groupby("slot")["season"].min()
    for yr in seasons:
        k_y = kept[kept["season"] == yr]
        b_y = entries(k_y)
        n_y = int((slot_season == yr).sum())
        by_season[str(yr)] = {
            "swings_kept_before_budget": int(len(k_y)), "entries_before_dedupe": int(len(b_y)),
            "unique_timestamps_before_budget": int(b_y["slot"].nunique()),
            "swings_dropped_for_budget": int(sw.loc[sw["swing_id"].isin(dropped), "season"].eq(yr).sum()),
            "swings_on_list": int((fit["season"] == yr).sum()), "unique_timestamps": n_y,
            "credits": n_y * CREDITS_PER_CALL}
    total = {"swings_kept_before_budget": int(len(kept)), "entries_before_dedupe": int(len(before_cut)),
             "unique_timestamps_before_budget": int(before_cut["slot"].nunique()),
             "credits_before_budget": int(before_cut["slot"].nunique() * CREDITS_PER_CALL),
             "swings_dropped_for_budget": len(dropped), "swings_on_list": int(len(fit)),
             "entries_on_list": int(len(e)), "unique_timestamps": int(len(lst)),
             "credits": int(len(lst) * CREDITS_PER_CALL),
             "calls_shared_by_2plus_swings": int((lst["n_swings"] > 1).sum())}
    est = {"league": league, "credits_per_call": CREDITS_PER_CALL, "budget_credits": BUDGET[league],
           "by_season": by_season, "total": total,
           "assumes": "one region (us) and one market (h2h) per historical call; 10 credits per call"}
    (out / f"credit_estimate_{league}.json").write_text(json.dumps(est, indent=2))
    rows = "".join(f"| {yr} | {v['swings_on_list']} | {v['unique_timestamps']} | {v['credits']:,} | "
                   f"{v['swings_dropped_for_budget']} |\n" for yr, v in by_season.items())
    md = (f"# Credit estimate ({league})\n\n"
          f"| Season | Swings on list | Unique timestamps | Credits | Dropped for budget |\n|---|---|---|---|---|\n"
          f"{rows}| **Total** | {total['swings_on_list']} | {total['unique_timestamps']} | {total['credits']:,} | "
          f"{total['swings_dropped_for_budget']} |\n\n"
          f"Budget {BUDGET[league]:,} credits. Before and after times: {total['entries_on_list']}; calls covering "
          f"2+ swings: {total['calls_shared_by_2plus_swings']}. Assumes {est['assumes']}.\n")
    (out / f"credit_estimate_{league}.md").write_text(md)
    print(md)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Task 7 step 6: Odds API timestamp list and credit estimate")
    ap.add_argument("--league", choices=list(BUDGET), default="nfl")
    a = ap.parse_args(argv)
    return run(a.league)


if __name__ == "__main__":
    raise SystemExit(main())
