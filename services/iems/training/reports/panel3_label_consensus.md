# Panel 3 — Rule labels (eight heads)

_Generated 2026-05-18T20:59:48+00:00_

Heads: `refrigerator`, `dishwasher`, `microwave`, `dryer`, `washing_machine`, `pressure_pump`, `computers`, `tv_stereo`. Rule-only; no LLM supervision in this run. Starting point: `panel3_claude_code_prompt.md` §3.1 + §3.2 sequential constraint. Calibrated against 35 days of accumulated data for this house — mid-range heads (washer, pump, computers, TV) use a *baseline-step* formulation (`panel3_w − 30 min rolling minimum`) instead of raw power, because panel3 spends ~76% of time in the 200–500 W always-on baseline (fridge cycling + networking + idle computers) which would otherwise be tagged as appliance activity. Large clearly-separated signals (dryer, dishwasher) keep raw-power rules. Implementation: `services/iems/training/rule_engine.py`.

Data window: `2026-04-28 23:59:50+00:00` → `2026-05-18 20:59:10+00:00` (171717 rows on 10s grid; `panel3_w` observed on 31121 rows / 18.1%).

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
| `refrigerator` | 171717 | 8557 | 422 | 162738 | 0.9530 |
| `dishwasher` | 171717 | 2023 | 26973 | 142721 | 0.0698 |
| `microwave` | 171717 | 175 | 26973 | 144569 | 0.0064 |
| `dryer` | 171717 | 362 | 29721 | 141634 | 0.0120 |
| `washing_machine` | 171717 | 1609 | 16683 | 153425 | 0.0880 |
| `pressure_pump` | 171717 | 0 | 22835 | 148882 | 0.0000 |
| `computers` | 171717 | 5197 | 4086 | 162434 | 0.5598 |
| `tv_stereo` | 171717 | 1771 | 17654 | 152292 | 0.0912 |

## Label counts — last 7 days

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `refrigerator` | 60481 | 5287 | 227 | 54967 |
| `dishwasher` | 60481 | 628 | 10701 | 49152 |
| `microwave` | 60481 | 37 | 10701 | 49743 |
| `dryer` | 60481 | 33 | 11521 | 48927 |
| `washing_machine` | 60481 | 835 | 7000 | 52646 |
| `pressure_pump` | 60481 | 0 | 9142 | 51339 |
| `computers` | 60481 | 2054 | 1805 | 56622 |
| `tv_stereo` | 60481 | 881 | 5814 | 53786 |

## Contiguous ON-run length distribution (in 10s samples)

| head | runs | mean | p50 | p90 | max |
|---|---:|---:|---:|---:|---:|
| `refrigerator` | 88 | 97.2 | 22 | 331 | 960 |
| `dishwasher` | 279 | 7.3 | 3 | 18 | 160 |
| `microwave` | 171 | 1.0 | 1 | 1 | 2 |
| `dryer` | 28 | 12.9 | 7 | 25 | 79 |
| `washing_machine` | 310 | 5.2 | 2 | 10 | 148 |
| `pressure_pump` | 0 | – | – | – | – |
| `computers` | 285 | 18.2 | 7 | 49 | 150 |
| `tv_stereo` | 122 | 14.5 | 7 | 38 | 77 |

## Diurnal histograms (positive-label counts by local hour)

### refrigerator
```
  00h |####                          | 204
  01h |##                            | 90
  02h |#                             | 27
  03h |#                             | 25
  04h |#                             | 47
  05h |#                             | 59
  06h |#                             | 24
  07h |##                            | 78
  08h |#######                       | 342
  09h |########                      | 397
  10h |#################             | 827
  11h |##################            | 869
  12h |##############################| 1419
  13h |########################      | 1116
  14h |##########                    | 455
  15h |######                        | 282
  16h |###########                   | 543
  17h |#######                       | 320
  18h |########                      | 390
  19h |#######                       | 326
  20h |                              | 0
  21h |                              | 0
  22h |########                      | 357
  23h |########                      | 360
```

### dishwasher
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |#######                       | 76
  07h |                              | 1
  08h |########                      | 98
  09h |#                             | 7
  10h |#############                 | 150
  11h |#                             | 9
  12h |#######                       | 85
  13h |##########                    | 118
  14h |############################  | 330
  15h |###################           | 224
  16h |#####                         | 63
  17h |#########################     | 295
  18h |##############################| 349
  19h |##################            | 209
  20h |#                             | 6
  21h |                              | 0
  22h |                              | 0
  23h |                              | 3
```

### microwave
```
  00h |                              | 0
  01h |                              | 0
  02h |                              | 0
  03h |                              | 0
  04h |                              | 0
  05h |                              | 0
  06h |                              | 1
  07h |                              | 0
  08h |                              | 1
  09h |                              | 0
  10h |                              | 0
  11h |                              | 0
  12h |                              | 0
  13h |###########                   | 24
  14h |#                             | 3
  15h |                              | 0
  16h |##                            | 5
  17h |##############################| 64
  18h |#####################         | 44
  19h |###############               | 33
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
  13h |#######################       | 121
  14h |##                            | 12
  15h |                              | 0
  16h |                              | 0
  17h |######                        | 32
  18h |##############################| 157
  19h |########                      | 40
  20h |                              | 0
  21h |                              | 0
  22h |                              | 0
  23h |                              | 0
```

### washing_machine
```
  00h |##                            | 21
  01h |#                             | 11
  02h |                              | 0
  03h |                              | 0
  04h |##                            | 20
  05h |                              | 0
  06h |                              | 0
  07h |                              | 2
  08h |####                          | 39
  09h |######                        | 67
  10h |#####                         | 55
  11h |###                           | 37
  12h |####                          | 41
  13h |###########                   | 117
  14h |####                          | 45
  15h |##                            | 21
  16h |##############                | 150
  17h |###############               | 159
  18h |##############################| 322
  19h |##################            | 189
  20h |                              | 4
  21h |###########################   | 294
  22h |#                             | 12
  23h |                              | 3
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
  07h |#                             | 17
  08h |######                        | 149
  09h |###########                   | 273
  10h |###############               | 369
  11h |########################      | 597
  12h |##############################| 744
  13h |################              | 393
  14h |####                          | 105
  15h |#########                     | 219
  16h |####################          | 502
  17h |#############                 | 323
  18h |##############                | 349
  19h |###############               | 373
  20h |#                             | 21
  21h |##############                | 349
  22h |#################             | 414
  23h |                              | 0
```

### tv_stereo
```
  00h |###########                   | 164
  01h |######                        | 96
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
  17h |#######                       | 100
  18h |##########                    | 149
  19h |####                          | 61
  20h |################              | 243
  21h |##############################| 450
  22h |#############                 | 194
  23h |#####################         | 314
```

