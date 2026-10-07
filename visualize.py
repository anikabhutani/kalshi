"""
Simple charts of what it costs to bet on Kalshi, written in Python with Plotly.

Reads:   output/taker_costs.csv   (made by compute_costs.py)
Writes:  output/charts.html       (open it in any browser)

Every chart answers one question in plain words. Costs are shown as
"out of every $10 you bet, how much goes to costs", so no math is needed to read them.

Usage:
  pip install pandas plotly
  python visualize.py
"""

import os

import pandas as pd
import plotly.graph_objects as go

OUT = "output"
TYPICAL_SIZE = 10  # contracts per bet used in most charts

GROUPS = ["Big longshot", "Underdog", "Toss-up", "Favorite", "Big favorite"]
GROUP_RANGES = ["under 20¢", "20 to 40¢", "40 to 60¢", "60 to 80¢", "80¢ and up"]
GROUP_EDGES = [0, 20, 40, 60, 80, 101]

FEE_COLOR = "#C2364B"   # Kalshi's fee
GAP_COLOR = "#E8A33D"   # price gap
MAIN_COLOR = "#2F5DA8"
GREY = "#B7BFCC"

FONT = dict(family="Helvetica Neue, Arial, sans-serif", size=16, color="#172033")


def style(fig, title, subtitle, height=480):
    fig.update_layout(
        title=dict(text=f"<b>{title}</b><br><span style='font-size:15px;color:#5A6578'>{subtitle}</span>",
                   x=0, xanchor="left", font=dict(size=22)),
        font=FONT, paper_bgcolor="white", plot_bgcolor="white", height=height,
        margin=dict(l=40, r=40, t=120, b=60),
        hoverlabel=dict(bgcolor="white", font=FONT),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=15)),
        bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, linecolor="#C9D0DB")
    fig.update_yaxes(showgrid=True, gridcolor="#EEF1F5", zeroline=False)
    return fig


def load():
    t = pd.read_csv(os.path.join(OUT, "taker_costs.csv"))
    t = t[(t.pass_id == t.pass_id.max()) & (t.fill_status == "filled")].copy()
    t["price"] = t.avg_fill_price * 100
    t["group"] = pd.cut(t.price, GROUP_EDGES, right=False, labels=GROUPS)
    # out of every $10 bet, dollars that go to the fee and to the price gap
    t["fee_per_10"] = t.fee_per_contract / t.avg_fill_price * 10
    t["gap_per_10"] = (t.half_spread + t.price_impact.fillna(0)) / t.avg_fill_price * 10
    t["cost_per_10"] = t.fee_per_10 + t.gap_per_10
    t["gap_cents"] = (t.spread * 100).round()
    return t


def x_labels():
    return [f"{g}<br><span style='font-size:13px;color:#5A6578'>{r}</span>" for g, r in zip(GROUPS, GROUP_RANGES)]


def chart_cost_per_10(t):
    """1. Out of every $10 you bet, how much goes to costs?"""
    d = t[t.order_size == TYPICAL_SIZE].groupby("group", observed=True)[["fee_per_10", "gap_per_10", "cost_per_10"]].mean()
    x = x_labels()
    fig = go.Figure()
    fig.add_bar(x=x, y=d.fee_per_10, name="Kalshi's fee", marker_color=FEE_COLOR,
                hovertemplate="Fee: $%{y:.2f} of every $10<extra></extra>")
    fig.add_bar(x=x, y=d.gap_per_10, name="Price gap (buying a little above fair price)", marker_color=GAP_COLOR,
                hovertemplate="Price gap: $%{y:.2f} of every $10<extra></extra>")
    fig.add_scatter(x=x, y=d.cost_per_10, mode="text", text=[f"<b>${v:.2f}</b>" for v in d.cost_per_10],
                    textposition="top center", textfont=dict(size=20), showlegend=False, hoverinfo="skip")
    fig.update_layout(barmode="stack")
    fig.update_yaxes(tickprefix="$", tickformat=".2f", range=[0, d.cost_per_10.max() * 1.25], title="Cost out of every $10 bet")
    return style(fig, "Out of every $10 you bet on Kalshi, this much goes to costs",
                 f"Average across all open NFL markets, for a {TYPICAL_SIZE}-contract bet. "
                 "Betting on longshots costs the most; betting on big favorites costs the least.")


def chart_small_bets(t):
    """2. Do small bets cost more?"""
    d = t[t.order_size.isin([1, 100])].groupby(["group", "order_size"], observed=True).cost_per_10.mean().unstack()
    x = x_labels()
    fig = go.Figure()
    fig.add_bar(x=x, y=d[1], name="1 contract", marker_color=FEE_COLOR,
                text=[f"${v:.2f}" for v in d[1]], textposition="outside",
                hovertemplate="1-contract bet: $%{y:.2f} of every $10<extra></extra>")
    fig.add_bar(x=x, y=d[100], name="100 contracts", marker_color=GREY,
                text=[f"${v:.2f}" for v in d[100]], textposition="outside",
                hovertemplate="100-contract bet: $%{y:.2f} of every $10<extra></extra>")
    fig.update_layout(barmode="group")
    fig.update_yaxes(tickprefix="$", tickformat=".2f", range=[0, d.values.max() * 1.25], title="Cost out of every $10 bet")
    return style(fig, "Tiny bets pay more, because the fee rounds up to a whole cent",
                 "Same markets, two bet sizes. A 1-contract bet pays at least 1¢ in fees no matter how small the fee should be.")


def chart_gap(t):
    """3. How tight are prices?"""
    d = t[(t.order_size == TYPICAL_SIZE) & (t.side == "yes")]
    counts = d.gap_cents.clip(upper=3).value_counts().sort_index()
    labels = ["1¢<br>(smallest possible)", "2¢", "3¢ or more"]
    shares = counts / counts.sum()
    fig = go.Figure(go.Bar(
        x=labels[:len(shares)], y=shares, marker_color=[MAIN_COLOR, GREY, GREY][:len(shares)],
        text=[f"<b>{v:.0%}</b><br>{n} markets" for v, n in zip(shares, counts)], textposition="outside",
        hovertemplate="%{y:.0%} of markets<extra></extra>", showlegend=False))
    fig.update_yaxes(tickformat=".0%", range=[0, 1], title="Share of markets")
    fig.update_xaxes(title="Gap between the buy price and the sell price")
    return style(fig, "Prices are tight: about 3 in 4 markets have the smallest possible gap",
                 "A small gap means you can buy close to the fair price.", height=440)


def chart_busy(t):
    """4. Do busier markets have tighter prices?"""
    d = t[(t.order_size == TYPICAL_SIZE) & (t.side == "yes")].sort_values("volume").reset_index(drop=True)
    d["busy"] = pd.qcut(d.index, 4, labels=["Least traded", "Less traded", "More traded", "Most traded"])
    g = d.groupby("busy", observed=True).gap_cents.apply(lambda x: (x <= 1).mean())
    fig = go.Figure(go.Bar(
        x=g.index.astype(str), y=g, marker_color=[GREY, GREY, GREY, MAIN_COLOR],
        text=[f"<b>{v:.0%}</b>" for v in g], textposition="outside", textfont=dict(size=18),
        hovertemplate="%{y:.0%} have the smallest gap<extra></extra>", showlegend=False))
    fig.update_yaxes(tickformat=".0%", range=[0, 1.05], title="Markets with the smallest gap (1¢)")
    fig.update_xaxes(title="Markets split into four equal groups by how much has been traded")
    return style(fig, "The more a market trades, the tighter its prices",
                 "This is the pattern the study will test properly in the regressions.", height=440)


def chart_market_types(t):
    """5. Does it matter which kind of bet?"""
    names = {"KXNFLGAME": "Who wins", "KXNFLSPREAD": "Point spread", "KXNFLTOTAL": "Total points"}
    d = t[t.order_size == TYPICAL_SIZE].assign(kind=t.series.map(names))
    g = d.groupby("kind").cost_per_10.mean().reindex(names.values())
    n = d[d.side == "yes"].groupby("kind").size().reindex(names.values())
    fig = go.Figure(go.Bar(
        x=g.values, y=[f"{k}  " for k in g.index], orientation="h", marker_color=MAIN_COLOR,
        text=[f"<b>${v:.2f}</b>  ({c} markets)" for v, c in zip(g, n)], textposition="outside",
        hovertemplate="$%{x:.2f} of every $10<extra></extra>", showlegend=False))
    fig.update_xaxes(tickprefix="$", tickformat=".2f", range=[0, g.max() * 1.5], title="Cost out of every $10 bet", showgrid=True, gridcolor="#EEF1F5")
    fig.update_yaxes(showgrid=False, autorange="reversed")
    return style(fig, "Costs are similar across the three kinds of NFL bets",
                 f"Average cost for a {TYPICAL_SIZE}-contract bet. Differences mostly come from which prices each kind tends to have.",
                 height=360)


def main():
    t = load()
    figs = [chart_cost_per_10(t), chart_small_bets(t), chart_gap(t), chart_busy(t), chart_market_types(t)]

    start = pd.to_datetime(t.requested_utc.min()).tz_convert("America/Los_Angeles")
    intro = f"""
    <h1>What it costs to bet on Kalshi</h1>
    <p>A snapshot of {t.ticker.nunique()} open NFL markets, taken {start:%B %-d, %Y at %-I:%M %p} Pacific.
    These are Kalshi's costs only. We have not compared them to sportsbooks yet.</p>
    <div class="key">
      <p><b>How to read these charts.</b> When you buy a contract on Kalshi you pay two small costs on top of the fair price:</p>
      <p><span class="sw" style="background:{FEE_COLOR}"></span><b>Kalshi's fee</b>, which Kalshi charges on every trade.</p>
      <p><span class="sw" style="background:{GAP_COLOR}"></span><b>The price gap</b>. The price to buy is always a little higher than the price to sell. Buying means paying a bit above the fair price, which is halfway between the two.</p>
      <p>Each chart shows these costs as <b>dollars out of every $10 you bet</b>. Hover over a bar to see the exact number.</p>
    </div>"""
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'>"
             "<meta name='viewport' content='width=device-width, initial-scale=1'><title>What it costs to bet on Kalshi</title>"
             "<style>body{font-family:Helvetica Neue,Arial,sans-serif;color:#172033;background:#F1F3F7;margin:0;font-size:17px;line-height:1.5}"
             "main{max-width:1000px;margin:0 auto;padding:36px 20px 60px}h1{font-size:38px;margin:0 0 8px}"
             "p{max-width:70ch;margin:6px 0}.key{background:white;border:1px solid #D6DBE4;border-radius:12px;padding:16px 20px;margin-top:20px}"
             ".sw{display:inline-block;width:13px;height:13px;border-radius:3px;margin-right:8px}"
             ".card{background:white;border:1px solid #D6DBE4;border-radius:12px;padding:10px;margin-top:24px}</style>"
             "</head><body><main>", intro]
    for i, fig in enumerate(figs):
        parts.append("<div class='card'>" + fig.to_html(full_html=False, include_plotlyjs=(i == 0),
                                                         config={"displayModeBar": False, "responsive": True}) + "</div>")
    parts.append("</main></body></html>")

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "charts.html")
    with open(path, "w") as f:
        f.write("\n".join(parts))
    print(f"Wrote {len(figs)} charts to {path}")


if __name__ == "__main__":
    main()