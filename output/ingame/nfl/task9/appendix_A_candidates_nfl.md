# Appendix A candidates: in-game walkthrough with the sportsbook side

Bears @ Panthers (Sep 13, 2026, 2026_01_CHI_CAR) has no swing in the Task 7 files (its normal movement was high, sigma 6.3, so the threshold was about 30 points and no move cleared it). Below are pulled swings that can stand in.

**Recommended: 2026_09_DEN_CAR-S02** (Denver at Carolina, Nov 8, 2026): a Panthers home game at the same stadium as the case study, a touchdown at the swing, and both books repriced after it (every book price within 0.3-6.5 points of Kalshi). Alternate: 2026_08_CAR_GB-S01 (Panthers at Green Bay, Oct 29). **Not recommended: 2026_02_MIN_CHI-S01** (the Bears' next game, Sep 20): closest in time, but FanDuel had not repriced at the after time (Bears +114, 47% implied, vs Kalshi 30.5%), even though FanDuel's update timestamp is after the swing; useful only as an example of a stale line.

Note: the brief's check values (in-game Kalshi cost $0.43 before and $0.16 after) match no pulled swing (closest: 2025_18_DAL_NYG-S04, NYG $0.446 -> $0.167). Confirm with Julia which swing her Appendix A text uses before replacing it. Costs per $10 are in dollars; Kalshi at 24 contracts, fee rounded up to the cent per order; ruler A fair = Kalshi midpoint, ruler B fair = the book's Shin price.

## 2026_09_DEN_CAR-S02: DEN at CAR, 2026-11-08

Play near t: touchdown; home win price 42.5 -> 27.5 (15.0 points); threshold 14.0 points (sigma 2.96); settled 5 min after t.

### Kalshi, minute by minute (home team market)

| minute_utc           |   bid |   ask |   mid |   spread |   volume_both | steady   | flagged   | marker    |
|:---------------------|------:|------:|------:|---------:|--------------:|:---------|:----------|:----------|
| 2026-11-08T20:16:00Z |    48 |    49 |  48.5 |        1 |      26459.3  | False    | False     |           |
| 2026-11-08T20:17:00Z |    44 |    45 |  44.5 |        1 |      15528.7  | False    | False     |           |
| 2026-11-08T20:18:00Z |    44 |    45 |  44.5 |        1 |       7719.67 | False    | False     |           |
| 2026-11-08T20:19:00Z |    44 |    45 |  44.5 |        1 |      11580    | False    | False     |           |
| 2026-11-08T20:20:00Z |    44 |    45 |  44.5 |        1 |      12682.2  | False    | False     |           |
| 2026-11-08T20:21:00Z |    42 |    43 |  42.5 |        1 |      86156.7  | True     | False     | BEFORE    |
| 2026-11-08T20:22:00Z |    39 |    40 |  39.5 |        1 |      17854.3  | False    | False     |           |
| 2026-11-08T20:23:00Z |    40 |    41 |  40.5 |        1 |      69367.4  | False    | False     |           |
| 2026-11-08T20:24:00Z |    35 |    36 |  35.5 |        1 |      33061.2  | False    | False     |           |
| 2026-11-08T20:25:00Z |    38 |    39 |  38.5 |        1 |      51531.9  | False    | False     |           |
| 2026-11-08T20:26:00Z |    31 |    32 |  31.5 |        1 |     105263    | False    | False     |           |
| 2026-11-08T20:27:00Z |    23 |    24 |  23.5 |        1 |     248718    | False    | True      | SWING (t) |
| 2026-11-08T20:28:00Z |    27 |    28 |  27.5 |        1 |      67523.4  | False    | False     |           |
| 2026-11-08T20:29:00Z |    28 |    29 |  28.5 |        1 |      74230.3  | False    | False     |           |
| 2026-11-08T20:30:00Z |    28 |    29 |  28.5 |        1 |      23670.5  | False    | False     |           |
| 2026-11-08T20:31:00Z |    29 |    30 |  29.5 |        1 |      36027.5  | False    | False     |           |
| 2026-11-08T20:32:00Z |    27 |    28 |  27.5 |        1 |      34603.4  | True     | False     | AFTER     |
| 2026-11-08T20:33:00Z |    25 |    26 |  25.5 |        1 |      90618    | False    | False     |           |
| 2026-11-08T20:34:00Z |    17 |    19 |  18   |        2 |      86882.9  | False    | False     |           |
| 2026-11-08T20:35:00Z |    16 |    17 |  16.5 |        1 |      75796.3  | False    | False     |           |

### Both venues at the before and after times

| which   | request_time_utc     | book_snapshot_time   |   price_age_min | team   |   kalshi_bid |   kalshi_ask |   kalshi_mid |   kalshi_fee |   kalshi_cost_per10 | book       |   odds |   implied_p |   shin_fair_p |   cost_ruler_A |   cost_ruler_B |   kalshi_cost_ruler_B |   extra_cost_A | usable   |
|:--------|:---------------------|:---------------------|----------------:|:-------|-------------:|-------------:|-------------:|-------------:|--------------------:|:-----------|-------:|------------:|--------------:|---------------:|---------------:|----------------------:|---------------:|:---------|
| before  | 2026-11-08T20:21:00Z | 2026-11-08T20:20:36Z |             0.4 | CAR    |           42 |           43 |         42.5 |       1.75   |              0.5028 | DraftKings |    104 |      0.4902 |        0.4561 |         1.33   |         0.6962 |               -0.1915 |         0.8272 | True     |
| before  | 2026-11-08T20:21:00Z | 2026-11-08T20:20:36Z |             0.4 | CAR    |           42 |           43 |         42.5 |       1.75   |              0.5028 | FanDuel    |    114 |      0.4673 |        0.4369 |         0.905  |         0.6504 |                0.2369 |         0.4022 | True     |
| before  | 2026-11-08T20:21:00Z | 2026-11-08T20:20:36Z |             0.4 | DEN    |           57 |           58 |         57.5 |       1.7083 |              0.3699 | DraftKings |   -137 |      0.5781 |        0.5439 |         0.0529 |         0.5904 |                0.8902 |        -0.317  | True     |
| before  | 2026-11-08T20:21:00Z | 2026-11-08T20:20:36Z |             0.4 | DEN    |           57 |           58 |         57.5 |       1.7083 |              0.3699 | FanDuel    |   -146 |      0.5935 |        0.5631 |         0.3116 |         0.5121 |                0.5691 |        -0.0583 | True     |
| after   | 2026-11-08T20:32:00Z | 2026-11-08T20:30:36Z |             1.4 | CAR    |           27 |           28 |         27.5 |       1.4167 |              0.6516 | DraftKings |    226 |      0.3067 |        0.2739 |         1.035  |         1.0723 |                0.6905 |         0.3834 | True     |
| after   | 2026-11-08T20:32:00Z | 2026-11-08T20:30:36Z |             1.4 | CAR    |           27 |           28 |         27.5 |       1.4167 |              0.6516 | FanDuel    |    220 |      0.3125 |        0.2828 |         1.2    |         0.9494 |                0.3853 |         0.5484 | True     |
| after   | 2026-11-08T20:32:00Z | 2026-11-08T20:30:36Z |             1.4 | DEN    |           72 |           73 |         72.5 |       1.4167 |              0.2576 | DraftKings |   -315 |      0.759  |        0.7261 |         0.4484 |         0.4333 |                0.2422 |         0.1908 | True     |
| after   | 2026-11-08T20:32:00Z | 2026-11-08T20:30:36Z |             1.4 | DEN    |           72 |           73 |         72.5 |       1.4167 |              0.2576 | FanDuel    |   -295 |      0.7468 |        0.7172 |         0.2924 |         0.3972 |                0.3628 |         0.0348 | True     |

## 2026_08_CAR_GB-S01: CAR at GB, 2026-10-30

Play near t: touchdown; home win price 51.5 -> 65.5 (14.0 points); threshold 14.0 points (sigma 2.96); settled 5 min after t.

### Kalshi, minute by minute (home team market)

| minute_utc           |   bid |   ask |   mid |   spread |   volume_both | steady   | flagged   | marker    |
|:---------------------|------:|------:|------:|---------:|--------------:|:---------|:----------|:----------|
| 2026-10-30T00:51:00Z |    53 |    54 |  53.5 |        1 |       87916.3 | False    | False     |           |
| 2026-10-30T00:52:00Z |    53 |    54 |  53.5 |        1 |       44632.8 | False    | False     |           |
| 2026-10-30T00:53:00Z |    53 |    54 |  53.5 |        1 |       38093.6 | False    | False     |           |
| 2026-10-30T00:54:00Z |    51 |    52 |  51.5 |        1 |       90329.1 | True     | False     |           |
| 2026-10-30T00:55:00Z |    51 |    52 |  51.5 |        1 |      147094   | True     | False     |           |
| 2026-10-30T00:56:00Z |    51 |    52 |  51.5 |        1 |      143606   | True     | False     | BEFORE    |
| 2026-10-30T00:57:00Z |    54 |    55 |  54.5 |        1 |       95157.4 | False    | False     |           |
| 2026-10-30T00:58:00Z |    54 |    55 |  54.5 |        1 |       61364.2 | False    | False     |           |
| 2026-10-30T00:59:00Z |    43 |    44 |  43.5 |        1 |      234502   | False    | False     |           |
| 2026-10-30T01:00:00Z |    44 |    45 |  44.5 |        1 |      182395   | False    | False     |           |
| 2026-10-30T01:01:00Z |    45 |    46 |  45.5 |        1 |      163828   | False    | False     |           |
| 2026-10-30T01:02:00Z |    46 |    47 |  46.5 |        1 |       96388.2 | False    | False     |           |
| 2026-10-30T01:03:00Z |    50 |    51 |  50.5 |        1 |      110089   | False    | False     |           |
| 2026-10-30T01:04:00Z |    50 |    51 |  50.5 |        1 |      139742   | False    | False     |           |
| 2026-10-30T01:05:00Z |    50 |    51 |  50.5 |        1 |       77186.4 | False    | False     |           |
| 2026-10-30T01:06:00Z |    50 |    51 |  50.5 |        1 |       84765.8 | False    | False     |           |
| 2026-10-30T01:07:00Z |    45 |    47 |  46   |        2 |      370677   | False    | False     |           |
| 2026-10-30T01:08:00Z |    51 |    52 |  51.5 |        1 |       66254   | False    | False     |           |
| 2026-10-30T01:09:00Z |    58 |    59 |  58.5 |        1 |      124826   | False    | False     |           |
| 2026-10-30T01:10:00Z |    58 |    59 |  58.5 |        1 |      143741   | False    | False     |           |
| 2026-10-30T01:11:00Z |    58 |    59 |  58.5 |        1 |       38128.5 | False    | False     |           |
| 2026-10-30T01:12:00Z |    62 |    63 |  62.5 |        1 |      186081   | False    | True      | SWING (t) |
| 2026-10-30T01:13:00Z |    63 |    64 |  63.5 |        1 |      213337   | False    | False     |           |
| 2026-10-30T01:14:00Z |    63 |    64 |  63.5 |        1 |       40147   | False    | False     |           |
| 2026-10-30T01:15:00Z |    64 |    65 |  64.5 |        1 |      520307   | False    | False     |           |
| 2026-10-30T01:16:00Z |    65 |    66 |  65.5 |        1 |      230289   | False    | False     |           |
| 2026-10-30T01:17:00Z |    65 |    66 |  65.5 |        1 |      136069   | True     | False     | AFTER     |
| 2026-10-30T01:18:00Z |    65 |    66 |  65.5 |        1 |       70747   | True     | False     |           |
| 2026-10-30T01:19:00Z |    65 |    66 |  65.5 |        1 |       52569.4 | True     | False     |           |
| 2026-10-30T01:20:00Z |    64 |    65 |  64.5 |        1 |      131991   | True     | False     |           |

### Both venues at the before and after times

| which   | request_time_utc     | book_snapshot_time   |   price_age_min | team   |   kalshi_bid |   kalshi_ask |   kalshi_mid |   kalshi_fee |   kalshi_cost_per10 | book       |   odds |   implied_p |   shin_fair_p |   cost_ruler_A |   cost_ruler_B |   kalshi_cost_ruler_B |   extra_cost_A | usable   |
|:--------|:---------------------|:---------------------|----------------:|:-------|-------------:|-------------:|-------------:|-------------:|--------------------:|:-----------|-------:|------------:|--------------:|---------------:|---------------:|----------------------:|---------------:|:---------|
| before  | 2026-10-30T00:56:00Z | 2026-10-30T00:55:36Z |             0.4 | CAR    |           48 |           49 |         48.5 |       1.75   |              0.4433 | DraftKings |   -114 |      0.5327 |        0.4989 |         0.8956 |         0.6344 |                0.1692 |         0.4523 | True     |
| before  | 2026-10-30T00:56:00Z | 2026-10-30T00:55:36Z |             0.4 | CAR    |           48 |           49 |         48.5 |       1.75   |              0.4433 | FanDuel    |   -111 |      0.5261 |        0.4956 |         0.7806 |         0.5793 |                0.2347 |         0.3373 | True     |
| before  | 2026-10-30T00:56:00Z | 2026-10-30T00:55:36Z |             0.4 | GB     |           51 |           52 |         51.5 |       1.75   |              0.4186 | DraftKings |   -115 |      0.5349 |        0.5011 |         0.3717 |         0.6319 |                0.6775 |        -0.0469 | True     |
| before  | 2026-10-30T00:56:00Z | 2026-10-30T00:55:36Z |             0.4 | GB     |           51 |           52 |         51.5 |       1.75   |              0.4186 | FanDuel    |   -115 |      0.5349 |        0.5044 |         0.3717 |         0.5698 |                0.6157 |        -0.0469 | True     |
| after   | 2026-10-30T01:17:00Z | 2026-10-30T01:15:36Z |             1.4 | CAR    |           34 |           35 |         34.5 |       1.625  |              0.5802 | DraftKings |    166 |      0.3759 |        0.3428 |         0.823  |         0.8824 |                0.6411 |         0.2428 | True     |
| after   | 2026-10-30T01:17:00Z | 2026-10-30T01:15:36Z |             1.4 | CAR    |           34 |           35 |         34.5 |       1.625  |              0.5802 | FanDuel    |    148 |      0.4032 |        0.3728 |         1.444  |         0.7534 |               -0.1801 |         0.8638 | True     |
| after   | 2026-10-30T01:17:00Z | 2026-10-30T01:15:36Z |             1.4 | GB     |           65 |           66 |         65.5 |       1.5833 |              0.3083 | DraftKings |   -223 |      0.6904 |        0.6572 |         0.5128 |         0.4805 |                0.2752 |         0.2045 | True     |
| after   | 2026-10-30T01:17:00Z | 2026-10-30T01:15:36Z |             1.4 | GB     |           65 |           66 |         65.5 |       1.5833 |              0.3083 | FanDuel    |   -192 |      0.6575 |        0.6272 |         0.0385 |         0.462  |                0.7203 |        -0.2698 | True     |

## 2026_02_MIN_CHI-S01: MIN at CHI, 2026-09-20

Play near t: no play within 3 min; home win price 52.5 -> 30.5 (22.0 points); threshold 28.0 points (sigma 5.93); settled 4 min after t.

### Kalshi, minute by minute (home team market)

| minute_utc           |   bid |   ask |   mid |   spread |   volume_both | steady   | flagged   | marker    |
|:---------------------|------:|------:|------:|---------:|--------------:|:---------|:----------|:----------|
| 2026-09-20T19:21:00Z |    50 |    51 |  50.5 |        1 |       69695   | False    | False     |           |
| 2026-09-20T19:22:00Z |    51 |    52 |  51.5 |        1 |       50705.5 | False    | False     |           |
| 2026-09-20T19:23:00Z |    53 |    54 |  53.5 |        1 |       11920.1 | False    | False     |           |
| 2026-09-20T19:24:00Z |    53 |    54 |  53.5 |        1 |       13083.9 | False    | False     |           |
| 2026-09-20T19:25:00Z |    53 |    54 |  53.5 |        1 |       16402.6 | False    | False     |           |
| 2026-09-20T19:26:00Z |    52 |    53 |  52.5 |        1 |       52504.5 | True     | False     | BEFORE    |
| 2026-09-20T19:27:00Z |    50 |    51 |  50.5 |        1 |       42763.5 | False    | False     |           |
| 2026-09-20T19:28:00Z |    65 |    66 |  65.5 |        1 |      288612   | False    | False     |           |
| 2026-09-20T19:29:00Z |    62 |    63 |  62.5 |        1 |      281986   | False    | False     |           |
| 2026-09-20T19:30:00Z |    62 |    63 |  62.5 |        1 |       28849.5 | False    | False     |           |
| 2026-09-20T19:31:00Z |    70 |    71 |  70.5 |        1 |      105229   | False    | False     |           |
| 2026-09-20T19:32:00Z |    67 |    68 |  67.5 |        1 |       64003.6 | False    | False     |           |
| 2026-09-20T19:33:00Z |    60 |    61 |  60.5 |        1 |       68703   | False    | False     |           |
| 2026-09-20T19:34:00Z |    50 |    51 |  50.5 |        1 |       61796.9 | False    | False     |           |
| 2026-09-20T19:35:00Z |    27 |    31 |  29   |        4 |      144336   | False    | True      | SWING (t) |
| 2026-09-20T19:36:00Z |    28 |    29 |  28.5 |        1 |      265282   | False    | True      |           |
| 2026-09-20T19:37:00Z |    28 |    29 |  28.5 |        1 |      117351   | False    | True      |           |
| 2026-09-20T19:38:00Z |    28 |    29 |  28.5 |        1 |      109755   | False    | True      |           |
| 2026-09-20T19:39:00Z |    30 |    31 |  30.5 |        1 |      117825   | True     | False     | AFTER     |
| 2026-09-20T19:40:00Z |    21 |    22 |  21.5 |        1 |      245701   | False    | False     |           |
| 2026-09-20T19:41:00Z |    17 |    18 |  17.5 |        1 |      168067   | False    | False     |           |
| 2026-09-20T19:42:00Z |    15 |    16 |  15.5 |        1 |      164899   | False    | False     |           |

### Both venues at the before and after times

| which   | request_time_utc     | book_snapshot_time   |   price_age_min | team   |   kalshi_bid |   kalshi_ask |   kalshi_mid |   kalshi_fee |   kalshi_cost_per10 | book       |   odds |   implied_p |   shin_fair_p |   cost_ruler_A |   cost_ruler_B |   kalshi_cost_ruler_B |   extra_cost_A | usable   |
|:--------|:---------------------|:---------------------|----------------:|:-------|-------------:|-------------:|-------------:|-------------:|--------------------:|:-----------|-------:|------------:|--------------:|---------------:|---------------:|----------------------:|---------------:|:---------|
| before  | 2026-09-20T19:26:00Z | 2026-09-20T19:25:36Z |             0.4 | CHI    |           52 |           53 |         52.5 |         1.75 |              0.411  | DraftKings |   -120 |      0.5455 |        0.512  |         0.375  |         0.614  |                0.6491 |        -0.036  | True     |
| before  | 2026-09-20T19:26:00Z | 2026-09-20T19:25:36Z |             0.4 | CHI    |           52 |           53 |         52.5 |         1.75 |              0.411  | FanDuel    |   -128 |      0.5614 |        0.5307 |         0.6484 |         0.5469 |                0.3068 |         0.2374 | True     |
| before  | 2026-09-20T19:26:00Z | 2026-09-20T19:25:36Z |             0.4 | MIN    |           47 |           48 |         47.5 |         1.75 |              0.4523 | DraftKings |   -109 |      0.5215 |        0.488  |         0.8922 |         0.6422 |                0.1902 |         0.4399 | True     |
| before  | 2026-09-20T19:26:00Z | 2026-09-20T19:25:36Z |             0.4 | MIN    |           47 |           48 |         47.5 |         1.75 |              0.4523 | FanDuel    |    100 |      0.5    |        0.4693 |         0.5    |         0.614  |                0.5669 |         0.0477 | True     |
| after   | 2026-09-20T19:39:00Z | 2026-09-20T19:35:36Z |             3.4 | CHI    |           30 |           31 |         30.5 |         1.5  |              0.6154 | DraftKings |    215 |      0.3175 |        0.2866 |         0.3925 |         0.9719 |                1.1813 |        -0.2229 | True     |
| after   | 2026-09-20T19:39:00Z | 2026-09-20T19:35:36Z |             3.4 | CHI    |           30 |           31 |         30.5 |         1.5  |              0.6154 | FanDuel    |    114 |      0.4673 |        0.4369 |         3.473  |         0.6504 |               -3.443  |         2.8576 | True     |
| after   | 2026-09-20T19:39:00Z | 2026-09-20T19:35:36Z |             3.4 | MIN    |           69 |           70 |         69.5 |         1.5  |              0.2797 | DraftKings |   -291 |      0.7442 |        0.7134 |         0.6617 |         0.4146 |                0.0225 |         0.382  | True     |
| after   | 2026-09-20T19:39:00Z | 2026-09-20T19:35:36Z |             3.4 | MIN    |           69 |           70 |         69.5 |         1.5  |              0.2797 | FanDuel    |   -146 |      0.5935 |        0.5631 |        -1.7103 |         0.5121 |                2.1244 |        -1.99   | True     |
