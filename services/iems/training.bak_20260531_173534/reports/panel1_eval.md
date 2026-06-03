# Panel 1 — Eval (held-out test split)

_Generated 2026-05-12T17:49:46+00:00_

Model: `services/iems/models/nilm_panel1_int8.onnx` (dynamic-quantized).
Test split: 4 days (2026-05-06, 05-07, 05-11, 05-12), stride=1.

## Accuracy

| head | valid windows | TP | FP | FN | TN | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `heat_pump` | 1729 | 23 | 417 | 2 | 1287 | 0.052 | 0.920 | **0.099** |
| `solar_pump` | 4961 | 0 | 1235 | 242 | 3484 | 0.000 | 0.000 | **0.000** |

### Confusion matrices

`heat_pump`:
```
              pred=0   pred=1
  actual=0     1287      417
  actual=1        2       23
```

`solar_pump`:
```
              pred=0   pred=1
  actual=0     3484     1235
  actual=1      242        0
```

## Latency (single window, Mac CPU)

| variant | avg ms / window |
|---|---:|
| FP32 ONNX | 0.336 |
| int8 dynamic quant | 0.360 |

Benchmark: 10000 iterations after 50-step warm-up. Provider: CPUExecutionProvider.

## Acceptance bars

| metric | target | actual | pass? |
|---|---:|---:|:--:|
| Heat pump F1 | ≥ 0.92 | 0.099 | ✗ |
| Solar pump F1 | ≥ 0.80 | 0.000 | ✗ |
| int8 latency ms / window | ≤ 1.5 | 0.360 | ✓ |

**Accuracy bars missed.** Per the task spec, do not wire this model into the live disaggregator. The real-time monitoring harness in Phase 8 explicitly does not touch production code and is the agreed next step to observe the model's response on the live stream.
