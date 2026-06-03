# Panel 1 — Label inventory

_Generated 2026-05-12T00:51:00+00:00_

## Partitions surveyed
- `par_nilm_disaggregated_2026_04_00_d14_insert_timestamp`: empty for circuit='Panel1 (HVAC)'
- `par_nilm_disaggregated_2026_04_01_d14_insert_timestamp`: empty for circuit='Panel1 (HVAC)'
- `par_nilm_disaggregated_2026_05_00_d14_insert_timestamp`: 6898 rows

## Per-appliance totals across partitions

| appliance | rows | on_rows | on_pct | first_ts | last_ts | avg_conf | avg_panel_w |
|---|---:|---:|---:|---|---|---:|---:|
| `blower_high` | 16 | 16 | 100.0% | 2026-03-22 20:41:49.000000 | 2026-03-23 06:42:43.000000 | 0.707 | 243.6 |
| `blower_low` | 16 | 16 | 100.0% | 2026-03-22 20:52:17.000000 | 2026-03-23 06:25:45.000000 | 0.934 | 130.5 |
| `heat_pump` | 3433 | 0 | 0.0% | 2026-05-06 01:57:08.000000 | 2026-05-11 23:16:08.000000 | 0.750 | 1367.3 |
| `vacuum_cleaner` | 3433 | 0 | 0.0% | 2026-05-06 01:57:08.000000 | 2026-05-11 23:16:08.000000 | 0.750 | 1367.3 |

## Summary

Panel 1 carries 4 labeled appliance keys across 1 active partitions for 6898 total rows.

**Warning:** No `solar_water_heater_pump` (or `solar_pump`) appliance key is present in the labels. Phase 1 acceptance condition requires explicit treatment of this gap before training.
