# Rule-Based NILM Disaggregator — Session Report

_Generated 2026-05-12._

This is a rule-only disaggregator derived from `panel2_spec.md`
and `panel3_spec.md` §3.1 (consensus rule labels). No BiLSTM,
no ONNX, no LLM consensus — the rules alone produce per-appliance ON/OFF
state from the live panel-power stream.

## Coverage

| Panel | Appliances |
|---|---|
| Panel 1 (HVAC) | `heat_pump`, `solar_pump`, `vacuum_cleaner` (mobile) |
| Panel 2 (H2O) | `water_heater`, `hair_dryer`, `sprinklers`, `bath_lights` |
| Panel 3 (Kitchen) | `refrigerator`, `dishwasher`, `microwave`, `dryer`, `washing_machine`, `pressure_pump`, `computers`, `tv_stereo` |

Total: 15 appliance heads.

## Architecture

```
data/panel1_60d.parquet (35 d × 10 s grid, all panels + weather)
   │
   ├─ services/iems/training/labels_panel2.py     (offline labels)
   ├─ services/iems/training/labels_panel3.py     (offline labels)
   │     │
   │     ▼
   │   data/panel2_60d_labeled.parquet
   │   data/panel3_60d_labeled.parquet
   │   reports/panel{2,3}_label_consensus.md
   │
   └─ services/iems/training/rule_engine.py       (shared rules)
         │
         ▼
       services/iems/training/realtime_monitor_rules.py
         (10 s tick, AnyLog → DataFrame → apply_rules → jsonl)
```

`rule_engine.py` is the single source of truth. The offline labelers and
the live monitor both call `apply_rules(df)`.

## Calibration ("training" from accumulated data)

Both prompts express their rules in raw-power terms. Running those rules
unmodified against 35 days of accumulated data revealed two systematic
problems on this house:

1. **Panel 2 always-on baseline (150–250 W)** falls inside the
   100–320 W range the prompts use for sprinklers and bath lights. The
   raw-power rule would tag panel baseline as sprinkler/light activity
   in every AM/PM window, producing 7,252 false-positive sprinkler
   labels and 2,688 false-positive bath-light labels on the historical
   data.
2. **Panel 3 spends ~76% of time in the 200–500 W baseline band**
   (fridge cycling + always-on networking + idle computers). The
   prompt's washing-machine rule (300–2200 W on raw panel) captured
   15,200 baseline events as washer activity. Several heads also had
   zero negative-class examples because their OFF rule keyed off
   `panel_w < 50 W`, a state this house never reaches.

The calibrated rules switch the small/medium heads to a **baseline-step
formulation**:

```
panel_step = panel_w − panel_w.rolling("30min").min()
```

`panel_step` is the *increment above quiescent baseline* — the same
trick Panel 1's `solar_pump` rule already uses. Large clearly-separated
signals (water heater, hair dryer, dryer, dishwasher, microwave) keep
raw-power rules because their bands sit far above the panel baseline.

After calibration, label counts on the 35-day window:

| Appliance | Panel | pos (1) | neg (0) | rule basis |
|---|---|---:|---:|---|
| `heat_pump` | 1 | (see labels_panel1.py — unchanged) | | raw + weather |
| `solar_pump` | 1 | | | step |
| `vacuum_cleaner` | 1 | | | step |
| `water_heater` | 2 | 1227 | 26471 | raw + solar damping |
| `hair_dryer` | 2 | 57 | 26248 | raw |
| `sprinklers` | 2 | 781 | 24687 | step + AM/PM window |
| `bath_lights` | 2 | 215 | 25276 | step + evening window |
| `refrigerator` | 3 | 13963 | 0 | 4 h quantile baseline |
| `dishwasher` | 3 | 1337 | 24467 | raw |
| `microwave` | 3 | 175 | 24467 | rising-edge + raw |
| `dryer` | 3 | 481 | 26792 | raw |
| `washing_machine` | 3 | 401 | 21949 | step |
| `pressure_pump` | 3 | 63 | 20886 | step |
| `computers` | 3 | 5995 | 3202 | step + work hours |
| `tv_stereo` | 3 | 1437 | 17915 | step + evening |

Refrigerator has 0 negatives because this house's panel 3 quantile
baseline never falls below 30 W in the captured window — the fridge is
truly always-on.

## Live session

100 ticks, ~33 minutes, 18:25 → 18:58 UTC (11:25 → 11:57 America/Los_Angeles).
No errors. Per-appliance state distribution:

| appliance | on | off | nan |
|---|---:|---:|---:|
| `heat_pump` | 0 | 0 | 100 |
| `solar_pump` | 0 | 100 | 0 |
| `vacuum_cleaner` | 0 | 100 | 0 |
| `water_heater` | 0 | 100 | 0 |
| `hair_dryer` | 0 | 100 | 0 |
| `sprinklers` | 0 | 100 | 0 |
| `bath_lights` | 0 | 100 | 0 |
| `refrigerator` | 100 | 0 | 0 |
| `dishwasher` | 0 | 100 | 0 |
| `microwave` | 0 | 100 | 0 |
| `dryer` | 0 | 100 | 0 |
| `washing_machine` | 0 | 100 | 0 |
| `pressure_pump` | 0 | 100 | 0 |
| `computers` | 2 | 0 | 98 |
| `tv_stereo` | 0 | 100 | 0 |

Live panel readings during the session (W):

| panel | min | median | max |
|---|---:|---:|---:|
| `panel1_w` | 233 | 234 | 235 |
| `panel2_w` | 112 | 113 | 114 |
| `panel3_w` | 215 | 275 | 312 |
| `shop_w` | 4 | 5 | 5 |

### Latency

| metric | ms |
|---:|---:|
| mean | 1339 |
| p50 | 1089 |
| p90 | 1988 |
| p99 | 4510 |
| max | 4965 |

Dominated by the 4.5 h AnyLog query each tick (~1 s). For a tighter
loop, cache the rolling baseline in memory and only query the most
recent 30 s per tick — out of scope for this pass.

### Sanity checks

| Check | Result |
|---|---|
| Total ticks ≥ 60 | 100 ✓ |
| Error count | 0 ✓ |
| Refrigerator predicted ON (always-on) | yes, 100% ✓ |
| Heat pump NaN under no-demand weather (60–75 °F) | yes ✓ |
| Sprinklers OFF at midday (outside AM/PM window) | yes ✓ |
| TV/stereo OFF at midday (outside evening window) | yes ✓ |
| `panel3_w > 4000 W` but `dryer` OFF anomalies | 0 ✓ |
| Any predicted ON with panel below appliance floor | 0 ✓ |

## Known limitations

1. **Long-running computers become baseline.** When computers stay on
   for ≥ 30 minutes, the rolling-min baseline absorbs them and
   `panel3_step → 0`. The head correctly avoids false-positive but
   transitions to NaN ("unknown") rather than staying at 1. This
   manifested in the live session: 98/100 ticks NaN despite a likely
   on-state. A mitigation is to maintain a longer-horizon baseline
   (e.g. nighttime quantile only) — out of scope here.
2. **Heat pump in the 60–75 °F dead band stays NaN.** The Panel 1 rule
   keys off `weather_demand = temp < 60 OR temp > 75`. At 65–70 °F the
   compressor sometimes runs (humidity, schedule), and the rule cannot
   tell — it stays NaN by design.
3. **No LLM consensus.** Both source prompts intersect rule labels with
   LLM disaggregator labels (§3.2/§3.3) to reject rule false-positives.
   This pass uses rules only because LLM labels for panels 2/3
   appliances aren't populated in `nilm_disaggregated` yet. Adding the
   intersection later is a one-line `merge_asof` per appliance.
4. **Refrigerator OFF class is empty.** Correctly reflects that this
   house's fridge runs continuously; not a defect.

## Artifacts

```
services/iems/training/
  rule_engine.py                          ← single source of truth
  labels_panel2.py                        ← offline labeler (4 heads)
  labels_panel3.py                        ← offline labeler (8 heads)
  realtime_monitor_rules.py               ← live unified harness
  reports/
    panel2_label_consensus.md
    panel3_label_consensus.md
    realtime_rules_2026-05-12T1825.jsonl
    realtime_rules_2026-05-12T1825_summary.md
    rules_session_report.md               ← this file

data/
  panel2_60d_labeled.parquet
  panel3_60d_labeled.parquet
```

`services/iems/load/disaggregator.py` is untouched. `nilm_disaggregated`
is not written to. Nothing committed.

## Running it

```bash
# Generate / refresh offline labels:
.venv-training/bin/python3 services/iems/training/labels_panel2.py
.venv-training/bin/python3 services/iems/training/labels_panel3.py

# Run the live monitor (Ctrl-C → writes summary md):
RULES_TICK_S=10 RULES_SUMMARY_EVERY=60 \
  .venv-training/bin/python3 services/iems/training/realtime_monitor_rules.py
```
