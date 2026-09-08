# Streaming and storage

All figures read off Pat's box on 2026-09-08.

## Four independent writers

| writer | path | table | rate |
|---|---|---|---|
| `anylog-consumer` | Kafka to AnyLog REST streaming PUT | `energy_readings` | 850 to 960 rows/min |
| operator1's own Kafka consumer | Kafka direct into the node | `egauge_kafka` | 850 to 960 rows/min |
| `solar-producer` | Solar Assistant to AnyLog | `solar_data` | 11 to 12 rows/min |
| `iems-inference` | AnyLog REST streaming PUT | `nilm_disaggregated` | 44 rows/min |
| `iems-dashboard` | AnyLog REST streaming PUT | `anomalies` | only when the relay acts |

Sampled twice on 2026-09-08, six hours apart: 846 / 848 / 12 / 44 and then
948 / 950 / 11 / 44. The `nilm_disaggregated` figure is exact because it is
generated, 22 heads on a 30 s tick. The eGauge figures vary because a 60 second
SQL window does not align with the poll boundary.

`solar_data` and `nilm_disaggregated` run on a different path from eGauge, so a
split verdict localises a fault immediately. Both staying current while the first
two freeze is the signature of the producer, not of anything downstream.

The two eGauge rates track each other because both come from the same Kafka
topic. The producer reports a steady 960 messages a minute, so anything in the
850 to 960 band is a windowing artefact, not a loss. A number well under 850, or
one that keeps falling, is worth chasing.

## The meter

eGauge18646 at `192.168.254.19`. The producer polls `dev.get("/register?rate")`
once per second and publishes one Kafka message per register, keyed by register
name. Sixteen registers.

```
Panel1 (HVAC)   Panel2 (H2O)   Panel3 (Kitchen)   Shop
Grid Power      Generac Power  Current on Utility Tie
I11 I12 I21 I22 I31 I32        VrmsA  VrmsB  F1
```

Raw panel power is negative by convention, so every rule and labeller runs on
`abs(w)`.

### The producer hang

This bug has cost 107 hours of data across three incidents and is the single
largest source of data loss on the deployment.

| date | duration lost |
|---|---|
| 2026-08-29 00:24 to 08-31 20:32 | 68 h |
| 2026-09-01 00:47 to 20:07 | 19 h |
| 2026-09-03 02:23 to 22:23 | 20 h |

The hang is inside `dev.get("/register?rate")` in the `egauge.webapi` library,
which offers no way to pass a timeout through. `requests.get` therefore runs with
`connect timeout=None`, and a meter blip mid-read blocks the socket read forever.
The loop never returns, nothing is logged, PID 1 stays alive and Docker reports
the container healthy. Restarting it takes 46 to 48 s and needs SIGKILL, which is
the hung thread signature.

The permanent fix is applied **on Pat's box** and is not yet in the repository.
`egauge_kafka_producer.py` lines 38 to 57.

```python
HTTP_TIMEOUT  = (int(os.environ.get("EGAUGE_CONNECT_TIMEOUT", "5")),
                 int(os.environ.get("EGAUGE_READ_TIMEOUT", "10")))
WATCHDOG_SECS = int(os.environ.get("WATCHDOG_SECONDS", "120"))

_orig_session_request = requests.Session.request
def _request_with_timeout(self, method, url, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = HTTP_TIMEOUT
    return _orig_session_request(self, method, url, **kw)
requests.Session.request = _request_with_timeout

_last_poll = [time.monotonic()]
def _watchdog():
    stalled = time.monotonic() - _last_poll[0]
    if stalled > WATCHDOG_SECS:
        os._exit(1)
```

`restart: unless-stopped` brings the container back. The producer logs
`Watchdog armed: exit if no poll completes within 120 s` at startup, which is the
line to look for after any restart. Current state is poll #288000, 16 registers,
960 msg/min, healthy for three days.

Nothing buffers upstream of Kafka, so every one of these gaps is permanent.

## Kafka

KRaft mode, single node, `apache/kafka:3.9.2`. Topic `egauge-energy`, three
partitions, replication factor 1, 168 h retention, 1 GB retention bytes, 100 MB
segments.

```
KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092,EXTERNAL://host.docker.internal:9094
```

Containers reach the broker on `kafka:9092`. The AnyLog node's own consumer
reaches it on `host.docker.internal:9094`, which is why the consumer registration
names port 9094.

```
run kafka consumer where ip = host.docker.internal and port = 9094
  and reset = earliest
  and topic = (name = egauge-energy and dbms = customers and table = egauge_kafka
    and column.ts.timestamp = "bring [ts]" and column.dev.str = "bring [dev]"
    and column.nm.str = "bring [nm]" and column.tp.str = "bring [tp]"
    and column.w.float = "bring [w]" and column.kwh.float = "bring [kwh]")
```

`get msg client` currently reports subscription 0001 on
`host.docker.internal:9094`, 7,267,849 messages, 7,267,849 success, **0 errors**,
last message timestamped to the second.

`anylog-consumer` prints `Stats: N OK, M FAIL` every 30 s. Identical N across two
lines means it is subscribed but consuming nothing, and the fix is a restart. Its
PUT timeout is 10 s with no back-pressure, so it gives up and pauses whenever the
operator is slow. That is how a Postgres stall turns into lost minutes rather
than a queue, and it is still open.

## Solar Assistant

LAN device at `192.168.254.48:1883`, topic prefix `solar_assistant`.
`solar-producer` republishes JSON into AnyLog's own MQTT broker on 1883 under
topic `solar`, where a `run msg client` maps it to `solar_data`.

On Pat's box the configured broker path is idle. Solar is actually ingested
through the REST streaming path, `INGEST_MODE=rest`, and the subscriber is
configured and idle. Both paths are kept because the mapping is byte identical
either way. `get processes` confirms MQTT and MSG Broker both Running, with the
broker listening on `47.146.83.255:1883`.

## AnyLog

Two nodes, both `anylogco/anylog-network:2.1.2608`.

| node | ports | role |
|---|---|---|
| `master` | 32048 TCP, 32049 REST | metadata, ledger, 162 policies |
| `operator1` | 32148 TCP, 32149 REST, 1883 MQTT | operator, streamer, Kafka consumer, MQTT broker, MCP server, blobs archiver |

```
master@47.146.83.255:32048     running
operator1@47.146.83.255:32148  running
```

The operator policy carries `ip: 127.0.0.1` and
`local_ip: host.docker.internal`. Connections report External
`47.146.83.255:32148`, Internal `host.docker.internal:32148`, Bind
`0.0.0.0:32148`.

Thread pools are TCP 6, REST 6, Query Pool 3, Operator 1. REST timeout is 20 s,
SSL false.

### The node-policy trap

`node_policy.al` aborts with "Failed to configure node based on !node_type ID",
and **under 2.1.2608 that abort exits the whole script array**, so
`local_script.al` at the end never runs. No operator, no streamer, no Kafka
consumer. Under 2.0.2606 it was survivable, which is why this only fired on the
upgrade even though `local_script.al`'s own comment records the policy path
failing since July.

The cause is the lookup. The patched `validate_node_policy.al` searched by
`ip = !external_ip` and, in its fallback, by `ip = !overlay_ip`. Neither matches
a policy whose `ip` is `127.0.0.1`. Upstream 2.1.2608 has a proper overlay check
that matches on `local_ip`, so the mounted patch was brought in line. The
corrected clause is at line 49 of the deployed file.

```diff
 :overlay-fallback:
 <is_policy = blockchain get !node_type where
     company=!company_name and
     name=!node_name and
-    ip = !overlay_ip and
+    local_ip = !overlay_ip and
     port = !anylog_server_port bring.first>
```

Verified by a second full recreate of `operator1`. Everything comes up on its own
now with no manual `process local_script.al`.

The file is bind mounted from
`streaming/anylog/docker-compose/docker-makefiles/operator1-configs/patches/validate_node_policy.al`
to `/app/deployment-scripts/node-deployment/policies/validate_node_policy.al`,
read only. `local_script.al` is mounted the same way into `node-deployment/`.

### Licensing

`LICENSE_KEY` must be in both nodes' environment. 2.1.2608 requires it, and
without it `set_params.al` prints "Missing license key, cannot continue..." and
terminates. The `license_policy.al` bind mount that patched
`set license where activation_key = !activation_key` into `!license_key` must be
**removed**, because 2.1.2608 ships that intent as
`set license where activation_key = $LICENSE_KEY` and no longer assigns
`!license_key`. Keeping the mount feeds the licence step an undefined variable.

Current licence is company Guest, type beta, expiring 2026-11-01, `max_nodes` 10.

## Postgres and partitions

`postgres:14.0-alpine` as container `postgres1`, compose service `postgres`.
AnyLog connects `almgm` and `customers` as psql on `host.docker.internal:5432`,
and holds `monitoring` and `system_query` as sqlite.

Two login roles exist, `admin` and `demo`. The superuser the container is
initialised with is `admin`, from `POSTGRES_USER` defaulting to `admin` and
`POSTGRES_PASSWORD` defaulting to `passwd`. `demo` is created by
`streaming/postgres/init/01-ensure-demo-user.sql` and is the role AnyLog's own
inserts arrive as. Use `admin` for the inspection queries below, and pass the
password through the environment or psql will prompt and hang.

```bash
sudo docker exec -e PGPASSWORD=passwd postgres1 \
  psql -U admin -d customers -tAc "<query>"
```

Five logical tables plus monthly `par_*` partitions.

```
anomalies  egauge_kafka  energy_readings  nilm_disaggregated  solar_data
```

Partitions currently present.

```
par_anomalies_2026_{08,09}_m01_insert_timestamp
par_egauge_kafka_2026_07_01_d14_insert_timestamp        <- old fourteen-day
par_egauge_kafka_2026_{08,09}_m01_insert_timestamp
par_energy_readings_2026_08_00_d14_insert_timestamp     <- old fourteen-day
par_energy_readings_2026_{08,09}_m01_insert_timestamp
par_nilm_disaggregated_2026_08_00_d14_insert_timestamp  <- old fourteen-day
par_nilm_disaggregated_2026_{08,09}_m01_insert_timestamp
par_solar_data_2026_{08,09}_m01_insert_timestamp
```

The three `d14` partitions are left over from before the change and are still
resolvable, which is what lets a stale partition cache return a plausible but
wrong answer instead of an error.

`energy_readings` columns.

```
row_id, insert_timestamp, tsd_name, tsd_id, ts, dev, nm, tp, w, kwh
```

`ts` is meter time and `insert_timestamp` is arrival time. **Use
`insert_timestamp` for liveness.** `tp` is the measurement type, `P` power, `V`
voltage, `I` current, `F` frequency, and filtering on it is mandatory or units
are mixed in one aggregate. `nm` is the register name.

The parent table is empty. Rows live in the partitions, which is why a plain
`SELECT … FROM energy_readings` can return `Empty data set` while the data is
right there.

### Partitioning must be monthly

```
customers.*  : (1, 'month', 'insert_timestamp')
monitoring.* : (12, 'hours', 'insert_timestamp')
```

Set it with a POST. A GET is refused.

```bash
curl -X POST http://127.0.0.1:32149 -H "User-Agent: AnyLog/1.23" \
  -H "command: partition customers * using insert_timestamp by month"
```

Two independent places define this and they must agree.
`operator1-configs/base_configs.env` line 159 sets `PARTITION_INTERVAL=1 month`,
with `PARTITION_COLUMN=insert_timestamp`, `PARTITION_KEEP=3` and
`PARTITION_SYNC=1 day`, and `local_script.al` also sets monthly partitioning. On
a container recreate on 2026-09-01 the env file still said `14 days`, so the
operator applied that, queries resolved against the old `d14` partitions and
returned 291,865 rows with a newest timestamp of 3 August while writes continued
into the monthly `m01` tables. After the fix the same query returned 25.9 M rows
and a current timestamp.

### The month-boundary partition bug

At 00:00 on the first of the month AnyLog creates the new partitions. On
2026-09-01 it created `par_solar_data_2026_09_m01_insert_timestamp` with **11
columns instead of 39**, and every insert was rejected.

```
PostgreSQL Error - Failed to ingest CSV buffer:
  'customers.par_solar_data_2026_09_m01_insert_timestamp' failed -
  'column "pv_power_1" of relation "..." does not exist'
INSERT has more expressions than target columns
```

`solar-producer` looked healthy the whole time, reporting `255457 OK` and
climbing, because its publish to AnyLog's broker succeeded. The rejection
happened one hop later inside the operator. Only `solar_data`, the widest table,
was truncated. `energy_readings`, `egauge_kafka` and `nilm_disaggregated` got
their correct 10, 10 and 15 columns.

The broken partition held zero rows, so it was safe to rebuild from August.

```sql
DROP TABLE par_solar_data_2026_09_m01_insert_timestamp;
CREATE TABLE par_solar_data_2026_09_m01_insert_timestamp
  (LIKE par_solar_data_2026_08_m01_insert_timestamp INCLUDING ALL);
```

**Check this on the first of every month, before rows accumulate.** Check every
table, not just `solar_data`, since the failure mode is width dependent and a
future schema change could move it.

```bash
sudo docker exec -e PGPASSWORD=passwd postgres1 psql -U admin -d customers -tAc \
  "select table_name, count(*) as cols from information_schema.columns
   where table_schema='public' and table_name like 'par_%'
   group by table_name order by table_name"
```

Expected widths, verified 2026-09-08.

| table | columns |
|---|---|
| `par_energy_readings_*` | 10 |
| `par_egauge_kafka_*` | 10 |
| `par_nilm_disaggregated_*` | 15 |
| `par_anomalies_*` | 18 |
| `par_solar_data_*` | **39** |

Both September partitions currently read 39, so the 2026-09-01 rebuild held.

### The other month-boundary hazard

`_get_partitions` in `services/iems/load/anylog_query.py` caches per process with
no TTL, so every month boundary re-arms a stale partition stall for any container
up since before the rollover. See `05_inference_runtime.md`.

## Ingestion triage

Containers reporting `Up` proves nothing. On 2026-08-29 the eGauge path was dead
for 68 hours with every container green.

```bash
# 1. when did each table last RECEIVE a row
for t in energy_readings egauge_kafka solar_data nilm_disaggregated; do
  printf '%-20s ' "$t"
  curl -s http://100.119.235.24:32149 \
    -H "User-Agent: AnyLog/1.23" -H "destination: network" \
    -H "command: sql customers format=json and stat=false
        \"select max(insert_timestamp) as newest from $t\""
  echo
done

# 2. read the producer's last LOG LINE, not its status
sudo docker logs --tail 5 egauge-producer
sudo docker logs --tail 5 anylog-consumer

# 3. check the bridge counter is moving
sudo docker logs --tail 2 anylog-consumer   # identical N twice = consuming nothing
```

Restart order is producer, then bridge, then re-run step 1.

`get streaming` on the operator gives the same answer from the node's own point
of view, and is the fastest single check. Current reading.

```
customers.energy_readings    | 7,268,127 rows | last process 00:00:00
customers.egauge_kafka       | 7,267,851 rows | last process 00:00:00
customers.solar_data         |   104,981 rows | last process 00:00:01
customers.nilm_disaggregated |   390,602 rows | last process 00:00:22
customers.anomalies          |         1 row  | last process 80:14:03
monitoring.node_insight      |    14,678 rows | last process 00:00:24
monitoring.docker_insight    |     5,914 rows | last process 145:41:54
```

Those counts are since the node last started, not lifetime. `anomalies` at
80 hours is the round trip write test from 2026-09-04 and is expected.

## Known noise

`monitoring.docker_insight` has not processed in 145 hours. It streams into a
`blobs_monitoring` DBMS that is not connected, filling the error directory. Either
connect that database or stop the monitoring collection. Open.

A disposable `ZZ Probe` object policy, id
`0000000000000000000000000000abcd`, will not drop. Both
`blockchain drop policy where id = …` and `blockchain drop policy !policy` are
no-ops on this build. It has no `uns` node so it never appears in the tree, only
as an extra row of `blockchain get object`.
