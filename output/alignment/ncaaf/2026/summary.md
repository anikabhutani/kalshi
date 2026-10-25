# College football (NCAAF) alignment, 2026 season

Generated 2026-10-25 22:34 UTC. Games: 455; matched: 355; Kalshi events left unmatched: 469.

## Match status

- matched: 355 (Matched to one Kalshi event with one market per team.)
- no_kalshi_event: 100 (No Kalshi event for these two teams within a day of kickoff.)

## Checks

- [pass] Game list: each played game once, final kickoff time: 455 games (0 postseason); 0 duplicates; 0 not using the provider's final start time; 3 duplicate listings in the odds feed dropped (the listing the feed kept updating is kept).
- [warn] Every game is matched or has a reason code: {'matched': 355, 'no_kalshi_event': 100}
- [pass] Each game has its own two Kalshi markets, one per team: 355 matched games; 0 Kalshi events used twice; 0 without two distinct markets.
- [warn] Learned team table: one school per Kalshi code, no school under two teams: 199 Kalshi codes mapped to 199 feed names; 0 codes with two schools []; 0 schools under two different Kalshi teams []. Kalshi spelling/code variants of one team: {'NC State Wolfpack': ['NC St.', 'NCST', 'North Carolina St.']}.
- [warn] Name matches are clear: 348 games with both names agreeing exactly, 7 partly (spelling differences, listed with match_score in crosswalk.csv); smallest lead over the runner-up 0.5.
- [warn] Ticker dates match kickoff dates (Eastern): 1 of 355 ticker dates differ by a day.
- [warn] Kalshi events not matched to a game: 469 Kalshi events unmatched ({'no_odds_game': 469}); listed in kalshi_events_unmatched.csv.
- [warn] Every matched market has candles: 184 matched markets without a candle file: ['KXNCAAFGAME-26SEP11VILLLOU-LOU', 'KXNCAAFGAME-26SEP11RICHNCST-NCST', 'KXNCAAFGAME-26SEP11NORFUVA-UVA', 'KXNCAAFGAME-26SEP11RUTGBC-BC']
- [pass] No price from after its checkpoint: 11,742 prices; 0 timestamped after their checkpoint; 0 negative ages; checkpoints all 0-24 h before their kickoff.
- [pass] Snapshot prices recomputed independently: All 14,200 rows re-found by scanning every candle and line (no merge_asof); 0 differ.
- [warn] Every game x team x checkpoint x source present: 14,200 rows, expected 14,200; 0 duplicates; rows without a price: DraftKings 450 of 3550, FanDuel 344 of 3550, Kalshi 920 of 3550, Pinnacle 744 of 3550
- [pass] Kalshi prices for the two teams add up to about $1: 1,315 game checkpoints; 0 where home mid + away mid is outside 0.85-1.15 (median sum 1.000).
- [pass] Kalshi and sportsbooks agree on which team is which: 245 games compared at kickoff; 0 fit better with the teams swapped.
- [pass] Sportsbook prices are the team's own line: 9,112 sportsbook prices; implied probability recomputed exactly (worst 0.0e+00); each was looked up by the team's own name.
- [pass] Every game x team x checkpoint x venue x ruler (x n) once: 85200 rows, expected 85200 (355 games x 2 teams x 5 checkpoints x 4 rulers x (3 Kalshi sizes + 3 books)); 0 duplicates.
- [pass] Each ruler's two fair chances add up to 100%: Largest gap 2.22e-16 over 5750 game-checkpoint-rulers.
- [pass] Cost per $10 recomputed independently from the snapshots: 40730 usable rows recomputed with exact fractions, a closed-form Shin and the fee rounded up to the cent; 0 differ.
- [pass] Each sportsbook costs more than its own fair price: 0 of 5622 own-ruler sportsbook rows are negative.
- [pass] Kalshi fee per order is the exact fee rounded up by less than 1 cent: 0 Kalshi rows outside [exact fee, exact fee + 1 cent).
- [pass] n applies to Kalshi only: 0 sportsbook rows with an n, 0 Kalshi rows without one.
- [pass] No sportsbook price older than the maximum age is used: 0 usable rows break it. Usable: 40730 of 85200; max ages (min): 24h 360, 3h 45, 1h 15, 15m 10, close 60.
- [pass] n values are real trade sizes: From NFL trade_sizes_2026.json, KXNFLGAME (no college trade sizes pulled).

## Median price age (minutes) at each checkpoint

source      DraftKings  FanDuel  Kalshi  Pinnacle
checkpoint                                       
24h               69.4     69.4     1.0      68.2
3h                27.4     27.5     0.0      27.4
1h                39.4     39.4     0.0      39.4
15m               26.2     26.3     0.0      24.4
close              9.9      9.9     0.0       9.4

## Median cost per $10 (usable rows only)

Rows: the venue you bet at (Kalshi at each order size n). Columns: the ruler (whose fair price the cost is measured against). Own ruler = that venue's margin only.
n values from: NFL trade_sizes_2026.json, KXNFLGAME (no college trade sizes pulled). Usable rows: 40730 of 85200.

ruler                    A_Kalshi  B_Pinnacle  B_FanDuel  B_DraftKings
checkpoint venue_n                                                    
24h        Kalshi n=24      0.388       0.346      0.336         0.348
           Kalshi n=72      0.387       0.344      0.332         0.344
           Kalshi n=213     0.385       0.345      0.329         0.343
           Pinnacle         0.368       0.342      0.370         0.362
           FanDuel          0.430       0.426      0.433         0.421
           DraftKings       0.413       0.403      0.406         0.444
3h         Kalshi n=24      0.382       0.349      0.359         0.338
           Kalshi n=72      0.378       0.342      0.359         0.338
           Kalshi n=213     0.378       0.342      0.359         0.335
           Pinnacle         0.317       0.298      0.323         0.317
           FanDuel          0.426       0.431      0.433         0.390
           DraftKings       0.423       0.414      0.412         0.435
1h         Kalshi n=24      0.390       0.354      0.338         0.365
           Kalshi n=72      0.387       0.350      0.337         0.363
           Kalshi n=213     0.386       0.348      0.337         0.362
           Pinnacle         0.311       0.325      0.330         0.325
           FanDuel          0.437       0.432      0.455         0.398
           DraftKings       0.410       0.408      0.405         0.440
15m        Kalshi n=24      0.383       0.333      0.342         0.355
           Kalshi n=72      0.380       0.332      0.339         0.353
           Kalshi n=213     0.378       0.329      0.339         0.353
           Pinnacle         0.356       0.289      0.335         0.316
           FanDuel          0.432       0.416      0.429         0.435
           DraftKings       0.419       0.415      0.409         0.440
close      Kalshi n=24      0.390       0.366      0.370         0.350
           Kalshi n=72      0.387       0.357      0.367         0.347
           Kalshi n=213     0.386       0.357      0.367         0.347
           Pinnacle         0.326       0.295      0.324         0.316
           FanDuel          0.427       0.423      0.433         0.417
           DraftKings       0.413       0.413      0.412         0.444
