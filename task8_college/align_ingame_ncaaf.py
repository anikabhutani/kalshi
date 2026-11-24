"""Task 8 Part 1 (college): line up in-game FanDuel / DraftKings moneylines with Kalshi at every swing's before
and after time, then checks, coverage and summaries.

    python align_ingame_ncaaf.py            # after pull_ingame_ncaaf.py

Inputs
- ../task7_college/output/: timestamp_list_ncaaf.csv, swings_ncaaf.csv, games_ncaaf.csv,
  kalshi_minutes_ncaaf_<season>.csv (Task 7, read only)
- ../task7_college/data/<season>/crosswalk.csv: Kalshi event ticker <-> CollegeFootballData game_id and the two
  Kalshi team tickers (Task 7)
- ingame_raw_ncaaf/*.json and credit_log_ncaaf.csv (pull_ingame_ncaaf.py)
- inputs/task5_ncaaf/<season>/{crosswalk.csv, team_table.csv, costs.csv.gz}: the Task 5 college alignment
  (branch origin/abhi-bsb-kalshi, output/alignment/ncaaf/). Extracted with `git show` on first run.

Outputs (output/)
- ingame_aligned_ncaaf.csv   one row per swing x which (before/after) x team x book
- ingame_coverage_ncaaf.csv  the funnel and a count for every reason code
- ingame_checks_ncaaf.json   the checks in the task doc
- ingame_summary_ncaaf.csv   every summary, medians with 95% bootstrap intervals that resample games
- hand_check_ncaaf.md        worksheet: 5 swings, raw response values next to the aligned values

Definitions (paper shared terms, the same as align_ingame_nfl.py so the leagues sit side by side)
- Request time = the time the Odds API was asked for (timestamp list). Several swing times in the same 5-minute
  slot share one request; each row also keeps the swing's own before/after time (own_time_utc).
- Kalshi: the minute-table row at the request time (= the last candle at or before it; Task 7 minute table, home
  market with the away team flipped, or the away market flipped when the home market is thin). kalshi_candle_time
  is the last minute at or before the request with a new candle on that market. Fee from the Task 7 fee function
  at n_med (2025: 50, 2026: 24). Cost per $10 = 10 x (1 - mid / (ask + fee)).
- Sportsbook: price paid = probability implied by American odds. price_age_min = request time - snapshot time.
  Usable only if <= 5 min. No h2h market for the book on the event = missing_or_suspended.
- Ruler A: fair = Kalshi midpoint (headline). Ruler B: fair = the book's own Shin price; Kalshi's cost under it too.
- extra_cost_A = book cost_ruler_A - Kalshi cost (ruler A); same game, team and request time.
- Price group by Kalshi midpoint: longshot < 40, middle 40-60, favorite >= 60.

Event matching (Task 5 crosswalk logic, college team mapping), first rule that finds a candidate wins:
1. task5_crosswalk: the Odds API event id is the Task 5 college game_id, which Task 5 matched to a Kalshi event.
2. team_table: both Kalshi team codes (from the Task 7 team tickers) map through the Task 5 learned team table
   (Kalshi code -> feed name) to the event's two team names, commence time within 12 h of kickoff.
3. cfbd_name: both CollegeFootballData school names score >= 0.75 against the feed names (Task 7 name_score,
   mascot dropped), commence time within 12 h of kickoff.
"""

import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
T7 = os.path.join(HERE, "..", "task7_college")
sys.path.insert(0, T7)
import config as C7  # noqa: E402  (Task 7 config: N_MED, fee multiplier)
from common import fee_dollars, name_score  # noqa: E402  (Task 7 fee function and CFBD name matching)

T7_OUT = os.path.join(T7, "output")
RAW = os.path.join(HERE, "ingame_raw_ncaaf")
CREDIT_LOG = os.path.join(HERE, "credit_log_ncaaf.csv")
T5 = os.path.join(HERE, "inputs", "task5_ncaaf")
OUT = os.path.join(HERE, "output")
T5_BRANCH = "origin/abhi-bsb-kalshi"
SEASONS = (2025, 2026)
LEAGUE = "ncaaf"

STALE_MIN = 5.0
MID_LO, MID_HI = 10.0, 90.0
MATCH_WINDOW_S = 12 * 3600
NAME_MIN = 0.75
BOOT, SEED = 2000, 0
IDENTICAL_FLAG_SHARE = 0.10
BOOKS = {"fanduel": "FanDuel", "draftkings": "DraftKings"}
MISSING_CODES = ("no_raw_file", "event_not_matched", "event_matched_twice", "missing_or_suspended",
                 "one_team_missing")


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

def unix(s):
    if s is None or (isinstance(s, float) and np.isnan(s)) or s == "":
        return None
    return int(pd.Timestamp(s).timestamp())


def iso(t):
    return None if t is None else pd.Timestamp(int(t), unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def implied(odds):
    o = float(odds)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def shin_two_way(p_a, p_b, iterations=80):
    """Shin fair probabilities for a two-way line (Task 5, app/task4/sportsbook_costs.py, copied unchanged)."""
    p_a, p_b = np.asarray(p_a, dtype=float), np.asarray(p_b, dtype=float)
    total = p_a + p_b

    def fair(z, p):
        return (np.sqrt(z ** 2 + 4 * (1 - z) * p ** 2 / total) - z) / (2 * (1 - z))

    lo, hi = np.zeros_like(total), np.full_like(total, 0.5)
    for _ in range(iterations):
        z = (lo + hi) / 2
        too_low = fair(z, p_a) + fair(z, p_b) < 1
        hi = np.where(too_low, z, hi)
        lo = np.where(too_low, lo, z)
    z = (lo + hi) / 2
    fa, fb = fair(z, p_a), fair(z, p_b)
    unsolved = ~(np.abs(fa + fb - 1) < 1e-9)
    fa, fb, z = (np.where(unsolved, np.nan, x) for x in (fa, fb, z))
    return fa, fb, z


def slot(ts):
    return (int(ts) - 60) // 300 * 300


def raw_name(request_time_utc):
    return pd.Timestamp(request_time_utc).strftime("%Y%m%dT%H%M%SZ") + ".json"


def kfee_cents(ask_c, season):
    """Fee per contract in cents, Task 7 fee function at n_med for the season."""
    n = C7.N_MED[int(season)]
    return fee_dollars(n, ask_c / 100, C7.FEE_MULTIPLIER[int(season)]) / n * 100


def name_vs_feed(cfbd_name, feed_name):
    """Best Task 7 name_score of a CFBD school against the feed name with 0, 1 or 2 trailing (mascot) words cut."""
    w = str(feed_name).split()
    return max(name_score(cfbd_name, " ".join(w[:len(w) - k])) for k in range(0, min(3, len(w))))


# --------------------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------------------

def ensure_task5():
    for s in SEASONS:
        for f in ("crosswalk.csv", "team_table.csv", "costs.csv.gz"):
            dest = os.path.join(T5, str(s), f)
            if os.path.exists(dest):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            blob = subprocess.run(["git", "show", f"{T5_BRANCH}:output/alignment/ncaaf/{s}/{f}"], cwd=HERE,
                                  capture_output=True, check=True).stdout
            open(dest, "wb").write(blob)


def load():
    ensure_task5()
    lst = pd.read_csv(os.path.join(T7_OUT, f"timestamp_list_{LEAGUE}.csv"))
    sw = pd.read_csv(os.path.join(T7_OUT, f"swings_{LEAGUE}.csv"))
    games = pd.read_csv(os.path.join(T7_OUT, f"games_{LEAGUE}.csv"))
    games = games[games["status"] == "used"].set_index("event_ticker")
    xw7 = pd.concat([pd.read_csv(os.path.join(T7, "data", str(s), "crosswalk.csv")) for s in SEASONS])
    xw7 = xw7.drop_duplicates("event_ticker").set_index("event_ticker")
    kal = {}
    for s in SEASONS:
        m = pd.read_csv(os.path.join(T7_OUT, f"kalshi_minutes_{LEAGUE}_{s}.csv"), low_memory=False)
        for et, x in m.groupby("event_ticker"):
            kal[et] = x.set_index("ts").sort_index()
    xw5 = pd.concat([pd.read_csv(os.path.join(T5, str(s), "crosswalk.csv")) for s in SEASONS])
    xw5 = xw5[xw5["status"] == "matched"]
    tt = pd.concat([pd.read_csv(os.path.join(T5, str(s), "team_table.csv")) for s in SEASONS])
    code_to_feed = tt.drop_duplicates("kalshi_code").set_index("kalshi_code")["feed_name"].to_dict()
    return {"list": lst, "swings": sw, "games": games, "xw7": xw7, "kal": kal, "xw5": xw5,
            "code_to_feed": code_to_feed}


def entries(lst, sw):
    """One row per swing x which with the request that covers it."""
    on = sw[sw["on_list"] == True].set_index("swing_id")  # noqa: E712
    rows = []
    for r in lst.itertuples():
        R = int(r.request_ts)
        for sid in str(r.swing_ids).split("|"):
            s = on.loc[sid]
            for which in ("before", "after"):
                own = int(s[f"{which}_ts"])
                if slot(own) == slot(R):
                    rows.append({"swing_id": sid, "which": which, "request_ts": R,
                                 "request_time_utc": r.request_time_utc, "own_time_ts": own})
    e = pd.DataFrame(rows).drop_duplicates(["swing_id", "which"])
    keep = ["swing_id", "game_id", "event_ticker", "season", "week", "home", "away", "t_ts", "abs_move",
            "size_move", "matched_play"]
    return e.merge(on.reset_index()[keep], on="swing_id", how="left")


# --------------------------------------------------------------------------------------
# event matching
# --------------------------------------------------------------------------------------

def dedupe_events(events):
    """The API sometimes lists one event id twice in a snapshot (same teams and kickoff; usually the same odds with a
    different last_update, occasionally a different price). Merge them: one event per id, and for each book the copy
    with the latest market last_update (the most recent price at the snapshot)."""
    by = {}
    for e in events:
        if e["id"] not in by:
            by[e["id"]] = dict(e, bookmakers=list(e.get("bookmakers") or []))
            continue
        cur = {b["key"]: b for b in by[e["id"]]["bookmakers"]}
        for b in e.get("bookmakers") or []:
            lu = max((m.get("last_update") or "" for m in b.get("markets") or []), default="")
            old = cur.get(b["key"])
            old_lu = max((m.get("last_update") or "" for m in (old or {}).get("markets") or []), default="")
            if old is None or lu > old_lu:
                cur[b["key"]] = b
        by[e["id"]]["bookmakers"] = list(cur.values())
    return list(by.values())


def duplicate_event_stats():
    files = dups = diff_price = 0
    for f in sorted(os.listdir(RAW)):
        if not f.endswith(".json"):
            continue
        data = json.load(open(os.path.join(RAW, f), encoding="utf-8"))["response"].get("data") or []
        seen, had = {}, False
        for e in data:
            seen.setdefault(e["id"], []).append(e)
        for copies in seen.values():
            if len(copies) > 1:
                dups += 1
                had = True
                prices = {json.dumps(sorted((b["key"], [o["price"] for o in b["markets"][0]["outcomes"]])
                                            for b in c.get("bookmakers") or [] if b.get("markets"))) for c in copies}
                diff_price += len(prices) > 1
        files += had
    return {"raw_files_with_duplicate_event_ids": files, "duplicated_event_ids": dups,
            "duplicates_with_different_prices": diff_price,
            "rule": "merged by event id; each book takes the copy with the latest market last_update"}


def match_event(events, et, g, inp):
    """Returns (candidate events, method, {feed name: 'home'/'away'})."""
    kick = unix(g["kickoff_utc"])
    near = [e for e in events if abs(unix(e["commence_time"]) - kick) <= MATCH_WINDOW_S]
    x7 = inp["xw7"].loc[et]
    code_h, code_a = str(x7["ticker_home"]).rsplit("-", 1)[1], str(x7["ticker_away"]).rsplit("-", 1)[1]

    # 1. Task 5 crosswalk (event id -> Kalshi event)
    x5 = inp["xw5"][inp["xw5"]["kalshi_event_ticker"] == et]
    ids = set(x5["game_id"])
    c = [e for e in events if e["id"] in ids]
    if c:
        side = {}
        for r in x5.itertuples():
            for feed, code in ((r.home, r.kalshi_code_home), (r.away, r.kalshi_code_away)):
                side[feed] = "home" if code == code_h else ("away" if code == code_a else None)
        return c, "task5_crosswalk", side

    # 2. learned team table (Kalshi code -> feed name)
    fh, fa = inp["code_to_feed"].get(code_h), inp["code_to_feed"].get(code_a)
    if fh and fa:
        c = [e for e in near if {e["home_team"], e["away_team"]} == {fh, fa}]
        if c:
            return c, "team_table", {fh: "home", fa: "away"}

    # 3. CollegeFootballData names against feed names
    c, side = [], {}
    for e in near:
        straight = min(name_vs_feed(g["home"], e["home_team"]), name_vs_feed(g["away"], e["away_team"]))
        flipped = min(name_vs_feed(g["home"], e["away_team"]), name_vs_feed(g["away"], e["home_team"]))
        if max(straight, flipped) >= NAME_MIN:
            c.append(e)
            if straight >= flipped:
                side.update({e["home_team"]: "home", e["away_team"]: "away"})
            else:
                side.update({e["away_team"]: "home", e["home_team"]: "away"})
    return c, ("cfbd_name" if c else "none"), side


# --------------------------------------------------------------------------------------
# build aligned rows
# --------------------------------------------------------------------------------------

def kalshi_side(k, R, side):
    pos = k.index.searchsorted(R, side="right") - 1
    if pos < 0:
        return None
    row = k.iloc[pos]
    upto = k.iloc[:pos + 1]
    nc = upto.index[upto["new_candle"].astype(bool).to_numpy()]
    candle_t = int(nc[-1]) if len(nc) else None
    if side == "home":
        bid, ask, mid, cost, fee = row["bid"], row["ask"], row["mid"], row["cost_home_per10"], row["fee_home_c"]
    else:
        bid, ask, mid = 100 - row["ask"], 100 - row["bid"], 100 - row["mid"]
        cost, fee = row["cost_away_per10"], row["fee_away_c"]
    return {"kalshi_minute_ts": int(k.index[pos]), "kalshi_candle_time": iso(candle_t), "kalshi_candle_ts": candle_t,
            "kalshi_bid": bid, "kalshi_ask": ask, "kalshi_mid": mid, "kalshi_spread": ask - bid, "kalshi_fee": fee,
            "kalshi_cost_per10": cost, "kalshi_filled": bool(row["filled"]), "kalshi_source_market": row["source_market"]}


def build(inp):
    e = entries(inp["list"], inp["swings"])
    games = inp["games"]
    rows, ev_log, cache = [], [], {}
    for x in e.to_dict("records"):
        fn = raw_name(x["request_time_utc"])
        if fn not in cache:
            p = os.path.join(RAW, fn)
            cache[fn] = json.load(open(p, encoding="utf-8"))["response"] if os.path.exists(p) else {}
            if cache[fn]:
                cache[fn]["data"] = dedupe_events(cache[fn].get("data") or [])
        d = cache[fn]
        snap_ts = unix(d.get("timestamp"))
        et = x["event_ticker"]
        g = games.loc[et]
        kick, final = unix(g["kickoff_utc"]), unix(g["final_whistle_utc"])
        R = int(x["request_ts"])
        cands, method, side_of = match_event(d.get("data") or [], et, g, inp) if d else ([], "no_raw_file", {})
        base = {"game_id": int(x["game_id"]), "season": int(x["season"]), "week": x["week"],
                "event_ticker": et, "swing_id": x["swing_id"], "which": x["which"],
                "request_time_utc": x["request_time_utc"], "own_time_utc": iso(x["own_time_ts"]), "raw_file": fn,
                "abs_move": x["abs_move"], "matched_play": x["matched_play"], "kickoff_utc": g["kickoff_utc"],
                "final_whistle_utc": g["final_whistle_utc"], "game_in_progress": bool(kick <= R <= final),
                "match_method": method}
        ev_log.append({"swing_id": x["swing_id"], "which": x["which"], "game_id": base["game_id"], "raw_file": fn,
                       "has_raw": bool(d), "events_matched": len(cands), "match_method": method,
                       "event_id": cands[0]["id"] if len(cands) == 1 else None})
        k = inp["kal"].get(et)
        teams = {"home": x["home"], "away": x["away"]}
        for side in ("home", "away"):
            ks = kalshi_side(k, R, side) if k is not None else None
            for bk, name in BOOKS.items():
                row = {**base, "team": teams[side], "side": side, "book": name, **(ks or {})}
                reason = ""
                if not d:
                    reason = "no_raw_file"
                elif len(cands) != 1:
                    reason = "event_not_matched" if not cands else "event_matched_twice"
                if not reason:
                    ev = cands[0]
                    row["odds_api_event_id"] = ev["id"]
                    row["odds_api_teams"] = f"{ev['away_team']} @ {ev['home_team']}"
                    b = next((b for b in ev.get("bookmakers") or [] if b.get("key") == bk), None)
                    mk = next((m for m in (b or {}).get("markets") or [] if m.get("key") == "h2h"), None)
                    if mk is None:
                        reason = "missing_or_suspended"
                    else:
                        row["book_last_update"] = mk.get("last_update") or b.get("last_update")
                        oc = {side_of.get(o["name"]): o["price"] for o in mk.get("outcomes") or []}
                        if side not in oc or len(oc) != 2 or None in oc:
                            reason = "one_team_missing"
                        else:
                            other = "away" if side == "home" else "home"
                            p, q = implied(oc[side]), implied(oc[other])
                            fa, fb, z = shin_two_way([p], [q])
                            row.update({"odds": oc[side], "odds_other": oc[other], "implied_p": p, "implied_p_other": q,
                                        "overround": p + q - 1, "shin_fair_p": float(fa[0]),
                                        "shin_fair_p_other": float(fb[0]), "shin_z": float(z[0])})
                row["book_snapshot_time"] = d.get("timestamp")
                row["price_age_min"] = (R - snap_ts) / 60 if snap_ts else np.nan
                # flag only (does not change usable): an 'after' book snapshot taken before the swing minute t is
                # a pre-swing price, even when it is under 5 minutes old
                row["book_snap_before_swing"] = bool(x["which"] == "after" and snap_ts is not None
                                                     and snap_ts < int(x["t_ts"]))
                row["swing_time_utc"] = iso(int(x["t_ts"]))
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
    ok = a[a["usable"]].groupby(["swing_id", "book", "team"])["which"].nunique()
    pair_ok = set(ok[ok == 2].index)
    a["pair_usable"] = [(s, b, t) in pair_ok for s, b, t in zip(a["swing_id"], a["book"], a["team"])]
    sizes = a.drop_duplicates("swing_id")["abs_move"]
    cuts = sizes.quantile([1 / 3, 2 / 3]).to_numpy()
    a["size_tercile"] = np.select([a["abs_move"] <= cuts[0], a["abs_move"] <= cuts[1]], ["small", "medium"], "large")
    return a, pd.DataFrame(ev_log), e, cuts


# --------------------------------------------------------------------------------------
# summaries
# --------------------------------------------------------------------------------------

def boot(x, col, stat=np.nanmedian):
    """Point estimate and 95% interval; resamples games (all of a game's rows together), not rows."""
    x = x.dropna(subset=[col])
    if x.empty:
        return None, None, None
    groups = [v[col].to_numpy() for _, v in x.groupby("game_id")]
    rng = np.random.default_rng(SEED)
    sims = [stat(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))]))
            for _ in range(BOOT)]
    return float(stat(x[col])), float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))


def excluded(a):
    if "reason_code" not in a:
        return {}
    r = a["reason_code"]
    return {"excluded_stale": int((r == "stale").sum()),
            "excluded_missing_or_suspended": int(r.isin(MISSING_CODES).sum()),
            "excluded_suspect": int((~r.isin(("ok", "stale") + MISSING_CODES)).sum())}


def srow(metric, book, which, group, est, lo, hi, x, a_all, unit="cents per $10", scale=100.0):
    return {"metric": metric, "book": book, "which": which, "group": group,
            "estimate": None if est is None else round(est * scale, 3),
            "ci_low": None if lo is None else round(lo * scale, 3),
            "ci_high": None if hi is None else round(hi * scale, 3), "unit": unit,
            "distinguishable_from_zero": None if lo is None else bool(lo > 0 or hi < 0),
            "rows": int(len(x)), "games": int(x["game_id"].nunique()) if len(x) else 0, **excluded(a_all)}


def pregame():
    """Task 5 college costs at the kickoff ('close') snapshot, ruler A, Kalshi at n = median trade size."""
    pre = []
    for s in SEASONS:
        c = pd.read_csv(os.path.join(T5, str(s), "costs.csv.gz"), low_memory=False)
        c = c[(c["ruler"] == "A_Kalshi") & (c["checkpoint"] == "close")]
        k = c[(c["venue"] == "Kalshi") & (c["n_label"] == "median")][
            ["game_id", "team", "cost_per_10", "usable", "fair"]].rename(columns={"cost_per_10": "k_cost", "usable": "k_ok"})
        for name in BOOKS.values():
            b = c[c["venue"] == name][["game_id", "team", "cost_per_10", "usable"]].drop_duplicates(["game_id", "team"])
            b = b.merge(k, on=["game_id", "team"])
            b["book"], b["season"] = name, s
            b["extra"] = b["cost_per_10"] - b["k_cost"]
            b["ok"] = b["usable"].astype(bool) & b["k_ok"].astype(bool)
            pre.append(b)
    return pd.concat(pre, ignore_index=True)


def summaries(a, cuts):
    out = []
    u = a[a["usable"]]
    for name in BOOKS.values():
        for which in ("before", "after"):
            x = u[(u["book"] == name) & (u["which"] == which)]
            al = a[(a["book"] == name) & (a["which"] == which)]
            out.append(srow("extra_cost_A", name, which, "all", *boot(x, "extra_cost_A"), x, al))
            out.append(srow("extra_cost_B", name, which, "all", *boot(x, "extra_cost_B"), x, al))
            out.append(srow("book_cost_A", name, which, "all", *boot(x, "cost_ruler_A"), x, al))
            out.append(srow("book_cost_B", name, which, "all", *boot(x, "cost_ruler_B"), x, al))
            out.append(srow(f"kalshi_cost_B_vs_{name}_shin", "Kalshi", which, "all",
                            *boot(x, "kalshi_cost_ruler_B"), x, al))
            for grp in ("longshot", "middle", "favorite"):
                y = x[x["price_group"] == grp]
                out.append(srow("extra_cost_A", name, which, f"price_group={grp}", *boot(y, "extra_cost_A"), y,
                                al[al["price_group"] == grp]))
            for t, lab in (("small", f"<= {cuts[0]:.1f} pts"), ("medium", f"{cuts[0]:.1f}-{cuts[1]:.1f} pts"),
                           ("large", f"> {cuts[1]:.1f} pts")):
                y = x[x["size_tercile"] == t]
                out.append(srow("extra_cost_A", name, which, f"swing_size={t} ({lab})", *boot(y, "extra_cost_A"), y,
                                al[al["size_tercile"] == t]))
            # how often the book drops out in-game (share of swing-team rows with the event matched)
            m = al[~al["reason_code"].isin(["no_raw_file", "event_not_matched", "event_matched_twice"])].copy()
            m["missing"] = (m["reason_code"] == "missing_or_suspended").astype(float)
            out.append(srow("share_missing_or_suspended", name, which, "matched events", *boot(m, "missing", np.nanmean),
                            m, al, unit="share of rows", scale=1.0))
    k = u.drop_duplicates(["swing_id", "which", "team"])
    for which in ("before", "after"):
        x = k[k["which"] == which]
        out.append(srow("kalshi_cost_A", "Kalshi", which, "all", *boot(x, "kalshi_cost_ruler_A"), x,
                        a[(a["which"] == which) & (a["book"] == "FanDuel")]))
    # share of swing-team-times where Kalshi is cheapest of the three venues (ruler A, both books usable)
    pv = u.pivot_table(index=["game_id", "swing_id", "which", "team"], columns="book", values="cost_ruler_A")
    kc = k.set_index(["game_id", "swing_id", "which", "team"])[["kalshi_cost_ruler_A", "price_group"]]
    pv = pv.join(kc).dropna(subset=list(BOOKS.values()) + ["kalshi_cost_ruler_A"]).reset_index()
    pv["kalshi_cheapest"] = ((pv["kalshi_cost_ruler_A"] < pv["FanDuel"]) &
                             (pv["kalshi_cost_ruler_A"] < pv["DraftKings"])).astype(float)
    for which in ("before", "after"):
        x = pv[pv["which"] == which]
        out.append(srow("share_kalshi_cheapest", "all three", which, "all", *boot(x, "kalshi_cheapest", np.nanmean),
                        x, a[a["which"] == which], unit="share of swing-team-times", scale=1.0))
        for grp in ("longshot", "middle", "favorite"):
            y = x[x["price_group"] == grp]
            out.append(srow("share_kalshi_cheapest", "all three", which, f"price_group={grp}",
                            *boot(y, "kalshi_cheapest", np.nanmean), y, a[a["which"] == which],
                            unit="share of swing-team-times", scale=1.0))
    # reprice gap: |book Shin fair change - Kalshi midpoint change|, home team, usable before-and-after pairs
    for name in BOOKS.values():
        h = a[(a["book"] == name) & (a["side"] == "home") & a["pair_usable"]]
        p = h.pivot_table(index=["game_id", "swing_id"], columns="which",
                          values=["shin_fair_p", "kalshi_mid"]).dropna()
        if len(p):
            book_chg = (p[("shin_fair_p", "after")] - p[("shin_fair_p", "before")]) * 100
            k_chg = p[("kalshi_mid", "after")] - p[("kalshi_mid", "before")]
            gap = pd.DataFrame({"gap": (book_chg - k_chg).abs(), "signed": book_chg - k_chg,
                                "k_move": k_chg.abs()}).reset_index()
            al = a[a["book"] == name]
            out.append(srow("reprice_gap_abs", name, "after-before", "all", *boot(gap, "gap"), gap, al,
                            unit="points of win probability", scale=1.0))
            out.append(srow("reprice_gap_signed", name, "after-before", "all", *boot(gap, "signed"), gap, al,
                            unit="points (book change - Kalshi change)", scale=1.0))
            out.append(srow("kalshi_mid_move_abs", name, "after-before", "same pairs", *boot(gap, "k_move"), gap, al,
                            unit="points", scale=1.0))
    # paired after - before change in extra cost, ruler A
    for name in BOOKS.values():
        x = a[(a["book"] == name) & a["pair_usable"]].pivot_table(index=["game_id", "swing_id", "team"],
                                                                   columns="which", values="extra_cost_A").dropna()
        x = (x["after"] - x["before"]).rename("chg").reset_index()
        out.append(srow("extra_cost_A_after_minus_before", name, "after-before", "pairs", *boot(x, "chg"), x,
                        a[a["book"] == name]))
    # sensitivity: 'after' rows without book snapshots taken before the swing minute
    for name in BOOKS.values():
        al = a[(a["book"] == name) & (a["which"] == "after")]
        x = u[(u["book"] == name) & (u["which"] == "after") & ~u["book_snap_before_swing"].astype(bool)]
        r = srow("extra_cost_A", name, "after", "sensitivity: book snapshot at or after swing minute", *boot(x, "extra_cost_A"),
                 x, al)
        r["excluded_suspect"] = r.get("excluded_suspect", 0) + int((al["usable"] & al["book_snap_before_swing"]).sum())
        out.append(r)
        h = a[(a["book"] == name) & (a["side"] == "home") & a["pair_usable"]]
        bad = set(h.loc[h["book_snap_before_swing"].astype(bool), "swing_id"])
        h = h[~h["swing_id"].isin(bad)]
        p = h.pivot_table(index=["game_id", "swing_id"], columns="which", values=["shin_fair_p", "kalshi_mid"]).dropna()
        if len(p):
            gap = (((p[("shin_fair_p", "after")] - p[("shin_fair_p", "before")]) * 100
                    - (p[("kalshi_mid", "after")] - p[("kalshi_mid", "before")])).abs().rename("gap").reset_index())
            out.append(srow("reprice_gap_abs", name, "after-before", "sensitivity: book snapshot at or after swing minute",
                            *boot(gap, "gap"), gap, a[a["book"] == name], unit="points of win probability", scale=1.0))
    # in-game vs pregame (Task 5 kickoff snapshot)
    pre = pregame()
    for name in BOOKS.values():
        allb = pre[pre["book"] == name]
        x = allb[allb["ok"]]
        base = {"excluded_stale": None, "excluded_missing_or_suspended": None,
                "excluded_suspect": int((~allb["ok"]).sum())}
        groups = [("all", x)] + [(f"price_group={g}", x[(x["fair"] >= lo) & (x["fair"] < hi)])
                                 for g, (lo, hi) in (("longshot", (0, .4)), ("middle", (.4, .6)), ("favorite", (.6, 1.01)))]
        for grp, y in groups:
            r = srow("pregame_extra_cost_A_kickoff", name, "pregame kickoff (Task 5)", grp, *boot(y, "extra"), y, allb)
            r.update(base)
            out.append(r)
    return pd.DataFrame(out)


# --------------------------------------------------------------------------------------
# coverage and checks
# --------------------------------------------------------------------------------------

def coverage(a, ev, e, n_list_swings, lst):
    raw = {f for f in os.listdir(RAW) if f.endswith(".json")}
    calls = {raw_name(t) for t in lst["request_time_utc"]}
    rows = [("swings on the list", n_list_swings),
            ("swing times on the list (swing x before/after)", 2 * n_list_swings),
            ("swing times covered by a request", int(len(e))),
            ("requests on the list (calls to make)", int(len(lst))),
            ("requests with a raw file (calls made, HTTP 200)", int(len(calls & raw))),
            ("swing times with a raw file", int(ev["has_raw"].sum())),
            ("swing times with the event matched to exactly one game", int((ev["events_matched"] == 1).sum()))]
    for m, n in ev[ev["events_matched"] == 1]["match_method"].value_counts().items():
        rows.append((f"  ... matched by {m}", int(n)))
    for name in BOOKS.values():
        b = a[a["book"] == name]
        g = b.groupby(["swing_id", "which"])
        matched = g["reason_code"].apply(lambda r: not r.isin(["no_raw_file", "event_not_matched",
                                                               "event_matched_twice"]).any())
        present = g["reason_code"].apply(lambda r: not r.isin(MISSING_CODES[:4]).any())
        fresh = g["price_age_min"].max() <= STALE_MIN
        both = g["odds"].apply(lambda s: s.notna().sum() == 2)
        usable = g["usable"].all()
        pairs = b[b["pair_usable"]].groupby("swing_id")["team"].nunique()
        rows += [(f"{name}: swing times with the event matched", int(matched.sum())),
                 (f"{name}: ... and the book present (not missing_or_suspended)", int(present.sum())),
                 (f"{name}: ... and fresh (price_age_min <= 5)", int((present & fresh).sum())),
                 (f"{name}: ... and both teams priced", int((present & fresh & both).sum())),
                 (f"{name}: ... and usable (all checks)", int(usable.sum())),
                 (f"{name}: swings with a usable before-and-after pair (both teams)", int((pairs == 2).sum()))]
    for (name, rc), n in a.groupby(["book", "reason_code"]).size().items():
        rows.append((f"reason_code {name}: {rc} (rows)", int(n)))
    return pd.DataFrame(rows, columns=["step", "count"])


def credit_checks(lst):
    log = pd.read_csv(CREDIT_LOG)
    ok = log[log["http_status"] == 200].sort_values("call_n")
    rem = pd.to_numeric(ok["credits_remaining"], errors="coerce").to_numpy()
    last = pd.to_numeric(ok["credits_last"], errors="coerce").to_numpy()
    steps = rem[:-1] - rem[1:]
    other_use = int((steps != last[1:]).sum())
    return {"calls_logged": int(len(log)), "calls_http_200": int(len(ok)),
            "requests_on_list": int(len(lst)),
            "credits_per_call_seen": sorted(set(int(v) for v in last)),
            "credits_used_by_pull": int(last.sum()),
            "expected_10_x_calls": int(10 * len(ok)),
            "credits_remaining_first_call": int(rem[0]) if len(rem) else None,
            "credits_remaining_last_call": int(rem[-1]) if len(rem) else None,
            "remaining_drop_equals_credits_charged_on_every_call": other_use == 0,
            "calls_where_remaining_dropped_by_a_different_amount": other_use,
            "match": bool(last.sum() == 10 * len(ok) and other_use == 0),
            "budget": 18_000}


def checks(a, ev, e, sw, lst):
    on = sw[sw["on_list"] == True]  # noqa: E712
    raw = {f for f in os.listdir(RAW) if f.endswith(".json")}
    two = a.dropna(subset=["implied_p", "implied_p_other"]).drop_duplicates(["swing_id", "which", "book"])
    priced = a[a["odds"].notna()]
    R = a["request_time_utc"].map(unix)
    snap_after = int((a["book_snapshot_time"].map(unix) > R).sum())
    cand_after = int((a["kalshi_candle_ts"] > R).sum())
    kk = a.dropna(subset=["kalshi_ask", "kalshi_fee"])
    fee_re = np.array([kfee_cents(r.kalshi_ask, r.season) for r in kk.itertuples()])
    # the Task 7 minute table stores the fee to 4 decimals (n = 24 gives repeating decimals), so compare there
    fee_ok = np.abs(np.round(fee_re, 4) - kk["kalshi_fee"].to_numpy()) < 1e-9
    pair_rows = a[a["pair_usable"]]
    pair_good = pair_rows.groupby(["swing_id", "book", "team"])["usable"].agg(lambda s: bool(s.all()) and len(s) == 2)
    # each Odds API event goes to one game only (within a raw file and across the whole run)
    m1 = ev[ev["events_matched"] == 1]
    ev_games = m1.groupby("event_id")["game_id"].nunique()
    game_events = m1.groupby("game_id")["event_id"].nunique()
    ident = []
    for name in BOOKS.values():
        p = a[(a["book"] == name) & (a["side"] == "home") & a["odds"].notna()].pivot_table(
            index="swing_id", columns="which", values=["odds", "odds_other"], aggfunc="first").dropna()
        same = (p[("odds", "before")] == p[("odds", "after")]) & (p[("odds_other", "before")] == p[("odds_other", "after")])
        share = float(same.mean()) if len(p) else None
        ident.append({"book": name, "swings_with_prices_at_both_times": int(len(p)),
                      "identical_line_before_and_after": int(same.sum()), "share": None if share is None else round(share, 4),
                      "flag_possible_pregame_line": None if share is None else bool(share > IDENTICAL_FLAG_SHARE)})
    lu = a.dropna(subset=["book_last_update"])
    lu_age = (lu["request_time_utc"].map(unix) - lu["book_last_update"].map(unix)) / 60
    in_prog = a.drop_duplicates(["swing_id", "which"])
    return {
        "league": LEAGUE,
        "every_swing_on_list_has_a_request": {
            "pass": bool(len(e) == 2 * len(on)), "swings_on_list": int(len(on)),
            "swing_times_on_list": int(2 * len(on)), "swing_times_with_request": int(len(e))},
        "every_request_has_a_raw_file": {
            "pass": bool({raw_name(t) for t in lst["request_time_utc"]} <= raw),
            "requests": int(len(lst)),
            "missing": sorted({raw_name(t) for t in lst["request_time_utc"]} - raw)[:20]},
        "credits_used_match_calls_made": credit_checks(lst),
        "each_event_matches_one_game": {
            "pass": bool((ev["events_matched"] <= 1).all() and (ev_games <= 1).all() and (game_events <= 1).all()),
            "swing_times_matched_to_exactly_one_event": int((ev["events_matched"] == 1).sum()),
            "swing_times_matched_to_two_or_more": int((ev["events_matched"] > 1).sum()),
            "swing_times_not_matched": int((ev["events_matched"] == 0).sum()),
            "events_assigned_to_more_than_one_game": int((ev_games > 1).sum()),
            "games_assigned_more_than_one_event": int((game_events > 1).sum()),
            "api_duplicate_event_entries": duplicate_event_stats(),
            "match_methods": m1["match_method"].value_counts().to_dict()},
        "both_teams_present_for_each_book": {
            "pass": bool((a["reason_code"] != "one_team_missing").all()),
            "book_rows_with_one_team_missing": int((a["reason_code"] == "one_team_missing").sum())},
        "implied_probabilities_sum_at_least_1": {
            "pass": bool(((two["implied_p"] + two["implied_p_other"]) >= 1).all()), "lines": int(len(two)),
            "below_1": int(((two["implied_p"] + two["implied_p_other"]) < 1).sum()),
            "overround_median": round(float((two["implied_p"] + two["implied_p_other"] - 1).median()), 4) if len(two) else None},
        "shin_fair_probabilities_sum_to_1": {
            "pass": bool((priced["shin_fair_p"] + priced["shin_fair_p_other"] - 1).abs().max() < 1e-9) if len(priced) else None,
            "lines": int(len(priced)), "unsolved": int(priced["shin_fair_p"].isna().sum()),
            "max_abs_error": float((priced["shin_fair_p"] + priced["shin_fair_p_other"] - 1).abs().max()) if len(priced) else None},
        "snapshot_and_candle_never_after_request": {
            "pass": bool(snap_after == 0 and cand_after == 0),
            "book_snapshot_after_request_rows": snap_after, "kalshi_candle_after_request_rows": cand_after},
        "game_in_progress_at_request": {
            "pass": bool(in_prog["game_in_progress"].all()),
            "swing_times_not_in_progress": int((~in_prog["game_in_progress"]).sum()),
            "source": "Task 7 games_ncaaf.csv kickoff_utc / final_whistle_utc"},
        "kalshi_midpoints_between_10_and_90": {
            "pass": bool(a.loc[a["usable"], "kalshi_mid"].between(MID_LO, MID_HI).all()),
            "rule": "rows outside 10-90 get reason_code kalshi_mid_outside_10_90 and are not usable; pass = no usable row outside",
            "rows_outside": int((~a["kalshi_mid"].dropna().between(MID_LO, MID_HI)).sum()),
            "usable_rows_outside": int((~a.loc[a["usable"], "kalshi_mid"].between(MID_LO, MID_HI)).sum())},
        "fee_recomputed_matches_file": {
            "pass": bool(fee_ok.all()), "rows": int(len(fee_ok)), "mismatches": int((~fee_ok).sum()),
            "compared_at": "4 decimals of a cent (the file's precision)",
            "note": ("fee_calculator.py is not in the repo (searched every branch and the local folders). Fee recomputed "
                     "with the Task 7 / Task 5 fee function: 0.07 x n x P x (1-P) x multiplier, rounded up to the cent "
                     "per order, n = n_med (2025: 50, 2026: 24), multiplier 1.")},
        "no_duplicate_rows": {"pass": bool(not a.duplicated(["swing_id", "which", "team", "book"]).any()),
                              "duplicates": int(a.duplicated(["swing_id", "which", "team", "book"]).sum())},
        "pairs_have_both_rows_usable": {"pass": bool(pair_good.all()), "pairs": int(len(pair_good)),
                                        "violations": int((~pair_good).sum())},
        "identical_book_price_before_and_after": ident,
        "after_snapshot_taken_before_swing_minute": {
            "flag_only": True,
            "usable_after_rows": int((a["usable"] & (a["which"] == "after")).sum()),
            "usable_after_rows_flagged": int((a["usable"] & a["book_snap_before_swing"].astype(bool)).sum()),
            "note": ("the book's 'after' snapshot predates the swing minute t, so it is a pre-swing price although under "
                     "5 minutes old; kept usable (same rule as NFL), reported as a sensitivity row in the summary")},
        "price_age_min": {"min": round(float(a["price_age_min"].min()), 3), "median": round(float(a["price_age_min"].median()), 3),
                          "max": round(float(a["price_age_min"].max()), 3),
                          "rows_over_5": int((a["price_age_min"] > STALE_MIN).sum())},
        "book_last_update_minutes_before_request": {
            "median": round(float(lu_age.median()), 2) if len(lu) else None,
            "p90": round(float(lu_age.quantile(.9)), 2) if len(lu) else None,
            "rows_over_5": int((lu_age > 5).sum())},
        "kalshi_candle_minutes_before_request": {
            "median": round(float(((R - a["kalshi_candle_ts"]) / 60).median()), 2),
            "p90": round(float(((R - a["kalshi_candle_ts"]) / 60).quantile(.9)), 2)},
    }


# --------------------------------------------------------------------------------------
# hand-check worksheet
# --------------------------------------------------------------------------------------

def hand_check(a, n=5):
    """Pulls the raw values for 5 random swings (seeded) straight from the JSON, independently of the aligned
    file, and prints them side by side. You still look at the lines and write down what you compared."""
    rng = np.random.default_rng(7)
    pool = sorted(a.loc[a["pair_usable"], "swing_id"].unique())
    ids = rng.choice(pool, size=min(n, len(pool)), replace=False)
    out = ["# Hand-check worksheet (college): 5 swings against the raw Odds API responses", "",
           "Picked at random (seed 7) from swings with a usable before-and-after pair. For each time: the raw file, "
           "the snapshot time in it, the event found by its id, and each book's American odds for both teams read "
           "straight from the JSON, next to the aligned file's values. Recomputed: implied probability from the odds, "
           "Kalshi midpoint from bid and ask, and extra cost A.", ""]
    all_ok = True
    for sid in ids:
        out.append(f"## {sid}")
        for which in ("before", "after"):
            x = a[(a["swing_id"] == sid) & (a["which"] == which)]
            fn = x["raw_file"].iloc[0]
            d = json.load(open(os.path.join(RAW, fn), encoding="utf-8"))["response"]
            eid = x["odds_api_event_id"].dropna().iloc[0]
            copies = [e for e in d["data"] if e["id"] == eid]
            ev = dedupe_events(copies)[0]
            if len(copies) > 1:
                out.append(f"  - note: the raw file lists this event {len(copies)} times; merged (latest last_update per book)")
            out.append(f"- **{which}**: request {x['request_time_utc'].iloc[0]} (swing's own time "
                       f"{x['own_time_utc'].iloc[0]}), raw `{fn}`, snapshot {d['timestamp']} (aligned "
                       f"{x['book_snapshot_time'].iloc[0]}, age {x['price_age_min'].iloc[0]:.2f} min); event `{eid}` "
                       f"{ev['away_team']} @ {ev['home_team']}, kickoff {ev['commence_time']}")
            for bk, name in BOOKS.items():
                mk = next((m for b in ev["bookmakers"] if b["key"] == bk for m in b["markets"] if m["key"] == "h2h"), None)
                raw_odds = {o["name"]: o["price"] for o in (mk or {}).get("outcomes", [])}
                out.append(f"  - {name} raw: " + ", ".join(f"{k} {v:+d}" for k, v in raw_odds.items())
                           + f" (last_update {mk['last_update'] if mk else '-'})")
                for r in x[x["book"] == name].itertuples():
                    if pd.isna(r.odds):
                        out.append(f"    - aligned {r.team} ({r.side}): no odds, reason_code {r.reason_code}"
                                   f" -> {'match' if mk is None else 'CHECK'}")
                        all_ok &= mk is None
                        continue
                    ok = (int(r.odds) in raw_odds.values() and abs(implied(r.odds) - r.implied_p) < 1e-12
                          and abs((r.kalshi_bid + r.kalshi_ask) / 2 - r.kalshi_mid) < 1e-9
                          and d["timestamp"] == r.book_snapshot_time)
                    all_ok &= ok
                    out.append(f"    - aligned {r.team} ({r.side}): odds {int(r.odds):+d}, implied {r.implied_p:.4f}, "
                               f"Shin {r.shin_fair_p:.4f}; Kalshi bid/ask {r.kalshi_bid:.1f}/{r.kalshi_ask:.1f} mid "
                               f"{r.kalshi_mid:.1f}, fee {r.kalshi_fee:.2f}c, cost {r.kalshi_cost_per10 * 100:.1f}c; "
                               f"book cost A {r.cost_ruler_A * 100:.1f}c, extra A {r.extra_cost_A * 100:+.1f}c -> "
                               f"{'match' if ok else 'MISMATCH'}")
        out.append("")
    out += [f"Automated comparison: {'all values match' if all_ok else 'MISMATCHES FOUND (see above)'}.", "",
            "## What I compared (write this yourself)", "", "- ", ""]
    return "\n".join(out)


# --------------------------------------------------------------------------------------

COLS = ["game_id", "season", "week", "event_ticker", "swing_id", "which", "request_time_utc", "own_time_utc",
        "kalshi_candle_time", "team", "side", "kalshi_bid", "kalshi_ask", "kalshi_mid", "kalshi_spread", "kalshi_fee",
        "kalshi_cost_per10", "book", "odds_api_event_id", "odds_api_teams", "match_method", "book_snapshot_time",
        "book_last_update", "price_age_min", "odds", "odds_other", "implied_p", "overround", "shin_fair_p",
        "price_group", "cost_ruler_A", "cost_ruler_B", "kalshi_cost_ruler_A", "kalshi_cost_ruler_B", "extra_cost_A",
        "extra_cost_B", "usable", "reason_code", "pair_usable", "book_snap_before_swing", "swing_time_utc",
        "game_in_progress", "abs_move", "size_tercile",
        "matched_play", "raw_file"]


def main():
    os.makedirs(OUT, exist_ok=True)
    inp = load()
    a, ev, e, cuts = build(inp)
    on = inp["swings"][inp["swings"]["on_list"] == True]  # noqa: E712
    for c in COLS:
        if c not in a.columns:
            a[c] = np.nan
    out = a[COLS].sort_values(["request_time_utc", "swing_id", "which", "book", "side"])
    num = out.select_dtypes("float").columns
    out[num] = out[num].round(6)
    out.to_csv(os.path.join(OUT, f"ingame_aligned_{LEAGUE}.csv"), index=False)
    coverage(a, ev, e, len(on), inp["list"]).to_csv(os.path.join(OUT, f"ingame_coverage_{LEAGUE}.csv"), index=False)
    ck = checks(a, ev, e, inp["swings"], inp["list"])
    json.dump(ck, open(os.path.join(OUT, f"ingame_checks_{LEAGUE}.json"), "w"), indent=2, default=str)
    sm = summaries(a, cuts)
    sm.to_csv(os.path.join(OUT, f"ingame_summary_{LEAGUE}.csv"), index=False)
    open(os.path.join(OUT, f"hand_check_{LEAGUE}.md"), "w", encoding="utf-8").write(hand_check(a))
    print(f"aligned rows {len(out):,} (usable {int(out['usable'].sum()):,}); swings on list {len(on)}")
    print(out.groupby(["book", "reason_code"]).size().to_string())
    print(json.dumps({k: (v.get("pass") if isinstance(v, dict) and "pass" in v else v) for k, v in ck.items()},
                     indent=1, default=str))
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_rows", 300):
        print(sm[["metric", "book", "which", "group", "estimate", "ci_low", "ci_high", "rows", "games",
                  "distinguishable_from_zero"]].to_string())


if __name__ == "__main__":
    main()
