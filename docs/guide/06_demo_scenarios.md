# 6. Demo scenarios, outages and other cases

[Guide home](README.md) · back [5. Check it and use it](05_use.md) · next [7. Real hardware](07_live_hardware.md)

In the `demo` profile the `demo-replay` container stands in for the meter and
the inverter. It reads one recorded scenario from `tests/scenarios/output/`,
moves its timestamps to now, and sends it through exactly the same path as real
hardware, Kafka for the meter and the AnyLog MQTT broker for solar. Everything
after that, the database, the models, the engine and the dashboard, cannot tell
the difference. When a scenario ends it starts again.

## Pick a scenario

Set `DEMO_SCENARIO` in `.env`, then apply it.

```bash
docker compose up -d demo-replay
```

| scenario | what happens |
|---|---|
| `baseline_normal` | an ordinary afternoon, a heat pump run from minute 20 to 55 |
| `grid_outage_islanded` | the grid drops at minute 30 and the house runs on battery and solar |
| `full_blackout` | the grid is lost and the inverter trips, the meter goes dark |
| `generator_backup` | an outage at low battery, the generator starts at minute 25 |
| `psps_low_soc` | an evening public safety power shutoff with the battery at 35% |
| `meter_dropout` | the meter stops answering for 50 minutes while solar continues |
| `frozen_values` | one reading repeats for 50 minutes |
| `ct_sign_flip` | the panel sensors report negative power |
| `month_rollover` | data across a month boundary |
| `brownout_sag` | the utility voltage sags to about 105 V for 10 minutes |

Each folder also has an `expect.json` that says what the system should do, so a
test can check it. [`tests/scenarios/README.md`](../../tests/scenarios/README.md)
describes every case in detail.

## Play faster

`DEMO_SPEED=4` in `.env` plays four times faster. The appliance models expect
real time, so keep it at 1 when you want believable appliance results.

## Make your own

Scenarios are defined in `tests/scenarios/scenarios.yaml`. Add one, then
regenerate the files (needs Python 3.9 or newer and `pyyaml`).

```bash
cd tests/scenarios
python3 -m pip install pyyaml
python3 generate.py --list
python3 generate.py my_new_case
```

Next, [7. Real hardware](07_live_hardware.md).
