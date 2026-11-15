# Hand-check: 5 swings against the raw Odds API responses

For each swing and time: opened the raw response file, found the event by team names, and compared the snapshot time, each book's American odds for both teams and the market's last update with the aligned file; recomputed the implied probability and the Kalshi midpoint from bid and ask.

## 2026_01_ARI_LAC-S01
- **before** request 2026-09-13T22:33:00Z, raw file `2026-09-13T223300Z.json`: snapshot 2026-09-13T22:30:36Z (aligned: 2026-09-13T22:30:36Z), event Arizona Cardinals at Los Angeles Chargers
  - FanDuel LAC: raw -230 vs aligned -230; implied 0.6970; Kalshi bid/ask 68.0/69.0 mid 68.5; extra cost A -11.2c -> match
  - FanDuel ARI: raw +176 vs aligned +176; implied 0.3623; Kalshi bid/ask 31.0/32.0 mid 31.5; extra cost A +69.7c -> match
  - DraftKings LAC: raw -227 vs aligned -227; implied 0.6942; Kalshi bid/ask 68.0/69.0 mid 68.5; extra cost A -15.1c -> match
  - DraftKings ARI: raw +168 vs aligned +168; implied 0.3731; Kalshi bid/ask 31.0/32.0 mid 31.5; extra cost A +94.9c -> match
- **after** request 2026-09-13T22:56:00Z, raw file `2026-09-13T225600Z.json`: snapshot 2026-09-13T22:55:36Z (aligned: 2026-09-13T22:55:36Z), event Arizona Cardinals at Los Angeles Chargers
  - FanDuel LAC: raw +255 vs aligned +255; implied 0.2817; Kalshi bid/ask 31.0/32.0 mid 31.5; extra cost A -179.1c -> match
  - FanDuel ARI: raw -350 vs aligned -350; implied 0.7778; Kalshi bid/ask 68.0/69.0 mid 68.5; extra cost A +90.9c -> match
  - DraftKings LAC: raw +223 vs aligned +223; implied 0.3096; Kalshi bid/ask 31.0/32.0 mid 31.5; extra cost A -78.3c -> match
  - DraftKings ARI: raw -302 vs aligned -302; implied 0.7512; Kalshi bid/ask 68.0/69.0 mid 68.5; extra cost A +59.8c -> match

## 2026_02_GB_NYJ-S02
- **before** request 2026-09-20T19:09:00Z, raw file `2026-09-20T190900Z.json`: snapshot 2026-09-20T19:05:36Z (aligned: 2026-09-20T19:05:36Z), event Green Bay Packers at New York Jets
  - FanDuel NYJ: raw +118 vs aligned +118; implied 0.4587; Kalshi bid/ask 44.0/46.0 mid 45.0; extra cost A -38.6c -> match
  - FanDuel GB: raw -150 vs aligned -150; implied 0.6000; Kalshi bid/ask 54.0/56.0 mid 55.0; extra cost A +35.7c -> match
  - DraftKings NYJ: raw +118 vs aligned +118; implied 0.4587; Kalshi bid/ask 44.0/46.0 mid 45.0; extra cost A -38.6c -> match
  - DraftKings GB: raw -155 vs aligned -155; implied 0.6078; Kalshi bid/ask 54.0/56.0 mid 55.0; extra cost A +47.5c -> match
- **after** request 2026-09-20T19:19:00Z, raw file `2026-09-20T191900Z.json`: snapshot 2026-09-20T19:15:36Z (aligned: 2026-09-20T19:15:36Z), event Green Bay Packers at New York Jets
  - FanDuel NYJ: raw -265 vs aligned -265; implied 0.7260; Kalshi bid/ask 68.0/69.0 mid 68.5; extra cost A +28.1c -> match
  - FanDuel GB: raw +200 vs aligned +200; implied 0.3333; Kalshi bid/ask 31.0/32.0 mid 31.5; extra cost A -5.9c -> match
  - DraftKings NYJ: raw -187 vs aligned -187; implied 0.6516; Kalshi bid/ask 68.0/69.0 mid 68.5; extra cost A -79.7c -> match
  - DraftKings GB: raw +141 vs aligned +141; implied 0.4149; Kalshi bid/ask 31.0/32.0 mid 31.5; extra cost A +180.0c -> match

## 2026_08_ARI_DAL-S01
- **before** request 2026-11-01T18:20:00Z, raw file `2026-11-01T182000Z.json`: snapshot 2026-11-01T18:15:36Z (aligned: 2026-11-01T18:15:36Z), event Arizona Cardinals at Dallas Cowboys
  - FanDuel DAL: raw -280 vs aligned -280; implied 0.7368; Kalshi bid/ask 66.0/67.0 mid 66.5; extra cost A +67.1c -> match
  - FanDuel ARI: raw +210 vs aligned +210; implied 0.3226; Kalshi bid/ask 33.0/34.0 mid 33.5; extra cost A -97.1c -> match
  - DraftKings DAL: raw -242 vs aligned -242; implied 0.7076; Kalshi bid/ask 66.0/67.0 mid 66.5; extra cost A +29.8c -> match
  - DraftKings ARI: raw +178 vs aligned +178; implied 0.3597; Kalshi bid/ask 33.0/34.0 mid 33.5; extra cost A +10.1c -> match
- **after** request 2026-11-01T18:38:00Z, raw file `2026-11-01T183800Z.json`: snapshot 2026-11-01T18:35:36Z (aligned: 2026-11-01T18:35:36Z), event Arizona Cardinals at Dallas Cowboys
  - FanDuel DAL: raw -850 vs aligned -850; implied 0.8947; Kalshi bid/ask 85.0/86.0 mid 85.5; extra cost A +28.6c -> match
  - FanDuel ARI: raw +500 vs aligned +500; implied 0.1667; Kalshi bid/ask 14.0/15.0 mid 14.5; extra cost A +41.0c -> match
  - DraftKings DAL: raw -840 vs aligned -840; implied 0.8936; Kalshi bid/ask 85.0/86.0 mid 85.5; extra cost A +27.4c -> match
  - DraftKings ARI: raw +501 vs aligned +501; implied 0.1664; Kalshi bid/ask 14.0/15.0 mid 14.5; extra cost A +39.5c -> match

## 2025_20_HOU_NE-S01
- **before** request 2026-01-18T20:05:00Z, raw file `2026-01-18T200500Z.json`: snapshot 2026-01-18T20:00:43Z (aligned: 2026-01-18T20:00:43Z), event Houston Texans at New England Patriots
  - FanDuel NE: raw -205 vs aligned -205; implied 0.6721; Kalshi bid/ask 62.0/63.0 mid 62.5; extra cost A +36.6c -> match
  - FanDuel HOU: raw +172 vs aligned +172; implied 0.3676; Kalshi bid/ask 37.0/38.0 mid 37.5; extra cost A -74.6c -> match
  - DraftKings NE: raw -180 vs aligned -180; implied 0.6429; Kalshi bid/ask 62.0/63.0 mid 62.5; extra cost A -5.7c -> match
  - DraftKings HOU: raw +150 vs aligned +150; implied 0.4000; Kalshi bid/ask 37.0/38.0 mid 37.5; extra cost A +7.9c -> match
- **after** request 2026-01-18T20:19:00Z, raw file `2026-01-18T201900Z.json`: snapshot 2026-01-18T20:15:39Z (aligned: 2026-01-18T20:15:39Z), event Houston Texans at New England Patriots
  - FanDuel NE: raw -350 vs aligned -350; implied 0.7778; Kalshi bid/ask 75.0/76.0 mid 75.5; extra cost A +6.1c -> match
  - FanDuel HOU: raw +255 vs aligned +255; implied 0.2817; Kalshi bid/ask 24.0/25.0 mid 24.5; extra cost A +60.6c -> match
  - DraftKings NE: raw -330 vs aligned -330; implied 0.7674; Kalshi bid/ask 75.0/76.0 mid 75.5; extra cost A -7.0c -> match
  - DraftKings HOU: raw +240 vs aligned +240; implied 0.2941; Kalshi bid/ask 24.0/25.0 mid 24.5; extra cost A +97.4c -> match

## 2026_07_CIN_BAL-S01
- **before** request 2026-10-25T18:46:00Z, raw file `2026-10-25T184600Z.json`: snapshot 2026-10-25T18:45:36Z (aligned: 2026-10-25T18:45:36Z), event Cincinnati Bengals at Baltimore Ravens
  - FanDuel BAL: raw -205 vs aligned -205; implied 0.6721; Kalshi bid/ask 64.0/65.0 mid 64.5; extra cost A +8.5c -> match
  - FanDuel CIN: raw +158 vs aligned +158; implied 0.3876; Kalshi bid/ask 35.0/36.0 mid 35.5; extra cost A +27.6c -> match
  - DraftKings BAL: raw -176 vs aligned -176; implied 0.6377; Kalshi bid/ask 64.0/65.0 mid 64.5; extra cost A -43.4c -> match
  - DraftKings CIN: raw +132 vs aligned +132; implied 0.4310; Kalshi bid/ask 35.0/36.0 mid 35.5; extra cost A +119.9c -> match
- **after** request 2026-10-25T18:59:00Z, raw file `2026-10-25T185900Z.json`: snapshot 2026-10-25T18:55:36Z (aligned: 2026-10-25T18:55:36Z), event Cincinnati Bengals at Baltimore Ravens
  - FanDuel BAL: raw +128 vs aligned +128; implied 0.4386; Kalshi bid/ask 37.0/38.0 mid 37.5; extra cost A +90.4c -> match
  - FanDuel CIN: raw -164 vs aligned -164; implied 0.6212; Kalshi bid/ask 62.0/63.0 mid 62.5; extra cost A -39.6c -> match
  - DraftKings BAL: raw +170 vs aligned +170; implied 0.3704; Kalshi bid/ask 37.0/38.0 mid 37.5; extra cost A -67.1c -> match
  - DraftKings CIN: raw -230 vs aligned -230; implied 0.6970; Kalshi bid/ask 62.0/63.0 mid 62.5; extra cost A +69.8c -> match

Result: all values match.