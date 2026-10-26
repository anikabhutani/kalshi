"""The two "Kalshi vs. the Sportsbooks" deck charts and their stat-box numbers, for NFL or college.

Rebuilds Prisha's slides 17-18 (NFL) exactly and the college versions (slides 19-20) from the
alignment output. Run on the NFL data it reproduces every number on her slides (+0.6c, +3.0c,
52% / 54%, +9c, -6c, 79%), which is how the method below was confirmed.

Chart 1, "Kalshi and Sportsbooks Price Residuals (Per $10)": for each checkpoint (24 h, 3 h, 1 h,
close = "At kickoff"), the median of (book cost - Kalshi cost) per $10 for the same game, team and
moment. Fair price = Pinnacle de-vigged (ruler B_Pinnacle), Kalshi cost at the median trade size,
usable rows only. Whiskers: 95% interval of the median, resampling games (2,000 resamples, fixed seed).
Stat boxes: the same difference over all checkpoints (median, and the share of pairs above 0).

Chart 2, "Median Cost Per $10 Bet, By Team's Chance of Winning": everything against Kalshi's own fair
price (ruler A_Kalshi), bucketed by that fair price in 10-point bins (10-20% ... 80-90% shown).
Kalshi line and "Kalshi fee alone": all ruler-A rows at the median trade size. Book lines: book cost
against Kalshi's fair price, on rows where that book's own line is recent enough (B_<book> usable).
Stat boxes: favorites (fair >= 60%) median of (book - Kalshi), averaged over the two books;
FanDuel on longshots (fair < 40%); fee share = sum of fee / sum of Kalshi cost (ruler A).

Colors are Prisha's slide colors converted from the Mac display profile to sRGB, and the PNGs are
tagged sRGB, so they look the same on every screen and in PowerPoint.

    cd backend && .venv/bin/python -m app.alignment.slide_charts --league ncaaf
    cd backend && .venv/bin/python -m app.alignment.slide_charts --league nfl     # check against slides 17-18
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from app.task4.common import REPO_ROOT  # noqa: E402

ALIGN = REPO_ROOT / "data" / "alignment"
SEASONS = ("2025", "2026")
KEY = ["game_id", "team", "checkpoint"]
BOOKS = ("FanDuel", "DraftKings")

# Prisha's slide colors (sRGB)
BG, BORDER, GRID = "#040d0a", "#3a4440", "#26302c"
LABEL, TICK, TITLE = "#f5f7f4", "#a9b3ae", "#ffffff"
FD, DK, KALSHI = "#4ea3ff", "#f1b33d", "#00dd94"
W, H, DPI = 1030, 632, 100  # panel size in slide pixels; saved at 3x


def _paths(league: str) -> tuple[Path, str]:
    return (ALIGN / "ncaaf", "costs.csv.gz") if league == "ncaaf" else (ALIGN, "costs.csv")


def load(league: str, seasons: tuple[str, ...] = SEASONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    folder, costs_name = _paths(league)
    costs = pd.concat([pd.read_csv(folder / s / costs_name) for s in seasons], ignore_index=True)
    snaps = pd.concat([pd.read_csv(folder / s / "snapshots.csv") for s in seasons], ignore_index=True)
    return costs, snaps


def residual_pairs(costs: pd.DataFrame, snaps: pd.DataFrame) -> pd.DataFrame:
    """Chart 1 rows: Pinnacle fair price, median trade size, usable; one row per pair with each book."""
    k = costs[(costs["ruler"] == "B_Pinnacle") & (costs["n_label"] == "median") & (costs["usable"])]
    books = snaps[snaps["source"].isin(BOOKS)][KEY + ["source", "book_implied"]]
    m = k.merge(books, on=KEY).dropna(subset=["book_implied", "fair", "cost_per_10"])
    m["book_cost"] = 10 * (1 - m["fair"] / m["book_implied"])
    m["resid"] = m["book_cost"] - m["cost_per_10"]
    return m


def boot_median(rows: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Median of resid and its 95% interval, resampling games."""
    rng = np.random.default_rng(seed)
    arrs = list(rows.groupby("game_id")["resid"].apply(np.asarray).values)
    meds = np.empty(n_boot)
    for i in range(n_boot):
        meds[i] = np.median(np.concatenate([arrs[j] for j in rng.integers(0, len(arrs), len(arrs))]))
    lo, hi = np.percentile(meds, (2.5, 97.5))
    return float(np.median(rows["resid"])), float(lo), float(hi)


def by_chance(costs: pd.DataFrame, snaps: pd.DataFrame) -> tuple[dict[str, pd.Series], pd.DataFrame, dict]:
    """Chart 2 series (cost per $10 by fair-price bucket) plus the rows behind each book line."""
    a = costs[(costs["ruler"] == "A_Kalshi") & (costs["n_label"] == "median")].dropna(subset=["fair", "cost_per_10"]).copy()
    a["bucket"] = np.floor(a["fair"] * 10).astype(int)
    out = {"Kalshi": a.groupby("bucket")["cost_per_10"].median(),
           "Kalshi fee alone": a.groupby("bucket")["fee_per_10"].median()}
    rows = {}
    for b in BOOKS:
        fresh = costs[(costs["ruler"] == f"B_{b}") & (costs["n_label"] == "median") & (costs["usable"])][KEY]
        s = snaps[snaps["source"] == b][KEY + ["book_implied"]]
        m = a.merge(fresh, on=KEY).merge(s, on=KEY).dropna(subset=["book_implied"])
        m["book_cost"] = 10 * (1 - m["fair"] / m["book_implied"])
        out[b] = m.groupby("bucket")["book_cost"].median()
        rows[b] = m
    return out, a, rows


# ------------------------------------------------------------------ drawing


def _fig() -> plt.Figure:
    f = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=BG)
    f.patches.append(FancyBboxPatch((1.2 / W, 1.2 / H), (W - 2.4) / W, (H - 2.4) / H,
                                    boxstyle=f"round,pad=0,rounding_size={12 / W}", transform=f.transFigure,
                                    facecolor=BG, edgecolor=BORDER, linewidth=1.3, zorder=-10, mutation_aspect=W / H))
    return f


def _x(px: float) -> float:
    return px / W


def _y(py: float) -> float:
    return 1 - py / H


def _fit(f: plt.Figure, t, width_px: float):
    r = f.canvas.get_renderer()
    for _ in range(4):
        t.set_fontsize(t.get_fontsize() * width_px / t.get_window_extent(renderer=r).width)
    return t


def _text(f, x, y, s, width, ha="center", color=LABEL, style="normal", weight="bold"):
    return _fit(f, f.text(_x(x), _y(y), s, ha=ha, va="center", color=color, fontsize=12,
                          fontstyle=style, fontweight=weight), width)


def _axis(ax, edges, y0=0.0):
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=1.0)
    ax.set_axisbelow(True)
    ax.axhline(y0, color=BORDER, linewidth=1.3, zorder=1)
    ax.tick_params(length=0)
    for e in edges:
        ax.plot([e], [y0], marker="|", markersize=6, color=BORDER, clip_on=False, zorder=1, markeredgewidth=1.3)


def _save(f: plt.Figure, path: Path) -> None:
    from PIL import Image, ImageCms
    f.savefig(path, dpi=300, facecolor=BG)
    plt.close(f)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.open(path).convert("RGB").save(path, icc_profile=srgb)


def chart1(res: dict[str, list[tuple[float, float, float]]], path: Path) -> None:
    labels = ["24 h before", "3 h before", "1 h before", "At kickoff"]
    hi = max(r[2] for v in res.values() for r in v)
    lo = min(r[1] for v in res.values() for r in v)
    top, bot = max(8.0, 2 * np.ceil(hi / 2)), min(-2.0, 2 * np.floor(lo / 2))
    f = _fig()
    ax = f.add_axes([_x(84), _y(560), _x(900), _y(148) - _y(560)], facecolor=BG)
    ax.set_xlim(0, 4)
    ax.set_ylim(bot, top)
    ax.set_yticks(np.arange(bot, top + 0.1, 2))
    ax.set_yticklabels([])
    ax.set_xticks([])
    _axis(ax, [1, 2, 3])
    for j, (b, col) in enumerate(((BOOKS[0], FD), (BOOKS[1], DK))):
        pos = np.arange(4) + 0.5 + (-1 if j == 0 else 1) * 0.193
        med = [r[0] for r in res[b]]
        ax.bar(pos, med, width=0.356, color=col, zorder=2)
        ax.errorbar(pos, med, yerr=[[r[0] - r[1] for r in res[b]], [r[2] - r[0] for r in res[b]]], fmt="none",
                    ecolor=LABEL, elinewidth=1.8, capsize=4.5, capthick=1.8, zorder=3)
    for v in np.arange(bot, top + 0.1, 2):
        py = 560 - (v - bot) / (top - bot) * (560 - 148)
        f.text(_x(68), _y(py), f"+{v:.0f}¢" if v > 0 else f"{v:.0f}¢", ha="right", va="center", color=TICK,
               fontsize=13.5)
    first = None
    for i, lab in enumerate(labels):
        t = f.text(_x(84 + 112.5 + 225 * i), _y(583), lab, ha="center", va="center", color=LABEL, fontsize=12,
                   fontweight="bold")
        first = _fit(f, t, 101) if first is None else first
        t.set_fontsize(first.get_fontsize())
    _text(f, 489, 30, "Kalshi and Sportsbooks Price Residuals (Per $10)", 600, color=TITLE)
    for x0, col, lab, width in ((284, FD, "FanDuel minus Kalshi", 194), (528, DK, "DraftKings minus Kalshi", 211)):
        f.patches.append(FancyBboxPatch((_x(x0), _y(117)), _x(10), _y(107) - _y(117), boxstyle="square,pad=0",
                                        transform=f.transFigure, facecolor=col, edgecolor="none"))
        _text(f, x0 + 15, 112, lab, width, ha="left")
    _save(f, path)


def chart2(vals: dict[str, list[float]], path: Path) -> None:
    xl = [f"{10 * k}–{10 * k + 10}%" for k in range(1, 9)]
    top = max(90.0, 15 * np.ceil(max(np.nanmax(v) for v in vals.values()) / 15))
    f = _fig()
    ax = f.add_axes([_x(95), _y(559), _x(878), _y(159) - _y(559)], facecolor=BG)
    ax.set_xlim(0, 8)
    ax.set_ylim(0, top)
    ax.set_yticks(np.arange(0, top + 1, 15))
    ax.set_yticklabels([])
    ax.set_xticks([])
    _axis(ax, range(1, 8))
    xi = np.arange(8) + 0.5
    ax.plot(xi, vals["Kalshi fee alone"], color=KALSHI, linewidth=1.6, linestyle=(0, (4, 3)), zorder=2)
    ax.plot(xi, vals["FanDuel"], color=FD, linewidth=2.6, marker="o", markersize=8, zorder=4)
    ax.plot(xi, vals["DraftKings"], color=DK, linewidth=2.6, marker="o", markersize=8, zorder=4)
    ax.plot(xi, vals["Kalshi"], color=KALSHI, linewidth=4.2, marker="o", markersize=9, zorder=3)
    for v in np.arange(0, top + 1, 15):
        f.text(_x(78), _y(559 - v / top * 400), f"{v:.0f}¢", ha="right", va="center", color=TICK, fontsize=13.5)
    first = None
    for i, lab in enumerate(xl):
        t = f.text(_x(95 + 54.9 + 109.75 * i), _y(584), lab, ha="center", va="center", color=LABEL, fontsize=12,
                   fontweight="bold")
        first = _fit(f, t, 70) if first is None else first
        t.set_fontsize(first.get_fontsize())
    _text(f, 39, 41, "Median Cost Per $10 Bet, By Team’s Chance of Winning", 670, ha="left", color=TITLE)
    _fit(f, f.text(_x(991), _y(37), "Dashed: Kalshi fee alone", ha="right", va="center", color=TICK,
                   fontstyle="italic", fontsize=11), 200)
    _text(f, 35, 616, "← Longshots", 138, ha="left", color=TICK)
    _text(f, 991, 616, "Favorites →", 123, ha="right", color=TICK)

    def icon(x0, x1, col, lw, ms, ls="-"):
        f.lines.append(Line2D([_x(x0), _x(x1)], [_y(123)] * 2, transform=f.transFigure, color=col, linewidth=lw,
                              linestyle=ls))
        if ms:
            f.lines.append(Line2D([_x((x0 + x1) / 2)], [_y(123)], transform=f.transFigure, marker="o", markersize=ms,
                                  color=col, linestyle=""))
    icon(196, 243, KALSHI, 4.2, 8)
    _text(f, 247, 123, "Kalshi", 54, ha="left")
    icon(328, 375, FD, 2.6, 7)
    _text(f, 379, 123, "FanDuel", 73, ha="left")
    icon(480, 527, DK, 2.6, 7)
    _text(f, 531, 123, "DraftKings", 91, ha="left")
    icon(650, 698, KALSHI, 1.6, 0, (0, (4, 3)))
    _text(f, 701, 123, "Kalshi fee alone", 138, ha="left")
    _save(f, path)


# ------------------------------------------------------------------ run


def run(league: str, out: Path | None = None) -> dict:
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    # Arial (or its metric twin Liberation Sans): the font of the slide charts
    plt.rcParams.update({"font.family": next((n for n in ("Arial", "Liberation Sans", "Helvetica") if n in have),
                                             "DejaVu Sans")})
    costs, snaps = load(league)
    folder = out or (_paths(league)[0] / "charts")
    folder.mkdir(parents=True, exist_ok=True)
    name = {"ncaaf": "college", "nfl": "nfl"}[league]

    pairs = residual_pairs(costs, snaps)
    cps = [("24h", "24 h before"), ("3h", "3 h before"), ("1h", "1 h before"), ("close", "At kickoff")]
    res = {b: [tuple(100 * v for v in boot_median(pairs[(pairs["source"] == b) & (pairs["checkpoint"] == c)]))
               for c, _ in cps] for b in BOOKS}
    chart1(res, folder / f"{name}_1_kalshi_vs_sportsbooks.png")

    series, a, rows = by_chance(costs, snaps)
    vals = {s: [100 * series[s].get(k, np.nan) for k in range(1, 9)] for s in ("Kalshi", "FanDuel", "DraftKings",
                                                                              "Kalshi fee alone")}
    chart2(vals, folder / f"{name}_2_where_the_gap_is_biggest.png")

    fav = {b: float(100 * (r["book_cost"] - r["cost_per_10"])[r["fair"] >= 0.6].median()) for b, r in rows.items()}
    lng = {b: float(100 * (r["book_cost"] - r["cost_per_10"])[r["fair"] < 0.4].median()) for b, r in rows.items()}
    numbers = {
        "league": league,
        "trade_size": {"n_median": int(a["n"].iloc[0]), "source": str(a["n_source"].iloc[0])},
        "slide_1": {
            **{f"{b} extra cost per $10 (cents)": round(float(100 * pairs[pairs["source"] == b]["resid"].median()), 2)
               for b in BOOKS},
            **{f"{b} share of bets costing more than Kalshi (%)":
               round(float(100 * (pairs[pairs["source"] == b]["resid"] > 0).mean()), 1) for b in BOOKS},
            "pairs": {b: int((pairs["source"] == b).sum()) for b in BOOKS},
        },
        "slide_2": {
            "extra sportsbook cost on favorites, 60%+ (cents, average of the two books)":
                round((fav[BOOKS[0]] + fav[BOOKS[1]]) / 2, 2),
            "favorites by book (cents)": {b: round(v, 2) for b, v in fav.items()},
            "FanDuel minus Kalshi on longshots, under 40% (cents; negative = FanDuel cheaper)": round(lng["FanDuel"], 2),
            "longshots by book (cents)": {b: round(v, 2) for b, v in lng.items()},
            "share of Kalshi's cost that is the fee (%)": round(float(100 * a["fee_per_10"].sum() / a["cost_per_10"].sum()), 1),
        },
        "chart_1_median_and_95pct_interval_cents": {b: {lab: [round(x, 2) for x in r] for (_, lab), r in zip(cps, res[b])}
                                                    for b in BOOKS},
        "chart_2_cents": {s: {f"{10 * k}-{10 * k + 10}%": round(v, 1) for k, v in zip(range(1, 9), vs)}
                          for s, vs in vals.items()},
    }
    (folder / f"{name}_numbers.json").write_text(json.dumps(numbers, indent=2))
    return numbers


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Deck charts: Kalshi vs. the sportsbooks (NFL or college).")
    p.add_argument("--league", choices=("ncaaf", "nfl"), default="ncaaf")
    a = p.parse_args(argv)
    n = run(a.league)
    s1, s2 = n["slide_1"], n["slide_2"]
    print(f"{a.league}: trade size n = {n['trade_size']['n_median']} ({n['trade_size']['source']})")
    print("Slide 1 stat boxes: FanDuel {:+.1f}¢, DraftKings {:+.1f}¢, share {:.0f}% / {:.0f}%".format(
        s1["FanDuel extra cost per $10 (cents)"], s1["DraftKings extra cost per $10 (cents)"],
        s1["FanDuel share of bets costing more than Kalshi (%)"], s1["DraftKings share of bets costing more than Kalshi (%)"]))
    print("Slide 2 stat boxes: favorites {:+.0f}¢, FanDuel on longshots {:+.0f}¢, fee share {:.0f}%".format(
        s2["extra sportsbook cost on favorites, 60%+ (cents, average of the two books)"],
        s2["FanDuel minus Kalshi on longshots, under 40% (cents; negative = FanDuel cheaper)"],
        s2["share of Kalshi's cost that is the fee (%)"]))
    print(f"charts: {(_paths(a.league)[0] / 'charts')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
