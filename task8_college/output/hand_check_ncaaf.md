# Hand-check worksheet (college): 5 swings against the raw Odds API responses

Picked at random (seed 7) from swings with a usable before-and-after pair. For each time: the raw file, the snapshot time in it, the event found by its id, and each book's American odds for both teams read straight from the JSON, next to the aligned file's values. Recomputed: implied probability from the odds, Kalshi midpoint from bid and ask, and extra cost A.

## 401858248-S02
- **before**: request 2026-10-03T22:11:00Z (swing's own time 2026-10-03T22:11:00Z), raw `20261003T221100Z.json`, snapshot 2026-10-03T22:10:36Z (aligned 2026-10-03T22:10:36Z, age 0.40 min); event `a77fd3143159a9d16a75685528d9960b` Louisville Cardinals @ NC State Wolfpack, kickoff 2026-10-03T19:35:45Z
  - FanDuel raw: Louisville Cardinals +190, NC State Wolfpack -250 (last_update 2026-10-03T22:10:31Z)
    - aligned NC State (home): odds -250, implied 0.7143, Shin 0.6847; Kalshi bid/ask 67.0/68.0 mid 67.5, fee 1.54c, cost 29.4c; book cost A 55.0c, extra A +25.6c -> match
    - aligned Louisville (away): odds +190, implied 0.3448, Shin 0.3153; Kalshi bid/ask 32.0/33.0 mid 32.5, fee 1.58c, cost 60.2c; book cost A 57.5c, extra A -2.7c -> match
  - DraftKings raw: Louisville Cardinals +193, NC State Wolfpack -263 (last_update 2026-10-03T22:09:59Z)
    - aligned NC State (home): odds -263, implied 0.7245, Shin 0.6916; Kalshi bid/ask 67.0/68.0 mid 67.5, fee 1.54c, cost 29.4c; book cost A 68.3c, extra A +39.0c -> match
    - aligned Louisville (away): odds +193, implied 0.3413, Shin 0.3084; Kalshi bid/ask 32.0/33.0 mid 32.5, fee 1.58c, cost 60.2c; book cost A 47.8c, extra A -12.5c -> match
- **after**: request 2026-10-03T22:22:00Z (swing's own time 2026-10-03T22:22:00Z), raw `20261003T222200Z.json`, snapshot 2026-10-03T22:20:36Z (aligned 2026-10-03T22:20:36Z, age 1.40 min); event `a77fd3143159a9d16a75685528d9960b` Louisville Cardinals @ NC State Wolfpack, kickoff 2026-10-03T19:35:45Z
  - FanDuel raw: Louisville Cardinals -142, NC State Wolfpack +112 (last_update 2026-10-03T22:20:28Z)
    - aligned NC State (home): odds +112, implied 0.4717, Shin 0.4425; Kalshi bid/ask 43.0/44.0 mid 43.5, fee 1.75c, cost 49.2c; book cost A 77.8c, extra A +28.6c -> match
    - aligned Louisville (away): odds -142, implied 0.5868, Shin 0.5575; Kalshi bid/ask 56.0/57.0 mid 56.5, fee 1.75c, cost 38.3c; book cost A 37.1c, extra A -1.2c -> match
  - DraftKings raw: Louisville Cardinals -152, NC State Wolfpack +114 (last_update 2026-10-03T22:20:13Z)
    - aligned NC State (home): odds +114, implied 0.4673, Shin 0.4321; Kalshi bid/ask 43.0/44.0 mid 43.5, fee 1.75c, cost 49.2c; book cost A 69.1c, extra A +19.9c -> match
    - aligned Louisville (away): odds -152, implied 0.6032, Shin 0.5679; Kalshi bid/ask 56.0/57.0 mid 56.5, fee 1.75c, cost 38.3c; book cost A 63.3c, extra A +25.0c -> match

## 401858458-S01
- **before**: request 2026-09-20T05:08:00Z (swing's own time 2026-09-20T05:08:00Z), raw `20260920T050800Z.json`, snapshot 2026-09-20T05:05:36Z (aligned 2026-09-20T05:05:36Z, age 2.40 min); event `7a6a2035bf5d7abd30d6cc8b76d59e3e` Purdue Boilermakers @ UCLA Bruins, kickoff 2026-09-20T03:10:00Z
  - FanDuel raw: Purdue Boilermakers +134, UCLA Bruins -172 (last_update 2026-09-20T05:05:23Z)
    - aligned UCLA (home): odds -172, implied 0.6324, Shin 0.6025; Kalshi bid/ask 59.0/60.0 mid 59.5, fee 1.71c, cost 35.8c; book cost A 59.1c, extra A +23.3c -> match
    - aligned Purdue (away): odds +134, implied 0.4274, Shin 0.3975; Kalshi bid/ask 40.0/41.0 mid 40.5, fee 1.71c, cost 51.7c; book cost A 52.3c, extra A +0.6c -> match
  - DraftKings raw: Purdue Boilermakers +124, UCLA Bruins -165 (last_update 2026-09-20T05:05:02Z)
    - aligned UCLA (home): odds -165, implied 0.6226, Shin 0.5881; Kalshi bid/ask 59.0/60.0 mid 59.5, fee 1.71c, cost 35.8c; book cost A 44.4c, extra A +8.6c -> match
    - aligned Purdue (away): odds +124, implied 0.4464, Shin 0.4119; Kalshi bid/ask 40.0/41.0 mid 40.5, fee 1.71c, cost 51.7c; book cost A 92.8c, extra A +41.1c -> match
- **after**: request 2026-09-20T05:16:00Z (swing's own time 2026-09-20T05:16:00Z), raw `20260920T051600Z.json`, snapshot 2026-09-20T05:15:36Z (aligned 2026-09-20T05:15:36Z, age 0.40 min); event `7a6a2035bf5d7abd30d6cc8b76d59e3e` Purdue Boilermakers @ UCLA Bruins, kickoff 2026-09-20T03:10:00Z
  - FanDuel raw: Purdue Boilermakers +255, UCLA Bruins -350 (last_update 2026-09-20T05:14:21Z)
    - aligned UCLA (home): odds -350, implied 0.7778, Shin 0.7480; Kalshi bid/ask 76.0/77.0 mid 76.5, fee 1.25c, cost 22.4c; book cost A 16.4c, extra A -5.9c -> match
    - aligned Purdue (away): odds +255, implied 0.2817, Shin 0.2520; Kalshi bid/ask 23.0/24.0 mid 23.5, fee 1.29c, cost 70.8c; book cost A 165.8c, extra A +94.9c -> match
  - DraftKings raw: Purdue Boilermakers +233, UCLA Bruins -322 (last_update 2026-09-20T05:15:21Z)
    - aligned UCLA (home): odds -322, implied 0.7630, Shin 0.7314; Kalshi bid/ask 76.0/77.0 mid 76.5, fee 1.25c, cost 22.4c; book cost A -2.6c, extra A -24.9c -> match
    - aligned Purdue (away): odds +233, implied 0.3003, Shin 0.2686; Kalshi bid/ask 23.0/24.0 mid 23.5, fee 1.29c, cost 70.8c; book cost A 217.5c, extra A +146.6c -> match

## 401866449-S02
- **before**: request 2026-10-24T23:01:00Z (swing's own time 2026-10-24T23:01:00Z), raw `20261024T230100Z.json`, snapshot 2026-10-24T23:00:36Z (aligned 2026-10-24T23:00:36Z, age 0.40 min); event `1a5a1c924e5dec296e50299139791794` Eastern Michigan Eagles @ Ohio Bobcats, kickoff 2026-10-24T20:05:41Z
  - FanDuel raw: Eastern Michigan Eagles +440, Ohio Bobcats -700 (last_update 2026-10-24T23:00:13Z)
    - aligned Ohio (home): odds -700, implied 0.8750, Shin 0.8449; Kalshi bid/ask 79.0/80.0 mid 79.5, fee 1.12c, cost 20.0c; book cost A 91.4c, extra A +71.4c -> match
    - aligned Eastern Michigan (away): odds +440, implied 0.1852, Shin 0.1551; Kalshi bid/ask 20.0/21.0 mid 20.5, fee 1.17c, cost 75.2c; book cost A -107.0c, extra A -182.2c -> match
  - DraftKings raw: Eastern Michigan Eagles +287, Ohio Bobcats -419 (last_update 2026-10-24T23:00:33Z)
    - aligned Ohio (home): odds -419, implied 0.8073, Shin 0.7745; Kalshi bid/ask 79.0/80.0 mid 79.5, fee 1.12c, cost 20.0c; book cost A 15.3c, extra A -4.8c -> match
    - aligned Eastern Michigan (away): odds +287, implied 0.2584, Shin 0.2255; Kalshi bid/ask 20.0/21.0 mid 20.5, fee 1.17c, cost 75.2c; book cost A 206.7c, extra A +131.5c -> match
- **after**: request 2026-10-24T23:12:00Z (swing's own time 2026-10-24T23:12:00Z), raw `20261024T231200Z.json`, snapshot 2026-10-24T23:10:36Z (aligned 2026-10-24T23:10:36Z, age 1.40 min); event `1a5a1c924e5dec296e50299139791794` Eastern Michigan Eagles @ Ohio Bobcats, kickoff 2026-10-24T20:05:41Z
  - FanDuel raw: Eastern Michigan Eagles +215, Ohio Bobcats -290 (last_update 2026-10-24T23:10:29Z)
    - aligned Ohio (home): odds -290, implied 0.7436, Shin 0.7131; Kalshi bid/ask 69.0/70.0 mid 69.5, fee 1.50c, cost 28.0c; book cost A 65.3c, extra A +37.4c -> match
    - aligned Eastern Michigan (away): odds +215, implied 0.3175, Shin 0.2869; Kalshi bid/ask 30.0/31.0 mid 30.5, fee 1.50c, cost 61.5c; book cost A 39.3c, extra A -22.3c -> match
  - DraftKings raw: Eastern Michigan Eagles +179, Ohio Bobcats -245 (last_update 2026-10-24T23:09:48Z)
    - aligned Ohio (home): odds -245, implied 0.7101, Shin 0.6759; Kalshi bid/ask 69.0/70.0 mid 69.5, fee 1.50c, cost 28.0c; book cost A 21.3c, extra A -6.6c -> match
    - aligned Eastern Michigan (away): odds +179, implied 0.3584, Shin 0.3241; Kalshi bid/ask 30.0/31.0 mid 30.5, fee 1.50c, cost 61.5c; book cost A 149.1c, extra A +87.5c -> match

## 401858217-S02
- **before**: request 2026-09-12T20:23:00Z (swing's own time 2026-09-12T20:23:00Z), raw `20260912T202300Z.json`, snapshot 2026-09-12T20:20:36Z (aligned 2026-09-12T20:20:36Z, age 2.40 min); event `52e9b0f6515766724ee70457912bdc18` Duke Blue Devils @ Illinois Fighting Illini, kickoff 2026-09-12T19:40:00Z
  - FanDuel raw: Duke Blue Devils +250, Illinois Fighting Illini -340 (last_update 2026-09-12T20:20:08Z)
    - aligned Illinois (home): odds -340, implied 0.7727, Shin 0.7435; Kalshi bid/ask 73.0/74.0 mid 73.5, fee 1.38c, cost 24.9c; book cost A 48.8c, extra A +23.9c -> match
    - aligned Duke (away): odds +250, implied 0.2857, Shin 0.2565; Kalshi bid/ask 26.0/27.0 mid 26.5, fee 1.42c, cost 67.5c; book cost A 72.5c, extra A +5.0c -> match
  - DraftKings raw: Duke Blue Devils +260, Illinois Fighting Illini -364 (last_update 2026-09-12T20:19:39Z)
    - aligned Illinois (home): odds -364, implied 0.7845, Shin 0.7534; Kalshi bid/ask 73.0/74.0 mid 73.5, fee 1.38c, cost 24.9c; book cost A 63.1c, extra A +38.2c -> match
    - aligned Duke (away): odds +260, implied 0.2778, Shin 0.2466; Kalshi bid/ask 26.0/27.0 mid 26.5, fee 1.42c, cost 67.5c; book cost A 46.0c, extra A -21.4c -> match
- **after**: request 2026-09-12T20:31:00Z (swing's own time 2026-09-12T20:31:00Z), raw `20260912T203100Z.json`, snapshot 2026-09-12T20:30:36Z (aligned 2026-09-12T20:30:36Z, age 0.40 min); event `52e9b0f6515766724ee70457912bdc18` Duke Blue Devils @ Illinois Fighting Illini, kickoff 2026-09-12T19:40:00Z
  - FanDuel raw: Duke Blue Devils +430, Illinois Fighting Illini -670 (last_update 2026-09-12T20:30:35Z)
    - aligned Illinois (home): odds -670, implied 0.8701, Shin 0.8407; Kalshi bid/ask 82.0/83.0 mid 82.5, fee 1.00c, cost 17.9c; book cost A 51.9c, extra A +34.0c -> match
    - aligned Duke (away): odds +430, implied 0.1887, Shin 0.1593; Kalshi bid/ask 17.0/18.0 mid 17.5, fee 1.04c, cost 81.0c; book cost A 72.5c, extra A -8.5c -> match
  - DraftKings raw: Duke Blue Devils +508, Illinois Fighting Illini -790 (last_update 2026-09-12T20:30:08Z)
    - aligned Illinois (home): odds -790, implied 0.8876, Shin 0.8616; Kalshi bid/ask 82.0/83.0 mid 82.5, fee 1.00c, cost 17.9c; book cost A 70.6c, extra A +52.7c -> match
    - aligned Duke (away): odds +508, implied 0.1645, Shin 0.1384; Kalshi bid/ask 17.0/18.0 mid 17.5, fee 1.04c, cost 81.0c; book cost A -64.0c, extra A -145.0c -> match

## 401864575-S01
- **before**: request 2026-09-12T23:30:00Z (swing's own time 2026-09-12T23:30:00Z), raw `20260912T233000Z.json`, snapshot 2026-09-12T23:25:36Z (aligned 2026-09-12T23:25:36Z, age 4.40 min); event `18c682b142ecfadb8d6d801f5fb9aac7` South Alabama Jaguars @ Tulane Green Wave, kickoff 2026-09-12T23:05:00Z
  - FanDuel raw: South Alabama Jaguars +230, Tulane Green Wave -310 (last_update 2026-09-12T23:25:27Z)
    - aligned Tulane (home): odds -310, implied 0.7561, Shin 0.7265; Kalshi bid/ask 71.0/72.0 mid 71.5, fee 1.42c, cost 26.1c; book cost A 54.4c, extra A +28.2c -> match
    - aligned South Alabama (away): odds +230, implied 0.3030, Shin 0.2735; Kalshi bid/ask 28.0/29.0 mid 28.5, fee 1.46c, cost 64.3c; book cost A 59.5c, extra A -4.8c -> match
  - DraftKings raw: South Alabama Jaguars +229, Tulane Green Wave -317 (last_update 2026-09-12T23:25:05Z)
    - aligned Tulane (home): odds -317, implied 0.7602, Shin 0.7281; Kalshi bid/ask 71.0/72.0 mid 71.5, fee 1.42c, cost 26.1c; book cost A 59.4c, extra A +33.3c -> match
    - aligned South Alabama (away): odds +229, implied 0.3040, Shin 0.2719; Kalshi bid/ask 28.0/29.0 mid 28.5, fee 1.46c, cost 64.3c; book cost A 62.4c, extra A -1.9c -> match
- **after**: request 2026-09-12T23:42:00Z (swing's own time 2026-09-12T23:42:00Z), raw `20260912T234200Z.json`, snapshot 2026-09-12T23:40:36Z (aligned 2026-09-12T23:40:36Z, age 1.40 min); event `18c682b142ecfadb8d6d801f5fb9aac7` South Alabama Jaguars @ Tulane Green Wave, kickoff 2026-09-12T23:05:00Z
  - FanDuel raw: South Alabama Jaguars +126, Tulane Green Wave -162 (last_update 2026-09-12T23:40:11Z)
    - aligned Tulane (home): odds -162, implied 0.6183, Shin 0.5879; Kalshi bid/ask 56.0/59.0 mid 57.5, fee 1.71c, cost 52.8c; book cost A 70.1c, extra A +17.2c -> match
    - aligned South Alabama (away): odds +126, implied 0.4425, Shin 0.4121; Kalshi bid/ask 41.0/44.0 mid 42.5, fee 1.75c, cost 71.0c; book cost A 39.5c, extra A -31.5c -> match
  - DraftKings raw: South Alabama Jaguars +118, Tulane Green Wave -156 (last_update 2026-09-12T23:40:06Z)
    - aligned Tulane (home): odds -156, implied 0.6094, Shin 0.5753; Kalshi bid/ask 56.0/59.0 mid 57.5, fee 1.71c, cost 52.8c; book cost A 56.4c, extra A +3.6c -> match
    - aligned South Alabama (away): odds +118, implied 0.4587, Shin 0.4247; Kalshi bid/ask 41.0/44.0 mid 42.5, fee 1.75c, cost 71.0c; book cost A 73.5c, extra A +2.5c -> match

Automated comparison: all values match.

## What I compared (write this yourself)

- 
