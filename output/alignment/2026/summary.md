# Alignment, 2026 season

Generated 2026-10-24 09:07 UTC. Games: 80; matched: 80; Kalshi events left unmatched: 41.

## Match status

- matched: 80 (Matched to one Kalshi event with one market per team.)

## Checks

- [pass] 32-team table is valid: 32 teams, no code used for two teams.
- [warn] Game list: each game once, final kickoff time: 80 games; 0 duplicates; 0 from another season; 0 not using the provider's final start time. Kickoff moved by more than 60 min after first listing: Chicago Bears at Green Bay Packers (-201 min).
- [pass] Every game is matched or has a reason code: {'matched': 80}
- [pass] Each game has its own two Kalshi markets, one per team: 80 matched games; 0 Kalshi events used twice; 0 without two distinct markets; 0 markets whose ticker team is not the team they are filed under.
- [pass] Ticker dates match kickoff dates (Eastern): All 80 ticker dates equal the Eastern kickoff date.
- [pass] Every Kalshi team code is in the table: All codes in 121 Kalshi events are known.
- [pass] Kalshi events not matched to a game: 41 Kalshi events unmatched; 0 of them dated inside the season's game dates (listed in kalshi_events_unmatched.csv).
- [pass] No price from after its checkpoint: 3,200 prices; 0 timestamped after their checkpoint; 0 negative ages; checkpoints all 0-24 h before their kickoff.
- [pass] Snapshot prices recomputed independently: All 3,200 rows re-found by scanning every candle and line (no merge_asof); 0 differ.
- [pass] Every game x team x checkpoint x source present: 3,200 rows, expected 3,200; 0 duplicates; rows without a price: DraftKings 0 of 800, FanDuel 0 of 800, Kalshi 0 of 800, Pinnacle 0 of 800
- [pass] Kalshi prices for the two teams add up to about $1: 400 game checkpoints; 0 where home mid + away mid is outside 0.85-1.15 (median sum 1.000).
- [pass] Kalshi and sportsbooks agree on which team is which: 80 games compared at kickoff; 0 fit better with the teams swapped.
- [pass] Sportsbook prices are the team's own line: 2,400 sportsbook prices; implied probability recomputed exactly (worst 0.0e+00); each was looked up by the team's own name.
- [warn] Price ages recorded: 46% of sportsbook prices are more than an hour old at their checkpoint. Median ages: Kalshi 3h: 0.4 min; Pinnacle 3h: 66.9 min; Kalshi 1h: 0.4 min; Pinnacle 1h: 9.7 min; Kalshi 15m: 0.4 min; Pinnacle 15m: 52.5 min. Costs only use prices within the maximum age (costs.MAX_AGE_MIN); older ones are marked not usable, so checkpoints with few fresh snapshots have few costs.
- [pass] Every game x team x checkpoint x venue x ruler (x n) once: 19200 rows, expected 19200 (80 games x 2 teams x 5 checkpoints x 4 rulers x (3 Kalshi sizes + 3 books)); 0 duplicates.
- [pass] Each ruler's two fair chances add up to 100%: Largest gap 2.22e-16 over 1600 game-checkpoint-rulers.
- [pass] Cost per $10 recomputed independently from the snapshots: 11808 usable rows recomputed with exact fractions, a closed-form Shin and the fee rounded up to the cent; 0 differ.
- [pass] Each sportsbook costs more than its own fair price: 0 of 1344 own-ruler sportsbook rows are negative.
- [pass] Kalshi fee per order is the exact fee rounded up by less than 1 cent: 0 Kalshi rows outside [exact fee, exact fee + 1 cent).
- [pass] n applies to Kalshi only: 0 sportsbook rows with an n, 0 Kalshi rows without one.
- [pass] No sportsbook price older than the maximum age is used: 0 usable rows break it. Usable: 11808 of 19200; max ages (min): 24h 360, 3h 45, 1h 15, 15m 10, close 60.
- [pass] n values are real trade sizes: From trade_sizes_2026.json, KXNFLGAME.

## Median price age (minutes) at each checkpoint

source      DraftKings  FanDuel  Kalshi  Pinnacle
checkpoint                                       
24h               68.3     68.3     0.5      68.3
3h                66.9     66.9     0.4      66.9
1h                 9.7      9.7     0.4       9.7
15m               52.5     52.5     0.4      52.5
close             12.0     12.0     0.4      12.0

## Median cost per $10 (usable rows only)

Rows: the venue you bet at (Kalshi at each order size n). Columns: the ruler (whose fair price the cost is measured against). Own ruler = that venue's margin only.
n values from: trade_sizes_2026.json, KXNFLGAME. Usable rows: 11808 of 19200.

ruler                    A_Kalshi  B_Pinnacle  B_FanDuel  B_DraftKings
checkpoint venue_n                                                    
24h        Kalshi n=24      0.396       0.410      0.372         0.366
           Kalshi n=72      0.393       0.410      0.370         0.365
           Kalshi n=213     0.393       0.410      0.369         0.364
           Pinnacle         0.305       0.295      0.313         0.313
           FanDuel          0.392       0.382      0.378         0.390
           DraftKings       0.409       0.414      0.414         0.431
3h         Kalshi n=24      0.410       0.404      0.410         0.367
           Kalshi n=72      0.410       0.403      0.409         0.366
           Kalshi n=213     0.410       0.401      0.409         0.365
           Pinnacle         0.288       0.263      0.273         0.268
           FanDuel          0.384       0.375      0.367         0.380
           DraftKings       0.416       0.400      0.410         0.426
1h         Kalshi n=24      0.411       0.401      0.426         0.365
           Kalshi n=72      0.411       0.401      0.422         0.363
           Kalshi n=213     0.410       0.401      0.422         0.363
           Pinnacle         0.259       0.257      0.275         0.270
           FanDuel          0.380       0.385      0.390         0.388
           DraftKings       0.409       0.408      0.406         0.440
15m        Kalshi n=24      0.396         NaN        NaN           NaN
           Kalshi n=72      0.393         NaN        NaN           NaN
           Kalshi n=213     0.393         NaN        NaN           NaN
close      Kalshi n=24      0.387       0.375      0.411         0.377
           Kalshi n=72      0.385       0.373      0.411         0.374
           Kalshi n=213     0.384       0.372      0.411         0.374
           Pinnacle         0.266       0.244      0.253         0.282
           FanDuel          0.386       0.386      0.386         0.380
           DraftKings       0.419       0.409      0.410         0.444
