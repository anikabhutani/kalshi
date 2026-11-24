"""Task 7 Part 1, steps 1-5 and 7 (college): find the big in-game swings on Kalshi, pick steady before and
after times, check them against CollegeFootballData plays, and record Kalshi's prices at each time.

Inputs come from data.py (data/<season>/crosswalk.csv, candles/, cfbd/). Every threshold is in config.py.

    python swings.py                       # main run (config.K_PCT, config.STEADY_RANGE)
    python swings.py --k-pct 97.5          # robustness rerun -> output/k_p97.5/
    python swings.py --steady-range 1      # tighter steady rule -> output/steady1/

Then run timestamp_list.py (with the same flags) for step 6.

1. Minute table: the home team's KXNCAAFGAME market, one row per minute from kickoff to the final whistle
   (first and last CFBD play for games with good timestamps; otherwise the scheduled start and the last
   minute Kalshi's price was still undecided). A thin home market is replaced by the away market, flipped.
   A minute whose quote lacks a bid or an ask carries the last two-sided quote forward and is ``filled``.
2. Threshold: quiet minutes are in-game minutes more than 5 minutes from a touchdown, field goal, turnover
   or failed fourth down. d = 5-minute midpoint change. sigma_game = 1.4826 x MAD(d) over quiet minutes
   (floor 1 point; under 20 quiet minutes -> league median, marked). k = 99th percentile of |d| / sigma_game
   over quiet minutes of good-timestamp games. Games without good timestamps: sigma from all usable minutes.
3. Swings: |d| > k x sigma, the move holds 3 minutes later (>= 3/4 of the threshold, same direction), midpoint
   10-90. Flagged minutes within 10 minutes are one swing; t = the minute with the biggest one-minute jump.
4. Steady: 5 minutes ending at the minute with midpoint range <= 2, spread <= 5c, nothing filled. Before = the
   latest steady minute at least 1 minute before the move started; after = the first steady minute after t
   with spread within 2c of the before spread. Every dropped swing gets a reason.
5. Catch rate, match rate, sigma range, plots. 7. Kalshi at every before / after time, summaries.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config as C
from common import (EASTERN, cost_per_10, iso, load_plays, minute_end, season_dir, timestamp_quality, unix)

MIN = 60


# --------------------------------------------------------------------------------------
# Step 1: minute table
# --------------------------------------------------------------------------------------

def market_minutes(c, grid):
    """Last quote at or before each grid minute, the minute's own volume, and whether a candle exists."""
    g = pd.DataFrame({"ts": grid})
    if c.empty:
        return g.assign(bid=np.nan, ask=np.nan, volume=0.0, has_candle=False)
    c = c.sort_values("ts")
    m = pd.merge_asof(g, c[["ts", "bid", "ask"]], on="ts", direction="backward")
    vol = c.groupby("ts")["volume"].sum()
    m["volume"] = g["ts"].map(vol).fillna(0.0).to_numpy()
    m["has_candle"] = g["ts"].isin(set(c["ts"])).to_numpy()
    return m


def two_sided(m):
    """bid/ask from the last two-sided quote; ``filled`` where the minute's own quote is not two-sided."""
    valid = m["bid"].gt(0) & m["ask"].lt(100) & m["ask"].gt(m["bid"])
    out = m.copy()
    out["filled"] = ~valid
    out.loc[~valid, ["bid", "ask"]] = np.nan
    out[["bid", "ask"]] = out[["bid", "ask"]].ffill()
    out.loc[out["bid"].isna(), "filled"] = True
    return out


def build_minutes(cands, g, k0, k1, season):
    start, end = minute_end(k0), minute_end(k1)
    grid = np.arange(start - C.PREGAME_MIN * MIN, end + 1, MIN, dtype=np.int64)
    sides, info = {}, {}
    for side, tk in (("home", g["ticker_home"]), ("away", g["ticker_away"])):
        m = two_sided(market_minutes(cands[cands["ticker"] == tk], grid))
        ing = (m["ts"] >= start) & (m["ts"] <= end)
        info[f"{side}_filled_share"] = round(float(m.loc[ing, "filled"].mean()), 4)
        info[f"{side}_volume"] = float(m.loc[ing, "volume"].sum())
        sides[side] = m
    thin_home = (info["home_filled_share"] > info["away_filled_share"] + C.THIN_FILLED_MARGIN) or \
                (info["home_volume"] < C.THIN_VOLUME_SHARE * info["away_volume"])
    src = "away" if thin_home else "home"
    m = sides[src]
    df = pd.DataFrame({"ts": grid})
    if src == "home":
        df["bid"], df["ask"] = m["bid"].to_numpy(), m["ask"].to_numpy()
    else:
        df["bid"], df["ask"] = 100 - m["ask"].to_numpy(), 100 - m["bid"].to_numpy()
    df["volume"] = m["volume"].to_numpy()
    df["volume_both"] = sides["home"]["volume"].to_numpy() + sides["away"]["volume"].to_numpy()
    df["filled"] = m["filled"].to_numpy()
    df["new_candle"] = m["has_candle"].to_numpy()
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["spread"] = df["ask"] - df["bid"]
    n, mult = C.N_MED[season], C.FEE_MULTIPLIER[season]
    df["cost_home_per10"], df["fee_home_c"] = cost_per_10(df["mid"].to_numpy(), df["ask"].to_numpy(), n, mult)
    df["cost_away_per10"], df["fee_away_c"] = cost_per_10(100 - df["mid"].to_numpy(), 100 - df["bid"].to_numpy(),
                                                          n, mult)
    # filled minutes are never used for cost
    df.loc[df["filled"], ["cost_home_per10", "fee_home_c", "cost_away_per10", "fee_away_c"]] = np.nan
    df["in_game"] = (df["ts"] >= start) & (df["ts"] <= end)
    info.update({"source_market": src, "kickoff_minute": start, "end_minute": end})
    return df, info


def kalshi_end(cands, g, k0):
    """Final whistle when play timestamps are not usable: the last minute (within 5.5 h of kickoff) that the
    home price was still undecided (mid 2-98)."""
    tk = g["ticker_home"] if (cands["ticker"] == g["ticker_home"]).any() else g["ticker_away"]
    s = unix(k0)
    c = cands[(cands["ticker"] == tk) & (cands["ts"] >= s) & (cands["ts"] <= s + 5.5 * 3600)]
    c = c[c["bid"].gt(0) & c["ask"].lt(100)]
    mid = (c["bid"] + c["ask"]) / 2
    live = c.loc[(mid > 2) & (mid < 98), "ts"]
    if live.empty:
        return k0 + pd.Timedelta(hours=3.5)
    return pd.Timestamp(int(live.max()), unit="s", tz="UTC")


def steady_flags(df, rng):
    mid = df["mid"]
    hi = mid.rolling(C.STEADY_LEN, min_periods=C.STEADY_LEN).max()
    lo = mid.rolling(C.STEADY_LEN, min_periods=C.STEADY_LEN).min()
    sp = df["spread"].rolling(C.STEADY_LEN, min_periods=C.STEADY_LEN).max()
    fl = df["filled"].astype(float).rolling(C.STEADY_LEN, min_periods=C.STEADY_LEN).max()
    return ((hi - lo <= rng + 1e-9) & (sp <= C.STEADY_SPREAD + 1e-9) & (fl == 0)).to_numpy()


def usable_d(df):
    """d = 5-minute midpoint change, and whether the minute can be used for sigma: in-game, neither end
    filled, midpoint 10-90 at both ends."""
    mid = df["mid"].to_numpy()
    filled = df["filled"].to_numpy()
    d = np.full(len(mid), np.nan)
    d[C.D_LAG:] = mid[C.D_LAG:] - mid[:-C.D_LAG]
    prev_f = np.ones(len(mid), bool)
    prev_f[C.D_LAG:] = filled[:-C.D_LAG]
    prev_mid = np.full(len(mid), np.nan)
    prev_mid[C.D_LAG:] = mid[:-C.D_LAG]
    with np.errstate(invalid="ignore"):
        ok = (df["in_game"].to_numpy() & ~filled & ~prev_f & (mid >= C.MID_LO) & (mid <= C.MID_HI)
              & (prev_mid >= C.MID_LO) & (prev_mid <= C.MID_HI) & ~np.isnan(d))
    return d, ok


def mad_sigma(d):
    if len(d) == 0:
        return float("nan")
    return float(C.MAD_SCALE * np.median(np.abs(d - np.median(d))))


# --------------------------------------------------------------------------------------
# Steps 3-4: swings, steady before / after
# --------------------------------------------------------------------------------------

@dataclass
class Game:
    key: str
    df: pd.DataFrame
    info: dict
    events: pd.DataFrame = field(default_factory=pd.DataFrame)
    sigma: float = float("nan")
    sigma_note: str = ""


def find_swings(st, thr, rng):
    df = st.df
    mid, ts = df["mid"].to_numpy(), df["ts"].to_numpy()
    filled, in_game = df["filled"].to_numpy(), df["in_game"].to_numpy()
    n = len(df)
    d, _ = usable_d(df)
    fwd = np.full(n, np.nan)   # mid 3 minutes after the flag minus mid 5 minutes before it
    fwd[C.D_LAG:n - C.HOLD_LAG] = mid[C.D_LAG + C.HOLD_LAG:] - mid[:n - C.D_LAG - C.HOLD_LAG]
    prev_f = np.ones(n, bool)
    prev_f[C.D_LAG:] = filled[:-C.D_LAG]
    with np.errstate(invalid="ignore"):
        flag = (in_game & ~filled & ~prev_f & (np.abs(d) > thr) & (fwd * np.sign(d) >= C.HOLD_SHARE * thr)
                & (mid >= C.MID_LO) & (mid <= C.MID_HI))
    df["flagged"] = flag
    steady = steady_flags(df, rng) & in_game
    df["steady"] = steady
    groups = []
    for i in np.flatnonzero(flag):
        if groups and i - groups[-1][-1] <= C.GROUP_GAP_MIN:
            groups[-1].append(i)
        else:
            groups.append([i])
    jump = np.abs(np.diff(mid, prepend=np.nan))
    raw = []
    for grp in groups:
        f = grp[0]
        t = max(grp, key=lambda i: (np.nan_to_num(jump[i]), -i))
        base = mid[f - C.D_LAG]
        # the move starts at the first minute after the 5-minute base that is 1+ point away from it
        moving = [s for s in range(f - C.D_LAG + 1, t + 1) if abs(mid[s] - base) >= 1]
        raw.append({"i_first": f, "i_last": grp[-1], "i_t": t, "i_start": moving[0] if moving else f,
                    "base": base, "peak_z": float(np.nanmax(np.abs(d[grp])) / st.sigma)})
    out = []
    for j, sw in enumerate(raw):
        t, s0 = sw["i_t"], sw["i_start"]
        b = next((i for i in range(s0 - 1, max(0, t - C.MAX_FROM_T) - 1, -1) if steady[i]), None)
        a = next((i for i in range(t + 1, min(n - 1, t + C.MAX_FROM_T) + 1)
                  if steady[i] and (b is None or abs(df["spread"].iat[i] - df["spread"].iat[b])
                                    <= C.AFTER_SPREAD_TOL + 1e-9)), None)
        reason = ""
        if b is None:
            reason = f"no steady before time within {C.MAX_FROM_T} min"
        elif a is None:
            reason = f"no steady after time within {C.MAX_FROM_T} min"
        elif j + 1 < len(raw) and raw[j + 1]["i_start"] <= a:
            reason = "next swing starts before the after time"
        elif C.DROP_IF_PREV_SWING_AFTER_BEFORE and j > 0 and raw[j - 1]["i_last"] >= b:
            reason = "previous swing is after the before time"
        elif C.SETTLED_SHARE is not None and abs(mid[a] - mid[b]) < C.SETTLED_SHARE * thr:
            reason = f"move reversed: settled change under {C.SETTLED_SHARE:g} x threshold"
        vol10 = float(df["volume_both"].iloc[max(0, t - 5):t + 6].sum())
        size = (mid[a] - mid[b]) if (a is not None and b is not None) else (mid[min(n - 1, t + C.HOLD_LAG)] - sw["base"])
        out.append({
            "swing_id": f"{st.key}-S{j + 1:02d}", "t_utc": iso(ts[t]), "t_ts": int(ts[t]),
            "first_flag_utc": iso(ts[sw["i_first"]]), "move_start_utc": iso(ts[s0]),
            "mid_at_start": round(sw["base"], 2), "mid_at_t": round(mid[t], 2),
            "mid_before": None if b is None else round(mid[b], 2), "mid_after": None if a is None else round(mid[a], 2),
            "size_move": round(float(size), 2), "abs_move": round(abs(float(size)), 2),
            "before_utc": None if b is None else iso(ts[b]), "after_utc": None if a is None else iso(ts[a]),
            "before_ts": None if b is None else int(ts[b]), "after_ts": None if a is None else int(ts[a]),
            "min_before_to_t": None if b is None else int((ts[t] - ts[b]) // MIN),
            "minutes_to_settle": None if a is None else int((ts[a] - ts[t]) // MIN),
            "sigma_game": round(st.sigma, 3), "threshold": round(thr, 3), "peak_z": round(sw["peak_z"], 2),
            "kalshi_volume_10min": round(vol10, 2), "rank_score": round(abs(float(size)) * vol10, 1),
            "status": "dropped" if reason else "kept", "drop_reason": reason,
        })
    return out


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------

def load_wp(season, game_id):
    p = os.path.join(season_dir(season, "cfbd", "wp"), f"{int(game_id)}.json")
    if not os.path.exists(p):
        return None
    out = {}
    for r in json.load(open(p, encoding="utf-8")) or []:
        pid, wp = r.get("playId"), r.get("homeWinProbability")
        if pid is not None and wp is not None:
            out[str(pid)] = float(wp)
    return out


def load_games(seasons, steady_range):
    games, glog = [], []
    for season in seasons:
        cw = pd.read_csv(season_dir(season, "crosswalk.csv"))
        for r in cw[cw["status"] != "matched"].itertuples():
            glog.append({"event_ticker": r.event_ticker, "season": season, "status": r.status})
        cw = cw[cw["status"] == "matched"].copy()
        cw["scheduled_start_utc"] = pd.to_datetime(cw["scheduled_start_utc"], utc=True, format="ISO8601")
        plays = load_plays(season)
        by_game = {gid: x for gid, x in plays.groupby("game_id")}
        for _, g in cw.iterrows():
            row = {"event_ticker": g["event_ticker"], "game_id": int(g["game_id"]), "season": season,
                   "season_type": g["season_type"], "week": g["week"], "home": g["home"], "away": g["away"],
                   "home_cls": g["home_cls"], "away_cls": g["away_cls"],
                   "scheduled_start_utc": g["scheduled_start_utc"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "start_tbd": g["start_tbd"]}
            cpath = os.path.join(season_dir(season, "candles"), f"{g['event_ticker']}.csv.gz")
            if not os.path.exists(cpath):
                glog.append({**row, "status": "no candles"})
                continue
            cands = pd.read_csv(cpath)
            gp = by_game.get(g["game_id"], pd.DataFrame())
            good, why, k0, k1 = timestamp_quality(gp, g["scheduled_start_utc"]) if len(gp) else \
                (False, "no plays", None, None)
            if good:
                src = "CFBD first / last play"
            else:
                if g["start_tbd"]:
                    glog.append({**row, "status": "no reliable game times (start TBD, bad play timestamps)",
                                 "timestamp_check": why})
                    continue
                k0 = g["scheduled_start_utc"]
                k1, src = kalshi_end(cands, g, k0), "scheduled start / Kalshi price"
            if cands.empty or cands["ts"].max() < unix(k0) + 3600:
                glog.append({**row, "status": "candles do not cover the game", "timestamp_check": why})
                continue
            df, info = build_minutes(cands, g, k0, k1, season)
            st = Game(str(int(g["game_id"])), df, {**row, **info, "good_timestamps": good, "timestamp_check": why,
                                                   "game_times_from": src, "kickoff_utc": iso(info["kickoff_minute"]),
                                                   "final_whistle_utc": iso(info["end_minute"]),
                                                   "n_med": C.N_MED[season]})
            if good:
                # all scoring plays / turnovers / failed 4ths, placeholder stamps interpolated (quiet minutes);
                # matching and the catch rate use only real stamps (``wall_ok``)
                e = gp[gp["event"] != ""].dropna(subset=["wall_fill"]).copy()
                e["minute_ts"] = [minute_end(w) for w in e["wall_fill"]]
                wp = load_wp(season, g["game_id"])
                e["wp_home"] = [wp.get(str(i)) if wp else None for i in e["id"]]
                e["wp_pulled"] = wp is not None and len(wp) > 0
                st.events = e
            games.append(st)
            glog.append({**st.info, "status": "used"})
    return games, glog


# --------------------------------------------------------------------------------------
# Step 2: sigma and k
# --------------------------------------------------------------------------------------

def set_sigmas(games):
    for st in games:
        d, ok = usable_d(st.df)
        ts = st.df["ts"].to_numpy()
        if st.info["good_timestamps"]:
            near = np.zeros(len(ts), bool)
            for e in (st.events["minute_ts"].to_numpy() if len(st.events) else []):
                near |= np.abs(ts - e) <= C.QUIET_GAP_MIN * MIN
            st.df["quiet"] = st.df["in_game"].to_numpy() & ~near
            qd = d[st.df["quiet"].to_numpy() & ok]
            st.info["quiet_minutes"] = int(len(qd))
            st.sigma = mad_sigma(qd) if len(qd) >= C.MIN_QUIET else float("nan")
        else:
            st.df["quiet"] = pd.NA
            ad = d[ok]
            st.info["quiet_minutes"] = None
            st.info["usable_minutes"] = int(len(ad))
            st.sigma = mad_sigma(ad) if len(ad) >= C.MIN_QUIET else float("nan")
            st.sigma_note = "all usable minutes (no good play timestamps)"
    good_raw = np.array([s.sigma for s in games if s.info["good_timestamps"] and np.isfinite(s.sigma)])
    league_med = float(np.median(np.maximum(good_raw, C.SIGMA_FLOOR))) if len(good_raw) else C.SIGMA_FLOOR
    for st in games:
        notes = [st.sigma_note] if st.sigma_note else []
        if not np.isfinite(st.sigma):
            st.sigma = league_med
            notes.append(f"under {C.MIN_QUIET} usable minutes: league median sigma")
        elif st.sigma < C.SIGMA_FLOOR:
            notes.append(f"floor: MAD sigma {st.sigma:.2f} raised to {C.SIGMA_FLOOR:g}")
            st.sigma = C.SIGMA_FLOOR
        st.sigma_note = "; ".join(notes)
        st.info["sigma_game"] = round(st.sigma, 4)
        st.info["sigma_note"] = st.sigma_note
    return league_med


def quiet_z(games):
    zs = []
    for st in games:
        if st.info["good_timestamps"]:
            d, ok = usable_d(st.df)
            q = st.df["quiet"].to_numpy(dtype=bool) & ok
            zs.append(np.abs(d[q]) / st.sigma)
    return np.concatenate(zs) if zs else np.array([])


# --------------------------------------------------------------------------------------
# Step 5: checks against plays
# --------------------------------------------------------------------------------------

def match_cols(sw, games):
    """Nearest CFBD play (touchdown, field goal, turnover, failed fourth down) to each swing's t."""
    by = {s.info["event_ticker"]: s for s in games}
    cols = {k: [] for k in ("nearest_play", "nearest_play_min_from_t", "nearest_play_text", "nearest_play_type",
                            "nearest_play_id")}
    for r in sw.itertuples():
        st = by[r.event_ticker]
        ev = st.events[st.events["wall_ok"]] if len(st.events) else st.events
        if ev.empty or not st.info["good_timestamps"]:
            for v in cols.values():
                v.append(None)
            continue
        gap = (ev["minute_ts"] - r.t_ts) / MIN
        j = gap.abs().idxmin()
        e = ev.loc[j]
        cols["nearest_play"].append(e["event"])
        cols["nearest_play_min_from_t"].append(int(gap[j]))
        cols["nearest_play_text"].append(str(e.get("play_text"))[:200])
        cols["nearest_play_type"].append(e.get("play_type"))
        cols["nearest_play_id"].append(str(e["id"]))
    for k, v in cols.items():
        sw[k] = v
    ok = sw["nearest_play_min_from_t"].abs() <= C.MATCH_MIN
    sw["matched_play"] = sw["nearest_play"].where(ok)
    sw["matched_play_type"] = sw["nearest_play_type"].where(ok)
    sw["matched_play_text"] = sw["nearest_play_text"].where(ok)
    sw.loc[~sw["good_timestamps"].astype(bool), "matched_play"] = "n/a: no good play timestamps"


def rates(sw, games):
    """Catch rate (touchdowns and turnovers at 20-80% home win probability that land within the tolerance of a
    swing's t) and match rate (swings with a real play within the tolerance), good-timestamp games only.

    Win probability: CFBD's where it was pulled, else the Kalshi midpoint the minute before the play. The rate
    is also given on the CFBD-win-probability sample alone."""
    good = [s for s in games if s.info["good_timestamps"] and not s.events.empty]
    out = {}
    for tol in (C.MATCH_MIN, 5):
        res = {"all": [0, 0], "cfbd_wp_sample": [0, 0]}
        by_type = {"touchdown": [0, 0], "turnover": [0, 0]}
        wp_src = {"cfbd": 0, "kalshi_mid": 0}
        for st in good:
            ts_sw = sw.loc[sw["event_ticker"] == st.info["event_ticker"], "t_ts"].to_numpy() if len(sw) else np.array([])
            mid_by = dict(zip(st.df["ts"], st.df["mid"]))
            for e in st.events[st.events["event"].isin(["touchdown", "turnover"]) & st.events["wall_ok"]].itertuples():
                wp = e.wp_home
                from_cfbd = wp is not None and not (isinstance(wp, float) and np.isnan(wp))
                if not from_cfbd:
                    m = mid_by.get(e.minute_ts - MIN)
                    if m is None or np.isnan(m):
                        continue
                    wp = m / 100
                if not C.WP_LO <= wp <= C.WP_HI:
                    continue
                wp_src["cfbd" if from_cfbd else "kalshi_mid"] += 1
                hit = bool(len(ts_sw)) and bool((np.abs(ts_sw - e.minute_ts) <= tol * MIN).any())
                res["all"][0] += hit
                res["all"][1] += 1
                if e.wp_pulled and from_cfbd:
                    res["cfbd_wp_sample"][0] += hit
                    res["cfbd_wp_sample"][1] += 1
                by_type[e.event][0] += hit
                by_type[e.event][1] += 1
        swg = sw[sw["event_ticker"].isin({s.info["event_ticker"] for s in good})] if len(sw) else sw
        match = float((swg["nearest_play_min_from_t"].abs() <= tol).mean()) if len(swg) else None
        kept = swg[swg["status"] == "kept"] if len(swg) else swg
        out[f"within_{tol}_min"] = {
            "catch_rate": round(res["all"][0] / res["all"][1], 4) if res["all"][1] else None,
            "plays_checked": res["all"][1], "caught": res["all"][0],
            "catch_rate_cfbd_wp_sample": round(res["cfbd_wp_sample"][0] / res["cfbd_wp_sample"][1], 4)
            if res["cfbd_wp_sample"][1] else None,
            "plays_checked_cfbd_wp_sample": res["cfbd_wp_sample"][1],
            "by_type": {k: {"caught": v[0], "plays": v[1]} for k, v in by_type.items()},
            "wp_source": wp_src,
            "match_rate": None if match is None else round(match, 4), "swings_checked": int(len(swg)),
            "match_rate_kept": round(float((kept["nearest_play_min_from_t"].abs() <= tol).mean()), 4)
            if len(kept) else None,
        }
    return out


# --------------------------------------------------------------------------------------
# Step 7: Kalshi at every before / after time
# --------------------------------------------------------------------------------------

def kalshi_at_swings(sw, games):
    by = {s.info["event_ticker"]: s for s in games}
    rows = []
    for r in sw.itertuples():
        st = by[r.event_ticker]
        df = st.df.set_index("ts")
        for kind in ("before", "after"):
            t = getattr(r, f"{kind}_ts")
            if t is None or (isinstance(t, float) and np.isnan(t)):
                continue
            x = df.loc[int(t)]
            for team, side in ((st.info["home"], "home"), (st.info["away"], "away")):
                if side == "home":
                    bid, ask, mid, cost, fee = x["bid"], x["ask"], x["mid"], x["cost_home_per10"], x["fee_home_c"]
                else:
                    bid, ask, mid = 100 - x["ask"], 100 - x["bid"], 100 - x["mid"]
                    cost, fee = x["cost_away_per10"], x["fee_away_c"]
                rows.append({"swing_id": r.swing_id, "event_ticker": r.event_ticker, "game_id": r.game_id,
                             "season": r.season, "status": r.status, "kind": kind, "time_utc": iso(t), "team": team,
                             "side": side, "bid": round(bid, 2), "ask": round(ask, 2), "midpoint": round(mid, 2),
                             "spread": round(ask - bid, 2), "fee_per_contract_c": round(fee, 4),
                             "cost_per_10": round(cost, 4), "n_med": C.N_MED[int(r.season)], "abs_move": r.abs_move,
                             "matched_play": r.matched_play, "source_market": st.info["source_market"]})
    return pd.DataFrame(rows)


def _med(x):
    return round(float(x.median()), 4) if len(x) and x.notna().any() else None


def summaries(sw, at):
    if sw.empty:
        return {}
    kept = sw[sw["status"] == "kept"]
    a = at[at["status"] == "kept"]
    out = {
        "swings_found": int(len(sw)), "swings_kept": int(len(kept)),
        "dropped_by_reason": sw.loc[sw.status == "dropped", "drop_reason"].value_counts().to_dict(),
        "median_minutes_to_settle_kept": _med(kept["minutes_to_settle"]),
        "minutes_to_settle_kept_p25_p75": [float(kept["minutes_to_settle"].quantile(q)) for q in (0.25, 0.75)]
        if len(kept) else None,
        "median_minutes_to_settle_all_with_after": _med(sw["minutes_to_settle"].dropna()),
        "median_cost_per_10": {k: _med(a.loc[a.kind == k, "cost_per_10"]) for k in ("before", "after")},
        "median_spread_c": {k: _med(a.loc[a.kind == k, "spread"]) for k in ("before", "after")},
    }
    p = a.pivot_table(index=["swing_id", "side"], columns="kind", values="cost_per_10")
    if {"before", "after"} <= set(p.columns):
        diff = (p["after"] - p["before"]).dropna()
        out["paired_after_minus_before_cost_per_10"] = {"median": _med(diff), "mean": round(float(diff.mean()), 4),
                                                         "n": int(len(diff))}
    bt = {}
    for typ in ("touchdown", "turnover", "field_goal", "failed_fourth"):
        ids = kept.loc[kept["matched_play"] == typ, "swing_id"]
        x = a[a["swing_id"].isin(ids)]
        bt[typ] = {"swings": int(len(ids)), "median_cost_before": _med(x.loc[x.kind == "before", "cost_per_10"]),
                   "median_cost_after": _med(x.loc[x.kind == "after", "cost_per_10"]),
                   "median_abs_move": _med(kept.loc[kept["swing_id"].isin(ids), "abs_move"]),
                   "median_minutes_to_settle": _med(kept.loc[kept["swing_id"].isin(ids), "minutes_to_settle"])}
    good = kept["good_timestamps"].astype(bool)
    bt["no play within 3 min (good timestamps)"] = {"swings": int((good & kept["matched_play"].isna()).sum())}
    bt["no good play timestamps"] = {"swings": int((~good).sum())}
    out["by_play_type"] = bt
    bins, labels = [0, 10, 20, 30, 101], ["<10 pts", "10-20 pts", "20-30 pts", "30+ pts"]
    a2 = a.assign(size_bin=pd.cut(a["abs_move"], bins, labels=labels, right=False))
    k2 = kept.assign(size_bin=pd.cut(kept["abs_move"], bins, labels=labels, right=False))
    out["by_swing_size"] = {lab: {"swings": int((k2.size_bin == lab).sum()),
                                  "median_cost_before": _med(a2.loc[(a2.size_bin == lab) & (a2.kind == "before"), "cost_per_10"]),
                                  "median_cost_after": _med(a2.loc[(a2.size_bin == lab) & (a2.kind == "after"), "cost_per_10"]),
                                  "median_minutes_to_settle": _med(k2.loc[k2.size_bin == lab, "minutes_to_settle"])}
                            for lab in labels}
    return out


# --------------------------------------------------------------------------------------
# Plots
# --------------------------------------------------------------------------------------

def plots(games, sw, out, n):
    import glob

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for old in glob.glob(os.path.join(out, "swings_*.png")):
        os.remove(old)
    good = [s for s in games if s.info["good_timestamps"] and not s.events.empty]
    scored = []
    for s in good:
        x = sw[sw["event_ticker"] == s.info["event_ticker"]] if len(sw) else sw
        scored.append(((x["status"] == "kept").sum() if len(x) else 0, len(x), s))
    scored.sort(key=lambda r: (-r[0], -r[1], r[2].info["event_ticker"]))
    picks = []   # the games with the most kept swings, at least 5 days apart, both seasons if possible
    for want_season in (2025, 2026, None):
        for _, _, s in scored:
            if len(picks) == n:
                break
            if want_season is not None and (s.info["season"] != want_season or
                                            any(p.info["season"] == want_season for p in picks)):
                continue
            if s not in picks and all(abs(s.info["kickoff_minute"] - p.info["kickoff_minute"]) > 5 * 86400 for p in picks):
                picks.append(s)
    to_dt = lambda v: pd.Timestamp(int(v), unit="s", tz="UTC").tz_convert(EASTERN)  # noqa: E731
    files = []
    for s in picks:
        df = s.df[s.df["in_game"]]
        x = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(EASTERN)
        fig, ax = plt.subplots(figsize=(11, 4.4))
        ax.plot(x, df["mid"], color="#222", lw=1.2, label="Kalshi midpoint (home)")
        fl = df["filled"].to_numpy()
        if fl.any():
            ax.scatter(x[fl], df["mid"][fl], s=6, color="#bbb", label="filled minute", zorder=2)
        colors = {"touchdown": "#1a9850", "turnover": "#d73027", "field_goal": "#7570b3", "failed_fourth": "#e6ab02"}
        for typ, col in colors.items():
            e = s.events[(s.events["event"] == typ) & s.events["wall_ok"]]
            for i, t in enumerate(e["minute_ts"]):
                ax.axvline(to_dt(t), color=col, lw=0.8, ls="--", alpha=0.7,
                           label=typ.replace("_", " ") if i == 0 else None)
        xs = sw[sw["event_ticker"] == s.info["event_ticker"]]
        mid_by = dict(zip(s.df["ts"], s.df["mid"]))
        for i, r in enumerate(xs.itertuples()):
            ax.scatter([to_dt(r.t_ts)], [mid_by[r.t_ts]], marker="v", s=60, color="black", zorder=5,
                       label="swing t" if i == 0 else None)
            for kind, col, mk in (("before", "#2166ac", "o"), ("after", "#f46d43", "s")):
                v = getattr(r, f"{kind}_ts")
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    ax.scatter([to_dt(v)], [mid_by[int(v)]], marker=mk, s=42, color=col, zorder=6, edgecolor="white",
                               label=f"{kind} time" if i == 0 else None)
            if r.status == "dropped":
                ax.annotate("dropped", (to_dt(r.t_ts), mid_by[r.t_ts]), textcoords="offset points", xytext=(4, 6),
                            fontsize=7, color="#555")
        ax.set_ylim(0, 100)
        ax.set_ylabel("Home win price (cents)")
        ax.set_xlabel("US Eastern time")
        thr = xs["threshold"].iloc[0] if len(xs) else s.sigma
        ax.set_title(f"{s.info['away']} at {s.info['home']}, {s.info['season']} week {s.info['week']}  "
                     f"({s.info['event_ticker']}; sigma {s.sigma:.2f}, threshold {thr:.1f} pts)", fontsize=10)
        ax.grid(alpha=0.25)
        h, l_ = ax.get_legend_handles_labels()
        ax.legend(h, l_, fontsize=7, loc="upper left", ncol=3, framealpha=0.9)
        fig.autofmt_xdate()
        fig.tight_layout()
        f = os.path.join(out, f"swings_{s.info['event_ticker']}.png")
        fig.savefig(f, dpi=150)
        plt.close(fig)
        files.append(os.path.basename(f))
    return files


# --------------------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------------------

def run(k_pct, steady_range):
    out = C.out_dir(k_pct, steady_range)
    seasons = list(C.SEASONS)
    games, glog = load_games(seasons, steady_range)
    league_med = set_sigmas(games)
    qz = quiet_z(games)
    n_good = sum(1 for s in games if s.info["good_timestamps"])
    if not len(qz):
        sys.exit("No quiet minutes from games with good play timestamps: k cannot be set.")
    ks = {p: float(np.percentile(qz, p)) for p in sorted(set(C.K_PCTS) | {k_pct})}
    k = ks[k_pct]
    print(f"{len(games)} games ({n_good} with good play timestamps); k: "
          + ", ".join(f"p{p:g} = {v:.3f}" for p, v in ks.items()) + f" from {len(qz):,} quiet minutes")

    # swing counts and check rates at every reported percentile (robustness table)
    sens = {}
    for p, kv in ks.items():
        alt = []
        for st in games:
            for x in find_swings(Game(st.key, st.df.copy(), st.info, st.events, st.sigma), kv * st.sigma, steady_range):
                x.update(event_ticker=st.info["event_ticker"], good_timestamps=st.info["good_timestamps"])
                alt.append(x)
        alt = pd.DataFrame(alt)
        rr = {}
        if len(alt):
            match_cols(alt, games)
            rr = rates(alt, games).get(f"within_{C.MATCH_MIN}_min", {})
        sens[f"p{p:g}"] = {"k": round(kv, 4), "swings": int(len(alt)), "kept": int((alt.get("status") == "kept").sum())
                           if len(alt) else 0, "catch_rate_3min": rr.get("catch_rate"),
                           "match_rate_3min": rr.get("match_rate")}

    # main threshold (also leaves flagged / steady columns on each game's table)
    rows = []
    for st in games:
        for s in find_swings(st, k * st.sigma, steady_range):
            s.update({c: st.info[c] for c in ("event_ticker", "game_id", "season", "season_type", "week", "home",
                                              "away", "good_timestamps", "source_market")})
            rows.append(s)
        st.info["swings"] = sum(1 for r in rows if r["event_ticker"] == st.info["event_ticker"])
    sw = pd.DataFrame(rows)
    match_cols(sw, games)
    checks = rates(sw, games)
    for st in games:
        x = sw[sw["event_ticker"] == st.info["event_ticker"]]
        st.info["swings"], st.info["swings_kept"] = int(len(x)), int((x["status"] == "kept").sum())

    # minute tables
    for season in seasons:
        mt = []
        for st in games:
            if st.info["season"] != season:
                continue
            d, _ = usable_d(st.df)
            ing = st.df["in_game"].to_numpy()
            x = st.df[ing].copy()
            x.insert(0, "event_ticker", st.info["event_ticker"])
            x.insert(1, "game_id", st.info["game_id"])
            x.insert(2, "minute_utc", [iso(v) for v in x["ts"]])
            x["d5"] = d[ing]
            x["source_market"] = st.info["source_market"]
            mt.append(x.drop(columns=["in_game"]))
        m = pd.concat(mt, ignore_index=True)
        num = m.select_dtypes("float").columns
        m[num] = m[num].round(4)
        m.to_csv(os.path.join(out, f"kalshi_minutes_{C.LEAGUE}_{season}.csv"), index=False)

    cols_first = ["swing_id", "event_ticker", "game_id", "season", "season_type", "week", "home", "away", "t_utc",
                  "mid_before", "mid_after", "size_move", "abs_move", "before_utc", "after_utc", "minutes_to_settle",
                  "status", "drop_reason", "matched_play", "matched_play_type", "matched_play_text"]
    sw = sw[cols_first + [c for c in sw.columns if c not in cols_first]]
    sw.to_csv(os.path.join(out, f"swings_{C.LEAGUE}.csv"), index=False)
    gdf = pd.DataFrame(glog)
    used = pd.DataFrame([s.info for s in games])
    gdf = pd.concat([used.assign(status="used"), gdf[gdf["status"] != "used"]], ignore_index=True)
    gdf.to_csv(os.path.join(out, f"games_{C.LEAGUE}.csv"), index=False)
    at = kalshi_at_swings(sw, games)
    at.to_csv(os.path.join(out, f"kalshi_at_swings_{C.LEAGUE}.csv"), index=False)
    summ = {"all": summaries(sw, at)}
    for s_ in seasons:
        summ[str(s_)] = summaries(sw[sw["season"] == s_], at[at["season"] == s_])
    json.dump(summ, open(os.path.join(out, f"summaries_{C.LEAGUE}.json"), "w"), indent=2, default=str)
    open(os.path.join(out, f"summaries_{C.LEAGUE}.md"), "w", encoding="utf-8").write(summaries_md(summ))

    sig = used["sigma_game"]
    thr = {
        "league": C.LEAGUE, "seasons": seasons, "k_main": f"p{k_pct:g}", "steady_range_points": steady_range,
        "games_used": len(games), "games_used_by_season": {str(s_): int((used.season == s_).sum()) for s_ in seasons},
        "games_with_good_timestamps": n_good,
        "games_with_good_timestamps_by_season": {str(s_): int((used.good_timestamps & (used.season == s_)).sum())
                                                 for s_ in seasons},
        "games_not_used": gdf.loc[gdf.status != "used", "status"].value_counts().to_dict(),
        "timestamp_check_failures": used.loc[~used.good_timestamps, "timestamp_check"]
        .str.replace(r"[-+]?\d[\d.%]*", "#", regex=True).value_counts().to_dict(),
        "quiet_minutes": int(len(qz)), "k": {f"p{p:g}": round(v, 4) for p, v in ks.items()},
        "threshold_points_median_game": round(float(np.median(sig * k)), 3),
        "sigma_game": {"min": round(float(sig.min()), 3), "median": round(float(sig.median()), 3),
                       "max": round(float(sig.max()), 3)},
        "sigma_by_source": {
            "good timestamps (quiet minutes)": round(float(used.loc[used.good_timestamps, "sigma_game"].median()), 3),
            "no good timestamps (all minutes)": round(float(used.loc[~used.good_timestamps, "sigma_game"].median()), 3)
            if (~used.good_timestamps).any() else None},
        "league_median_sigma": round(league_med, 4),
        "games_floor": used.loc[used.sigma_note.str.contains("floor"), "event_ticker"].tolist(),
        "games_league_median": used.loc[used.sigma_note.str.contains("league median"), "event_ticker"].tolist(),
        "home_market_replaced_by_away": used.loc[used.source_market == "away", "event_ticker"].tolist(),
        "sensitivity": sens, "checks": checks,
        "n_med": {str(s_): C.N_MED[s_] for s_ in seasons},
        "rules": {"drop_if_prev_swing_after_before": C.DROP_IF_PREV_SWING_AFTER_BEFORE,
                  "settled_share": C.SETTLED_SHARE, "wp_source": "CFBD where pulled, else Kalshi mid the minute before"},
    }
    thr["plots"] = plots(games, sw, out, C.N_PLOTS)
    json.dump(thr, open(os.path.join(out, f"threshold_{C.LEAGUE}.json"), "w"), indent=2, default=str)
    open(os.path.join(out, f"threshold_{C.LEAGUE}.md"), "w", encoding="utf-8").write(threshold_md(thr))
    print(open(os.path.join(out, f"threshold_{C.LEAGUE}.md"), encoding="utf-8").read())


def pct(v):
    return "n/a" if v is None else f"{v:.1%}"


def threshold_md(t):
    c3, c5 = t["checks"][f"within_{C.MATCH_MIN}_min"], t["checks"]["within_5_min"]
    sens = "".join(f"| {p} | {v['k']:.3f} | {v['swings']} | {v['kept']} | {pct(v['catch_rate_3min'])} | "
                   f"{pct(v['match_rate_3min'])} |\n" for p, v in t["sensitivity"].items())
    bt = c3["by_type"]
    sig = t["sigma_game"]
    lines = [
        f"# Swing threshold (college, seasons {', '.join(map(str, t['seasons']))})", "",
        f"Games used: {t['games_used']} ({', '.join(f'{k} {v}' for k, v in t['games_used_by_season'].items())}). "
        f"With good play timestamps: {t['games_with_good_timestamps']} "
        f"({', '.join(f'{k} {v}' for k, v in t['games_with_good_timestamps_by_season'].items())}); "
        f"k comes from their {t['quiet_minutes']:,} quiet minutes.", "",
        f"Games not used: {json.dumps(t['games_not_used'])}.", "",
        f"Timestamp check failures: {json.dumps(t['timestamp_check_failures'])}.", "",
        "| Percentile | k | Swings | Kept | Catch rate (3 min) | Match rate (3 min) |", "|---|---|---|---|---|---|",
        sens,
        f"Main threshold: {t['k_main']} (steady range {t['steady_range_points']:g} points).", "",
        f"- Catch rate: {pct(c3['catch_rate'])} of {c3['plays_checked']:,} touchdowns and turnovers at 20-80% home "
        f"win probability (touchdowns {bt['touchdown']['caught']}/{bt['touchdown']['plays']}, turnovers "
        f"{bt['turnover']['caught']}/{bt['turnover']['plays']}). Win probability from CFBD for "
        f"{c3['wp_source']['cfbd']:,} plays, Kalshi midpoint for {c3['wp_source']['kalshi_mid']:,}. On the CFBD "
        f"win-probability sample alone: {pct(c3['catch_rate_cfbd_wp_sample'])} of {c3['plays_checked_cfbd_wp_sample']:,}.",
        f"- Match rate: {pct(c3['match_rate'])} of {c3['swings_checked']:,} swings in good-timestamp games have a "
        f"touchdown, field goal, turnover or failed fourth down within {C.MATCH_MIN} min of t (kept swings only: "
        f"{pct(c3['match_rate_kept'])}).",
        f"- Within 5 minutes: catch {pct(c5['catch_rate'])}, match {pct(c5['match_rate'])}.", "",
        f"sigma_game: min {sig['min']}, median {sig['median']}, max {sig['max']} points (good-timestamp games "
        f"{t['sigma_by_source']['good timestamps (quiet minutes)']}, others "
        f"{t['sigma_by_source']['no good timestamps (all minutes)']}). Threshold in the median game "
        f"{t['threshold_points_median_game']} points.", "",
        f"1-point floor used ({len(t['games_floor'])}): {', '.join(t['games_floor']) or 'none'}.", "",
        f"League-median sigma ({t['league_median_sigma']}) used in {len(t['games_league_median'])} games (under "
        f"{C.MIN_QUIET} usable minutes, mostly one-sided games outside 10-90). Home market replaced by the flipped "
        f"away market in {len(t['home_market_replaced_by_away'])} games. Both lists are in threshold_ncaaf.json and "
        f"games_ncaaf.csv (sigma_note, source_market).", "",
        f"n_med: {json.dumps(t['n_med'])}. Plots: {', '.join(t['plots'])}.", ""]
    return "\n".join(lines)


def summaries_md(s):
    def block(name, x):
        if not x:
            return f"## {name}\n\nNo swings.\n"
        mc, ms = x["median_cost_per_10"], x["median_spread_c"]
        p = x.get("paired_after_minus_before_cost_per_10", {})
        rows = "".join(f"| {k} | {v['swings']} | {v.get('median_cost_before')} | {v.get('median_cost_after')} | "
                       f"{v.get('median_abs_move', '')} | {v.get('median_minutes_to_settle', '')} |\n"
                       for k, v in x["by_play_type"].items())
        size = "".join(f"| {k} | {v['swings']} | {v['median_cost_before']} | {v['median_cost_after']} | "
                       f"{v['median_minutes_to_settle']} |\n" for k, v in x["by_swing_size"].items())
        return (f"## {name}\n\nSwings found {x['swings_found']}, kept {x['swings_kept']}. Dropped: "
                f"{json.dumps(x['dropped_by_reason'])}.\n\n"
                f"Median Kalshi cost per $10 (both teams, kept swings): before {mc['before']}, after {mc['after']}; "
                f"paired after minus before: median {p.get('median')}, mean {p.get('mean')} (n = {p.get('n')}). "
                f"Median spread: before {ms['before']}c, after {ms['after']}c.\n\n"
                f"Minutes to settle (t to after time, kept): median {x['median_minutes_to_settle_kept']}, "
                f"p25-p75 {x['minutes_to_settle_kept_p25_p75']}.\n\n"
                f"| Matched play | Swings | Cost before | Cost after | Median move | Minutes to settle |\n"
                f"|---|---|---|---|---|---|\n{rows}\n"
                f"| Swing size | Swings | Cost before | Cost after | Minutes to settle |\n|---|---|---|---|---|\n{size}\n")
    return "# Kalshi at swings: summaries (college)\n\n" + "".join(block(k if k != "all" else "Both seasons", v)
                                                                  for k, v in s.items())


def main():
    ap = argparse.ArgumentParser(description="Task 7 steps 1-5 and 7 (college)")
    ap.add_argument("--k-pct", type=float, default=C.K_PCT)
    ap.add_argument("--steady-range", type=float, default=C.STEADY_RANGE)
    a = ap.parse_args()
    run(a.k_pct, a.steady_range)


if __name__ == "__main__":
    main()
