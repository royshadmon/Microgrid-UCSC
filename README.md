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
