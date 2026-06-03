# Panel 3 — Eval (held-out test split, 8 heads)

_Generated 2026-05-13T05:05:56+00:00_

## Accuracy at threshold 0.5

| head | valid | TP | FP | FN | TN | P | R | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `refrigerator` | 2589 | 2589 | 0 | 0 | 0 | 1.000 | 1.000 | **1.000** |
| `dishwasher` | 2865 | 129 | 904 | 40 | 1792 | 0.125 | 0.763 | **0.215** |
| `microwave` | 2723 | 26 | 40 | 1 | 2656 | 0.394 | 0.963 | **0.559** |
| `dryer` | 2971 | 33 | 1325 | 8 | 1605 | 0.024 | 0.805 | **0.047** |
| `washing_machine` | 2612 | 9 | 16 | 33 | 2554 | 0.360 | 0.214 | **0.269** |
| `pressure_pump` | 2500 | 3 | 15 | 1 | 2481 | 0.167 | 0.750 | **0.273** |
| `computers` | 1264 | 545 | 6 | 259 | 454 | 0.989 | 0.678 | **0.804** |
| `tv_stereo` | 1452 | 254 | 0 | 0 | 1198 | 1.000 | 1.000 | **1.000** |

## Confusion matrices

`refrigerator`:
```
              pred=0   pred=1
  actual=0        0        0
  actual=1        0     2589
```

`dishwasher`:
```
              pred=0   pred=1
  actual=0     1792      904
  actual=1       40      129
```

`microwave`:
```
              pred=0   pred=1
  actual=0     2656       40
  actual=1        1       26
```

`dryer`:
```
              pred=0   pred=1
  actual=0     1605     1325
  actual=1        8       33
```

`washing_machine`:
```
              pred=0   pred=1
  actual=0     2554       16
  actual=1       33        9
```

`pressure_pump`:
```
              pred=0   pred=1
  actual=0     2481       15
  actual=1        1        3
```

`computers`:
```
              pred=0   pred=1
  actual=0      454        6
  actual=1      259      545
```

`tv_stereo`:
```
              pred=0   pred=1
  actual=0     1198        0
  actual=1        0      254
```

## Latency (single window, Mac CPU)

| variant | avg ms / window |
|---|---:|
| FP32 ONNX | 1.235 |
| int8 dynamic (MatMul-only) | 1.041 |

## Acceptance bars (per panel3 prompt)

| metric | target | actual | pass? |
|---|---:|---:|:--:|
| refrigerator F1 | ≥ 0.85 | 1.000 | ✓ |
| dishwasher F1 | ≥ 0.65 | 0.215 | ✗ |
| microwave F1 | ≥ 0.55 | 0.559 | ✓ |
| dryer F1 | ≥ 0.85 | 0.047 | ✗ |
| washing_machine F1 | ≥ 0.65 | 0.269 | ✗ |
| pressure_pump F1 | ≥ 0.70 | 0.273 | ✗ |
| computers F1 | ≥ 0.55 | 0.804 | ✓ |
| tv_stereo F1 | ≥ 0.55 | 1.000 | ✓ |
| int8 latency ms | ≤ 4.0 | 1.041 | ✓ |
