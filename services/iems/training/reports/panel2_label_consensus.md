# Panel 2 — Rule labels (four heads)

_Generated 2026-06-01T01:31:58+00:00_

Heads: `water_heater`, `hair_dryer`, `sprinklers`, `bath_lights`. Rule-only labels; no LLM supervision in this run. Starting point: `panel2_claude_code_prompt.md` §3.1. Calibrated against 35 days of accumulated data for this house — small-signal rules (sprinklers, bath_lights) use a *baseline-step* formulation (`panel2_w − 30 min rolling minimum`) instead of raw power, because the always-on panel2 baseline (150–250 W on this site) would otherwise be tagged as appliance activity. Implementation: `services/iems/training/rule_engine.py`.

Data window: `2026-04-28 23:59:50+00:00` → `2026-06-01 01:28:30+00:00` (285653 rows on 10s grid; `panel2_w` observed on 84182 rows / 29.5%).

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
| `water_heater` | 285653 | 1584 | 81763 | 202306 | 0.0190 |
| `hair_dryer` | 285653 | 210 | 81716 | 203727 | 0.0026 |
| `sprinklers` | 285653 | 3475 | 73749 | 208429 | 0.0450 |
| `bath_lights` | 285653 | 1130 | 75273 | 209250 | 0.0148 |

## Label counts — last 7 days

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `water_heater` | 60481 | 483 | 23856 | 36142 |
| `hair_dryer` | 60481 | 52 | 23862 | 36567 |
| `sprinklers` | 60481 | 1159 | 21668 | 37654 |
| `bath_lights` | 60481 | 34 | 22570 | 37877 |

## Diurnal histograms (positive-label counts by local hour)

### water_heater
```
  00h |#                             | 24
  01h |                              | 0
  02h |#                             | 19
  03h |                              | 0
  04h |##                            | 37
  05h |##                            | 37
  06h |#####                         | 88
  07h |###                           | 43
  08h |######                        | 91
  09h |#####                         | 88
  10h |##                            | 34
  11h |                              | 0
  12h |                              | 1
  13h |###                           | 52
  14h |#####                         | 82
  15h |                              | 3
  16h |####                          | 65
  17h |############                  | 204
  18h |##############################| 491
  19h |######                        | 104
  20h |######                        | 105
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
  06h |####                          | 14
  07h |#########                     | 28
  08h |###                           | 11
  09h |####                          | 14
  10h |                              | 0
  11h |#########                     | 28
  12h |                              | 0
  13h |#                             | 3
  14h |                              | 1
  15h |##############################| 97
  16h |                              | 1
  17h |##                            | 5
  18h |#                             | 4
  19h |#                             | 2
  20h |                              | 1
  21h |                              | 1
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
  06h |#                             | 23
  07h |####                          | 162
  08h |                              | 0
  09h |                              | 0
  10h |                              | 0
  11h |                              | 0
  12h |                              | 0
  13h |                              | 0
  14h |                              | 0
  15h |                              | 0
  16h |                              | 0
  17h |#########                     | 415
  18h |####                          | 190
  19h |##                            | 79
  20h |############################  | 1256
  21h |##############################| 1350
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
  22h |##############################| 1058
  23h |##                            | 72
```

