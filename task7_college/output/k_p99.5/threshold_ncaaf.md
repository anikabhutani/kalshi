# Swing threshold (college, seasons 2025, 2026)

Games used: 1617 (2025 933, 2026 684). With good play timestamps: 942 (2025 427, 2026 515); k comes from their 46,888 quiet minutes.

Games not used: {"no FBS team": 544, "no CFBD game (name/date)": 204, "zero-volume Kalshi event": 104, "candles do not cover the game": 1}.

Timestamp check failures: {"wallclock on # of plays": 339, "# of plays step back in time": 147, "#-min gap between plays": 133, "first play # min from scheduled start": 40, "game length # h": 16}.

| Percentile | k | Swings | Kept | Catch rate (3 min) | Match rate (3 min) |
|---|---|---|---|---|---|
| p97.5 | 4.047 | 1840 | 922 | 22.1% | 70.5% |
| p99 | 5.589 | 1027 | 482 | 12.9% | 72.5% |
| p99.5 | 6.913 | 657 | 308 | 8.3% | 73.2% |

Main threshold: p99.5 (steady range 2 points).

- Catch rate: 8.3% of 2,931 touchdowns and turnovers at 20-80% home win probability (touchdowns 167/2042, turnovers 76/889). Win probability from CFBD for 1,915 plays, Kalshi midpoint for 1,016. On the CFBD win-probability sample alone: 7.3% of 1,915.
- Match rate: 73.2% of 529 swings in good-timestamp games have a touchdown, field goal, turnover or failed fourth down within 3 min of t (kept swings only: 77.2%).
- Within 5 minutes: catch 10.4%, match 86.2%.

sigma_game: min 1.0, median 3.707, max 11.49 points (good-timestamp games 3.707, others 3.707). Threshold in the median game 25.625 points.

1-point floor used (37): KXNCAAFGAME-25NOV01PSUOSU, KXNCAAFGAME-25OCT18TXAMARK, KXNCAAFGAME-25OCT11OSUILL, KXNCAAFGAME-25SEP20BSUAFA, KXNCAAFGAME-25SEP20BYUECU, KXNCAAFGAME-25OCT11CLEMBC, KXNCAAFGAME-25NOV29CINTCU, KXNCAAFGAME-25NOV15LTWSU, KXNCAAFGAME-25OCT18WVUUCF, KXNCAAFGAME-25SEP06WCUWAKE, KXNCAAFGAME-25SEP06M-OHRUTG, KXNCAAFGAME-25SEP06UNCCHAR, KXNCAAFGAME-25SEP27GASOJMU, KXNCAAFGAME-25OCT11CHARARMY, KXNCAAFGAME-25SEP06BRYMASS, KXNCAAFGAME-25AUG28DSUDEL, KXNCAAFGAME-25SEP13FAUFIU, KXNCAAFGAME-25SEP20MEGASO, KXNCAAFGAME-25SEP20UTMMOSU, KXNCAAFGAME-25AUG30MORGUSA, KXNCAAFGAME-26SEP19UNCCLEM, KXNCAAFGAME-26SEP05CLEMLSU, KXNCAAFGAME-26SEP03ALBYBUFF, KXNCAAFGAME-26OCT10KUUTAH, KXNCAAFGAME-26OCT20MOSUDEL, KXNCAAFGAME-26SEP12TENNGT, KXNCAAFGAME-26SEP12GASOCLEM, KXNCAAFGAME-26OCT10ARIZWVU, KXNCAAFGAME-26SEP05SDSTNW, KXNCAAFGAME-26OCT03BCSMU, KXNCAAFGAME-26OCT03SAMUAB, KXNCAAFGAME-26SEP05TULNDUKE, KXNCAAFGAME-26OCT24UNTNAVY, KXNCAAFGAME-26SEP19CHARAPP, KXNCAAFGAME-26OCT16ASUTTU, KXNCAAFGAME-26OCT30MIZZARK, KXNCAAFGAME-26OCT23UTSATULN.

League-median sigma (3.7065) used in 469 games (under 20 usable minutes, mostly one-sided games outside 10-90). Home market replaced by the flipped away market in 220 games. Both lists are in threshold_ncaaf.json and games_ncaaf.csv (sigma_note, source_market).

n_med: {"2025": 50, "2026": 24}. Plots: swings_KXNCAAFGAME-25OCT18SMUCLEM.png, swings_KXNCAAFGAME-26OCT03WVUISU.png, swings_KXNCAAFGAME-26SEP05SDSTNW.png.
