# Microgrid-UCSC — Residential Microgrid Energy Management System

`microgrid-manager` is a research-engineering system for a residential
microgrid in Los Gatos, California, instrumented through an eGauge meter and
connected to the UCSC microgrid research site. It does two things:

1. **NILM (Non-Intrusive Load Monitoring)** — given only the aggregate power
   readings of four electrical sub-panels, it infers which individual
   appliances are running, second by second.
2. **DSS (Decision Support System)** — given the appliance states, the
   weather, and the time-of-use electricity rate, it produces dollar-valued
   recommendations ("defer the dryer to off-peak, save $X") and surfaces them
   on a live dashboard.

This README explains how the model works, the math behind it, the full system
architecture, the streaming pipeline, the partition-table design and its
trade-offs, every working Python query, the dashboard, and the training data.

---

## 1. System architecture

The system is a five-stage pipeline. Energy readings flow left to right;
predictions are written back into the same datastore.

```
 eGauge18646 meter            Apache Kafka            AnyLog operator1            Inference + DSS            Dashboards
 16 channels, ~6 s     -->   egauge-energy      -->   TCP 32148 / REST 32149  -->  ONNX + rules + DSS  -->   Node  :47821
 sub-panel power             topic, broker            customers DB                FastAPI :8000             Remote-GUI plugin
                             :9094                    egauge_kafka table          writes predictions
                                                      nilm_disaggregated table    back to AnyLog
```

### 1.1 Stage 1 — Metering

A single eGauge18646 meter exposes **16 channels**. Four of them are the
load-bearing sub-panels the NILM model reasons about:

| Sub-panel          | Appliances on it                                        |
|--------------------|---------------------------------------------------------|
| `Panel1 (HVAC)`    | Heat pump, solar water-heater pump                      |
| `Panel2 (H2O)`     | Water heater, hair dryer, sprinklers, bathroom lights   |
| `Panel3 (Kitchen)` | Refrigerator, dishwasher, microwave, cooktop, computers, TV/stereo |
| `Shop`             | Dryer, washing machine, pressure pump                   |

The remaining channels are `Grid Power`, `Generac Power` (fossil backup), the
voltage/current diagnostics (`VrmsA`, `VrmsB`, `F1`, `I11`..`I32`) and
`Current on Utility Tie`. There is no EV charger on this house.

### 1.2 Stage 2 — Kafka ingestion

A pipeline (`kafka-egauge-pipeline`) polls the eGauge and publishes each
reading to the Kafka topic `egauge-energy` on broker
`host.docker.internal:9094`. Kafka decouples meter polling from database
ingestion so a slow or restarting database never drops a reading.

### 1.3 Stage 3 — AnyLog storage

AnyLog `operator1` runs an embedded Kafka consumer that drains
`egauge-energy` and writes rows into the `egauge_kafka` table of the
`customers` Postgres database. AnyLog is reached two ways:

- **TCP 32148** — node-to-node / CLI.
- **REST 32149** — every read and write the IEMS code performs.

Each raw row is `(ts, nm, w)`: a UTC timestamp, the channel name, and watts.

### 1.4 Stage 4 — Inference and decision support

The `services/iems` package is the core of the project. One inference cycle:

1. Pulls the last ~10–12 minutes of all four panels plus the utility-tie
   current from `egauge_kafka`.
2. Builds a normalized feature window per panel.
3. Runs the per-panel ONNX model to get appliance probabilities.
4. Thresholds the probabilities into ON/OFF states.
5. Writes one `nilm_disaggregated` row per appliance back into AnyLog.
6. Runs anomaly checks, solar/TOU analytics, and the DSS rule tree to produce
   recommendations.

The orchestrator is `runner.run_iems_cycle()`; the standalone continuous
loop is `iems.inference.inference_loop`.

### 1.5 Stage 5 — Presentation

Two front-ends consume the results:

- **Standalone dashboard** — `services/iems/web/server.js`, a zero-dependency
  Node server on port **47821**. It talks directly to AnyLog REST and to the
  IEMS FastAPI backend.
- **Remote-GUI plugin** — `services/remote-gui-iems-plugin/`, an IEMS page
  (`IemsPage.js`) that plugs into the AnyLog Remote-GUI React app, backed by
  `iems_router.py` on the FastAPI backend (port 8000).

### 1.6 Repository layout

```
microgrid-manager/
├── services/iems/
│   ├── inference/         ONNX inference path (production)
│   │   ├── onnx_disaggregator.py   per-panel ONNX session + write-back
│   │   ├── feature_builder.py      raw rows -> normalized (1,100,12) tensor
│   │   ├── appliance_map.py        appliance -> physical panel routing
│   │   └── inference_loop.py       continuous inference daemon
│   ├── load/
│   │   ├── anylog_query.py         ALL AnyLog reads/writes (canonical)
│   │   ├── disaggregator.py        legacy LLM disaggregation path
│   │   ├── anomaly.py / shedding.py
│   ├── models/            trained weights: nilm_panel{1,2,3}.{pt,onnx,_int8.onnx}
│   │                      + panel{1,2,3}_norm.json normalization configs
│   ├── training/          window builders, model defs, train/eval/export
│   ├── decision_support/  DSS rule tree + dollar-valued recommender
│   ├── generation/        solar forecast + grid analytics
│   ├── storage/           virtual battery state-of-charge model
│   ├── web/server.js      standalone live dashboard (port 47821)
│   └── runner.py          one-cycle orchestrator
├── services/remote-gui-iems-plugin/   IEMS page for the AnyLog Remote-GUI
├── docs/anylog_query_cookbook.md      verified AnyLog REST query shapes
├── scripts/               start/stop helpers
└── tests/
```

---

## 2. How the NILM model works

### 2.1 The problem

Each sub-panel reports one number: total watts. Several appliances share a
panel, so the panel reading is the sum of whatever is currently running plus a
noisy always-on baseline. NILM is the inverse problem: recover the per-appliance
ON/OFF state from that single summed signal.

We treat it as **multi-label time-series classification**. For each panel we
take a short rolling window of recent power and predict, for every appliance on
that panel, the probability that it is ON at the centre of the window.

### 2.2 Why a BiLSTM and not an LLM

The project originally followed an LLM-prompting approach to NILM
(Xue et al. 2025). That concept worked but was impractical for a live system:
LLM inference took 5–60 seconds per panel and was non-deterministic. We replaced
it with small, trained **per-panel BiLSTM networks** plus a calibrated rules
layer, then exported the networks to **ONNX** for inference. The ONNX path runs
in roughly **5–25 ms per panel** — three to four orders of magnitude faster —
and is fully deterministic.

### 2.3 Network architecture

There is one model per load-bearing panel (`Panel1Net`, `Panel2Net`,
`Panel3Net`). All share the same shape; they differ only in the number of
output heads. Defined in `services/iems/training/model_panel{1,2,3}.py`.

**Input.** A tensor of shape `(batch, 100, 12)`: 100 timesteps (a 10-minute
window at 6-second resolution) of 12 features.

**Shared convolutional front-end** — extracts local shape features (edges,
ramps, spikes) shared across all appliances:

```
Conv1d(in=12, out=32, kernel=5, padding=2)
BatchNorm1d(32)
ReLU
Dropout(0.1)
```

**Per-head branches** — one independent branch per appliance, so a high-power
appliance cannot dominate the shared weights of a low-power one. Each
`HeadBranch`:

```
BiLSTM(input=32,  hidden=32, bidirectional)   ->  64-dim sequence
BiLSTM(input=64,  hidden=16, bidirectional)   ->  32-dim sequence
take last timestep                            ->  32-dim vector
Dropout(0.2)
Linear(32 -> 16) -> ReLU -> Linear(16 -> 1)
Sigmoid                                        ->  probability in [0,1]
```

**Heads per panel:**

| Model        | Heads | Appliances |
|--------------|------:|------------|
| `Panel1Net`  | 2     | `heat_pump`, `solar_pump` |
| `Panel2Net`  | 4     | `water_heater`, `hair_dryer`, `sprinklers`, `bath_lights` |
| `Panel3Net`  | 8     | `refrigerator`, `dishwasher`, `microwave`, `dryer`, `washing_machine`, `pressure_pump`, `computers`, `tv_stereo` |

Panel3 is the hardest panel — eight appliances, ~110k parameters — which is why
it uses fully untied per-head branches.

### 2.4 The 12 input features

Feature order is fixed and must match `panel{N}_norm.json`. Built by
`services/iems/inference/feature_builder.py`:

| # | Feature | Meaning |
|--:|---------|---------|
| 1 | `panel1_w` | Panel 1 power |
| 2 | `panel2_w` | Panel 2 power |
| 3 | `panel3_w` | Panel 3 power |
| 4 | `shop_w`   | Shop power |
| 5 | `outside_temp` | Outside temperature (°F) |
| 6 | `irradiance` | Solar irradiance (6-hour average) |
| 7 | `hour_sin` | sin component of hour-of-day |
| 8 | `hour_cos` | cos component of hour-of-day |
| 9 | `dow_sin`  | sin component of day-of-week |
| 10| `dow_cos`  | cos component of day-of-week |
| 11| `utility_tie_current` | Current on the utility tie |
| 12| `panelN_w_step` | First difference of this panel's power |

All four panels are fed to every model: appliances couple across panels (the
heat pump load correlates with HVAC demand which correlates with temperature),
and a cross-panel view lets each model use that context.

### 2.5 Inference path, end to end

`disaggregate_panel_onnx()` in `onnx_disaggregator.py`:

1. **Build the window** — `build_panel_window()` resamples the raw rows onto a
   uniform 6-second grid (forward-filling gaps, zero-filling missing channels),
   computes the 12 features, z-score normalizes, and reshapes to `(1,100,12)`.
2. **Run the session** — one cached `onnxruntime.InferenceSession` per panel,
   CPU execution provider.
3. **Threshold** — each head emits `p_{appliance}`; the appliance is ON when
   `p >= threshold`, where the threshold is read per-head from
   `panel{N}_norm.json`.
4. **Write back** — one `nilm_disaggregated` row per appliance, stamped with the
   window-end timestamp so the dashboard reflects the freshest sample.

ONNX sessions are loaded once and reused (`_session_cache`, lock-protected), so
only the first call per panel pays the model-load cost.

---

## 3. The math behind the model

### 3.1 Feature normalization

Every feature is z-score normalized using statistics computed once over the
training set and frozen into `panel{N}_norm.json`:

```
x_norm = (x - mean) / std            std clamped to 1.0 where std < 1e-6
```

This puts watts (thousands), temperature (tens) and trig features (-1..1) on a
comparable scale so no feature dominates the gradient.

### 3.2 Cyclical time encoding

Hour-of-day and day-of-week are periodic — hour 23 is adjacent to hour 0. A raw
integer would put them maximally far apart, so each is encoded on a circle:

```
hour_sin = sin(2*pi * hour / 24)     hour_cos = cos(2*pi * hour / 24)
dow_sin  = sin(2*pi * dow  / 7)      dow_cos  = cos(2*pi * dow  / 7)
```

### 3.3 The step feature

`panelN_w_step` is the first difference of panel power — it isolates switching
events from the slowly drifting baseline. In the window builder it is defined
against a rolling baseline:

```
baseline      = rolling_30min_min(panelN_w)
panelN_w_step = max(panelN_w - baseline, 0)
```

At inference time the simpler sample-to-sample difference is used
(`step[i] = panelN_w[i] - panelN_w[i-1]`, `step[0] = 0`).

### 3.4 1-D convolution

The front-end applies a 1-D convolution across time. With kernel width `k=5`
and `padding=2` the output length equals the input length; each output channel
`c` at timestep `t` is:

```
y[c, t] = sum over (j, tau) of  W[c, j, tau] * x[j, t + tau - 2]  +  b[c]
```

followed by batch normalization, ReLU, and dropout.

### 3.5 LSTM and BiLSTM

Each head runs two stacked bidirectional LSTMs. A single LSTM cell at step `t`:

```
i_t = sigmoid(W_i x_t + U_i h_{t-1} + b_i)      input gate
f_t = sigmoid(W_f x_t + U_f h_{t-1} + b_f)      forget gate
o_t = sigmoid(W_o x_t + U_o h_{t-1} + b_o)      output gate
g_t = tanh   (W_g x_t + U_g h_{t-1} + b_g)      candidate cell
c_t = f_t (.) c_{t-1} + i_t (.) g_t             cell state
h_t = o_t (.) tanh(c_t)                         hidden state
```

`(.)` is element-wise product. **Bidirectional** means one LSTM runs the window
front-to-back and another back-to-front; their hidden states are concatenated,
so the prediction at the window centre uses both past and future context within
the 10-minute window. The branch keeps only the final timestep's hidden vector.

### 3.6 Output and thresholding

The MLP head ends in a sigmoid, giving a per-appliance probability:

```
p = sigmoid(z) = 1 / (1 + exp(-z))
state = ON  if p >= threshold   else  OFF
```

Thresholds are tuned per appliance, not fixed at 0.5. Rare appliances with weak
signatures (e.g. Panel3 `refrigerator`, `washing_machine`, `computers` use
0.05) get low thresholds to recover recall; `dishwasher` uses 0.86 to suppress
false positives. Thresholds live in the `thresholds` block of
`panel{N}_norm.json`.

### 3.7 Training loss — masked, weighted BCE

Training labels come from the rule engine and are `{0, 1, NaN}` — `NaN` marks
an ambiguous sample that should not contribute to the loss. The loss is binary
cross-entropy, summed over heads, with two modifications (`train_panel{N}.py`):

```
masked, per head:
  keep only positions where the label is not NaN
  p clamped to [1e-7, 1 - 1e-7]
  L = - mean( pos_weight * t * log(p) + (1 - t) * log(1 - p) )

total loss = sum of L over all heads
```

**`pos_weight`** counteracts class imbalance. Most appliances are OFF most of
the time, so without weighting the model would just predict OFF. For each head:

```
pos_weight = n_negative / max(n_positive, 1)
```

so the rare positive class is up-weighted proportionally to how rare it is.

### 3.8 Optimization

```
optimizer      AdamW, learning rate 1e-3, weight decay 1e-4
batch size     256
max epochs     60
early stopping patience 10, on macro-averaged validation F1
```

The checkpoint with the best macro-averaged validation F1 is kept.

### 3.9 Evaluation metric — F1

Per head, at the chosen threshold:

```
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
F1        = 2 * precision * recall / (precision + recall)
```

Macro-F1 (the mean across heads) is the early-stopping and model-selection
criterion. `NaN` labels are excluded from all counts.

### 3.10 ONNX export and quantization

`export_panel{N}.py` traces the PyTorch model to ONNX (opset 17, dynamic batch
axis) and additionally produces a dynamically int8-quantized variant:

```
quantize_dynamic(weight_type=QInt8, op_types_to_quantize=["MatMul"])
```

Only `MatMul` ops are quantized — that captures most of the speed-up while
keeping accuracy stable. Measured single-window CPU latency on a Mac:
Panel1 FP32 ~0.34 ms / int8 ~0.36 ms; Panel3 FP32 ~1.24 ms / int8 ~1.04 ms.

---

## 4. The streaming pipeline in detail

### 4.1 Forward path — meter to database

```
eGauge18646  --poll-->  kafka-egauge-pipeline  --produce-->  Kafka topic egauge-energy
                                                                   |
                                          AnyLog operator1 embedded Kafka consumer
                                                                   |
                                                       customers.egauge_kafka  (one row per channel-reading)
```

If `local_script.al` does not auto-run on container start, the streamer,
operator, and Kafka consumer must each be POSTed individually over REST to
bring the node up.

### 4.2 Write-back path — predictions to database

After each inference cycle, `insert_predictions()` writes appliance states back
into `nilm_disaggregated` over an AnyLog **streaming PUT**. AnyLog routes the
rows to the correct partition by `insert_timestamp`:

```
PUT http://127.0.0.1:32149
headers: type=json, dbms=customers, table=nilm_disaggregated, mode=streaming
body:    JSON array of prediction records
```

One row is written **per appliance per cycle**, with the schema in section 5.3.

### 4.3 Networking notes

- Inside Docker, AnyLog is `host.docker.internal:32149`; from the Mac host it
  is `127.0.0.1:32149`.
- Always use `127.0.0.1`, never `localhost`, in the Python and Node code:
  `localhost` resolves to IPv6 `::1` while the Docker port maps bind IPv4 only.
- The AnyLog REST endpoint emits non-standard HTTP chunked responses, so the
  Python client (`anylog_query._al_request`) reads the socket raw and strips
  AnyLog's hex chunk-size markers itself rather than trusting the stdlib
  chunked decoder.

---

## 5. AnyLog partition tables — design and trade-offs

### 5.1 How AnyLog partitions

AnyLog stores both `egauge_kafka` and `nilm_disaggregated` as **time-range
partitioned** tables. Physically, each table is a set of partition tables named
on a date pattern, for example:

```
par_egauge_kafka_2026_05_00_d14_insert_timestamp
par_nilm_disaggregated_2026_05_00_d14_insert_timestamp
```

Each partition holds a bounded slice of time. New rows route to a partition by
their `insert_timestamp`. Partitions are discovered at runtime with
`get partitions where dbms=customers and table=<table>`.

### 5.2 Why partitions are used

- **Bounded scans.** A query for "the last 10 minutes" only needs the current
  partition. The engine never scans months of history to answer a question
  about the present minute — important for a system that queries every cycle.
- **Distributed time-series model.** AnyLog is designed to spread time-range
  partitions across operator nodes; partitioning is the unit of that
  distribution and of horizontal scale.
- **Cheap retention and lifecycle.** Old data can be aged out a whole partition
  at a time instead of with row-level deletes.
- **Ingestion routing.** The streaming PUT path routes rows to a partition by
  timestamp with no application-side bookkeeping.

### 5.3 The drawbacks (and how the code works around each)

Partitioning is the right model for this workload, but it leaks into the query
layer. Every drawback below is real, observed against the live operator, and
documented in `docs/anylog_query_cookbook.md`.

**1. The parent table name returns nothing.**
Querying `SELECT ... FROM egauge_kafka` against the logical table name returns
an empty result even when data exists. Queries must target a concrete partition
table (`par_egauge_kafka_2026_05_00_...`).
*Workaround:* `anylog_query()` discovers partitions and rewrites the table name
in the SQL to the actual partition(s) before sending.

**2. `NOW()`-relative recent windows are unreliable.**
A predicate such as `WHERE ts > NOW() - 5 minutes` does not reliably land on
the most recent partition; AnyLog's `NOW()` behaviour is version-dependent.
*Workaround:* `_rewrite_now()` replaces every `NOW() - N unit` expression with
an absolute ISO timestamp computed in Python before the query is sent.

**3. A time range can span partitions.**
A 24-hour or month-boundary query touches more than one partition; a single
`FROM` clause cannot address them all.
*Workaround:* `_partitions_for_range()` returns every partition overlapping the
window; `anylog_query()` runs the SQL against each, then merges and deduplicates
rows on `(ts, channel)`.

**4. Partition discovery has a per-call cost.**
Listing partitions is an extra REST round-trip.
*Workaround:* discovered partitions are cached in `_PARTITION_CACHE` (and on the
Node side for 5 minutes); `_invalidate_partition_cache()` forces a refresh.

**5. Stale partition cache at a month boundary.**
When a new month rolls over, a cached partition list misses the new partition.
*Workaround:* the cache is invalidatable, and the Node dashboard re-resolves
the latest partition every 5 minutes.

There are two further AnyLog SQL quirks, not strictly partition-related but
handled in the same module — see section 6.4.

---

## 6. Working Python queries

All AnyLog access is centralized in
`services/iems/load/anylog_query.py`. Nothing else in the codebase opens a
socket to AnyLog. Reads use AnyLog local SQL; writes use a streaming PUT.

### 6.1 Canonical query shape

The REST request that works against the live operator:

```
GET http://127.0.0.1:32149
headers:
  User-Agent: AnyLog/1.23
  command:    sql customers format=json and stat=false "<SQL>"
```

Response shapes the caller must handle:

- `{"Query": [ ... ]}`        — rows.
- `{"reply": "Empty data set"}` — a legitimate zero-row result, not an error.
- `{"err_code": ..., "err_text": ...}` — a parser/syntax error.

### 6.2 Read functions

| Function | Purpose |
|----------|---------|
| `anylog_query(sql, table, minutes)` | Core dispatcher: rewrites `NOW()`, resolves partitions, merges multi-partition results. |
| `fetch_channel(channel, start_iso, end_iso)` | All `(ts, nm, w)` rows for one channel in a time range. |
| `fetch_recent_window(channel, minutes)` | The last N minutes for one channel. |
| `fetch_all_panels(start_iso, end_iso)` | All six IEMS channels in a range, returned grouped by channel. |
| `fetch_all_panels_recent(minutes)` | The last N minutes for all panels in one query. |
| `fetch_distinct_channels()` | Distinct channel names in the current partition. |
| `health_check()` | Row count and data-freshness check over the last 5 minutes. |

### 6.3 Representative SQL

The SQL the helpers actually send (after `NOW()` rewriting and partition
substitution). These are the verified working shapes:

```sql
-- recent window, all panels (one query, then group client-side)
SELECT ts, nm, w FROM egauge_kafka
WHERE ts > NOW() - 30 minutes
ORDER BY ts ASC;

-- one channel, explicit range
SELECT ts, nm, w FROM egauge_kafka
WHERE nm = 'Grid Power' AND ts >= '2026-05-12 00:00:00'
                        AND ts <= '2026-05-12 23:59:59'
ORDER BY ts ASC;

-- latest NILM predictions for the dashboard
SELECT ts, circuit, appliance, state, confidence, avg_w
FROM nilm_disaggregated
ORDER BY ts DESC
LIMIT 100;

-- distinct channels (GROUP BY, not DISTINCT — see 6.4)
SELECT nm, COUNT(*) AS cnt FROM egauge_kafka
GROUP BY nm ORDER BY nm;

-- freshness / health
SELECT MAX(ts) AS latest, COUNT(*) AS cnt FROM egauge_kafka
WHERE ts > '2026-05-12 17:40:00';
```

### 6.4 Two SQL quirks the query layer hides

**Parenthesized channel names.** Three channels contain parentheses —
`Panel1 (HVAC)`, `Panel2 (H2O)`, `Panel3 (Kitchen)`. AnyLog's SQL parser
mishandles string literals containing parentheses: `WHERE nm = 'Panel1 (HVAC)'`
silently returns an empty set, and `IN (...)` / `LIKE '%...%'` raise
`IncompleteRead`. The workaround, used by `fetch_channel` and friends for the
`PAREN_CHANNELS` set, is to fetch by **time only** and filter by channel name
in Python:

```python
rows = anylog_query(
    "SELECT ts, nm, w FROM egauge_kafka "
    "WHERE ts > NOW() - 30 minutes ORDER BY ts ASC")
panel1 = [r for r in rows if r["nm"] == "Panel1 (HVAC)"]
```

**`SELECT DISTINCT` is broken.** `SELECT DISTINCT col` returns rows keyed
`"DISTINCT col"`. Use `GROUP BY` instead, as in the distinct-channels query
above.

A third quirk: the `run client ()` prefix and the `destination: network`
header are CLI/native constructs — `run client ()` returns `err 156`
("Wrong HTTP method") over REST GET, and `destination: network` times out
through Docker's hairpin NAT. The IEMS code therefore runs every query
**locally on the operator** with no destination header.

### 6.5 Write function

```python
insert_predictions(records)        # records: list of dicts, schema below
```

Sends one streaming PUT (section 4.2). Returns `True` on
`HTTP 200 + "Success"`. The `nilm_disaggregated` schema:

| Column | Type |
|--------|------|
| `ts` | timestamp without time zone |
| `circuit` | varchar — the appliance's physical panel |
| `appliance` | varchar |
| `state` | varchar — `ON` / `OFF` |
| `confidence` | double — the model probability |
| `avg_w` / `median_w` / `std_w` | double — recent power stats for the circuit |
| `window_start` / `window_end` | timestamp — the inference window bounds |
| `window_n` | integer — samples in the window |

`row_id` and `insert_timestamp` are managed by AnyLog and must not appear in
the payload.

### 6.6 Helper utilities

`_parse_ts` (multi-format timestamp parsing), `_ts_str`, `_tofloat`,
`resample_to_6s` (linear resampling onto the 6-second grid), and
`build_nilm_predictions` (convert per-appliance binary state arrays into
`nilm_disaggregated` rows).

---

## 7. The dashboard

### 7.1 Standalone dashboard — `services/iems/web/server.js`

A single-file, zero-npm Node HTTP server on port **47821**. It is both the API
proxy and the static UI (the HTML/CSS/JS is embedded in the file). It draws
from two upstream sources:

- **AnyLog REST** (`127.0.0.1:32149`) — raw `egauge_kafka` power and the
  `nilm_disaggregated` predictions.
- **IEMS FastAPI** (`127.0.0.1:8000`) — full cycle results, model metadata,
  health, weather and TOU.

It mirrors the Python query layer in JavaScript: it discovers and caches the
current partition, rewrites `NOW()` to absolute timestamps, and substitutes the
partition name into the SQL.

### 7.2 Dashboard API endpoints

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/api/snapshot` | GET | Latest power reading per panel. |
| `/api/history?minutes=N` | GET | Raw power time-series for the panels (capped at 2000 points). |
| `/api/nilm` | GET | The 100 most recent `nilm_disaggregated` rows. |
| `/api/cycle` | POST | Triggers a full IEMS cycle via the FastAPI backend. |
| `/api/models` | GET | Model metadata from the backend. |
| `/api/health` | GET | AnyLog row count (last 5 min) + backend health + server status. |

### 7.3 What the dashboard displays

- A **14-appliance NILM grid** — one card per appliance showing ON/OFF state
  and confidence, drawn with abstract SVG glyphs (no emoji).
- A **raw power line graph** of the four panels over a selectable window.
- A **TOU rate strip and load-forecast graph** — current time-of-use period
  and a near-term load projection.
- The **DSS recommendations** — the dollar-valued actions from the recommender.

### 7.4 Remote-GUI plugin — `services/remote-gui-iems-plugin/`

The second front-end is an IEMS page for the AnyLog Remote-GUI React app:

- `frontend/IemsPage.js` — the React page component.
- `frontend/iems_api.js` — a thin client over the FastAPI `/iems/*` routes
  (`/iems/cycle`, `/iems/models`, `/iems/health`, `/iems/appliances`,
  `/iems/tou_rates`, `/iems/anomalies/active`, `/iems/preferences`, ...).
- `backend/iems_router.py` — the FastAPI router that backs those routes.

These files are extracted from the upstream AnyLog Remote-GUI clone (which is a
separate repository and is not vendored here) so the IEMS-specific code is
versioned with the project.

### 7.5 How it all syncs up

There is no push channel or websocket — every surface **polls**, and the
shared `nilm_disaggregated` / `egauge_kafka` tables are the synchronization
point:

```
inference loop  --writes-->  nilm_disaggregated  <--reads--  dashboards
   (~30 s tick)                  (AnyLog)                    (~few-second poll)
```

1. The inference loop ticks on a fixed interval (default 30 s), runs all three
   panel models, and writes fresh `nilm_disaggregated` rows.
2. The dashboard polls `/api/nilm`, `/api/snapshot`, and `/api/history` on its
   own short interval and re-renders.
3. Because predictions are stamped with the **window-end** timestamp, the grid
   reflects the freshest sample rather than a window-midpoint several minutes
   old.
4. A manual `/api/cycle` POST runs an immediate full cycle (NILM + anomalies +
   DSS) for an on-demand refresh.

Eventual consistency is acceptable here: the meter resolution is ~6 s and
appliance state changes on the scale of minutes, so a few seconds of polling lag
is invisible to the user.

---

## 8. Training data

### 8.1 Source

Training data is the same live stream the system runs on: eGauge18646 to Kafka
to AnyLog `egauge_kafka`. Historical rows are pulled out of AnyLog (`pull_*`
scripts in `services/iems/training/`) into a wide table — `raw_pivot.parquet` —
with one column per channel on a shared UTC time index.

### 8.2 Feature engineering

`build_windows.py` and the per-panel `windows_panel{1,2,3}.py` builders:

1. **Resample** to a uniform 6-second grid, forward-filling short gaps.
   Continuous runs are detected with a gap tolerance of 10.5 s so a window
   never bridges a data outage.
2. **Compute** the 12 features of section 2.4, including the rolling-baseline
   step feature and the cyclical time encodings.
3. **Slide** a 100-sample (10-minute) window across each continuous run. The
   training split uses `stride = 1` (dense — every appliance event is seen);
   validation and test use stride 1 as well for a complete held-out scan.
4. **Label** each window by the appliance states at its centre sample
   (index 50).
5. **Normalize** — mean/std are computed over the training split only and
   written to `panel{N}_norm.json`.

Output: `data/panel{N}_windows.npz` (the `X`/`y` tensors per split) and the
matching `panel{N}_norm.json`.

### 8.3 Labels — the rule engine

There are no hand-labelled appliance traces for this house, so supervision
comes from `services/iems/training/rule_engine.py`: a pure-pandas, calibrated
rule layer that assigns each appliance, at each timestamp, one of:

- `1` — high-confidence ON (a rule fired clearly).
- `0` — high-confidence OFF (clear baseline).
- `NaN` — ambiguous; excluded from the loss (section 3.7).

Rules are calibrated against the house's own behaviour. Two examples:

- **Baseline-step rules.** Panel 2 sits at a 150–250 W always-on baseline and
  Panel 3 spends ~76% of its time in a 200–500 W baseline band. Raw-power
  thresholds would mislabel that baseline as an appliance, so small/medium
  appliances are detected on the **increment above a rolling 30-minute
  baseline**, not on absolute watts.
- **Large clearly-separated loads** (e.g. the dryer at 4–7.5 kW) keep simple
  raw-power thresholds.

Nominal appliance power ranges and ON thresholds come from
`appliance_data_updated.txt`.

### 8.4 The train/validation/test split

Splitting is **by observed-row position**, 70 / 10 / 20, preserving temporal
order. It is deliberately *not* a calendar-day split: the dense Kafka pipeline
only began producing data about five days before the training runs, so a
day-based split would starve the training set and leave several appliance heads
with zero positive examples. A representative Panel 2 / Panel 3 split:

| Split | Rows | UTC range |
|-------|-----:|-----------|
| Train | 17,882 | 2026-04-21 18:22 to 2026-05-06 03:34 |
| Val   | 2,554  | 2026-05-06 03:35 to 2026-05-07 01:31 |
| Test  | 5,109  | 2026-05-07 01:31 to 2026-05-12 17:48 |

### 8.5 Current model status

Honest assessment of where the models stand, from the held-out evaluations in
`services/iems/training/reports/`:

- **Panel 3 — production-ready for its strong heads.** `refrigerator` F1 1.00,
  `tv_stereo` F1 1.00, `computers` F1 0.80, `microwave` F1 0.56. The rare heads
  (`dishwasher`, `dryer`, `washing_machine`, `pressure_pump`) are weak — the
  test slice contains very few positive examples for them, so their F1 is
  unreliable rather than necessarily bad.
- **Panel 1 and Panel 2 — not yet wired into production.** Most heads have
  near-zero F1 on the current data. The cause is data, not architecture: only a
  few days of dense data exist and several appliances barely fired in that
  window. These panels need more — and more seasonal — data before retraining.
- **Known cross-panel routing issue.** Because every model is trained on all
  four panels' features, the Panel 3 model can predict appliances that
  physically live on the Shop panel (`dryer`, `washing_machine`,
  `pressure_pump`). `appliance_map.py` corrects for this at write-time: the
  `circuit` stored in `nilm_disaggregated` is the appliance's true physical
  panel, regardless of which model produced the prediction.

The most direct next step is broader and more seasonal data collection,
followed by retraining Panels 1 and 2.

---

## 9. Running the system

The four moving parts:

1. **Kafka pipeline** — `kafka-egauge-pipeline` ingests the eGauge into Kafka.
2. **AnyLog operator1** — brought up from the docker-compose makefiles; if
   `local_script.al` does not auto-run, POST the streamer, operator and Kafka
   consumer over REST.
3. **Inference + FastAPI backend** — the IEMS cycle / inference loop and the
   `/iems/*` API on port 8000.
4. **Dashboards** — `node services/iems/web/server.js` for the standalone
   dashboard on port 47821; the Remote-GUI plugin for the AnyLog GUI.

Quick checks:

```bash
# one inference pass, print JSON, exit
python -m iems.inference.inference_loop --once

# continuous inference (30 s tick)
python -m iems.inference.inference_loop --tick 30

# standalone dashboard
node services/iems/web/server.js     # -> http://127.0.0.1:47821
```

Python imports require `PYTHONPATH=services` (the package is `iems.*`).

### Research foundations

- Xue et al. 2025 — LLM-driven NILM via prompt engineering (the original
  concept; since replaced by trained networks for the live system).
- Adabi 2016 — UCSC PhD thesis on the IEMS four-domain architecture (user,
  load, generation, storage), which the cycle orchestrator follows.
