# Task: Build Panel 2 BiLSTM NILM Model

Hand this to Claude Code from inside the `microgrid-manager` working tree.
Phased, with explicit checkpoints — pause and report at each one.

This prompt mirrors the Panel 1 build. Run Panel 1 first if it has not been
done; the artifact layouts and conventions here assume the Panel 1 pipeline
is already in place.

---

## Objective

Build and train a BiLSTM model that predicts on/off state for the four
appliances on **Panel 2 (H2O)** — water heater, hair dryer, sprinklers, and
master bath mirror lights — then run it as a real-time monitoring harness
against the live Kafka → AnyLog stream. The harness logs every prediction
with a timestamp and tracks state-transition events per appliance.

Do not modify `services/iems/load/disaggregator.py`, do not write to
`nilm_disaggregated`, do not commit, do not push. Everything stays under
`services/iems/training/` and `services/iems/models/` as untracked local
artifacts.

**Panel 2 only.** Do not touch Panel 1, Panel 3, or Shop.

---

## Why Panel 2 is harder than Panel 1

- **Four appliances instead of two.** More heads, more interactions.
- **Two small-signal appliances overlap in power range.** Sprinklers
  (100–300W) and the master bath mirror light (100–300W) cannot be
  distinguished by power alone. The model must lean on **time-of-day** —
  sprinklers cluster in the early morning and evening; bath lights cluster
  in the evening/night and have variable duration.
- **Solar boiler interaction.** The water heater is solar-assisted. On
  high-irradiance, warm days, the tank is often pre-heated and the
  electric element rarely fires. Labels must encode this so the model
  doesn't learn "water heater fires every afternoon" when in fact it's
  the inverse.
- **Hair dryer bursts are short.** Often under 5 minutes. The
  16-minute window-midpoint labeling may dilute the positive class — flag
  but do not pre-emptively change the window size.

---

## Appliance spec (Panel 2)

From `docs/appliance_data_updated.txt`:

| Appliance | On threshold | Power range | Notes |
| --- | --- | --- | --- |
| Water heater | 500W | 2000–4000W | 240V element; solar-boiler-assisted |
| Hair dryer | 800W | 1200–1800W | Bathroom GFCI; bursts < 10 min |
| Sprinklers | 50W | 100–300W | Solenoid valves; early AM / early evening |
| Master bath mirror light | 80W | 100–300W | Incandescent; the only Panel 2 light load |

The pressure pump is **not** on Panel 2 — per the spec file annotation, it
is on Panel 3. Confirm this in Phase 1 against the labels in
`nilm_disaggregated`.

---

## Conventions — non-negotiable

- Read `CLAUDE.md` at the repo root before doing anything else. Follow it.
- Work on branch `hranjan` of `royshadmon/Microgrid-UCSC`.
- **No AI / Claude / Co-Authored-By attribution** in any commit message,
  README, code comment, or docstring.
- READMEs and docs: direct and imperative. No preamble.
- Use `127.0.0.1`, never `localhost`, in any Python or shell that hits
  Docker ports on this Mac.
- Direct AnyLog operator commands hit `http://127.0.0.1:32149` and **omit**
  the `destination: network` header.
- AnyLog responses wrap rows as `{"Query": [...]}`. Always extract `.Query`.
- Query partition tables directly:
  `par_<table>_<YYYY>_<MM>_00_d14_insert_timestamp`.
- `WHERE nm = 'Panel2 (H2O)'` returns empty because of the parentheses.
  Pull the time range without that filter and filter `nm` client-side.
- All new code lives under `services/iems/training/` and
  `services/iems/models/`. **Do not modify** any file under
  `services/iems/load/`. **Do not write** to `nilm_disaggregated`.

---

## Pre-flight

1. `cat ~/microgrid-manager/CLAUDE.md` and confirm the working rules match.

2. Confirm the Kafka pipeline is producing and AnyLog operator1 is a cluster
   member (per `README.html` §04). Run the standard restart sequence if not.

3. Confirm Panel 2 raw data is fresh (within the last 5 minutes):
   ```bash
   YM=$(date -u +%Y_%m)
   curl -s -H 'User-Agent: AnyLog/1.23' \
        -H "command: sql customers format=json and stat=false \
            \"SELECT MIN(ts) AS first, MAX(ts) AS last, COUNT(*) AS n \
            FROM par_egauge_kafka_${YM}_00_d14_insert_timestamp\"" \
        http://127.0.0.1:32149
   ```
   Then sanity-check that `Panel2 (H2O)` rows are present:
   ```bash
   curl -s -H 'User-Agent: AnyLog/1.23' \
        -H "command: sql customers format=json and stat=false \
            \"SELECT ts, nm, w FROM par_egauge_kafka_${YM}_00_d14_insert_timestamp \
            ORDER BY ts DESC LIMIT 200\"" \
        http://127.0.0.1:32149 | python3 -c \
     "import json,sys; rows=json.load(sys.stdin)['Query']; \
      print(sum(1 for r in rows if r['nm']=='Panel2 (H2O)'),'Panel2 rows')"
   ```

4. Confirm `nilm_disaggregated` has Panel 2 rows:
   ```bash
   curl -s -H 'User-Agent: AnyLog/1.23' \
        -H "command: sql customers format=json and stat=false \
            \"SELECT appliance, COUNT(*) AS n, SUM(state) AS on_count \
            FROM par_nilm_disaggregated_${YM}_00_d14_insert_timestamp \
            WHERE circuit = 'Panel2 (H2O)' GROUP BY appliance\"" \
        http://127.0.0.1:32149
   ```

5. Confirm the workspace and Panel 1 artifacts exist (the training pipeline
   needs them as reference, not as inputs):
   ```bash
   ls ~/microgrid-manager/services/iems/training/
   ls ~/microgrid-manager/services/iems/models/nilm_panel1_int8.onnx
   ```

6. Report status. **→ Checkpoint 1.**

---

## Phase 1 — Label inventory and comparison

### 1.1 Inventory script

Create `services/iems/training/scripts/panel2_label_inventory.py`. It must:

- Discover available `par_nilm_disaggregated_*` partitions for the last 3
  months.
- For each, run:
  ```sql
  SELECT appliance,
         COUNT(*)        AS rows,
         SUM(state)      AS on_count,
         MIN(ts)         AS first_ts,
         MAX(ts)         AS last_ts,
         AVG(confidence) AS avg_conf,
         AVG(avg_w)      AS avg_panel_w
  FROM   par_nilm_disaggregated_<YM>_00_d14_insert_timestamp
  WHERE  circuit = 'Panel2 (H2O)'
  GROUP  BY appliance
  ```
- Concatenate across months.
- Write to `services/iems/training/reports/panel2_label_inventory.md`.

### 1.2 Compare against the appliance spec

Create `services/iems/training/scripts/panel2_label_audit.py`. For each
labeled appliance on Panel 2, query a sample of 5,000 rows across partitions
and answer:

| Question | How to compute |
| --- | --- |
| Are all four spec appliances present in labels? | Cross-reference label list vs spec |
| Is anything labeled here that should be on Panel 3? | e.g. `pressure_pump`, `dishwasher`, `microwave`, `refrigerator` |
| Water heater false-positive (low) | `state=1` rows with `avg_w < 1000` |
| Water heater false-positive (high) | `state=1` rows with `avg_w > 4500` |
| Water heater false-negative | `state=0` rows with `avg_w > 2000` sustained |
| Solar damping in labels | Fraction of `water_heater=1` rows during `irradiance > 600 AND outside_temp > 65` — should be low if labels respect the solar boiler |
| Hair dryer duration | Median duration of contiguous `state=1` runs; expect 2–10 minutes |
| Sprinkler diurnal | Histogram by hour-of-day; expect clusters 04:00–07:00 and 17:00–21:00 |
| Bath light diurnal | Histogram by hour-of-day; expect 18:00–23:00 cluster, scattered daytime |
| Sprinkler vs light disambiguation | For rows where both are labeled OFF but `panel2_w` is in 100–300W and sustained, list time-of-day distribution |

Write to `services/iems/training/reports/panel2_label_audit.md`.

### 1.3 Report

**→ Checkpoint 2.** Pause and review. Specifically: if the audit shows
that any appliance is missing from labels, or that the solar damping is
absent (water heater fires evenly across irradiance bands), the rule labels
in Phase 3 will need to do extra work.

---

## Phase 2 — Pull training data

Create `services/iems/training/extract_panel2.py`. Mirror the Panel 1
extractor structure. Pull 60 days, month by month:

- **Power columns** from `egauge_kafka`: `Panel1 (HVAC)`, `Panel2 (H2O)`,
  `Panel3 (Kitchen)`, `Shop`, `Current on Utility Tie`. Filter `nm`
  client-side.
- **Weather**: outside temperature and shortwave irradiance for Los Gatos
  (37.2358°N, 121.9624°W) from Open-Meteo archive, 10-minute resolution.
- **Labels**: `ts, appliance, state, confidence, avg_w` from
  `nilm_disaggregated` partitions where `circuit = 'Panel2 (H2O)'`. Pivot
  so each appliance becomes a column.

Merge on timestamp, resample to a 10-second grid by mean aggregation,
backfill gaps with a one-step limit. Add time features:
`hour_sin, hour_cos, dow_sin, dow_cos`.

Write to `~/microgrid-manager/data/panel2_60d.parquet`. Print row count,
date range, and `df.describe()`.

```bash
cd ~/microgrid-manager
python3 services/iems/training/extract_panel2.py
```

**→ Checkpoint 3.**

---

## Phase 3 — Consensus labels

Create `services/iems/training/labels_panel2.py`. Produce four label
columns — `water_heater_label`, `hair_dryer_label`, `sprinklers_label`,
`bath_lights_label` — each in `{0, 1, NaN}`.

### 3.1 Rule labels

```python
p2     = df["Panel2 (H2O)"]
p2_60s = p2.rolling("60s").mean()
irr    = df["irradiance"]
temp   = df["outside_temp"]
hour   = df.index.hour

# Water heater (240V element, 2000–4000W)
rule_wh = NaN_series
rule_wh[(p2_60s > 2000) & (p2_60s < 4500)] = 1
rule_wh[p2 < 300] = 0
# Solar damping: if irradiance has been high and temp warm and WH has been
# OFF for ≥ 6h, prefer OFF unless a clear sustained > 2000W signal is present
solar_preheat = (irr.rolling("6h").mean() > 500) & (temp > 65)
rule_wh[(solar_preheat) & (p2_60s < 1500)] = 0

# Hair dryer (1200–1800W bursts, < 10 min typical)
rule_hd = NaN_series
rule_hd[(p2_60s > 1100) & (p2_60s < 1900) & (rule_wh != 1)] = 1
rule_hd[p2 < 300] = 0

# Sprinklers (100–300W, AM/PM clusters)
am_pm = ((hour >= 4) & (hour <= 7)) | ((hour >= 17) & (hour <= 21))
rule_spr = NaN_series
rule_spr[(p2_60s > 100) & (p2_60s < 320) & am_pm & (rule_wh != 1) & (rule_hd != 1)] = 1
# Outside the AM/PM window, sprinklers are unlikely
rule_spr[~am_pm & (p2_60s < 100)] = 0

# Bath mirror light (100–300W, evening cluster, but variable)
evening = (hour >= 18) | (hour <= 1)
rule_bl = NaN_series
rule_bl[(p2_60s > 100) & (p2_60s < 320) & evening
        & (rule_wh != 1) & (rule_hd != 1) & (rule_spr != 1)] = 1
rule_bl[p2 < 50] = 0
```

### 3.2 LLM label intersection

Time-align the per-appliance labels from `nilm_disaggregated` to the 10s
grid (nearest-neighbour join, 30s tolerance). For each row where the LLM
label and the rule label disagree on a positive call, drop the row to NaN.

### 3.3 Power-consistency check

For every row where rule and LLM agree on `state=1`, verify that the
contribution attributable to that appliance falls within its spec range
(use `avg_w` from the LLM label row as a proxy). If not, drop the row.

### 3.4 Final label

For each appliance, where rule and LLM agree → use it. Where the rule is
confident and the LLM is silent → use the rule. Where they disagree → NaN.

### 3.5 Reporting

Write `services/iems/training/reports/panel2_label_consensus.md`:

- Total labeled rows per appliance (0 / 1 / NaN)
- Class balance ratio per appliance
- Rows dropped at each filter stage
- Final positive-rate per appliance

**Stop and report if** sprinklers or bath lights have fewer than **300
positive examples** after consensus filtering. The small-signal appliances
need enough positives to learn or the model will collapse to predicting
always-OFF.

**→ Checkpoint 4.**

---

## Phase 4 — Windows

Create `services/iems/training/windows_panel2.py`.

- Window size: **100 timesteps** (~16 minutes at 10s cadence).
- Stride: 10 timesteps during training.
- Label is the value at the **window midpoint** (index 50) for each of the
  4 appliances.
- Drop windows where any of the four labels is NaN at the midpoint.
- 11 features per timestep (same column order as Panel 1):
  ```
  panel1_w, panel2_w, panel3_w, shop_w,
  outside_temp, irradiance,
  hour_sin, hour_cos, dow_sin, dow_cos,
  utility_tie_current
  ```
- Time-based split: first 70% / 10% / 20% by day. No random shuffling.
- Standardize using **training-split** mean/std only. Save to
  `services/iems/models/panel2_norm.json`.

Save tensors as `.npz` at `~/microgrid-manager/data/panel2_windows.npz`
with keys: `X_train, y_wh_train, y_hd_train, y_spr_train, y_bl_train,
X_val, y_wh_val, y_hd_val, y_spr_val, y_bl_val, X_test, y_wh_test,
y_hd_test, y_spr_test, y_bl_test`.

Report shapes and class balance per split. **→ Checkpoint 5.**

---

## Phase 5 — Train BiLSTM

### 5.1 Model definition

Create `services/iems/training/model_panel2.py`. Slightly larger than
Panel 1 because of the four heads:

```python
import torch, torch.nn as nn

class Panel2Net(nn.Module):
    def __init__(self, in_features=11):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_features, 32, kernel_size=5, padding=2),
            nn.BatchNorm1d(32), nn.ReLU(), nn.Dropout(0.1),
            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64), nn.ReLU(),
        )
        self.lstm1 = nn.LSTM(64, 96, batch_first=True, bidirectional=True)
        self.lstm2 = nn.LSTM(192, 48, batch_first=True, bidirectional=True)
        self.head = nn.Sequential(
            nn.Dropout(0.25),
            nn.Linear(96, 48), nn.ReLU(),
        )
        self.water_heater = nn.Linear(48, 1)
        self.hair_dryer   = nn.Linear(48, 1)
        self.sprinklers   = nn.Linear(48, 1)
        self.bath_lights  = nn.Linear(48, 1)

    def forward(self, x):                  # x: (B, T=100, F=11)
        h = self.conv(x.transpose(1, 2)).transpose(1, 2)
        h, _ = self.lstm1(h)
        h, _ = self.lstm2(h)
        h = h[:, -1, :]
        h = self.head(h)
        return (
            torch.sigmoid(self.water_heater(h)).squeeze(-1),
            torch.sigmoid(self.hair_dryer(h)).squeeze(-1),
            torch.sigmoid(self.sprinklers(h)).squeeze(-1),
            torch.sigmoid(self.bath_lights(h)).squeeze(-1),
        )
```

Parameter count target: ~110,000. Confirm with a print after construction.

### 5.2 Training script

Create `services/iems/training/train_panel2.py`:

- AdamW, `lr=1e-3`, `weight_decay=1e-4`.
- Batch size 256.
- **Weighted BCE** per head to account for class imbalance — compute
  `pos_weight = neg_count / pos_count` per appliance from the training split,
  pass to `BCEWithLogitsLoss(pos_weight=...)`. (Note: this means the heads
  return logits, not sigmoid outputs, during training — apply sigmoid only
  at eval and export. Adjust `forward()` accordingly with a `training_mode`
  flag or keep the sigmoid inside and use plain BCELoss with class weights
  baked into the loss reduction.)
- Loss = sum across heads of weighted BCE.
- Early stopping on **macro-average validation F1** across the four
  appliances. Patience 12 epochs. Max 120 epochs.
- Save best to `services/iems/models/nilm_panel2.pt`.
- Print per-epoch: train loss, val loss, val F1 per appliance, macro-F1.

Expected runtime on this Mac: 25–40 min on CPU.

**→ Checkpoint 6.** Report val F1 per appliance and the stopping epoch.

---

## Phase 6 — Export ONNX and quantize

Create `services/iems/training/export_panel2.py`. Same shape as Panel 1's
exporter — `torch.onnx.export` with `opset_version=17`, then
`quantize_dynamic` to int8.

Output: `services/iems/models/nilm_panel2.onnx` and
`services/iems/models/nilm_panel2_int8.onnx`. Report file sizes.

**→ Checkpoint 7.**

---

## Phase 7 — Validate (accuracy and latency)

Create `services/iems/training/eval_panel2.py`. Report per appliance on the
held-out test split: precision, recall, F1, confusion matrix. Then
benchmark single-window latency over 10,000 inferences.

Write metrics to `services/iems/training/reports/panel2_eval.md`.

### Acceptance bars

| Appliance | F1 target | Notes |
| --- | --- | --- |
| Water heater | ≥ 0.90 | Easiest — dominant signal on the panel |
| Hair dryer | ≥ 0.75 | Short bursts; window-midpoint label dilutes positives |
| Sprinklers | ≥ 0.70 | Small signal, time-of-day driven |
| Master bath light | ≥ 0.65 | Smallest signal, sparse positives |
| p99 latency, int8 ONNX, single window | ≤ 2.5 ms | Larger than Panel 1's bar because the model is bigger |

**→ Checkpoint 8.** If any bar is missed, stop and report. The most likely
culprit on a miss is the consensus labels — Panel 2's small-signal
appliances are easy to mislabel. Re-examine the audit before retraining.

---

## Phase 8 — Real-time monitoring harness

Create `services/iems/training/realtime_monitor_panel2.py`. Same structure
as Panel 1's monitor but with four appliances. It does **not** call the
existing disaggregator, does **not** write to `nilm_disaggregated`, and
does **not** import anything from `services/iems/load/`.

### 8.1 Initialization

```python
import json, signal, sys, time, os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, onnxruntime as ort

TICK_S        = int(os.environ.get("PANEL2_TICK_S", 10))
SUMMARY_EVERY = int(os.environ.get("PANEL2_SUMMARY_EVERY", 60))
WIN           = 100
APPLIANCES    = ["water_heater", "hair_dryer", "sprinklers", "bath_lights"]
ANYLOG        = "http://127.0.0.1:32149"

MODEL_DIR  = Path(__file__).resolve().parents[1] / "models"
REPORT_DIR = Path(__file__).resolve().parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)

stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
event_log  = REPORT_DIR / f"realtime_panel2_{stamp}.jsonl"
summary_md = REPORT_DIR / f"realtime_panel2_{stamp}_summary.md"

sess = ort.InferenceSession(str(MODEL_DIR / "nilm_panel2_int8.onnx"),
                            providers=["CPUExecutionProvider"])
norm = json.loads((MODEL_DIR / "panel2_norm.json").read_text())
mean = np.array(norm["mean"], dtype=np.float32)
std  = np.array(norm["std"],  dtype=np.float32)
buf  = np.empty((1, WIN, 11), dtype=np.float32)

prev = {a: None for a in APPLIANCES}
counters = {a: {"on": 0, "off": 0, "off_to_on": 0, "on_to_off": 0}
            for a in APPLIANCES}
latencies = deque(maxlen=1000)
ticks = 0
```

### 8.2 Each tick

```python
def fetch_window():
    """Last 16 minutes of Panel1/2/3/Shop/utility from egauge_kafka,
       weather (cached, 5-min refresh), time encodings. Return (100, 11)
       ndarray in the exact column order used at training time."""
    ...

def tick():
    global ticks
    t0 = time.perf_counter()
    feats = fetch_window()
    buf[0] = (feats - mean) / std
    outs = sess.run(None, {"window": buf})        # list of 4 arrays
    latency_ms = (time.perf_counter() - t0) * 1000
    latencies.append(latency_ms)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    states = {a: int(outs[i][0] > 0.5) for i, a in enumerate(APPLIANCES)}
    probs  = {a: float(outs[i][0])     for i, a in enumerate(APPLIANCES)}

    event = {"ts": now, "panel2_w": float(feats[-1, 1]),
             "outside_temp": float(feats[-1, 4]),
             "irradiance":   float(feats[-1, 5]),
             "latency_ms":   round(latency_ms, 3)}
    for a in APPLIANCES:
        old = prev[a]
        prev[a] = states[a]
        t = None
        if old is not None and old != states[a]:
            t = "off_to_on" if states[a] == 1 else "on_to_off"
            counters[a][t] += 1
        counters[a]["on" if states[a] else "off"] += 1
        event[a] = {"state": states[a], "prob": probs[a], "transition": t}

    with event_log.open("a") as f:
        f.write(json.dumps(event) + "\n")

    short = " ".join(f"{a.split('_')[0][:3]}={states[a]}({probs[a]:.2f})"
                     for a in APPLIANCES)
    print(f"{now}  {short}  p2={feats[-1,1]:5.0f}W  {latency_ms:.2f}ms",
          flush=True)
    ticks += 1
```

### 8.3 Periodic summary

Every `SUMMARY_EVERY` ticks, print per-appliance ON/OFF tick counts,
percentages, and transition counts, plus latency percentiles. Same format
as Panel 1's monitor, extended to four rows.

### 8.4 Graceful shutdown

SIGINT handler writes `summary_md` with the same content as the periodic
summary plus session start/end timestamps and total ticks.

### 8.5 Dry run

```bash
cd ~/microgrid-manager
python3 services/iems/training/realtime_monitor_panel2.py
```

Let it run for 60 ticks. Confirm one prediction line per tick, the first
summary block at tick 60, the jsonl growing monotonically, no errors, and
latency below 3 ms.

**→ Checkpoint 9.** Show me the first summary block and the last 10 jsonl
lines.

---

## Phase 9 — Live test session

Run continuously for **at least one hour**. Watch the output.

```bash
cd ~/microgrid-manager
python3 services/iems/training/realtime_monitor_panel2.py 2>&1 | tee \
  services/iems/training/reports/realtime_panel2_$(date -u +%Y-%m-%dT%H%M)_stdout.log
```

### During the session

Watch for:

- Water heater: 0–4 transitions per hour. **Zero is normal** if the day is
  sunny and the solar boiler has the tank up to temperature. Many
  transitions on a cold cloudy morning.
- Hair dryer: 0–2 transitions per hour; clusters morning and evening; brief
  on-periods of a few ticks.
- Sprinklers: 0–1 transitions per hour, only inside the AM (04:00–07:00) or
  PM (17:00–21:00) windows. Outside those windows, expect zero.
- Bath light: 0–4 transitions per hour, mostly evening.
- Cross-appliance sanity: if `panel2_w` is reading > 2000W and water_heater
  is OFF in the prediction, that's a misclassification worth noting. Same
  inverse: if `panel2_w` is below 100W and any appliance is ON, that's a
  misclassification.

### Session report

Stop the monitor with Ctrl-C. Build
`services/iems/training/reports/panel2_first_session.md`:

- Session duration, total ticks
- Per appliance: ON/OFF ticks, ON-fraction, transition counts
- Hour-of-day transition histogram for each appliance
- Mean / p50 / p99 latency
- Anomalies — list any tick where `panel2_w` and the predicted states
  disagree obviously (criterion above)
- A paragraph reconciling observed behavior with the appliance spec,
  specifically the solar-damping question for water heater

### Acceptance

| Check | Target |
| --- | --- |
| Session duration | ≥ 1 hour |
| Total ticks at 10s tick | ≥ 360 |
| Error count | 0 |
| p99 latency over the full session | ≤ 3 ms |
| Water heater transitions per hour | within 0–6 |
| Hair dryer transitions per hour | within 0–4 |
| Sprinkler transitions per hour | 0 outside AM/PM windows, 0–2 inside |
| Bath light transitions per hour | within 0–8 |

**→ Checkpoint 10.** Show me `panel2_first_session.md` and the last summary
block from stdout.

**Do not commit. Do not push. Do not modify `disaggregator.py`. Do not
write to `nilm_disaggregated`.**

---

## Output artifacts

When this task is complete, the following exist locally (none committed):

```
services/iems/training/
  extract_panel2.py
  labels_panel2.py
  windows_panel2.py
  model_panel2.py
  train_panel2.py
  export_panel2.py
  eval_panel2.py
  realtime_monitor_panel2.py
  scripts/
    panel2_label_inventory.py
    panel2_label_audit.py
  reports/
    panel2_label_inventory.md
    panel2_label_audit.md
    panel2_label_consensus.md
    panel2_eval.md
    realtime_panel2_<stamp>.jsonl
    realtime_panel2_<stamp>_summary.md
    realtime_panel2_<stamp>_stdout.log
    panel2_first_session.md

services/iems/models/
  nilm_panel2.pt
  nilm_panel2.onnx
  nilm_panel2_int8.onnx
  panel2_norm.json
```

`services/iems/load/disaggregator.py` is untouched. `nilm_disaggregated` is
untouched. Nothing is staged for commit.
