"""
Decides when a Kalshi NFL market and a sportsbook line are the same bet, matches them, and records
why a market has no match. Default scope: NFL weeks 2 to 5 of 2026.

Reads:   raw_trades/markets.jsonl, raw_trades/trades/*.jsonl.gz      (pull_trades.py)
         odds_data/history/history_americanfootball_nfl.csv          (sportsbook snapshots, odds_data.zip)
         team_names.csv                                              (Kalshi code -> provider team name)
Writes:  output/matching/*.csv

What counts as the same bet
  Who wins   Kalshi "<team> wins" YES  =  that team's moneyline at the book
  Spread     Kalshi "<team> wins by over X" YES  =  <team> -X at the book
             Kalshi NO                           =  the other team +X
  Total      Kalshi "over X points" YES / NO     =  Over X / Under X at the book
  Spreads and totals must be the exact same number. Kalshi only lists half-point numbers (3.5, 44.5),
  so a book line on a whole number (-3, 44) has no Kalshi twin: the book refunds on exactly 3 or 44,
  Kalshi does not.

When prices count as "the same moment"
  Kickoff is Kalshi's scheduled kickoff (expiration_time - 48h, see pull_trades.py).
  For each snapshot time we take the sportsbook snapshot closest to the target, inside its window,
  and taken before kickoff (anything later is live in-game odds). The Kalshi price is the trade
  closest in time to that sportsbook snapshot, within the Kalshi tolerance, and before kickoff.
  Windows are in SNAPSHOTS below.

Cost per $10 bet (same formula for every venue; q = fair chance the bet wins)
  cost = $10 x (1 - q / price paid per $1 of payout)
  Sportsbook price paid = 1 / decimal odds. Kalshi price paid = contract price + taker fee,
  fee = 0.07 x P x (1 - P) per contract, unrounded (rounding adds a little, see analyze_trades.py).
  Two choices of q:
    *_vs_own       q from the same venue's two sides with the margin removed proportionally.
                   For a sportsbook this is its vig. For Kalshi it is spread + fees, using the
                   closest taker trade on each side.
    *_vs_pinnacle  q = Pinnacle's no-vig chance at the same number and snapshot. Puts all venues on one
                   fair price, so a Kalshi price that is simply better than the book's shows up.

Usage:
  python match_markets.py                  # weeks 2 to 5
  python match_markets.py --weeks 2 3      # some weeks only
"""

import argparse
import gzip
import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

RAW_DIR = "raw_trades"
BOOK_FILE = os.path.join("odds_data", "history", "history_americanfootball_nfl.csv")
TEAM_FILE = "team_names.csv"
OUT_DIR = os.path.join("output", "matching")
EASTERN = ZoneInfo("America/New_York")
WEEK1_START = pd.Timestamp("2026-09-08", tz=EASTERN)  # same week definition as analyze_trades.py
TAKER_RATE = 0.07
BOOKS = ["Pinnacle", "FanDuel", "DraftKings"]
TYPES = {"KXNFLGAME": "Who wins", "KXNFLSPREAD": "Point spread", "KXNFLTOTAL": "Total points"}
BOOK_MARKET = {"KXNFLGAME": "h2h", "KXNFLSPREAD": "spreads", "KXNFLTOTAL": "totals"}

# name, target minutes before kickoff, sportsbook snapshot window (min..max minutes before kickoff),
# max minutes between the Kalshi trade and the sportsbook snapshot.
# "close" is the last sportsbook snapshot before kickoff, if it is within 30 minutes of kickoff.
SNAPSHOTS = [
    ("24h", 1440, 1080, 1800, 60),
    ("3h", 180, 135, 225, 15),
    ("1h", 60, 45, 75, 10),
    ("15m", 15, 5, 25, 5),
    ("close", 0, 0, 30, 5),
]
STALE_MINUTES = 60  # book line unchanged for longer than this before the snapshot gets flagged

PRICE_GROUPS = ["Big longshot (under 20¢)", "Underdog (20 to 40¢)", "Toss-up (40 to 60¢)",
                "Favorite (60 to 80¢)", "Big favorite (80¢ and up)"]
PRICE_EDGES = [0, 20, 40, 60, 80, 101]

# Miss reasons, in the order they are checked
REASONS = {
    "game_not_at_provider": "Sportsbook data has no game with these two teams near this kickoff",
    "no_snapshot_near_time": "No sportsbook snapshot inside the window for this snapshot time",
    "book_did_not_post_market": "This book had no line of this market type at that snapshot",
    "different_number": "The book's line is a different number (books post one main line, Kalshi many)",
    "kalshi_market_not_open_yet": "The Kalshi market was created after the sportsbook snapshot",
    "no_kalshi_trade_near_time": "Same bet, but no Kalshi trade close enough in time",
    "matched": "Matched",
    # sportsbook-side only
    "book_line_whole_number": "Book line is a whole number; Kalshi only lists half points",
    "no_kalshi_market_at_number": "Kalshi had no market at the book's number",
}


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------- Kalshi side

def load_teams():
    t = pd.read_csv(TEAM_FILE)
    return dict(zip(t.kalshi_code, t.provider_name)), {
        code: set(names.split(";")) for code, names in zip(t.kalshi_code, t.kalshi_names)}


def split_game(game, codes):
    """'26OCT04GBTB' -> ('GB', 'TB'): Kalshi puts the away team first."""
    teams = game[7:]
    splits = [(teams[:i], teams[i:]) for i in range(2, len(teams) - 1)
              if teams[:i] in codes and teams[i:] in codes]
    if len(splits) != 1:
        raise ValueError(f"can't split teams in {game}: {splits}")
    return splits[0]


def load_kalshi_markets(weeks, codes, kalshi_names):
    rows = []
    with open(os.path.join(RAW_DIR, "markets.jsonl")) as f:
        for line in f:
            m = json.loads(line)
            series = m["_series"]
            game = m["event_ticker"].split("-", 1)[1]
            suffix = m["ticker"].rsplit("-", 1)[1]
            team = {"KXNFLGAME": suffix, "KXNFLSPREAD": re.sub(r"\d+$", "", suffix)}.get(series)
            if team is not None and m.get("yes_sub_title", "").split(" wins")[0] not in kalshi_names[team]:
                raise ValueError(f"{m['ticker']}: '{m['yes_sub_title']}' is not in team_names.csv for {team}")
            rows.append({
                "ticker": m["ticker"], "series": series, "type": TYPES[series], "game": game,
                "kickoff": pd.Timestamp(parse_ts(m["expiration_time"]) - timedelta(hours=48)),
                "team": team, "strike": m.get("floor_strike") if series != "KXNFLGAME" else np.nan,
                "open_time": pd.Timestamp(parse_ts(m["open_time"])), "title": m.get("title", ""),
            })
    mk = pd.DataFrame(rows).drop_duplicates("ticker")
    mk["week"] = (mk.kickoff.dt.tz_convert(EASTERN) - WEEK1_START).dt.days // 7 + 1
    mk = mk[mk.week.isin(weeks)].copy()
    away_home = {g: split_game(g, codes) for g in mk.game.unique()}
    mk["away"] = mk.game.map(lambda g: away_home[g][0])
    mk["home"] = mk.game.map(lambda g: away_home[g][1])
    bad = mk[mk.team.notna() & (mk.team != mk.away) & (mk.team != mk.home)]
    if len(bad):
        raise ValueError(f"markets naming a team not in their game: {bad.ticker.tolist()[:5]}")
    return mk.reset_index(drop=True)


def load_trades(ticker):
    """{'yes': (times as int64 ns, prices), 'no': (...)} for one market; taker price per side."""
    path = os.path.join(RAW_DIR, "trades", f"{ticker}.jsonl.gz")
    if not os.path.exists(path):
        return None
    sides, seen = {"yes": ([], []), "no": ([], [])}, set()
    with gzip.open(path, "rt") as f:
        for line in f:
            t = json.loads(line)
            if t["trade_id"] in seen:
                continue
            seen.add(t["trade_id"])
            side = t["taker_side"]
            sides[side][0].append(t["created_time"])
            sides[side][1].append(float(t[f"{side}_price_dollars"]))
    out = {}
    for side, (times, prices) in sides.items():
        ts = (pd.to_datetime(times, utc=True, format="ISO8601").as_unit("ns").asi8 if times
              else np.array([], "int64"))
        order = np.argsort(ts)
        out[side] = (ts[order], np.array(prices)[order])
    return out


def nearest_trade(trades, side, at, tol_min, kickoff):
    """Closest taker trade on `side` within tol_min of `at`, before kickoff. (price, gap_min, n) or None."""
    if not trades:
        return None
    times, prices = trades[side]
    lo = np.searchsorted(times, (at - pd.Timedelta(minutes=tol_min)).value)
    hi = np.searchsorted(times, min(at + pd.Timedelta(minutes=tol_min), kickoff).value)
    if hi <= lo:
        return None
    window = times[lo:hi]
    i = lo + int(np.argmin(np.abs(window - at.value)))
    price = prices[i]
    if not 0 < price < 1:
        return None
    return price, (times[i] - at.value) / 6e10, hi - lo


# ---------------------------------------------------------------- sportsbook side

def load_book(start, end):
    h = pd.read_csv(BOOK_FILE, dtype={"event_id": str})
    for c in ("snapshot_ts", "commence_time", "market_last_update"):
        h[c] = pd.to_datetime(h[c], utc=True, format="ISO8601")
    h = h[(h.commence_time >= start - pd.Timedelta(days=1)) & (h.commence_time < end + pd.Timedelta(days=1))]
    h = h[h.bookmaker.isin(BOOKS)].copy()
    h["point"] = h.point.round(1)
    first = h.sort_values("snapshot_ts").groupby("event_id").first()
    events = first[["home_team", "away_team", "commence_time"]].rename(columns={"commence_time": "first_commence"})
    events["last_commence"] = h.groupby("event_id").commence_time.max()
    return h, events


def match_games(mk, events, names):
    """One row per Kalshi game with the provider event it maps to, or why none."""
    rows = []
    for game, g in mk.groupby("game"):
        g0 = g.iloc[0]
        home, away, ko = names[g0.home], names[g0.away], g0.kickoff
        cand = events[((events.home_team == home) & (events.away_team == away)) |
                      ((events.home_team == away) & (events.away_team == home))].copy()
        cand["gap_h"] = (cand.first_commence - ko).abs().dt.total_seconds() / 3600
        cand = cand[cand.gap_h <= 12].sort_values("gap_h")
        row = {"game": game, "week": g0.week, "kickoff": ko, "away": away, "home": home}
        if cand.empty:
            rows.append(dict(row, event_id=None, status="game_not_at_provider"))
            continue
        e = cand.iloc[0]
        rows.append(dict(row, event_id=e.name, status="matched",
                         home_away_swapped=e.home_team != home,
                         provider_kickoff=e.first_commence, provider_kickoff_last=e.last_commence,
                         kickoff_gap_min=(e.first_commence - ko).total_seconds() / 60))
    return pd.DataFrame(rows)


def pick_snapshots(event_rows, kickoff):
    """{snapshot name: snapshot_ts or None}, using the windows in SNAPSHOTS."""
    ts = pd.Series(event_rows.snapshot_ts.unique())
    before = (kickoff - ts).dt.total_seconds() / 60
    out = {}
    for name, target, lo, hi, _ in SNAPSHOTS:
        if name == "close":
            ok = ts[(before > 0) & (before <= hi)]
            out[name] = ok.max() if len(ok) else None
        else:
            ok = ts[(before >= lo) & (before <= hi)]
            out[name] = ok[(before[ok.index] - target).abs().idxmin()] if len(ok) else None
    return out


def bet_label(leg):
    market, outcome, point = leg
    if market == "h2h":
        return outcome
    return f"{outcome} {point:+g}" if market == "spreads" else f"{outcome} {point:g}"


def book_lines(rows):
    """{(market, outcome, point): row} for one book at one snapshot. point is None for moneylines."""
    out = {}
    for r in rows.itertuples():
        point = None if r.market == "h2h" else float(r.point)
        out[(r.market, r.outcome, point)] = r
    return out


def legs(m, names):
    """The book outcomes for Kalshi YES and NO (NO on a moneyline is the other team's moneyline)."""
    if m.series == "KXNFLGAME":
        other = m.home if m.team == m.away else m.away
        return ("h2h", names[m.team], None), ("h2h", names[other], None)
    if m.series == "KXNFLSPREAD":
        other = m.home if m.team == m.away else m.away
        return ("spreads", names[m.team], -m.strike), ("spreads", names[other], m.strike)
    return ("totals", "Over", m.strike), ("totals", "Under", m.strike)


def no_vig(lines, yes_leg, no_leg):
    """Chance of the YES leg with the margin removed, or None if either side is missing."""
    if yes_leg not in lines or no_leg not in lines:
        return None
    a, b = 1 / lines[yes_leg].price_decimal, 1 / lines[no_leg].price_decimal
    return a / (a + b)


# ---------------------------------------------------------------- matching

def cost_per_10(q, paid):
    return 10 * (1 - q / paid) if q is not None and paid else np.nan


def kalshi_all_in(price):
    return price + TAKER_RATE * price * (1 - price)


def run(mk, games, h, names):
    rows_by_snap = {k: g for k, g in h.groupby(["event_id", "snapshot_ts", "bookmaker"])}
    rows_by_event = {k: g for k, g in h.groupby("event_id")}
    trade_cache = {}

    def trades(ticker):
        if ticker not in trade_cache:
            trade_cache[ticker] = load_trades(ticker)
        return trade_cache[ticker]

    market_rows, pair_rows = [], []
    game_info = games.set_index("game")
    by_game = {g: d for g, d in mk.groupby("game")}
    for game, gm in by_game.items():
        gi = game_info.loc[game]
        kickoff = gm.kickoff.iloc[0]
        snaps = (pick_snapshots(rows_by_event[gi.event_id], kickoff) if gi.status == "matched"
                 else {s[0]: None for s in SNAPSHOTS})
        game_markets = {(m.series, m.team): m for m in gm.itertuples() if m.series == "KXNFLGAME"}
        for snap_name, _, _, _, tol in SNAPSHOTS:
            ts = snaps[snap_name]
            pin = book_lines(rows_by_snap.get((gi.event_id, ts, "Pinnacle"), h.iloc[:0])) if ts is not None else {}
            for book in BOOKS:
                lines = book_lines(rows_by_snap.get((gi.event_id, ts, book), h.iloc[:0])) if ts is not None else {}
                posted = {k[0] for k in lines}
                for m in gm.itertuples():
                    yes_leg, no_leg = legs(m, names)
                    base = {"ticker": m.ticker, "type": m.type, "game": game, "week": m.week,
                            "kickoff": kickoff, "team": m.team, "strike": m.strike, "book": book,
                            "snapshot": snap_name, "book_snapshot_ts": ts,
                            "minutes_before_kickoff": (kickoff - ts).total_seconds() / 60 if ts is not None else np.nan}
                    if gi.status != "matched":
                        market_rows.append(dict(base, status="game_not_at_provider"))
                        continue
                    if ts is None:
                        market_rows.append(dict(base, status="no_snapshot_near_time"))
                        continue
                    if yes_leg[0] not in posted:
                        market_rows.append(dict(base, status="book_did_not_post_market"))
                        continue
                    if yes_leg not in lines:
                        book_pts = sorted({k[2] for k in lines if k[0] == yes_leg[0] and k[1] == yes_leg[1]})
                        market_rows.append(dict(base, status="different_number", book_point=book_pts[0] if book_pts else np.nan))
                        continue
                    if m.open_time > ts:
                        market_rows.append(dict(base, status="kalshi_market_not_open_yet"))
                        continue

                    # Kalshi prices: YES and NO of this market; for moneylines the "other side" is the other
                    # team's YES, since that is how a Kalshi user would bet the other team.
                    tr = trades(m.ticker)
                    k_yes = nearest_trade(tr, "yes", ts, tol, kickoff)
                    if m.series == "KXNFLGAME":
                        other = game_markets.get(("KXNFLGAME", m.home if m.team == m.away else m.away))
                        k_no = nearest_trade(trades(other.ticker), "yes", ts, tol, kickoff) if other else None
                        sides = [("yes", yes_leg, no_leg, k_yes, k_no)]  # the other team's market gives the other side
                    else:
                        k_no = nearest_trade(tr, "no", ts, tol, kickoff)
                        sides = [("yes", yes_leg, no_leg, k_yes, k_no), ("no", no_leg, yes_leg, k_no, k_yes)]
                    own_k = (k_yes is not None) if m.series == "KXNFLGAME" else (k_yes is not None or k_no is not None)
                    status = "matched" if own_k else "no_kalshi_trade_near_time"
                    market_rows.append(dict(base, status=status, book_point=yes_leg[2]))
                    if status != "matched":
                        continue

                    for side, leg, opp, k, k_opp in sides:
                        if k is None:
                            continue
                        b, b_opp = lines[leg], lines.get(opp)
                        p_book = 1 / b.price_decimal
                        p_book_opp = 1 / b_opp.price_decimal if b_opp is not None else np.nan
                        q_own = no_vig(lines, leg, opp)
                        q_pin = no_vig(pin, leg, opp)
                        k_paid = kalshi_all_in(k[0])
                        k_paid_opp = kalshi_all_in(k_opp[0]) if k_opp is not None else np.nan
                        k_q_own = k_paid / (k_paid + k_paid_opp) if k_opp is not None else None
                        age = (ts - b.market_last_update).total_seconds() / 60
                        pair_rows.append({
                            **base, "side": side, "bet": bet_label(leg),
                            "book_american": b.price_american, "book_implied": p_book,
                            "book_overround": p_book + p_book_opp,
                            "book_line_age_min": age, "book_line_stale": age > STALE_MINUTES,
                            "kalshi_price": k[0], "kalshi_all_in": k_paid, "kalshi_trade_gap_min": k[1],
                            "kalshi_trades_in_window": k[2], "kalshi_overround": k_paid + k_paid_opp,
                            "fair_own_book": q_own, "fair_pinnacle": q_pin,
                            "book_cost_per_10_vs_own": cost_per_10(q_own, p_book),
                            "book_cost_per_10_vs_pinnacle": cost_per_10(q_pin, p_book),
                            "kalshi_fee_per_10": 10 * (k_paid - k[0]) / k_paid,
                            "kalshi_cost_per_10_vs_own": cost_per_10(k_q_own, k_paid),
                            "kalshi_cost_per_10_vs_pinnacle": cost_per_10(q_pin, k_paid),
                        })
    return pd.DataFrame(market_rows), pd.DataFrame(pair_rows)


def book_side(market_rows, mk, games, h, names):
    """Sportsbook point of view: for each line a book posted, is there a Kalshi market for it?"""
    code_of = {v: k for k, v in names.items()}
    kalshi_spread = {(m.game, m.team, m.strike) for m in mk[mk.series == "KXNFLSPREAD"].itertuples()}
    kalshi_total = {(m.game, m.strike) for m in mk[mk.series == "KXNFLTOTAL"].itertuples()}
    status = market_rows.set_index(["ticker", "book", "snapshot"]).status
    ticker_of = {(m.series, m.game, m.team if isinstance(m.team, str) else None,
                  None if np.isnan(m.strike) else m.strike): m.ticker for m in mk.itertuples()}
    used = market_rows.dropna(subset=["book_snapshot_ts"])[["game", "snapshot", "book_snapshot_ts", "kickoff", "week"]].drop_duplicates()
    ev = games.set_index("game").event_id
    snap = h.set_index(["event_id", "snapshot_ts", "bookmaker"]).sort_index()
    rows = []
    for u in used.itertuples():
        for book in BOOKS:
            key = (ev[u.game], u.book_snapshot_ts, book)
            if key not in snap.index:
                continue
            lines = snap.loc[key]
            for market, ml in lines.groupby("market"):
                if market == "h2h":
                    units = [(o, None) for o in ml.outcome]
                elif market == "spreads":
                    fav = ml[ml.point < 0]
                    units = [(fav.outcome.iloc[0], -fav.point.iloc[0])] if len(fav) else [(ml.outcome.iloc[0], 0.0)]
                else:
                    units = [("Over", ml.point.iloc[0])]
                for outcome, point in units:
                    r = {"game": u.game, "week": u.week, "book": book, "snapshot": u.snapshot,
                         "type": {"h2h": "Who wins", "spreads": "Point spread", "totals": "Total points"}[market],
                         "line": outcome if point is None else f"{outcome} {('-' if market == 'spreads' else '')}{point:g}"}
                    team = code_of.get(outcome)
                    if point is not None and point == round(point):
                        r["status"] = "book_line_whole_number"
                    elif market == "spreads" and (u.game, team, point) not in kalshi_spread:
                        r["status"] = "no_kalshi_market_at_number"
                    elif market == "totals" and (u.game, point) not in kalshi_total:
                        r["status"] = "no_kalshi_market_at_number"
                    else:
                        series = {"h2h": "KXNFLGAME", "spreads": "KXNFLSPREAD", "totals": "KXNFLTOTAL"}[market]
                        tk = ticker_of.get((series, u.game, team if market != "totals" else None, point))
                        r["ticker"] = tk
                        r["status"] = status.get((tk, book, u.snapshot), "no_kalshi_market_at_number") if tk else "no_kalshi_market_at_number"
                    rows.append(r)
    return pd.DataFrame(rows)


def rate_table(df, by):
    t = df.groupby(by + ["status"], observed=True).size().unstack(fill_value=0)
    t.insert(0, "total", t.sum(axis=1))
    t.insert(1, "match_rate", t.get("matched", 0) / t.total)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", nargs="+", type=int, default=[2, 3, 4, 5])
    args = ap.parse_args()

    names, kalshi_names = load_teams()
    mk = load_kalshi_markets(args.weeks, set(names), kalshi_names)
    h, events = load_book(mk.kickoff.min(), mk.kickoff.max())
    missing_teams = (set(events.home_team) | set(events.away_team)) - set(names.values())
    if missing_teams:
        raise ValueError(f"provider teams not in team_names.csv: {missing_teams}")
    games = match_games(mk, events, names)
    print(f"Weeks {args.weeks}: {len(games)} Kalshi games, {(games.status == 'matched').sum()} found at the provider, "
          f"{len(mk)} Kalshi markets")
    no_trades = [t for t in mk.ticker if not os.path.exists(os.path.join(RAW_DIR, "trades", f"{t}.jsonl.gz"))]
    if no_trades:
        print(f"WARNING: {len(no_trades)} markets have no trade file. Run pull_trades.py first.")

    market_rows, pairs = run(mk, games, h, names)
    book = book_side(market_rows, mk, games, h, names)

    os.makedirs(OUT_DIR, exist_ok=True)
    save = lambda df, name, **kw: df.to_csv(os.path.join(OUT_DIR, name + ".csv"), **kw)
    order = [s[0] for s in SNAPSHOTS]
    for df in (market_rows, pairs, book):
        df["snapshot"] = pd.Categorical(df.snapshot, categories=order, ordered=True)
        df["book"] = pd.Categorical(df.book, categories=BOOKS, ordered=True)

    save(games, "games", index=False)
    save(market_rows, "kalshi_markets_matched", index=False)
    save(book, "book_lines_matched", index=False)
    save(pairs, "side_by_side", index=False)
    save(rate_table(market_rows, ["type"]), "match_rate_kalshi_by_type")
    save(rate_table(market_rows, ["type", "book", "snapshot"]), "match_rate_kalshi")
    save(rate_table(book, ["type"]), "match_rate_book_by_type")
    save(rate_table(book, ["type", "book", "snapshot"]), "match_rate_book")
    save(pd.Series(REASONS, name="meaning").rename_axis("status"), "reasons")

    # Side-by-side summary: median cost per $10 for each matched pair
    pairs["price_group"] = pd.cut(pairs.fair_own_book * 100, PRICE_EDGES, right=False, labels=PRICE_GROUPS)
    cost_cols = ["book_cost_per_10_vs_own", "kalshi_cost_per_10_vs_own", "book_cost_per_10_vs_pinnacle",
                 "kalshi_cost_per_10_vs_pinnacle", "kalshi_fee_per_10"]

    def summary(by):
        g = pairs.groupby(by, observed=True)
        out = g[cost_cols].median()
        out.insert(0, "pairs", g.size())
        out["kalshi_cheaper_vs_pinnacle_share"] = g.apply(
            lambda d: (d.kalshi_cost_per_10_vs_pinnacle < d.book_cost_per_10_vs_pinnacle)[
                d.fair_pinnacle.notna()].mean(), include_groups=False)
        return out.round(3)

    save(summary(["type", "book", "snapshot"]), "side_by_side_summary")
    save(summary(["type", "book"]), "side_by_side_by_type_book")
    save(summary(["type", "price_group"]), "side_by_side_by_price_group")

    print("\nKalshi markets matched (any book, any snapshot):")
    print(rate_table(market_rows, ["type"]).to_string())
    print("\nSportsbook lines with a Kalshi twin:")
    print(rate_table(book, ["type"]).to_string())
    print(f"\n{len(pairs):,} matched price pairs. Median cost per $10 by market type and book:")
    print(summary(["type", "book"]).to_string())
    print(f"\nTables written to {OUT_DIR}/")


if __name__ == "__main__":
    main()
