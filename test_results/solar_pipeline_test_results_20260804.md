# Solar-aware NILM pipeline — test results

Date: 2026-08-04

## Scope

Two suites, run in two places, after the solar-aware rules/inference changes
(`solar+eGauge` commit) were deployed live:

1. `services/iems/tests/test_pipeline_solar.py` — 11 `unittest` tests covering
   the solar-aware gating logic added to the NILM rules engine. Run on the Mac
   dev environment and, separately, inside the live `iems-inference` container
   on Pat's deployment (Python 3.11, real ONNX models, the actual deployed
   `rules_additive.py` / `onnx_disaggregator.py` / `anylog_query.py`).
2. `tests/test_iems.py` — the pre-existing 17-test pytest suite for the wider
   IEMS app (DSS, prompt builder, TOU classification, remote-gui plugin). Mac
   only; this suite and its `tests/` directory were never part of Pat's
   deployment tree or the `iems-inference` build context.

## 1. `test_pipeline_solar.py` — solar-aware inference

### Mac (dev)

```
PYTHONPATH=services .venv-training/bin/python3 -m unittest iems.tests.test_pipeline_solar -v
```

```
Ran 11 tests in 0.252s
OK
```

### Pat (live production, inside `iems-inference` container)

Test files were not present in Pat's deployment tree (only the four inference
source files had been deployed there previously, not `services/iems/tests/`).
Staged `__init__.py` + `test_pipeline_solar.py` into
`/home/pat/microgrid_manager/Microgrid-UCSC-dev_fin/services/iems/tests/`,
`docker cp`'d them into the already-running `iems-inference` container (no
restart, no interruption to the live 30s inference loop), then:

```
docker exec iems-inference python3 -m unittest iems.tests.test_pipeline_solar -v
```

```
Ran 11 tests in 0.082s
OK
```

Same 11/11 pass on both machines, against the actual deployed code (not a
mock/stub environment) on Pat's side.

### Test breakdown (11 tests, 5 classes)

| Class | Tests | Verifies |
|---|---|---|
| `TestMeasuredSolarGating` | 4 | `_low_solar` / `_battery_charging` prefer a measured `solar_data` snapshot (`pv_power`, `battery_power`) over the weather proxy when one is present; correct fallback to the irradiance/cloud-cover/time-window logic when a snapshot is absent. |
| `TestApplyRulesSolarThreading` | 3 | The `solar` snapshot threads correctly through `apply_rules`: the Panel1 solar pump recovers ON / gates OFF correctly off measured PV, and `battery_charging` / `house_load_w` are annotated onto the per-appliance output when solar data is present. |
| `TestSolarSnapshotParsing` | 2 | `fetch_solar_snapshot` (`anylog_query.py`) parses a live-shaped AnyLog row into the typed dict the rules engine expects, and returns `{}` (not an exception) when there is no row inside the lookback window. |
| `TestFeatureBuilder` | 1 | The `(1, 100, 14)` feature-window tensor shape and finiteness contract still holds. |
| `TestEndToEndDisaggregation` | 1 | A full Panel3 disaggregation cycle — real ONNX model + rules engine — with a synthetic solar snapshot, no writeback. |

Individual results (identical on both machines):

```
test_measured_battery_and_house_load_annotations (TestApplyRulesSolarThreading) ... ok
test_solar_pump_gated_off_when_pv_low (TestApplyRulesSolarThreading) ... ok
test_solar_pump_recovered_when_pv_high (TestApplyRulesSolarThreading) ... ok
test_panel3_full_cycle_with_solar (TestEndToEndDisaggregation) ... ok
test_window_tensor_shape_and_finite (TestFeatureBuilder) ... ok
test_battery_charging_measured_vs_fallback (TestMeasuredSolarGating) ... ok
test_falls_back_to_weather_without_solar (TestMeasuredSolarGating) ... ok
test_high_pv_overrides_overcast_weather (TestMeasuredSolarGating) ... ok
test_low_pv_overrides_sunny_weather (TestMeasuredSolarGating) ... ok
test_empty_returns_empty_dict (TestSolarSnapshotParsing) ... ok
test_parse_and_types (TestSolarSnapshotParsing) ... ok
```

This suite exists because the solar-aware gating logic had a real, silent
failure mode before it shipped: the original weather fallback read
`cloud = float(w.get("cloud_cover_pct", 100.0) or 100.0)`, which mapped a
legitimate `cloud_cover_pct=0` (clear sky) to `100` (full overcast), because
`0` is falsy in Python. `test_falls_back_to_weather_without_solar` caught
this before deployment. Fixed to an explicit `is not None` check.

## 2. `tests/test_iems.py` — application suite (Mac only)

```
PYTHONPATH=services .venv-training/bin/python3 -m pytest tests/ -v
```

```
17 passed in 0.10s
```

All 17 pre-existing tests pass unchanged (config, prompt builder, output
schema, anomaly rules, output normalizer, TOU classification, end-to-end
cycle, remote-gui plugin). None of these exercise the solar path directly —
they cover the app surfaces that were not touched by the solar+eGauge work —
so this run is a regression check, not new coverage.

### Environment note

The first attempt (`python3 -m pytest tests/ -v` against the system
interpreter) failed one test —
`test_iems_cycle_returns_all_four_domain_blocks` — with
`ModuleNotFoundError: No module named 'numpy'`. This was an environment
mismatch, not a code regression: the system Python has `pytest` but not the
project's `numpy`/`onnxruntime` stack, while `.venv-training` has the
opposite (numpy but no pytest, since the venv was set up for training
scripts, not test running). Installed `pytest` into `.venv-training` and
reran; all 17 passed. `.venv-training` now has `pytest` available going
forward.

## Conclusion

11/11 solar-aware tests pass identically on the Mac dev environment and on
Pat's live `iems-inference` container. 17/17 pre-existing app tests pass on
Mac, confirming no regression outside the solar path. No test failures were
attributable to the solar+eGauge code changes; the one failure encountered
was a missing-dependency artifact of running against the wrong Python
interpreter, resolved by installing the missing package into the correct
venv.
