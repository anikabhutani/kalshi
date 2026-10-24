# Alignment, 2025 season

Generated 2026-10-24 09:08 UTC. Games: 285; matched: 283; Kalshi events left unmatched: 0.

## Match status

- matched: 283 (Matched to one Kalshi event with one market per team.)
- no_kalshi_event: 2 (No Kalshi event for these two teams within a day of kickoff.)

## Checks

- [pass] 32-team table is valid: 32 teams, no code used for two teams.
- [warn] Game list: each game once, final kickoff time: 285 games; 0 duplicates; 0 from another season; 0 not using the provider's final start time. Kickoff moved by more than 60 min after first listing: Denver Broncos at New York Jets (+61 min), New England Patriots at New Orleans Saints (-202 min), San Francisco 49ers at Tampa Bay Buccaneers (+206 min), Los Angeles Rams at Jacksonville Jaguars (+62 min), Cincinnati Bengals at Buffalo Bills (-202 min), Chicago Bears at Green Bay Packers (+205 min), Philadelphia Eagles at Washington Commanders (+123 min), Green Bay Packers at Chicago Bears (+440 min), Cincinnati Bengals at Miami Dolphins (-437 min), New England Patriots at Baltimore Ravens (+442 min), Houston Texans at Los Angeles Chargers (-1230 min), Baltimore Ravens at Green Bay Packers (-1019 min), Carolina Panthers at Tampa Bay Buccaneers (-1230 min), Seattle Seahawks at San Francisco 49ers (-1020 min), Detroit Lions at Chicago Bears (+205 min), Arizona Cardinals at Los Angeles Rams (+205 min), Washington Commanders at Philadelphia Eagles (+205 min), New York Jets at Buffalo Bills (+205 min), Miami Dolphins at New England Patriots (+205 min), Kansas City Chiefs at Las Vegas Raiders (+205 min), Baltimore Ravens at Pittsburgh Steelers (+443 min), Los Angeles Rams at Carolina Panthers (-1226 min), Green Bay Packers at Chicago Bears (-1020 min), San Francisco 49ers at Philadelphia Eagles (+222 min), Los Angeles Chargers at New England Patriots (+435 min), San Francisco 49ers at Seattle Seahawks (-1020 min), Los Angeles Rams at Chicago Bears (+340 min).
- [warn] Every game is matched or has a reason code: {'matched': 283, 'no_kalshi_event': 2}
- [pass] Each game has its own two Kalshi markets, one per team: 283 matched games; 0 Kalshi events used twice; 0 without two distinct markets; 0 markets whose ticker team is not the team they are filed under.
- [warn] Ticker dates match kickoff dates (Eastern): 3 ticker dates differ by a day: KXNFLGAME-26JAN04CARTB vs Jan 03, KXNFLGAME-26JAN04SEASF vs Jan 03, KXNFLGAME-26JAN18SFSEA vs Jan 17
- [pass] Every Kalshi team code is in the table: All codes in 283 Kalshi events are known.
- [pass] Kalshi events not matched to a game: 0 Kalshi events unmatched; 0 of them dated inside the season's game dates (listed in kalshi_events_unmatched.csv).
- [pass] No price from after its checkpoint: 11,310 prices; 0 timestamped after their checkpoint; 0 negative ages; checkpoints all 0-24 h before their kickoff.
- [pass] Snapshot prices recomputed independently: All 11,320 rows re-found by scanning every candle and line (no merge_asof); 0 differ.
- [warn] Every game x team x checkpoint x source present: 11,320 rows, expected 11,320; 0 duplicates; rows without a price: DraftKings 0 of 2830, FanDuel 0 of 2830, Kalshi 10 of 2830, Pinnacle 0 of 2830
- [pass] Kalshi prices for the two teams add up to about $1: 1,410 game checkpoints; 0 where home mid + away mid is outside 0.85-1.15 (median sum 1.000).
- [pass] Kalshi and sportsbooks agree on which team is which: 282 games compared at kickoff; 0 fit better with the teams swapped.
- [pass] Sportsbook prices are the team's own line: 8,490 sportsbook prices; implied probability recomputed exactly (worst 0.0e+00); each was looked up by the team's own name.
- [warn] Price ages recorded: 58% of sportsbook prices are more than an hour old at their checkpoint. Median ages: Kalshi 3h: 0 min; Pinnacle 3h: 67.4 min; Kalshi 1h: 0 min; Pinnacle 1h: 130.4 min; Kalshi 15m: 0 min; Pinnacle 15m: 112.2 min. Costs only use prices within the maximum age (costs.MAX_AGE_MIN); older ones are marked not usable, so checkpoints with few fresh snapshots have few costs.
- [pass] Every game x team x checkpoint x venue x ruler (x n) once: 67920 rows, expected 67920 (283 games x 2 teams x 5 checkpoints x 4 rulers x (3 Kalshi sizes + 3 books)); 0 duplicates.
- [pass] Each ruler's two fair chances add up to 100%: Largest gap 2.22e-16 over 5655 game-checkpoint-rulers.
- [pass] Cost per $10 recomputed independently from the snapshots: 37842 usable rows recomputed with exact fractions, a closed-form Shin and the fee rounded up to the cent; 0 differ.
- [pass] Each sportsbook costs more than its own fair price: 0 of 4206 own-ruler sportsbook rows are negative.
- [pass] Kalshi fee per order is the exact fee rounded up by less than 1 cent: 0 Kalshi rows outside [exact fee, exact fee + 1 cent).
- [pass] n applies to Kalshi only: 0 sportsbook rows with an n, 0 Kalshi rows without one.
- [pass] No sportsbook price older than the maximum age is used: 0 usable rows break it. Usable: 37842 of 67920; max ages (min): 24h 360, 3h 45, 1h 15, 15m 10, close 60.
- [pass] n values are real trade sizes: From trade_sizes_2026.json, KXNFLGAME (2026 sizes used for 2025).

## Median price age (minutes) at each checkpoint

source      DraftKings  FanDuel  Kalshi  Pinnacle
checkpoint                                       
24h              127.3    127.3     0.2     127.3
3h                67.4    154.4     0.0      67.4
1h               130.4    130.4     0.0     130.4
15m              112.2    112.2     0.0     112.2
close              9.8      9.8     0.0       9.8

## Median cost per $10 (usable rows only)

Rows: the venue you bet at (Kalshi at each order size n). Columns: the ruler (whose fair price the cost is measured against). Own ruler = that venue's margin only.
n values from: trade_sizes_2026.json, KXNFLGAME (2026 sizes used for 2025). Usable rows: 37842 of 67920.

ruler                    A_Kalshi  B_Pinnacle  B_FanDuel  B_DraftKings
checkpoint venue_n                                                    
24h        Kalshi n=24      0.396       0.390      0.405         0.405
           Kalshi n=72      0.394       0.388      0.400         0.403
           Kalshi n=213     0.394       0.387      0.401         0.403
           Pinnacle         0.309       0.284      0.302         0.301
           FanDuel          0.388       0.391      0.386         0.389
           DraftKings       0.413       0.413      0.413         0.435
3h         Kalshi n=24      0.397       0.412      0.403         0.405
           Kalshi n=72      0.395       0.409      0.401         0.399
           Kalshi n=213     0.394       0.409      0.400         0.397
           Pinnacle         0.270       0.248      0.272         0.259
           FanDuel          0.384       0.393      0.391         0.388
           DraftKings       0.405       0.408      0.413         0.435
1h         Kalshi n=24      0.390       0.393      0.396         0.389
           Kalshi n=72      0.387       0.387      0.394         0.387
           Kalshi n=213     0.386       0.386      0.394         0.388
           Pinnacle         0.252       0.239      0.265         0.272
           FanDuel          0.390       0.396      0.374         0.384
           DraftKings       0.408       0.415      0.419         0.446
15m        Kalshi n=24      0.390       0.376      0.429         0.407
           Kalshi n=72      0.387       0.372      0.425         0.403
           Kalshi n=213     0.386       0.372      0.425         0.403
           Pinnacle         0.266       0.235      0.237         0.266
           FanDuel          0.381       0.383      0.377         0.374
           DraftKings       0.409       0.406      0.403         0.426
close      Kalshi n=24      0.390       0.379      0.408         0.390
           Kalshi n=72      0.387       0.376      0.407         0.386
           Kalshi n=213     0.386       0.375      0.406         0.385
           Pinnacle         0.268       0.244      0.261         0.261
           FanDuel          0.387       0.384      0.378         0.390
           DraftKings       0.409       0.413      0.414         0.442
