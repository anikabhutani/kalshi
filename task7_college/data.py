"""Task 7 Part 1 inputs (college): CollegeFootballData games and plays, the Kalshi KXNCAAFGAME market list,
a game crosswalk, and 1-minute candles around each game. Everything is cached under data/<season>/,
so rerunning only fetches what is missing.

    python data.py all                 # cfbd -> markets -> crosswalk -> candles
    python data.py wp                  # after swings.py has run once: win probability sample (CFBD calls)
    python data.py <step> --season 2026

Candles: reuse the Task 5 raw pulls first (config.RAW_ZIPS); anything not in a zip is pulled from Kalshi
(read-only GETs, no key): live batch /markets/candlesticks, or /historical/markets/{ticker}/candlesticks
for markets past the historical cutoff.
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

import config as C
from common import (EASTERN, candle_rows, load_cfbd_games, load_plays, name_score, save_candles, season_dir,
                    ticker_date, timestamp_quality, unix)

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
MAX_BATCH_CANDLES = 10_000      # live batch: tickers x minutes requested
MAX_HIST_CANDLES = 5_000        # historical: minutes per request
log = logging.getLogger("data")


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------

class Kalshi:
    """GET-only, rate-limited, retries 429 / 5xx. Never touches private endpoints."""

    def __init__(self, rps=C.KALSHI_RPS):
        self.s = requests.Session()
        self.interval = 1.0 / rps
        self.next = time.monotonic()
        self.lock = threading.Lock()
        self.count = 0

    def get(self, path, params=None):
        for attempt in range(8):
            with self.lock:
                now = time.monotonic()
                slot = max(now, self.next)
                self.next = slot + self.interval
            time.sleep(max(0.0, slot - now))
            self.count += 1
            try:
                r = self.s.get(KALSHI + path, params=params, timeout=60)
            except requests.RequestException as e:
                log.warning(f"network error {e}; retry")
                time.sleep(2 ** min(attempt, 5))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** min(attempt, 6))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} on {path} {params}: {r.text[:300]}")
            return r.json()
        raise RuntimeError(f"gave up on {path}")

    def pages(self, path, params, key):
        out, cursor = [], None
        while True:
            p = dict(params, **({"cursor": cursor} if cursor else {}))
            body = self.get(path, p)
            out += body.get(key) or []
            cursor = body.get("cursor")
            if not cursor or not body.get(key):
                return out


class CFBDClient:
    def __init__(self):
        key = C.cfbd_key()
        if not key:
            sys.exit("CFBD_API_KEY missing: add CFBD_API_KEY=... to task7_college/.env")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {key}", "accept": "application/json"})
        self.calls = 0
        self.remaining = None

    def get(self, path, params):
        for attempt in range(3):
            r = self.s.get(C.CFBD + path, params=params, timeout=180)
            self.calls += 1
            self.remaining = r.headers.get("X-CallLimit-Remaining", self.remaining)
            if r.status_code == 429:
                time.sleep(15 * (attempt + 1))
                continue
            if r.status_code == 401:
                sys.exit("CollegeFootballData returned 401: check CFBD_API_KEY in .env")
            r.raise_for_status()
            return r.json()
        r.raise_for_status()


# --------------------------------------------------------------------------------------
# CollegeFootballData: games and plays
# --------------------------------------------------------------------------------------

def pull_cfbd(season):
    cf = CFBDClient()
    folder = season_dir(season, "cfbd")
    now = pd.Timestamp.now(tz="UTC")
    gpath = os.path.join(folder, "games.json")
    games = cf.get("/games", {"year": season, "seasonType": "both"})
    json.dump(games, open(gpath, "w", encoding="utf-8"))
    g = load_cfbd_games(season)
    g = g[g["completed"].fillna(False).astype(bool) & (g["start"] < now)]
    print(f"{season}: {len(g)} completed CFBD games")
    for (stype, week), grp in g.groupby(["season_type", "week"]):
        path = os.path.join(folder, f"plays_{stype}_{int(week)}.json")
        # a week is final once its last game started more than 36 h ago; until then it is re-pulled
        if os.path.exists(path) and grp["start"].max() < now - pd.Timedelta(hours=36):
            continue
        plays = []
        for cls in C.CFBD_PLAY_CLASSIFICATIONS:
            plays += cf.get("/plays", {"year": season, "week": int(week), "seasonType": stype,
                                       "classification": cls}) or []
        json.dump(plays, open(path, "w", encoding="utf-8"))
        print(f"  plays {stype} week {int(week)}: {len(plays)}")
    print(f"CFBD: {cf.calls} calls this run; {cf.remaining} left this month")


# --------------------------------------------------------------------------------------
# Kalshi market list
# --------------------------------------------------------------------------------------

def pull_markets(seasons):
    k = Kalshi()
    folder = season_dir("kalshi")
    live = k.pages("/events", {"series_ticker": C.KALSHI_SERIES, "limit": 200, "with_nested_markets": "true"},
                   "events")
    json.dump(live, open(os.path.join(folder, "events_live.json"), "w", encoding="utf-8"))
    hist = k.pages("/historical/markets", {"series_ticker": C.KALSHI_SERIES, "limit": 1000}, "markets")
    json.dump(hist, open(os.path.join(folder, "markets_historical.json"), "w", encoding="utf-8"))
    rows = []
    for e in live:
        for m in e.get("markets") or []:
            rows.append(market_row(m, "live"))
    rows += [market_row(m, "historical") for m in hist]
    mk = pd.DataFrame(rows).drop_duplicates("ticker", keep="last")
    mk.to_csv(os.path.join(folder, "markets.csv"), index=False)
    print(f"Kalshi: {len(mk)} {C.KALSHI_SERIES} markets ({(mk.source == 'historical').sum()} archived) "
          f"in {mk.event_ticker.nunique()} events; {k.count} requests")


def market_row(m, source):
    return {"ticker": m.get("ticker"), "event_ticker": m.get("event_ticker"), "team": m.get("yes_sub_title"),
            "result": m.get("result"), "status": m.get("status"), "settlement_ts": m.get("settlement_ts"),
            "volume": m.get("volume_fp", m.get("volume")), "source": source}


def kalshi_events():
    mk = pd.read_csv(os.path.join(season_dir("kalshi"), "markets.csv"))
    mk["date"] = mk["event_ticker"].map(ticker_date)
    ev = (mk.sort_values("ticker").groupby("event_ticker")
            .agg(date=("date", "first"), tickers=("ticker", list), teams=("team", list),
                 source=("source", "first"), volume=("volume", "sum")).reset_index())
    return ev[ev["tickers"].map(len) == 2].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Crosswalk: Kalshi event <-> CFBD game
# --------------------------------------------------------------------------------------

def crosswalk(season):
    g = load_cfbd_games(season)
    lo, hi = (pd.Timestamp(x, tz="UTC") for x in C.SEASON_RANGE[season])
    g = g[g["completed"].fillna(False).astype(bool) & (g["start"] >= lo) & (g["start"] < hi)].copy()
    g["et_date"] = g["start"].dt.tz_convert(EASTERN).dt.date
    ev = kalshi_events()
    ev = ev[ev["date"].map(lambda d: d is not None and lo.date() <= d < hi.date())].reset_index(drop=True)
    # Void duplicates (e.g. the whole Oct 17 2026 slate was listed twice; the OCT17 copies never traded and
    # settled 'scalar', the games traded under OCT16 tickers) are logged and left out of matching.
    dead = pd.to_numeric(ev["volume"], errors="coerce").fillna(0) <= 0
    dead_log = ev[dead]
    ev = ev[~dead].reset_index(drop=True)
    by_date = {d: x for d, x in g.groupby("et_date")}
    cands = []
    for ei, e in ev.iterrows():
        for dd in (-1, 0, 1):
            near = by_date.get(e["date"] + pd.Timedelta(days=dd))
            if near is None:
                continue
            for gi, r in near.iterrows():
                for home_idx in (0, 1):
                    sh = name_score(e["teams"][home_idx], r["home"])
                    sa = name_score(e["teams"][1 - home_idx], r["away"])
                    if min(sh, sa) >= C.NAME_MATCH_MIN:
                        cands.append((sh + sa - 0.01 * abs(dd), ei, gi, home_idx, min(sh, sa)))
    # best name score first; ties (Kalshi sometimes lists a game twice, one event dead with no volume) go to
    # the event with more volume
    vol = pd.to_numeric(ev["volume"], errors="coerce").fillna(0)
    used_e, used_g, rows = set(), set(), []
    for score, ei, gi, home_idx, worst in sorted(cands, key=lambda c: (-round(c[0], 6), -vol[c[1]])):
        if ei in used_e or gi in used_g:
            continue
        used_e.add(ei)
        used_g.add(gi)
        e, r = ev.loc[ei], g.loc[gi]
        rows.append({"event_ticker": e["event_ticker"], "game_id": int(r["id"]), "season": season,
                     "season_type": r["season_type"], "week": int(r["week"]), "home": r["home"], "away": r["away"],
                     "home_cls": r.get("home_cls"), "away_cls": r.get("away_cls"),
                     "neutral_site": bool(r.get("neutral_site")), "scheduled_start_utc": r["start"],
                     "start_tbd": bool(r.get("start_tbd")), "ticker_home": e["tickers"][home_idx],
                     "ticker_away": e["tickers"][1 - home_idx], "kalshi_home": e["teams"][home_idx],
                     "kalshi_away": e["teams"][1 - home_idx], "kalshi_source": e["source"],
                     "kalshi_volume": e["volume"], "match_score_worst": round(worst, 3), "status": "matched"})
    cw = pd.DataFrame(rows)
    for ei, e in ev.iterrows():
        if ei not in used_e:
            cw = pd.concat([cw, pd.DataFrame([{"event_ticker": e["event_ticker"], "season": season,
                                               "kalshi_home": e["teams"][0], "kalshi_away": e["teams"][1],
                                               "kalshi_volume": e["volume"],
                                               "status": "no CFBD game (name/date)"}])], ignore_index=True)
    if len(dead_log):
        cw = pd.concat([cw, pd.DataFrame({"event_ticker": dead_log["event_ticker"], "season": season,
                                          "kalshi_volume": 0, "status": "zero-volume Kalshi event"})],
                       ignore_index=True)
    m = cw["status"] == "matched"
    fbs =(cw["home_cls"] == "fbs") | (cw["away_cls"] == "fbs")
    cw.loc[m & ~fbs, "status"] = "no FBS team" if C.FBS_ONLY else "matched"
    cw.to_csv(season_dir(season, "crosswalk.csv"), index=False)
    print(f"{season}: {len(ev)} Kalshi events -> {cw.status.value_counts().to_dict()}; "
          f"{len(g) - m.sum()} completed CFBD games have no Kalshi event")
    bad = cw[cw.status.str.startswith("no CFBD")]
    if len(bad):
        print("  unmatched Kalshi events (first 15):",
              ", ".join(f"{r.event_ticker} [{r.kalshi_home} / {r.kalshi_away}]" for r in bad.head(15).itertuples()))


def in_scope(season):
    cw = pd.read_csv(season_dir(season, "crosswalk.csv"))
    cw = cw[cw["status"] == "matched"].copy()
    cw["scheduled_start_utc"] = pd.to_datetime(cw["scheduled_start_utc"], utc=True, format="ISO8601")
    return cw


# --------------------------------------------------------------------------------------
# Candles
# --------------------------------------------------------------------------------------

def window(start):
    s = unix(start)
    return s - C.CANDLE_PAD_BEFORE_H * 3600, s + C.CANDLE_PAD_AFTER_H * 3600


class ZipIndex:
    """Task 5 raw pulls. 2025: raw/candles/<series>/<ticker>.json ({ticker, candlesticks}).
    2026: raw/candles/<event>/<event>__g0__<start>.json ({markets: [{market_ticker, candlesticks}]})."""

    def __init__(self, paths):
        self.zips = []
        for p in paths:
            if os.path.exists(p):
                z = zipfile.ZipFile(p)
                by_ticker, by_event = {}, {}
                for n in z.namelist():
                    parts = n.split("/")
                    if len(parts) == 4 and parts[1] == "candles" and n.endswith(".json"):
                        if parts[2] == C.KALSHI_SERIES:
                            by_ticker[parts[3][:-5]] = n
                        elif parts[2].startswith(C.KALSHI_SERIES + "-"):
                            by_event.setdefault(parts[2], []).append(n)
                self.zips.append((z, by_ticker, by_event))
                print(f"  zip {os.path.basename(p)}: {len(by_ticker)} market files, {len(by_event)} event folders")
            else:
                print(f"  zip not found, will pull instead: {p}")

    def rows(self, event, tickers, lo, hi):
        for z, by_ticker, by_event in self.zips:
            if all(t in by_ticker for t in tickers):
                out = []
                for t in tickers:
                    body = json.loads(z.read(by_ticker[t]))
                    out += candle_rows(t, body.get("candlesticks") or [], lo, hi)
                return out
            if event in by_event:
                out = []
                for n in by_event[event]:
                    start = int(n.rsplit("__", 1)[1][:-5])
                    if start > hi or start + 400_000 < lo:
                        continue
                    for m in json.loads(z.read(n)).get("markets") or []:
                        t = m.get("market_ticker") or m.get("ticker")
                        if t in tickers:
                            out += candle_rows(t, m.get("candlesticks") or [], lo, hi)
                return out
        return None


def covers_game(path, start):
    """A saved candle file counts only if it reaches 2.5 h past the scheduled start (a batch call can come back
    with just the 'latest before start' candle; quick games settle about 2 h 50 min after the start)."""
    if not os.path.exists(path):
        return False
    ts = pd.read_csv(path, usecols=["ts"])["ts"]
    return len(ts) > 0 and ts.max() >= unix(start) + 2.5 * 3600


def pull_candles(season, one_per_call=False):
    cw = in_scope(season)
    folder = season_dir(season, "candles")
    todo = cw[[not covers_game(os.path.join(folder, f"{r.event_ticker}.csv.gz"), r.scheduled_start_utc)
               for r in cw.itertuples()]]
    print(f"{season}: {len(cw)} games in scope, {len(todo)} need a candle file")
    if todo.empty:
        return
    zi = ZipIndex(C.RAW_ZIPS.get(season, []))
    api = []
    from_zip = 0
    for r in todo.itertuples():
        lo, hi = window(r.scheduled_start_utc)
        rows = zi.rows(r.event_ticker, [r.ticker_home, r.ticker_away], lo, hi)
        # a zip file that does not reach the game (e.g. pulled before it was played) goes to the API
        if rows and max(x["ts"] for x in rows) >= lo + (C.CANDLE_PAD_BEFORE_H + 2.5) * 3600:
            save_candles(os.path.join(folder, f"{r.event_ticker}.csv.gz"), rows)
            from_zip += 1
        else:
            api.append(r)
    print(f"  {from_zip} games from the raw pulls; {len(api)} from the API")
    if not api:
        return
    k = Kalshi()
    live = [r for r in api if r.kalshi_source == "live"]
    hist = [r for r in api if r.kalshi_source != "live"]
    minutes = (C.CANDLE_PAD_BEFORE_H + C.CANDLE_PAD_AFTER_H) * 60 + 1
    per_call = max(1, MAX_BATCH_CANDLES // (2 * minutes))     # games per batch call (2 markets each)
    # batch calls share one window, so group games with close start times
    live.sort(key=lambda r: r.scheduled_start_utc)
    done = 0
    for i in range(0, len(live), per_call):
        grp = live[i:i + per_call]
        lo = min(window(r.scheduled_start_utc)[0] for r in grp)
        hi = max(window(r.scheduled_start_utc)[1] for r in grp)
        if one_per_call or (hi - lo) // 60 * 2 * len(grp) > MAX_BATCH_CANDLES:   # spread-out starts: one per call
            sub = [[r] for r in grp]
        else:
            sub = [grp]
        for g2 in sub:
            lo = min(window(r.scheduled_start_utc)[0] for r in g2)
            hi = max(window(r.scheduled_start_utc)[1] for r in g2)
            tks = [t for r in g2 for t in (r.ticker_home, r.ticker_away)]
            body = k.get("/markets/candlesticks", {"market_tickers": ",".join(tks), "start_ts": lo, "end_ts": hi,
                                                   "period_interval": 1, "include_latest_before_start": "true"})
            got = {}
            for m in body.get("markets") or []:
                t = m.get("market_ticker") or m.get("ticker")
                got[t] = m.get("candlesticks") or []
            for r in g2:
                rows = []
                for t in (r.ticker_home, r.ticker_away):
                    if t in got:
                        rows += candle_rows(t, got[t])
                    else:   # archived since the market list was pulled
                        rows += hist_candles(k, t, *window(r.scheduled_start_utc))
                save_candles(os.path.join(folder, f"{r.event_ticker}.csv.gz"), rows)
                done += 1
        print(f"  live: {done}/{len(live)} games, {k.count} requests", flush=True)
    for j, r in enumerate(hist, 1):
        lo, hi = window(r.scheduled_start_utc)
        rows = hist_candles(k, r.ticker_home, lo, hi) + hist_candles(k, r.ticker_away, lo, hi)
        save_candles(os.path.join(folder, f"{r.event_ticker}.csv.gz"), rows)
        if j % 25 == 0 or j == len(hist):
            print(f"  historical: {j}/{len(hist)} games, {k.count} requests", flush=True)
    print(f"Kalshi candles: {k.count} requests")


def hist_candles(k, ticker, lo, hi):
    rows, t = [], lo
    while t <= hi:
        end = min(hi, t + (MAX_HIST_CANDLES - 1) * 60)
        body = k.get(f"/historical/markets/{ticker}/candlesticks", {"start_ts": t, "end_ts": end, "period_interval": 1})
        rows += candle_rows(ticker, body.get("candlesticks") or [])
        t = end + 60
    return rows


# --------------------------------------------------------------------------------------
# Win probability sample
# --------------------------------------------------------------------------------------

def pull_wp(seasons):
    """CFBD in-game win probability for a seeded random sample of good-timestamp games (the only games the
    catch rate uses), up to config.CFBD_WP_MAX_CALLS calls in total across seasons."""
    pool = []
    for season in seasons:
        cw = in_scope(season)
        pl = load_plays(season)
        by = {gid: x for gid, x in pl.groupby("game_id")}
        for r in cw.itertuples():
            good = timestamp_quality(by.get(r.game_id, pd.DataFrame()), r.scheduled_start_utc)[0] \
                if r.game_id in by else False
            if good:
                pool.append((season, int(r.game_id)))
    rng = np.random.default_rng(C.CFBD_WP_SEED)
    order = [pool[i] for i in rng.permutation(len(pool))]
    have = [(s, g) for s, g in order if os.path.exists(season_dir(s, "cfbd", "wp", f"{g}.json"))]
    budget = C.CFBD_WP_MAX_CALLS - len(have)
    todo = [(s, g) for s, g in order if (s, g) not in set(have)][:max(0, budget)]
    print(f"Good-timestamp games: {len(pool)}; win probability already saved for {len(have)}; pulling {len(todo)}")
    if not todo:
        return
    cf = CFBDClient()
    for j, (s, g) in enumerate(todo, 1):
        try:
            body = cf.get("/metrics/wp", {"gameId": g})
        except requests.HTTPError:
            body = []
        json.dump(body, open(season_dir(s, "cfbd", "wp", f"{g}.json"), "w", encoding="utf-8"))
        if j % 50 == 0 or j == len(todo):
            print(f"  {j}/{len(todo)} (CFBD calls left this month: {cf.remaining})", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["all", "cfbd", "markets", "crosswalk", "candles", "wp"])
    ap.add_argument("--season", type=int, nargs="+", default=list(C.SEASONS))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.step in ("all", "cfbd"):
        for s in a.season:
            pull_cfbd(s)
    if a.step in ("all", "markets"):
        pull_markets(a.season)
    if a.step in ("all", "crosswalk"):
        for s in a.season:
            crosswalk(s)
    if a.step in ("all", "candles"):
        for s in a.season:
            pull_candles(s)
            pull_candles(s, one_per_call=True)   # retry anything a batch call returned short
    if a.step == "wp":
        pull_wp(a.season)


if __name__ == "__main__":
    main()
