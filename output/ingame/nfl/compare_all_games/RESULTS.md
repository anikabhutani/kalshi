# In-game NFL results: Kalshi vs DraftKings and FanDuel (2025 season + 2026 through Nov 9)

**Data.** 421 games with in-game odds: every 5-minute Odds API snapshot from first to last play, moneyline, DraftKings and FanDuel, joined to Kalshi 1-minute quotes. 56,456 live book-team-snapshot rows; **22,624 (40%) usable**, from 416 games. Fair price = Kalshi midpoint; Kalshi cost at 24 contracts (ask + fee, rounded up to the cent); book cost from its odds. Book prices were a median 22 s old at the snapshot.

**Usable row ("calm"):** Kalshi's midpoint stayed within 2 points, its spread at 5¢ or less and two-sided, from the book's last update to the minute after the snapshot; fair price between 10% and 90%.

## Headline
| | FanDuel | DraftKings |
|---|---|---|
| Extra cost per $10 vs Kalshi, median (95% interval) | +19.3¢ (+17.9¢ to +20.2¢) | +20.4¢ (+19.8¢ to +21.0¢) |
| Mean | -3.9¢ (-12.2¢ to +1.7¢) | +9.8¢ (+6.7¢ to +12.5¢) |
| Robustness: fair = book's own de-vigged price (median) | +19.4¢ (+17.7¢ to +20.3¢) | +20.3¢ (+20.0¢ to +20.8¢) |
| Robustness: Kalshi calm for the 5 min before the snapshot (7,824 rows, median) | +20.2¢ (+19.3¢ to +21.6¢) | +21.2¢ (+20.4¢ to +22.9¢) |
| Median cost per $10 (Kalshi: 45¢) | 56¢ | 57¢ |
| Book overround in-game (median) | 6.0% | 6.1% |
| Rows where the book was cheaper than Kalshi | 36% | 32% |

Intervals resample whole games (2,000 draws). By season (median): 2025 FanDuel +17.4¢ (+16.6¢ to +19.2¢), DraftKings +18.8¢ (+17.4¢ to +19.1¢); 2026 FanDuel +21.4¢ (+19.9¢ to +22.8¢), DraftKings +23.4¢ (+22.7¢ to +24.3¢).

**Median vs mean.** Every median interval excludes zero. FanDuel's **mean** interval includes zero: FanDuel is much cheaper than Kalshi on longshots, and those rows pull the average down. Report the median as the headline, and say that on average across all prices FanDuel's gap is not distinguishable from zero.

## Where the gap is (cost per $10, median)
| Fair chance | Kalshi | FanDuel | DraftKings | FanDuel extra | DraftKings extra | Rows |
|---|---|---|---|---|---|---|
| 10-20% | 92¢ | 44¢ | 90¢ | -45.7¢ | -3.6¢ | 3,230 |
| 20-30% | 71¢ | 45¢ | 75¢ | -27.7¢ | +2.3¢ | 2,951 |
| 30-40% | 58¢ | 57¢ | 72¢ | -2.7¢ | +13.1¢ | 2,627 |
| 40-50% | 49¢ | 59¢ | 70¢ | +8.7¢ | +19.9¢ | 2,481 |
| 50-60% | 40¢ | 55¢ | 54¢ | +13.9¢ | +13.2¢ | 2,493 |
| 60-70% | 32¢ | 55¢ | 53¢ | +23.1¢ | +20.2¢ | 2,623 |
| 70-80% | 24¢ | 61¢ | 52¢ | +35.9¢ | +28.9¢ | 2,934 |
| 80-90% | 16¢ | 58¢ | 47¢ | +41.1¢ | +29.1¢ | 3,253 |

Kalshi is cheaper for teams at a 40% chance or more. On longshots under 30%, FanDuel is cheaper than Kalshi, and DraftKings is close to Kalshi. Kalshi's 1¢ spread plus fee is a large share of a cheap contract. The pattern is the same with each book's own de-vigged price as the fair price, so it reflects cost structure, not Kalshi's ruler.

## Before and after big swings (187 kept swings)
| | FanDuel | DraftKings |
|---|---|---|
| Before (median) | +17.8¢ (+16.0¢ to +20.6¢) | +16.9¢ (+14.7¢ to +20.9¢) |
| After (median) | +22.4¢ (+17.3¢ to +23.4¢) | +18.4¢ (+16.2¢ to +20.1¢) |
| Paired change, after − before | -1.9¢ (-10.1¢ to +6.1¢) | -0.6¢ (-5.2¢ to +3.8¢) |

The paired change is **not distinguishable from zero** for either book (154 FanDuel and 150 DraftKings pairs). Swing rows: 1,480; 488 not calm; 20 after-swing book prices were older than the swing and dropped.

## Availability
Books listed no price for a live game in 7.6% (FanDuel) and 8.4% (DraftKings) of in-game snapshots. The gaps are not around big plays: under 2% of snapshots within 15 minutes of a swing, and 0 of 187 first snapshots after one. They are near the end of games: about 39% of snapshots in a game's last 10 minutes and 26% with 10–30 minutes left, against under 1% in the first two hours. Kalshi kept quoting.

## Exclusions (main rule)
| Reason | Rows |
|---|---|
| Kalshi moved > 2 points in the window | 23,172 |
| fair price outside 10-90 | 8,902 |
| Kalshi quote filled (one-sided) in the window | 886 |
| no Kalshi data for the game | 456 |
| no Kalshi minute at the snapshot | 348 |
| Kalshi spread > 5c in the window | 68 |

"No Kalshi data for the game" is the 2025 NFC Championship (LA at SEA), which has no Kalshi candles in either source.

## Caveats
- Snapshots are every 5 minutes: a line freeze shorter than that is invisible. "No suspensions around swings" means none lasting until the next snapshot.
- Moneyline only. Kalshi at 24 contracts; in-game Kalshi depth beyond the quoted spread is not checked.
- Only calm moments (40% of rows) are compared; fast-moving moments are excluded by design.
- Fair price = Kalshi midpoint, matching the pregame study; the book-de-vig robustness check gives the same result.
