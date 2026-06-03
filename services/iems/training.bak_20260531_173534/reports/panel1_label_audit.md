# Panel 1 — Label audit vs appliance spec

_Generated 2026-05-12T00:56:57+00:00_

## Appliance spec parsed from `appliance_data_updated.txt`

| appliance | on_threshold | min_w | max_w | source |
|---|---:|---:|---:|---|
| `heat_pump` | 300 | 1500 | 4000 | appliance_data_updated.txt |
| `solar_water_heater_pump` | 30 | 50 | 250 | default (file mentions appliance, no thresholds) |

## Raw Panel 1 coverage (egauge_kafka)

- First ts seen: `2026-04-21 18:17:23.000000`  
- Last ts seen: `2026-05-12 00:56:48.000000`

## `heat_pump`

- Sampled rows: **3433**  
- Date range: `2026-05-06 01:57:08+00:00` → `2026-05-11 23:16:08+00:00`  
- Label distribution: ON 0 (0.0%), OFF 3433

### Label-vs-power consistency

| check | count | of | % |
|---|---:|---:|---:|
| State=ON with `avg_w < 0.5 × min_w` (750W) [low FP] | 0 | 0 | 0.0% |
| State=ON with `avg_w > 1.5 × max_w` (6000W) [high FP] | 0 | 0 | 0.0% |
| State=OFF with `avg_w > 1.3 × on_threshold` (390W) [susp. FN] | 980 | 3433 | 28.5% |

### Diurnal ON histogram (hour-of-day, local time)

_No ON rows — diurnal histogram is empty._

### avg_w distribution (labeled rows)

| stat | value |
|---|---:|
| count | 3433.0 |
| mean | 1367.3 |
| std | 1985.8 |
| min | 98.8 |
| 10% | 100.0 |
| 50% | 230.6 |
| 90% | 4880.1 |
| max | 5249.1 |

### Coverage gap vs raw
- Days of raw data before first label: **14.3**  
- Days of raw data after last label: **0.1**

## `solar_water_heater_pump`

**No rows in `nilm_disaggregated` for `circuit='Panel1 (HVAC)'` and `appliance='solar_water_heater_pump'`.** The model can be trained only with alternative labels (e.g., rule-only). See consensus phase.

## Acceptance check

- **Solar water heater pump labels: ABSENT.** The Phase 1 stopping condition is triggered. Training will need a rule-only label path for this appliance (deferred to Phase 3 consensus design).
- Heat pump: **0 ON labels** in the sample. The label stream is calling the heat pump OFF in every window even when the panel is drawing well above the on-threshold. This is a different failure mode than the prompt's stated 25% FP cap — it is essentially 100% miss rate on the positive class. Surface for review before training.
