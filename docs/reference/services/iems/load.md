# Load Folder

`services/iems/load/` — the Load domain (Adabi 5.3). Everything that reads panel power off the operator, turns it into per-appliance ON/OFF, watches for anomalies, and ranks what to shed first.

Two NILM paths coexist:

- The **LLM4NILM path** (`prompt_builder.py` → `disaggregator.py` → `llm_client.py` → `output_normalizer.py`) — slower, follows Xue et al. 2025, kept as an opt-in fallback.
- The **ONNX path** (`services/iems/inference/`) — production default, sub-100 ms per panel.

Both write into `nilm_disaggregated` through `anylog_query.insert_predictions()`.

---

## `anylog_query.py`

**Contents.** AnyLog REST client — every read and every write the IEMS pipeline does goes through this module. Zero `psycopg2`. Reads use raw socket SQL (no `destination` header so they run locally on the operator); writes use streaming PUT with `mode=streaming` and the `tsd_name`/`tsd_id` columns in slots 3–4. Partition discovery is cached for 60 s via `_get_partitions()`.

**Use in the system.** The single source of truth for "what does the meter say right now." Anything in `services/iems/` that needs a number from the operator imports something from here. The whole AnyLog gotchas list (parenthesized channel names, `run client ()` failures, `err_16` on streaming writes, NOW() unreliability) is encoded in this file's docstring and in `docs/anylog_query_cookbook.md`.

**Key surface.**
```python
fetch_channel(channel, start_iso, end_iso, ...)        # one channel time-window read
fetch_recent_window(channel, minutes=30)               # convenience wrapper
fetch_all_panels(start_iso, end_iso)                   # full snapshot for runner.py
fetch_all_panels_recent(minutes=30)
fetch_distinct_channels()                              # health check
insert_predictions(predictions, ...)                   # streaming PUT to nilm_disaggregated
resample_to_6s(rows)                                   # alignment helper before NILM
build_nilm_predictions(panel, appliance_states, ...)   # rows-for-PUT helper
health_check(anylog_url)                               # /iems/health
```

---

## `anomaly.py`

**Contents.** Three site-specific anomaly detectors, each returning an `Alert(severity, appliance, message, evidence)` or `None`:

- `detect_water_heater_dormancy()` — element failure / breaker / stuck solar-boiler; only fires when cold AND low irradiance, per `test_water_heater_dormancy_only_fires_when_cold_AND_low_irradiance`.
- `detect_pump_anomaly()` — pressure-pump cycling above 2× baseline (the plumbing-leak case proven at this site).
- `detect_phantom_dryer()` — dryer on 2–5 AM with no preceding wash cycle (HVAC/inverter trip protection, even if Dr. Mantey's ramp-up retrofit now mitigates the original failure mode).

`run_all_anomaly_checks()` runs all three and returns the non-None list.

**Use in the system.** The runner calls `run_all_anomaly_checks()` once per cycle; alerts are passed to `recommender.build_recommendations()` and emitted as urgent DSS cards. This is the domain-knowledge layer Adabi calls for in Chapter 5 — rules that the LLM/ONNX layer alone won't catch.

---

## `disaggregator.py`

**Contents.** The LLM4NILM per-panel pipeline (Xue et al. 2025). One entry point — `disaggregate_panel(panel, panel_rows, weather, ...)` — runs a sliding window over the resampled time series, calls the LLM via `llm_client`, normalizes each output through `output_normalizer.normalize()`, and returns a `DisaggregationResult(panel, states, latency_ms, model, ...)`.

**Use in the system.** Selected when `runner.run_iems_cycle(nilm_backend="ollama")`. Slow (5–60 s per panel) and prone to malformed JSON, so the ONNX path is default; this module is kept for ablation, fallback, and as the reference implementation for the LLM4NILM paper.

---

## `llm_client.py`

**Contents.** Plain HTTP wrappers around Ollama and llama.cpp (the OpenAI-compatible endpoint). Functions: `list_models`, `pull_model_stream`, `delete_model`, `show_model`, `call_chat`, `call_ollama`, `call_llama_cpp`, plus diagnostic helpers `diag_ping` and `test_model_latency`. Uses `urllib` only — no `requests` dependency.

**Use in the system.** Called by `disaggregator.py` during LLM4NILM cycles and by `iems_router.py` to surface Ollama's model list to the Remote-GUI model picker. `OLLAMA_URL` defaults to `http://host.docker.internal:11434` so the FastAPI container can reach the Mac-side Ollama daemon.

---

## `mobile_load.py`

**Contents.** Vacuum-cleaner cross-panel reconciliation. `reconcile_vacuum(panel_results, panel_power)` resolves the case where multiple panels' disaggregators independently emit `vacuum_cleaner_status=1` in the same window — it picks the one with the largest unattributed residual via `_pick_highest_residual()` and zeroes the others. `build_vacuum_records()` formats the result for `insert_predictions`.

**Use in the system.** Adabi's thesis flags the vacuum as the canonical mobile load — it walks from panel to panel and confuses any per-panel disaggregator. The runner pipes every panel's NILM dict through this module before persisting, so `nilm_disaggregated` has at most one ON vacuum row per timestamp.

---

## `output_normalizer.py`

**Contents.** Implements Xue et al. 2025 Section 4.3 — robustness handling for LLM disaggregator output. `normalize(raw_output, expected_fields, window_size, ...)`:

1. Tries `_parse_json()` (with a JSON-repair retry for trailing/missing braces).
2. Coerces every value to a binary list via `_to_binary_list()` (handles `"1"`, `true`, `1.0`, lists, scalars).
3. Pads/truncates to `window_size` with `_align_length()`.
4. Falls back to all-zeros with a warning when parsing fails entirely.

**Use in the system.** Sits between `llm_client.call_ollama` and `disaggregator.DisaggregationResult.states`. Without it, a single malformed JSON from the LLM kills the cycle; with it, the worst case is one window of zeros. Two of the test suite's 17 cases exercise the malformed-JSON and short-output paths.

---

## `prompt_builder.py`

**Contents.** Per-panel prompt construction. Three extensions over the LLM4NILM paper, called out in the file docstring:

1. Per-panel prompts — only the appliances in `CHANNELS[panel]["appliances"]` are included.
2. Weather context — injected for weather-coupled appliances (heat pump, water heater).
3. A `vacuum_cleaner_status` catch field on every panel.

Functions: `build_system_prompt(panel, weather)`, `build_user_message(panel, samples, ...)`, `get_panel_output_fields(panel)`, `build_disaggregation_prompt(...)`. Static templates live in `services/iems/prompts/`.

**Use in the system.** Called by `disaggregator.disaggregate_panel()` once per window. The output schema this module declares is what `output_normalizer` later validates against.

---

## `shedding.py`

**Contents.** Load-shedding ranking (Adabi 5.3). `rank_shed_candidates(states, target_reduction_w, mode)` returns a `ShedPlan(candidates, total_w, target_w)` where `candidates` are `ShedCandidate(appliance, power_w, shed_priority, panel, deferrable, reason, savings_dollars)` sorted by `shed_priority`. `CRITICAL_APPLIANCES` (refrigerator, pressure_pump, networking) are filtered out before ranking. `estimate_shed_savings_dollars()` prices the plan against `TOU_RATES`.

**Use in the system.** Called via `decision_support/shedding_bridge.py` from `recommender.py`, and directly by `runner.py` for the headline shed estimate in the cycle metadata. The test suite asserts that the dryer ranks first (`test_dryer_ranked_first_in_shed_priority`) and that critical appliances are never shed (`test_refrigerator_pump_networking_never_shed`).
