# Tests Folder

`tests/` — the pytest suite. Run from the repo root with `services/` on the path. There is a second, separate unittest suite for the solar-aware inference path at `services/iems/tests/test_pipeline_solar.py` (below).

```bash
PYTHONPATH=services pytest tests/ -v
```

```
tests/
├── __init__.py
├── conftest.py       # puts services/ on sys.path
└── test_iems.py      # 17 tests covering all four domains
```

## `conftest.py`

Two-line shim — prepends `services/` to `sys.path` so the suite can import `iems.config`, `iems.load.*`, `iems.decision_support.*`, etc. without an editable install:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))
```

The same lines appear at the top of `test_iems.py` so any one test can also be run standalone.

## `test_iems.py`

17 unit tests, grouped by domain. Each test is a single assertion about a contract that the rest of the project depends on — they exist to catch regressions in the runtime path, not to test for coverage.

### Configuration (3 tests)

- `test_no_ev_charger_anywhere` — `APPLIANCES` and every `CHANNELS[panel]["appliances"]` must be EV-free (site doesn't have one; an early bug populated it everywhere).
- `test_dryer_ranked_first_in_shed_priority` — `APPLIANCES["dryer"]["shed_priority"] == 1` and peak power ≥ 7000 W; no other deferrable appliance may outrank it.
- `test_refrigerator_pump_networking_never_shed` — runs `rank_shed_candidates` with all critical loads ON and asserts none appear in the plan.

### Prompt builder (3 tests)

- `test_panel2_prompt_lists_water_heater_AND_hair_drier_AND_sprinklers` — Panel2's system prompt enumerates the right appliances.
- `test_solar_boiler_note_present_in_water_heater_prompt` — the solar-boiler context note survives prompt assembly (it's what makes water-heater dormancy detection meaningful).
- `test_weather_context_injected_when_panel1_or_panel2` — weather block is injected for HVAC/H2O panels and omitted for the others.

### Output schema (1 test)

- `test_vacuum_cleaner_field_present_in_every_panel_output_schema` — the mobile-load catch field (`vacuum_cleaner_status`) is on every panel's output schema. Reconciliation in `mobile_load.reconcile_vacuum` depends on this.

### Anomalies (2 tests)

- `test_pump_anomaly_fires_above_2x_baseline_cycles` — pump cycling alert triggers at ≥2× baseline.
- `test_water_heater_dormancy_only_fires_when_cold_AND_low_irradiance` — both conditions are required (cold weather alone isn't enough when the solar boiler can carry the load).

### Output normalizer (2 tests)

- `test_output_normalizer_handles_malformed_json` — degrades to all-zeros without raising.
- `test_output_normalizer_pads_short_output` — short LLM outputs get padded to `window_size`.

### TOU / Generation (2 tests)

- `test_tou_classify_peak_summer_weekday` — PG&E summer peak window classification.
- `test_tou_classify_off_peak_winter_weekend` — weekend off-peak in winter.

### End-to-end (1 test)

- `test_iems_cycle_returns_all_four_domain_blocks` — `run_iems_cycle()` returns a result that has Load, Generation, Storage, and DSS blocks all populated. This is the smoke test for the orchestrator.

### Remote-GUI plug-in (3 tests)

- `test_remote_gui_feature_registers_in_nav` — the IEMS feature is registered in the Remote-GUI feature config (see `docs/services/remote_gui/FEATURE_CONFIG_README.md`).
- `test_ollama_model_list_proxy` — `/iems/models` round-trip through `llm_client.list_models`.
- `test_mobile_vacuum_reconciliation_resolves_conflict` — when two panels both claim the vacuum, only the larger-residual panel keeps it.

## `services/iems/tests/test_pipeline_solar.py`

A second, separate suite covering the solar-aware NILM inference path added
alongside the Solar Assistant integration. Uses stdlib `unittest` (not
pytest) since the training venv doesn't have pytest installed:

```bash
cd ~/microgrid-manager
PYTHONPATH=services .venv-training/bin/python3 -m unittest iems.tests.test_pipeline_solar -v
```

```
services/iems/tests/
├── __init__.py
└── test_pipeline_solar.py    # 11 tests, five groups
```

11 tests grouped by concern:

- **`TestMeasuredSolarGating`** (4 tests) — `_low_solar`/`_battery_charging`
  prefer a measured `solar_data` snapshot (`pv_power`, `battery_power`) over
  the weather proxy when one is present, and fall back to the
  irradiance/cloud-cover/time-window logic when it isn't.
- **`TestApplyRulesSolarThreading`** (3 tests) — the `solar` snapshot threads
  correctly through `apply_rules`: the solar pump recovers/gates off with
  measured PV, and `battery_charging` / `house_load_w` get annotated onto
  the per-appliance output when solar data is present.
- **`TestSolarSnapshotParsing`** (2 tests) — `fetch_solar_snapshot` in
  `anylog_query.py` parses a live AnyLog row into the typed dict the rules
  engine expects, and returns `{}` (not an exception) when there's no
  recent row.
- **`TestFeatureBuilder`** (1 test) — the `(1, 100, 14)` feature-window
  tensor shape and finiteness contract still holds.
- **`TestEndToEndDisaggregation`** (1 test) — a full Panel3 disaggregation
  cycle (real ONNX model + rules) with a synthetic solar snapshot, no
  writeback.

This suite exists because the solar-aware gating logic has an easy silent
failure mode: a falsy-zero bug in the original weather fallback (`cloud=0`,
i.e. clear sky, was being read as `cloud=100`, full overcast) was caught by
`TestMeasuredSolarGating` before it shipped. Run it whenever
`rules_additive.py`, `onnx_disaggregator.py`, `inference_loop.py`, or
`anylog_query.py`'s solar path changes.

## Use in the project

Every regression that's bitten the runtime — silent EV charger in the panel mapping, dryer demoted in shed priority, malformed JSON from the LLM crashing a cycle, vacuum being double-attributed across panels, a clear-sky reading misread as overcast in the solar gating fallback — has a test here. CI doesn't exist on this repo yet, so both suites are run by hand before each merge to `dev_fin`. The conventional invocations:

```bash
cd ~/microgrid-manager
PYTHONPATH=services pytest tests/ -v
PYTHONPATH=services .venv-training/bin/python3 -m unittest iems.tests.test_pipeline_solar -v
```

Both suites are fast (no AnyLog or Ollama calls — anything that would hit the network is either stubbed or tests pure config / pure-function behavior, and the one end-to-end test loads the ONNX model directly without a live AnyLog round trip), so there's no reason to skip either.
