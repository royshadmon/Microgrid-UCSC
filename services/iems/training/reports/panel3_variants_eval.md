# Panel 3 — variant comparison

_Baseline BCE vs focal loss vs oversampling vs 2D appliance attention._
_All metrics on the held-out test split with per-head thresholds tuned on val._

## Macro-F1 summary

| variant | macro F1 @ 0.5 | macro F1 (tuned thr) | latency ms/window |
|---|---:|---:|---:|
| `baseline_bce` | 0.5208 | 0.4944 | 0.92 |
| `focal_loss` | 0.4766 | 0.4827 | 0.96 |
| `oversample` | 0.4928 | 0.5115 | 0.93 |
| `attention2d` | 0.4830 | 0.5020 | 0.89 |

## Per-head F1 (tuned threshold)

| head | test+ | baseline_bce | focal_loss | oversample | attention2d |
|---|---:|---:|---:|---:|---:|
| `refrigerator` | 2589 | 1.000 | 1.000 | 1.000 | 1.000 |
| `dishwasher` | 169 | 0.219 | 0.692 | 0.473 | 0.172 |
| `microwave` | 27 | 0.559 | 0.000 | 0.297 | 0.481 |
| `dryer` | 41 | 0.047 | 0.044 | 0.045 | 0.070 |
| `washing_machine` | 42 | 0.052 | 0.323 | 0.289 | 0.343 |
| `pressure_pump` | 4 | 0.273 | 0.000 | 0.004 | 0.100 |
| `computers` | 804 | 0.804 | 0.803 | 0.983 | 0.849 |
| `tv_stereo` | 254 | 1.000 | 1.000 | 1.000 | 1.000 |