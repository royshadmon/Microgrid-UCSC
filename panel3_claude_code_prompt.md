# Task: Build Panel 3 BiLSTM NILM Model

Hand this to Claude Code from inside the `microgrid-manager` working tree.
Phased, with explicit checkpoints — pause and report at each one.

This is the hardest of the three panel models. Run Panel 1 and Panel 2
first; the artifact layouts and conventions here assume both are already in
place.

---

## Objective

Build and train a BiLSTM model that predicts on/off state for the eight
appliances on **Panel 3 (Kitchen)** — refrigerator, dishwasher, microwave,
dryer, washing machine, pressure pump, computers, and TV/stereo — then run
it as a real-time monitoring harness against the live Kafka → AnyLog stream.
The harness logs every prediction with a timestamp and tracks state-
transition events per appliance.

Do not modify `services/iems/load/disaggregator.py`, do not write to
`nilm_disaggregated`, do not commit, do not push. Everything stays under
`services/iems/training/` and `services/iems/models/` as untracked local
artifacts.

**Panel 3 only.** Do not touch Panel 1, Panel 2, or Shop.

---

## Why Panel 3 is the hardest panel

- **Eight appliances on one panel.** Aggregate signal is the sum of up to
  eight overlapping loads, several of which sit in similar power ranges.
- **Refrigerator is always cycling.** It is the dominant always-on load —
  roughly 50–70% of all 10-second samples will have the fridge ON. This
  changes class balance and means the model has to learn to keep predicting
  fridge ON underneath other appliances.
- **Updated panel assignments.** The spec file moves **dryer**, **washing
  machine**, and **pressure pump** from Shop to Panel 3. The existing
  `nilm_disaggregated` labels may still tag these on Shop. Phase 1 has to
  detect and account for that.
- **Sequential dependencies.** Washer → dryer is a real coupling. Pressure
  pump cycles often correlate with dishwasher or washing-machine starts
  (water demand) and with sprinkler events on Panel 2 (cross-panel).
- **Bursty short-cycle appliances.** Microwave bursts are often under 2
  minutes — at the window-midpoint labeling approach, many positive
  instances are diluted. Microwave F1 will be the lowest of the eight.
- **Small-signal overlap.** TV/stereo (100–200W) and computers (200–500W)
  overlap in range. Time-of-day is the primary discriminator: computers
  daytime/working hours, TV evening.
- **Cooktop and oven are mentioned in the spec** but rarely fire and may
  have insufficient positive examples to train a dedicated head. Phase 1
  decides whether to include cooktop as a ninth head.

---

## Appliance spec (Panel 3)

From `docs/appliance_data_updated.txt`:

| Appliance | On threshold | Power range | Notes |
| --- | --- | --- | --- |
| Refrigerator | 50W | 80–200W | Always cycling; spec also lists garage fridge and garage freezer as auxiliary refrigeration on Panel 3 |
| Dishwasher | 50W | 200–1800W | Multi-stage cycle (heater, pump, dry) |
| Microwave | 200W | 900–1500W | Short bursts (often < 2 min) |
| Dryer | 1000W | 4000–7000W | 240V, distinctive large signal |
| Washing machine | 50W | 200–2000W | Multi-stage (agitate, spin) |
| Pressure pump | 200W | 500–1000W | Intermittent; correlates with water-using appliances |
| Computers (aggregated) | 100W | 200–500W | Daytime cluster |
| TV/stereo | 80W | 100–200W | Evening cluster |

Out of scope for this build (mentioned in the spec but no clean per-circuit
labels expected): cooktop, oven, toaster, toaster oven, coffee maker, iron.

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
- `WHERE nm = 'Panel3 (Kitchen)'` returns empty because of the parentheses.
  Pull the time range without that filter and filter `nm` client-side.
- All new code lives under `services/iems/training/` and
  `services/iems/models/`. **Do not modify** any file under
  `services/iems/load/`. **Do not write** to `nilm_disaggregated`.

---

## Pre-flight

1. `cat ~/microgrid-manager/CLAUDE.md` and confirm.

2. Confirm Kafka pipeline is producing and AnyLog operator1 is a cluster
   member (per `README.html` §04). Run the standard restart sequence if
   needed.

3. Confirm Panel 3 raw data is fresh and rows are present:
   ```bash
   YM=$(date -u +%Y_%m)
   curl -s -H 'User-Agent: AnyLog/1.23' \
        -H "command: sql customers format=json and stat=false \
            \"SELECT ts, nm, w FROM par_egauge_kafka_${YM}_00_d14_insert_timestamp \
            ORDER BY ts DESC LIMIT 500\"" \
        http://127.0.0.1:32149 | python3 -c \
     "import json,sys; rows=json.load(sys.stdin)['Query']; \
      from collections import Counter; \
      c=Counter(r['nm'] for r in rows); \
      print('Panel3:', c.get('Panel3 (Kitchen)',0),' Shop:', c.get('Shop',0))"
   ```

4. Inventory **all panels' labels** for the appliances we expect on Panel 3.
   The labels may currently still be tagged under `Shop` for dryer,
   washing_machine, and pressure_pump:
   ```bash
   curl -s -H 'User-Agent: AnyLog/1.23' \
        -H "command: sql customers format=json and stat=false \
            \"SELECT circuit, appliance, COUNT(*) AS n \
            FROM par_nilm_disaggregated_${YM}_00_d14_insert_timestamp \
            WHERE appliance IN ('refrigerator','dishwasher','microwave','dryer', \
                                'washing_machine','pressure_pump','computers','tv_stereo') \
            GROUP BY circuit, appliance ORDER BY appliance, circuit\"" \
        http://127.0.0.1:32149
   ```

5. Confirm the workspace and Panel 1/2 artifacts exist:
   ```bash
   ls ~/microgrid-manager/services/iems/models/nilm_panel{1,2}_int8.onnx
   ```

6. Report status. **→ Checkpoint 1.**

---

## Phase 1 — Label inventory and comparison

### 1.1 Inventory script

Create `services/iems/training/scripts/panel3_label_inventory.py`. Pull
**both** `circuit = 'Panel3 (Kitchen)'` and `circuit = 'Shop'` rows for the
last 3 months. For each (circuit, appliance) pair:

```sql
SELECT circuit, appliance,
       COUNT(*)        AS rows,
       SUM(state)      AS on_count,
       MIN(ts)         AS first_ts,
       MAX(ts)         AS last_ts,
       AVG(confidence) AS avg_conf,
       AVG(avg_w)      AS avg_circuit_w
FROM   par_nilm_disaggregated_<YM>_00_d14_insert_timestamp
WHERE  circuit IN ('Panel3 (Kitchen)','Shop')
GROUP  BY circuit, appliance
```

Write to `services/iems/training/reports/panel3_label_inventory.md`.
**Specifically flag** any appliance from the Panel 3 spec that is currently
labeled under `circuit = 'Shop'`. Those labels need to be re-tagged in
Phase 3 because the panel assignment has changed.

### 1.2 Audit script

Create `services/iems/training/scripts/panel3_label_audit.py`. For each
labeled appliance, query 5,000 sample rows and answer:

| Question | How to compute |
| --- | --- |
| Are all 8 spec appliances present? | Cross-reference vs spec |
| Cooktop labels present and how many positive examples? | Count `appliance='cooktop' AND state=1` rows; threshold for inclusion: ≥ 500 |
| Refrigerator ON-fraction | `SUM(state) / COUNT(*)` — expect 0.50–0.75 |
| Dryer / washer / pressure_pump on Shop vs Panel 3 | Count rows per circuit |
| Dryer false-positive (high) | `state=1 AND avg_w > 8000` |
| Dryer false-negative | `state=0 AND avg_w > 3000` sustained |
| Microwave ON-duration distribution | Histogram of contiguous `state=1` run lengths (in seconds); expect mode 30s–120s |
| Dishwasher cycle-duration distribution | Histogram of contiguous `state=1` runs; expect mode 30 min–90 min |
| Washer → dryer sequence | Fraction of dryer-ON events preceded by a washer-ON event in the prior 90 minutes |
| TV vs computers separability | Count rows where both are labeled OFF but `avg_circuit_w` is in 100–500W range, broken down by hour-of-day |
| Pressure pump correlation with sprinklers | Cross-reference `pressure_pump=1` rows against Panel 2 `sprinklers=1` rows at the same `ts` |

Write to `services/iems/training/reports/panel3_label_audit.md`.

### 1.3 Decision on cooktop

If the audit shows ≥ 500 positive `cooktop` examples, add it as a ninth
head in Phase 5 and adjust all downstream phases accordingly. Otherwise,
proceed with 8 heads and note cooktop in the report as a rule-only label
for future work.

**→ Checkpoint 2.** Pause and review. Do not proceed if more than two
appliances have fewer than 300 positive examples — that's a labeling
problem to address before training.

---

## Phase 2 — Pull training data

Create `services/iems/training/extract_panel3.py`. Pull 60 days, month by
month:

- **Power columns** from `egauge_kafka`: `Panel1 (HVAC)`, `Panel2 (H2O)`,
  `Panel3 (Kitchen)`, `Shop`, `Current on Utility Tie`.
- **Weather**: outside temperature and shortwave irradiance for Los Gatos
  from Open-Meteo archive, 10-minute resolution.
- **Labels**: pull from **both** `circuit = 'Panel3 (Kitchen)'` and
  `circuit = 'Shop'`. For appliances that the spec says belong on Panel 3
  (dryer, washing_machine, pressure_pump), the Shop-circuit labels are
  still valid training signal — the panel reassignment is administrative.

Merge on timestamp, resample to a 10-second grid by mean aggregation,
backfill gaps with a one-step limit. Add time features.

Write to `~/microgrid-manager/data/panel3_60d.parquet`. Print row count,
date range, and `df.describe()`.

```bash
cd ~/microgrid-manager
python3 services/iems/training/extract_panel3.py
```

**→ Checkpoint 3.**

---

## Phase 3 — Consensus labels

Create `services/iems/training/labels_panel3.py`. Produce eight (or nine,
with cooktop) label columns in `{0, 1, NaN}`.

### 3.1 Rule labels

Apply in order. Larger/more distinctive appliances first so smaller ones
can be conditioned on the absence of the bigger ones.

```python
p3       = df["Panel3 (Kitchen)"]
p3_60s   = p3.rolling("60s").mean()
p3_delta = p3.diff()
irr      = df["irradiance"]
hour     = df.index.hour

# Dryer (4000–7000W, distinctive)
rule_dryer = NaN_series
rule_dryer[(p3_60s > 3500) & (p3_60s < 7500)] = 1
rule_dryer[p3 < 500] = 0

# Microwave (900–1500W bursts, < 5 min typical)
# Use rising-edge detection because window-midpoint loses short bursts
rising_mw = (p3_delta > 600) & (p3_60s > 800) & (p3_60s < 1700)
rule_mw = NaN_series
rule_mw[rising_mw & (rule_dryer != 1)] = 1
rule_mw[p3 < 200] = 0

# Dishwasher (200–1800W, multi-stage, 30–90 min runs)
# Stage-1 heat element is the easiest signature; stage-2 pump is hard
rule_dw = NaN_series
rule_dw[(p3_60s > 1000) & (p3_60s < 2000) & (rule_dryer != 1) & (rule_mw != 1)] = 1
rule_dw[p3 < 50] = 0

# Washing machine (200–2000W, multi-stage, 20–60 min)
rule_wm = NaN_series
rule_wm[(p3_60s > 300) & (p3_60s < 2200) & (rule_dryer != 1)
        & (rule_mw != 1) & (rule_dw != 1)] = 1
rule_wm[p3 < 50] = 0

# Pressure pump (500–1000W, intermittent short cycles)
rule_pp = NaN_series
rule_pp[(p3_60s > 400) & (p3_60s < 1100) & (rule_dryer != 1)
        & (rule_mw != 1) & (rule_dw != 1) & (rule_wm != 1)] = 1
rule_pp[p3 < 50] = 0

# Refrigerator (80–200W cycling, the always-on baseline)
# Hardest part: must be ON even when other appliances are also ON.
# Use a long rolling minimum to estimate "what's left when the big stuff
# is off" and treat fridge as ON when residual is in its range.
p3_baseline = p3.rolling("4h").quantile(0.1)
rule_fridge = NaN_series
rule_fridge[(p3_baseline > 50) & (p3_baseline < 250)] = 1
rule_fridge[p3 < 20] = 0

# Computers (200–500W, working-hours cluster)
work_hours = (hour >= 7) & (hour <= 22)
rule_comp = NaN_series
rule_comp[(p3 > 150) & (p3 < 600) & work_hours
          & (rule_dryer != 1) & (rule_mw != 1) & (rule_dw != 1)
          & (rule_wm != 1) & (rule_pp != 1)] = 1
rule_comp[p3 < 50] = 0

# TV/stereo (100–200W, evening cluster)
evening = (hour >= 17) | (hour <= 1)
rule_tv = NaN_series
rule_tv[(p3 > 80) & (p3 < 250) & evening
        & (rule_dryer != 1) & (rule_mw != 1) & (rule_dw != 1)
        & (rule_wm != 1) & (rule_pp != 1) & (rule_comp != 1)] = 1
rule_tv[p3 < 50] = 0

# Optional: cooktop (240V, very rare positive class)
# Apply only if Phase 1 decided to include it.
```

### 3.2 Sequential constraint refinement

After base rules, apply the washer → dryer sequence rule:

```python
# A dryer-ON labeled positive should typically be preceded by a washer-ON
# event in the prior 90 minutes. If not, the LLM label is suspect.
washer_recent = rule_wm.rolling("90min").max()   # 1 if washer was ON anywhere in the window
suspect_dryer = (rule_dryer == 1) & (washer_recent.fillna(0) < 1)
# Downgrade — drop these from training rather than forcing 0
rule_dryer[suspect_dryer] = NaN
```

### 3.3 LLM label intersection

For each appliance, time-align the LLM labels to the 10s grid. Treat
**Shop-circuit labels for dryer, washing_machine, pressure_pump as valid
Panel 3 signal**. Intersect with rule labels: where they agree, keep; where
they disagree on a positive call, drop to NaN.

### 3.4 Final label and reporting

Write `services/iems/training/reports/panel3_label_consensus.md`:

- Per appliance: total labeled rows (0 / 1 / NaN), class balance, positive
  rate
- Rows dropped at each filter stage
- Sequential-constraint dropouts (number of suspect dryer events removed)
- Cross-circuit accounting (how many positive examples came from Shop vs
  Panel 3 for the three reassigned appliances)

**Stop and report if any appliance has fewer than 200 positive examples**
after consensus filtering. Smaller is unworkable for an 8-head model and
the head will collapse to always-OFF.

**→ Checkpoint 4.**

---

## Phase 4 — Windows

Create `services/iems/training/windows_panel3.py`.

- Window size: **100 timesteps** (~16 minutes at 10s cadence).
- Stride: 10 timesteps during training.
- Label is the value at the **window midpoint** for each appliance.
- Drop windows where any label is NaN at the midpoint.
- 11 features per timestep (same column order as Panel 1 and 2):
  ```
  panel1_w, panel2_w, panel3_w, shop_w,
  outside_temp, irradiance,
  hour_sin, hour_cos, dow_sin, dow_cos,
  utility_tie_current
  ```
- Time-based split: 70 / 10 / 20 by day. No random shuffling.
- Standardize using **training-split** statistics only. Save to
  `services/iems/models/panel3_norm.json`.

Save tensors as `.npz` at `~/microgrid-manager/data/panel3_windows.npz`
with one `y_<appliance>_<split>` key per (appliance, split) pair.

Report shapes and per-appliance class balance per split. **→ Checkpoint 5.**

---

## Phase 5 — Train BiLSTM

### 5.1 Model definition

Create `services/iems/training/model_panel3.py`. Larger than Panels 1 and 2
because of the eight heads:

```python
import torch, torch.nn as nn

APPLIANCES = [
    "refrigerator", "dishwasher", "microwave", "dryer",
    "washing_machine", "pressure_pump", "computers", "tv_stereo",
    # add "cooktop" here if Phase 1 included it
]

class Panel3Net(nn.Module):
    def __init__(self, in_features=11, appliances=APPLIANCES):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_features, 32, kernel_size=5, padding=2),
            nn.BatchNorm1d(32), nn.ReLU(), nn.Dropout(0.1),
            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64), nn.ReLU(),
            nn.Conv1d(64, 96, kernel_size=3, padding=1),
            nn.BatchNorm1d(96), nn.ReLU(),
        )
        self.lstm1 = nn.LSTM(96, 128, batch_first=True, bidirectional=True)
        self.lstm2 = nn.LSTM(256, 64, batch_first=True, bidirectional=True)
        self.shared = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(128, 64), nn.ReLU(),
        )
        self.heads = nn.ModuleDict({a: nn.Linear(64, 1) for a in appliances})
        self.appliances = appliances

    def forward(self, x):                  # x: (B, T=100, F=11)
        h = self.conv(x.transpose(1, 2)).transpose(1, 2)
        h, _ = self.lstm1(h)
        h, _ = self.lstm2(h)
        h = h[:, -1, :]
        h = self.shared(h)
        return {a: torch.sigmoid(self.heads[a](h)).squeeze(-1)
                for a in self.appliances}
```

Parameter count target: ~200,000–220,000. Confirm with a print after
construction.

### 5.2 Training script

Create `services/iems/training/train_panel3.py`:

- AdamW, `lr=1e-3`, `weight_decay=1e-4`.
- Batch size 256.
- **Weighted BCE per head.** Compute `pos_weight = neg_count / pos_count`
  per appliance from the training split, pass to
  `BCEWithLogitsLoss(pos_weight=...)` per head. (Either return logits from
  the model during training and apply sigmoid at eval/export, or use
  `BCELoss` with sample-weight tensors — pick one and stay consistent.)
- Loss = sum across heads of weighted BCE. Optionally normalize by number of
  heads.
- Early stopping on **macro-average validation F1** across all heads.
  Patience 15 epochs. Max 150 epochs.
- Save best to `services/iems/models/nilm_panel3.pt`.
- Print per-epoch: train loss, val loss, val F1 per appliance, macro-F1.

Expected runtime on this Mac: 45–75 min on CPU. Be patient.

**→ Checkpoint 6.** Report val F1 per appliance and the stopping epoch.

---

## Phase 6 — Export ONNX and quantize

Create `services/iems/training/export_panel3.py`. Same pattern as Panel 1
and Panel 2: `torch.onnx.export` with `opset_version=17`, then
`quantize_dynamic` to int8.

Output: `services/iems/models/nilm_panel3.onnx` and
`services/iems/models/nilm_panel3_int8.onnx`. Report file sizes.

Because the model has a dict output, declare `output_names` as a flat list
in the appliance order used by the model:

```python
output_names = list(model.appliances)
```

**→ Checkpoint 7.**

---

## Phase 7 — Validate (accuracy and latency)

Create `services/iems/training/eval_panel3.py`. Per appliance on the
held-out test split: precision, recall, F1, confusion matrix. Latency
benchmark: 10,000 single-window inferences, report mean / p50 / p99.

Write metrics to `services/iems/training/reports/panel3_eval.md`.

### Acceptance bars

These are deliberately looser than Panel 1 and Panel 2 because the panel is
genuinely harder. Hitting all of them on the first training run would be
remarkable.

| Appliance | F1 target | Reason |
| --- | --- | --- |
| Dryer | ≥ 0.85 | Large distinctive signal |
| Refrigerator | ≥ 0.85 | Lots of data; main risk is overconfident predictions when other loads spike |
| Pressure pump | ≥ 0.70 | Intermittent but distinctive mid-range signal |
| Washing machine | ≥ 0.65 | Multi-stage; agitation phase is hard |
| Dishwasher | ≥ 0.65 | Multi-stage; pump phase overlaps with washer ranges |
| Computers | ≥ 0.55 | Small signal, overlaps with TV |
| TV/stereo | ≥ 0.55 | Smallest signal, overlaps with computers |
| Microwave | ≥ 0.55 | Bursty; window-midpoint label loses many positives |
| p99 latency, int8 ONNX, single window | ≤ 4 ms | Largest model of the three |

If any appliance misses its bar by more than 0.10, stop and report rather
than re-training blindly. Common root causes:

- Microwave miss → window size is too large. Consider a 50-step window
  variant in a follow-up pass.
- Computers / TV miss → the time-of-day feature engineering is doing all
  the discrimination and the model isn't seeing enough other signal. Check
  per-hour F1 to confirm.
- Dishwasher miss → multi-stage signature requires more sequence context.
  Try return_sequences=True and per-timestep loss on dishwasher only.

**→ Checkpoint 8.**

---

## Phase 8 — Real-time monitoring harness

Create `services/iems/training/realtime_monitor_panel3.py`. Same skeleton
as Panel 1 and Panel 2, extended to eight appliances. Does **not** call
the existing disaggregator, does **not** write to `nilm_disaggregated`, and
does **not** import anything from `services/iems/load/`.

### 8.1 Initialization

```python
import json, signal, sys, time, os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, onnxruntime as ort

TICK_S        = int(os.environ.get("PANEL3_TICK_S", 10))
SUMMARY_EVERY = int(os.environ.get("PANEL3_SUMMARY_EVERY", 60))
WIN           = 100
APPLIANCES    = ["refrigerator", "dishwasher", "microwave", "dryer",
                 "washing_machine", "pressure_pump", "computers", "tv_stereo"]
ANYLOG        = "http://127.0.0.1:32149"

MODEL_DIR  = Path(__file__).resolve().parents[1] / "models"
REPORT_DIR = Path(__file__).resolve().parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)

stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
event_log  = REPORT_DIR / f"realtime_panel3_{stamp}.jsonl"
summary_md = REPORT_DIR / f"realtime_panel3_{stamp}_summary.md"

sess = ort.InferenceSession(str(MODEL_DIR / "nilm_panel3_int8.onnx"),
                            providers=["CPUExecutionProvider"])
norm = json.loads((MODEL_DIR / "panel3_norm.json").read_text())
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
    outs = sess.run(None, {"window": buf})        # list, one array per head
    latency_ms = (time.perf_counter() - t0) * 1000
    latencies.append(latency_ms)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    states = {a: int(outs[i][0] > 0.5) for i, a in enumerate(APPLIANCES)}
    probs  = {a: float(outs[i][0])     for i, a in enumerate(APPLIANCES)}

    event = {"ts": now,
             "panel3_w":     float(feats[-1, 2]),
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

    # compact stdout — show only currently-ON appliances
    on_now = [a for a in APPLIANCES if states[a] == 1]
    on_str = ",".join(a[:3] for a in on_now) or "(none)"
    transitions_now = [a for a in APPLIANCES if event[a]["transition"]]
    trans_str = " ".join(f"{a[:3]}:{event[a]['transition']}"
                         for a in transitions_now)
    print(f"{now}  ON: {on_str:30}  p3={feats[-1,2]:5.0f}W  "
          f"{latency_ms:.2f}ms  {trans_str}", flush=True)
    ticks += 1
```

### 8.3 Periodic summary

Every `SUMMARY_EVERY` ticks, print per-appliance ON/OFF tick counts,
percentages, and transition counts, plus latency percentiles. Eight rows
of appliance summary plus the latency row.

### 8.4 Graceful shutdown

SIGINT handler writes `summary_md` with session start/end, total ticks,
and the final per-appliance counters.

### 8.5 Dry run

```bash
cd ~/microgrid-manager
python3 services/iems/training/realtime_monitor_panel3.py
```

Run for 60 ticks. Confirm:

- Stdout shows one prediction line per tick, in the compact format
- First summary block at tick 60
- jsonl grows by one line per tick
- No errors in stderr
- Latency stays under 5 ms

**→ Checkpoint 9.**

---

## Phase 9 — Live test session

Run continuously for **at least one hour**, ideally two — Panel 3 has more
infrequent appliances (dishwasher full cycles, dryer cycles) that may not
fire in a single hour.

```bash
cd ~/microgrid-manager
python3 services/iems/training/realtime_monitor_panel3.py 2>&1 | tee \
  services/iems/training/reports/realtime_panel3_$(date -u +%Y-%m-%dT%H%M)_stdout.log
```

### Expected behavior

Watch for these per-hour transition counts:

| Appliance | Transitions/hour | Notes |
| --- | --- | --- |
| Refrigerator | 6–20 | Compressor cycling; the noisiest appliance on the panel |
| Dryer | 0–2 | Only fires during laundry sessions |
| Microwave | 0–4 | Clusters at meal times; off→on quickly followed by on→off |
| Dishwasher | 0–1 | Full cycle is one off→on and one on→off, 30–90 min apart |
| Washing machine | 0–2 | Cycle is one off→on, one on→off, 20–60 min apart |
| Pressure pump | 0–6 | Correlated with water-using appliances and Panel 2 sprinklers |
| Computers | 0–4 | Mostly daytime |
| TV/stereo | 0–4 | Mostly evening |

Cross-checks to call out as anomalies:

- `panel3_w > 4000` but dryer predicted OFF → likely misclassification
- `panel3_w < 50` but any appliance predicted ON → likely false positive
- Dryer ON with no washer ON in prior 90 min → suspect (the
  sequential-constraint case)
- Pressure pump ON for more than 10 consecutive ticks (100s) → unusual;
  pump cycles are typically short

### Session report

Stop with Ctrl-C. Build
`services/iems/training/reports/panel3_first_session.md`:

- Session duration, total ticks
- Per appliance: ON/OFF ticks, ON-fraction, transition counts, mean
  contiguous-ON-run length (in ticks)
- Hour-of-day transition histogram per appliance
- Latency mean / p50 / p99
- Cross-check anomalies — list every tick that triggered one of the
  conditions above, with timestamps
- Washer → dryer sequence audit: did any predicted dryer-ON event lack a
  preceding predicted washer-ON in the prior 90 min?
- A paragraph reconciling observed behavior with the appliance spec,
  specifically the fridge cycling rate and the laundry sequence

### Acceptance

| Check | Target |
| --- | --- |
| Session duration | ≥ 1 hour (2 hours recommended) |
| Total ticks at 10s tick | ≥ 360 |
| Error count | 0 |
| p99 latency over the full session | ≤ 5 ms |
| Refrigerator transitions per hour | within 4–25 |
| Dryer transitions per hour | within 0–4 |
| Microwave transitions per hour | within 0–8 |
| Number of "panel3 > 4000W but dryer OFF" anomalies | ≤ 2 per hour |
| Number of "panel3 < 50W but any ON" anomalies | 0 |

**→ Checkpoint 10.** Show me `panel3_first_session.md` and the last summary
block.

**Do not commit. Do not push. Do not modify `disaggregator.py`. Do not
write to `nilm_disaggregated`.**

---

## Output artifacts

When this task is complete, the following exist locally (none committed):

```
services/iems/training/
  extract_panel3.py
  labels_panel3.py
  windows_panel3.py
  model_panel3.py
  train_panel3.py
  export_panel3.py
  eval_panel3.py
  realtime_monitor_panel3.py
  scripts/
    panel3_label_inventory.py
    panel3_label_audit.py
  reports/
    panel3_label_inventory.md
    panel3_label_audit.md
    panel3_label_consensus.md
    panel3_eval.md
    realtime_panel3_<stamp>.jsonl
    realtime_panel3_<stamp>_summary.md
    realtime_panel3_<stamp>_stdout.log
    panel3_first_session.md

services/iems/models/
  nilm_panel3.pt
  nilm_panel3.onnx
  nilm_panel3_int8.onnx
  panel3_norm.json
```

`services/iems/load/disaggregator.py` is untouched. `nilm_disaggregated` is
untouched. Nothing is staged for commit.
