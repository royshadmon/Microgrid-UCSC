# Panel 2 — Rule labels (four heads)

_Generated 2026-05-12T18:21:04+00:00_

Heads: `water_heater`, `hair_dryer`, `sprinklers`, `bath_lights`. Rule-only labels; no LLM supervision in this run. Starting point: `panel2_claude_code_prompt.md` §3.1. Calibrated against 35 days of accumulated data for this house — small-signal rules (sprinklers, bath_lights) use a *baseline-step* formulation (`panel2_w − 30 min rolling minimum`) instead of raw power, because the always-on panel2 baseline (150–250 W on this site) would otherwise be tagged as appliance activity. Implementation: `services/iems/training/rule_engine.py`.

Data window: `2026-04-07 18:55:50+00:00` → `2026-05-12 17:48:20+00:00` (301996 rows on 10s grid; `panel2_w` observed on 28087 rows / 9.3%).

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
| `water_heater` | 301996 | 1227 | 26471 | 274298 | 0.0443 |
| `hair_dryer` | 301996 | 57 | 26248 | 275691 | 0.0022 |
| `sprinklers` | 301996 | 781 | 24687 | 276528 | 0.0307 |
| `bath_lights` | 301996 | 215 | 25276 | 276505 | 0.0084 |

## Label counts — last 7 days

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `water_heater` | 60481 | 664 | 10278 | 49539 |
| `hair_dryer` | 60481 | 9 | 10276 | 50196 |
| `sprinklers` | 60481 | 293 | 9530 | 50658 |
| `bath_lights` | 60481 | 192 | 9599 | 50690 |

## Diurnal histograms (positive-label counts by local hour)

### water_heater
```
  00h |                              | 4
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |#                             | 18
  05h |                              | 0
  06h |#                             | 18
  07h |###                           | 38
  08h |######                        | 90
  09h |#                             | 17
  10h |                              | 0
  11h |                              | 0
  12h |##                            | 28
  13h |###                           | 48
  14h |###########                   | 152
  15h |##                            | 34
  16h |##                            | 34
  17h |###########                   | 155
  18h |##############################| 432
  19h |######                        | 93
  20h |##                            | 31
  21h |##                            | 23
  22h |                              | 0
  23h |#                             | 12
```

### hair_dryer
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |                              | 0
  07h |                              | 0
  08h |#                             | 1
  09h |                              | 0
  10h |                              | 0
  11h |                              | 0
  12h |                              | 0
  13h |#                             | 1
  14h |##                            | 2
  15h |##############################| 38
  16h |#                             | 1
  17h |#####                         | 6
  18h |###                           | 4
  19h |##                            | 2
  20h |                              | 0
  21h |##                            | 2
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
  17h |###########################   | 237
  18h |######                        | 57
  19h |#                             | 9
  20h |########################      | 212
  21h |##############################| 266
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
  22h |##############################| 213
  23h |                              | 2
```

