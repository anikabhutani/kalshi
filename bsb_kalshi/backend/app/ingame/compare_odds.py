"""In-game NFL cost comparison: Kalshi vs DraftKings and FanDuel (Task 7 / paper Section 6).

Inputs
- The full in-game odds pull (odds_full_pull.py / pull_nfl_ingame_odds.py): every 5-minute Odds API snapshot,
  DraftKings and FanDuel moneylines, one row per snapshot x game x book x team.
- Kalshi minute tables from swings.py (kalshi_minutes_nfl_<season>.csv) and the swing list (swings_nfl.csv).

Definitions (the paper's shared terms, unchanged from the pregame study)
- Fair price: the Kalshi midpoint, for the team being bet.
- Price paid: Kalshi ask + fee (n_med = 24, fee rounded up to the cent); a book's price implied by its odds.
- Cost per $10 = $10 x (1 - fair / price paid). Extra cost per $10 = book cost - Kalshi cost, same game, team
  and snapshot.

When a row counts ("calm")
- Kalshi quote two-sided (not filled) and fair price between 10 and 90 (outside it the game is basically over).
- Kalshi's midpoint stayed within 2 points, its spread at 5c or less and no minute filled, from the book's own
  last update (or 1 minute before the snapshot, whichever is earlier) to the minute after the snapshot. Then
  the book price and Kalshi's price describe the same game situation, so the gap is cost, not timing.
  The 5-minute calm rule of the swing study was written before we knew the books' update times; in the data a
  book's last update is a median 22 s before the snapshot. The strict version (Kalshi calm for the 5 minutes
  before the snapshot as well) is reported as a robustness check (--strict reruns everything with it).

Results
1. All calm moments: median (and mean) extra cost per book, 95% interval from resampling whole games.
2. By fair price bucket and by time since kickoff.
3. Swing pairs: the snapshots at each kept swing's before and after times; after-swing book prices must have
   been updated after the swing. Paired after - before change per book.
4. Suspensions: share of in-game 5-minute snapshots in which a book listed no price for a live game, overall
   and in the snapshot right after a swing.

    cd backend && .venv/bin/python -m app.ingame.compare_odds --odds ~/Downloads/nfl_ingame_odds_2025_2026.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.task4.common import REPO_ROOT

DATA = REPO_ROOT / "data" / "ingame" / "nfl"
CALM_RANGE = 2.0
CALM_SPREAD = 5.0
FAIR_LO, FAIR_HI = 10.0, 90.0
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


def ts(s: pd.Series) -> np.ndarray:
    return (pd.to_datetime(s, utc=True).astype("int64") // 10**9).to_numpy() \
        if not pd.api.types.is_integer_dtype(s) else s.to_numpy()


def to_unix(s: pd.Series) -> np.ndarray:
    d = pd.to_datetime(s, utc=True, format="ISO8601")
    return np.array([int(x.timestamp()) if pd.notna(x) else -1 for x in d], dtype=np.int64)


def load_odds(path: Path) -> pd.DataFrame:
    cols = ["season", "season_type", "week", "game_id", "home", "away", "first_play_utc", "last_play_utc", "game_live",
            "minutes_since_first_play", "mark_utc", "snapshot_utc", "bookmaker", "bookmaker_last_update_utc",
            "bookmaker_age_sec", "market", "team", "american_odds", "implied_prob"]
    d = pd.read_csv(path, usecols=cols, low_memory=False)
    d = d[(d["game_live"] == True) & (d["market"] == "h2h") & d["game_id"].notna()].copy()  # noqa: E712
    d["team_code"] = d["team"].map(TEAMS)
    d["side"] = np.where(d["team_code"] == d["home"], "home", np.where(d["team_code"] == d["away"], "away", None))
    d = d[d["side"].notna()]
    d["snap_ts"] = to_unix(d["snapshot_utc"])
    d["mark_ts"] = to_unix(d["mark_utc"])
    d["upd_ts"] = to_unix(d["bookmaker_last_update_utc"])
    return d.reset_index(drop=True)


def load_kalshi(seasons: list[int]) -> dict[str, pd.DataFrame]:
    out = {}
    for s in seasons:
        m = pd.read_csv(DATA / "out" / f"kalshi_minutes_nfl_{s}.csv", low_memory=False,
                        usecols=["game_id", "ts", "bid", "ask", "mid", "spread", "filled", "cost_home_per10",
                                 "cost_away_per10"])
        for gid, x in m.groupby("game_id"):
            out[gid] = x.set_index("ts").sort_index()
    return out


def attach_kalshi(d: pd.DataFrame, kal: dict[str, pd.DataFrame], min_window_sec: int = 60) -> pd.DataFrame:
    """Kalshi at the minute ending at or before the snapshot, and the calm check over the book's window."""
    n = len(d)
    cols = {k: np.full(n, np.nan) for k in ("k_mid", "k_bid", "k_ask", "k_spread", "k_cost", "calm_range",
                                             "calm_max_spread")}
    status = np.full(n, "", dtype=object)
    filled = np.zeros(n, bool)
    for gid, idx in d.groupby("game_id").indices.items():
        k = kal.get(gid)
        if k is None:
            status[idx] = "no Kalshi data for the game"
            continue
        kts = k.index.to_numpy()
        kmid, kspread, kfill = k["mid"].to_numpy(), k["spread"].to_numpy(), k["filled"].to_numpy().astype(bool)
        sub = d.iloc[idx]
        for j, (s, u, side) in enumerate(zip(sub["snap_ts"], sub["upd_ts"], sub["side"])):
            i = idx[j]
            mk = s // 60 * 60
            pos = np.searchsorted(kts, mk)
            if pos >= len(kts) or kts[pos] != mk:
                status[i] = "no Kalshi minute at the snapshot"
                continue
            lo = min(mk - min_window_sec, (u // 60 * 60) if u > 0 else mk - 240)
            hi = mk + 60
            w = (kts >= lo) & (kts <= hi)
            mids = kmid[w]
            cols["calm_range"][i] = float(np.nanmax(mids) - np.nanmin(mids)) if len(mids) else np.nan
            cols["calm_max_spread"][i] = float(np.nanmax(kspread[w])) if len(mids) else np.nan
            filled[i] = bool(kfill[w].any()) or bool(kfill[pos])
            row = k.iloc[pos]
            if side == "home":
                mid, bid, ask, cost = row["mid"], row["bid"], row["ask"], row["cost_home_per10"]
            else:
                mid, bid, ask, cost = 100 - row["mid"], 100 - row["ask"], 100 - row["bid"], row["cost_away_per10"]
            cols["k_mid"][i], cols["k_bid"][i], cols["k_ask"][i] = mid, bid, ask
            cols["k_spread"][i], cols["k_cost"][i] = ask - bid, cost
    for k_, v in cols.items():
        d[k_] = v
    d["k_window_filled"] = filled
    d["fair"] = d["k_mid"] / 100
    d["book_cost"] = 10 * (1 - d["fair"] / d["implied_prob"])
    d["extra_cost"] = d["book_cost"] - d["k_cost"]
    reason = pd.Series(status, index=d.index)
    reason[(reason == "") & d["k_window_filled"]] = "Kalshi quote filled (one-sided) in the window"
    reason[(reason == "") & ((d["k_mid"] < FAIR_LO) | (d["k_mid"] > FAIR_HI))] = "fair price outside 10-90"
    reason[(reason == "") & (d["calm_range"] > CALM_RANGE + 1e-9)] = "Kalshi moved > 2 points in the window"
    reason[(reason == "") & (d["calm_max_spread"] > CALM_SPREAD + 1e-9)] = "Kalshi spread > 5c in the window"
    d["exclusion"] = reason
    d["calm"] = reason == ""
    return d


def boot_stat(x: pd.DataFrame, col: str, stat: str = "median") -> dict[str, Any]:
    """Point estimate on all rows; 95% interval resampling whole games."""
    f = np.nanmedian if stat == "median" else np.nanmean
    if len(x) == 0:
        return {"estimate": None, "ci95": [None, None], "rows": 0, "games": 0, "excludes_zero": False}
    est = float(f(x[col]))
    groups = [v[col].to_numpy() for _, v in x.groupby("game_id")]
    rng = np.random.default_rng(SEED)
    sims = np.empty(BOOT)
    for b in range(BOOT):
        pick = rng.integers(0, len(groups), len(groups))
        sims[b] = f(np.concatenate([groups[i] for i in pick]))
    lo, hi = np.percentile(sims, [2.5, 97.5])
    return {"estimate": round(est, 4), "ci95": [round(float(lo), 4), round(float(hi), 4)], "rows": int(len(x)),
            "games": int(x["game_id"].nunique()), "excludes_zero": bool(lo > 0 or hi < 0)}


def suspensions(d_all: pd.DataFrame, sw: pd.DataFrame) -> dict[str, Any]:
    """Share of in-game 5-minute snapshots where a book listed no price for a live game."""
    games = d_all.drop_duplicates("game_id")[["game_id", "first_play_utc", "last_play_utc"]]
    marks = np.sort(d_all["mark_ts"].unique())
    exp = []
    for gid, a, b in zip(games["game_id"], to_unix(games["first_play_utc"]), to_unix(games["last_play_utc"])):
        # snapshots taken while the game was live (snapshot ~37 s after the mark)
        exp += [(gid, m) for m in marks if a <= m + 37 <= b]
    e = pd.DataFrame(exp, columns=["game_id", "mark_ts"])
    out: dict[str, Any] = {"expected_game_snapshots": int(len(e))}
    after_swing = set()
    for _, r in sw.iterrows():
        nxt = (int(r["t_ts"]) // 300 + 1) * 300   # first snapshot mark after the swing minute
        after_swing.add((r["game_id"], nxt - 300 if nxt - 300 + 37 >= r["t_ts"] else nxt))
    for bk, name in BOOKS.items():
        have = set(map(tuple, d_all.loc[d_all["bookmaker"] == bk, ["game_id", "mark_ts"]].drop_duplicates().to_numpy()))
        miss = np.array([(g, m) not in have for g, m in zip(e["game_id"], e["mark_ts"])])
        aft = np.array([(g, m) in after_swing for g, m in zip(e["game_id"], e["mark_ts"])])
        out[name] = {"missing_share_all": round(float(miss.mean()), 4),
                     "missing_share_first_snapshot_after_swing": round(float(miss[aft].mean()), 4) if aft.any() else None,
                     "snapshots_after_swing": int(aft.sum())}
    return out


def swing_pairs(d: pd.DataFrame, sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    kept = sw[(sw["status"] == "kept")]
    if "on_list" in kept:
        kept = kept[kept["on_list"] == True]  # noqa: E712
    idx = d.set_index(["game_id", "mark_ts"]).sort_index()
    for _, r in kept.iterrows():
        for kind in ("before", "after"):
            t = int(r[f"{kind}_ts"])
            mark = (t - 60) // 300 * 300
            try:
                x = idx.loc[(r["game_id"], mark)]
            except KeyError:
                continue
            x = x.reset_index() if isinstance(x, pd.DataFrame) else x.to_frame().T.reset_index()
            for _, y in x.iterrows():
                stale = kind == "after" and y["upd_ts"] < int(r["t_ts"])
                rows.append({"swing_id": r["swing_id"], "game_id": r["game_id"], "kind": kind,
                             "bookmaker": y["bookmaker"], "side": y["side"], "extra_cost": y["extra_cost"],
                             "book_cost": y["book_cost"], "k_cost": y["k_cost"], "calm": y["calm"],
                             "stale_book": bool(stale), "matched_play": r.get("matched_play")})
    return pd.DataFrame(rows)


def overround(d: pd.DataFrame) -> pd.DataFrame:
    g = d.groupby(["game_id", "mark_ts", "bookmaker"])
    o = g["implied_prob"].sum().rename("overround").reset_index()
    o = o[g.size().to_numpy() == 2]
    o["overround"] -= 1
    return o


def charts(res: dict[str, Any], buckets: pd.DataFrame, pairs_tab: dict[str, Any], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from app.alignment.slide_charts import BG, DK, FD, GRID, KALSHI, LABEL, TICK

    col = {"FanDuel": FD, "DraftKings": DK, "Kalshi": KALSHI}

    def frame(ax, fig):
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(BG)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(colors=TICK, labelsize=11)
        ax.grid(axis="y", color=GRID, lw=1)
        ax.set_axisbelow(True)

    # 1. extra cost per $10 vs Kalshi, all calm moments
    fig, ax = plt.subplots(figsize=(8, 5), dpi=200)
    frame(ax, fig)
    names = list(BOOKS.values())
    ests = [res["extra_cost_median"][n]["estimate"] * 100 for n in names]
    lo = [res["extra_cost_median"][n]["ci95"][0] * 100 for n in names]
    hi = [res["extra_cost_median"][n]["ci95"][1] * 100 for n in names]
    ax.bar(names, ests, color=[col[n] for n in names], width=0.55)
    ax.errorbar(names, ests, yerr=[np.array(ests) - lo, np.array(hi) - ests], fmt="none", ecolor=LABEL, capsize=8, lw=1.5)
    for i, v in enumerate(ests):
        ax.text(i, hi[i] + 0.6, f"+{v:.1f}¢" if v >= 0 else f"{v:.1f}¢", ha="center", color=LABEL, fontsize=13,
                fontweight="bold")
    ax.axhline(0, color=TICK, lw=1)
    ax.set_ylabel("Extra cost per $10 vs Kalshi (cents)", color=TICK, fontsize=11)
    ax.set_title("In-game: extra cost per $10 vs Kalshi (median, 95% interval)", color=LABEL, fontsize=13)
    n = res["extra_cost_median"]["FanDuel"]
    fig.text(0.01, 0.01, f"NFL 2025-26, calm in-game moments; {n['games']} games, "
             f"{res['calm_rows']:,} book-team-snapshot rows. Fair = Kalshi midpoint; Kalshi at 24 contracts.",
             color=TICK, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "ingame_extra_cost.png", facecolor=BG)
    plt.close(fig)

    # 2. cost per $10 by fair price
    fig, ax = plt.subplots(figsize=(9, 5), dpi=200)
    frame(ax, fig)
    for name in ("Kalshi", "FanDuel", "DraftKings"):
        y = buckets[f"{name}_median"] * 100
        ax.plot(buckets["bucket"], y, marker="o", color=col[name], lw=2.5, label=name)
    ax.set_ylabel("Cost per $10 (cents, median)", color=TICK, fontsize=11)
    ax.set_xlabel("Fair chance of the team winning (Kalshi midpoint)", color=TICK, fontsize=11)
    ax.set_title("In-game cost per $10 by fair price", color=LABEL, fontsize=13)
    leg = ax.legend(frameon=False, fontsize=11)
    for t in leg.get_texts():
        t.set_color(LABEL)
    fig.tight_layout()
    fig.savefig(out / "ingame_cost_by_price.png", facecolor=BG)
    plt.close(fig)

    # 3. before vs after big swings
    if pairs_tab and all(pairs_tab[n][k]["estimate"] is not None for n in ("FanDuel", "DraftKings") for k in ("before", "after")):
        fig, ax = plt.subplots(figsize=(8, 5), dpi=200)
        frame(ax, fig)
        x = np.arange(2)
        for k, (name, off) in enumerate((("FanDuel", -0.18), ("DraftKings", 0.18))):
            vals = [pairs_tab[name][kind]["estimate"] * 100 for kind in ("before", "after")]
            ci = [pairs_tab[name][kind]["ci95"] for kind in ("before", "after")]
            ax.bar(x + off, vals, width=0.34, color=col[name], label=name)
            ax.errorbar(x + off, vals, yerr=[[v - c[0] * 100 for v, c in zip(vals, ci)],
                                              [c[1] * 100 - v for v, c in zip(vals, ci)]],
                        fmt="none", ecolor=LABEL, capsize=6, lw=1.3)
        ax.set_xticks(x, ["Before big play", "After big play"])
        ax.axhline(0, color=TICK, lw=1)
        ax.set_ylabel("Extra cost per $10 vs Kalshi (cents)", color=TICK, fontsize=11)
        ax.set_title("Extra cost right before and after big swings", color=LABEL, fontsize=13)
        leg = ax.legend(frameon=False, fontsize=11)
        for t in leg.get_texts():
            t.set_color(LABEL)
        fig.tight_layout()
        fig.savefig(out / "ingame_swings_before_after.png", facecolor=BG)
        plt.close(fig)


def run(odds_path: Path, seasons: list[int], strict: bool = False) -> int:
    out = DATA / ("compare_strict5min" if strict else "compare")
    out.mkdir(parents=True, exist_ok=True)
    d_all = load_odds(odds_path)
    kal = load_kalshi(seasons)
    d = attach_kalshi(d_all.copy(), kal, 240 if strict else 60)
    sw = pd.read_csv(DATA / "out" / "swings_nfl.csv")
    calm = d[d["calm"]]
    res: dict[str, Any] = {
        "live_rows": int(len(d)), "calm_rows": int(len(calm)), "calm_share": round(float(d["calm"].mean()), 4),
        "games_with_odds": int(d["game_id"].nunique()), "games_with_calm_rows": int(calm["game_id"].nunique()),
        "exclusions": d.loc[~d["calm"], "exclusion"].value_counts().to_dict(),
        "book_age_sec_median": float(d["bookmaker_age_sec"].median()),
        "extra_cost_median": {}, "extra_cost_mean": {}, "cost_per_10_median": {},
    }
    for bk, name in BOOKS.items():
        x = calm[calm["bookmaker"] == bk]
        res["extra_cost_median"][name] = boot_stat(x, "extra_cost", "median")
        res["extra_cost_mean"][name] = boot_stat(x, "extra_cost", "mean")
        res["cost_per_10_median"][name] = round(float(x["book_cost"].median()), 4)
        res["share_rows_book_cheaper_than_kalshi_" + name] = round(float((x["extra_cost"] < 0).mean()), 4)
    kal_rows = calm.drop_duplicates(["game_id", "snap_ts", "side"])
    res["cost_per_10_median"]["Kalshi"] = round(float(kal_rows["k_cost"].median()), 4)
    res["kalshi_spread_median_c"] = float(kal_rows["k_spread"].median())
    # by season
    res["by_season"] = {}
    for s, x in calm.groupby("season"):
        res["by_season"][str(int(s))] = {name: boot_stat(x[x["bookmaker"] == bk], "extra_cost")
                                         for bk, name in BOOKS.items()}
    # robustness: each book's own proportional de-vig as the fair price (removes book-vs-Kalshi disagreement)
    tot = calm.groupby(["game_id", "snap_ts", "bookmaker"])["implied_prob"].transform("sum")
    both = calm.groupby(["game_id", "snap_ts", "bookmaker"])["implied_prob"].transform("size") == 2
    cb = calm[both].assign(fair_b=calm.loc[both, "implied_prob"] / tot[both])
    cb["book_cost_b"] = 10 * (1 - cb["fair_b"] / cb["implied_prob"])
    k_paid = (cb["k_cost"] / 10 - 1) * -1   # = fair_kalshi / kalshi_paid -> kalshi_paid = fair_k / that
    cb["kalshi_paid"] = cb["fair"] / k_paid
    cb["k_cost_b"] = 10 * (1 - cb["fair_b"] / cb["kalshi_paid"])
    cb["extra_cost_b"] = cb["book_cost_b"] - cb["k_cost_b"]
    res["extra_cost_median_book_devig_ruler"] = {name: boot_stat(cb[cb["bookmaker"] == bk], "extra_cost_b")
                                                 for bk, name in BOOKS.items()}
    cb = cb.assign(bucket_b=pd.cut(cb["fair_b"] * 100, list(range(10, 100, 10)), right=False))
    res["book_devig_ruler_by_fair_price"] = {
        str(b): {name: round(float(x.loc[x["bookmaker"] == bk, "extra_cost_b"].median()), 4) for bk, name in BOOKS.items()}
        for b, x in cb.groupby("bucket_b", observed=True)}
    # overround
    o = overround(calm)
    res["book_overround_median"] = {BOOKS[b]: round(float(v), 4) for b, v in o.groupby("bookmaker")["overround"].median().items()}
    # buckets by fair price
    bins = list(range(10, 100, 10))
    calm = calm.assign(bucket=pd.cut(calm["k_mid"], bins, right=False, labels=[f"{a}-{a + 10}%" for a in bins[:-1]]))
    brow = []
    for b, x in calm.groupby("bucket", observed=True):
        r = {"bucket": str(b), "rows": int(len(x)), "games": int(x["game_id"].nunique()),
             "Kalshi_median": float(x.drop_duplicates(["game_id", "snap_ts", "side"])["k_cost"].median())}
        for bk, name in BOOKS.items():
            y = x[x["bookmaker"] == bk]
            r[f"{name}_median"] = float(y["book_cost"].median())
            r[f"{name}_extra_median"] = float(y["extra_cost"].median())
        brow.append(r)
    buckets = pd.DataFrame(brow)
    buckets.round(4).to_csv(out / "by_fair_price.csv", index=False)
    # by time since first play
    tb = pd.cut(calm["minutes_since_first_play"], [0, 60, 120, 180, 1000], right=False,
                labels=["0-60 min", "60-120 min", "120-180 min", "180+ min"])
    res["by_minutes_since_kickoff"] = {
        str(lab): {name: round(float(x.loc[x["bookmaker"] == bk, "extra_cost"].median()), 4) for bk, name in BOOKS.items()}
        | {"rows": int(len(x))} for lab, x in calm.groupby(tb, observed=True)}
    # swing pairs
    p = swing_pairs(d, sw)
    pairs_tab: dict[str, Any] = {}
    if len(p):
        p.to_csv(out / "swing_pairs.csv", index=False)
        usable = p[p["calm"] & ~p["stale_book"]]
        res["swing_pairs"] = {"rows": int(len(p)), "usable_rows": int(len(usable)),
                              "dropped_not_calm": int((~p["calm"]).sum()),
                              "dropped_stale_after": int((p["calm"] & p["stale_book"]).sum())}
        for bk, name in BOOKS.items():
            pairs_tab[name] = {kind: boot_stat(usable[(usable["bookmaker"] == bk) & (usable["kind"] == kind)], "extra_cost")
                               for kind in ("before", "after")}
            pv = usable[usable["bookmaker"] == bk].pivot_table(index=["swing_id", "side", "game_id"], columns="kind",
                                                               values="extra_cost").dropna().reset_index()
            if len(pv) and {"before", "after"} <= set(pv.columns):
                pv["chg"] = pv["after"] - pv["before"]
                pairs_tab[name]["paired_after_minus_before"] = boot_stat(pv, "chg")
        res["swing_pairs"]["by_book"] = pairs_tab
    res["suspensions"] = suspensions(d_all, sw[sw["status"] == "kept"])
    (out / "summary.json").write_text(json.dumps(res, indent=2, default=str))
    keep = ["season", "week", "game_id", "snapshot_utc", "minutes_since_first_play", "bookmaker", "team", "side",
            "american_odds", "implied_prob", "bookmaker_age_sec", "k_bid", "k_ask", "k_mid", "k_cost", "book_cost",
            "extra_cost", "calm_range", "calm", "exclusion"]
    d[keep].round(4).to_csv(out / "ingame_rows.csv.gz", index=False, compression="gzip")
    charts(res, buckets, pairs_tab, out)
    print(json.dumps({k: v for k, v in res.items() if k not in ("by_minutes_since_kickoff",)}, indent=1, default=str))
    print(buckets.round(3).to_string())
    print(json.dumps(res["by_minutes_since_kickoff"], indent=0))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="In-game NFL cost comparison (Kalshi vs DraftKings, FanDuel)")
    ap.add_argument("--odds", type=Path, required=True)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026])
    ap.add_argument("--strict", action="store_true", help="robustness: Kalshi calm for the 5 minutes before the snapshot")
    a = ap.parse_args(argv)
    return run(a.odds, a.seasons, a.strict)


if __name__ == "__main__":
    raise SystemExit(main())
