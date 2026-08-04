# AnyLog Query Cookbook

Verified working REST shapes for the IEMS pipeline against live operator1
(host.docker.internal:32149 from inside Docker, 127.0.0.1:32149 from the Mac).

This is the source of truth. If something below stops working, run the
verification scripts in `tests/` before changing the canonical helper in
`services/iems/load/anylog_query.py`.

---

## VERIFIED 2026-04-28 — `run client ()` returns err 156

**Test:**

```bash
curl -s --max-time 10 http://127.0.0.1:32149 \
  -H "User-Agent: AnyLog/1.23" -H "destination: network" \
  -H 'command: run client () sql customers format=json and stat=false "SELECT MAX(ts) as latest FROM egauge_kafka WHERE ts > NOW() - 5 minutes"'
```

**Live response:**

```json
{"method": "get", "node": "192.168.65.1", "err_code": 156, "err_text": "Wrong HTTP method used"}
HTTP 400
```

**Conclusion:** the `run client ()` prefix is a Native-CLI construct that
the REST endpoint refuses on GET. Sources that recommend it (older AnyLog
docs, the previous anylog_query.py docstring) are wrong for our REST path.
The `destination: network` header is what routes the query through the
cluster operators.

Confirmed against live operator1 with Cluster Member: True and active
Kafka consumer. Evidence saved in
`test_results/20260428_103401_02_syntax_comparison.log`.

---

## Canonical SQL query shape

```
GET http://{anylog_url}
Headers:
  User-Agent:  AnyLog/1.23
  destination: network
  command:     sql customers format=json and stat=false "<SQL>"
```

**Response shapes:**

- `{"Query": [...]}` → rows
- `{"reply": "Empty data set"}` → legitimate zero-row result, NOT an error
- `{"err_code": ..., "err_text": ...}` → parser/syntax error

A correct caller treats both `Query` and the empty-data reply as success.

---

## Canonical admin command shape

For `get columns`, `get tables`, `get processes`, etc. — no destination
header, no `sql` prefix, just the raw command.

```
GET http://{anylog_url}
Headers:
  User-Agent: AnyLog/1.23
  command:    get columns where dbms = customers and table = nilm_disaggregated
```

Response is plain text (table-formatted), not JSON.

---

## Parser quirk: parenthesized channel literals

Channel names like `Panel1 (HVAC)`, `Panel2 (H2O)`, `Panel3 (Kitchen)`
contain parentheses, which the AnyLog SQL parser handles unreliably.

| Form | Result |
|------|--------|
| `WHERE nm = 'Grid Power'` | ✓ works |
| `WHERE nm = 'Panel1 (HVAC)'` | ✗ returns Empty data set even when rows exist |
| `WHERE nm IN ('Panel1 (HVAC)', 'Panel2 (H2O)')` | ✗ IncompleteRead |
| `WHERE nm LIKE '%Panel%'` | ✗ IncompleteRead |

**Workaround that works (verified 2026-04-28):**

```sql
SELECT ts, nm, w FROM egauge_kafka
WHERE ts > NOW() - 5 minutes
ORDER BY ts ASC
```

Fetch by time only, partition by `nm` client-side. One query returns all
six panels including the three parenthesized ones. Evidence in
`test_results/20260428_103401_02e_direct_panels_test.log`.

---

## Insert path (streaming ingestion)

Predictions land in `nilm_disaggregated` via PUT:

```
PUT http://{anylog_url}
Headers:
  User-Agent:   AnyLog/1.23
  Content-Type: application/json
  command:      data put where dbms=customers and table=nilm_disaggregated and mode=streaming and format=json
Body: JSON array of records
```

`nilm_disaggregated` schema (verified live):

| Column           | Type                          |
|------------------|-------------------------------|
| ts               | timestamp without time zone   |
| circuit          | character varying             |
| appliance        | character varying             |
| state            | character varying             |
| confidence       | double                        |
| avg_w            | double                        |
| median_w         | double                        |
| std_w            | double                        |
| window_start     | timestamp without time zone   |
| window_end       | timestamp without time zone   |
| window_n         | integer                       |

`row_id` and `insert_timestamp` are managed by AnyLog — do not include
them in the insert payload.

---

## Solar Assistant ingestion (`solar_data`, verified live)

Measured PV/battery/grid/load telemetry from a Solar Assistant box, forwarded by
`streaming/solar-pipeline/solar_producer.py`. Two ingestion modes; broker mode is
the default and is what's running in production.

**Schema (6 mapped columns, matches the AnyLog blockchain policy):**

| Column          | Type  | Source                                    |
|-----------------|-------|--------------------------------------------|
| pv_power        | float | `inverter_1/pv_power`                     |
| battery_power    | float | `total/battery_power`                     |
| battery_soc      | float | `total/battery_state_of_charge`           |
| grid_power       | float | `inverter_1/grid_power`                   |
| load_power       | float | `inverter_1/load_power`                   |
| device_mode      | str   | `inverter_1/device_mode`                  |

`ts` and `insert_timestamp` are added/managed automatically; do not include
`insert_timestamp` in the payload (same rule as `nilm_disaggregated`, above).
The table is partitioned `by month` (not `d14` like `egauge_kafka`) — the
14-day partition-name scheme was found to generate unreachable partitions
across some month boundaries, so `solar_data` (and now `customers` generally)
uses `partition customers * using insert_timestamp by month` in
`operator1-configs/local_script.al` instead.

### Broker mode (default, `INGEST_MODE=broker`)

AnyLog acts as its own MQTT broker. The operator subscribes to itself via a
`run msg client` command (added once, in `local_script.al`, before `run
operator`) that maps the `solar` topic's JSON fields straight to columns:

```
run msg client where broker = local and port = 1883 and topic = (
  name = solar and dbms = customers and table = solar_data and
  column.ts.timestamp = "bring [ts]" and
  column.pv_power.float = "bring [pv_power]" and
  column.battery_power.float = "bring [battery_power]" and
  column.battery_soc.float = "bring [battery_soc]" and
  column.grid_power.float = "bring [grid_power]" and
  column.load_power.float = "bring [load_power]" and
  column.device_mode.str = "bring [device_mode]")
```

`solar_producer.py` then just publishes a plain JSON payload to that topic on
the AnyLog broker (`ANYLOG_BROKER:1883`, topic `solar`) — no REST call, no
`command:` header, just an MQTT publish. Verified by hand-publishing a raw
MQTT message to the `solar` topic and confirming it landed in `solar_data`.

### REST fallback (`INGEST_MODE=rest`)

Same streaming-PUT shape as `nilm_disaggregated`, pointed at `solar_data`:

```
PUT http://{anylog_url}
Headers:
  User-Agent: AnyLog/1.23
  type:       json
  dbms:       customers
  table:      solar_data
  mode:       streaming
Body: {"ts": "...", "pv_power": 4164.0, "battery_power": 3029.0,
       "battery_soc": 95.0, "grid_power": 59.0, "load_power": 844.0,
       "device_mode": "..."}
```

Use this path only if the broker's `run msg client` mapping isn't active yet
— it hits the same table with the same schema, just over REST instead of MQTT.

### Reading it back — `fetch_solar_snapshot` (`services/iems/load/anylog_query.py`)

The inference loop calls this once per 30 s tick to get the latest measured
row for rule gating (`rules_additive.py`'s `_low_solar` / `_battery_charging`):

```sql
SELECT ts, pv_power, battery_power, battery_soc, grid_power, load_power, device_mode
FROM solar_data
WHERE ts > NOW() - 10 minutes
ORDER BY ts DESC
```

Returns `{}` if there's no row inside the window (e.g. `solar-producer` is
down or Solar Assistant is offline) — callers treat an empty dict as "no
measured solar available" and fall back to the weather-derived estimate.
The returned dict includes `age_s`, the row's age in seconds, so callers can
also reject a technically-present but stale snapshot if they choose to.

---

## Live channel inventory (16 total, eGauge18646)

| Channel                 | Type     | Workaround? |
|-------------------------|----------|-------------|
| Grid Power              | sub      | no          |
| Generac Power           | sub      | no          |
| Shop                    | sub      | no          |
| VrmsA, VrmsB, F1        | metric   | no          |
| I11, I12, I21, I22, I31, I32 | metric | no       |
| Current on Utility Tie  | metric   | no          |
| Panel1 (HVAC)           | sub      | **yes**     |
| Panel2 (H2O)            | sub      | **yes**     |
| Panel3 (Kitchen)        | sub      | **yes**     |

The three parenthesized panels require the time-only fetch + client-side
filter pattern.
