# Panel 1 — Rule labels (three heads)

_Generated 2026-05-12T18:00:20+00:00_

Heads: `heat_pump`, `solar_pump`, `vacuum_cleaner`. Rule-only; no LLM supervision. Heat-pump cycles mask the other two (their meters can't see a 100-W pump while the compressor draws 4 kW).

## Rule definitions

```
panel1_60s_mean = panel1_w.rolling('60s', min_periods=3).mean()
step            = panel1_w_step  (panel1_w − 30-min rolling min)
weather_demand  = outside_temp < 60 OR outside_temp > 75

heat_pump:
  1  if  panel1_60s > 1500 AND weather_demand
  0  if  panel1_w < 200
  drop->NaN if 1 and panel1_w ∉ [750, 6000]

solar_pump:
  1  if  40<step<300 AND irradiance>200 AND heat_pump!=1
  0  if  irradiance<50 OR step<10 OR panel1_w<30 OR step>300 OR heat_pump=1
  drop->NaN if 1 and panel1_w ∉ [100, 500]

vacuum_cleaner:
  1  if  500<step<1400 AND panel1_w<2000 AND heat_pump!=1
  0  if  step<100 OR panel1_w<100 OR heat_pump=1 OR step>1500
```

## Label counts — all data in parquet

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `heat_pump_label`      | 301996 | 2438 | 14052 | 285506 |
| `solar_pump_label`     | 301996 | 1466 | 18062 | 282468 |
| `vacuum_cleaner_label` | 301996 | 43 | 18800 | 283153 |

## Label counts — May 6 onward (recent slice)

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `heat_pump_label`      | 58251 | 312 | 3636 | 54303 |
| `solar_pump_label`     | 58251 | 429 | 7138 | 50684 |
| `vacuum_cleaner_label` | 58251 | 0 | 7341 | 50910 |

## Drops by power-consistency

- Heat pump rule positives dropped: **39**
- Solar pump rule positives dropped: **1**
