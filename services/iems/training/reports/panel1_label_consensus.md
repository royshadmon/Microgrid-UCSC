# Panel 1 — Rule labels (three heads)

_Generated 2026-06-01T01:31:57+00:00_

Heads: `heat_pump`, `solar_pump`. Rule-only; no LLM supervision. Heat-pump cycles mask the other two (their meters can't see a 100-W pump while the compressor draws 4 kW).

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
  0  if  irradiance<50 OR step<10 OR panel1_w<50 OR step>300 OR heat_pump=1
  drop->NaN if 1 and panel1_w ∉ [100, 500]
interlock: heat_pump forced 0 where solar_pump=1 (mutex)

  0  if  step<100 OR panel1_w<100 OR heat_pump=1 OR step>1500
```

## Label counts — all data in parquet

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `heat_pump_label`      | 285653 | 3397 | 53013 | 229243 |
| `solar_pump_label`     | 285653 | 3060 | 61154 | 221439 |

## Label counts — May 6 onward (recent slice)

| head | rows | pos (1) | neg (0) | NaN |
|---|---:|---:|---:|---:|
| `heat_pump_label`      | 225172 | 2220 | 41179 | 181773 |
| `solar_pump_label`     | 225172 | 2231 | 48065 | 174876 |

## Drops by power-consistency

- Heat pump rule positives dropped: **25**
- Solar pump rule positives dropped: **2**
