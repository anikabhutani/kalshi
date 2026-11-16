# busy_market_inputs_nfl.csv: inputs for the busy-market test (NFL)

One row per game × team × pregame snapshot (24h, 3h, 1h, 15m, kickoff), 2025 season and 2026 to date. That is 363 games and 3,630 rows; 3,620 have a usable Kalshi row. Ruler A (fair price = Kalshi midpoint), Kalshi at the median trade size (24 contracts). Costs come straight from the Task 5 aligned files (`output/alignment/<season>/costs.csv`); volume and open interest come from the Kalshi 1-minute candles in the Task 3 store (`data/task3/nfl_costs.db`).

## Columns
| Column | Meaning |
|---|---|
| game_id, season, week, team, team_code, side | As in the Task 5 files |
| snapshot, snapshot_utc, kickoff_utc | Pregame snapshot ("kickoff" = Task 5's "close" checkpoint) |
| kalshi_ticker, kalshi_route | Kalshi market for the team; route = how Task 5 priced the bet (YES on the team's market, or NO on the opponent's) |
| kalshi_fair | Kalshi midpoint, 0–1 (the ruler A fair price) |
| price_group | longshot < 0.40, middle 0.40–0.60, favorite ≥ 0.60 (by kalshi_fair) |
| kalshi_cost_per10 | Kalshi cost per $10 = 10 × (1 − fair ÷ price paid), in dollars (0.43 = 43¢) |
| kalshi_fee_part_per10 | The part of that cost that is the fee (Task 5 `fee_per_10`) |
| kalshi_bidask_part_per10 | The rest: cost − fee part (paying the ask instead of the midpoint) |
| kalshi_usable | Task 5 usable flag for the Kalshi row |
| fanduel_cost_per10, draftkings_cost_per10, *_usable | Book cost per $10 under ruler A, with the Task 5 usable flags (price-age limits) |
| extra_cost_fanduel_per10, extra_cost_draftkings_per10 | Book cost − Kalshi cost, same game, team, snapshot (dollars per $10) |
| volume_60m_contracts | Contracts traded on the team's Kalshi market in the 60 minutes up to the snapshot (sum of 1-minute candle volume, minutes ending in (t − 60 min, t]) |
| volume_60m_dollars | The same in dollars: each minute's contracts × that minute's midpoint (last trade if no quote) |
| volume_60m_contracts_both_markets | Both teams' markets combined (game-level alternative) |
| open_interest_contracts | Contracts held on the team's market at the snapshot (last candle at or before the snapshot) |
| open_interest_both_markets | Both markets combined |
| open_interest_age_min | Minutes between that candle and the snapshot (median 0.1, max 7) |
| depth_available | Always False: our candle files store only the best bid and ask, not the order book. **Depth cannot be tested**; per the brief, say so in the paper and don't claim it was tested. |

## Use only usable rows, and know where they are
- Kalshi: 3,620 of 3,630 usable (the 10 unusable have no Kalshi price).
- Sportsbooks (Task 5 price-age rule), share of rows usable:

| Snapshot | 2025 | 2026 |
|---|---|---|
| 24h | 84% | 84% |
| 3h | 40% | 45% |
| 1h | 21% | 51% |
| 15m | 3% | 0% |
| kickoff | 99–100% | 100% |

So questions 1–2 (Kalshi's own cost and its bid-ask part) can use all snapshots. Question 3 (extra cost over each book) rests mostly on the 24h and kickoff rows, and 15m is effectively unavailable. Say so in the paper.

## Notes
- Volume is very skewed (median about 109,000 contracts in the hour, max 8.3 million). Ranking into quartiles, as the brief asks, avoids the scale problem.
- Kalshi costs are for a taker order at 24 contracts; volume and open interest don't change that assumption.
- Every row from the same game is one piece of evidence: resample or cluster by game_id.
