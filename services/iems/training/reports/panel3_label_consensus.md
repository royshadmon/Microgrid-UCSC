# Panel 3 — Rule labels (eight heads)

_Generated 2026-06-01T01:31:58+00:00_

Heads: `refrigerator`, `dishwasher`, `microwave`, `dryer`, `washing_machine`, `pressure_pump`, `computers`, `tv_stereo`. Rule-only; no LLM supervision in this run. Starting point: `panel3_claude_code_prompt.md` §3.1 + §3.2 sequential constraint. Calibrated against 35 days of accumulated data for this house — mid-range heads (washer, pump, computers, TV) use a *baseline-step* formulation (`panel3_w − 30 min rolling minimum`) instead of raw power, because panel3 spends ~76% of time in the 200–500 W always-on baseline (fridge cycling + networking + idle computers) which would otherwise be tagged as appliance activity. Large clearly-separated signals (dryer, dishwasher) keep raw-power rules. Implementation: `services/iems/training/rule_engine.py`.

Data window: `2026-04-28 23:59:50+00:00` → `2026-06-01 01:28:30+00:00` (285653 rows on 10s grid; `panel3_w` observed on 84181 rows / 29.5%).

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
| `refrigerator` | 285653 | 37327 | 2168 | 246158 | 0.9451 |
| `dishwasher` | 285653 | 3882 | 76095 | 205676 | 0.0485 |
| `microwave` | 285653 | 252 | 76095 | 209306 | 0.0033 |
| `dryer` | 285653 | 725 | 81315 | 203613 | 0.0088 |
| `washing_machine` | 285653 | 3745 | 50132 | 231776 | 0.0695 |
| `pressure_pump` | 285653 | 0 | 66751 | 218902 | 0.0000 |
| `computers` | 285653 | 13587 | 16561 | 255505 | 0.4507 |
| `tv_stereo` | 285653 | 6168 | 46357 | 233128 | 0.1174 |

## Label counts — last 7 days

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `refrigerator` | 60481 | 15519 | 623 | 44339 |
| `dishwasher` | 60481 | 741 | 22983 | 36757 |
| `microwave` | 60481 | 57 | 22983 | 37441 |
| `dryer` | 60481 | 244 | 23986 | 36251 |
| `washing_machine` | 60481 | 943 | 15386 | 44152 |
| `pressure_pump` | 60481 | 0 | 20351 | 40130 |
| `computers` | 60481 | 3707 | 6015 | 50759 |
| `tv_stereo` | 60481 | 2049 | 13304 | 45128 |

## Contiguous ON-run length distribution (in 10s samples)

| head | runs | mean | p50 | p90 | max |
|---|---:|---:|---:|---:|---:|
| `refrigerator` | 469 | 79.6 | 23 | 204 | 1454 |
| `dishwasher` | 491 | 7.9 | 3 | 19 | 160 |
| `microwave` | 248 | 1.0 | 1 | 1 | 2 |
| `dryer` | 57 | 12.7 | 5 | 34 | 97 |
| `washing_machine` | 617 | 6.1 | 2 | 15 | 160 |
| `pressure_pump` | 0 | – | – | – | – |
| `computers` | 732 | 18.6 | 8 | 48 | 165 |
| `tv_stereo` | 411 | 15.0 | 6 | 43 | 103 |

## Diurnal histograms (positive-label counts by local hour)

### refrigerator
```
  00h |##########                    | 1238
  01h |##########                    | 1234
  02h |######                        | 780
  03h |#####                         | 700
  04h |######                        | 740
  05h |#####                         | 682
  06h |####                          | 465
  07h |########                      | 1036
  08h |########                      | 1070
  09h |#############                 | 1717
  10h |####################          | 2565
  11h |#####################         | 2725
  12h |##############################| 3890
  13h |######################        | 2873
  14h |################              | 2031
  15h |#############                 | 1747
  16h |#####################         | 2704
  17h |#################             | 2165
  18h |##########                    | 1241
  19h |########                      | 1068
  20h |#####                         | 678
  21h |###                           | 374
  22h |##############                | 1815
  23h |##############                | 1789
```

### dishwasher
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |##                            | 41
  04h |#                             | 22
  05h |##                            | 51
  06h |##########                    | 207
  07h |####                          | 79
  08h |#############                 | 259
  09h |##                            | 35
  10h |#########                     | 190
  11h |#                             | 22
  12h |#############                 | 277
  13h |#########                     | 188
  14h |####################          | 404
  15h |##############                | 282
  16h |##########                    | 197
  17h |##############################| 619
  18h |############################  | 569
  19h |####################          | 407
  20h |#                             | 26
  21h |                              | 0
  22h |                              | 0
  23h |                              | 7
```

### microwave
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |#                             | 2
  06h |                              | 1
  07h |                              | 0
  08h |#                             | 2
  09h |                              | 0
  10h |#                             | 4
  11h |#                             | 2
  12h |                              | 0
  13h |########                      | 25
  14h |###                           | 10
  15h |                              | 0
  16h |###                           | 11
  17h |##############################| 95
  18h |###################           | 59
  19h |#############                 | 41
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
  10h |#                             | 9
  11h |                              | 4
  12h |                              | 0
  13h |###########################   | 225
  14h |###########                   | 91
  15h |                              | 0
  16h |####                          | 32
  17h |######                        | 49
  18h |##############################| 253
  19h |#######                       | 62
  20h |                              | 0
  21h |                              | 0
  22h |                              | 0
  23h |                              | 0
```

### washing_machine
```
  00h |#########                     | 138
  01h |#####                         | 83
  02h |#                             | 20
  03h |                              | 1
  04h |###                           | 42
  05h |##                            | 26
  06h |                              | 7
  07h |####                          | 68
  08h |#####                         | 73
  09h |########                      | 124
  10h |############                  | 188
  11h |#####                         | 75
  12h |###########                   | 164
  13h |###################           | 291
  14h |######                        | 85
  15h |######                        | 93
  16h |###########################   | 418
  17h |#######################       | 360
  18h |##############################| 463
  19h |############################# | 450
  20h |########                      | 119
  21h |######################        | 342
  22h |#                             | 20
  23h |######                        | 95
```

### pressure_pump
```
  (no positive examples)
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
  07h |###                           | 150
  08h |########                      | 373
  09h |###############               | 666
  10h |#######################       | 1031
  11h |###########################   | 1215
  12h |############################  | 1269
  13h |#######################       | 1015
  14h |##############                | 627
  15h |###############               | 683
  16h |######################        | 966
  17h |###########################   | 1202
  18h |###################           | 867
  19h |##############################| 1347
  20h |############                  | 521
  21h |################              | 727
  22h |#####################         | 928
  23h |                              | 0
```

### tv_stereo
```
  00h |#############                 | 542
  01h |#################             | 713
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
  17h |##########                    | 395
  18h |##########                    | 413
  19h |#######                       | 269
  20h |#################             | 685
  21h |########################      | 978
  22h |#######################       | 932
  23h |##############################| 1241
```

