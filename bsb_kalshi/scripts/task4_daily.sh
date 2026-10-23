#!/usr/bin/env bash
# Daily Task 4 update: pick up newly played NFL games, then rebuild results and charts.
#
# Source today is a file export (odds_data.zip). The backfill remembers the last --path, so
# replace that file with a newer export and this picks up the new games. Games already saved
# as complete are skipped. When an Odds API key exists, switch to: --source api
#
# Cron example (every day at 9:10 am local time):
#   10 9 * * * /path/to/bsb-kalshi/scripts/task4_daily.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/data/task4/daily.log"
mkdir -p "$ROOT/data/task4"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY=python3
cd "$ROOT/backend"
{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  "$PY" -m app.task4.sportsbook_backfill "$@"
  "$PY" -m app.task4.sportsbook_report
} >>"$LOG" 2>&1
