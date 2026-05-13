# Panel 2 — Eval (held-out test split, 4 heads)

_Generated 2026-05-13T04:51:38+00:00_

## Accuracy at threshold 0.5

| head | valid | TP | FP | FN | TN | P | R | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `water_heater` | 2988 | 0 | 0 | 0 | 2988 | 0.000 | 0.000 | **0.000** |
| `hair_dryer` | 2988 | 0 | 0 | 0 | 2988 | 0.000 | 0.000 | **0.000** |
| `sprinklers` | 2812 | 50 | 1116 | 1 | 1645 | 0.043 | 0.980 | **0.082** |
| `bath_lights` | 2652 | 0 | 0 | 2 | 2650 | 0.000 | 0.000 | **0.000** |

## Confusion matrices

`water_heater`:
```
              pred=0   pred=1
  actual=0     2988        0
  actual=1        0        0
```

`hair_dryer`:
```
              pred=0   pred=1
  actual=0     2988        0
  actual=1        0        0
```

`sprinklers`:
```
              pred=0   pred=1
  actual=0     1645     1116
  actual=1        1       50
```

`bath_lights`:
```
              pred=0   pred=1
  actual=0     2650        0
  actual=1        2        0
```

## Latency (single window, Mac CPU)

| variant | avg ms / window |
|---|---:|
| FP32 ONNX | 0.501 |
| int8 dynamic (MatMul-only) | 0.504 |

## Acceptance bars (per panel2 prompt)

| metric | target | actual | pass? |
|---|---:|---:|:--:|
| water_heater F1 | ≥ 0.90 | 0.000 | ✗ |
| hair_dryer F1 | ≥ 0.75 | 0.000 | ✗ |
| sprinklers F1 | ≥ 0.70 | 0.082 | ✗ |
| bath_lights F1 | ≥ 0.65 | 0.000 | ✗ |
| int8 latency ms | ≤ 2.5 | 0.504 | ✓ |
