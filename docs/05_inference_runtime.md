# Inference runtime

`iems-inference` runs one tick every 30 s, three panels per tick, and writes on
every tick. On Pat's box that is 44 `nilm_disaggregated` rows a minute, measured
2026-09-08.

All line numbers in this document are from Pat's box.

## The loop

`inference/inference_loop.py`, 155 lines.

```python
TICK_SECONDS = 30      # line 25
WINDOW_MINUTES = 12    # line 26
```

Per tick.

```python
weather = get_weather()                                  # Open-Meteo
panel_rows = self._fetch_all_inputs()                    # 12-minute window, all panels
panel_rows[UTIL_CHANNEL] = fetch_channel(UTIL_CHANNEL, start, end)
solar = fetch_solar_snapshot(minutes=10)                 # Solar Assistant via AnyLog
for panel in PANEL_TO_MODEL.keys():
    r = disaggregate_panel_onnx(panel=panel, panel_rows=panel_rows,
                                weather=weather, write_to_anylog=write, solar=solar)
```

Every external call is individually caught. A failed utility tie fetch or a
failed solar snapshot degrades the tick rather than killing the loop, and a
failed panel logs and leaves the other two intact. `SIGINT` and `SIGTERM` set a
stop flag which is checked every 100 ms during the sleep, so a `docker stop`
takes well under a second.

The twelve minute fetch window against a hundred sample six second window, ten
minutes, is deliberate slack. It covers gaps in the meter feed without the
resampler having to extrapolate.

```bash
python -m iems.inference.inference_loop --tick 30
python -m iems.inference.inference_loop --once      # one pass, print JSON
```

Both `--tick` and `--window` are accepted and default to the constants above.

## Feature construction

`inference/feature_builder.py`, 238 lines.

The feature list, window and mid all come out of the norm file, so the builder
follows whatever the model was trained with rather than assuming. The norm file
that matters is the one **inside the `iems-inference` image**. On Pat's box the
running set is eighteen features, which adds `sun_elev`, `csky_ghi`, `pv_power`
and `pv_valid` to the fourteen. See `04_training_pipeline.md`.

```python
features = norm["features"]
window = int(norm["window"])
mid = int(norm.get("mid", window // 2))
mean = np.asarray(norm["mean"], dtype=np.float32)
std  = np.asarray(norm["std"],  dtype=np.float32)
```

`_resample_uniform` returns exactly `window` values on a `step_s` grid ending at
the newest available row, forward filling gaps and zero filling entirely missing
channels.

**Zero filling is a real failure mode, not a nicety.** On the dev Mac,
`egauge_kafka` died on 2026-07-23 and the inference loop kept running on zero
filled windows without erroring, producing confident output from nothing. The
tell is the `energy_readings` last process time in `get streaming`, not the
container status.

Diurnal features are built in local time.

```python
HOUSE_TZ = ZoneInfo("America/Los_Angeles")
BATTERY_WINDOW = (16, 21)
```

Training derives `tod_sin` and `tod_cos` and the battery window in local time, so
using UTC at inference would shift every diurnal feature by seven or eight hours.

Solar geometry is computed, not fetched, from a NOAA approximation and the
Haurwitz model at `_SITE_LAT, _SITE_LON = 37.2358, -121.9624`. `pv_power` and
`pv_valid` come from the live Solar Assistant snapshot when one is passed, and
`pv_valid=0` marks it absent, matching how the training archive encodes rows with
no measured PV.

## The ONNX pass

`inference/onnx_disaggregator.py`, 268 lines.

One session per panel, cached under a lock at process start, line 107. A new
model file therefore does not take effect until the container restarts, and
because nothing is bind mounted, a new model file means a rebuilt image.

Output naming is accepted in three forms, because three exporters have been used
over the life of the project, line 156.

```python
for _cand in ((f"prob_{head}",) if dual_head else (f"p_{head}", head)):
    if _cand in out_names:
        _idx = out_names.index(_cand); break
else:
    raise KeyError(f"model output for head {head!r} not found; "
                   f"available outputs: {out_names}")
```

It raises rather than defaulting, which is correct. A missing head silently
scored at zero would be indistinguishable from an appliance that is off.

### Measured panel watts

The most important twelve lines in the file, line 130.

```python
# Measured panel power = mean abs() of the most recent raw samples for THIS
# panel's own channel. These are REAL watts, used by the physics rules.
# (The de-normalized tensor value is NOT a physical watt: the feature builder
# applies a training-time transform, so a +300 W reading can de-normalize to
# a negative number. Reasoning on that misfires the gate/overshoot rules, so
# we read the raw samples instead.)
_own = panel_rows.get(panel, []) or []
for _r in _own[-30:]:
    _recent.append(abs(float(_r.get("w", 0) or 0)))
panel_w_meas = sum(_recent) / len(_recent)
```

Every physics rule downstream, the power gate, the Panel1 residual, the Panel2
2.5 kW gate, additive recovery and the overshoot trim, is denominated in
`panel_w_meas`. De-normalising the tensor instead would feed those rules a number
that is not a watt.

### Power estimate per head

```python
if dual_head and f"pow_{head}" in out_names:
    power_w = float(...) * 1000.0            # model regresses kW
else:
    power_w = float(APPLIANCE_NOMINAL_W.get(head, 100)) if state else 0.0
```

Single head models fall back to `APPLIANCE_NOMINAL_W` from `appliance_map.py`.
`additive=dual_head` in the `apply_rules` call means additive reconciliation only
runs when the model actually regresses power, since reconciling nominal constants
against measured watts would be arithmetic on placeholders.

## Gate and rule order at runtime

1. Raw probability against the per head threshold from the norm file baked into
   the `iems-inference` image. Those are the eighteen feature thresholds listed
   in `04_training_pipeline.md`.
2. `postprocess.apply_gates` with the **local** hour. Time of day exclusivity,
   the solar pump daylight gate, COLLAPSED heads forced to UNKNOWN, DEMOTED heads
   capped at 0.49 and reduced to MAYBE. Both `OFF` and `MAYBE` collapse to
   `state = 0`, and the reason survives in `preds[h]["flag"]`.
3. `rules_additive.apply_rules`. Panel1 weather reconciliation, mutual exclusion
   which is currently a no-op, battery charging annotation, house load
   annotation, the power gate, Panel2 water heater, then additive recovery and
   overshoot trim.

Full rule text is in `03_rules_engines.md`.

The local hour conversion is done explicitly and defaults to noon on failure,
line 178, because a wrong hour would silently invert every time of day gate.

## The write path

`_write_predictions`, line 226. One `nilm_disaggregated` row per head per tick,
so fourteen rows for Panel3 and four each for Panel1 and Panel2. That is 22 rows
per tick and 44 a minute at a 30 s tick, which matches the measured rate.

```python
ts_str = result.window_end_ts or result.midpoint_ts
```

Rows are stamped with the window **end**, not the midpoint, so the dashboard
reflects the freshest sample rather than something five minutes old.

| column | value |
|---|---|
| `ts` | window end |
| `circuit` | from `APPLIANCE_TO_PANEL`, so a head is attributed to its physical panel |
| `appliance` | head name |
| `state` | `ON` or `OFF` |
| `confidence` | the gated confidence, four decimals |
| `avg_w`, `median_w` | reconciled `power_w` if above zero, else the nominal, else 0.0 when OFF |
| `std_w` | standard deviation of the last thirty raw panel samples |
| `window_start`, `window_end`, `window_n` | provenance |

## AnyLog access

`load/anylog_query.py`, 488 lines. All reads and writes go through AnyLog REST.
There is no psycopg2 path.

Writes use streaming PUT.

```
headers: type=json, dbms=customers, table=<table>, mode=streaming
```

The table schema must carry `tsd_name CHAR(3)` and `tsd_id INT` as columns three
and four, after `row_id` and `insert_timestamp`, because AnyLog fills these
positionally. AnyLog then routes the row to the correct partition from
`insert_timestamp`.

Reads use local SQL with no destination header, so they run on the operator node.
Python computes absolute timestamps because AnyLog's `NOW()` is version
unreliable, and `_rewrite_now` handles the substitution. Responses are parsed
after stripping AnyLog's non-standard hex chunk size markers.

### Quirks the module works around

| quirk | workaround |
|---|---|
| `SELECT DISTINCT` returns the key `"DISTINCT col"` | use `GROUP BY` |
| `IN` and `LIKE` with parenthesised channel names return empty | fetch the whole time window and filter by `nm` client side |
| `destination: network` times out through Docker hairpin NAT from inside a container | never used on this path |
| `run client ()` returns an empty body over REST | TCP or CLI only |
| the parent table is empty, rows live in `par_*` partitions | partition discovery via `get partitions` |

Note the asymmetry, because it catches people. From **inside** a container,
`destination: network` hairpins and times out, which is why `anylog_query.py`
runs local SQL. From a shell on the host, `destination: network` is exactly the
header a SQL command needs, and without it AnyLog answers
`err_code 156, Wrong HTTP method used`.

### The partition cache

`_PARTITION_CACHE` is per process with **no TTL**. `_invalidate_partition_cache`
exists but nothing calls it on a schedule.

This caused a live outage on 2026-09-01. `iems-inference` had been up eight days,
so its cache still named the August partition, roughly 20 M rows, and
`fetch_distinct_channels` rescanned it on every loop. Postgres reached 166 percent
CPU with fourteen concurrent three minute scans of
`par_energy_readings_2026_08_m01_insert_timestamp`, the scans piled up faster than
they completed, and the operator's inserts were squeezed out. Ingestion crawled to
zero rows in 60 s while the producer kept publishing 960 messages a minute.

Restarting `iems-inference` cleared it and ingestion drained about eighteen
minutes of Kafka backlog at roughly 2,000 rows a minute.

**Every month boundary re-arms this** for any container up since before the
rollover. The old fourteen day partitions are still present on Pat's box and
still resolvable, which is what makes a stale cache return a plausible but wrong
answer rather than an error. The workaround in the deploy routine is to restart
`iems-backend` immediately after any dashboard deploy. The fix is a TTL or an
invalidation on partition change in `_get_partitions`, and it is still open.

## The on-demand path

`runner.run_iems_cycle()` is the single function every UI calls. It runs the same
disaggregation plus the generation, storage and decision support domains, and it
is what `POST /iems/cycle` triggers. A measured user path cycle on Pat's box
takes 9 to 12 s and moves `nilm_disaggregated` by about 36 rows.

## Reading a prediction

Given one `nilm_disaggregated` row, the questions in order.

1. Is the head COLLAPSED, meaning `water_heater` or `dishwasher`? Then the state
   came from `rules_additive`, never from the model, and the threshold in the
   norm file is irrelevant.
2. Is it DEMOTED, meaning `solar_pump` or `pressure_pump`? Then it can never be a
   firm ON and the DSS must not act on it.
3. What is `confidence` against the head's threshold in the norm file? Use the
   running table in `04_training_pipeline.md`, which is the one inside the
   `iems-inference` image. A 0.95 threshold head at 0.94 is an OFF that nearly
   fired.
4. Which rule decided it? The `rule` field distinguishes `model` from
   `heat_pump_recovery`, `water_heater_power_gate`, `additive_recovery`,
   `power_gate_off` and `overshoot_trim`.
5. Does `avg_w` come from a regression or from `APPLIANCE_NOMINAL_W`? If the
   model is single head it is the nominal, which is a constant, not a
   measurement.
