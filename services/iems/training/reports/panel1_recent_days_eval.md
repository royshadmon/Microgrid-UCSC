# Panel 1 — Retrained model output on recent days

_Generated 2026-05-12T17:49:47+00:00_

Model: `nilm_panel1_int8.onnx` (retrained 2026-05-12). Thresholds: HP=0.68, SP=0.53.

Day boundaries are UTC. Windows are dense (stride=1) so each prediction corresponds to one 10-second midpoint.

## Yesterday — 2026-05-11 UTC

_27 feature-valid rows but no contiguous 100-row runs._

## Today — 2026-05-12 UTC

- Feature-valid rows: **2158**  
- Eval windows (stride=1, contiguous): **1712**  
- Window timespan: `2026-05-12 00:55:20+00:00` → `2026-05-12 17:40:10+00:00`

### Per-head metrics vs rule labels

| head | valid windows | TP | FP | FN | TN | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| heat_pump | 23 | 0 | 0 | 0 | 23 | 0.000 | 0.000 | **0.000** |
| solar_pump | 1602 | 0 | 194 | 185 | 1223 | 0.000 | 0.000 | **0.000** |

### Predicted-state behavior (independent of rule labels)

| head | predicted ON ticks | predicted OFF | off→on | on→off |
|---|---:|---:|---:|---:|
| heat_pump | 198 (11.6%) | 1514 | 1 | 0 |
| solar_pump | 194 (11.3%) | 1518 | 1 | 0 |

### Probability distribution

`heat_pump` (threshold 0.68):
- min=0.240  p10=0.245  p50=0.249  p90=0.733  max=0.743

`solar_pump` (threshold 0.53):
- min=0.318  p10=0.320  p50=0.323  p90=0.538  max=0.550

### Predicted ON-rate by local hour (PT)

| hour | HP ON / total | SP ON / total |
|---:|---:|---:|
| 00 | 87 / 94 | 83 / 94 |
| 10 | 111 / 111 | 111 / 111 |
| 17 | 0 / 28 | 0 / 28 |
| 18 | 0 / 282 | 0 / 282 |
| 19 | 0 / 158 | 0 / 158 |
| 20 | 0 / 200 | 0 / 200 |
| 21 | 0 / 119 | 0 / 119 |
| 22 | 0 / 360 | 0 / 360 |
| 23 | 0 / 360 | 0 / 360 |

### Raw signals at midpoint (for cross-check)

- `panel1_w` midpoint values: min=179W max=394W mean=301W
- `panel1_w_step` midpoint: min=0W max=141W mean=16W
- `irradiance` midpoint: min=0 max=655 mean=126 W/m²

