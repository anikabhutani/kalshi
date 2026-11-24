# Task 7 Part 1: in-game swings, college (ncaaf)

Theo. College football, 2025 season and 2026 to date. Same method as the NFL run on `abhi-bsb-kalshi`
(`bsb_kalshi/backend/app/ingame/`), ported to standalone scripts.

## Rerun

Python with pandas, numpy, requests and matplotlib. Put a CollegeFootballData key in `task7_college/.env`
(`CFBD_API_KEY=...`). Kalshi is read-only and needs no key. The Task 5 raw pulls (`kalshi_raw_2025_season_nfl_ncaaf.zip`,
`kalshi_raw_2026_college_ncaaf.zip`) are read from two folders up if present (`config.RAW_ZIPS`); otherwise
those candles are pulled.

```
cd task7_college
python data.py all          # CFBD games + plays, Kalshi market list, crosswalk, candles (cached in data/)
python data.py wp           # CFBD win probability for a seeded sample of good-timestamp games
python swings.py            # steps 1-5 and 7
python timestamp_list.py    # step 6
python swings.py --k-pct 97.5 && python timestamp_list.py --k-pct 97.5    # robustness -> output/k_p97.5/
python swings.py --k-pct 99.5 && python timestamp_list.py --k-pct 99.5    # robustness -> output/k_p99.5/
```

Every threshold is in `config.py`. `--steady-range 1` gives the tighter steady rule (output/steady1/).

## Files (output/)

| File | What |
|---|---|
| `kalshi_minutes_ncaaf_<season>.csv` | step 1 minute table, kickoff to final whistle, with `filled`, `quiet`, `flagged`, `steady`, `d5` |
| `swings_ncaaf.csv` | one row per swing: t, mids before/after, move, before/after times, minutes to settle, `status` / `drop_reason`, matched CFBD play, sigma, threshold, peak z, `on_list` |
| `timestamp_list_ncaaf.csv` | Odds API request time (UTC), sport key, before/after, swing ids covered |
| `credit_estimate_ncaaf.{md,json}` | unique timestamps and credits by season |
| `kalshi_at_swings_ncaaf.csv` | bid, ask, mid, spread, fee, cost per $10 for both teams at every before/after time |
| `summaries_ncaaf.{md,json}` | step 7 summaries (before vs after cost, by play type, by swing size, minutes to settle) |
| `threshold_ncaaf.{md,json}` | k at 97.5/99/99.5, quiet minutes, games used, catch and match rates, sigma range, floor and fallback games |
| `games_ncaaf.csv` | every Kalshi event: used or why not, timestamp check result, sigma and its source, source market |
| `swings_<event>.png` | the step 5 plots |
| `k_p97.5/`, `k_p99.5/` | the same files at the other thresholds (minute tables not committed) |
