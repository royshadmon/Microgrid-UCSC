# Claude Code Prompt — Complete the MATNilm 2DMA Migration (all 3 panels)

You are working in `~/microgrid-manager` on branch `model_dev_working`. Docker is up
(AnyLog operator1 on REST 32149 / TCP 32148, eGauge18646 reachable, inference loop PID
running `iems.inference.inference_loop --tick 30`). The goal is to **finish migrating all
three panels from the legacy Conv1D+BiLSTM ONNX models to the MATNilm 2DMA dual-head
architecture**, retrain on fresh data from Dr. Mantey's house pulled from AnyLog + eGauge,
wire the dual-head + additive/mutex/battery rules into live inference, and verify the
pipeline end to end.

Do NOT revert to BiLSTM. Keep the MATNilm scaffolding already on disk
(`training/model_matnilm.py`, `training/train_matnilm.py`, `inference/rules_additive.py`,
`inference/appliance_map.py`).

## Hard rules (do not violate)
- Python interpreter is always `.venv-training/bin/python3`. Set `PYTHONPATH=services` (or
  `sys.path.insert(0,"services")`) for any `iems.*` import.
- Never use `localhost` for Docker/AnyLog — use `127.0.0.1` (Mac resolves localhost to IPv6).
- No force-push. No Claude / AI / tool attribution in commits, READMEs, code comments, or
  reports. Commit messages are plain and imperative.
- Before overwriting any file you did not just create, back it up:
  `cp file file.bak.$(date +%s)`. The `*.bak_20260531_173534` dirs are the pre-session
  snapshot — leave them.
- Work one phase at a time. At each **CHECKPOINT**, print the stated artifacts/metrics and
  STOP for review before starting the next phase. Training runs are long — never start a
  full train without first confirming a `--quick` smoke run passed.
- The live inference loop must keep running on the current ONNX models until Phase 7 is
  validated. Do not delete the legacy `nilm_panel{1,2,3}.onnx` files until Phase 9.

## Canonical appliance spec (authoritative — supersedes appliance_data_updated.txt)
There is **no Shop panel** in the logical model. The eGauge still exposes a `Shop` register
(garage subfeed); keep `shop_w` as an INPUT feature but attribute its appliances to Panel 3.

Panel 1 (HVAC):
- heat_pump — on 300 W, range 1500–4000 W; **fan-only sub-state ~550 W** (rarely on alone)
- solar_pump (solar water-heater pump) — on ~50 W, range 100–250 W
- **Interlock/mutex:** when the solar pump runs the heat pump is OFF and vice versa.

Panel 2 (H2O):
- water_heater — on 500 W, range 2000–4000 W
- hair_dryer — on 800 W, range 1200–1800 W
- sprinklers — on 50 W, range 100–300 W
- bath_lights — master-bath mirror incandescent, ~300 W, daily/short. Only incandescent load.
- jacuzzi pump — NEVER used; omit entirely.

Panel 3 (Kitchen) — includes former "shop"/garage loads:
- dryer (240 V) — on 1000 W, range 4000–7000 W
- washing_machine — on 50 W, range 200–2000 W
- dishwasher — on 50 W, range 200–1800 W
- microwave — on 200 W, range 900–1500 W
- pressure_pump — on 200 W, range 500–1000 W
- refrigerator — on 50 W, range 80–200 W (kitchen fridge + garage fridge + garage freezer)
- computers (aggregated) — on 100 W, range 200–500 W
- tv_stereo — on 80 W, range 100–200 W
- garage_opener — short transient ~300–600 W (no labeled head yet; see Phase 5 note)
- occasional small loads (toaster, toaster oven, coffee maker, oven 240 V, cooktop 240 V,
  clothes iron) — unlabeled background; do not add heads.

Mobile: vacuum_cleaner — on 600 W, range 800–1200 W; changes panels; routed to Panel 3.
Critical loads: refrigerator(×2 + freezer), garage_opener, networking (unmetered), pressure_pump.
Battery: charged daily **16:00–21:00** local (the `battery_window` feature / DSS flag).

The `inference/rules_additive.py::APPLIANCE_SIGNATURE` table and `inference/appliance_map.py`
already match the above. Treat that table as the single source of truth and reconcile every
other file to it.

---

## PHASE 0 — Preflight & state capture
**Goal:** confirm environment, capture the starting point, do not disturb the live loop.
Steps:
1. `git status` and `git rev-parse --abbrev-ref HEAD` — confirm branch `model_dev_working`.
2. `ps aux | grep inference_loop | grep -v grep` — confirm the live loop PID; record it.
3. Verify interpreter + libs:
   `.venv-training/bin/python3 -c "import torch, onnx, onnxruntime, numpy, pandas; \
   print(torch.__version__, torch.backends.mps.is_available())"`
4. Snapshot current model reports:
   `cat services/iems/training/reports/panel{1,2}_matnilm_train.json | head -60`
**CHECKPOINT:** print branch, loop PID, lib versions. STOP.

## PHASE 1 — Reconcile the appliance spec across the codebase
**Goal:** make labels, nominals, and signatures consistent with the canonical spec above.
Files: `appliance_data_updated.txt`, `inference/appliance_map.py`, `inference/rules_additive.py`,
`training/labels_panel1.py`, `training/labels_panel2.py`, `training/labels_panel3.py`.
Steps:
1. Rewrite `appliance_data_updated.txt` to the canonical spec (it is referenced by the label
   scripts' docstrings; keep it accurate).
2. Diff thresholds: `labels_panel1.py` currently uses `SP_ON_THRESHOLD=30`; the canonical
   solar_pump on-threshold is 50 W. Align label thresholds to the signature table for ALL
   heads in all three label scripts (heat_pump 300, solar_pump 50, water_heater 500,
   hair_dryer 800, sprinklers 50, bath_lights 80, dryer 1000, washing_machine 50,
   dishwasher 50, microwave 200, pressure_pump 200, refrigerator 50, computers 100,
   tv_stereo 80). Do not change the feature engineering, only the numeric thresholds and
   any range gates.
3. In `labels_panel1.py`, encode the **interlock**: a window where Panel-1 power is in the
   solar-pump band AND below the heat-pump on-threshold should label solar_pump=1,
   heat_pump=0; when heat_pump=1, solar_pump must be 0 (mutually exclusive labels).
4. Confirm `appliance_map.py` panel routing and `APPLIANCE_NOMINAL_W` already match — only
   edit if a value contradicts the spec.
**CHECKPOINT:** `git diff --stat`; print the final threshold constants from each label
script side by side. STOP.

## PHASE 2 — Pull fresh data from AnyLog + eGauge
**Goal:** extend the training data from its current end (2026-05-18) through "now" (the
labeled parquets currently span 2026-04-28 → 2026-05-18, ~20 days; we want the freshest
~30–45 days). AnyLog is the primary source; eGauge fills gaps and provides registers AnyLog
may lack (VrmsA/B, utility tie).
Steps:
1. Inspect what AnyLog has now. Use the MCP AnyLog tools or curl. Remember the gotchas:
   - Query the partition table directly:
     `par_egauge_kafka_<YYYY>_<MM>_00_d14_insert_timestamp`, not the parent name.
   - `--noproxy '*'`, header `User-Agent: AnyLog/1.23`, and
     `-H 'command: sql customers format=json and stat=false "..."'`.
   - Never put a parenthesized string literal in a WHERE clause (e.g. `nm='Panel1 (HVAC)'`
     silently returns empty) — fetch by time only and filter client-side.
   - Confirm the latest `ts` available:
     `SELECT MAX(ts) FROM egauge_kafka`.
2. Pull eGauge directly for the recent window using `training/pull_egauge_historical.py`
   (adjust `START_DATE`/`END_DATE` to cover 2026-05-18 → today; it pulls registers
   `Panel1 (HVAC)`, `Panel2 (H2O)`, `Panel3 (Kitchen)`, `Shop`, `Current on Utility Tie`,
   `VrmsA`, `VrmsB`, `F1`). Requires `EGAUGE_USER` / `EGAUGE_PASSWORD` env vars — if unset,
   STOP and ask the user to provide them (do not hardcode credentials).
3. Merge fresh rows into `data/panel{1,2,3}_60d.parquet`, dedupe on timestamp, keep the
   weather columns (`outside_temp`, `irradiance` from Open-Meteo, lat 37.2358 lon -121.9624)
   and re-derive `utility_tie_current`. Preserve the exact column schema the window builders
   expect (`panel1_w panel2_w panel3_w shop_w outside_temp irradiance utility_tie_current`
   + time encodings derived at window-build time).
**CHECKPOINT:** print, for each panel, `len(df)`, `df.index.min()`, `df.index.max()`, and
NaN counts per column. Confirm the max timestamp advanced past 2026-05-18. STOP.

## PHASE 3 — Re-label with the reconciled thresholds
**Goal:** regenerate `data/panel{P}_60d_labeled.parquet` from the freshly pulled raw parquet.
Steps:
1. `PYTHONPATH=services .venv-training/bin/python3 services/iems/training/labels_panel1.py`
2. `... labels_panel2.py` ; `... labels_panel3.py`
3. Read each `reports/panel{P}_label_consensus.md` and print the per-head pos/neg/nan counts.
**CHECKPOINT:** print the positive counts per head per panel. Flag any head with < ~150
positives total — that head will not train well and is the likely Panel-2 failure cause.
STOP.

## PHASE 4 — Rebuild windows (battery-aware, hour-curriculum-ready)
**Goal:** regenerate npz + norm.json for all panels with the 13-feature vector that already
includes `battery_window`, preserving the additive regression-target apportionment.
Steps:
1. `PYTHONPATH=services .venv-training/bin/python3 services/iems/training/windows_panel1.py`
   then `windows_panel2.py`, `windows_panel3.py`.
2. These write `data/panel{P}_windows.npz` and `services/iems/models/panel{P}_norm.json`.
   Note current head coverage: P1 {hp,sp}; P2 {water_heater,hair_dryer,sprinklers,bath_lights};
   P3 {refrigerator,dishwasher,microwave,dryer,washing_machine,pressure_pump,computers,tv_stereo}.
3. **Split fix (important):** the current chronological split can strand all positives of a
   rare head in one split (this is why Panel-2 val/test F1 is ~0 with n_pos=1–3). Modify the
   slide/split so each head has a non-trivial positive count in BOTH val and test — either a
   stratified day assignment or a positives-aware shuffle within runs. Keep windows
   contiguous (no leakage of the same run across splits).
4. Verify the feature order in each norm.json ends with `... panel{P}_w_step, battery_window`
   and that `features.index("panel{P}_w")` resolves (the trainer needs `panel_col`).
**CHECKPOINT:** print npz shapes and per-head valid/pos counts for train/val/test for all
three panels. Confirm every head has pos>0 in val AND test. STOP.

## PHASE 5 — Complete MATNilm training for all three panels
**Goal:** full training of all panels with the hour-of-day curriculum + dual heads, fixing
the Panel-1 solar_pump and Panel-2 collapse, and migrating Panel 3.
Trainer: `services/iems/training/train_matnilm.py --panel {1|2|3} [--epochs N] [--quick]`.
It auto-detects heads from the npz, derives additive watt targets via
`build_reg_targets` (apportion panel mid-power across ON heads by `APPLIANCE_NOMINAL_W`),
trains hour-by-hour, early-stops on avg F1, writes `models/nilm_panel{P}_matnilm.pt` and
`reports/panel{P}_matnilm_train.json`.
Steps (run in this order, smoke first):
1. Smoke each panel: `... train_matnilm.py --panel 1 --quick` (then 2, then 3). Confirm it
   runs end to end and writes a report. STOP if any panel errors.
2. Full Panel 1 (`--epochs 80`). solar_pump remediation if F1 stays 0: confirm Phase-4 split
   gives solar_pump positives in val; raise its `pos_weight` cap; rely on the inference-time
   mutex/additive rules as a safety net (do not fake labels).
3. Full Panel 2 (`--epochs 80`). This is the hard one. Apply in order, re-evaluating after
   each: (a) the Phase-4 stratified split; (b) more data from Phase 2; (c) per-head
   `pos_weight` (already capped at 50 — raise cap for water_heater/hair_dryer if still 0);
   (d) optional focal loss from `training/losses.py`; (e) lower per-head decision threshold
   and re-tune in Phase 8. A head with essentially no positives (hair_dryer was n_pos=1)
   should be reported as "insufficient data", not forced.
4. Full Panel 3 (`--epochs 80`). This is a fresh migration (no prior matnilm artifact).
   Compare against the legacy `nilm_panel3.onnx` baseline (refrigerator/computers/dishwasher
   were the strong heads). Do NOT add `garage_opener` or `vacuum_cleaner` heads unless Phase 3
   produced labels for them — note them as deferred.
5. The MATNilm `mid` slice index must equal `window//2` (=50) and `in_features` must equal
   the npz feature count (13). The trainer sets these from the npz; verify in the log line
   `[train] params=...`.
**CHECKPOINT:** print the `test` block (P/R/F1/n_pos per head) from all three
`panel{P}_matnilm_train.json`. State, per head, pass/fail against the acceptance bar:
F1 ≥ 0.70 for high-signal heads (heat_pump, water_heater, dryer, microwave, refrigerator,
dishwasher, computers), ≥ 0.50 acceptable for low-signal heads (solar_pump, sprinklers,
bath_lights, hair_dryer, washing_machine, pressure_pump, tv_stereo). STOP.

## PHASE 6 — Export dual-head MATNilm to ONNX (with parity check)
**Goal:** the legacy `export_panel{1,2,3}.py` export the OLD single-head models and do not
know MATNilm. Write one generic `training/export_matnilm.py --panel {1|2|3}`.
Requirements:
1. Rebuild the `MATNilm` module with the saved `config` + heads from
   `reports/panel{P}_matnilm_train.json`, load `models/nilm_panel{P}_matnilm.pt`, `eval()`.
2. Export with a dynamic batch axis, opset 17, input name `x` shape `[B,100,13]`, output
   names `prob_<head>...` then `pow_<head>...` in head order (the forward returns
   `tuple(probs)+tuple(powers)`).
3. Write `models/nilm_panel{P}_matnilm.onnx`. Then **parity check**: run the same 64 val
   windows through PyTorch and through `onnxruntime` and assert max abs prob diff < 1e-4.
4. Do not int8-quantize yet (the legacy `_int8.onnx` exist; leave them).
**CHECKPOINT:** print the three onnx paths, their sizes, and the parity max-diffs. STOP.

## PHASE 7 — Wire dual-head + rules into live inference
**Goal:** make `onnx_disaggregator.py` consume MATNilm dual-head ONNX and apply
`rules_additive.apply_rules`, and point `appliance_map.py` at the new models.
Files: `inference/appliance_map.py`, `inference/onnx_disaggregator.py`,
`inference/feature_builder.py`, `inference/inference_loop.py`.
Steps:
1. In `appliance_map.py`, repoint each panel's `"onnx"` to `nilm_panel{P}_matnilm.onnx`.
2. In `feature_builder.py`, confirm it emits the 13-feature vector in norm.json order,
   INCLUDING `battery_window` (1.0 if 16:00–21:00 local else 0.0) and `panel{P}_w_step`.
   Add `battery_window` if missing.
3. In `onnx_disaggregator.py::disaggregate_panel_onnx`, parse the dual-head outputs into
   `preds = {appliance: {"state": int(prob>thr), "confidence": float(prob),
   "power_w": float(pow_kw*1000)}}`, then call
   `apply_rules(preds, panel_power_w=<measured panel mid-watt>, ts_local=<window mid local
   ts>, additive=True)`. Thresholds come from `panel{P}_norm.json["thresholds"]` if present,
   else 0.5. Keep the existing `nilm_disaggregated` row schema and column ORDER exactly:
   `ts, circuit, appliance, state, confidence, avg_w, median_w, std_w, window_start,
   window_end, window_n` — and DO NOT include `insert_timestamp` in the streaming payload.
4. Add a `--dry-run` path to `inference_loop.py` that prints the reconciled preds for one
   tick without writing to AnyLog.
**CHECKPOINT:** run `PYTHONPATH=services .venv-training/bin/python3 -m
iems.inference.inference_loop --tick 30 --dry-run` for one tick; print the per-appliance
reconciled output for each panel (state, confidence, power_w, rule). STOP.

## PHASE 8 — Evaluation & threshold tuning (post-rules, vs baseline)
**Goal:** honest side-by-side of MATNilm+rules vs the legacy ONNX, and per-head threshold
tuning written back into norm.json.
Steps:
1. Write/extend a `training/eval_matnilm.py` that loads the test split, runs MATNilm ONNX,
   applies `apply_rules`, and reports per-head P/R/F1 — both raw model and post-rules — and
   diffs against the legacy `nilm_panel{P}.onnx` numbers from `reports/all_panels_eval.json`.
2. Tune per-head decision thresholds (sweep 0.2–0.8) to maximize F1 on val; persist as
   `panel{P}_norm.json["thresholds"][head]`. The window builder already preserves an existing
   `thresholds` block, so re-running Phase 4 will not clobber them.
3. Quantify the additive layer's contribution: report F1 with `additive=False` vs `True`,
   and how often `additive_recovery` / `overshoot_trim` / `mutex` fire.
**CHECKPOINT:** print the comparison table (legacy vs matnilm-raw vs matnilm+rules per head)
and the tuned thresholds. STOP.

## PHASE 9 — Pipeline verification & commit
**Goal:** cut the live loop over to the new models and confirm rows land, then commit.
Steps:
1. Confirm Docker/AnyLog health (MCP `checkStatus` / `getClusterNodeMapping`, or
   `make up ANYLOG_TYPE=operator1` from `~/docker-compose/docker-makefiles/` if needed).
2. Restart the inference loop on the new models (stop the recorded PID, relaunch
   `-m iems.inference.inference_loop --tick 30`). Watch logs in `test_results/`.
3. Verify writes to `nilm_disaggregated`. If rows quarantine with `err_16` (the known
   AnyLog JSON→SQL timestamp-coercion blocker): confirm the payload excludes
   `insert_timestamp`, that `ts` is sent as the schema's `timestamp without time zone`
   (no trailing `Z`), and read `/app/AnyLog-Network/data/error/` inside the operator
   container. A direct `psql` insert of the same row succeeding confirms it is the
   materialization layer, not the data.
4. Sanity-check the dashboard (Node on 47821) shows per-appliance cards updating.
5. Commit on `model_dev_working`: `git add -A && git commit -m "Complete MATNilm 2DMA
   migration for all panels; additive+mutex+battery inference; retrain on extended
   AnyLog/eGauge data"`. No force-push, no attribution.
**CHECKPOINT:** print last 20 lines of the inference log, a `SELECT COUNT(*)` /
recent-rows query against `nilm_disaggregated`, and `git log --oneline -3`. STOP.

---
### Notes for whoever runs this
- Panels are independent — if Panel 2 needs more data than is available, ship Panels 1 and 3
  and leave Panel 2's weak heads flagged rather than forcing them.
- Keep the legacy ONNX models in place as the rollback target until Phase 9 passes.
- The mutex (heat_pump↔solar_pump), the battery window (16–21), and additive
  recovery/trim are enforced at inference in `rules_additive.py`, so the network does not
  have to learn them perfectly — but the labels should still respect the interlock.
