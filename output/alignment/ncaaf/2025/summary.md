# College football (NCAAF) alignment, 2025 season

Generated 2026-10-25 22:36 UTC. Games: 978; matched: 935; Kalshi events left unmatched: 1.

## Match status

- matched: 935 (Matched to one Kalshi event with one market per team.)
- no_kalshi_event: 43 (No Kalshi event for these two teams within a day of kickoff.)

## Checks

- [pass] Game list: each played game once, final kickoff time: 978 games (61 postseason); 0 duplicates; 0 not using the provider's final start time; 3 duplicate listings in the odds feed dropped (the listing the feed kept updating is kept).
- [warn] Every game is matched or has a reason code: {'matched': 935, 'no_kalshi_event': 43}
- [pass] Each game has its own two Kalshi markets, one per team: 935 matched games; 0 Kalshi events used twice; 0 without two distinct markets.
- [warn] Learned team table: one school per Kalshi code, no school under two teams: 233 Kalshi codes mapped to 232 feed names; 0 codes with two schools []; 0 schools under two different Kalshi teams []. Kalshi spelling/code variants of one team: {'Miami (OH) RedHawks': ['M-OH', 'MOH', 'Miami (OH)']}.
- [warn] Name matches are clear: 920 games with both names agreeing exactly, 15 partly (spelling differences, listed with match_score in crosswalk.csv); smallest lead over the runner-up 0.5.
- [warn] Ticker dates match kickoff dates (Eastern): 4 of 935 ticker dates differ by a day.
- [warn] Kalshi events not matched to a game: 1 Kalshi events unmatched ({'duplicate_listing': 1}); listed in kalshi_events_unmatched.csv.
- [warn] Every matched market has candles: 4 matched markets without a candle file: ['KXNCAAFGAME-25NOV22HARVYALE-YALE', 'KXNCAAFGAME-25DEC13SCSTPV-PV', 'KXNCAAFGAME-25NOV22HARVYALE-HARV', 'KXNCAAFGAME-25DEC13SCSTPV-SCST']
- [pass] No price from after its checkpoint: 34,288 prices; 0 timestamped after their checkpoint; 0 negative ages; checkpoints all 0-24 h before their kickoff.
- [pass] Snapshot prices recomputed independently: All 37,400 rows re-found by scanning every candle and line (no merge_asof); 0 differ.
- [warn] Every game x team x checkpoint x source present: 37,400 rows, expected 37,400; 0 duplicates; rows without a price: DraftKings 832 of 9350, FanDuel 908 of 9350, Kalshi 20 of 9350, Pinnacle 1352 of 9350
- [pass] Kalshi prices for the two teams add up to about $1: 4,665 game checkpoints; 0 where home mid + away mid is outside 0.85-1.15 (median sum 1.000).
- [pass] Kalshi and sportsbooks agree on which team is which: 866 games compared at kickoff; 0 fit better with the teams swapped.
- [pass] Sportsbook prices are the team's own line: 24,958 sportsbook prices; implied probability recomputed exactly (worst 0.0e+00); each was looked up by the team's own name.
- [pass] Every game x team x checkpoint x venue x ruler (x n) once: 224400 rows, expected 224400 (935 games x 2 teams x 5 checkpoints x 4 rulers x (3 Kalshi sizes + 3 books)); 0 duplicates.
- [pass] Each ruler's two fair chances add up to 100%: Largest gap 2.22e-16 over 16983 game-checkpoint-rulers.
- [pass] Cost per $10 recomputed independently from the snapshots: 129466 usable rows recomputed with exact fractions, a closed-form Shin and the fee rounded up to the cent; 0 differ.
- [pass] Each sportsbook costs more than its own fair price: 0 of 14782 own-ruler sportsbook rows are negative.
- [pass] Kalshi fee per order is the exact fee rounded up by less than 1 cent: 0 Kalshi rows outside [exact fee, exact fee + 1 cent).
- [pass] n applies to Kalshi only: 0 sportsbook rows with an n, 0 Kalshi rows without one.
- [pass] No sportsbook price older than the maximum age is used: 0 usable rows break it. Usable: 129466 of 224400; max ages (min): 24h 360, 3h 45, 1h 15, 15m 10, close 60.
- [pass] n values are real trade sizes: From NFL trade_sizes_2026.json, KXNFLGAME (2026 sizes used for 2025) (no college trade sizes pulled).

## Median price age (minutes) at each checkpoint

source      DraftKings  FanDuel  Kalshi  Pinnacle
checkpoint                                       
24h               99.4     99.4     0.8     100.9
3h                41.4     40.8     0.3      41.7
1h                40.6     40.4     0.2      43.7
15m               27.0     27.1     0.1      27.1
close             11.8     11.8     0.0      11.9

## Median cost per $10 (usable rows only)

Rows: the venue you bet at (Kalshi at each order size n). Columns: the ruler (whose fair price the cost is measured against). Own ruler = that venue's margin only.
n values from: NFL trade_sizes_2026.json, KXNFLGAME (2026 sizes used for 2025) (no college trade sizes pulled). Usable rows: 129466 of 224400.

ruler                    A_Kalshi  B_Pinnacle  B_FanDuel  B_DraftKings
checkpoint venue_n                                                    
24h        Kalshi n=24      0.394       0.364      0.390         0.360
           Kalshi n=72      0.391       0.360      0.385         0.359
           Kalshi n=213     0.390       0.360      0.383         0.359
           Pinnacle         0.364       0.329      0.366         0.364
           FanDuel          0.389       0.398      0.400         0.392
           DraftKings       0.410       0.414      0.414         0.440
3h         Kalshi n=24      0.383       0.371      0.372         0.367
           Kalshi n=72      0.381       0.368      0.372         0.367
           Kalshi n=213     0.380       0.368      0.370         0.366
           Pinnacle         0.325       0.301      0.329         0.326
           FanDuel          0.390       0.398      0.398         0.399
           DraftKings       0.403       0.408      0.416         0.440
1h         Kalshi n=24      0.383       0.340      0.361         0.339
           Kalshi n=72      0.379       0.340      0.359         0.338
           Kalshi n=213     0.379       0.338      0.358         0.337
           Pinnacle         0.328       0.308      0.331         0.326
           FanDuel          0.395       0.394      0.391         0.398
           DraftKings       0.401       0.408      0.416         0.442
15m        Kalshi n=24      0.383       0.344      0.342         0.346
           Kalshi n=72      0.379       0.343      0.340         0.344
           Kalshi n=213     0.379       0.343      0.340         0.344
           Pinnacle         0.318       0.295      0.311         0.315
           FanDuel          0.394       0.409      0.407         0.398
           DraftKings       0.413       0.413      0.415         0.440
close      Kalshi n=24      0.400       0.362      0.395         0.364
           Kalshi n=72      0.397       0.360      0.394         0.360
           Kalshi n=213     0.396       0.359      0.394         0.360
           Pinnacle         0.324       0.298      0.321         0.321
           FanDuel          0.394       0.395      0.400         0.401
           DraftKings       0.406       0.409      0.413         0.440
