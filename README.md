# Microgrid IEMS — Residential NILM + Intelligent Energy Management

Real-time, appliance-level energy disaggregation (NILM) and decision support for a
single residence (Los Gatos, CA), built as a UCSC research project. Live power is
streamed from an eGauge meter, normalized through a distributed AnyLog/PostgreSQL
time-series layer, disaggregated into per-appliance ON/OFF states by per-panel neural
models reconciled with a physics rules engine, and surfaced on live dashboards.

The system is grounded in Adabi (2016, UCSC PhD — four-domain IEMS: User, Load,
Generation, Storage), with NILM design informed by Hart (1992, event detection),
Xiong et al. (2023, MATNilm), and Xue et al. (2025, LLM4NILM, evaluated and rejected
for latency/instability).

---

## 1. Data pipeline (streaming)

```
 eGauge 18646  ──>  Kafka  ──>  AnyLog operator  ──>  PostgreSQL
 (16 channels)   (egauge-      (REST :32149,         (egauge_kafka,
                  energy)       TCP :32148)            nilm_disaggregated)
                                     ▲
 Solar Assistant ────────────────────┘             (solar_data: pv_power,
 (MQTT, Pat's Pi)  AnyLog broker (msg client,        battery_power, battery_soc,
                    port 1883) or REST streaming     grid_power, load_power,
                                                      device_mode)
                                     │
                                     ▼
                         ONNX inference loop (host)
                         every ~30 s: fetch window + solar snapshot -> models -> rules
                                     │
                                     ▼  writes one row / appliance / window
                            nilm_disaggregated  ──>  Dashboards
                                                     - Node  :47821
                                                     - React :3001  (FastAPI :8000)
```

- **Solar Assistant (`streaming/solar-pipeline/solar_producer.py`):** subscribes to the Solar
  Assistant Mosquitto broker on Pat's LAN and forwards one row per interval into AnyLog's
  `customers.solar_data` table. Two ingestion modes (`INGEST_MODE` env var): `broker` (default)
  publishes into AnyLog's own MQTT broker via `run msg client`, which maps topic fields straight
  to columns; `rest` streams directly via REST PUT. This is the measured PV/battery/grid/load
  source the rules engine (Section 3) prefers over the derived/weather-based estimate.

- **eGauge channels (16):** `Grid Power` (signed, +import/-export), `Generac Power`,
  `Panel1 (HVAC)`, `Panel2 (H2O)`, `Panel3 (Kitchen)`, `Shop`, plus per-leg Vrms / I / F
  diagnostics. There is **no PV channel on the eGauge** (solar is derived from its
  energy balance) and **no EV charger**; measured solar/battery telemetry instead comes
  from Solar Assistant via `solar_data` (see above) once ingestion has run.
- **Panels (physical install):**
  - Panel1 (HVAC): heat pump (~1.5-4 kW, ~550 W fan-only sub-state) and the solar
    thermal circulation pump (~150 W). The two are mutually exclusive (interlocked).
  - Panel2 (H2O): solar-thermal-assisted electric water heater (~2-4 kW bursts),
    bathrooms, outdoor outlets, master-bath incandescent lights.
  - Panel3 (Kitchen): refrigerator/freezer, dishwasher, microwave, cooktop, TV/stereo,
    computers, and the former shop loads (clothes washer, dryer, water pressure pump).
- **Battery:** a real 2009 lead-acid deep-cycle bank (~13.5 kWh). It is **not metered**;
  SOC is modeled and charged from derived solar surplus (10% floor).
- **Solar:** derived by energy balance, `Solar = max(0, (|P1|+|P2|+|P3|+|Shop|) - GridNet - Generac)`.

### AnyLog query constraints (hard-won)
- Query **partition tables directly** (e.g. `par_egauge_kafka_2026_06_00_d14_insert_timestamp`),
  never the parent table.
- Use `127.0.0.1`, not `localhost` (macOS resolves localhost to IPv6; Docker binds IPv4).
- Channel names with parentheses (`Panel1 (HVAC)`) silently return empty in `WHERE`
  predicates — fetch by time window and filter client-side.
- The streaming write contract for `nilm_disaggregated` is a PUT to `:32149` with headers
  `type:json, dbms:customers, table:nilm_disaggregated, mode:streaming`; the NDJSON payload
  must exclude `insert_timestamp` and match the schema column order exactly.

---

## 2. The models

Three independent neural models, **one per sub-panel**, exported to ONNX for ~5-25 ms CPU
inference. NILM is treated as **multi-label** (each appliance head is an independent binary
classifier), not multi-class.

### 2.1 Active models — BiLSTM (the working backbone)
- **Files:** `services/iems/models/nilm_panel{1,2,3}.onnx` (+ `_int8` variants).
- **Input:** `(batch, 100, 12)` — a 10-minute window at 6-second resolution, 12 features:
  `panel1_w, panel2_w, panel3_w, shop_w, outside_temp, irradiance, hour_sin, hour_cos,
  dow_sin, dow_cos, utility_tie_current, panel{N}_w_step`. Normalized with the per-panel
  mean/std stored in `panel{N}_norm_bilstm.json`.
- **Architecture:** stacked bidirectional LSTMs per head; the final hidden state feeds an
  MLP ending in a sigmoid, giving a per-appliance probability `p`. `state = ON if p >= threshold`.
- **Heads:** Panel1 `{heat_pump, solar_pump}`; Panel2 `{water_heater, hair_dryer, sprinklers,
  bath_lights}`; Panel3 `{refrigerator, dishwasher, microwave, dryer, washing_machine,
  pressure_pump, computers, tv_stereo}` (14 appliances total across the 3 panels).
- **Per-head thresholds** (`panel{N}_norm_bilstm.json["thresholds"]`) are tuned, not fixed at
  0.5: always-on / weak-signature loads (refrigerator, washing_machine, computers) use ~0.05
  for recall; the rest are lowered for sensitivity and gated by physics (Section 3). Panel3 is
  production-grade (refrigerator/TV F1 near 1.0); **Panel1 and Panel2 are weak** (limited
  labeled data, class imbalance) and lean heavily on the rules layer.
- **Training (`services/iems/training/`):** labels come from the rule engine (`{0,1,NaN}`,
  NaN = ambiguous, masked from loss); masked weighted BCE with per-head `pos_weight =
  n_neg/n_pos` to counter imbalance; AdamW (lr 1e-3, wd 1e-4), batch 256, early stopping on
  macro-F1. Window builders: `windows_panel{N}.py`; label builders: `labels_panel{N}.py`,
  `rule_engine.py`; threshold tuning: `tune_thresholds*.py`.

### 2.2 MATNilm — present but disabled
- **Files:** `services/iems/models/nilm_panel{1,2,3}_matnilm.{onnx,pt}`,
  `panel{N}_norm.json` (13 features, adds `battery_window`), dual-head (`prob_*` + `pow_*`).
- **Status:** trained but **collapsed** — they learned the per-appliance prior and ignore the
  input (a +-2 sigma change in panel power moves the output by <0.001). The active path was
  reverted to BiLSTM. The MATNilm files are retained for reference / future retraining.
- To switch models, edit `PANEL_TO_MODEL` in `services/iems/inference/appliance_map.py`
  (the `onnx` + `norm` paths). The disaggregator auto-detects dual-head models by `prob_*`
  output names.

---

## 3. The rules-based system

A physics/weather reconciliation layer (`services/iems/inference/rules_additive.py`) runs on
the model output every window, encoding domain facts the networks are not guaranteed to honor
on weak data. Each appliance carries a `rule` tag showing which rule decided its state. The
measured per-panel power used by the rules is the **mean of the raw panel samples** (real
watts), not the de-normalized model feature.

Order of operations (`apply_rules`):
1. **Panel1 solar/weather rules** (`apply_panel1_rules`): the solar circulation pump only runs
   when there is sun to circulate. When a recent `solar_data` snapshot exists
   (`fetch_solar_snapshot`, Section 1), gating uses **measured** `pv_power` (< 200 W =>
   confidently OFF) in place of the weather proxy; otherwise it falls back to
   `irradiance_6h_avg`/`cloud_cover_pct`/daylight. The heat pump is reconciled from live
   Panel1 watts vs its band (incl. the ~550 W fan-only sub-state).
2. **Mutual exclusion**: at most one of `{heat_pump, solar_pump}` ON (highest confidence wins).
3. **Battery charging** flag: measured `battery_power >= 50 W` from `solar_data` when
   available, else the fixed 16:00-21:00 local charging-window fallback. When solar data is
   present the tick also annotates each appliance with the measured `house_load_w`
   (`solar_data.load_power`).
4. **Power gate** (anti-false-positive): an appliance cannot be ON if its panel draws less than
   that appliance alone needs. This is what makes low thresholds safe on the weak panels — an
   idle panel can never light up.
5. **Panel2 water-heater rule** (`apply_panel2_rules`, cross-panel): solar-thermal fallback —
   when the solar pump is confidently OFF (low solar), the electric water heater is the hot-water
   source; it fires only when Panel2 is actually drawing water-heater-band power (~2-4 kW).
   Panel1 stashes solar context per tick; Panel2 reads it (panels run in order).
6. **Additive disambiguation** (MATNilm/dual-head only): residual panel watts beyond the ON set
   recover the best-fitting OFF appliance; a soft overshoot trim drops only low-confidence,
   non-physics-set appliances (never the top call or a >=0.5-confidence one).

`services/iems/training/rule_engine.py` is the calibrated, house-specific rule engine that both
**generates training labels** and serves as the conceptual backbone; appliances with too few
positive labels are intended to be served from rules rather than the model.

`services/iems/decision_support/rule_tree.py` holds the downstream DSS recommendation logic.

---

## 4. Repository layout (key files)

```
streaming/solar-pipeline/solar_producer.py  # Solar Assistant MQTT -> AnyLog solar_data (Section 1)
services/iems/
  inference/
    inference_loop.py        # continuous loop: fetch -> model -> rules -> write (--once / --dry-run)
    onnx_disaggregator.py    # loads ONNX sessions, applies thresholds + rules, writes nilm_disaggregated
    feature_builder.py       # builds the normalized (1,100,N) feature window from panel rows + weather
    appliance_map.py         # PANEL_TO_MODEL registry, appliance->panel routing, nominal watts
    rules_additive.py        # physics/weather reconciliation (Section 3)
  models/
    nilm_panel{1,2,3}.onnx           # ACTIVE BiLSTM models (+ _int8)
    panel{N}_norm_bilstm.json        # ACTIVE 12-feature norm + thresholds
    nilm_panel{1,2,3}_matnilm.{onnx,pt}  # disabled MATNilm (collapsed)
    panel{N}_norm.json               # MATNilm 13-feature norm
  training/                  # window builders, label builders, rule_engine, threshold tuning, reports
    pull_solar_parquet.py    # pulls solar_data history -> analysis/solar/solar_history.parquet
                             #   (USE_SOLAR=1 in train_all_physical.py merges it into features
                             #   once eGauge/solar coverage overlaps by ~2+ weeks)
  storage/battery_model.py   # modeled lead-acid SOC (13.5 kWh, 10% floor, solar-charged)
  decision_support/rule_tree.py
  load/anylog_query.py       # AnyLog REST read/write (fetch_all_panels, insert_predictions,
                              #   fetch_solar_snapshot -> latest measured solar_data row)
  tests/test_pipeline_solar.py  # unit tests: solar gating, rules threading, feature window
                                 #   shape, end-to-end panel3 disaggregation
  weather.py                 # Open-Meteo (irradiance, cloud cover, temp) for Los Gatos
  web/server.js              # Node live dashboard (:47821) — KPIs, NILM ON/OFF grid, solar/battery, DSS

services/remote-gui/         # upstream AnyLog Remote-GUI clone (separate repo); holds the
                             # React frontend (CLI/local-cli-fe-full) + FastAPI plugin
                             # (CLI/local-cli-backend/plugins/iems) for the :3001 / :8000 app
test_results/                # diagnosis notes and live test outputs
*.bak.*                      # timestamped editor/session backup snapshots
```

---

## 5. Setup and running

### Prerequisites
Docker + Docker Compose, Python 3.11+ (a training venv at `.venv-training/`), Node.js (for the
Node dashboard), and SSH access to the eGauge / Kafka source.

### 5.1 Bring up the streaming stack
```bash
cd ~/microgrid-manager
docker compose up -d            # operator1 (AnyLog), master, postgres1, kafka, egauge-producer,
                                # anylog-consumer, kafka-ui (:8080), ollama, iems-app
```
- AnyLog operator config: `~/docker-compose/docker-makefiles/operator1-configs/`.
- The eGauge producer publishes to Kafka topic `egauge-energy`; the AnyLog operator consumes it
  and lands rows in PostgreSQL (`customers` DB, table `egauge_kafka`).
- Verify ingestion (replace partition date as needed):
  ```bash
  docker exec postgres1 psql -U demo -d customers -t -A -c \
    "select max(ts) from par_egauge_kafka_2026_06_00_d14_insert_timestamp;"
  ```

### 5.2 Run the NILM inference loop
```bash
PYTHONPATH=services .venv-training/bin/python3 -m iems.inference.inference_loop --tick 30
# one pass (JSON):            ... --once
# one pass, no DB write:      ... --dry-run     # prints per-appliance state/conf/power/rule
```
On macOS this is run as a launchd agent (`com.microgrid.iems-inference`); restart with:
```bash
launchctl kickstart -k gui/$(id -u)/com.microgrid.iems-inference
```
The loop writes one `nilm_disaggregated` row per appliance per window (~30 s).

### 5.3 Dashboards
```bash
# Node dashboard (live KPIs + NILM ON/OFF grid + derived solar/modeled battery + DSS)
node services/iems/web/server.js          # http://localhost:47821

# React app + FastAPI backend (built into the iems-app container)
docker compose up -d iems-app             # http://localhost:3001  (API http://localhost:8000/docs)
```
Useful endpoints: `:47821/api/nilm`, `:47821/api/storage`, `:8000/iems/storage`, `:8000/iems/health`.

### 5.4 Model / threshold changes
- Switch model family: edit `PANEL_TO_MODEL` in `appliance_map.py`, then restart the loop and
  `docker restart iems-app`.
- Tune detection: edit `thresholds` in `panel{N}_norm_bilstm.json`; the physics power gate keeps
  low thresholds from producing false positives on idle panels.
- Rules: edit `rules_additive.py` (signature bands, weather thresholds, mutex groups).

---

## 6. Known limitations
- **Panel1 / Panel2 models are weak** (limited labeled data, class imbalance). Their appliances
  are governed largely by the power gate + weather rules; real improvement needs more seasonal
  labeled data and retraining.
- **MATNilm models are collapsed** (constant priors) and disabled.
- **Solar is derived by default** (energy balance, carries a small unmetered-load offset,
  clamps to 0 at night); **measured** PV/battery/grid/load is available from Solar Assistant
  (`solar_data`, ingesting since Aug 2026) and is preferred by the rules engine when a recent
  snapshot exists. Model retraining on solar features (`USE_SOLAR`) is built but blocked until
  eGauge and solar telemetry overlap by ~2 weeks.
- **Battery SOC is modeled**, not metered (charged by solar surplus, 10% floor).
- Predictions are best-estimate over a trailing window, not an instantaneous measurement.
