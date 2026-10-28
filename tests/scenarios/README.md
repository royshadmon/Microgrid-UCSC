# IEMS dummy test scenarios

Synthetic data for exercising the IEMS pipeline under power outages and other
failure cases, kept separate from the live deployment and from real site data.
Nothing here is wired into Pat's box yet. This folder is the starting point for
the next development step.

## What is here

| file | purpose |
|---|---|
| `scenarios.yaml` | every scenario, its timed events and the behaviour the system is expected to show |
| `generate.py` | writes CSVs shaped like the live `energy_readings` and `solar_data` tables |
| `output/<scenario>/` | `energy_readings.csv`, `solar_data.csv`, `expect.json` |

```
python3 generate.py --list
python3 generate.py                          # all scenarios
python3 generate.py grid_outage_islanded     # one scenario
```

Requires Python 3.9 or newer and `pyyaml`.

## Scenarios

| scenario | what happens | what it should catch |
|---|---|---|
| `baseline_normal` | ordinary afternoon, heat pump runs 20 to 55 min | reference for every other case |
| `grid_outage_islanded` | utility drops at 30 min, house islands on battery and PV | readiness, DSS deferral, Ask reporting islanding |
| `full_blackout` | grid lost and inverter trips, meter goes dark | NILM must not keep emitting frozen predictions, gap watchdog |
| `generator_backup` | outage at low SOC, Generac starts at 25 min | generator channel, load shedding |
| `psps_low_soc` | evening shutoff with the battery at 35% | readiness before the shutoff, pre charge advice |
| `meter_dropout` | eGauge stops answering for 50 min, solar continues | the exact failure seen 2026-10-16 to 2026-10-26 |
| `frozen_values` | producer republishes one reading for 50 min | stale feed detection |
| `ct_sign_flip` | subpanel CTs report negative watts | NILM output identical to baseline, since features use absolute values |
| `month_rollover` | runs across the UTC month boundary | truncated partition fault seen 2026-09-01 and 2026-10-01 |
| `brownout_sag` | utility sags to about 105 V for 10 min | undervoltage flag, no spurious ON events |

## Conventions

Timestamps are UTC, matching storage. Display layers convert to Pacific.
Channel names match the live eGauge channels exactly. Battery power is positive
while charging in this generator. Confirm that sign against the live Solar
Assistant feed before asserting on it. The household loads are simple shapes
(fridge 15 minutes on in every 40, heat pump 3.2 kW, PV from a sun elevation
curve on a 6.2 kW array) and are not fitted to the real house.

## Next steps

Replay into a scratch AnyLog operator or a throwaway Postgres schema, never the
live `customers` database. Then drive `inference_loop`, the gap watchdog, the
readiness rules and the DSS against each scenario and assert on `expect.json`.
