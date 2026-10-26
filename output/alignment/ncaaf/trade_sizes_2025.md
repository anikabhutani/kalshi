# Kalshi college football (game-winner markets of the matched games) trade sizes, 2025 season (contracts)

1870 markets; percentiles use inverted_cdf (each value is a real trade size).

| Markets | Block trades | Trades | Median | p75 | p90 | Median (per contract) | p75 (pc) | p90 (pc) |
|---|---|---|---|---|---|---|---|---|
| all college markets | including | 12,174,453 | 50 | 196 | 600 | 2222 | 6000 | 12207 |
| all college markets | excluding | 12,174,453 | 50 | 196 | 600 | 2222 | 6000 | 12207 |
| KXNCAAFGAME | including | 12,174,453 | 50 | 196 | 600 | 2222 | 6000 | 12207 |
| KXNCAAFGAME | excluding | 12,174,453 | 50 | 196 | 600 | 2222 | 6000 | 12207 |

## Checks

- [pass] all_markets_pulled: 1870 markets; 0 not finished; 0 hit the page safety limit.
- [pass] no_duplicate_trades: 12,174,453 trades; 0 trade ids appear twice after merging live and historical.
- [pass] sizes_valid: 0 trades with a missing or non-positive size.
- [pass] trades_belong_to_markets: 0 trades whose ticker is not one of the season's markets.
- [pass] percentiles_recomputed: Median, p75 and p90 recomputed from the sorted sizes; largest difference 0.
- [pass] markets_without_trades: 0 markets had no trades at all (normal for far-off strikes).
- [pass] block_trades: 0.00% of trades are block trades; both versions are reported.
