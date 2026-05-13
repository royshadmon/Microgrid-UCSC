# Panel 3 — Rule labels (eight heads)

_Generated 2026-05-12T18:24:01+00:00_

Heads: `refrigerator`, `dishwasher`, `microwave`, `dryer`, `washing_machine`, `pressure_pump`, `computers`, `tv_stereo`. Rule-only; no LLM supervision in this run. Starting point: `panel3_claude_code_prompt.md` §3.1 + §3.2 sequential constraint. Calibrated against 35 days of accumulated data for this house — mid-range heads (washer, pump, computers, TV) use a *baseline-step* formulation (`panel3_w − 30 min rolling minimum`) instead of raw power, because panel3 spends ~76% of time in the 200–500 W always-on baseline (fridge cycling + networking + idle computers) which would otherwise be tagged as appliance activity. Large clearly-separated signals (dryer, dishwasher) keep raw-power rules. Implementation: `services/iems/training/rule_engine.py`.

Data window: `2026-04-07 18:55:50+00:00` → `2026-05-12 17:48:20+00:00` (301996 rows on 10s grid; `panel3_w` observed on 28087 rows / 9.3%).

## Rule definitions (paraphrase)

Rules apply in order of signal size so smaller heads can
be conditioned on the absence of bigger appliances.

```
p3_60s     = panel3_w.rolling('60s').mean()
p3_delta   = panel3_w.diff()
p3_step    = panel3_w − panel3_w.rolling('30min').min()
p3_fridge  = panel3_w.rolling('4h').quantile(0.1)
local_hour = ts.tz_convert('America/Los_Angeles').hour

dryer         [raw] : 1 if 3500<p3_60s<7500 | 0 if panel3_w<2000
microwave     [raw] : 1 if p3_delta>600 AND 800<p3_60s<1700 AND dryer!=1
                      (rising-edge to catch <5-min bursts)
                      0 if panel3_w<600
dishwasher    [raw] : 1 if 1000<p3_60s<2000 AND dryer/mw!=1
                      0 if panel3_w<600
washing_mach. [step]: 1 if 500<p3_step<2000 AND dryer/mw/dw!=1
                      0 if panel3_w<250
pressure_pump [step]: 1 if 400<p3_step<1000 AND dryer/mw/dw/wm!=1
                      0 if panel3_w<250
refrigerator        : 1 if 50<p3_fridge<250 (always-on baseline)
                      0 if p3_fridge<30   (very rare at this house)
computers     [step]: 1 if 100<p3_step<500 AND 7<=h<=22 AND big!=1
                      0 if NOT work hours OR panel3_w<100
tv_stereo     [step]: 1 if 80<p3_step<200 AND (h>=17 OR h<=1) AND big/comp!=1
                      0 if NOT evening OR panel3_w<70

§3.2 refinement: a dryer-ON without a washer-ON in the
prior 90 minutes is suspect → drop to NaN, don't force 0.
```

## Label counts — full window

| head | rows | pos (1) | neg (0) | NaN | pos rate |
|---|---:|---:|---:|---:|---:|
| `refrigerator` | 301996 | 13963 | 0 | 288033 | 1.0000 |
| `dishwasher` | 301996 | 1337 | 24467 | 276192 | 0.0518 |
| `microwave` | 301996 | 175 | 24467 | 277354 | 0.0071 |
| `dryer` | 301996 | 481 | 26792 | 274723 | 0.0176 |
| `washing_machine` | 301996 | 401 | 21949 | 279646 | 0.0179 |
| `pressure_pump` | 301996 | 63 | 20886 | 281047 | 0.0030 |
| `computers` | 301996 | 5995 | 3202 | 292799 | 0.6518 |
| `tv_stereo` | 301996 | 1437 | 17915 | 282644 | 0.0743 |

## Label counts — last 7 days

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `refrigerator` | 60481 | 8531 | 0 | 51950 |
| `dishwasher` | 60481 | 656 | 9482 | 50343 |
| `microwave` | 60481 | 144 | 9482 | 50855 |
| `dryer` | 60481 | 167 | 10673 | 49641 |
| `washing_machine` | 60481 | 240 | 8728 | 51513 |
| `pressure_pump` | 60481 | 30 | 8493 | 51958 |
| `computers` | 60481 | 2265 | 1333 | 56883 |
| `tv_stereo` | 60481 | 795 | 5650 | 54036 |

## Contiguous ON-run length distribution (in 10s samples)

| head | runs | mean | p50 | p90 | max |
|---|---:|---:|---:|---:|---:|
| `refrigerator` | 163 | 85.7 | 25 | 235 | 1019 |
| `dishwasher` | 211 | 6.3 | 2 | 16 | 159 |
| `microwave` | 170 | 1.0 | 1 | 1 | 2 |
| `dryer` | 32 | 15.0 | 11 | 33 | 80 |
| `washing_machine` | 192 | 2.1 | 2 | 4 | 17 |
| `pressure_pump` | 39 | 1.6 | 1 | 2 | 19 |
| `computers` | 360 | 16.7 | 4 | 42 | 181 |
| `tv_stereo` | 102 | 14.1 | 6 | 36 | 91 |

## Diurnal histograms (positive-label counts by local hour)

### refrigerator
```
  00h |#####                         | 242
  01h |####                          | 205
  02h |####                          | 193
  03h |###                           | 165
  04h |###                           | 179
  05h |###                           | 180
  06h |##                            | 128
  07h |#####                         | 276
  08h |###                           | 153
  09h |########                      | 423
  10h |#################             | 899
  11h |#######################       | 1205
  12h |##############################| 1571
  13h |###########################   | 1431
  14h |######################        | 1136
  15h |##############                | 734
  16h |##############                | 733
  17h |###############               | 775
  18h |#####################         | 1120
  19h |################              | 836
  20h |#                             | 32
  21h |#######                       | 352
  22h |#########                     | 451
  23h |##########                    | 544
```

### dishwasher
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |#######                       | 73
  07h |                              | 1
  08h |####                          | 40
  09h |#                             | 6
  10h |##                            | 27
  11h |                              | 5
  12h |###                           | 28
  13h |######                        | 68
  14h |##############################| 324
  15h |#####################         | 226
  16h |#####                         | 54
  17h |##############                | 150
  18h |#####################         | 231
  19h |#########                     | 102
  20h |                              | 0
  21h |                              | 0
  22h |                              | 0
  23h |                              | 2
```

### microwave
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |#                             | 2
  07h |                              | 0
  08h |                              | 1
  09h |                              | 1
  10h |                              | 0
  11h |                              | 0
  12h |                              | 0
  13h |###                           | 8
  14h |##                            | 5
  15h |                              | 0
  16h |##                            | 4
  17h |##############################| 74
  18h |#####################         | 52
  19h |###########                   | 28
  20h |                              | 0
  21h |                              | 0
  22h |                              | 0
  23h |                              | 0
```

### dryer
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
  13h |##################            | 122
  14h |##                            | 14
  15h |                              | 0
  16h |                              | 0
  17h |###########                   | 76
  18h |##############################| 208
  19h |#########                     | 61
  20h |                              | 0
  21h |                              | 0
  22h |                              | 0
  23h |                              | 0
```

### washing_machine
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |                              | 0
  07h |##                            | 9
  08h |########                      | 31
  09h |#                             | 5
  10h |#####                         | 20
  11h |###                           | 11
  12h |##                            | 8
  13h |########                      | 34
  14h |##########                    | 40
  15h |####                          | 18
  16h |#####                         | 20
  17h |##############################| 123
  18h |##############                | 57
  19h |#####                         | 22
  20h |                              | 0
  21h |                              | 0
  22h |                              | 0
  23h |#                             | 3
```

### pressure_pump
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |                              | 0
  07h |##                            | 2
  08h |####                          | 3
  09h |                              | 0
  10h |#                             | 1
  11h |#                             | 1
  12h |#####                         | 4
  13h |#                             | 1
  14h |#                             | 1
  15h |##                            | 2
  16h |                              | 0
  17h |############################  | 22
  18h |##############################| 24
  19h |##                            | 2
  20h |                              | 0
  21h |                              | 0
  22h |                              | 0
  23h |                              | 0
```

### computers
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |                              | 0
  07h |#                             | 25
  08h |#####                         | 130
  09h |###############               | 364
  10h |############                  | 294
  11h |###########################   | 665
  12h |#######################       | 574
  13h |#####################         | 534
  14h |########                      | 191
  15h |##################            | 446
  16h |##############################| 751
  17h |##################            | 446
  18h |#######################       | 577
  19h |###############               | 381
  20h |#                             | 15
  21h |###########                   | 282
  22h |#############                 | 320
  23h |                              | 0
```

### tv_stereo
```
  00h |#############                 | 153
  01h |#######                       | 75
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
  17h |##########                    | 116
  18h |######                        | 70
  19h |#####                         | 52
  20h |##################            | 207
  21h |######################        | 251
  22h |###############               | 172
  23h |##############################| 341
```

