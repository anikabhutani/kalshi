# Alignment, 2026 season

Generated 2026-10-24 00:06 UTC. Games: 80; matched: 65; Kalshi events left unmatched: 13.

## Match status

- matched: 65 (Matched to one Kalshi event with one market per team.)
- no_kalshi_event: 15 (No Kalshi event for these two teams within a day of kickoff.)

## Checks

- [pass] 32-team table is valid: 32 teams, no code used for two teams.
- [warn] Game list: each game once, final kickoff time: 80 games; 0 duplicates; 0 from another season; 0 not using the provider's final start time. Kickoff moved by more than 60 min after first listing: Chicago Bears at Green Bay Packers (-201 min).
- [warn] Every game is matched or has a reason code: {'matched': 65, 'no_kalshi_event': 15}
- [pass] Each game has its own two Kalshi markets, one per team: 65 matched games; 0 Kalshi events used twice; 0 without two distinct markets; 0 markets whose ticker team is not the team they are filed under.
- [pass] Ticker dates match kickoff dates (Eastern): All 65 ticker dates equal the Eastern kickoff date.
- [pass] Every Kalshi team code is in the table: All codes in 78 Kalshi events are known.
- [pass] Kalshi events not matched to a game: 13 Kalshi events unmatched; 0 of them dated inside the season's game dates (listed in kalshi_events_unmatched.csv).
- [pass] No price from after its checkpoint: 2,600 prices; 0 timestamped after their checkpoint; 0 negative ages; checkpoints all 0-24 h before their kickoff.
- [pass] Snapshot prices recomputed independently: All 2,600 rows re-found by scanning every candle and line (no merge_asof); 0 differ.
- [pass] Every game x team x checkpoint x source present: 2,600 rows, expected 2,600; 0 duplicates; rows without a price: DraftKings 0 of 650, FanDuel 0 of 650, Kalshi 0 of 650, Pinnacle 0 of 650
- [pass] Kalshi prices for the two teams add up to about $1: 325 game checkpoints; 0 where home mid + away mid is outside 0.85-1.15 (median sum 1.000).
- [pass] Kalshi and sportsbooks agree on which team is which: 65 games compared at kickoff; 0 fit better with the teams swapped.
- [pass] Sportsbook prices are the team's own line: 1,950 sportsbook prices; implied probability recomputed exactly (worst 0.0e+00); each was looked up by the team's own name.
- [warn] Price ages recorded: 45% of sportsbook prices are more than an hour old at their checkpoint. Median ages: Kalshi 3h: 0.5 min; Pinnacle 3h: 64.4 min; Kalshi 1h: 0.5 min; Pinnacle 1h: 8.2 min; Kalshi 15m: 0.5 min; Pinnacle 15m: 52.2 min. Costs only use prices within the maximum age (costs.MAX_AGE_MIN); older ones are marked not usable, so checkpoints with few fresh snapshots have few costs.
- [pass] Every game x team x checkpoint x venue x ruler (x n) once: 20800 rows, expected 20800 (65 games x 2 teams x 5 checkpoints x 4 rulers x (5 Kalshi sizes + 3 books)); 0 duplicates.
- [pass] Each ruler's two fair chances add up to 100%: Largest gap 2.22e-16 over 1300 game-checkpoint-rulers.
- [pass] Cost per $10 recomputed independently from the snapshots: 13186 usable rows recomputed with exact fractions, a closed-form Shin and the fee rounded up to the cent; 0 differ.
- [pass] Each sportsbook costs more than its own fair price: 0 of 1104 own-ruler sportsbook rows are negative.
- [pass] Kalshi fee per order is the exact fee rounded up by less than 1 cent: 0 Kalshi rows outside [exact fee, exact fee + 1 cent).
- [pass] n applies to Kalshi only: 0 sportsbook rows with an n, 0 Kalshi rows without one.
- [pass] No sportsbook price older than the maximum age is used: 0 usable rows break it. Usable: 13186 of 20800; max ages (min): 24h 360, 3h 45, 1h 15, 15m 10, close 60.
- [warn] n values are real trade sizes: Using the team's placeholder sizes 1, 5, 10, 25, 100: run make trade-sizes for this season, then re-run.

## Median price age (minutes) at each checkpoint

source      DraftKings  FanDuel  Kalshi  Pinnacle
checkpoint                                       
24h               67.4     67.4     0.5      67.4
3h                64.4     64.4     0.5      64.4
1h                 8.2      8.2     0.5       8.2
15m               52.2     52.2     0.5      52.2
close             12.0     12.0     0.5      12.0

## Median cost per $10 (usable rows only)

Rows: the venue you bet at (Kalshi at each order size n). Columns: the ruler (whose fair price the cost is measured against). Own ruler = that venue's margin only.
n values from: placeholder (run make trade-sizes). Usable rows: 13186 of 20800.

ruler                    A_Kalshi  B_Pinnacle  B_FanDuel  B_DraftKings
checkpoint venue_n                                                    
24h        Kalshi n=1       0.446       0.470      0.424         0.449
           Kalshi n=5       0.409       0.424      0.379         0.377
           Kalshi n=10      0.409       0.416      0.371         0.373
           Kalshi n=25      0.399       0.411      0.360         0.367
           Kalshi n=100     0.398       0.409      0.360         0.366
           Pinnacle         0.305       0.296      0.313         0.317
           FanDuel          0.392       0.382      0.373         0.390
           DraftKings       0.410       0.414      0.414         0.426
3h         Kalshi n=1       0.455       0.459      0.463         0.416
           Kalshi n=5       0.420       0.427      0.421         0.382
           Kalshi n=10      0.420       0.420      0.406         0.381
           Kalshi n=25      0.412       0.414      0.406         0.367
           Kalshi n=100     0.410       0.410      0.402         0.366
           Pinnacle         0.288       0.263      0.273         0.270
           FanDuel          0.380       0.375      0.367         0.380
           DraftKings       0.416       0.400      0.410         0.426
1h         Kalshi n=1       0.455       0.473      0.477         0.447
           Kalshi n=5       0.420       0.402      0.440         0.365
           Kalshi n=10      0.420       0.397      0.440         0.365
           Kalshi n=25      0.413       0.387      0.433         0.353
           Kalshi n=100     0.411       0.384      0.428         0.349
           Pinnacle         0.263       0.262      0.292         0.270
           FanDuel          0.380       0.385      0.385         0.389
           DraftKings       0.402       0.403      0.413         0.413
15m        Kalshi n=1       0.441         NaN        NaN           NaN
           Kalshi n=5       0.402         NaN        NaN           NaN
           Kalshi n=10      0.398         NaN        NaN           NaN
           Kalshi n=25      0.391         NaN        NaN           NaN
           Kalshi n=100     0.386         NaN        NaN           NaN
close      Kalshi n=1       0.436       0.471      0.472         0.457
           Kalshi n=5       0.398       0.388      0.418         0.407
           Kalshi n=10      0.398       0.375      0.403         0.389
           Kalshi n=25      0.391       0.373      0.403         0.383
           Kalshi n=100     0.386       0.371      0.402         0.383
           Pinnacle         0.272       0.246      0.253         0.284
           FanDuel          0.386       0.385      0.373         0.382
           DraftKings       0.425       0.409      0.410         0.440
