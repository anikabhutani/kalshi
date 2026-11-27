"""Section 6.1 figures (NFL in-game), from task8/ingame_summary_nfl.csv. Deck colors and dark background.

    cd backend && python -m app.ingame.figures_61
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.task4.common import REPO_ROOT  # noqa: E402

T8 = REPO_ROOT / "data" / "ingame" / "nfl" / "task8"
OUT = REPO_ROOT / "data" / "ingame" / "nfl" / "task9"
BG, GRID, TICK, LABEL = "#040d0a", "#26302c", "#a9b3ae", "#e8ecea"
COL = {"FanDuel": "#4ea3ff", "DraftKings": "#f1b33d", "Kalshi": "#00dd94"}
for f in ("Arial", "Liberation Sans", "DejaVu Sans"):
    if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break


def frame(ax, fig):
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=TICK, labelsize=11, length=0)
    ax.grid(axis="y", color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.axhline(0, color=TICK, lw=1)


def pick(s, metric, book, which, group="all"):
    r = s[(s.metric == metric) & (s.book == book) & (s.which == which) & (s.group == group)].iloc[0]
    return r.estimate, r.ci_low, r.ci_high, int(r.rows), int(r.games)


def bars(ax, xs, est, lo, hi, color, width, fmt="{:+.1f}¢"):
    est, lo, hi = map(np.array, (est, lo, hi))
    ax.bar(xs, est, width=width, color=color, zorder=2)
    ax.errorbar(xs, est, yerr=[est - lo, hi - est], fmt="none", ecolor=LABEL, capsize=5, lw=1.3, zorder=3)
    for x, e, h, l_ in zip(xs, est, hi, lo):
        y = h + 1.2 if e >= 0 else l_ - 1.2
        ax.text(x, y, fmt.format(e), ha="center", va="bottom" if e >= 0 else "top", color=LABEL, fontsize=10.5,
                fontweight="bold")


def legend(ax, items):
    from matplotlib.patches import Patch
    leg = ax.legend(handles=[Patch(color=c, label=l) for l, c in items], frameon=False, fontsize=11, loc="upper left")
    for t in leg.get_texts():
        t.set_color(LABEL)


def fig_before_after(s, out: Path) -> dict:
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=200)
    frame(ax, fig)
    labels = ["Pregame\n(kickoff)", "In-game\nbefore swing", "In-game\nafter swing"]
    x = np.arange(3)
    n = {}
    for k, (book, off) in enumerate((("FanDuel", -0.19), ("DraftKings", 0.19))):
        vals = [pick(s, "pregame_extra_cost_A_kickoff", book, "pregame kickoff"),
                pick(s, "extra_cost_A", book, "before"), pick(s, "extra_cost_A", book, "after")]
        bars(ax, x + off, [v[0] for v in vals], [v[1] for v in vals], [v[2] for v in vals], COL[book], 0.36)
        n[book] = vals
    ax.set_ylim(-2, 27)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Extra cost per $10 vs Kalshi (cents)", color=TICK, fontsize=11)
    ax.set_title("Sportsbook extra cost per $10 over Kalshi: pregame vs in-game", color=LABEL, fontsize=13, loc="left")
    legend(ax, [(b, COL[b]) for b in ("FanDuel", "DraftKings")])
    fig.tight_layout()
    fig.savefig(out / "fig_6_1a_extra_cost_pregame_vs_ingame.png", facecolor=BG)
    plt.close(fig)
    return n


def fig_price_group(s, out: Path) -> dict:
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=200)
    frame(ax, fig)
    groups = ["longshot", "middle", "favorite"]
    x = np.arange(3)
    n = {}
    for book, off in (("FanDuel", -0.19), ("DraftKings", 0.19)):
        vals = [pick(s, "extra_cost_A_pooled_before_after", book, "before+after", f"price_group={g}") for g in groups]
        bars(ax, x + off, [v[0] for v in vals], [v[1] for v in vals], [v[2] for v in vals], COL[book], 0.36)
        n[book] = vals
    ax.set_ylim(-30, 40)
    ax.set_xticks(x, ["Longshots\n(Kalshi under 40%)", "Middle\n(40-60%)", "Favorites\n(60% and up)"])
    ax.set_ylabel("Extra cost per $10 vs Kalshi (cents)", color=TICK, fontsize=11)
    ax.set_title("In-game extra cost per $10 by price group (before and after swings pooled)", color=LABEL,
                 fontsize=13, loc="left")
    legend(ax, [(b, COL[b]) for b in ("FanDuel", "DraftKings")])
    fig.tight_layout()
    fig.savefig(out / "fig_6_1b_extra_cost_by_price_group.png", facecolor=BG)
    plt.close(fig)
    return n


def fig_cheapest(s, out: Path) -> dict:
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=200)
    frame(ax, fig)
    groups = ["all", "price_group=longshot", "price_group=middle", "price_group=favorite"]
    x = np.arange(4)
    n = {}
    for which, off, shade in (("before", -0.19, "#00a870"), ("after", 0.19, COL["Kalshi"])):
        vals = [pick(s, "share_kalshi_cheapest", "all three", which, g) for g in groups]
        bars(ax, x + off, [v[0] * 100 for v in vals], [v[1] * 100 for v in vals], [v[2] * 100 for v in vals], shade,
             0.36, fmt="{:.0f}%")
        n[which] = vals
    ax.axhline(100 / 3, color=TICK, lw=1, ls="--")
    ax.set_xticks(x, ["All", "Longshots", "Middle", "Favorites"])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Kalshi cheapest of the three venues (%)", color=TICK, fontsize=11)
    ax.set_title("How often Kalshi was the cheapest venue at swing times", color=LABEL, fontsize=13, loc="left")
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    leg = ax.legend(handles=[Patch(color="#00a870", label="Before swing"), Patch(color=COL["Kalshi"], label="After swing"),
                             Line2D([], [], color=TICK, ls="--", label="One in three (no venue favored)")],
                    frameon=False, fontsize=11, loc="upper left")
    for t in leg.get_texts():
        t.set_color(LABEL)
    fig.tight_layout()
    fig.savefig(out / "fig_6_1c_kalshi_cheapest_share.png", facecolor=BG)
    plt.close(fig)
    return n


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = pd.read_csv(T8 / "ingame_summary_nfl.csv")
    a = fig_before_after(s, OUT)
    b = fig_price_group(s, OUT)
    c = fig_cheapest(s, OUT)
    print({"6.1a": a, "6.1b": b, "6.1c": c})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
