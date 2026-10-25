# Kalshi Recon

A local web app that probes the **Kalshi Predictions API** (REST + WebSocket), logs every
request as evidence, and visualizes the results so a researcher can answer six questions
about what the API can provide for comparing Kalshi sports-contract prices with sportsbook
odds.

The backend is a read-only, rate-limited client. The frontend collects data, computes
objective metrics, and draws charts. **All findings are typed by you.**

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Scaffold, spec loader, signed GET-only client, rate limiter, evidence log, connection status, UI shell + Home | done |
| 2 | M1 Endpoints, M2 Schema, M3 Timestamps | done |
| 3 | M4 Depth, M5 Limits, M8 Export | done |
| 4 | M6 REST vs WebSocket, M7 Sportsbook overlay | done (awaiting your testing) |

## Setup

Requirements: Python 3.11+ and Node 20+.

```bash
make install                 # backend venv + pip install, frontend npm install
cp .env.example .env         # then fill in the values below
```

`.env` (paste the private key text between the double quotes; multiple lines are fine):

```
KALSHI_KEY_ID=<your API key id>
KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----"
```

Alternatively leave `KALSHI_PRIVATE_KEY` empty and set
`KALSHI_PRIVATE_KEY_PATH=./secrets/kalshi-read.pem` to a PEM file (`secrets/` is git-ignored).

Use a **read-scope** key. Production keys only work against production hosts; demo keys only
against demo hosts (choose the base URL in Settings, gear icon in the top bar).

## Run

```bash
make dev        # backend on http://127.0.0.1:8000, frontend on http://127.0.0.1:5173
```

Or separately: `make backend` and `make frontend`. Tests: `make test`.

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`; set `BACKEND_URL` to point it
at a backend on another port.

## Task 4: sportsbook vig and cost per $10 (NFL)

DraftKings, FanDuel and Pinnacle; moneyline, spread and total; every played NFL game of the 2025
season (regular season and playoffs) and the 2026 season so far, each season calculated and
charted separately (`SEASONS` in `common.py`). Code is in `backend/app/task4/`; everything it
writes goes to `data/task4/` (git-ignored). In the app, open **Task 4** in the sidebar
(`/task4`): enter the path to the odds export once and press **Run backfill and calculate**; the
page shows the checklist, the self-checks, games list, quality check, and a 2025 and a 2026
version of every chart. Same steps from the command line:

```bash
make sportsbook-backfill ODDS_FILE=~/Downloads/odds_data.zip   # first run: save raw per game
make sportsbook-report                                         # costs, checks, charts (exit 1 if a check fails)
make sportsbook                                                # both; reuses the last file
```

- **Source:** today the only source is the `odds_data.zip` export from `odds_history_pull.py`.
  `--source api` is a placeholder for The Odds API and exits until it is implemented and an
  `ODDS_API_KEY` is in `.env`.
- **Raw:** each game's rows, unchanged, in `data/task4/raw/<event_id>.csv.gz`.
  `data/task4/manifest.json` records which games are complete, so reruns skip them.
- **Games list:** `data/task4/games.csv` (season, week or playoff round, kickoff, and which books
  posted each market).
- **Results:** `data/task4/results/<season>/` (see the docstring of `sportsbook_report.py` for
  each file) and `data/task4/charts/<season>/*.png`. Every number in a chart note or on the page
  comes from that season's `facts.json`; none is typed in.
- **Self-checks:** `checks.py` runs after every calculation and writes `checks.json` per season:
  odds recomputed with exact fractions, Shin's fair prices inverted back to the book's prices,
  every cost and the headline table recomputed independently, longshots costing more than
  favorites, no mirror-image price groups, every game present, closing lines within an hour of
  kickoff, no in-game prices, no game in the wrong season, weeks matching the NFL calendar, chart
  notes matching the tables, and Kalshi coverage. Tests in `tests/test_task4_sportsbook.py`
  deliberately reintroduce each earlier mistake and confirm the checks catch it.
- **Daily:** `scripts/task4_daily.sh` runs both steps and logs to `data/task4/daily.log`.
  Schedule it with cron (example in the script). With a file source it only finds new games
  when the file at the remembered path is replaced with a newer export.

Kalshi is added to the Task 4 tables and charts from Task 3's API data
(`data/task3/exports/checkpoint_quotes.csv` and `checkpoint_costs.csv`): run Task 3 first, then
Task 4. To compare like with like it uses the 15-minute quote, 10 contracts, and for spreads and
totals only the strike nearest 50¢ (`kalshi_all_strikes.csv` shows the every-strike average too).
Kalshi appears only in seasons Task 3 has downloaded (by default Task 3 starts Sept 14, 2026, so
2025 has no Kalshi and 2026 week 1 is partly missing; the Kalshi coverage check says so).

Definitions: cost per $10 = expected loss on a $10 bet at the fair (no-vig) price, found with
Shin's method, which lets the margin fall more on longshots (`sportsbook_costs.py` has the formula).
A market's cost is the average of its two sides. The simpler proportional method
(`10 * (1 - 1 / (p_a + p_b))`) charges both sides of a bet the same, so it hides any
favorite/longshot difference; its results are kept in `*_proportional` columns as a check.
DraftKings and FanDuel sides are also priced against Pinnacle's fair line at the same snapshot
and line. Closing line = last snapshot before kickoff, if it is within an hour of kickoff (an
older last price is left out and listed in the quality check). Snapshots after kickoff are
excluded.
The data has no game results, so the de-vig method can't be tested against outcomes here.

## Alignment: Kalshi vs sportsbooks on the same games (both seasons)

Code in `backend/app/alignment/`, output in `data/alignment/` (git-ignored).

```bash
make trade-sizes SEASON=2026   # median / p75 / p90 Kalshi trade size (needs the Kalshi key; resumable)
make align SEASON=2026         # steps 1-5 for one season; then SEASON=2025 (re-run after trade sizes)
```

- **Trade sizes** (`trade_sizes.py`): Task 3 keeps 1-minute candles, which only hold volume per
  minute, so this pulls every individual trade (`/markets/trades` + `/historical/trades`, merged
  by `trade_id`, no silent page cap) for the season's game, spread and total markets in the Task 3
  store. Reports per-trade and per-contract percentiles, with and without block trades; every
  value is a real trade size (`inverted_cdf`). Saved per market, so a stop (first HTTP 429) loses
  nothing: rerun to continue. `--from-saved` recomputes without requests.
- **Pipeline** (`pipeline.py`): 1. game list (kickoff = the provider's final start time; most
  games shift a few minutes, flexed games by up to a day); 2. crosswalk from `KXNFLGAME` tickers
  (Eastern-time dates, teams split by the two market suffixes, `teams.py` for the 32 teams; every
  game `matched` or a reason code); 3. snapshots at 24h, 3h, 1h, 15m and kickoff with
  `merge_asof(direction="backward")` for Kalshi and each book, with each price's age;
  4. costs (`costs.py`): cost per $10 = 10 x (1 - fair / price paid) for every venue (Kalshi,
  Pinnacle, FanDuel, DraftKings) against every ruler: **ruler A = Kalshi** (the two team markets'
  mid prices, scaled to 100%), **ruler B = Pinnacle, FanDuel, DraftKings** (each book's two prices
  de-vigged with Shin; proportional kept alongside). Kalshi price = cheaper of YES on the team's
  market at the ask or NO on the opponent's at 1 - bid, plus the taker fee 0.07 x n x p x (1 - p)
  rounded up to the cent per order, at n = the median / p75 / p90 trade size (the team's
  placeholder sizes 1, 5, 10, 25, 100 until `make trade-sizes` has run). Sportsbook prices older
  than `MAX_AGE_MIN` at the checkpoint (24h 6 h, 3h 45 min, 1h 15 min, 15m 10 min, close 60 min)
  are kept but marked not usable. 5. checks and the three files per season (`crosswalk.csv`,
  `snapshots.csv`, `costs.csv`), plus `kalshi_events_unmatched.csv`, `checks.json` and `summary.md`
  (median cost table: venue x ruler x checkpoint).
- **Checks** (`checks.py`): independent re-lookup of every snapshot without `merge_asof`, no
  look-ahead, full grid, Kalshi team prices summing to about $1, Kalshi vs sportsbook agreeing on
  which team is which, one-to-one matching, Eastern dates, unknown team codes, price ages; for
  costs: full grid, each ruler summing to 100%, every usable cost recomputed with exact fractions
  and a closed-form Shin, fee rounded up per order, positive own-book margin, n only on Kalshi,
  no stale price used, and a warning while n is still the placeholder.
  `tests/test_alignment.py` breaks each one on purpose and confirms it is caught.
- **2025 Kalshi data**: Task 3 starts at 2026-09-14 by default; for 2025 run
  `cd backend && .venv/bin/python -m app.task3.backfill --start-date 2025-09-01`.

## College football alignment (same five steps)

`backend/app/alignment/college.py`, output in `data/alignment/ncaaf/<season>/` (git-ignored). Reads
`data/odds_data.zip` (college odds) and Theo's `data/kalshi_raw_2025_season_nfl_ncaaf.zip` (Kalshi
markets and 1-minute candles) without unzipping.

```bash
make college SEASON=2025   # ~3 min
```

Same steps and code as the NFL (`pipeline.snapshots`, `costs.compute`, the snapshot and cost checks);
only the crosswalk differs: there is no fixed table for ~250 schools, so a Kalshi game is matched to
the odds game on the same date (+-1 day) whose *both* team names agree (Kalshi's school name must
start the feed name, and a following "State", "Tech", "A&M", ... means another school), clearly ahead
of the runner-up and mutually. The team table is then learned from the matches (`team_table.csv`) and
checked: one school per Kalshi code and per Kalshi name. Kalshi duplicate listings of one game keep
the listing with candles and more volume. n values: the NFL game-winner trade sizes (no college trade
sizes pulled). The three files: `crosswalk.csv`, `snapshots.csv`, `costs.csv.gz` (gzip; pandas
reads it directly).

## In-game analysis (page "In-game")

Code in `backend/app/ingame/analysis.py`, output in `data/ingame/<season>/` (git-ignored). No Kalshi
requests: it reads the trades saved by `make trade-sizes` (2026 so far) and the Task 3 candles and
market results (2025 and 2026).

```bash
make ingame        # both seasons; ~40 s the first time, seconds after (cached per market)
```

- **Kickoff**: Kalshi's milestone start time; else the sportsbook feed's final start time
  (`data/alignment/<season>/crosswalk.csv`); else Task 3's estimate. Preseason left out.
- **Trades** (2026): money, fees and trade counts by time from kickoff and by price group of the
  side the taker bought; trade sizes; fee rounding; taker result per $10 before/after fees on
  settled markets (ties left out). Fees use Kalshi's formula 0.07 x contracts x p x (1 - p) rounded
  up to the cent per fill, in exact integer arithmetic.
- **Prices** (both seasons): bid/ask sampled every 5 minutes from 3 h before to 4 h after kickoff
  (latest candle at or before each moment, never after settlement): spread, cost per $10 at the
  median trade size, share of markets with both sides quoted; accuracy (Brier score, calibration
  slope, reliability) of one market per game at -60, 0, 30, ..., 180 minutes vs the result.
- **Uncertainty**: 95% intervals resample whole games, 1,000 times. Points after 150 minutes only
  include unfinished games, so they are biased toward close or long games.
- **Checks**: trades reconcile with the trade-size report, every trade binned once, fees recomputed
  with exact fractions, no trades after settlement, taker totals equal by two paths, kickoff sources
  agree, exactly one winner per game, no look-ahead, no crossed quotes, enough games per checkpoint.
  `tests/test_ingame.py` breaks each one on purpose.

## Sources of truth

Everything the app knows about the API comes from `specs/`:

| File | Used for |
|---|---|
| `specs/openapi.yaml` | REST endpoint catalog, params, auth requirement, base URLs. Downloaded from `https://docs.kalshi.com/openapi.yaml` (info.version 3.32.0). |
| `specs/asyncapi.yaml` | WebSocket server, channels, messages. Downloaded from `https://docs.kalshi.com/asyncapi.yaml` (info.version 2.0.0). |
| `specs/auth_notes.md` | Request signing (RSA-PSS / SHA-256, `timestamp + METHOD + path`), WebSocket handshake signing and the REST ↔ WebSocket host table. |
| `specs/rate_limits.md` | Documented token buckets and 429 behavior. |

The client refuses to call any path that is not a GET operation in `specs/openapi.yaml`.

## How modules map to the research questions

| Question | Modules | Page |
|---|---|---|
| Q1 How is the data organized? | M2 Schema, M1 Endpoints | Schema |
| Q2 Where do timestamps come from? | M3 Timestamp Lab | Timestamps |
| Q3 What is live vs archived, how far back? | M4 Depth & Archive | Depth |
| Q4 Practical limits (auth, rate, pagination) | M1 auth matrix, M5 Limits | Limits |
| Q5 Which endpoints matter? | M1 Endpoints (your ratings) | Endpoints |
| Q6 REST vs WebSocket | M6 Recorder | REST vs WS |

M7 (sportsbook overlay) is a support tool; M8 exports the evidence appendix.

## Modules available now

Every job asks for confirmation in a safety dialog (request estimate, hard cap, minimum
duration) when it may send more than 10 requests. Each page restores its latest stored results
on load, has a "Raw requests" drawer, and an autosaving notes box.

Notes are also copied to `notes/answers.json` (tracked by git) on every save, so commit that
file to keep your answers. On startup, any empty notes box is filled from it, so a fresh clone
shows your answers; text already in the database is never overwritten. A note containing the
key id or private-key text is not copied to the file.

- **M1 Endpoints** (`/endpoints`). All 117 operations from `specs/openapi.yaml` with objective
  signals: tag, auth per spec, pagination params, time-range params, timestamp fields, historical
  signals, account-specific flag. The **auth probe** discovers IDs from public list endpoints,
  then calls each probe-able GET once without the key and once with it, and classifies the
  result (public / key required / denied even with key / inconclusive / error / not probed).
  Account and portfolio endpoints are excluded by default (tick "Include account/portfolio
  read endpoints" to probe them; their response bodies are still never stored). The probe has a
  fixed hard cap of 150 requests. Mismatches with the spec's security declaration are flagged. Charts: spec claim × observed
  matrix, classification by tag. Your 1–5 rating and reason per endpoint autosave (Q5).
- **M2 Schema** (`/schema`). Categories, tags and series come from `/search/tags_by_categories`
  and `/series` (nothing hardcoded). **Pull game** fetches series → event (with nested markets) →
  markets list, stores raw JSON, and builds a field dictionary per entity (path, observed types,
  example, presence, nulls, detected timestamp format, distinct values) compared with the spec
  schema (in spec, type/format, nullable, required, values outside the spec enum, spec fields
  not observed). The relationship tree shows which fields equal the parent identifier, checked
  on every record.
- **M3 Timestamps** (`/timestamps`). For one market and window: candlesticks at every
  `period_interval` the spec allows (live or `/historical` per `GET /historical/cutoff`), trades
  (paged up to your cap), an orderbook snapshot, and market metadata timestamps. Metrics per
  source: records, first/last, finest/median/max spacing, expected vs missing slots, slots
  without a trade, longest/median gap, timestamp field and format. A clock check compares every
  response's `Date` header with local time. `price_at` returns, for each source, the latest price
  at or before a moment, its timestamp, and staleness. Charts: price lines or candles with
  bid/ask, trades and volume; data-density heatmap; gap timeline.
- **M4 Depth & Archive** (`/depth`). Reads `GET /historical/cutoff`, then finds the oldest and
  newest retrievable record per endpoint. Endpoints with an upper time-bound parameter
  (`/markets/trades` and `/historical/trades` via `max_ts`; `/markets` via `max_settled_ts` with
  `status=settled`, or `max_close_ts`) are binary-searched with `limit=1` requests down to an
  hour or a day; `/historical/markets` has no time parameters in the spec, so it is paged by
  cursor up to a page cap. The archive matrix takes one archived and one settled sample market
  (plus yours, optionally) and requests each from the live and historical market, trades and
  candlestick endpoints and `/events/{event_ticker}`. Hard request cap (default 80). Charts:
  availability timeline per endpoint with the cutoff lines, availability matrix.
- **M5 Limits** (`/limits`). `specs/rate_limits.md` parsed into tier and cost tables, shown next
  to the client limiter and (with a key) `GET /account/limits` and `GET /account/endpoint_costs`.
  **Ramp test**: one public endpoint at stepped target rates (default 1 → 2 req/s in 0.5 steps,
  10 requests per step), recording status, latency and any rate-limit headers; it stops at the
  first 429. Steps above the Settings rate limit are rejected, and a run is capped at 200
  requests. **Pagination analyzer**: server default size, spec maximum, maximum + 1 and minimum,
  then a cursor walk recording items per page, duplicates, cursor reuse and the end-of-list
  signal. Charts: latency vs target rate, per-request timeline, header values over time, items
  per page.
- **M6 REST vs WebSocket** (`/rest-vs-ws`). For one live market and 1–30 minutes: one
  authenticated WebSocket (URL paired with the configured REST host in `specs/auth_notes.md`,
  handshake signed over `timestamp + "GET" + "/trade-api/ws/v2"`) subscribed to `ticker` and
  `trade` (optionally `orderbook_delta`) with `market_ticker`, while REST polls
  `GET /markets/{ticker}` (and optionally `GET /markets/trades` with `min_ts` overlap) at your
  interval through the global limiter. Every message is kept with its local receive time and
  appended raw to `data/raw/ws-<job id>.jsonl`; the handshake and the subscribe command are
  evidence rows (`WS handshake`, `WS subscribe`) and count toward the request cap. Reconnects use
  exponential backoff (at most 6 handshakes); a 401/403 handshake, a missing subscription
  acknowledgement, or the first HTTP 429 stops the job. Metrics: messages per type, WS price
  changes, REST changes detected, REST misses per poll interval, trades matched by `trade_id`,
  latency (receive − `ts_ms`, receive − `sending_ts_ms`), sequence gaps per `sid`, connections,
  reconnects and errors. Charts: event timeline (WS vs REST), bid/ask/last from both feeds,
  latency histogram, cumulative updates. A REST vs WebSocket table is filled only with text from
  the spec files (auth, channels, delivery, timestamps, sequence, keep-alive, limits).
- **M7 Sportsbook overlay** (`/sportsbook`). Upload a CSV (`timestamp_utc, book, event, market,
  odds_american, odds_decimal`; template downloadable) or generate labelled **DUMMY DATA** for
  the window of a stored Timestamp Lab run. Odds become implied probability (American
  `100/(A+100)` or `−A/(−A+100)`, decimal `1/D`); rows sharing timestamp, book and event with
  exactly two outcomes get proportional no-vig probability `p/(p_a+p_b)` and the overround.
  The overlay picks one outcome and one Kalshi price series from a stored M3 run and uses
  `price_at` for the latest Kalshi price at or before each sportsbook timestamp; the gap
  (Kalshi − sportsbook, percentage points) is computed only when that price is within your
  age limit. Kalshi probability is YES price ÷ $1.00 (fees not included). M7 never calls
  Kalshi.
- **Task 3 NFL costs** (`/task3`). Lists every event and market in `KXNFLGAME`, `KXNFLSPREAD`
  and `KXNFLTOTAL` with kickoff (US Eastern) on or after the start date (default 2026-09-14),
  settled ones included. Kickoff and week come from `GET /milestones?type=football_game`.
  `backend/app/task3/backfill.py` downloads 1-minute candles (bid, ask, last, volume, open
  interest) from open to settlement with the batch `GET /markets/candlesticks` (at most 100
  tickers and 10,000 market-minutes per request). Markets that only exist in the archive
  (`GET /historical/markets`) are read from `GET /historical/markets/{ticker}/candlesticks`. Raw
  responses are saved as gzip in `data/task3/raw/`, and candles go to `data/task3/nfl_costs.db`.
  Cost of a bet = half the bid-ask gap + taker fee `ceil(0.07 × C × P × (1 − P))` (rounded up to
  the cent by default, or to $0.0001), at 1/10/100 contracts and 24 h/3 h/1 h/15 min before
  kickoff, using the last candle at or before each checkpoint, for both YES and NO. Results show
  cost per $10 bet by price group, market type and week, plus a quality check: markets with no
  candles, bid above ask, and gaps of 3¢ or more. CSVs are written to `data/task3/exports/`.
  Daily update: `make backfill` re-lists games and fetches only minutes after each market's
  `fetched_through`. Fully downloaded settled markets are never requested again. Cron example:
  `15 9 * * * cd <repo>/backend && .venv/bin/python -m app.task3.backfill >> <repo>/data/task3/backfill.log 2>&1`.
- **M8 Evidence & Export** (`/evidence`). Confirm the API version and date checked, pick charts,
  and export to `data/exports/kalshi-recon-export-<UTC time>/`: `appendix.md` (header, your
  Q1–Q6 notes verbatim with placeholders where empty, M1–M6 metric tables, jobs, every logged
  request), `csv/*.csv` (one per table, full request log included) and `charts/*.png` (rendered
  in the browser with Plotly from the stored results). Before anything is written the export is
  scanned for the key id and private-key fragments; on a match it aborts and writes nothing.

## Spec notes and assumptions

Places where the specs were silent or the live API differed. None of these are guessed
silently; each is either a marked `TODO(spec)` in code or shown as data in the UI.

- **Candles per request.** The spec gives no maximum number of candlesticks per response. M3
  splits windows into chunks of at most 1440 periods (`CANDLES_PER_REQUEST`, `TODO(spec)` in
  `m3_timestamps.py`).
- **Market status values.** Live markets report `status: "finalized"`, which is not in the
  `GET /events` `status` filter enum (`unopened, open, closed, settled`). M2 shows observed
  values outside a spec enum.
- **Daily candles** end at 04:00 UTC (`end_period_ts % 86400 == 14400`), reported as the
  alignment offset in M3 metrics.
- **1-minute candles** are omitted for minutes with no activity, and `price` is `{}` when a
  period had no trade; M3 counts both separately (missing periods vs periods without a trade).
- **Orderbook** responses carry no timestamp field; M3 uses the local receive time and the
  `Date` header, and says so in the table.
- **Auth probe coverage.** Endpoints whose path or required query parameters need an ID that
  cannot be discovered from a public list (for example order IDs, subaccount IDs) are listed as
  "not probed" with the reason.
- **`/historical/markets` depth.** The spec lists no time-range parameters for it, so M4 walks it
  by cursor (newest first as served) and reports the oldest record seen within the page cap,
  not the true oldest.
- **Time bounds are exclusive.** `max_ts` is documented as "before this Unix timestamp"; the
  bisection treats every upper bound as exclusive.
- **Rate-limit headers.** `specs/rate_limits.md` says 429 responses currently carry no
  `Retry-After` or `X-RateLimit-*` headers. M5 records whatever rate-related headers appear and
  shows an empty state listing the header names seen if none are numeric.
- **Tier budget units.** Tier read/write budgets are shown as tokens per second, as written in
  `specs/rate_limits.md`. Matching your account's tier to a documented tier is a
  case-insensitive name comparison.
- **Pagination boundary cases** may send `limit` = spec maximum + 1 and the spec minimum on
  purpose, to record what the server does outside the documented range.
- **WebSocket hosts.** `specs/asyncapi.yaml` lists only the production server. The demo and
  `api.elections` WebSocket URLs come from the `specs/auth_notes.md` tables, paired with the
  REST host in the same row and column.
- **WebSocket limits.** `specs/rate_limits.md` does not mention WebSocket. The only limit text
  in the specs is asyncapi error codes 26 and 27; the comparison table says so.
- **`orderbook_delta`** is a subscribe channel in asyncapi but listed under "Private channels"
  in `specs/auth_notes.md`. It is off by default and marked on the page.
- **Price-state pairing.** REST `last_price_dollars` ("Price for the last traded YES contract")
  is compared with WS ticker `price_dollars` ("Last traded price") by their spec descriptions.
- **Latency** values are local receive time minus a Kalshi timestamp, so they include the local
  clock offset; the REST `Date` header offset (1 s resolution) is shown next to them.
- **Trades overlap.** REST trade polls use `min_ts` = previous poll time − 5 s and the spec
  maximum `limit`; the spec does not say whether `min_ts` is inclusive, so duplicates are removed
  by `trade_id`. Trades are compared only from the first confirmed subscription (the
  `subscribed` ack's `sending_ts_ms`), since earlier trades could not have been streamed.
- **CSV `market` column** is read as the outcome name (one row per outcome); two-way no-vig needs
  exactly two outcome rows per timestamp, book and event.

## Safety design

- **GET-only.** `KalshiClient.call` raises `ReadOnlyViolation` for any other method, and an
  httpx request hook rejects non-GET requests a second time. The WebSocket client can only
  encode a `subscribe` command for `ticker`, `trade` or `orderbook_delta` with a market ticker
  (`app/ws_client.py`, `WsCommandBlocked` otherwise); sessions end by closing the socket.
- **Spec-bound.** Paths must match a GET operation in `specs/openapi.yaml`.
- **Polite.** One request in flight at a time; global token bucket (default 2 req/s, burst 2,
  editable in Settings); transport errors and 5xx retried at most twice; 4xx never retried;
  the first HTTP 429 stops the job and pauses the client (honoring `Retry-After` if Kalshi ever
  sends it; `specs/rate_limits.md` says it currently does not). Every job has a hard request
  cap, and the red **Stop all jobs** button cancels everything.
- **Secrets.** The key id and private key are read from `.env` by the backend only. They are
  never logged, returned to the frontend, or written to the database. `KALSHI-ACCESS-*`,
  `Authorization`, and cookie headers are redacted, and the key id is scrubbed from any stored
  text. Response bodies from account endpoints (`/portfolio`, `/fcm`, `/api_keys`,
  `/communications`, personal `/historical/fills|orders|positions`) are never stored.
- **Evidence.** Every attempt is a row in SQLite table `requests` (`data/kalshi_recon.db`).
  Jobs can save full public response bodies to `data/raw/<request id>.json`.

## What this tool does NOT do

- It does not place, amend, or cancel orders, transfer funds, or change any account setting.
  It never sends anything but GET to the REST API, and nothing but market-data `subscribe`
  commands over the WebSocket.
- It does not fetch sportsbook odds. M7 uses only files you upload or clearly labelled DUMMY
  DATA.
- It does not write findings, summaries, interpretations, or recommendations. Every
  "answer" field is a text box you fill in. Exports contain your notes verbatim, with empty
  placeholders where you have not written anything.
- It does not use the Perps APIs.
- It does not send your key or signatures anywhere except to Kalshi in request headers.

## Project layout

```
backend/
  app/main.py            FastAPI app
  app/config.py          .env settings (secrets live only here and in the client)
  app/kalshi_client.py   signing, token bucket, GET-only guard, retries, evidence logging
  app/ws_client.py       subscribe-only WebSocket client (signed handshake, evidence rows)
  app/evidence.py        redaction + SQLite evidence log
  app/spec_loader.py     OpenAPI / AsyncAPI parsing
  app/jobs.py            background jobs, cancellation, request caps, SSE events
  app/settings_store.py  user-editable settings (API version, base URL, rate limit)
  app/modules/           one router per module (m0 core, m1 endpoints, m2 schema, m3 timestamps,
                         m4 depth, m5 limits, m6 REST vs WS, m7 sportsbook, m8 export)
  app/analysis/          pure metric code: gaps, price_at, timestamp formats, JSON flattening,
                         auth probe, depth bisection, rate-limit doc / ramp / pagination,
                         WS vs REST comparison, spec comparison, odds, sportsbook CSV, export
  tests/                 unit tests (throwaway keys, mocked transport)
frontend/
  src/pages/             one page per module
  src/components/        layout, tables, charts (lazy-loaded Plotly), notes, job progress,
                         raw-requests drawer, safety dialog, per-module components
  src/lib/api.ts         typed backend client
specs/                   source-of-truth documents
notes/answers.json       your Q1-Q6 notes (tracked copy, restored into an empty database)
data/                    SQLite DB, raw bodies, exports (git-ignored)
```
