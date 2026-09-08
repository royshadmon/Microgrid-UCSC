# File inventory

Two file sets make up the system. Part A is what exists on Pat's box and is the
authority on runtime behaviour. Part B is the repository, which is where models
are made and where fixes should land. Part C is the drift, which is real and
which matters.

Listings verified 2026-09-08. Backups matching `*.bak*`, the
`services/iems/{inference,models,training}.bak_*` trees, and the dated
directories under `test_results/` and `.deploy_backups/` are historical snapshots
and are excluded throughout.

---

# Part A. Pat's box

## A.1 The deployment root

`/home/pat/microgrid_manager/Microgrid-UCSC-dev_fin/`, owned by `pat` and
unreadable as `microgrid`.

| path | role |
|---|---|
| `docker-compose.yaml` | **one file for twelve services.** A bare `docker compose down` here stops both AnyLog nodes and everything else. This is the mistake that took the whole stack down on 2026-08-17. Always `up -d --no-deps <service>` |
| `.env` | `ANYLOG_LICENSE`, eGauge credentials, Postgres credentials, site lat/lon/tz, inference tick, Solar Assistant credentials |
| `services/iems/web/server.js` | the deployed dashboard, 2784 lines. Two column Ask tab, the `dt` header element, the `/api/sources` SQL rewrite and its 60 s cache |
| `services/iems/**` | the source tree the images are **built** from. Nothing bind mounts it, so editing a file here changes nothing until the owning image is rebuilt |
| `services/iems/models/` | the **18 feature** model set dated 2026-08-10. This is the tree `iems-inference` was rebuilt from on 2026-09-08, so it is now the source of the running models. Nothing bind mounts it, so a change here needs an image rebuild to take effect |
| `streaming/anylog/docker-compose/docker-makefiles/operator1-configs/base_configs.env` | line 159 `PARTITION_INTERVAL=1 month`, with `PARTITION_KEEP=3` and `PARTITION_SYNC=1 day`. It reverted to `14 days` on a container recreate on 2026-09-01 and queries silently resolved against the old `d14` partitions |
| `.../operator1-configs/patches/validate_node_policy.al` | bind mounted at `/app/deployment-scripts/node-deployment/policies/`. The overlay fallback must match on `local_ip = !overlay_ip` at line 49. With `ip = !overlay_ip` the lookup fails, and under 2.1.2608 that abort exits the whole script array |
| `.../operator1-configs/local_script.al` | bind mounted operator bootstrap. Also sets monthly partitioning, so it and `base_configs.env` must agree |
| `appliance_data_updated.txt` | the site appliance inventory. Source of every canonical power band and on-threshold, and copied into the `iems-backend` image |
| `.deploy_backups/rolling_<stamp>/` | written by `~/rolling-deploy/deploy_rolling.sh`. Four rolling stamps present, newest `rolling_20260810_155421` |
| `docs/anylog_query_cookbook.md` | the only file in the deployment root's own docs directory |

The compose file names twelve services.

```
postgres  master  operator1  kafka  kafka-ui  egauge-producer
anylog-consumer  ollama  iems-app  iems-inference  iems-dashboard  solar-producer
```

Eleven named volumes back them, including `operator1-local-scripts` mounted at
`/app/deployment-scripts`. Docker only auto-seeds a named volume from the image
when Docker itself creates that volume. A pre-created empty volume is mounted as
is, which is how `operator1` once booted with an empty `/app/deployment-scripts`,
found no `main.al`, and idled with its port closed.

The `license_policy.al` bind mount on `master` was removed at the 2.1.2608
upgrade. See `00_architecture.md`.

## A.2 What the deployment root does **not** have

This is the part that matters most for reading the rest of these documents.

```
services/iems/training/     the OLDER generation only
analysis/egauge_consolidation/   absent
analysis/solar/                  absent
services/remote-gui-overlay-212/ absent, it lives in ~microgrid
```

Present in `services/iems/training` on Pat's box: `canonical_signatures.py`,
`rule_engine.py`, `postprocess.py`, `losses.py`, `make_labels.py`,
`vacuum_detector.py`, `solar_features.py`, `build_windows.py`,
`split_utils.py`, `aug_oversample.py`, the `model_panel{1,2,3}*.py`
architectures, the `train_panel{N}*.py` and `eval_panel{N}*.py` families,
`export_panel{1,2,3}.py`, `export_matnilm.py`, `tune_thresholds{,_v2}.py`,
`realtime_monitor{,_rules}.py`, the `pull_*.py` acquisition scripts and
`smoke_test.py`.

Absent from Pat's box and present only in the repository:
`temporal_rule_engine.py`, `physical_labeler.py`, `physical_labeler_v2.py`,
`dual_labeler.py`, `train_rolling.py`, `train_all_physical.py`,
`train_all_dual.py`, `export_physical.py`, `gen_norm_physical.py`,
`signature_crosscheck.py`, `camal_pipeline.py`, `timer_differentiator.py`,
`rule_engine_ct.py`, `make_labels_ct.py`, `build_windows_ct.py`,
`reg_targets_ct.py`, `phase0_ct/`, `matnilm/`.

`services/iems/models/` on Pat's box holds the three served ONNX files, their
`.pt` checkpoints, the `int8` and `matnilm` variants, the three
`panel{N}_norm_bilstm.json` files and three legacy `panel{N}_norm.json`. It has
none of the `.bak_14f_*`, `.bak_18f_*`, `_ct` or `_aug_{solar,nosolar}` files the
repository carries.

**Pat's box runs the serving path. The repository is where models are made.**
The models actually running were produced by a trainer that does not exist on
Pat's box, and reached it as prebuilt files in `~microgrid/nilm_deploy/` that
were copied into the `iems-inference` image on 2026-08-24. They are byte
identical to the repository's, so on models the two machines agree. The 18
feature set sitting on the deployment root is an older `deploy_rolling.sh` run
that nothing loads.

## A.3 `~microgrid/` — the operational home

Readable and writable as `microgrid`. This is where deploys, backups and the
out-of-compose engine actually live.

| path | role |
|---|---|
| `iems-backend-build/` | build context for `iems-backend:local`. **The engine that serves the whole system.** Holds `main_api.py`, `iems_router.py`, `iems_ask.py`, and a Dockerfile that additionally copies `appliance_data_updated.txt` and `breaker_ratings.yaml`, which the base inference image does not carry |
| `iems-backend-build/iems_ask.py` | 20,835 bytes. Selective parallel TTL cached live feeds, opt-in site knowledge, rules constants read live out of `rules_additive.py` so the summary cannot drift from the running rules |
| `remote-gui-overlay-212/` | the GUI overlay build context. `Dockerfile`, `backend/iems/iems_router.py` at 277 lines, `frontend/iems/{IemsPage.js,iems_api.js,iems_dash.js}`, `enable_iems.py`, `gen_dash_module.py` |
| `deploy_gui212.sh` | deploy and rollback for `iems-app`. Label driven compose discovery, four line rewrite, never runs `down`, `--rollback <stamp>` |
| `deploy_anylog20.sh` | the AnyLog major version upgrade script, same conventions. Licence gate first, per volume backup, explicit rollback |
| `rolling-deploy/deploy_rolling.sh` | writes the 18 feature model set onto the deployment root and backs up to `.deploy_backups/rolling_<stamp>/`. On its own it does **not** change what is running, because nothing bind mounts that directory. Also carries `inference/ models/ monitoring/ training/ web/` staging trees |
| `rolling-deploy/fix_ha_token.sh` | redundant since the bind mount, kept as a fallback if the compose file is restored from a pre-2026-08-31 backup |
| `build_uns_graph.py` | UNS graph generator and uploader. Reads the inventory live from the IEMS engine. Idempotent, `--dry-run` writes JSON without publishing |
| `uns-graph/` | `uns_objects.json` 45 KB, `uns_assignments.json` 35 KB, `uns_graph_single.json` 102 KB, `uns_knowledge_graph_cache.json` 44 KB |
| `ha_token.txt` | Home Assistant long lived token, 184 bytes, mode 600. Bind mounted read only into `iems-dashboard` at `/app/.ha_token`. Before the mount existed it was `docker cp`ed into the container's writable layer and was destroyed by every rebuild, which silently disabled every thermostat control |
| `nilm_deploy/` | **the source of the running models.** Its three ONNX files are byte identical to the ones inside `iems-inference`. Also holds the norm files, `feature_builder.py`, `recommender.py`, `server.js` and a second copy of the HA token |
| `iems_grafana/` | `docker-compose.grafana.yml`, `grafana/provisioning/`, `grafana/dashboards/`, `remote_grafana_fix.sh`, and a staged `server.js` |
| `.gui_backups/gui212_<stamp>/` | compose backup, previous route list, manifest. Latest good stamp `20260901_155124` |
| `.anylog_backups/anylog20_<stamp>/` | per volume tarballs and compose copies from the node upgrades |
| `.ledger_backups/20260831_155705/` | per type policy dumps, `all.json` at 105 KB, and the raw ledger files from both containers. Rollback is one `docker cp` and a restart |
| `patch_ask.py`, `patch_src.py` | the two idempotent patch scripts actually used on this host. Each asserts a single match per anchor and refuses to double-patch |
| `model-deploy/`, `phase04-deploy/`, `remote-gui-overlay/` | earlier deployment trees, superseded |
| `build212*.log`, `deploy212*.log`, `build_backend*.log` | build and deploy transcripts |
| `license_policy.al` | the removed master patch, kept for reference |

---

# Part B. The repository by role

Paths are relative to the repository root, `~/microgrid-manager` on the dev Mac.
Files marked **repo only** do not exist on Pat's box.

## B.1 Root

| file | role |
|---|---|
| `docker-compose.yaml` | the whole stack, twelve services in one file |
| `.env` / `.env.example` | see the README for the key list |
| `docker-compose.grafana.yml` | Grafana 11.3.0 with the Infinity datasource |
| `docker-compose.iems-app-only.yaml.ref` | reference fragment for bringing up `iems-app` alone |
| `README.md`, `INSTALL.md`, `GRAFANA_README.md` | top level documentation |
| `server.js` | staging copy of the dashboard server, shipped by the `deploy*.sh` scripts |
| `appliance_data_updated.txt` | the site appliance inventory |
| `matnilm_spec.md`, `panel2_spec.md`, `panel3_spec.md` | the written specifications the rule heads were derived from |
| `egauge_python_test.py` | one-off meter connectivity probe |

## B.2 Deployment and operations scripts

Full detail in `08_scripts_and_shells.md`.

| file | runs where |
|---|---|
| `scripts/deploy_gui212.sh` | Pat's box, `sudo bash` |
| `scripts/start.sh`, `start_all.sh`, `stop.sh` | a host with the split compose layout, which is the dev Mac and not Pat's box |
| `scripts/probe_egauge.py`, `download_egauge_year.py` | anywhere |
| `deploy2.sh`, `deploy_dashboard.sh` | the Mac, over SSH |
| `deploy_grafana.sh`, `fix_grafana.sh` | the Mac, over SSH |
| `remote_grafana_fix.sh` | Pat's box |
| `fix_and_verify.sh`, `diag_sources.sh`, `verify.sh` | the Mac, over SSH |

## B.3 Streaming layer

| file | role |
|---|---|
| `streaming/kafka-egauge-pipeline/egauge_kafka_producer.py` | polls `dev.get("/register?rate")` once per second, publishes one Kafka message per register keyed by register name. The host copy has the timeout and watchdog. The repository copy does not |
| `streaming/kafka-egauge-pipeline/kafka_to_anylog.py` | the `anylog-consumer` bridge. Batches into AnyLog streaming PUT on 32149, prints `Stats: N OK, M FAIL` every 30 s. Identical N across two lines means subscribed but consuming nothing |
| `streaming/kafka-egauge-pipeline/Dockerfile.{producer,consumer}` | images for the two above |
| `streaming/kafka-egauge-pipeline/docker-compose.kafka.yml` | standalone Kafka stack used by `start.sh` |
| `streaming/solar-pipeline/solar_producer.py` | subscribes to Solar Assistant MQTT, republishes to AnyLog. `INGEST_MODE=rest` switches it to streaming PUT, which is what Pat's box actually uses |
| `streaming/anylog/docker-compose/docker-makefiles/` | all AnyLog node configuration. Note the `docker-compose/` level in the path |
| `streaming/postgres/init/01-ensure-demo-user.sql` | creates the `demo` role AnyLog writes as |
| `streaming/launchd/com.microgrid.iems-inference.plist.template` | macOS launchd agent for the dev inference loop |

## B.4 IEMS engine, runtime

Line counts are from Pat's box.

| file | lines | role |
|---|---|---|
| `services/iems/backend/main_api.py` | — | the `iems-backend` FastAPI app. Mounts `api_router` and `ask_router` |
| `services/iems/backend/iems_router.py` | — | the engine routes |
| `services/iems/backend/iems_ask.py` | — | the Ask endpoint. The deployed copy is `~microgrid/iems-backend-build/iems_ask.py` and is ahead of this one |
| `services/iems/runner.py` | — | `run_iems_cycle()`, the four domain pass |
| `services/iems/config.py` | — | `CHANNELS`, `APPLIANCES`, `TOU_RATES`, `LOAD_PANELS`, `CRITICAL_APPLIANCES`. Channel names match the meter exactly and are not negotiable |
| `services/iems/weather.py` | — | Open-Meteo fetch, no API key |
| `services/iems/inference/inference_loop.py` | 155 | the 30 s loop, `TICK_SECONDS = 30`, `WINDOW_MINUTES = 12` |
| `services/iems/inference/onnx_disaggregator.py` | 268 | one cached session per panel, threshold application, gates, `apply_rules`, write |
| `services/iems/inference/feature_builder.py` | 238 | builds the `(1, window, n_features)` tensor |
| `services/iems/inference/appliance_map.py` | 97 | `PANEL_TO_MODEL`, `APPLIANCE_TO_PANEL`, `APPLIANCE_NOMINAL_W`, `CRITICAL_APPLIANCES`, `MOBILE_APPLIANCES` |
| `services/iems/inference/rules_additive.py` | 348 | the runtime rules engine. Also read live by the Ask endpoint |
| `services/iems/load/anylog_query.py` | 488 | all AnyLog reads and writes. `_get_partitions` caches per process with no TTL |
| `services/iems/load/{disaggregator,llm_client,prompt_builder,output_normalizer}.py` | — | the older LLM disaggregation path |
| `services/iems/load/anomaly.py` | — | water heater dormancy, pressure pump over-cycling, phantom dryer |
| `services/iems/load/shedding.py` | — | shed candidate ranking |
| `services/iems/load/mobile_load.py` | — | vacuum reconciliation across panels |
| `services/iems/generation/grid_analytics.py` | — | PG&E E6 period classification and the 24 hour rate strip |
| `services/iems/generation/solar_forecast.py` | — | irradiance proxy for dispatch |
| `services/iems/storage/battery_model.py` | — | 13.5 kWh SOC tracker, 10 percent floor |
| `services/iems/storage/dispatch.py` | — | charge, discharge or hold |
| `services/iems/decision_support/recommender.py` | — | dollar denominated recommendations |
| `services/iems/decision_support/optimizer.py` | — | 24 h hourly linear program |
| `services/iems/decision_support/rule_tree.py` | 34 | AUTO versus USER_DRIVEN tagging and the flow branch |
| `services/iems/decision_support/shedding_bridge.py` | — | import cycle breaker |
| `services/iems/detect/breaker_margin.py` | — | per leg RMS current against breaker ratings |
| `services/iems/detect/breaker_ratings.yaml` | — | the ratings, also copied into the engine image |
| `services/iems/detect/stuck_off.py` | — | detects an appliance that always cycled and has stopped |
| `services/iems/detect/hvac_shed.py` | 414 | the only real actuator on the site |
| `services/iems/detect/ha_client.py` | — | minimal Home Assistant REST client |
| `services/iems/detect/anomaly_store.py` | — | writes `customers.anomalies` |
| `services/iems/monitoring/gap_watchdog.py` | — | alerts when a channel has been silent too long |
| `services/iems/web/server.js` | 2784 | the standalone dashboard. Zero dependencies |

Only `iems-dashboard` talks to Home Assistant. `iems-inference` and
`iems-backend` have no HA configuration.

## B.5 Models

| file | role |
|---|---|
| `services/iems/models/nilm_panel{1,2,3}.onnx` | the served models. Panel1 four heads, Panel2 four heads, Panel3 fourteen heads |
| `services/iems/models/panel{1,2,3}_norm_bilstm.json` | feature order, mean, std, window 100, stride 10, mid 50, head names, per head thresholds. Pat's box runs the **18 feature** set. The repository's working copies are still the 14 feature set, with the 18 feature files kept as `.bak_18f_*` |
| `services/iems/models/nilm_panel{1,2,3}.pt` | the checkpoints the ONNX files were exported from |
| `services/iems/models/nilm_panel{N}_int8.onnx` | quantised variants |
| `services/iems/models/nilm_panel{N}_matnilm.{pt,onnx}` | MATNILM architecture variants |
| `services/iems/models/panel{N}_norm.json` | legacy normalisation, superseded by the `_bilstm` files |
| `services/iems/models/nilm_panel{N}.onnx.bak_{14f,18f}_*` | **repo only.** Previous feature count generations, kept for rollback |
| `services/iems/models/nilm_panel{N}_ct.pt`, `panel{N}_ct_norm.json` | **repo only.** The CT instrumented walk test generation |
| `services/iems/models/panel{N}_aug_{solar,nosolar}_norm_bilstm.json` | **repo only** |

## B.6 Training pipeline

Detail in `02_physical_labellers.md` and `04_training_pipeline.md`. Everything in
this section marked **repo only** is absent from Pat's box.

Acquisition. `pull_data.py`, `pull_6mo.py`, `pull_egauge_csv.py`,
`pull_egauge_historical.py`, `merge_fresh_anylog.py`, `extract_panel1{,_pg}.py`.
Repo only: `pull_august_overlap.py`, `pull_solar_parquet.py`, `pull_data_ct.py`.

Labelling. `canonical_signatures.py`, `rule_engine.py`, `make_labels.py`,
`vacuum_detector.py`, `solar_features.py`, `labels_panel{1,2,3}.py`,
`postprocess.py`. Repo only: `temporal_rule_engine.py`, `physical_labeler.py`,
`physical_labeler_v2.py`, `dual_labeler.py`, `timer_differentiator.py`,
`camal_pipeline.py`, `signature_crosscheck.py`, `rule_engine_ct.py`,
`make_labels_ct.py`.

Windowing, models, training, export. `build_windows.py`,
`windows_panel{1,2,3}.py`, `split_utils.py`, `_resplit.py`, `aug_oversample.py`,
`losses.py`, `model_panel{1,2,3}.py`, `model_panel3_attn.py`,
`model_matnilm.py`, `train_panel{N}*.py`, `train_all_panels.py`,
`train_models.py`, `train_matnilm.py`, `tune_thresholds{,_v2}.py`,
`export_panel{1,2,3}.py`, `export_matnilm.py`, `eval_panel{1,2,3}.py`,
`eval_recent_days.py`, `realtime_monitor{,_rules}.py`, `smoke_test.py`.
Repo only: `train_rolling.py`, `train_all_physical.py`, `train_all_dual.py`,
`train_panel3_dual.py`, `export_physical.py`, `gen_norm_physical.py`,
`build_windows_ct.py`, `reg_targets_ct.py`, `phase0_ct/`, `matnilm/`.

`reports/` holds every evaluation, census and unit test artifact the pipeline
emits. `requirements-training.txt` pins the training dependencies.

## B.7 GUI overlay and plugin

The deployed copy is `~microgrid/remote-gui-overlay-212/`.

| file | role |
|---|---|
| `Dockerfile` | two stage overlay on `anylogco/remote-gui:2.1.2`. Adds five files, modifies one |
| `backend/iems/iems_router.py` | 277 lines, 26 `/iems` routes. Explicit routes, never a catch-all, because a wildcard `/iems/{path:path}` would swallow `/iems/dash` and the OpenAPI schema should describe the real surface. Every forward runs in `starlette.concurrency.run_in_threadpool`, which is the single most important line in the plugin |
| `frontend/iems/IemsPage.js` | 60 lines. Inject style, set `innerHTML`, mount, tear down |
| `frontend/iems/iems_api.js` | plugin API surface |
| `frontend/iems/iems_dash.js` | generated, 105 KB. Never hand edited |
| `gen_dash_module.py` | fetches the live dashboard, scopes 198 CSS rules under `.iems-dash-root`, takes markup verbatim minus script tags, wraps the controller unmodified with `document`, `fetch` and the four timer functions shadowed |
| `enable_iems.py` | appends the four line `iems` entry to the `plugins` map in `feature_config.json`. `plugin_order.json` is deliberately untouched |
| `services/remote-gui-iems-plugin/` | the earlier plugin against the forked GUI. Superseded |
| `services/remote-gui/` | the full fork of the AnyLog remote-gui, kept as reference. Superseded in production by the upstream image plus the overlay |

## B.8 Grafana

`grafana/docker-compose.grafana.yml`, `grafana/provisioning/datasources/infinity.yml`
pointed at the dashboard's `/api/grafana/*` feeds,
`grafana/provisioning/dashboards/provider.yml`, and
`grafana/dashboards/iems-microgrid.json`.

## B.9 Analysis, tools and tests

`analysis/inventory/build_register_inventory.py` and `register_inventory.csv` are
on both machines. `analysis/anomalies/` and `analysis/automation/` exist on both.
`analysis/egauge_consolidation/` and `analysis/solar/` hold the training archive
and are repository only.

`tools/uns/build_uns_graph.py` is the repository copy of the UNS builder, and the
deployed copy is `~microgrid/build_uns_graph.py`. `tools/uns/make_paths_json.py`
and the UNS artifacts sit alongside it. `tools/ha_probe.py`, `tools/mqtt_dump.py`,
`tools/sa_login.py` and `tools/sa_mqtt_cfg.py` are debugging helpers.

Tests are `tests/test_iems.py`, `tests/conftest.py` and the package tests
`services/iems/tests/test_{breaker_margin,pipeline_solar,register_inventory}.py`.

---

# Part C. The drift

The full table is in the README. The four rows worth repeating here.

| item | Pat's box | repository |
|---|---|---|
| running models | **18 feature**, 22 heads, baked into `iems-inference` and `iems-backend` since 2026-09-08 | 14 feature working copies, 18 feature kept as `.bak_18f_*` |
| training pipeline | older generation only | complete |
| eGauge producer timeout and watchdog | applied | not applied |

Anything changed in the repository has to be brought over deliberately. Anything
changed on the host should be back-ported, and the producer fix is the one that
matters most, because it has cost 107 hours of data across three incidents.
