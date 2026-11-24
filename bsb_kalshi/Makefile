.PHONY: install dev backend frontend test build backfill sportsbook-backfill sportsbook-report sportsbook trade-sizes align ingame college slide-charts trade-list

PYTHON ?= python3

install:
	cd backend && $(PYTHON) -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

dev:
	./scripts/dev.sh

backend:
	cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/python -m pytest -q

build:
	cd frontend && npm run build

backfill:
	cd backend && .venv/bin/python -m app.task3.backfill

# Task 4: sportsbook odds. First run: make sportsbook-backfill ODDS_FILE=~/Downloads/odds_data.zip
sportsbook-backfill:
	cd backend && .venv/bin/python -m app.task4.sportsbook_backfill $(if $(ODDS_FILE),--path $(ODDS_FILE),)

sportsbook-report:
	cd backend && .venv/bin/python -m app.task4.sportsbook_report

sportsbook: sportsbook-backfill sportsbook-report

# Alignment (Kalshi vs sportsbooks, same games and moments). SEASON=2026 or 2025.
trade-sizes:
	cd backend && .venv/bin/python -m app.alignment.trade_sizes --season $(SEASON) $(if $(LEAGUE),--league $(LEAGUE),) $(if $(SERIES),--series $(SERIES),)

align:
	cd backend && .venv/bin/python -m app.alignment.pipeline --season $(SEASON)

# In-game analysis (needs make trade-sizes for trades; Task 3 for prices and results). Both seasons.
ingame:
	cd backend && .venv/bin/python -m app.ingame.analysis --season 2025 && .venv/bin/python -m app.ingame.analysis --season 2026

# College football (NCAAF) alignment, one season. Needs data/odds_data.zip and Theo's raw Kalshi zip in data/.
college:
	cd backend && .venv/bin/python -m app.alignment.college --season $(or $(SEASON),2025)

# Deck charts and stat-box numbers (Kalshi vs. the sportsbooks). LEAGUE=ncaaf (default) or nfl.
slide-charts:
	cd backend && .venv/bin/python -m app.alignment.slide_charts --league $(or $(LEAGUE),ncaaf)

# Trades for a list of markets (data/alignment/extra/markets/$(LABEL).csv), several workers, one shared rate limit.
trade-list:
	cd backend && .venv/bin/python -m app.alignment.trade_sizes --markets-file ../data/alignment/extra/markets/$(LABEL).csv --label $(LABEL) --concurrency $(or $(CONCURRENCY),1) $(if $(RPS),--rps $(RPS),)

# Task 7 in-game swings (college). Pull needs internet, your Kalshi key and CFBD_API_KEY in .env.
ingame-pull:
	cd backend && .venv/bin/python -m app.ingame.swing_data pull --season $(or $(SEASON),2026)

# Task 7 NFL (2025 + 2026): Task 3 candles -> nflverse -> swings -> timestamp list. Run make task3 first for new games.
swings-nfl:
	cd backend && .venv/bin/python -m app.ingame.swing_data export-task3
	cd backend && .venv/bin/python -m app.ingame.swing_data fill-nfl-zip
	cd backend && .venv/bin/python -m app.ingame.swing_data pull-nflverse
	cd backend && .venv/bin/python -m app.ingame.swings --league nfl --seasons 2025 2026 $(if $(STEADY),--steady-range $(STEADY),)
	cd backend && .venv/bin/python -m app.ingame.timestamp_list --league nfl
