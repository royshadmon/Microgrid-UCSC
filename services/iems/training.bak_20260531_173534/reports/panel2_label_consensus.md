# Panel 2 — Rule labels (four heads)

_Generated 2026-05-18T20:59:47+00:00_

Heads: `water_heater`, `hair_dryer`, `sprinklers`, `bath_lights`. Rule-only labels; no LLM supervision in this run. Starting point: `panel2_claude_code_prompt.md` §3.1. Calibrated against 35 days of accumulated data for this house — small-signal rules (sprinklers, bath_lights) use a *baseline-step* formulation (`panel2_w − 30 min rolling minimum`) instead of raw power, because the always-on panel2 baseline (150–250 W on this site) would otherwise be tagged as appliance activity. Implementation: `services/iems/training/rule_engine.py`.

Data window: `2026-04-28 23:59:50+00:00` → `2026-05-18 20:59:10+00:00` (171717 rows on 10s grid; `panel2_w` observed on 31122 rows / 18.1%).

## Rule definitions (paraphrase)

```
p2_60s     = panel2_w.rolling('60s').mean()
p2_step    = panel2_w − panel2_w.rolling('30min').min()
irr_6h     = irradiance.rolling('6h').mean()
local_hour = ts.tz_convert('America/Los_Angeles').hour

water_heater:                              [raw power]
  1  if  2000 < p2_60s < 4500
  0  if  panel2_w < 300
  0  if  irr_6h > 500 AND outside_temp > 65°F AND p2_60s < 1500
        (solar boiler preheated the tank)

hair_dryer:                                [raw power]
  1  if  1100 < p2_60s < 1900 AND water_heater != 1
  0  if  panel2_w < 300

sprinklers:                                [baseline step]
  am_pm = local_hour in [4..7] or [17..21]
  1  if  50 < p2_step < 250 AND am_pm AND wh/hd != 1
  0  if  NOT am_pm
  0  if  p2_step < 25

bath_lights:                               [baseline step]
  evening = local_hour >= 18 OR local_hour <= 1
  1  if  50 < p2_step < 250 AND evening AND wh/hd/spr != 1
  0  if  NOT evening
  0  if  p2_step < 25
```

## Label counts — full window

| head | rows | pos (1) | neg (0) | NaN | pos rate |
|---|---:|---:|---:|---:|---:|
| `water_heater` | 171717 | 942 | 29475 | 141300 | 0.0310 |
| `hair_dryer` | 171717 | 65 | 29882 | 141770 | 0.0022 |
| `sprinklers` | 171717 | 1308 | 26420 | 143989 | 0.0472 |
| `bath_lights` | 171717 | 304 | 27831 | 143582 | 0.0108 |

## Label counts — last 7 days

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `water_heater` | 60481 | 21 | 11427 | 49033 |
| `hair_dryer` | 60481 | 14 | 11654 | 48813 |
| `sprinklers` | 60481 | 608 | 9976 | 49897 |
| `bath_lights` | 60481 | 116 | 10399 | 49966 |

## Diurnal histograms (positive-label counts by local hour)

### water_heater
```
  00h |                              | 4
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |#                             | 18
  05h |#                             | 18
  06h |#                             | 18
  07h |#                             | 18
  08h |######                        | 90
  09h |#                             | 17
  10h |                              | 0
  11h |                              | 0
  12h |                              | 0
  13h |                              | 6
  14h |###                           | 41
  15h |                              | 0
  16h |                              | 0
  17h |###########                   | 155
  18h |##############################| 417
  19h |#######                       | 93
  20h |##                            | 31
  21h |#                             | 16
  22h |                              | 0
  23h |                              | 0
```

### hair_dryer
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |###########                   | 13
  07h |                              | 0
  08h |#                             | 1
  09h |                              | 0
  10h |                              | 0
  11h |                              | 0
  12h |                              | 0
  13h |##                            | 2
  14h |#                             | 1
  15h |##############################| 37
  16h |                              | 0
  17h |###                           | 4
  18h |###                           | 4
  19h |##                            | 2
  20h |                              | 0
  21h |#                             | 1
  22h |                              | 0
  23h |                              | 0
```

### sprinklers
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |                              | 0
  07h |                              | 0
  08h |                              | 0
  09h |                              | 0
  10h |                              | 0
  11h |                              | 0
  12h |                              | 0
  13h |                              | 0
  14h |                              | 0
  15h |                              | 0
  16h |                              | 0
  17h |############                  | 268
  18h |###                           | 68
  19h |##                            | 46
  20h |############                  | 266
  21h |##############################| 660
  22h |                              | 0
  23h |                              | 0
```

### bath_lights
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |                              | 0
  07h |                              | 0
  08h |                              | 0
  09h |                              | 0
  10h |                              | 0
  11h |                              | 0
  12h |                              | 0
  13h |                              | 0
  14h |                              | 0
  15h |                              | 0
  16h |                              | 0
  17h |                              | 0
  18h |                              | 0
  19h |                              | 0
  20h |                              | 0
  21h |                              | 0
  22h |##############################| 286
  23h |##                            | 18
```

