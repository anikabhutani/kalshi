"""Results tables, plain charts and self-checks for Task 4, one set per NFL season.

Reads ``data/task4/snapshots.csv.gz`` (written by ``sportsbook_backfill``) and, for every season
in ``common.SEASONS`` (2025 and 2026), writes:

data/task4/results/<season>/
    costs_all_snapshots.csv   every game / book / market / snapshot: both sides, vig, cost per $10
    costs_all_sides.csv       the same split into sides, with the Pinnacle-referenced cost
    qc_issues.csv             every quality check issue, one row each
    qc_summary.csv            issue counts by check and book
    by_book_market.csv        closing lines: cost per $10 by book and market type
    by_price_group.csv        closing lines: cost per $10 by book, market and price group
    by_week.csv               closing lines: cost per $10 by book, market and NFL week
    by_time_to_kickoff.csv    all pre-kickoff snapshots: cost per $10 by time before kickoff
    favorites_longshots.csv   closing moneylines: favorites vs underdogs vs longshots
    kalshi_info.json          whether Kalshi was added, from where, and how it was lined up
    kalshi_all_strikes.csv    Kalshi main line vs every strike (why the two averages differ)
    facts.json                counts the chart notes and page text are built from
    checks.json               the self-checks (see ``checks.py``) and their results
    summary.md                the headline numbers (no conclusions; those are yours to write)
data/task4/charts/<season>/*.png
data/task4/results/index.json  seasons, game counts and check status

Kalshi rows come from Task 3's API data (see ``app/task4/kalshi.py`` for how they are matched).

"Closing line" = the last snapshot before kickoff; how far before is in ``facts.json``.
Time-to-kickoff averages are taken per game first, then across games, so games with more
snapshots do not count more. No number in a chart note is typed in: they all come from facts.

Command line (exit code 1 if any self-check fails; the results are still written)::

    cd backend && .venv/bin/python -m app.task4.sportsbook_report
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.task4 import kalshi as kalshi_mod
from app.task4.common import (
    BOOKS,
    CHARTS_DIR,
    GAMES,
    MARKET_LABELS,
    MARKETS,
    RESULTS_DIR,
    SEASONS,
    SNAPSHOTS,
    season_start,
    week_label,
)
from app.task4.sportsbook_costs import (
    PRICE_GROUPS,
    PRICE_GROUP_LABELS,
    TIME_BUCKETS,
    QC_CHECKS,
    TIME_BUCKET_LABELS,
    closing_lines,
    compute,
)

BOOK_COLORS = {"DraftKings": "#2f6f3e", "FanDuel": "#1f5fa8", "Pinnacle": "#9a4a1c", "Kalshi": "#6a3d9a"}
SPORTSBOOKS_ONLY = ("DraftKings", "FanDuel")  # the books priced against Pinnacle
SHORT_ROUND = {"Wild Card": "WC", "Divisional": "DIV", "Conference": "CONF", "Super Bowl": "SB"}


def stats(df: pd.DataFrame, by: list[str], col: str = "cost_per_10") -> pd.DataFrame:
    g = df.groupby(by, observed=True)[col]
    out = g.agg(n="count", mean="mean", median="median", min="min", max="max").reset_index()
    return out.round(4)


def _round(df: pd.DataFrame) -> pd.DataFrame:
    num = df.select_dtypes("number").columns
    return df.assign(**{c: df[c].round(6) for c in num})


def build_tables(r: dict[str, pd.DataFrame], kalshi: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    markets = r["markets"]
    good = markets[~markets["has_bad_odds"]]
    sides = r["sides"]
    sides = sides[sides["market_snapshot_id"].isin(good["market_snapshot_id"])]
    close = closing_lines(good)
    close_sides = sides[sides["market_snapshot_id"].isin(close["market_snapshot_id"])]

    t: dict[str, pd.DataFrame] = {}
    by_bm = stats(close, ["bookmaker", "market"])
    by_bm = by_bm.merge(
        stats(close, ["bookmaker", "market"], "overround")[["bookmaker", "market", "mean"]]
        .rename(columns={"mean": "mean_overround"}),
        on=["bookmaker", "market"],
    ).merge(
        stats(close, ["bookmaker", "market"], "cost_per_10_proportional")[["bookmaker", "market", "mean"]]
        .rename(columns={"mean": "mean_cost_proportional"}),
        on=["bookmaker", "market"],
    )
    t["by_book_market"] = by_bm

    pg = stats(close_sides, ["bookmaker", "market", "price_group"])
    pg_pin = stats(close_sides.dropna(subset=["cost_vs_pinnacle_per_10"]),
                   ["bookmaker", "market", "price_group"], "cost_vs_pinnacle_per_10")
    t["by_price_group"] = pg.merge(
        pg_pin[["bookmaker", "market", "price_group", "n", "mean"]].rename(
            columns={"n": "n_vs_pinnacle", "mean": "mean_cost_vs_pinnacle"}),
        on=["bookmaker", "market", "price_group"], how="left",
    ).merge(
        stats(close_sides, ["bookmaker", "market", "price_group"], "cost_per_10_proportional")[
            ["bookmaker", "market", "price_group", "mean"]].rename(columns={"mean": "mean_cost_proportional"}),
        on=["bookmaker", "market", "price_group"], how="left",
    )

    t["by_week"] = stats(close, ["bookmaker", "market", "week"])

    pre = good[good["pre_kickoff"]]
    per_game = (pre.groupby(["bookmaker", "market", "time_bucket", "event_id"], observed=True)
                [["cost_per_10", "overround"]].mean().reset_index())
    tk = per_game.groupby(["bookmaker", "market", "time_bucket"], observed=True).agg(
        games=("event_id", "nunique"), mean_cost_per_10=("cost_per_10", "mean"),
        mean_overround=("overround", "mean")).reset_index()
    tk["time_bucket"] = pd.Categorical(tk["time_bucket"], TIME_BUCKET_LABELS[::-1], ordered=True)
    t["by_time_to_kickoff"] = tk.sort_values(["bookmaker", "market", "time_bucket"]).round(4)

    ml = close_sides[close_sides["market"] == "h2h"].copy()
    ml["group"] = np.where(ml["fair_prob"] < 0.25, "longshot (<25%)", ml["role"])
    fl = ml.groupby(["bookmaker", "group"]).agg(
        n=("fair_prob", "count"),
        mean_fair_prob=("fair_prob", "mean"),
        mean_cost_per_10=("cost_per_10", "mean"),
        n_vs_pinnacle=("cost_vs_pinnacle_per_10", "count"),
        mean_cost_vs_pinnacle=("cost_vs_pinnacle_per_10", "mean"),
        sd_cost_vs_pinnacle=("cost_vs_pinnacle_per_10", "std"),
        mean_cost_proportional=("cost_per_10_proportional", "mean"),
        mean_cost_vs_pinnacle_proportional=("cost_vs_pinnacle_proportional", "mean"),
    ).reset_index()
    t["favorites_longshots"] = fl.round(4)

    qc = r["qc"]
    summary = qc.groupby(["check", "bookmaker"]).agg(
        issues=("event_id", "size"), games=("event_id", "nunique")).reset_index()
    found = set(summary["check"])
    zero = pd.DataFrame({"check": [c for c in QC_CHECKS if c not in found],
                         "bookmaker": "all", "issues": 0, "games": 0})
    t["qc_summary"] = pd.concat([summary, zero], ignore_index=True)
    t["qc_issues"] = qc
    t["costs_all_snapshots"] = _round(markets.drop(columns=["market_snapshot_id"]))
    t["costs_all_sides"] = _round(r["sides"].drop(columns=["market_snapshot_id"]))
    t["_close"] = close
    add_kalshi(t, kalshi)
    t["by_week"]["week_label"] = t["by_week"]["week"].map(week_label)
    return t


def _per_game(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Average Kalshi rows per game first, so a game with more strikes or sides counts once."""
    return df.groupby(keys + ["event_id"], observed=True)["cost_per_10"].mean().reset_index()


def add_kalshi(t: dict[str, pd.DataFrame], k: pd.DataFrame | None) -> None:
    """Append Kalshi rows (from Task 3's API data) to the comparable result tables."""
    info: dict = {"available": k is not None and not k.empty, "source": str(kalshi_mod.KALSHI_EXPORTS),
                  "closing_checkpoint": kalshi_mod.CLOSING_CHECKPOINT, "size_contracts": kalshi_mod.SIZE}
    if not info["available"]:
        info["note"] = "No Task 3 exports found. Run Task 3 (list, download, analyze) to add Kalshi."
        t["_kalshi_info"] = info
        t["kalshi_all_strikes"] = pd.DataFrame()
        return
    main = k[k["main_line"]]
    close = main[main["checkpoint"] == kalshi_mod.CLOSING_CHECKPOINT]
    kb = "bookmaker"

    pg = _per_game(close, [kb, "market"])
    bm = stats(pg, [kb, "market"]).assign(mean_overround=np.nan, mean_cost_proportional=np.nan)
    t["by_book_market"] = pd.concat([t["by_book_market"], bm], ignore_index=True)

    sides = close.assign(price_group=pd.cut(close["fair_prob"], PRICE_GROUPS, labels=PRICE_GROUP_LABELS,
                                            include_lowest=True))
    pgr = stats(sides, [kb, "market", "price_group"]).assign(n_vs_pinnacle=np.nan, mean_cost_vs_pinnacle=np.nan)
    t["by_price_group"] = pd.concat([t["by_price_group"], pgr], ignore_index=True)

    wk = stats(_per_game(close, [kb, "market", "week"]), [kb, "market", "week"])
    t["by_week"] = pd.concat([t["by_week"], wk], ignore_index=True)

    timed = main.assign(time_bucket=pd.cut(main["minutes_to_kickoff"], TIME_BUCKETS,
                                           labels=TIME_BUCKET_LABELS, right=True, include_lowest=True))
    tg = _per_game(timed, [kb, "market", "time_bucket"])
    tk = tg.groupby([kb, "market", "time_bucket"], observed=True).agg(
        games=("event_id", "nunique"), mean_cost_per_10=("cost_per_10", "mean")).reset_index()
    tk["mean_overround"] = np.nan
    tk["time_bucket"] = pd.Categorical(tk["time_bucket"], TIME_BUCKET_LABELS[::-1], ordered=True)
    t["by_time_to_kickoff"] = pd.concat([t["by_time_to_kickoff"], tk.round(4)], ignore_index=True)

    ml = close[close["market"] == "h2h"].copy()
    ml["group"] = np.where(ml["fair_prob"] < 0.25, "longshot (<25%)",
                           np.where(ml["fair_prob"] > 0.5, "favorite", "underdog"))
    fl = ml.groupby([kb, "group"]).agg(
        n=("fair_prob", "count"), mean_fair_prob=("fair_prob", "mean"),
        mean_cost_per_10=("cost_per_10", "mean")).reset_index()
    fl["n_vs_pinnacle"] = 0
    fl["mean_cost_vs_pinnacle"] = np.nan
    t["favorites_longshots"] = pd.concat([t["favorites_longshots"], fl.round(4)], ignore_index=True)

    allc = k[k["checkpoint"] == kalshi_mod.CLOSING_CHECKPOINT]
    cmp = pd.concat([
        stats(_per_game(close, ["market"]), ["market"]).assign(rows="main line only (used in charts)"),
        stats(_per_game(allc, ["market"]), ["market"]).assign(rows="every strike, Yes and No"),
    ], ignore_index=True)
    t["kalshi_all_strikes"] = cmp[["market", "rows", "n", "mean", "median", "min", "max"]]
    info.update({
        "games_by_market": {m: int(close.loc[close["market"] == m, "event_id"].nunique())
                            for m in ("h2h", "spreads", "totals")},
        "first_kickoff": str(k["kickoff"].min()), "last_kickoff": str(k["kickoff"].max()),
        "exports_modified": pd.Timestamp((kalshi_mod.KALSHI_EXPORTS / "checkpoint_costs.csv").stat().st_mtime,
                                         unit="s", tz="UTC").isoformat()
        if (kalshi_mod.KALSHI_EXPORTS / "checkpoint_costs.csv").exists() else None,
    })
    t["_kalshi_info"] = info


# --------------------------------------------------------------------------------------
# Charts (plain matplotlib)
# --------------------------------------------------------------------------------------


def _books(table: pd.DataFrame) -> list[str]:
    """The books that appear in a table, in a fixed order (Kalshi last, when present)."""
    present = set(table["bookmaker"])
    return [b for b in (*BOOKS, kalshi_mod.KALSHI) if b in present]


def _bars(ax, table: pd.DataFrame, cats: list[str], col: str, cat_col: str) -> None:
    books = _books(table.dropna(subset=[col]))
    width = 0.8 / max(1, len(books))
    x = np.arange(len(cats))
    for i, book in enumerate(books):
        sub = table[table["bookmaker"] == book].set_index(cat_col)[col]
        vals = [sub.get(c, np.nan) for c in cats]
        bars = ax.bar(x + (i - (len(books) - 1) / 2) * width, vals, width, label=book, color=BOOK_COLORS[book])
        for b, v in zip(bars, vals):
            if pd.notna(v):
                ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom",
                        fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    ax.margins(y=0.25)
    ax.grid(axis="y", alpha=0.3)


def _pyplot():
    """matplotlib is imported only when PNGs are drawn, so the app starts without it."""
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["text.parse_math"] = False  # "$10" is money, not math
    import matplotlib.pyplot as plt

    return plt


# --------------------------------------------------------------------------------------
# Facts: every count a chart note or the page quotes, computed from the season's data
# --------------------------------------------------------------------------------------


def _int_map(s: pd.Series) -> dict:
    return {str(k): int(v) for k, v in s.items()}


def build_facts(t: dict[str, pd.DataFrame], season: int, games: pd.DataFrame) -> dict:
    """Counts and ranges for one season. Chart notes and the page use these, never typed numbers."""
    close = t["_close"]
    tk = t["by_time_to_kickoff"]
    pg = t["by_price_group"]
    fl = t["favorites_longshots"]
    sportsbooks = list(BOOKS)
    week_games = games.groupby("week").size()
    median_week = float(week_games.median()) if len(week_games) else 0.0
    last_week = int(week_games.index.max()) if len(week_games) else None
    regular = games[games["week"] <= 18]
    playoffs = games[games["week"] > 18]
    longshot = fl[(fl["group"] == "longshot (<25%)") & fl["bookmaker"].isin(sportsbooks)]["n"]
    tk_ml = tk[(tk["market"] == "h2h") & tk["bookmaker"].isin(sportsbooks)]
    return {
        "season": season,
        "label": f"{season} season",
        "games": int(close["event_id"].nunique()),
        "games_listed": int(len(games)),
        "regular_season_games": int(len(regular)),
        "playoff_games": int(len(playoffs)),
        "first_kickoff": close["commence_time"].min().isoformat() if len(close) else None,
        "last_kickoff": close["commence_time"].max().isoformat() if len(close) else None,
        "closing_minutes_min": round(float(close["minutes_to_kickoff"].min()), 1) if len(close) else None,
        "closing_minutes_max": round(float(close["minutes_to_kickoff"].max()), 1) if len(close) else None,
        "games_by_book_at_close": _int_map(close.groupby("bookmaker")["event_id"].nunique()),
        "time_bucket_games": {b: _int_map(tk_ml[tk_ml["bookmaker"] == b].set_index("time_bucket")["games"])
                              for b in sportsbooks},
        "price_group_sides": {b: _int_map(pg[(pg["bookmaker"] == b) & (pg["market"] == "h2h")]
                                         .set_index("price_group")["n"]) for b in sportsbooks},
        "longshot_sides_min": int(longshot.min()) if len(longshot) else 0,
        "longshot_sides_max": int(longshot.max()) if len(longshot) else 0,
        "weeks": [{"week": int(w), "label": week_label(w), "games": int(n)} for w, n in week_games.items()],
        "last_week": week_label(last_week) if last_week is not None else None,
        "last_week_games": int(week_games.iloc[-1]) if len(week_games) else 0,
        # a week with under half the usual number of games is still in progress (or a playoff round)
        "last_week_partial": bool(last_week is not None and last_week <= 18
                                  and week_games.iloc[-1] < median_week / 2),
        "kalshi": t["_kalshi_info"],
    }


def _bucket_note(facts: dict, order: list[str]) -> str:
    """Which books cover fewer than all games in some time bucket, worded from the data."""
    total = facts["games"]
    parts = []
    for book, buckets in facts["time_bucket_games"].items():
        thin = [f"{b} {buckets.get(b, 0)}" for b in order if buckets.get(b, 0) < total]
        if thin:
            parts.append(f"{book} has fewer than {total} games in: " + ", ".join(thin))
    return ("; ".join(parts) + ".") if parts else f"Every sportsbook covers all {total} games in every bucket."


# --------------------------------------------------------------------------------------
# Charts (plain matplotlib)
# --------------------------------------------------------------------------------------


def charts(t: dict[str, pd.DataFrame], facts: dict, out_dir: Path) -> list[str]:
    plt = _pyplot()
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    tag = facts["label"]
    games = facts["games"]
    kalshi_on = bool(facts["kalshi"].get("available"))
    closing = (f"closing line = last snapshot before kickoff, {facts['closing_minutes_min']:g}-"
               f"{facts['closing_minutes_max']:g} min out")

    def save(fig, name):
        fig.savefig(out_dir / name, dpi=150)
        plt.close(fig)
        made.append(name)

    # 1. Book x market
    fig, ax = plt.subplots(figsize=(8, 4.5))
    tbl = t["by_book_market"].assign(label=lambda d: d["market"].map(MARKET_LABELS))
    _bars(ax, tbl, [MARKET_LABELS[m] for m in MARKETS], "mean", "label")
    ax.set_ylabel("Cost per $10 bet ($)")
    ax.set_title(f"{tag}: cost per $10 at the closing line, by book and market", fontsize=10)
    ax.legend(loc="upper center", ncol=4, fontsize=8)
    fig.text(0.01, 0.01, f"{games} games; {closing}."
             + (" Kalshi: 15 min before, main line, 10 contracts." if kalshi_on else ""), fontsize=8)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save(fig, "1_cost_by_book_market.png")

    # 2. Price group (moneyline), own fair price and Pinnacle's fair price
    pg = t["by_price_group"]
    pg = pg[pg["market"] == "h2h"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    _bars(axes[0], pg, PRICE_GROUP_LABELS, "mean", "price_group")
    axes[0].set_title("Moneyline: cost vs the book's own fair price (Shin)")
    axes[0].set_xlabel("Fair win probability of the side bet (Shin)")
    axes[0].set_ylabel("Cost per $10 bet ($)")
    _bars(axes[1], pg[pg["bookmaker"].isin(SPORTSBOOKS_ONLY)].assign(
        mean=lambda d: d["mean_cost_vs_pinnacle"]), PRICE_GROUP_LABELS, "mean", "price_group")
    axes[1].set_title("Moneyline: cost vs Pinnacle's fair price (Shin)")
    axes[1].set_xlabel("Fair win probability of the side bet (Shin)")
    axes[1].axhline(0, color="black", lw=0.8)
    axes[0].legend(loc="upper center", ncol=4, fontsize=8)
    ns = facts["price_group_sides"].get("DraftKings", {})
    fig.text(0.01, 0.01, "Bets per group (DraftKings): " + ", ".join(
        f"{g} n={ns.get(g, 0)}" for g in PRICE_GROUP_LABELS) +
        ". Groups under 20 bets are noisy." + (" Kalshi is grouped by its mid price." if kalshi_on else ""),
        fontsize=8)
    fig.suptitle(f"{tag}: cost per $10 by price group (closing lines)")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save(fig, "2_cost_by_price_group.png")

    # 3. Week (regular season, then playoff rounds)
    wk = t["by_week"]
    weeks = sorted(wk["week"].unique())
    labels = [week_label(w) for w in weeks]
    fig, axes = plt.subplots(1, 3, figsize=(15 if len(weeks) > 8 else 13, 4.2), sharey=True)
    for ax, m in zip(axes, MARKETS):
        for book in _books(wk):
            d = wk[(wk["bookmaker"] == book) & (wk["market"] == m)].set_index("week")["mean"]
            ax.plot(range(len(weeks)), [d.get(w, np.nan) for w in weeks], marker="o", ms=3,
                    label=book, color=BOOK_COLORS[book])
        ax.set_title(MARKET_LABELS[m])
        ax.set_xlabel("NFL week")
        ax.set_xticks(range(len(weeks)))
        ax.set_xticklabels([SHORT_ROUND.get(lab, lab) for lab in labels],
                           rotation=90 if len(weeks) > 8 else 0, fontsize=7)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Cost per $10 bet ($)")
    axes[0].legend(fontsize=8)
    note = (f"Last week shown ({facts['last_week']}) has {facts['last_week_games']} game"
            f"{'' if facts['last_week_games'] == 1 else 's'} so far."
            if facts["last_week_partial"] else "")
    if facts["playoff_games"]:
        note += (f" Playoffs: WC = Wild Card, DIV = Divisional, CONF = Conference, SB = Super Bowl "
                 f"({facts['playoff_games']} games).")
    fig.text(0.01, 0.01, note.strip(), fontsize=8)
    fig.suptitle(f"{tag}: cost per $10 at the closing line, by week")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    save(fig, "3_cost_by_week.png")

    # 4. Time to kickoff
    tk = t["by_time_to_kickoff"]
    order = TIME_BUCKET_LABELS[::-1]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
    for ax, m in zip(axes, MARKETS):
        for book in _books(tk):
            d = tk[(tk["bookmaker"] == book) & (tk["market"] == m)].set_index("time_bucket")
            y = [d["mean_cost_per_10"].get(b, np.nan) for b in order]
            ax.plot(order, y, marker="o", label=book, color=BOOK_COLORS[book])
        ax.set_title(MARKET_LABELS[m])
        ax.set_xlabel("Time before kickoff")
        ax.tick_params(axis="x", rotation=30)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Cost per $10 bet ($)")
    axes[0].legend(fontsize=8)
    note = "Moneyline games per bucket. " + _bucket_note(facts, order)
    if kalshi_on:
        note += " Kalshi (Task 3) has quotes only at 24 h, 3 h, 1 h and 15 min before kickoff."
    fig.text(0.01, 0.01, note, fontsize=8, wrap=True)
    fig.suptitle(f"{tag}: how cost per $10 changes as kickoff gets closer (games averaged equally)")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    save(fig, "4_cost_vs_time_to_kickoff.png")

    # 5. Favorites vs longshots
    fl = t["favorites_longshots"]
    groups = ["favorite", "underdog", "longshot (<25%)"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    _bars(axes[0], fl.rename(columns={"mean_cost_per_10": "v"}), groups, "v", "group")
    axes[0].set_title("Cost vs the book's own fair price (Shin)")
    axes[0].set_ylabel("Cost per $10 bet ($)")
    _bars(axes[1], fl[fl["bookmaker"].isin(SPORTSBOOKS_ONLY)].rename(columns={"mean_cost_vs_pinnacle": "v"}),
          groups, "v", "group")
    axes[1].set_title("Cost vs Pinnacle's fair price (Shin)")
    axes[1].axhline(0, color="black", lw=0.8)
    axes[0].legend(loc="upper center", ncol=4, fontsize=8)
    fig.text(0.01, 0.01, f"Longshot bets per sportsbook: {facts['longshot_sides_min']}-"
             f"{facts['longshot_sides_max']}. Small groups swing widely game to game.", fontsize=8)
    fig.suptitle(f"{tag}: moneyline favorites vs underdogs vs longshots (closing; longshots are also underdogs)")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save(fig, "5_favorites_vs_longshots.png")
    return made


def _md(df: pd.DataFrame, index: bool = False) -> str:
    try:
        return df.to_markdown(index=index)
    except ImportError:  # tabulate not installed
        return "```\n" + df.to_string(index=index) + "\n```"


def _tally(checks: list[dict]) -> str:
    counts = {s: sum(c["status"] == s for c in checks) for s in ("pass", "warn", "skip", "fail")}
    return ", ".join(f"{n} {s}" for s, n in counts.items() if n) or "none"


def write_summary(t: dict[str, pd.DataFrame], facts: dict, checks: list[dict]) -> str:
    k = facts["kalshi"]
    failed = [c for c in checks if c["status"] == "fail"]
    lines = [
        f"# Task 4: NFL sportsbook cost per $10, {facts['label']} (numbers only)",
        "",
        f"Games: {facts['games']} ({facts['regular_season_games']} regular season, "
        f"{facts['playoff_games']} playoff), kickoff {facts['first_kickoff'][:10]} to "
        f"{facts['last_kickoff'][:10]}. Books: {', '.join(BOOKS)}. Closing line = last snapshot before "
        f"kickoff ({facts['closing_minutes_min']:g}-{facts['closing_minutes_max']:g} min out).",
        "Cost per $10 = expected loss on a $10 bet at the fair price (Shin's method; the market figure "
        "averages its two sides). Proportional-method results are in the *_proportional columns.",
        "",
        f"Self-checks: {_tally(checks)}"
        + (f"; FAILED: {', '.join(c['title'] for c in failed)}" if failed else "") + " (checks.json).",
        "",
        "## Closing lines by book and market",
        "",
        _md(t["by_book_market"][["bookmaker", "market", "n", "mean", "median", "min", "max",
                                 "mean_overround"]]),
        "",
        "## Favorites vs underdogs (moneyline, closing)",
        "",
        _md(t["favorites_longshots"]),
        "",
        "## Time before kickoff (mean cost per $10, games averaged equally)",
        "",
        t["by_time_to_kickoff"].pivot_table(index=["bookmaker", "market"], columns="time_bucket",
                                            values="mean_cost_per_10", observed=True)
        .round(3).pipe(_md, index=True),
        "",
        "## Kalshi (from Task 3's API data)",
        "",
        (f"Added: 15-minute quote, main line (strike nearest 50 cents for spreads and totals), "
         f"10 contracts. Games: {k.get('games_by_market')} of {facts['games']}."
         if k["available"] else k["note"]),
        "",
        _md(t["kalshi_all_strikes"]) if k["available"] else "",
        "",
        "## Quality check",
        "",
        _md(t["qc_summary"]),
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Seasons
# --------------------------------------------------------------------------------------


def split_season(r: dict[str, pd.DataFrame], season: int) -> dict[str, pd.DataFrame]:
    """The computed tables restricted to one season's games (QC rows follow their game)."""
    markets = r["markets"]
    events = set(markets.loc[markets["season"] == season, "event_id"])
    out = {
        "markets": markets[markets["event_id"].isin(events)].copy(),
        "sides": r["sides"][r["sides"]["event_id"].isin(events)].copy(),
        "sides_raw": r["sides_raw"][r["sides_raw"]["event_id"].isin(events)].copy(),
        "qc": r["qc"][r["qc"]["event_id"].isin(events)].copy(),
    }
    return out


def season_window(season: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """[Tuesday before this season's opener, Tuesday before the next one) in UTC."""
    lo = pd.Timestamp(season_start(season)).tz_localize("America/New_York").tz_convert("UTC")
    hi = pd.Timestamp(season_start(season + 1)).tz_localize("America/New_York").tz_convert("UTC")
    return lo, hi


def _clear(path: Path) -> None:
    """Remove a season folder's old output, and files left in the flat layout of earlier versions."""
    if path.exists():
        shutil.rmtree(path)


def run_season(r: dict[str, pd.DataFrame], season: int, games: pd.DataFrame,
               manifest: dict) -> dict:
    from app.task4 import checks as checks_mod

    rs = split_season(r, season)
    season_games = games[games["season"] == season].copy()
    if rs["markets"].empty:
        return {"season": season, "games": 0, "checks_failed": 0, "checks": 0, "skipped": True}
    lo, hi = season_window(season)
    k = kalshi_mod.load(kickoff_range=(lo, hi - pd.Timedelta(seconds=1)))
    t = build_tables(rs, k)
    if not t["_kalshi_info"]["available"]:
        t["_kalshi_info"]["note"] = (
            "Task 3 has no Kalshi games in this season's dates."
            if (kalshi_mod.KALSHI_EXPORTS / "checkpoint_costs.csv").exists()
            else "No Task 3 exports found. Run Task 3 (list, download, analyze) to add Kalshi.")
    facts = build_facts(t, season, season_games)
    checks = checks_mod.run_checks(season, t, rs, facts, season_games, manifest, r)

    out = RESULTS_DIR / str(season)
    _clear(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in t.items():
        if not name.startswith("_"):
            df.to_csv(out / f"{name}.csv", index=False)
    (out / "kalshi_info.json").write_text(json.dumps(t["_kalshi_info"], indent=2, default=str))
    (out / "facts.json").write_text(json.dumps(facts, indent=2, default=str))
    (out / "checks.json").write_text(json.dumps(checks, indent=2, default=str))
    (out / "summary.md").write_text(write_summary(t, facts, checks))
    chart_dir = CHARTS_DIR / str(season)
    _clear(chart_dir)
    try:
        made = charts(t, facts, chart_dir)
    except ModuleNotFoundError as exc:
        made = []
        print(f"{season}: PNG charts skipped ({exc}); run: pip install -r requirements.txt")
    failed = [c for c in checks if c["status"] == "fail"]
    print(f"{season}: {facts['games']} games, {len(made)} charts, self-checks: {_tally(checks)}"
          + "".join(f"\n  {c['status'].upper()} {c['title']}: {c['detail']}"
                    for c in checks if c["status"] in ("fail", "warn")))
    return {"season": season, "games": facts["games"], "checks": len(checks),
            "checks_failed": len(failed), "warnings": sum(c["status"] == "warn" for c in checks)}


def main() -> int:
    from app.task4.sportsbook_backfill import load_manifest

    snaps = pd.read_csv(SNAPSHOTS, dtype=str, keep_default_na=False)
    r = compute(snaps)
    games = pd.read_csv(GAMES) if GAMES.exists() else pd.DataFrame(columns=["event_id", "season", "week"])
    manifest = load_manifest()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Files from the earlier one-season layout would be read as current results; remove them.
    for old in list(RESULTS_DIR.glob("*.csv")) + list(RESULTS_DIR.glob("*.md")) + \
            [p for p in RESULTS_DIR.glob("*.json") if p.name != "index.json"] + list(CHARTS_DIR.glob("*.png")):
        old.unlink()
    seasons = [run_season(r, s, games, manifest) for s in SEASONS]
    index = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
             "seasons": [s for s in seasons if not s.get("skipped")]}
    (RESULTS_DIR / "index.json").write_text(json.dumps(index, indent=2))
    return 1 if any(s.get("checks_failed") for s in seasons) else 0


if __name__ == "__main__":
    raise SystemExit(main())
