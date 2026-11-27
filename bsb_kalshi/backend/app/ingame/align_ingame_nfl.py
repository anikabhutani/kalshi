"""Task 8 Part 1 (NFL): line up in-game sportsbook prices with Kalshi at every swing's before and after time.

Inputs (data/ingame/nfl/)
- out/timestamp_list_nfl.csv, out/swings_nfl.csv, out/games_nfl.csv, out/kalshi_minutes_nfl_<season>.csv (Task 7)
- task8/ingame_raw_nfl/<request_time>.json: the Odds API historical response for each request on the list
  (sport americanfootball_nfl, regions us, markets h2h, bookmakers draftkings,fanduel, odds american)
- task8/credit_log_nfl.csv
- data/alignment/<season>/costs.csv (Task 5) for the pregame comparison

Where the raw responses come from: the historical endpoint returns the latest snapshot at or before the
requested time. Every in-game snapshot of every game was already pulled (odds_full_pull /
pull_nfl_ingame_odds.py), so `prepare` gives each request on the list exactly the response the API returns
for it: the latest saved snapshot at or before the request time, provided the next saved snapshot is after
it (checked for every request). No new credits are spent; the credit log records the call that fetched
each snapshot.

Definitions (paper shared terms)
- Kalshi: the last 1-minute candle at or before the request time, home market (away flipped), n_med = 24,
  fee 0.07 x n x P x (1-P) rounded up to the cent per order. Cost per $10 = 10 x (1 - mid / (ask + fee)).
- Sportsbook: price implied by its American odds. price_age_min = request time - snapshot time; usable only
  if <= 5 minutes. A book with no h2h line for the event = missing_or_suspended.
- Ruler A: fair = Kalshi midpoint for everyone (headline). Ruler B: fair = the book's own Shin-devigged
  price; Kalshi's cost under it is reported too. Extra cost per $10 = book cost - Kalshi cost, same game,
  team and request time.
- Price group by Kalshi midpoint at that time: longshot < 40, middle 40-60, favorite >= 60.

    cd backend && .venv/bin/python -m app.ingame.align_ingame_nfl prepare --full-raw ../odds_pull/odds_raw
    cd backend && .venv/bin/python -m app.ingame.align_ingame_nfl align
"""

from __future__ import annotations

import argparse
import bisect
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.alignment.costs import fee_dollars
from app.task4.common import REPO_ROOT
from app.task4.sportsbook_costs import shin_two_way

DATA = REPO_ROOT / "data" / "ingame" / "nfl"
T8 = DATA / "task8"
RAW = T8 / "ingame_raw_nfl"
N_MED = 24
STALE_MIN = 5.0
MID_LO, MID_HI = 10.0, 90.0
BOOT, SEED = 2000, 0
BOOKS = {"fanduel": "FanDuel", "draftkings": "DraftKings"}
TEAMS = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def unix(s: str | None) -> int | None:
    if not s or (isinstance(s, float) and np.isnan(s)):
        return None
    return int(datetime.strptime(str(s).replace("Z", "").split(".")[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC).timestamp())


def iso(t: int | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(int(t), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def implied(odds: float) -> float:
    o = float(odds)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def slot(ts: int) -> int:
    return (int(ts) - 60) // 300 * 300


# --------------------------------------------------------------------------------------
# prepare: one raw file per request from the full in-game pull, and the credit log
# --------------------------------------------------------------------------------------

def prepare(full_raw: Path) -> int:
    lst = pd.read_csv(DATA / "out" / "timestamp_list_nfl.csv")
    snaps, log = [], []
    for p in sorted(full_raw.glob("*.json")):
        d = json.loads(p.read_text())
        r = d.get("_request", {})
        snaps.append((unix(d["timestamp"]), p))
        log.append({"raw_file": p.name, "requested_date_utc": r.get("requested_date"), "snapshot_utc": d["timestamp"],
                    "credits_this_call": r.get("requests_last"), "credits_remaining": r.get("requests_remaining")})
    snaps.sort()
    st = [s[0] for s in snaps]
    RAW.mkdir(parents=True, exist_ok=True)
    rows = []
    by_file = {x["raw_file"]: x for x in log}
    for _, r in lst.iterrows():
        R = int(r["request_ts"])
        i = bisect.bisect_right(st, R) - 1
        s_ts, path = snaps[i]
        exact = (R - s_ts) <= 300 and (i + 1 == len(snaps) or snaps[i + 1][0] > R)
        if not exact:
            raise SystemExit(f"{r['request_time_utc']}: no saved snapshot is exactly the API's answer; pull it.")
        dest = RAW / f"{r['request_time_utc'].replace(':', '')}.json"
        shutil.copy(path, dest)
        c = by_file[path.name]
        rows.append({"request_time_utc": r["request_time_utc"], "raw_file": dest.name, "source_file": path.name,
                     "snapshot_utc": c["snapshot_utc"], "pulled_with_request_utc": c["requested_date_utc"],
                     "credits_this_call": c["credits_this_call"], "credits_remaining_after_call": c["credits_remaining"]})
    pd.DataFrame(rows).to_csv(T8 / "credit_log_nfl.csv", index=False)
    full = pd.DataFrame(log)
    full.to_csv(T8 / "credit_log_full_pull.csv", index=False)
    print(f"{len(rows)} requests mapped to saved snapshots; full pull: {len(full)} calls")
    return 0


# --------------------------------------------------------------------------------------
# align
# --------------------------------------------------------------------------------------

def load_inputs() -> dict[str, Any]:
    lst = pd.read_csv(DATA / "out" / "timestamp_list_nfl.csv")
    sw = pd.read_csv(DATA / "out" / "swings_nfl.csv")
    games = pd.read_csv(DATA / "out" / "games_nfl.csv")
    games = games[games["status"] == "used"].set_index("event_ticker")
    kal = {}
    for s in (2025, 2026):
        m = pd.read_csv(DATA / "out" / f"kalshi_minutes_nfl_{s}.csv", low_memory=False)
        for gid, x in m.groupby("game_id"):
            kal[gid] = x.set_index("ts").sort_index()
    return {"list": lst, "swings": sw, "games": games, "kal": kal}


def entries(lst: pd.DataFrame, sw: pd.DataFrame) -> pd.DataFrame:
    """One row per swing x which (before/after) with the request that covers it."""
    on = sw[sw["on_list"] == True].set_index("swing_id")  # noqa: E712
    rows = []
    for _, r in lst.iterrows():
        R = int(r["request_ts"])
        for sid in str(r["swing_ids"]).split("|"):
            s = on.loc[sid]
            for which in ("before", "after"):
                if slot(int(s[f"{which}_ts"])) == slot(R):
                    rows.append({"swing_id": sid, "which": which, "request_ts": R,
                                 "request_time_utc": r["request_time_utc"], "own_time_ts": int(s[f"{which}_ts"])})
    e = pd.DataFrame(rows).drop_duplicates(["swing_id", "which"])
    return e.merge(on.reset_index()[["swing_id", "game_id", "event_ticker", "season", "week", "home", "away", "t_ts",
                                     "abs_move", "size_move", "matched_play"]], on="swing_id", how="left")


def kalshi_side(k: pd.DataFrame, R: int, side: str) -> dict[str, Any] | None:
    pos = k.index.searchsorted(R, side="right") - 1
    if pos < 0:
        return None
    row = k.iloc[pos]
    t = int(k.index[pos])
    if side == "home":
        bid, ask, mid, cost, fee = row["bid"], row["ask"], row["mid"], row["cost_home_per10"], row["fee_home_c"]
    else:
        bid, ask, mid, cost, fee = 100 - row["ask"], 100 - row["bid"], 100 - row["mid"], row["cost_away_per10"], row["fee_away_c"]
    return {"kalshi_candle_time": iso(t), "kalshi_candle_ts": t, "kalshi_bid": bid, "kalshi_ask": ask, "kalshi_mid": mid,
            "kalshi_spread": ask - bid, "kalshi_fee": fee, "kalshi_cost_per10": cost, "kalshi_filled": bool(row["filled"]),
            "kalshi_in_game": bool(row.get("in_game", True))}


def build(inp: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    e = entries(inp["list"], inp["swings"])
    games = inp["games"]
    rows, ev_log = [], []
    raw_cache: dict[str, dict] = {}
    for _, x in e.iterrows():
        f = RAW / f"{x['request_time_utc'].replace(':', '')}.json"
        if f.name not in raw_cache:
            raw_cache[f.name] = json.loads(f.read_text()) if f.exists() else {}
        d = raw_cache[f.name]
        snap_ts = unix(d.get("timestamp"))
        g = games.loc[x["event_ticker"]]
        kick, final = unix(g["kickoff_utc"]), unix(g["final_whistle_utc"])
        cands = [ev for ev in d.get("data") or []
                 if TEAMS.get(ev.get("home_team")) == x["home"] and TEAMS.get(ev.get("away_team")) == x["away"]
                 and abs(unix(ev["commence_time"]) - kick) <= 6 * 3600]
        base = {"game_id": x["game_id"], "season": int(x["season"]), "week": x["week"], "swing_id": x["swing_id"],
                "which": x["which"], "request_time_utc": x["request_time_utc"], "raw_file": f.name,
                "abs_move": x["abs_move"], "matched_play": x["matched_play"], "kickoff_utc": g["kickoff_utc"],
                "swing_t_utc": iso(int(x["t_ts"])),
                "final_whistle_utc": g["final_whistle_utc"],
                "game_in_progress": kick <= x["request_ts"] <= final}
        ev_log.append({"swing_id": x["swing_id"], "which": x["which"], "raw_file": f.name, "has_raw": bool(d),
                       "events_matched": len(cands), "event_id": cands[0]["id"] if len(cands) == 1 else None})
        R = int(x["request_ts"])
        k = inp["kal"].get(x["game_id"])
        for side, team in (("home", x["home"]), ("away", x["away"])):
            ks = kalshi_side(k, R, side) if k is not None else None
            for bk, name in BOOKS.items():
                row = {**base, "team": team, "side": side, "book": name, **(ks or {})}
                reason = ""
                if not d:
                    reason = "no_raw_file"
                elif len(cands) != 1:
                    reason = "event_not_matched" if not cands else "event_matched_twice"
                if not reason:
                    ev = cands[0]
                    row["odds_api_event_id"] = ev["id"]
                    b = next((b for b in ev.get("bookmakers") or [] if b.get("key") == bk), None)
                    mk = next((m for m in (b or {}).get("markets") or [] if m.get("key") == "h2h"), None)
                    if mk is None:
                        reason = "missing_or_suspended"
                    else:
                        oc = {TEAMS.get(o["name"]): o["price"] for o in mk.get("outcomes") or []}
                        row["book_last_update"] = mk.get("last_update") or b.get("last_update")
                        if team not in oc or len(oc) != 2:
                            reason = "one_team_missing"
                        else:
                            other = x["away"] if side == "home" else x["home"]
                            p, q = implied(oc[team]), implied(oc[other])
                            fa, fb, z = shin_two_way(np.array([p]), np.array([q]))
                            row.update({"odds": oc[team], "implied_p": p, "implied_p_other": q, "overround": p + q - 1,
                                        "shin_fair_p": float(fa[0]), "shin_fair_p_other": float(fb[0]), "shin_z": float(z[0])})
                row["book_snapshot_time"] = d.get("timestamp")
                row["price_age_min"] = (R - snap_ts) / 60 if snap_ts else np.nan
                if not reason and ks is None:
                    reason = "no_kalshi_candle"
                if not reason and row["price_age_min"] > STALE_MIN:
                    reason = "stale"
                if not reason and not base["game_in_progress"]:
                    reason = "game_not_in_progress"
                if not reason and ks["kalshi_filled"]:
                    reason = "kalshi_quote_filled"
                if not reason and not (MID_LO <= ks["kalshi_mid"] <= MID_HI):
                    reason = "kalshi_mid_outside_10_90"
                if not reason and np.isnan(row.get("shin_fair_p", np.nan)):
                    reason = "shin_unsolved"
                row["reason_code"] = reason or "ok"
                row["usable"] = not reason
                rows.append(row)
    a = pd.DataFrame(rows)
    # costs
    mid = a["kalshi_mid"] / 100
    paid_k = (a["kalshi_ask"] + a["kalshi_fee"]) / 100
    a["price_group"] = np.select([a["kalshi_mid"] < 40, a["kalshi_mid"] < 60], ["longshot", "middle"], "favorite")
    a.loc[a["kalshi_mid"].isna(), "price_group"] = None
    a["cost_ruler_A"] = 10 * (1 - mid / a["implied_p"])
    a["kalshi_cost_ruler_A"] = a["kalshi_cost_per10"]
    a["cost_ruler_B"] = 10 * (1 - a["shin_fair_p"] / a["implied_p"])
    a["kalshi_cost_ruler_B"] = 10 * (1 - a["shin_fair_p"] / paid_k)
    a["extra_cost_A"] = a["cost_ruler_A"] - a["kalshi_cost_ruler_A"]
    a["extra_cost_B"] = a["cost_ruler_B"] - a["kalshi_cost_ruler_B"]
    # robustness flag (not part of the brief's usable rule): an after-swing book price last updated before the
    # swing minute had not repriced yet, so it compares Kalshi's new price with the book's old one
    lu = a["book_last_update"].map(lambda v: unix(v) if isinstance(v, str) else None)
    tt = a["swing_t_utc"].map(unix)
    a["book_repriced_since_swing"] = [None if w == "before" else (bool(u >= t) if u is not None else None)
                                      for w, u, t in zip(a["which"], lu, tt)]
    # pair usability: swing x book x team usable at both times
    ok = a[a["usable"]].groupby(["swing_id", "book", "team"])["which"].nunique()
    pair_ok = set(ok[ok == 2].index)
    a["pair_usable"] = [(s, b, t) in pair_ok for s, b, t in zip(a["swing_id"], a["book"], a["team"])]
    return a, pd.DataFrame(ev_log), {"entries": len(e)}


# --------------------------------------------------------------------------------------
# summaries
# --------------------------------------------------------------------------------------

def boot(x: pd.DataFrame, col: str, stat=np.nanmedian) -> tuple[float | None, float | None, float | None]:
    x = x.dropna(subset=[col])
    if x.empty:
        return None, None, None
    groups = [v[col].to_numpy() for _, v in x.groupby("game_id")]
    rng = np.random.default_rng(SEED)
    sims = [stat(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])) for _ in range(BOOT)]
    return float(stat(x[col])), float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))


def excluded(a: pd.DataFrame) -> dict[str, int]:
    r = a["reason_code"]
    return {"excluded_stale": int((r == "stale").sum()), "excluded_missing_or_suspended": int(r.isin(
        ["missing_or_suspended", "one_team_missing", "event_not_matched", "no_raw_file"]).sum()),
            "excluded_suspect": int((~r.isin(["ok", "stale", "missing_or_suspended", "one_team_missing",
                                              "event_not_matched", "no_raw_file"])).sum())}


def srow(metric, book, which, group, est, lo, hi, x, a_all, unit="cents per $10", scale=100.0):
    return {"metric": metric, "book": book, "which": which, "group": group,
            "estimate": None if est is None else round(est * scale, 3), "ci_low": None if lo is None else round(lo * scale, 3),
            "ci_high": None if hi is None else round(hi * scale, 3), "unit": unit,
            "distinguishable_from_zero": None if lo is None else bool(lo > 0 or hi < 0),
            "rows": int(len(x)), "games": int(x["game_id"].nunique()) if len(x) else 0, **excluded(a_all)}


def summaries(a: pd.DataFrame) -> pd.DataFrame:
    out = []
    u = a[a["usable"]]
    for name in BOOKS.values():
        for which in ("before", "after"):
            x = u[(u["book"] == name) & (u["which"] == which)]
            al = a[(a["book"] == name) & (a["which"] == which)]
            out.append(srow("extra_cost_A", name, which, "all", *boot(x, "extra_cost_A"), x, al))
            out.append(srow("extra_cost_B", name, which, "all", *boot(x, "extra_cost_B"), x, al))
            out.append(srow("book_cost_A", name, which, "all", *boot(x, "cost_ruler_A"), x, al))
            for grp in ("longshot", "middle", "favorite"):
                y = x[x["price_group"] == grp]
                out.append(srow("extra_cost_A", name, which, f"price_group={grp}", *boot(y, "extra_cost_A"), y,
                                al[al["price_group"] == grp]))
    # Kalshi's own cost (ruler A), per time
    k = u.drop_duplicates(["swing_id", "which", "team"])
    for which in ("before", "after"):
        x = k[k["which"] == which]
        out.append(srow("kalshi_cost_A", "Kalshi", which, "all", *boot(x, "kalshi_cost_ruler_A"), x,
                        a[(a["which"] == which) & (a["book"] == "FanDuel")]))
        for name in BOOKS.values():
            y = u[(u["which"] == which) & (u["book"] == name)]
            out.append(srow(f"kalshi_cost_B_vs_{name}_shin", "Kalshi", which, "all", *boot(y, "kalshi_cost_ruler_B"), y,
                            a[(a["which"] == which) & (a["book"] == name)]))
            out.append(srow("book_cost_B", name, which, "all", *boot(y, "cost_ruler_B"), y,
                            a[(a["which"] == which) & (a["book"] == name)]))
    # swing size terciles (over swings on the list)
    sizes = a.drop_duplicates("swing_id")[["swing_id", "abs_move"]]
    cuts = sizes["abs_move"].quantile([1 / 3, 2 / 3]).to_numpy()
    a["size_tercile"] = np.select([a["abs_move"] <= cuts[0], a["abs_move"] <= cuts[1]], ["small", "medium"], "large")
    u = a[a["usable"]]
    for name in BOOKS.values():
        for which in ("before", "after"):
            for t in ("small", "medium", "large"):
                x = u[(u["book"] == name) & (u["which"] == which) & (u["size_tercile"] == t)]
                out.append(srow("extra_cost_A", name, which, f"swing_size={t} ({'<=' if t != 'large' else '>'}"
                                f"{cuts[0] if t == 'small' else cuts[1]:.1f} pts)" if t != "medium" else
                                f"swing_size=medium ({cuts[0]:.1f}-{cuts[1]:.1f} pts)",
                                *boot(x, "extra_cost_A"), x, a[(a["book"] == name) & (a["which"] == which) &
                                                               (a["size_tercile"] == t)]))
    # share of swing-team-times where Kalshi is the cheapest of the three venues (ruler A; both books usable)
    pv = u.pivot_table(index=["game_id", "swing_id", "which", "team"], columns="book", values="cost_ruler_A")
    kc = u.drop_duplicates(["swing_id", "which", "team"]).set_index(["game_id", "swing_id", "which", "team"])["kalshi_cost_ruler_A"]
    pv = pv.join(kc).dropna().reset_index()
    pv["kalshi_cheapest"] = ((pv["kalshi_cost_ruler_A"] < pv["FanDuel"]) & (pv["kalshi_cost_ruler_A"] < pv["DraftKings"])).astype(float)
    for which in ("before", "after"):
        x = pv[pv["which"] == which]
        out.append(srow("share_kalshi_cheapest", "all three", which, "all", *boot(x, "kalshi_cheapest", np.nanmean), x,
                        a[a["which"] == which], unit="share of swing-team-times", scale=1.0))
        for grp in ("longshot", "middle", "favorite"):
            ids = u[(u["which"] == which) & (u["price_group"] == grp)][["swing_id", "team"]].drop_duplicates()
            y = x.merge(ids, on=["swing_id", "team"])
            out.append(srow("share_kalshi_cheapest", "all three", which, f"price_group={grp}",
                            *boot(y, "kalshi_cheapest", np.nanmean), y, a[a["which"] == which], unit="share", scale=1.0))
    # reprice gap: |change in book Shin fair - change in Kalshi midpoint|, home team, usable pairs (points)
    for name in BOOKS.values():
        h = a[(a["book"] == name) & (a["side"] == "home") & a["pair_usable"]]
        p = h.pivot_table(index=["game_id", "swing_id"], columns="which", values=["shin_fair_p", "kalshi_mid"]).dropna()
        if len(p):
            gap = ((p[("shin_fair_p", "after")] - p[("shin_fair_p", "before")]) * 100
                   - (p[("kalshi_mid", "after")] - p[("kalshi_mid", "before")])).abs().rename("gap").reset_index()
            out.append(srow("reprice_gap_abs", name, "after-before", "all", *boot(gap, "gap"), gap,
                            a[a["book"] == name], unit="points of win probability", scale=1.0))
            kmove = (p[("kalshi_mid", "after")] - p[("kalshi_mid", "before")]).abs().median()
            out.append({"metric": "kalshi_mid_move_abs_median", "book": name, "which": "after-before", "group": "all",
                        "estimate": round(float(kmove), 3), "unit": "points", "rows": int(len(gap)),
                        "games": int(gap["game_id"].nunique())})
    # paired after - before, ruler A
    for name in BOOKS.values():
        x = a[(a["book"] == name) & a["pair_usable"]].pivot_table(index=["game_id", "swing_id", "team"], columns="which",
                                                                   values="extra_cost_A").dropna()
        x = (x["after"] - x["before"]).rename("chg").reset_index()
        out.append(srow("extra_cost_A_after_minus_before", name, "after-before", "pairs", *boot(x, "chg"), x,
                        a[a["book"] == name]))
    # pregame (Task 5) at the kickoff snapshot, ruler A, n_med
    pre = []
    for s in (2025, 2026):
        c = pd.read_csv(REPO_ROOT / "data" / "alignment" / str(s) / "costs.csv", low_memory=False)
        c = c[(c["ruler"] == "A_Kalshi") & (c["checkpoint"] == "close")]
        k = c[(c["venue"] == "Kalshi") & (c["n_label"] == "median")][["game_id", "team", "cost_per_10", "usable", "fair",
                                                                          "unusable_reason"]].rename(
            columns={"cost_per_10": "k_cost", "usable": "k_ok", "unusable_reason": "k_reason"})
        for name in BOOKS.values():
            b = c[c["venue"] == name][["game_id", "team", "cost_per_10", "usable", "unusable_reason"]] \
                .drop_duplicates(["game_id", "team"]).merge(k, on=["game_id", "team"])
            b["book"] = name
            b["extra"] = b["cost_per_10"] - b["k_cost"]
            b["ok"] = b["usable"] & b["k_ok"]
            why = b["unusable_reason"].fillna(b["k_reason"]).fillna("").astype(str)
            b["excl"] = np.where(b["ok"], "", np.where(why.str.contains("old"), "stale",
                                 np.where(why.str.contains("missing|no ", case=False), "missing", "suspect")))
            pre.append(b)
    pre = pd.concat(pre)
    pre["group"] = np.select([pre["fair"] < 0.4, pre["fair"] < 0.6], ["longshot", "middle"], "favorite")
    for name in BOOKS.values():
        pb = pre[pre["book"] == name]
        for grp in ("all", "longshot", "middle", "favorite"):
            al = pb if grp == "all" else pb[pb["group"] == grp]
            x = al[al["ok"]]
            e, lo, hi = boot(x, "extra")
            out.append({"metric": "pregame_extra_cost_A_kickoff", "book": name, "which": "pregame kickoff",
                        "group": "all" if grp == "all" else f"price_group={grp}", "estimate": round(e * 100, 3),
                        "ci_low": round(lo * 100, 3), "ci_high": round(hi * 100, 3), "unit": "cents per $10",
                        "distinguishable_from_zero": bool(lo > 0 or hi < 0), "rows": int(len(x)),
                        "games": int(x["game_id"].nunique()), "excluded_stale": int((al["excl"] == "stale").sum()),
                        "excluded_missing_or_suspended": int((al["excl"] == "missing").sum()),
                        "excluded_suspect": int((al["excl"] == "suspect").sum())})
    # robustness: after-swing rows whose book price was updated after the swing
    for name in BOOKS.values():
        al_b = a[(a["book"] == name) & (a["which"] == "after")]
        for grp in ("all", "longshot", "middle", "favorite"):
            al = al_b if grp == "all" else al_b[al_b["price_group"] == grp]
            x = al[al["usable"] & (al["book_repriced_since_swing"] == True)]  # noqa: E712
            r = srow("extra_cost_A_after_book_repriced_only", name, "after",
                     "all" if grp == "all" else f"price_group={grp}", *boot(x, "extra_cost_A"), x, al)
            r["excluded_not_repriced"] = int((al["usable"] & (al["book_repriced_since_swing"] == False)).sum())  # noqa: E712
            out.append(r)
        rp = a[(a["book"] == name) & a["pair_usable"]]
        bad = set(rp.loc[(rp["which"] == "after") & (rp["book_repriced_since_swing"] == False), "swing_id"])  # noqa: E712
        x = rp[~rp["swing_id"].isin(bad)].pivot_table(index=["game_id", "swing_id", "team"], columns="which",
                                                      values="extra_cost_A").dropna()
        x = (x["after"] - x["before"]).rename("chg").reset_index()
        r = srow("extra_cost_A_after_minus_before_repriced_pairs", name, "after-before", "pairs", *boot(x, "chg"), x,
                 a[a["book"] == name])
        r["excluded_not_repriced"] = int(len(bad))
        out.append(r)
    # 2. pooled before + after (one number per book and price group; used by the savings table)
    for name in BOOKS.values():
        al_b = a[a["book"] == name]
        for grp in ("all", "longshot", "middle", "favorite"):
            al = al_b if grp == "all" else al_b[al_b["price_group"] == grp]
            x = al[al["usable"]]
            out.append(srow("extra_cost_A_pooled_before_after", name, "before+after",
                            "all" if grp == "all" else f"price_group={grp}", *boot(x, "extra_cost_A"), x, al))
    return pd.DataFrame(out)


# --------------------------------------------------------------------------------------
# coverage and checks
# --------------------------------------------------------------------------------------

def coverage(a: pd.DataFrame, ev: pd.DataFrame, n_list_swings: int, n_requests: int) -> pd.DataFrame:
    st = a.groupby(["swing_id", "which"])
    rows = [("swings on the list", n_list_swings), ("requests on the list", n_requests),
            ("requests with a raw file", int(len(list(RAW.glob('*.json'))))),
            ("swing times (swing x before/after)", int(ev[["swing_id", "which"]].drop_duplicates().shape[0])),
            ("swing times with the event matched", int((ev["events_matched"] == 1).sum()))]
    for name in BOOKS.values():
        b = a[a["book"] == name]
        g = b.groupby(["swing_id", "which"])
        present = g["reason_code"].apply(lambda r: not r.isin(["missing_or_suspended", "event_not_matched",
                                                               "no_raw_file"]).any())
        fresh = g["price_age_min"].max() <= STALE_MIN
        both = g["odds"].apply(lambda s: s.notna().sum() == 2)
        usable = g["usable"].all()
        pairs = b[b["pair_usable"]].groupby("swing_id")["team"].nunique()
        rows += [(f"{name}: swing times with the book present", int(present.sum())),
                 (f"{name}: ... and fresh (age <= 5 min)", int((present & fresh).sum())),
                 (f"{name}: ... and both teams priced", int((present & fresh & both).sum())),
                 (f"{name}: ... and usable (all checks)", int(usable.sum())),
                 (f"{name}: swings with a usable before-and-after pair", int((pairs == 2).sum()))]
    for (name, rc), n in a.groupby(["book", "reason_code"]).size().items():
        rows.append((f"reason_code {name}: {rc} (rows)", int(n)))
    return pd.DataFrame(rows, columns=["step", "count"])


def checks(a: pd.DataFrame, ev: pd.DataFrame, sw: pd.DataFrame, lst: pd.DataFrame) -> dict[str, Any]:
    on = sw[sw["on_list"] == True]  # noqa: E712
    cred = pd.read_csv(T8 / "credit_log_nfl.csv")
    full = pd.read_csv(T8 / "credit_log_full_pull.csv")
    raw_names = {p.name for p in RAW.glob("*.json")}
    priced = a[a["odds"].notna()]
    two = a.dropna(subset=["implied_p", "implied_p_other"]).drop_duplicates(["swing_id", "which", "book"])
    snap_after = (a["book_snapshot_time"].map(unix) > a["request_time_utc"].map(unix)).sum()
    cand_after = (a["kalshi_candle_ts"] > a["request_time_utc"].map(unix)).sum()
    fee_re = a.dropna(subset=["kalshi_ask"]).apply(lambda r: fee_dollars(N_MED, r["kalshi_ask"] / 100) / N_MED * 100, axis=1)
    fee_ok = np.isclose(fee_re, a.dropna(subset=["kalshi_ask"])["kalshi_fee"], atol=1e-4)   # file stores 4 decimals
    pairs = a[a["pair_usable"]]
    pair_bad = pairs.groupby(["swing_id", "book", "team"])["usable"].agg(lambda s: s.all() and len(s) == 2)
    ident = []
    for name in BOOKS.values():
        p = a[(a["book"] == name) & (a["side"] == "home") & a["odds"].notna()].pivot_table(
            index="swing_id", columns="which", values=["odds"], aggfunc="first").dropna()
        ident.append({"book": name, "swings_with_both_times": int(len(p)),
                      "identical_home_odds_before_after": int((p[("odds", "before")] == p[("odds", "after")]).sum())})
    events_per_raw = ev.groupby("raw_file")["event_id"].apply(lambda s: s.dropna().tolist())
    ev_dupe = sum(1 for v in events_per_raw for x in set(v) if v.count(x) > 0) - sum(len(set(v)) for v in events_per_raw)
    c = {
        "every_swing_on_list_has_a_request": bool(set(on["swing_id"]) <= set(ev["swing_id"])),
        "swing_times_without_request": int(2 * len(on) - ev[["swing_id", "which"]].drop_duplicates().shape[0]),
        "every_request_has_a_raw_file": bool({r.replace(":", "") + ".json" for r in lst["request_time_utc"]} <= raw_names),
        "credits": {"calls_in_full_pull": int(len(full)), "credits_per_call": sorted(full["credits_this_call"].dropna().unique().tolist()),
                    "credits_used_full_pull": int(full["credits_this_call"].sum()),
                    "remaining_first_call": float(full.sort_values("requested_date_utc")["credits_remaining"].iloc[0]),
                    "remaining_last_call": float(full.sort_values("requested_date_utc")["credits_remaining"].iloc[-1]),
                    "match": bool(full["credits_this_call"].sum() == 10 * len(full)
                                  and full.sort_values("requested_date_utc")["credits_remaining"].iloc[0]
                                  - full.sort_values("requested_date_utc")["credits_remaining"].iloc[-1]
                                  == 10 * (len(full) - 1)),
                    "new_credits_for_this_list": 0, "requests_on_list": int(len(cred))},
        "each_event_matches_one_game": {"swing_times_matched_to_exactly_one_event": int((ev["events_matched"] == 1).sum()),
                                        "matched_to_two_or_more": int((ev["events_matched"] > 1).sum()),
                                        "not_matched": int((ev["events_matched"] == 0).sum())},
        "both_teams_present_for_each_book": {"book_times_with_one_team_missing": int((a["reason_code"] == "one_team_missing").sum())},
        "implied_sum_at_least_1": {"lines": int(len(two)), "below_1": int(((two["implied_p"] + two["implied_p_other"]) < 1).sum())},
        "shin_sums_to_1": {"lines": int(len(priced)), "max_abs_error": float(
            (priced["shin_fair_p"] + priced["shin_fair_p_other"] - 1).abs().max())},
        "book_snapshot_after_request": int(snap_after), "kalshi_candle_after_request": int(cand_after),
        "game_not_in_progress_rows": int((~a["game_in_progress"]).sum()),
        "kalshi_mid_outside_10_90_rows": int(((a["kalshi_mid"] < MID_LO) | (a["kalshi_mid"] > MID_HI)).sum()),
        "fee_recomputed_matches": {"rows": int(len(fee_ok)), "mismatches": int((~fee_ok).sum()),
                                   "tolerance_cents": 1e-4, "note": "fee_calculator.py is not in the repo; recomputed with the Task 5 fee function "
                                           "(0.07 x n x P x (1-P), rounded up to the cent, n = 24)"},
        "duplicate_rows": int(a.duplicated(["swing_id", "which", "team", "book"]).sum()),
        "pairs_with_both_rows_usable": {"pairs": int(len(pair_bad)), "violations": int((~pair_bad).sum())},
        "identical_book_price_before_and_after": ident,
        "after_rows_book_not_repriced_since_swing": {
            b: {"usable_after_rows": int((a["usable"] & (a["which"] == "after") & (a["book"] == b)).sum()),
                "book_last_update_before_swing": int((a["usable"] & (a["which"] == "after") & (a["book"] == b)
                                                      & (a["book_repriced_since_swing"] == False)).sum())}  # noqa: E712
            for b in BOOKS.values()},
        "price_age_min_range": [round(float(a["price_age_min"].min()), 2), round(float(a["price_age_min"].max()), 2)],
        "book_last_update_age_sec_median": float((a["request_time_utc"].map(unix)
                                                  - a["book_last_update"].map(unix)).median()),
    }
    for i in ident:
        share = i["identical_home_odds_before_after"] / max(i["swings_with_both_times"], 1)
        i["share"] = round(share, 4)
        i["flag_possible_pregame_line"] = share > 0.10
    return c


def hand_check(a: pd.DataFrame, n: int = 5) -> str:
    rng = np.random.default_rng(7)
    ids = rng.choice(sorted(a.loc[a["pair_usable"], "swing_id"].unique()), size=n, replace=False)
    lines = ["# Hand-check: 5 swings against the raw Odds API responses", "",
             "For each swing and time: opened the raw response file, found the event by team names, and compared the "
             "snapshot time, each book's American odds for both teams and the market's last update with the aligned "
             "file; recomputed the implied probability and the Kalshi midpoint from bid and ask.", ""]
    all_ok = True
    for sid in ids:
        lines.append(f"## {sid}")
        for which in ("before", "after"):
            x = a[(a["swing_id"] == sid) & (a["which"] == which)]
            f = RAW / x["raw_file"].iloc[0]
            d = json.loads(f.read_text())
            ev = next(e for e in d["data"] if e["id"] == x["odds_api_event_id"].dropna().iloc[0])
            lines.append(f"- **{which}** request {x['request_time_utc'].iloc[0]}, raw file `{f.name}`: snapshot "
                         f"{d['timestamp']} (aligned: {x['book_snapshot_time'].iloc[0]}), event {ev['away_team']} at "
                         f"{ev['home_team']}")
            for bk, name in BOOKS.items():
                mk = next(m for b in ev["bookmakers"] if b["key"] == bk for m in b["markets"] if m["key"] == "h2h")
                raw_odds = {TEAMS[o["name"]]: o["price"] for o in mk["outcomes"]}
                for _, r in x[x["book"] == name].iterrows():
                    ok = (raw_odds[r["team"]] == r["odds"] and abs(implied(r["odds"]) - r["implied_p"]) < 1e-12
                          and abs((r["kalshi_bid"] + r["kalshi_ask"]) / 2 - r["kalshi_mid"]) < 1e-9
                          and d["timestamp"] == r["book_snapshot_time"])
                    all_ok &= ok
                    lines.append(f"  - {name} {r['team']}: raw {raw_odds[r['team']]:+d} vs aligned {int(r['odds']):+d}; "
                                 f"implied {r['implied_p']:.4f}; Kalshi bid/ask {r['kalshi_bid']:.1f}/{r['kalshi_ask']:.1f} "
                                 f"mid {r['kalshi_mid']:.1f}; extra cost A {r['extra_cost_A'] * 100:+.1f}c -> "
                                 f"{'match' if ok else 'MISMATCH'}")
        lines.append("")
    lines.append(f"Result: {'all values match' if all_ok else 'MISMATCHES FOUND (see above)'}.")
    return "\n".join(lines)


def align() -> int:
    inp = load_inputs()
    a, ev, info = build(inp)
    on = inp["swings"][inp["swings"]["on_list"] == True]  # noqa: E712
    cols = ["game_id", "season", "week", "swing_id", "which", "request_time_utc", "kalshi_candle_time", "team", "side",
            "kalshi_bid", "kalshi_ask", "kalshi_mid", "kalshi_spread", "kalshi_fee", "kalshi_cost_per10", "book",
            "odds_api_event_id", "book_snapshot_time", "book_last_update", "price_age_min", "odds", "implied_p",
            "overround", "shin_fair_p", "price_group", "cost_ruler_A", "cost_ruler_B", "kalshi_cost_ruler_A",
            "kalshi_cost_ruler_B", "extra_cost_A", "extra_cost_B", "usable", "reason_code", "pair_usable",
            "swing_t_utc", "book_repriced_since_swing", "abs_move",
            "matched_play", "raw_file"]
    out = a[cols].sort_values(["request_time_utc", "swing_id", "which", "book", "side"])
    num = out.select_dtypes("float").columns
    out[num] = out[num].round(6)
    out.to_csv(T8 / "ingame_aligned_nfl.csv", index=False)
    coverage(a, ev, len(on), len(inp["list"])).to_csv(T8 / "ingame_coverage_nfl.csv", index=False)
    ck = checks(a, ev, inp["swings"], inp["list"])
    (T8 / "ingame_checks_nfl.json").write_text(json.dumps(ck, indent=2, default=str))
    sm = summaries(a)
    sm.to_csv(T8 / "ingame_summary_nfl.csv", index=False)
    (T8 / "hand_check_nfl.md").write_text(hand_check(a))
    print(f"aligned rows {len(out):,} (usable {int(out['usable'].sum()):,}); swings on list {len(on)}")
    print(out["reason_code"].value_counts().to_string())
    print(json.dumps(ck, indent=1, default=str)[:4000])
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_rows", 200):
        print(sm[["metric", "book", "which", "group", "estimate", "ci_low", "ci_high", "rows", "games",
                  "distinguishable_from_zero"]].to_string())
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Task 8: NFL in-game sportsbook alignment")
    ap.add_argument("command", choices=["prepare", "align"])
    ap.add_argument("--full-raw", type=Path, default=REPO_ROOT / "odds_pull" / "odds_raw")
    a = ap.parse_args(argv)
    return prepare(a.full_raw) if a.command == "prepare" else align()


if __name__ == "__main__":
    raise SystemExit(main())
