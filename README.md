# IEMS — Intelligent Energy Management System

Residential microgrid management for a house in Los Gatos, California.
Reads live power data from an eGauge18646 sub-meter, disaggregates it into
per-appliance ON/OFF states using a locally-running LLM (LLM4NILM, Xue et al.
2025), and displays results on a live dashboard with dollar-denominated
decision support.

Architecture: Adabi 2016 (UCSC PhD) four-domain IEMS — User, Load, Generation,
Storage. Data backbone: AnyLog distributed time-series database. No cloud
services required after initial setup.

---

## Prerequisites

Install these before anything else.

| Tool | Version | Install |
|---|---|---|
| Docker Desktop | ≥ 4.28 | https://www.docker.com/products/docker-desktop |
| Node.js | ≥ 18 | https://nodejs.org |
| Python | ≥ 3.11 | https://www.python.org |
| Git | any | https://git-scm.com |

Verify:
```bash
docker --version
node --version
python3 --version
git --version
```

---

## Repository layout

```
microgrid-manager/
├── docker-compose.yaml          # iems-app + ollama (run from here)
├── scripts/
│   ├── start.sh                 # full stack startup — run this first
│   └── stop.sh                  # clean shutdown
├── docs/
│   └── anylog_query_cookbook.md # verified AnyLog REST patterns
└── services/
    └── iems/
        ├── config.py            # house wiring, appliance profiles, TOU rates
        ├── runner.py            # IEMS cycle orchestrator (one call = full pass)
        ├── weather.py           # Open-Meteo + irradiance
        ├── requirements.txt
        ├── load/
        │   ├── anylog_query.py  # ALL AnyLog reads and writes
        │   ├── disaggregator.py # LLM4NILM pipeline per panel
        │   ├── prompt_builder.py
        │   ├── llm_client.py    # Ollama + llama.cpp adapters
        │   ├── output_normalizer.py
        │   ├── anomaly.py       # water heater / pump / dryer alerts
        │   ├── shedding.py      # load shedding priority (Adabi 5.3)
        │   └── mobile_load.py   # vacuum cleaner tracking
        ├── generation/
        │   ├── solar_forecast.py
        │   └── grid_analytics.py
        ├── storage/
        │   ├── battery_model.py # virtual Powerwall SOC
        │   └── dispatch.py
        ├── decision_support/
        │   ├── recommender.py   # dollar-denominated recommendations
        │   ├── rule_tree.py     # AUTO vs USER_DRIVEN tagging
        │   ├── optimizer.py
        │   └── shedding_bridge.py
        ├── prompts/
        │   ├── base_role.txt
        │   ├── load_disaggregation.txt
        │   └── anomaly_explainer.txt
        └── web/
            └── server.js        # Node.js dashboard (port 47821)
```

The three external stacks live outside this repo but are required:

| Stack | Location | What it runs |
|---|---|---|
| AnyLog master + operator | `~/docker-compose/docker-makefiles/docker-compose-files/` | Time-series DB |
| Kafka + eGauge bridge | `~/kafka-egauge-pipeline/` | Data ingestion |
| Postgres | `~/docker-compose/support-tools/postgres/` | Storage backend |

---

## First-time setup

### 1. Clone the repository

```bash
git clone git@github.com:royshadmon/Microgrid-UCSC.git
cd Microgrid-UCSC
```

### 2. Set up AnyLog

AnyLog requires its own directory structure. Clone it adjacent to this repo:

```bash
git clone https://github.com/AnyLog-co/docker-compose \
  ~/docker-compose
```

Copy the operator configs from this repo:

```bash
cp -r configs/operator1-configs \
  ~/docker-compose/docker-makefiles/operator1-configs
cp -r configs/master-configs \
  ~/docker-compose/docker-makefiles/master-configs
```

Create the Docker network AnyLog uses:

```bash
docker network create anylog-net 2>/dev/null || true
```

### 3. Set up the Kafka pipeline

```bash
git clone https://github.com/your-org/kafka-egauge-pipeline \
  ~/kafka-egauge-pipeline
```

Copy the `.env` with your eGauge credentials:

```bash
cp .env.example ~/kafka-egauge-pipeline/.env
# Edit and fill in:
# EGAUGE_URI=http://egauge18646.egaug.es
# EGAUGE_USER=your_username
# EGAUGE_PASS=your_password
```

### 4. Set up Postgres

```bash
cd ~/docker-compose/support-tools/postgres
# Edit postgres.env — set POSTGRES_PASSWORD
docker compose up -d
```

Create the database and tables:

```bash
docker exec postgres1 psql -U demo -c "CREATE DATABASE customers;"
docker exec postgres1 psql -U demo -d customers << 'SQL'
CREATE TABLE egauge_kafka (
  row_id           SERIAL PRIMARY KEY,
  insert_timestamp TIMESTAMP DEFAULT NOW(),
  tsd_name         CHAR(3),
  tsd_id           INT,
  ts               TIMESTAMP,
  dev              CHARACTER VARYING,
  nm               CHARACTER VARYING,
  tp               CHARACTER VARYING,
  w                DOUBLE PRECISION,
  kwh              DOUBLE PRECISION
);

CREATE TABLE nilm_disaggregated (
  row_id           SERIAL PRIMARY KEY,
  insert_timestamp TIMESTAMP DEFAULT NOW(),
  tsd_name         CHAR(3),
  tsd_id           INT,
  ts               TIMESTAMP,
  circuit          CHARACTER VARYING,
  appliance        CHARACTER VARYING,
  state            CHARACTER VARYING(3),
  confidence       DOUBLE PRECISION,
  avg_w            DOUBLE PRECISION,
  median_w         DOUBLE PRECISION,
  std_w            DOUBLE PRECISION,
  window_start     TIMESTAMP,
  window_end       TIMESTAMP,
  window_n         INTEGER
);
SQL
```

> **Critical schema rule**: `tsd_name CHAR(3)` and `tsd_id INT` must be columns
> 3 and 4 in every AnyLog-managed table (after `row_id` and `insert_timestamp`).
> AnyLog's streaming PUT fills these positionally — getting the order wrong
> silently corrupts all incoming data.

### 5. Pull an LLM model

Start Ollama first (step 7 below), then pull at least one model:

```bash
# After Ollama is running:
curl http://localhost:11434/api/pull \
  -d '{"name":"llama3.1:8b"}'
```

Recommended models in order of quality vs speed:

| Model | Size | NILM accuracy | Notes |
|---|---|---|---|
| `deepseek-r1:8b` | 5 GB | Best | Use for production |
| `llama3.1:8b` | 5 GB | Good | Faster than deepseek |
| `phi3:mini` | 2 GB | Basic | Fast, lower accuracy |

### 6. Adapt `config.py` to your house

Open `services/iems/config.py`. This file contains everything house-specific.

**Change the channels to match your eGauge:**

```python
CHANNELS = {
    "Grid Power":       {"role": "main_signed", "signed": True},
    "Generac Power":    {"role": "fossil_backup"},
    "Panel1 (HVAC)":    {"role": "subpanel", "appliances": ["heat_pump"]},
    ...
}
```

The channel names here must exactly match the `nm` column values in
`egauge_kafka`. Check what your meter reports:

```bash
docker exec postgres1 psql -U demo -d customers -c \
  "SELECT DISTINCT nm FROM egauge_kafka ORDER BY nm;"
```

**Change the appliance profiles:**

```python
APPLIANCES = {
    "heat_pump": {
        "panel": "Panel1 (HVAC)",
        "power_range_w": (1500, 4000),   # adjust to your appliance
        "on_threshold_w": 300,
        "avg_on_duration_min": 15,
        "usage_pattern": "describe when and how it runs",
        ...
    },
}
```

The `power_range_w` is the most important field — it is what the LLM uses to
identify appliances from the aggregate power signal.

**Change the TOU rates:**

```python
TOU_RATES = {
    "summer": {
        "peak":     {"hours": (16, 21), "rate": 0.46},
        "off_peak": {"hours": (0,  16), "rate": 0.26},
    },
    ...
}
```

Rates are in $/kWh. Match to your utility's current schedule. The system uses
these to compute dollar savings in recommendations.

**Change the house location:**

```python
HOUSE_LAT  = 37.2358    # your latitude
HOUSE_LON  = -121.9624  # your longitude
HOUSE_TZ   = "America/Los_Angeles"
```

These feed the weather API and TOU period detection.

---

## Starting the stack

```bash
~/microgrid-manager/scripts/start.sh
```

The script starts each service in dependency order and health-checks each
one before moving on. It takes about 60 seconds end to end.

What it does:

1. Starts AnyLog master
2. Starts AnyLog operator1 — waits for REST to respond
3. Verifies Operator + Streamer + Kafka Consumer are all `Running`
4. Starts Kafka + eGauge producer + AnyLog consumer bridge
5. Starts Ollama + iems-app (Docker Compose from this directory)
6. Starts the Node.js dashboard on port 47821
7. Checks that egauge_kafka has rows in the last 2 minutes

When finished:

```
  ✅  IEMS stack is running

     Dashboard  →  http://localhost:47821
     FastAPI    →  http://localhost:8000/iems/health
     Kafka UI   →  http://localhost:8080
     AnyLog     →  http://localhost:32149
```

## Stopping the stack

```bash
~/microgrid-manager/scripts/stop.sh
```

Postgres is left running by default (it has no startup dependency and
its data is safe at rest). Stop it separately if needed:

```bash
docker stop postgres1
```

---

## Dashboard

Open `http://localhost:47821` in a browser.

**Top bar** — live sub-panel snapshot. One tile per circuit. Updates every
time the page is open or the IEMS cycle runs.

**Raw Power** — last N minutes of watt readings per panel from `egauge_kafka`.

**NILM Disaggregation** — LLM4NILM output per panel. Shows ON/OFF state
per appliance with confidence and average watts. Populated after clicking
**Run IEMS Cycle**.

**Weather & TOU** — outside temperature, cloud cover, irradiance, wind, and
the current PG&E E6 time-of-use period and rate.

**DSS Recommendations** — dollar-denominated suggestions from the decision
support layer. Each has Accept / Defer / Dismiss.

**Ollama Models** — available local LLM models and their sizes.

**State Change Events** — log of ON→OFF and OFF→ON transitions detected since
the last cycle.

---

## Running a NILM cycle manually

From the dashboard: click **Run IEMS Cycle**.

From the command line:

```bash
curl -s -X POST http://localhost:8000/iems/cycle \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-r1:8b","window_minutes":10}'
```

The cycle runs one full Adabi four-domain pass:

1. Fetches last N minutes of raw watt readings from AnyLog
2. Resamples to 6-second intervals (LLM4NILM paper standard)
3. Sends sliding windows to the LLM for each panel
4. Normalises outputs to binary ON/OFF arrays
5. Runs anomaly detection
6. Computes generation + storage state
7. Builds dollar-denominated DSS recommendations
8. Writes appliance states to `nilm_disaggregated` via AnyLog streaming PUT

---

## AnyLog query reference

All queries go through `services/iems/load/anylog_query.py`.
See `docs/anylog_query_cookbook.md` for the full verified pattern list.

### Reading live data

```python
from iems.load.anylog_query import (
    fetch_all_panels_recent,
    fetch_channel,
    fetch_distinct_channels,
    health_check,
)

# All panels, last 10 minutes
data = fetch_all_panels_recent(minutes=10)
# Returns: {"Grid Power": [{"ts": "...", "nm": "...", "w": 3450.0}, ...], ...}

# Single channel, time range
rows = fetch_channel(
    channel="Panel3 (Kitchen)",
    start_iso="2026-05-06 08:00:00",
    end_iso="2026-05-06 09:00:00",
)

# Available channel names
channels = fetch_distinct_channels()

# Liveness check
status = health_check()
# Returns: {"ok": True, "row_count_5min": 1728, "latest_ts": "...", "staleness_s": 12}
```

### Running arbitrary SQL

```python
from iems.load.anylog_query import anylog_query

# Queries the correct partition automatically
rows = anylog_query(
    "SELECT ts, nm, w FROM egauge_kafka "
    "WHERE ts > NOW() - 5 minutes ORDER BY ts DESC LIMIT 20",
    table="egauge_kafka",
)
```

**Quirks you must know** (from `docs/anylog_query_cookbook.md`):

- `NOW()` is rewritten to an absolute ISO timestamp before sending — AnyLog's
  `NOW()` is unreliable across versions.
- Channel names with parentheses like `Panel1 (HVAC)` break AnyLog's SQL
  parser if used in `WHERE nm = '...'`. Use `fetch_all_panels_recent()` which
  fetches everything and filters client-side.
- `SELECT DISTINCT` returns the key `"DISTINCT nm"` not `"nm"` — use
  `GROUP BY` instead.
- `destination: network` times out due to Docker hairpin NAT. Never use it.
  All queries use local SQL (no destination header).
- `run client ()` via REST returns `err_code 156` — it is a CLI-only command.

### Writing NILM predictions

```python
from iems.load.anylog_query import insert_predictions

predictions = [
    {
        "ts":           "2026-05-06 10:00:00",
        "circuit":      "Panel3 (Kitchen)",
        "appliance":    "refrigerator",
        "state":        "ON",
        "confidence":   0.75,
        "avg_w":        148.0,
        "median_w":     145.0,
        "std_w":        3.5,
        "window_start": "2026-05-06 09:50:00",
        "window_end":   "2026-05-06 10:00:00",
        "window_n":     100,
    }
]

ok = insert_predictions(predictions)
```

Writes via AnyLog streaming PUT to `nilm_disaggregated`. AnyLog routes to the
correct partition based on `insert_timestamp`. Returns `True` on success.

### Sending admin commands

```python
from iems.load.anylog_query import anylog_admin

# Any AnyLog command that doesn't return tabular data
status = anylog_admin("get processes")
anylog_admin("get streaming")
```

---

## Adapting to a different AnyLog deployment

**If your operator runs on a different port**, change these in
`docker-compose.yaml` under `iems-app` environment:

```yaml
- ANYLOG_REST_URL=http://host.docker.internal:32149   # change port
- ANYLOG_HOST=host.docker.internal                    # change host
- ANYLOG_REST_PORT=32149                              # change port
```

And in `services/iems/load/anylog_query.py` change the defaults:

```python
_AL_HOST = os.environ.get("ANYLOG_HOST", "host.docker.internal")
_AL_PORT = int(os.environ.get("ANYLOG_REST_PORT", "32149"))
```

**If your Kafka topic has a different name**, edit
`~/docker-compose/docker-makefiles/operator1-configs/local_script.al`:

```
run kafka consumer where ... and topic = (name = YOUR-TOPIC-NAME ...)
```

**If your database is named something other than `customers`**, change
`ANYLOG_DBMS = "customers"` in `anylog_query.py` and all `docker-compose.yaml`
environment variables.

**If you use a different Postgres user/password**, update:

```yaml
- PGHOST=host.docker.internal
- PGPORT=5432
- PGDATABASE=customers
- PGUSER=your_user          # change this
- PGPASSWORD=your_password  # change this
```

---

## AnyLog partition management

Data is stored in 14-day partition tables:

```
par_egauge_kafka_YYYY_MM_SEQ_d14_insert_timestamp
par_nilm_disaggregated_YYYY_MM_SEQ_d14_insert_timestamp
```

AnyLog creates new partitions automatically when `create_table=true` is set
in the operator startup command (already set in `local_script.al`).

Check active partitions:

```bash
curl -s http://localhost:32149 \
  -H "User-Agent: AnyLog/1.23" \
  -H "command: get partitions where dbms=customers and table=egauge_kafka"
```

If the Python iems-app stops returning data after a partition boundary
(every 14 days), restart iems-app to flush the partition cache:

```bash
cd ~/microgrid-manager && docker compose restart iems-app
```

---

## Adding a new appliance

1. Add an entry to `APPLIANCES` in `config.py`:

```python
"your_appliance": {
    "panel": "Panel1 (HVAC)",            # which sub-panel
    "laxity": "user_controlled_interval", # see laxity types below
    "shed_priority": 3,
    "on_threshold_w": 200,
    "power_range_w": (800, 2000),
    "avg_on_duration_min": 20,
    "typical_cycle_min": 60,
    "usage_pattern": "describe behavior here",
    "user_visible_label": "My Appliance",
},
```

2. Add it to the panel's appliance list in `CHANNELS`:

```python
"Panel1 (HVAC)": {
    "role": "subpanel",
    "appliances": ["heat_pump", "your_appliance"],  # add here
},
```

3. If it should never be shed, add it to `CRITICAL_APPLIANCES` in `config.py`:

```python
CRITICAL_APPLIANCES = {"refrigerator", "pressure_pump", "networking", "your_appliance"}
```

**Laxity types** (from Adabi 2016):

| Value | Meaning |
|---|---|
| `auto_controlled` | System can shed/restore without asking user |
| `user_controlled_interval` | Can defer to a different time window |
| `user_controlled_non_interval` | User decides each time |
| `uninterruptible` | Never shed mid-cycle (e.g. washing machine) |

---

## API endpoints

### FastAPI (port 8000)

| Method | Path | Description |
|---|---|---|
| `GET` | `/iems/health` | AnyLog + Ollama + weather status |
| `POST` | `/iems/cycle` | Run one full IEMS disaggregation cycle |
| `GET` | `/iems/channels` | List available eGauge channels |
| `GET` | `/iems/nilm` | Latest NILM states from `nilm_disaggregated` |
| `GET` | `/iems/models` | Available Ollama models |

`POST /iems/cycle` body:

```json
{
  "model": "deepseek-r1:8b",
  "window_minutes": 10,
  "mode": "on_grid"
}
```

### Node.js dashboard (port 47821)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Combined AnyLog + iems-app status |
| `GET` | `/api/snapshot` | Latest watt reading per panel |
| `GET` | `/api/history?minutes=N` | Last N minutes of all panel readings |
| `GET` | `/api/nilm` | Last 100 NILM disaggregation rows |
| `POST` | `/api/cycle` | Trigger IEMS cycle (proxies to FastAPI) |

---

## AnyLog operator config files

These files control how AnyLog operator1 starts:

**`~/docker-compose/docker-makefiles/operator1-configs/base_configs.env`**
Node name, company, cluster name, port assignments.

**`~/docker-compose/docker-makefiles/operator1-configs/advance_configs.env`**
Buffer threshold, write mode, threshold volume.

**`~/docker-compose/docker-makefiles/operator1-configs/local_script.al`**
Runs at the end of the config policy script array. Contains only the Kafka
consumer command. Do not add `run streamer` or `run operator` here — the
config policy already runs those before this file.

**`~/docker-compose/docker-makefiles/operator1-configs/patches/validate_node_policy.al`**
Patched version of AnyLog's policy validator. Adds an overlay_ip fallback so
the operator can find its existing blockchain policy when the container's
external IP differs from `host.docker.internal` (the Docker DNS name under
which the policy was registered). Without this patch, the operator tries to
create a duplicate policy, fails, and starts without Operator / Streamer /
Kafka Consumer running.

Both `local_script.al` and `patches/validate_node_policy.al` are bind-mounted
into the container by `operator1-docker-compose.yaml` — they survive
container rebuilds without needing `docker cp`.

---

## Known issues

**Partition cache** — the `_PARTITION_CACHE` dict in `anylog_query.py` never
expires at runtime. After a new 14-day partition is created, restart iems-app
to pick it up. A future fix should add a 12-hour TTL.

**Master REST not declared** — the master node's `blockchain.json` contains
unresolved AnyLog variable references from an earlier misconfiguration. Master
falls back to operator-local blockchain, which works for all current queries,
but operations that require master validation (like deleting blockchain
policies) need to be done by directly editing the operator's local
`blockchain.json`.

**LLM disaggregation returns all-OFF** — this is normal when load is very low
(late night, nobody home). The LLM correctly identifies nothing is running. If
you see all-OFF during clearly active periods, check that the Ollama model is
loaded (`curl http://localhost:11434/api/tags`) and that panel wattages in
`/api/snapshot` are non-zero.

---

## How the Models Work

The disaggregator has two layers: a **rule engine** that turns raw panel
wattage into per-appliance ON / OFF labels via deterministic rules, and a
set of **per-panel BiLSTM neural networks** that learn to reproduce those
labels from a 16-minute window of panel features. The rules are how
labels are generated; the BiLSTMs are how predictions are made at
inference time.

**One model per panel, not one global model.** Panels 1, 2 and 3 have
very different appliance physics — an HVAC compressor signature has
nothing in common with a microwave burst. Sharing weights across panels
would dilute everything, so the pipeline trains three independent
models. Each is small enough to fit in CPU memory and runs in under
2 ms per window after int8 quantization.

**Per-head specialization.** Inside each panel's model, a shared 1D
convolution extracts local power transients (motor starts, heating
ramps). The output then feeds into one independent BiLSTM branch per
appliance — each branch has its own LSTM stack and its own sigmoid
classification head. This lets each appliance specialize without
fighting with the others for shared LSTM capacity.

**Window structure.** Predictions are produced for a single timestep,
but conditioned on 100 timesteps of context at 10-second cadence —
about 16 minutes per window. The label is read at the window midpoint
(index 50). Stride 1 at training time maximizes positive examples for
sparse heads; stride 10 at inference time is the operating cadence.

**Features per timestep (12).** Four panel watt readings (Panel 1,
Panel 2, Panel 3, Shop), outside temperature, shortwave irradiance,
utility-tie current, four time encodings (`hour_sin`, `hour_cos`,
`dow_sin`, `dow_cos`), and `panelN_w_step` for the current panel — the
panel reading minus its 30-min rolling minimum. The step feature is
what most rule-based labels actually key off, so surfacing it as a
model feature lets the network see the same signal the rules see.

**Inference pipeline.** ONNX Runtime with dynamic int8 quantization on
MatMul operators. Activations stay fp32 (a real constraint for LSTM —
the speedup is ~2× not ~4×). CPU-only, no GPU dependency. The trained
models live in `services/iems/models/`:

```
Panel 1 (HVAC, 3 appliances)
  Shared:    Conv1D(32, k=5) + BatchNorm + ReLU + Dropout(0.1)
  Per head:  BiLSTM(32) → BiLSTM(16) → Dropout(0.2) → Linear(16) → Linear(1)
  Heads:     heat_pump, solar_pump, vacuum_cleaner
  Parameters: 85,827
  ONNX int8 size: 378 KB

Panel 2 (H2O, 4 appliances)
  Shared:    Conv1D(32, k=5) + BatchNorm + ReLU + Dropout(0.1)
  Per head:  BiLSTM(32) → BiLSTM(16) → Dropout(0.2) → Linear(16) → Linear(1)
  Heads:     water_heater, hair_dryer, sprinklers, bath_lights
  Parameters: 113,764
  ONNX int8 size: 480 KB

Panel 3 (Kitchen, 8 appliances)
  Shared:    Conv1D(32, k=5) + BatchNorm + ReLU + Dropout(0.1)
  Per head:  BiLSTM(32) → BiLSTM(16) → Dropout(0.2) → Linear(16) → Linear(1)
  Heads:     refrigerator, dishwasher, microwave, dryer,
             washing_machine, pressure_pump, computers, tv_stereo
  Parameters: 225,512
  ONNX int8 size: 950 KB
```

The trunk is intentionally simple (one Conv layer); the per-head BiLSTM
branches carry all the temporal modeling capacity. This keeps the model
fast and avoids one head dominating shared parameters during training.

A parallel **RandomForest** path also lives in
`services/iems/training/train_models.py` and ships its own `.joblib`
files alongside the BiLSTM ONNX artifacts. The forest is a smaller,
simpler baseline for the same labels — useful for sanity checks and as
a fallback when ONNX runtime is unavailable. Its results are summarized
in the "Test Reports" section below.

---

## Appliance Rules and Labels

Rules live in `services/iems/training/rule_engine.py`. Each rule maps
the live panel signal to one of three label values: `1` (ON, high
confidence), `0` (OFF, high confidence), `NaN` (ambiguous — dropped at
training time). For each appliance the rule below states the exact
conditions; positive counts come from each panel's
`reports/panelN_label_consensus.md` over the 35-day data window
(`2026-04-07` → `2026-05-12`, ~28 k rows of observed panel data).

### Panel 1 (HVAC)

Rule helpers used below:

```
panel1_60s    = panel1_w.rolling("60s").mean()
step          = panel1_w − panel1_w.rolling("30min").min()
weather_demand = outside_temp < 60°F OR outside_temp > 75°F
```

#### Heat pump (Panel 1)

- **Spec**: on-threshold 300 W, power range 1500–4000 W
- **Rule label**:
  - `ON` when `panel1_60s > 1500` and `weather_demand` is true
  - `OFF` when `panel1_w < 200`
  - `NaN` otherwise (in-between or no weather demand)
  - Drop to `NaN` if rule says `ON` but `panel1_w ∉ [750, 6000]` —
    inconsistent with the heat-pump power band
- **Consensus filter**: rule-only in this pass; no LLM intersection
- **Positive examples (full window)**: 2,438

#### Solar water-heater pump (Panel 1)

- **Spec**: small 240 V pump (50–250 W) that fires during solar
  irradiance; specific thresholds not documented in the appliance file
- **Rule label**:
  - `ON` when `40 < step < 300` and `irradiance > 200 W/m²` and
    `heat_pump != 1`
  - `OFF` when `irradiance < 50` or `step < 10` or `panel1_w < 30`
    or `step > 300` or `heat_pump = 1`
  - Drop to `NaN` if rule says `ON` but `panel1_w ∉ [100, 500]`
- **Consensus filter**: rule-only
- **Positive examples**: 1,466

#### Vacuum cleaner (Panel 1, mobile)

- **Spec**: 600 W threshold, range 800–1200 W; nominally on Panel 1
  but mobile across outlets
- **Rule label**:
  - `ON` when `500 < step < 1400` and `panel1_w < 2000` and
    `heat_pump != 1`
  - `OFF` when `step < 100` or `panel1_w < 100` or `heat_pump = 1`
    or `step > 1500`
  - `NaN` otherwise
- **Consensus filter**: rule-only. Heat-pump cycles mask vacuum
  positives — the meter cannot resolve a 1 kW vacuum on top of a 4 kW
  compressor
- **Positive examples**: 43

### Panel 2 (H2O)

Rule helpers:

```
p2_60s     = panel2_w.rolling("60s").mean()
p2_step    = panel2_w − panel2_w.rolling("30min").min()
irr_6h     = irradiance.rolling("6h").mean()
local_hour = ts.tz_convert("America/Los_Angeles").hour
```

The always-on panel 2 baseline at this site (150–250 W) sits inside the
sprinkler / bath-light power range, so the small-signal rules switch to
a **baseline-step formulation** (`panel2_w − 30 min rolling minimum`).
The large signals (water heater, hair dryer) keep raw-power rules
because their bands sit clearly above the baseline.

#### Water heater (Panel 2)

- **Spec**: on-threshold 500 W, range 2000–4000 W; solar-thermal
  pre-heated tank
- **Rule label**:
  - `ON` when `2000 < p2_60s < 4500`
  - `OFF` when `panel2_w < 300`
  - `OFF` (solar damping) when `irr_6h > 500 W/m²` and
    `outside_temp > 65°F` and `p2_60s < 1500` — bright warm day, the
    solar boiler likely preheated the tank
  - `NaN` otherwise
- **Consensus filter**: rule-only
- **Positive examples**: 1,227

#### Hair dryer (Panel 2)

- **Spec**: on-threshold 800 W, range 1200–1800 W; short bursts
- **Rule label**:
  - `ON` when `1100 < p2_60s < 1900` and `water_heater != 1`
  - `OFF` when `panel2_w < 300`
  - `NaN` otherwise
- **Consensus filter**: rule-only
- **Positive examples**: 57 — short bursts and infrequent use make
  this the sparsest head on the panel

#### Sprinklers (Panel 2)

- **Spec**: on-threshold 50 W, range 100–300 W; solenoid valves cluster
  in early morning and evening watering windows
- **Rule label**:
  - `am_pm` window = local hour in `[4..7]` or `[17..21]`
  - `ON` when `50 < p2_step < 250` and `am_pm` and water heater /
    hair dryer not currently `ON`
  - `OFF` when `NOT am_pm`
  - `OFF` when `p2_step < 25`
- **Consensus filter**: rule-only
- **Positive examples**: 781

#### Bath mirror lights (Panel 2)

- **Spec**: on-threshold 80 W, range 100–300 W; incandescents in the
  master bath, the only light load on Panel 2
- **Rule label**:
  - `evening` window = local hour ≥ 18 or ≤ 1
  - `ON` when `50 < p2_step < 250` and `evening` and water heater /
    hair dryer / sprinklers not currently `ON`
  - `OFF` when `NOT evening`
  - `OFF` when `p2_step < 25`
- **Consensus filter**: rule-only
- **Positive examples**: 215

### Panel 3 (Kitchen)

Rule helpers:

```
p3_60s     = panel3_w.rolling("60s").mean()
p3_delta   = panel3_w.diff()
p3_step    = panel3_w − panel3_w.rolling("30min").min()
p3_fridge  = panel3_w.rolling("4h").quantile(0.1)
local_hour = ts.tz_convert("America/Los_Angeles").hour
```

Panel 3 spends ~76% of its observed time in the 200–500 W baseline
band (fridge cycling + always-on networking + idle computers). The
mid-range heads (washer, pump, computers, TV) use the baseline-step
formulation; large clearly-separated signals (dryer, dishwasher,
microwave) keep raw-power rules. Rules apply in descending order of
signal size so smaller heads can be conditioned on the absence of
bigger appliances.

#### Dryer (Panel 3)

- **Spec**: on-threshold 1000 W, range 4000–7000 W; 240 V, the biggest
  single load in the house
- **Rule label**:
  - `ON` when `3500 < p3_60s < 7500`
  - `OFF` when `panel3_w < 2000`
- **Consensus filter (§3.2 sequential constraint)**: a dryer-`ON` event
  with no washer-`ON` in the prior 90 minutes is suspect — drop to
  `NaN` rather than force `0`
- **Positive examples**: 481

#### Microwave (Panel 3)

- **Spec**: on-threshold 200 W, range 900–1500 W; bursts often < 2 min
- **Rule label**:
  - `ON` when `p3_delta > 600` and `800 < p3_60s < 1700` and
    `dryer != 1` (rising-edge to catch short bursts that midpoint
    labeling would otherwise dilute)
  - `OFF` when `panel3_w < 600`
- **Consensus filter**: rule-only
- **Positive examples**: 175

#### Dishwasher (Panel 3)

- **Spec**: on-threshold 50 W, range 200–1800 W; multi-stage cycle
  (heater, pump, dry)
- **Rule label**:
  - `ON` when `1000 < p3_60s < 2000` and dryer / microwave not `ON`
  - `OFF` when `panel3_w < 600`
- **Consensus filter**: rule-only
- **Positive examples**: 1,337

#### Washing machine (Panel 3)

- **Spec**: on-threshold 50 W, range 200–2000 W; multi-stage (agitate,
  spin)
- **Rule label (step)**:
  - `ON` when `500 < p3_step < 2000` and dryer / microwave /
    dishwasher not `ON`
  - `OFF` when `panel3_w < 250`
- **Consensus filter**: rule-only
- **Positive examples**: 401

#### Pressure pump (Panel 3)

- **Spec**: on-threshold 200 W, range 500–1000 W; intermittent short
  cycles, correlates with water-using appliances
- **Rule label (step)**:
  - `ON` when `400 < p3_step < 1000` and dryer / microwave /
    dishwasher / washer not `ON`
  - `OFF` when `panel3_w < 250`
- **Consensus filter**: rule-only
- **Positive examples**: 63

#### Refrigerator (Panel 3)

- **Spec**: on-threshold 50 W, range 80–200 W; always-on, cyclic
  compressor
- **Rule label**:
  - `ON` when `50 < p3_fridge < 250` — the 4 h 10th-percentile is
    "what the panel looks like when nothing else is on"
  - `OFF` when `p3_fridge < 30` — extremely rare at this site
- **Consensus filter**: rule-only. The OFF class is empty in this
  window — the fridge truly runs continuously
- **Positive examples**: 13,963

#### Computers (Panel 3)

- **Spec**: on-threshold 100 W, range 200–500 W; daytime cluster
- **Rule label (step)**:
  - `work_hours` = local hour in `[7..22]`
  - `ON` when `100 < p3_step < 500` and `work_hours` and no bigger
    appliance `ON`
  - `OFF` when `NOT work_hours` or `panel3_w < 100`
- **Consensus filter**: rule-only
- **Positive examples**: 5,995

#### TV / stereo (Panel 3)

- **Spec**: on-threshold 80 W, range 100–200 W; evening cluster
- **Rule label (step)**:
  - `evening` = local hour ≥ 17 or ≤ 1
  - `ON` when `80 < p3_step < 200` and `evening` and no bigger
    appliance and computers not `ON`
  - `OFF` when `NOT evening` or `panel3_w < 70`
- **Consensus filter**: rule-only
- **Positive examples**: 1,437

---

## Training Pipeline

Eight numbered steps from raw eGauge readings to a deployable ONNX
file. All artifacts land under `services/iems/training/` (scripts,
intermediates, reports) and `services/iems/models/` (trained models).

1. **Data extraction** — `extract_panel1.py` and `extract_panel1_pg.py`
   pull the available eGauge history month-by-month from `egauge_kafka`
   partitions, join Open-Meteo weather (10-min resolution), and
   resample to a 10-second grid with gaps backfilled by one step.
   Output: `data/panel1_60d.parquet` with all four panel watt
   readings plus weather and time features. Note: the data window
   on disk is 35 days, not 60 — the eGauge stream only began
   producing dense Kafka data around `2026-04-07`.

2. **Label generation** — `labels_panel1.py`, `labels_panel2.py`,
   `labels_panel3.py` apply the rules in `rule_engine.py` to the
   parquet and emit per-appliance label columns. Each label is
   one of `{0, 1, NaN}`. Reports of class balance, diurnal
   histograms, and run-length distributions get written to
   `reports/panelN_label_consensus.md`.

3. **Window construction** — `windows_panelN.py` slides a 100-step
   window over the labeled parquet, computes 12-feature vectors per
   timestep, and reads the appliance label at the window midpoint.
   Windows where all heads are `NaN` at the midpoint are dropped.
   Split: time-based 70 / 10 / 20 by observed-row position (not by
   calendar day — calendar splits put almost everything into val
   and test because the recoverable history is short).

4. **Feature standardization** — mean and std are computed on the
   training split only and saved to `services/iems/models/panelN_norm.json`.
   The same stats normalize val, test, and live inference inputs.

5. **Model training** — `train_panelN.py` builds the per-panel
   architecture described above and trains with AdamW
   (`lr=1e-3`, `weight_decay=1e-4`), batch size 256, per-head
   masked BCE that ignores `NaN` rows, and `pos_weight = neg / pos`
   per appliance to balance the class imbalance. Early stopping
   watches macro-average validation F1 with patience 12–15 epochs.
   CPU-only. Per-panel runtime on this Mac: Panel 1 ≈ 10 min, Panel 2
   ≈ 15 min, Panel 3 ≈ 40 min.

6. **ONNX export** — `export_panelN.py` traces the PyTorch model
   to ONNX with `opset_version=17` and a dynamic batch axis. Output:
   `services/iems/models/nilm_panelN.onnx`.

7. **Int8 quantization** — `quantize_dynamic` with `weight_type=QInt8`
   compresses the MatMul weights. Activations remain fp32 (LSTM
   limitation). Output: `nilm_panelN_int8.onnx` — usually ~5–10%
   larger than fp32 because the dynamic-quant metadata adds overhead
   for small weight tensors.

8. **Real-time monitoring** — `realtime_monitor.py` (Panel 1) and
   `realtime_monitor_rules.py` (unified rule-only path) pull a fresh
   window from AnyLog every 10 s, run the int8 ONNX model, log each
   prediction with a timestamp, and track per-appliance state
   transitions. Output: `reports/realtime_<stamp>.jsonl` plus a
   summary `.md` written on `SIGINT`. The monitor never touches
   `services/iems/load/disaggregator.py` and never writes to
   `nilm_disaggregated`.

A parallel RandomForest pipeline lives alongside — `pull_data.py` →
`make_labels.py` → `build_windows.py` → `train_models.py` →
`smoke_test.py`. It uses simpler threshold-based labels (no rule
engine), 20-feature engineered windows (mean/std/min/max/median/range
+ last 10 raw values + cyclic time encodings), and one
`MultiOutputClassifier(RandomForestClassifier)` per panel. Trained
models land at `services/iems/models/nilm_PanelN_<role>.joblib`.

---

## Test Reports

Numbers below are quoted exactly from
`services/iems/training/reports/panelN_eval.md`. All evaluations use
the int8 ONNX model on the held-out test split, threshold 0.5.

#### Panel 1 — Test Set Results

| Appliance | Precision | Recall | F1 | Acceptance bar | Status |
|---|---:|---:|---:|---:|---|
| Heat pump | 0.052 | 0.920 | 0.099 | ≥ 0.92 | missed by 0.821 |
| Solar pump | 0.000 | 0.000 | 0.000 | ≥ 0.80 | missed by 0.800 |

Confusion matrices (test split, 4 days, stride 1):

```
heat_pump            pred=0   pred=1          solar_pump          pred=0   pred=1
  actual=0     1287      417                    actual=0     3484     1235
  actual=1        2       23                    actual=1      242        0
```

**Latency** (int8 ONNX, single window, CPU, 10 k iterations,
50-step warm-up):

- FP32 ONNX: 0.336 ms / window
- int8 dynamic quant: 0.360 ms / window
- Bar: ≤ 1.5 ms — **met**

**Positive examples in training data** (after consensus filtering):
- Heat pump: 2,438
- Solar pump: 1,466
- Vacuum cleaner: 43 (head was trained but no separate eval bar)

#### Panel 2 — Test Set Results

| Appliance | Precision | Recall | F1 | Acceptance bar | Status |
|---|---:|---:|---:|---:|---|
| Water heater | 0.000 | 0.000 | 0.000 | ≥ 0.90 | test slice has zero positives |
| Hair dryer | 0.000 | 0.000 | 0.000 | ≥ 0.75 | test slice has zero positives |
| Sprinklers | 0.043 | 0.980 | 0.082 | ≥ 0.70 | missed by 0.618 |
| Bath lights | 0.000 | 0.000 | 0.000 | ≥ 0.65 | test slice has 2 positives |

Confusion matrices:

```
water_heater         pred=0   pred=1          hair_dryer           pred=0   pred=1
  actual=0     2988        0                    actual=0     2988        0
  actual=1        0        0                    actual=1        0        0

sprinklers           pred=0   pred=1          bath_lights          pred=0   pred=1
  actual=0     1645     1116                    actual=0     2650        0
  actual=1        1       50                    actual=1        2        0
```

**Latency**:

- FP32 ONNX: 0.501 ms / window
- int8 dynamic (MatMul-only): 0.504 ms / window
- Bar: ≤ 2.5 ms — **met**

**Positive examples in training data** (after consensus filtering):
- Water heater: 1,227
- Hair dryer: 57
- Sprinklers: 781
- Bath lights: 215

#### Panel 3 — Test Set Results

| Appliance | Precision | Recall | F1 | Acceptance bar | Status |
|---|---:|---:|---:|---:|---|
| Refrigerator | 1.000 | 1.000 | 1.000 | ≥ 0.85 | met |
| Dishwasher | 0.125 | 0.763 | 0.215 | ≥ 0.65 | missed by 0.435 |
| Microwave | 0.394 | 0.963 | 0.559 | ≥ 0.55 | met |
| Dryer | 0.024 | 0.805 | 0.047 | ≥ 0.85 | missed by 0.803 |
| Washing machine | 0.360 | 0.214 | 0.269 | ≥ 0.65 | missed by 0.381 |
| Pressure pump | 0.167 | 0.750 | 0.273 | ≥ 0.70 | missed by 0.427 |
| Computers | 0.989 | 0.678 | 0.804 | ≥ 0.55 | met |
| TV / stereo | 1.000 | 1.000 | 1.000 | ≥ 0.55 | met |

Confusion matrices:

```
refrigerator         pred=0   pred=1          dishwasher           pred=0   pred=1
  actual=0        0        0                    actual=0     1792      904
  actual=1        0     2589                    actual=1       40      129

microwave            pred=0   pred=1          dryer                pred=0   pred=1
  actual=0     2656       40                    actual=0     1605     1325
  actual=1        1       26                    actual=1        8       33

washing_machine      pred=0   pred=1          pressure_pump        pred=0   pred=1
  actual=0     2554       16                    actual=0     2481       15
  actual=1       33        9                    actual=1        1        3

computers            pred=0   pred=1          tv_stereo            pred=0   pred=1
  actual=0      454        6                    actual=0     1198        0
  actual=1      259      545                    actual=1        0      254
```

**Latency**:

- FP32 ONNX: 1.235 ms / window
- int8 dynamic (MatMul-only): 1.041 ms / window
- Bar: ≤ 4 ms — **met**

**Positive examples in training data** (after consensus filtering):
- Refrigerator: 13,963
- Dishwasher: 1,337
- Microwave: 175
- Dryer: 481
- Washing machine: 401
- Pressure pump: 63
- Computers: 5,995
- TV / stereo: 1,437

### RandomForest baseline (parallel pipeline)

Trained from threshold-only labels (no rule engine) on 20-dimensional
engineered windows, 80 / 20 chronological split. Numbers from the
`train_models.py` log on 2026-05-12. Note: the threshold labels collapse
the always-on fridge into the 80–200 W band, which almost never fires
alone on this house — see "Where Results Are Failing" below.

| Panel | Appliance | F1 |
|---|---|---:|
| Panel 1 (HVAC) | heat_pump | 0.942 |
| Panel 2 (H2O) | water_heater | 0.810 |
| Panel 3 (Kitchen) | cooktop | 0.784 |
| Panel 3 (Kitchen) | microwave | 0.842 |
| Panel 3 (Kitchen) | dishwasher | 0.000 |
| Panel 3 (Kitchen) | fridge | 0.037 |

---

## Real-Time Monitoring Results

### Panel 1 — live session 2026-05-12

Pulled from `reports/panel1_first_session.md` (the only first-session
log on disk as of this commit).

- **Session bounds**: `2026-05-12 04:55:11 UTC` → `2026-05-12 05:58:33 UTC`
- **Duration**: 63 min 22 s
- **Total ticks**: 365 (target ≥ 360)
- **Errors**: 0
- **Decision thresholds**: HP = 0.68, SP = 0.53 (chosen on val split)

Per-appliance behaviour during the session:

| appliance | ON ticks | OFF ticks | ON-fraction | off→on | on→off |
|---|---:|---:|---:|---:|---:|
| heat pump | 0 | 365 | 0.0% | 0 | 0 |
| solar pump | 0 | 365 | 0.0% | 0 | 0 |

The session ran 21:55–22:58 PT — a single idle nighttime hour with
`irradiance = 0`. Both heads were correctly OFF; HP probability held
at 0.249 ± 0.001 (vs. 0.68 threshold), SP at 0.323 ± 0.000 (vs. 0.53).
No transitions to validate. Live `panel1_w` ranged 314 → 398 W
(fan-only band, below the 1500 W compressor threshold).

Inference latency (model only, fetch excluded):

| stat | value (ms) |
|---:|---:|
| count | 365 |
| mean | 0.462 |
| p50 | 0.379 |
| p95 | 0.901 |
| p99 | 1.971 |
| max | 3.584 |

p99 1.971 ms clears the 2 ms bar.

### Panel 2 and Panel 3 — first sessions

`panel2_first_session.md` and `panel3_first_session.md` have not yet
been written. The unified rule-based monitor `realtime_monitor_rules.py`
has run a 100-tick session covering all three panels — see
`reports/realtime_rules_2026-05-12T1825_summary.md`. Per-appliance
NN-based first sessions for Panels 2 and 3 are listed as **not yet
measured**.

---

## Where Results Are Failing

The following heads did not meet their per-panel F1 acceptance bars on
the held-out test split. Each entry quotes the actual F1 from the eval
report, the target bar, the likely cause, and a concrete next step.

### Panel 1 · heat_pump

- **Target F1**: 0.92
- **Actual F1**: 0.099
- **Gap**: -0.821
- **Likely cause**: the test split (May 6–7, 11–12) sat in a low-load
  shoulder week — only 25 heat-pump positives across 1,729 valid
  windows. The model is firing too eagerly (recall 0.92, precision
  0.05) because the training pos_weight (`neg/pos ≈ 6:1`) pushed the
  decision boundary toward positive predictions. With so few real
  positives in test, almost every FP costs ~0.04 in precision.
- **Path forward**: threshold tuning per head — the val-tuned threshold
  was 0.68 but the eval used the default 0.5. Re-running eval at 0.68
  is a 5-line fix. Longer term, add more cold-weather days to the
  training window.

### Panel 1 · solar_pump

- **Target F1**: 0.80
- **Actual F1**: 0.000
- **Gap**: -0.800
- **Likely cause**: the test split has 242 true positives, the model
  predicted zero of them (0 TP, 0 FP, 242 FN). Combined with 1,235
  false-positive predictions where the truth was `0`, the head is
  effectively decoupled from the input. The solar-pump rule depends on
  a baseline step that the model never sees consistently — `panel1_w_step`
  is computed locally inside the window and rarely reaches the
  40–300 W trigger band during the 16-min context.
- **Path forward**: feed the rule directly as an auxiliary feature
  (concat the rule's binary output into the input vector), or extend
  the step lookback to 60 min so daytime steady-state activity
  registers above baseline.

### Panel 2 · water_heater

- **Target F1**: 0.90
- **Actual F1**: 0.000
- **Gap**: -0.900
- **Likely cause**: the test slice (May 7–12) has zero water-heater
  positives in the labeled data. The household didn't run the
  electric element during that window — likely because the solar
  boiler was sufficient. F1 is undefined when both precision and
  recall are 0 with no positives. Validation F1 was 0.94 on May 6;
  the model itself learned the signal.
- **Path forward**: re-evaluate against the validation split or a
  k-fold split. Long term, capture a longer training window with
  active electric-element cycles.

### Panel 2 · hair_dryer

- **Target F1**: 0.75
- **Actual F1**: 0.000
- **Gap**: -0.750
- **Likely cause**: only 57 hair-dryer positives exist across the
  entire 35-day data window (~9.5 minutes of total ON time) and zero
  appear in train or test. The window-midpoint label dilutes short
  bursts further. The model collapses to always-OFF.
- **Path forward**: shrink the window for this head specifically
  (50-step ≈ 8 min), oversample positives during training, or use a
  rising-edge label instead of midpoint to capture bursts the way
  the microwave rule does on Panel 3.

### Panel 2 · sprinklers

- **Target F1**: 0.70
- **Actual F1**: 0.082
- **Gap**: -0.618
- **Likely cause**: recall is 0.98 (model fires on almost every real
  positive) but precision is 0.04 — the aggressive pos_weight pushed
  the model toward positive predictions and 1,116 windows in the
  outside-AM/PM band were over-predicted.
- **Path forward**: same as heat_pump — threshold tuning on the val
  split. The rule itself does respect AM/PM windows; the model is
  just calibrated too aggressively.

### Panel 2 · bath_lights

- **Target F1**: 0.65
- **Actual F1**: 0.000
- **Gap**: -0.650
- **Likely cause**: only 2 true positives in the test split (all
  bath-light activity concentrated in May 6, which fell into val).
  Cannot get a meaningful F1 from 2 positives.
- **Path forward**: stratified split that ensures each head has ≥ 50
  positives per split.

### Panel 3 · dishwasher

- **Target F1**: 0.65
- **Actual F1**: 0.215
- **Gap**: -0.435
- **Likely cause**: dishwasher's multi-stage signature (heater stage
  at ~1.5 kW, then pump stage at ~200 W) overlaps the washer band
  during pump phase. Model catches the heat stage (recall 0.76) but
  predicts ON for 904 FPs that are actually washer or computer
  activity. The hierarchical rule order (dishwasher after dryer +
  microwave) does not enforce a similar masking at inference.
- **Path forward**: enforce the rule's hierarchical mask at inference
  time — if `panel3_w` is in a band claimed by a higher-priority
  appliance, suppress lower-priority head positives.

### Panel 3 · dryer

- **Target F1**: 0.85
- **Actual F1**: 0.047
- **Gap**: -0.803
- **Likely cause**: dryer's `pos_weight ≈ 88` from training pushed the
  head into 1,325 false positives. The §3.2 sequential constraint
  (suspect dryer-without-washer) was applied as a label drop at
  training time but is not enforced at inference. Day-time spikes
  from other appliances fall into the 3.5–7.5 kW band and get tagged
  as dryer.
- **Path forward**: gate the dryer prediction at inference on the
  washer-ON history — if no washer-ON in the prior 90 min, suppress
  dryer positives. Same rule, applied at the right layer.

### Panel 3 · washing_machine

- **Target F1**: 0.65
- **Actual F1**: 0.269
- **Gap**: -0.381
- **Likely cause**: washer has the lowest recall (0.21) among the
  failing heads — the multi-stage signature is hard to learn from
  the 100-step window alone because agitate and spin phases look
  very different. Most windows hit either the agitate cycle (low,
  intermittent) or the spin (high, brief), not both.
- **Path forward**: try a sequence-to-sequence head with per-timestep
  output, or extend window to 200 steps to catch full cycle context.

### Panel 3 · pressure_pump

- **Target F1**: 0.70
- **Actual F1**: 0.273
- **Gap**: -0.427
- **Likely cause**: 63 total positives across 35 days, 4 in test.
  Short pump cycles (mean 16 s in the label run-length report) and
  no clean separator from the panel baseline. Model fires recall
  0.75 but precision 0.17 on 15 FPs against 3 TPs.
- **Path forward**: same data-availability story as hair_dryer. Wait
  for more pump cycles to accumulate, or condition the head on
  recent water-using appliance activity.

---

## Known Bugs

### Model

- **Window-midpoint label dilution.** Predictions are made for the
  middle of a 16-minute window. Appliances with bursts shorter than
  ~2 minutes (microwave, hair dryer) rarely overlap the midpoint;
  positive labels under-count those bursts. Microwave partially works
  around this by using a rising-edge ON rule, but the model still
  trains against midpoint labels. Caps achievable F1 for short-burst
  heads.

- **8-minute prediction lag.** Because the prediction is for the
  window midpoint, "now" in `realtime_monitor.py` is actually about
  8 minutes behind wall-clock. Acceptable for testing data flow and
  for hourly recommendations, not for sub-minute real-time control.

- **Refrigerator class imbalance.** Fridge is ON 100% of observed
  time at this house — there are zero negatives in the consensus
  labels. The model trivially predicts always-ON. Standard BCE
  with `pos_weight=1` learned this correctly but the head provides
  no real signal for state transitions during high-load periods
  when other appliances mask the fridge signature.

- **TV / computers overlap.** Both small loads in similar power
  ranges; the model relies entirely on `hour_sin`/`hour_cos` to
  discriminate. Anomalous use (a daytime movie, an evening work
  session) will be misclassified. Test scores look strong because
  the test window happens to be on-schedule.

- **Dishwasher multi-stage signature.** Heat-element and pump
  stages have very different power signatures. The model catches
  the heat stage but tends to miss the pump stage, fragmenting
  what should be one contiguous cycle. Reflected in the
  precision-0.13 / recall-0.76 split for dishwasher on test.

- **Washer → dryer sequential constraint enforced as label drop,
  not prediction constraint.** The consensus labeler drops suspect
  dryer-without-washer rows from training, but the model itself
  does not enforce the rule at inference. False-positive dryer
  predictions during non-laundry hours are still possible — the
  1,325 dryer FPs on test are largely this.

- **Cross-panel features may be redundant for Panel 1.** Panel 1
  gets all four panel watt features. With only three heads —
  none of which depend on Panel 2/3 activity — the cross-panel
  signal is mostly noise. Worth an ablation.

- **Cooktop and oven are not modeled in the BiLSTM path.** Sparse
  positive class. The RandomForest path includes cooktop (F1 0.78)
  but the rule_engine excludes it because labels were insufficient
  to train a dedicated head.

- **Solar boiler interaction is heuristic.** Phase 3 rule labels
  for Panel 2 damp water-heater positives based on 6-hour mean
  irradiance and outside temperature. The model has no feature for
  tank temperature directly, so its solar awareness is only as
  good as the irradiance proxy.

- **Threshold-vs-default mismatch in eval.** Training tunes per-head
  thresholds on the val split (Panel 1 stored thresholds HP=0.68,
  SP=0.53 in `panel1_norm.json`), but `eval_panelN.py` runs at the
  default 0.5. Several missed F1 bars would close materially under
  the tuned thresholds. Either bake the thresholds into the ONNX
  output layer or wire them into the eval script.

- **35-day training window is the floor, not the ceiling.** Kafka
  only began producing dense data ~5 days before this commit.
  Several heads' positive classes are single-digit. Re-train with
  a longer window as data accumulates.

### AnyLog partitions

- **Parenthesized channel names break `WHERE` clauses.**
  `WHERE nm = 'Panel1 (HVAC)'` returns empty results. Workaround:
  fetch the time range and filter `nm` client-side. Affects every
  query against `egauge_kafka` and any table with parenthesized
  channel names.

- **Parent table queries return empty.** Must query specific
  `par_<table>_<YYYY>_<MM>_00_d14_insert_timestamp` partitions.
  Querying the parent table name returns nothing even when rows
  exist in the partitions. Affects `egauge_kafka` and
  `nilm_disaggregated`.

- **`destination: network` header times out on direct operator
  commands.** The blockchain operator policy carries a WAN IP that
  fails NAT hairpinning on this Mac. Workaround: omit the header
  for any command targeting `127.0.0.1:32149`. Codified in
  `anylog_query.py`.

- **macOS resolves `localhost` to IPv6 (`::1`).** Docker port
  bindings are IPv4 only. Use `127.0.0.1` everywhere. Affects every
  script that connects to AnyLog, Ollama, Postgres, or Kafka.

- **`local_script.al` does not auto-execute on operator container
  start.** Existing `node_policy` collision. After every operator
  restart, three POSTs must be issued manually (per the standard
  restart sequence). The patched `validate_node_policy.al` fixes
  most of this but operator restarts can still land in a state where
  Kafka Consumer is missing.

- **Cross-circuit label drift on Panel 3 appliances.** The
  `appliance_data_updated.txt` spec moves dryer, washing machine,
  and pressure pump from Shop to Panel 3, but historical
  `nilm_disaggregated` rows still tag these under `circuit = 'Shop'`.
  The Panel 3 training pipeline rescues both circuits as valid label
  sources; the production disaggregator does not yet do this.

- **Partition boundary at month rollover.** Queries that span the
  last day of one month and the first of the next must hit two
  partitions. None of the training scripts handle this elegantly —
  they iterate month-by-month, which means a window straddling the
  boundary can be silently dropped. Affects training extracts run
  near month-end.

- **Backfill limit of 1 step at the 10-second grid.** Resampling
  backfills gaps with a single 10-second step. Larger gaps (network
  outages, Kafka consumer lag) leave `NaN` rows that get dropped
  from training. The training scripts do not log how many rows are
  dropped this way — gap statistics belong in a future label audit.

- **Partition cache never expires.** `_PARTITION_CACHE` in
  `anylog_query.py` is populated at process start and never
  invalidated. After a new 14-day partition is created, restart
  `iems-app` to pick it up. A 12-hour TTL would fix this without
  user intervention.

- **PostgreSQL operator endpoint (port 5432) intermittently rejects
  handshakes.** Observed several times during this work — the TCP
  port is listening but the handshake closes mid-connection. AnyLog
  REST on `:32149` has the same symptom. The training scripts now
  fall back through PG → AnyLog REST → local parquet cache so an
  outage doesn't block work, but the operator container itself
  needs investigation.

---

## Research basis

- **Xue et al. 2025** — LLM4NILM: Prompting Large Language Models for
  Training-Free Non-Intrusive Load Monitoring (arXiv:2505.06330). The
  `disaggregator.py` + `prompt_builder.py` + `output_normalizer.py` pipeline
  implements this paper's zero-shot approach.

- **Adabi 2016** — UCSC PhD thesis on residential microgrid IEMS. The four-
  domain architecture (User, Load, Generation, Storage), laxity taxonomy,
  load shedding priority, and decision support flow branches come from this
  work.

---

## License

See LICENSE file.
