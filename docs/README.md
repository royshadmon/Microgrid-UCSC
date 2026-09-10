# IEMS documentation

Los Gatos residential microgrid. An eGauge meter and a Solar Assistant inverter
stream into AnyLog, local ONNX models disaggregate the panel power into
appliance states, a rules layer reconciles those states against measured watts,
and three web surfaces plus a local LLM read the result.

Two file sets make up the system and they are not the same.

**Pat's box** is the running deployment and the authority on what the system
does. Everything in these documents was written from it and verified against it
on 2026-09-08, twice, six hours apart. Route counts, versions, thresholds, file
line counts and partition widths all matched on both passes.

Where a figure varies by nature, such as an ingestion rate, the documents give a
band rather than a single sample and say which. Where a figure should be exact,
such as a route count or a threshold, it is exact and a mismatch means something
has changed.

**The repository** is the source tree those files were built from and the place
fixes should land. It is ahead of Pat's box on the training pipeline and behind
it on several runtime files. The drift table below is the full list.

| document | covers |
|---|---|
| `00_architecture.md` | what runs where, the data path, ports, site constants, MCP, UNS, ledger |
| `01_file_inventory.md` | Part A the files on Pat's box, Part B the repository by role, Part C the drift |
| `02_physical_labellers.md` | how supervision is manufactured. Repository only |
| `03_rules_engines.md` | the four rules engines, with the constants that are live on Pat's box |
| `04_training_pipeline.md` | archive to labels to windows to BiLSTM to ONNX. Repository only |
| `05_inference_runtime.md` | the 30 s loop, feature construction, gates, the write path |
| `06_apis_and_routes.md` | every route on 8009, 47821 and 8000, verified against the live OpenAPI |
| `07_streaming_storage.md` | Kafka, MQTT, AnyLog, Postgres, partitions, ingestion triage |
| `08_scripts_and_shells.md` | every deploy and operations script, and which machine it runs on |

### Older documents in this folder

These predate the numbered set and were not rewritten. They are still accurate
about their own subjects, but where one of them disagrees with a numbered
document about the live deployment, the numbered document is the one that was
verified against Pat's box.

| document | covers |
|---|---|
| `anylog_query_cookbook.md` | verified REST shapes for querying AnyLog, worth reading alongside `07` |
| `scripts.md` | the `scripts/` folder as it stood at eleven containers. `08` supersedes it on anything deployment related |
| `tests.md` | the pytest suite and the separate solar unittest suite |
| `memory.md` | the `memory/` note store and its conventions |
| `services/`, `streaming/` | per-module notes on the IEMS packages, the remote GUI, Kafka, Postgres and AnyLog |

---

# Part 1. Pat's box

## Reaching it

Tailscale `100.119.235.24`, SSH user `microgrid`. The box is
`pat-All-Series`, Ubuntu, four cores, 7.6 GB RAM, no GPU, 910 GB disk.

```bash
ssh microgrid@100.119.235.24
```

Docker needs `sudo` and `sudo -n` fails, so every docker command on this host is
interactive. The deployment root `/home/pat/microgrid_manager/Microgrid-UCSC-dev_fin`
is owned by `pat` and unreadable as `microgrid`.

Home Assistant sits at `http://araspberrypi.home:8123` on the house LAN, the
same subnet as the meter at `192.168.254.19`. Neither is on Tailscale, so both
are reachable only from Pat's box itself.

Use the hostname, not the IP. HA is on DHCP and moved from `192.168.254.69` to
`192.168.254.177` at some point before 2026-09-10, which broke every thermostat
control with `EHOSTUNREACH` while the token and the mount were both fine. The
router serves a `.home` domain and `araspberrypi.home` resolves from inside the
containers, so the hostname survives the next lease change. A static DHCP
reservation on the router would make it firmer still.

## What is running

Fourteen containers. Twelve come from one compose file, `iems-backend` is
started by hand, and `iems-grafana` has its own compose file.

| container | image | role |
|---|---|---|
| `master` | `anylogco/anylog-network:2.1.2608` | AnyLog metadata and ledger |
| `operator1` | `anylogco/anylog-network:2.1.2608` | AnyLog operator, streamer, Kafka consumer, MQTT broker, MCP server |
| `postgres1` | `postgres:14.0-alpine` | the `customers` database |
| `kafka` | `apache/kafka:3.9.2` | KRaft single node, topic `egauge-energy` |
| `kafka-ui` | `provectuslabs/kafka-ui:latest` | broker inspection |
| `egauge-producer` | built locally | polls the meter once a second |
| `anylog-consumer` | built locally | Kafka to AnyLog streaming PUT |
| `solar-producer` | built locally | Solar Assistant MQTT into AnyLog |
| `iems-inference` | built locally | the 30 s ONNX disaggregation loop |
| `iems-dashboard` | built locally | the standalone dashboard on 47821 |
| `iems-app` | `iems-remote-gui:2.1.2` | AnyLog EDM with the IEMS plugin |
| `ollama` | `ollama/ollama:latest` | the local model |
| `iems-backend` | `iems-backend:local` | **the engine.** Outside compose |
| `iems-grafana` | `grafana/grafana:11.3.0` | charts over the dashboard feeds |

`iems-backend` is the one container `docker compose up -d` will not recreate. It
carries `restart: unless-stopped` so it survives a reboot, but after any image
rebuild it has to be recreated by hand with its original spec.

## Verified URLs

Every one of these answered on 2026-09-08. Substitute `127.0.0.1` when working
on the box itself.

| surface | URL | notes |
|---|---|---|
| Dashboard | `http://100.119.235.24:47821/` | 6 tabs, 102 KB single page, 19 `/api/*` routes |
| AnyLog EDM frontend | `http://100.119.235.24:3001/` | React. Returns `index.html` 200 for **any** path |
| IEMS plugin page | `http://100.119.235.24:3001/dashboard/iems` | |
| MCP client page | `http://100.119.235.24:3001/dashboard/mcpclient` | |
| AnyLog EDM backend | `http://100.119.235.24:8000/` | 122 routes, 26 of them `/iems`, 20 `/uns`, 9 `/mcpclient` |
| Engine | `http://100.119.235.24:8009/` | 25 routes |
| Engine health | `http://100.119.235.24:8009/iems/health` | |
| Ask | `http://100.119.235.24:8009/iems/ask` | POST. The three `/iems/ask*` routes exist **only** here and as plugin forwards |
| Ask context | `http://100.119.235.24:8009/iems/ask/context?include=battery` | the exact bundle the model is given |
| AnyLog master REST | `http://100.119.235.24:32049` | header driven |
| AnyLog operator REST | `http://100.119.235.24:32149` | header driven |
| AnyLog MCP | `http://100.119.235.24:32149/mcp/sse` | 18 tools |
| Ollama | `http://100.119.235.24:11434` | |
| Grafana | `http://100.119.235.24:3000` | |
| Kafka UI | `http://100.119.235.24:8080` | |
| Postgres | `100.119.235.24:5432` | database `customers` |
| MQTT broker | `100.119.235.24:1883` | AnyLog's own broker |
| AnyLog TCP | `100.119.235.24:32048` master, `:32148` operator | |
| Kafka | `100.119.235.24:9092` internal, `:9094` external | the AnyLog consumer uses 9094 |

Port 3001 answers 200 with `index.html` for any path it does not recognise, so a
route test against it always passes. Test APIs against 8000 or 8009.

## Health check in four commands

```bash
# 1. both nodes alive
curl -s http://127.0.0.1:32049 -H "User-Agent: AnyLog/1.23" -H "command: get status"
curl -s http://127.0.0.1:32149 -H "User-Agent: AnyLog/1.23" -H "command: get status"

# 2. data actually arriving. insert_timestamp, never ts
for t in energy_readings egauge_kafka solar_data nilm_disaggregated; do
  printf '%-20s ' "$t"
  curl -s http://127.0.0.1:32149 \
    -H "User-Agent: AnyLog/1.23" -H "destination: network" \
    -H "command: sql customers format=json and stat=false
        \"select count(*) as c from $t where insert_timestamp >= NOW() - 60 seconds\""
  echo
done

# 3. the engine and the model
curl -s http://127.0.0.1:8009/iems/health
curl -s http://127.0.0.1:8009/iems/ask/health

# 4. the dashboard
curl -s -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:47821/api/sources
```

Expected rates are 850 to 960 rows a minute for `energy_readings` and
`egauge_kafka`, 11 to 12 for `solar_data`, and 44 for `nilm_disaggregated`.
`anomalies` is normally 0 because it only takes rows when the relay acts. The
`nilm_disaggregated` figure is exact, 22 heads on a 30 s tick, so a different
number there means a model or loop problem rather than sampling noise.

Containers reporting `Up` proves nothing. On 2026-08-29 the eGauge path was dead
for 68 hours with every container green.

## Deploying a change

Two rules, both learned the hard way and both written into `deploy_gui212.sh`.

```
1. Never run `docker compose down`. Twelve services share ONE compose file, so a
   bare `down` stops both AnyLog nodes and everything else. This took the whole
   stack down on 2026-08-17. Always `up -d --no-deps <service>`.
2. Verify the success condition, never the absence of a known failure string. A
   check that greps for a failure it has already seen passes on every failure it
   has not.
```

### Dashboard

The deployed file is `services/iems/web/server.js`, 2784 lines, owned by `pat`.
Edit it on the host and rebuild, or use the Mac-side `deploy2.sh`, which
`docker cp`s into the running container. The `docker cp` route is fast and it is
also why a later rebuild silently reverts the change.

```bash
sudo docker compose -f <compose> up -d --no-deps --build iems-dashboard
```

Two hazards. The whole page lives inside a JS template literal, so a single
quote inside a nested JS string needs two backslashes, and a lost escape kills
the entire inline controller while still serving HTTP 200. And every `$('id')`
lookup must have a matching `id="..."` in the markup, because a missing element
throws inside `pollSnapshot` and renders as a red "Power feed offline" banner.
Check both before deploying.

### Plugin

Any change to the dashboard has to be regenerated into the plugin, which carries
its own scoped copy.

```bash
cd ~/remote-gui-overlay-212
python3 gen_dash_module.py http://localhost:47821/ frontend/iems/iems_dash.js
sudo docker build -t iems-remote-gui:2.1.2 .
sudo docker compose -f <compose> up -d --no-deps --force-recreate iems-app
```

The overlay build is also the cheapest syntax check on `server.js`, because
esbuild refuses to bundle a broken module.

### Engine

```bash
cd ~/iems-backend-build
sudo docker build -t iems-backend:local .
sudo docker rm -f iems-backend
sudo docker run -d --name iems-backend --restart unless-stopped \
  --network microgrid-ucsc-dev_fin_default \
  --add-host host.docker.internal:host-gateway -p 8009:8000 \
  -e TZ=America/Los_Angeles -e ANYLOG_USER_AGENT=AnyLog/1.23 \
  -e ANYLOG_REST_PORT=32149 -e ANYLOG_HOST=host.docker.internal \
  -e ANYLOG_REST_URL=http://host.docker.internal:32149 \
  -e OLLAMA_URL=http://host.docker.internal:11434 \
  -e IEMS_DASH_URL=http://host.docker.internal:47821 \
  -e IEMS_ASK_MODEL=qwen2.5:1.5b-instruct -e IEMS_ASK_KEEP_ALIVE=-1 \
  -e IEMS_ASK_NUM_CTX=2048 -e IEMS_ASK_MAX_TOKENS=96 \
  -e IEMS_ASK_THREADS=3 -e IEMS_ASK_LIVE_TTL=30 \
  -e IEMS_REPO=/app/services \
  -e PGHOST=host.docker.internal -e PGPORT=5432 \
  -e PGUSER=admin -e PGPASSWORD=passwd -e PGDATABASE=customers \
  -e HOUSE_LAT=37.2358 -e HOUSE_LON=-121.9624 -e HOUSE_TZ=America/Los_Angeles \
  iems-backend:local
```

Restart `iems-backend` after any dashboard deploy anyway. Its partition cache has
no TTL, and a stale entry is what stalled ingestion at the 2026-09-01 month
rollover.

### GUI version bump

```bash
sudo bash ~/deploy_gui212.sh                      # deploy
sudo bash ~/deploy_gui212.sh --rollback 20260901_155124   # last known good
```

Touches only `iems-app`. Discovers the compose file from the container's
`com.docker.compose.project.config_files` label rather than assuming it, backs it
up to `~/.gui_backups/gui212_<stamp>/`, rewrites four lines, and verifies that
every pre-existing route still registers.

### Models

A model deploy is three steps, not one. Copying files onto the deployment root
changes nothing on its own, because no container bind mounts that directory.

```bash
cd /home/pat/microgrid_manager/Microgrid-UCSC-dev_fin

# 1. put the files where the build will see them
#    ~/rolling-deploy/deploy_rolling.sh writes to services/iems/models/

# 2. rebuild the image that loads them, and the backend that inherits from it
sudo docker compose build iems-inference
sudo docker compose up -d --no-deps iems-inference
cd ~/iems-backend-build && sudo docker build -t iems-backend:local .   # FROM the inference image
# then recreate iems-backend with its docker run block, see Engine above

# 3. confirm from inside the container, not from /iems/onnx/models
sudo docker exec iems-inference python3 -c "
import json, glob
for f in sorted(glob.glob('/app/services/iems/models/panel?_norm_bilstm.json')):
    d = json.load(open(f)); print(f, len(d['features']), 'features', d['heads'])
"
```

`iems-inference` caches one ONNX session per panel at process start, so step 2's
recreate is what actually loads the new models. Regenerate the UNS graph
afterwards, because the appliance layer is one node per head.

```bash
python3 ~/build_uns_graph.py
```

## Two traps specific to this host

**Partitioning must be monthly, in two places that must agree.** The operator
config sets `PARTITION_INTERVAL=1 month` at
`streaming/anylog/docker-compose/docker-makefiles/operator1-configs/base_configs.env`
line 159, and `local_script.al` sets it again. On a container recreate on
2026-09-01 the env file still said `14 days`, queries resolved against the old
`d14` partitions and returned an eleven day stale answer while writes went to the
monthly tables. Old `d14` partitions are still present and still resolvable.

**The operator will not start if the node policy lookup fails.** Under 2.1.2608 an
abort in `node_policy.al` exits the whole script array, so `local_script.al` never
runs and there is no operator, no streamer and no Kafka consumer. The mounted
`patches/validate_node_policy.al` must match the overlay fallback on
`local_ip = !overlay_ip`, not `ip`, because the operator policy carries
`ip: 127.0.0.1`.

---

# Part 2. A fresh host

This is what it takes to stand the stack up somewhere that is not Pat's box.

## Prerequisites

Docker with the compose plugin, roughly 8 GB RAM, four cores, and 50 GB of disk
for a few months of readings. A GPU is optional and the local LLM is the only
thing that wants one. Network reachability to an eGauge meter, and optionally a
Solar Assistant MQTT broker and a Home Assistant instance.

An AnyLog licence key is mandatory from 2.1.x onward. Without it `set_params.al`
prints `Missing license key, cannot continue...` and the node terminates.

## Configuration

Copy `.env.example` to `.env` and fill it. The keys the deployment actually uses
are `ANYLOG_LICENSE`, `EGAUGE_URI`, `EGAUGE_USER`, `EGAUGE_PASS`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `HOUSE_LAT`, `HOUSE_LON`,
`HOUSE_TZ`, `INFERENCE_TICK_SECONDS`, `SA_BROKER`, `SA_PORT`, `SA_USER`,
`SA_PASS` and `SA_PREFIX`.

Two site facts are compiled into the code rather than the environment. Channel
names in `services/iems/config.py` must match the meter's register names
exactly, and the appliance bands in
`services/iems/training/canonical_signatures.py` and
`services/iems/inference/rules_additive.py` describe this specific house.
Neither survives a move to a different site unchanged.

## Bring-up order

The order matters because each stage gates the next.

```
1. postgres            wait for healthy
2. master              wait for `get status` to report running
3. operator1           wait for Operator, Streamer and Kafka Consumer to be Running
4. kafka               wait for healthy
5. egauge-producer, anylog-consumer, solar-producer
6. ollama              pull a model before anything asks it a question
7. iems-backend        the engine, needed by both UIs
8. iems-dashboard, iems-app
9. iems-inference      last, because it reads what the others write
```

`scripts/start.sh` implements this as six phases with a health gate between each,
but it was written for the split compose layout where master and operator1 have
separate files. On a single compose file, bring services up individually with
`up -d --no-deps`.

Verify the operator before moving on. `get processes` must show Operator,
Streamer, Kafka Consumer, Blockchain Sync, MQTT and MSG Broker all Running. If
Operator is missing, the node policy lookup failed and nothing downstream will
work.

## After the stack is up

Register the Kafka consumer if `get msg client` does not already mention
`egauge-energy`. Set monthly partitioning with a POST, because a GET is refused.

```bash
curl -X POST http://127.0.0.1:32149 -H "User-Agent: AnyLog/1.23" \
  -H "command: partition customers * using insert_timestamp by month"
```

Then publish the UNS graph, which reads the inventory live from the engine so it
reflects what the meter and models actually expose.

```bash
python3 tools/uns/build_uns_graph.py --dry-run   # writes JSON, publishes nothing
python3 tools/uns/build_uns_graph.py
```

## Ports a fresh host needs

```
32048 32049   AnyLog master TCP and REST
32148 32149   AnyLog operator TCP and REST
1883          AnyLog MQTT broker
9092 9094     Kafka internal and external
5432          Postgres
8000 3001     AnyLog EDM backend and frontend
8009          IEMS engine
47821         standalone dashboard
11434         Ollama
3000          Grafana
8080          Kafka UI
```

`8000` and `31800` are pinned explicitly by `REMOTE_GUI_BE` and `REMOTE_GUI_FE`.
AnyLog EDM 2.1.x defaults its backend to 8080, which collides with Kafka UI, and
`:8000/iems/*` is wired into the dashboard and the ONNX smoke tests.

---

# Part 3. Where Pat's box and the repository differ

Verified 2026-09-08. Treat Pat's box as the authority on runtime behaviour and
the repository as the authority on how the models were made.

| item | Pat's box | repository |
|---|---|---|
| eGauge producer | request timeout `(5, 10)` injected into `requests.Session.request`, plus a 120 s watchdog calling `os._exit(1)` | neither. This bug has cost 107 hours of data across three incidents |
| dashboard `server.js` | 2784 lines, `/api/sources` counts in SQL, 60 s cache with in-flight de-duplication | earlier revision, `/api/sources` pulled 30 minutes of raw rows on every call |
| AnyLog nodes | `2.1.2608` on both | `ucsc-arm` |
| GUI image | `iems-remote-gui:2.1.2` | `iems-remote-gui:2.1.2-beta` |
| overlay router | 277 lines, 26 `/iems` routes including `/iems/ask*` | 23 routes, no `/iems/ask*` |
| local model | `qwen2.5:1.5b-instruct` on both `iems-backend` and `iems-app` | `qwen2.5:3b-instruct` |
| `iems-backend` | running on 8009, hand started, build context `~microgrid/iems-backend-build` | not in compose at all |
| **running models** | **18 feature**, 22 heads, baked into `iems-inference` and `iems-backend` since 2026-09-08 | 14 feature working copies, 18 feature kept as `.bak_18f_*` |
| training pipeline | the older generation only. No physical labellers, no rolling trainer, no `export_physical.py` | complete |
| training archive | absent | `analysis/egauge_consolidation/`, `analysis/solar/` |
| master ledger | repaired 2026-08-31, 162 policies matching operator1 | not applicable |
| UNS graph | 64 objects and 64 namespace nodes published on operator1 | builder only |

**Pat's box runs the serving path. The repository is where models are made.** The
models actually running were produced by a trainer that does not exist on Pat's
box and reached it as prebuilt files in `~microgrid/nilm_deploy/`, copied into
the `iems-inference` image on 2026-08-24. Verified by md5, they are byte
identical to the repository's, so on models the two machines agree.

### Model copies on the host

Before 2026-09-08 three different model generations sat on this host and only one
ran. That is resolved. The deploy on 2026-09-08 rebuilt `iems-inference` from the
deployment root and `iems-backend` from the inference image, so all three now
agree at 18 features.

| copy | features | status |
|---|---|---|
| baked into `iems-inference` | 18 | live, writes `nilm_disaggregated` |
| baked into `iems-backend` | 18 | matches, so `/iems/onnx/models` is accurate |
| `services/iems/models/` on the deployment root | 18 | the tree both images were built from |

**No container bind mounts the model directory.** `iems-inference`,
`iems-backend` and `iems-app` all report `Binds: null`. Copying model files onto
the deployment root changes nothing until the owning image is rebuilt, which is
exactly how the 18 feature set sat unused from 2026-08-10 to 2026-09-08.

`/iems/onnx/models` reads `iems-backend`'s own copy, so it is accurate only while
the two images are built in step. Rebuild them together, or verify against
`iems-inference` directly. `04_training_pipeline.md` has the checks that cannot
drift.

## Measured model performance

Fold 4 of the rolling walk-forward run that produced the deployed models. Full
per head tables, including the earlier folds, are in `04_training_pipeline.md`.

| panel | head | P | R | F1 |
|---|---|---|---|---|
| 1 | `heat_pump` | 0.856 | 1.000 | 0.923 |
| 1 | `solar_pump` | 0.066 | 0.801 | 0.121 |
| 2 | `water_heater` | 1.000 | 0.969 | 0.984 |
| 2 | `hair_dryer` | 0.558 | 1.000 | 0.716 |
| 2 | `sprinklers` | 0.326 | 0.331 | 0.328 |
| 2 | `bath_lights` | 0.227 | 0.699 | 0.343 |
| 3 | `microwave` | 0.931 | 0.977 | 0.954 |
| 3 | `computers` | 0.800 | 0.942 | 0.865 |
| 3 | `dishwasher` | 0.648 | 0.938 | 0.767 |
| 3 | `cooktop` | 0.600 | 1.000 | 0.750 |
| 3 | `washing_machine` | 0.464 | 0.865 | 0.604 |
| 3 | `tv_stereo` | 0.384 | 0.888 | 0.536 |
| 3 | `garage_opener` | 0.610 | 0.456 | 0.522 |
| 3 | `counter_appliance` | 0.347 | 1.000 | 0.516 |
| 3 | `garage_fridge` | 0.363 | 0.841 | 0.507 |
| 3 | `garage_freezer` | 0.312 | 0.852 | 0.457 |
| 3 | `refrigerator` | 0.230 | 0.864 | 0.363 |
| 3 | `pressure_pump` | 0.195 | 0.904 | 0.321 |

`jacuzzi_pump`, `strip_heater`, `dryer` and `oven` had fewer than 50 positives in
fold 4 and are reported as unmeasured rather than given a number. `oven` measured
F1 0.781 in fold 3 on 309 positives.

Recall runs ahead of precision on most heads. The runtime power gate removes
false positives after the model, so a head can carry low standalone precision and
still behave in production.

## Known open items

| item | where |
|---|---|
| `_get_partitions` caches per process with no TTL, re-arming a stall at every month boundary | `services/iems/load/anylog_query.py` |
| `anylog-consumer` PUT timeout is 10 s with no back-pressure, so an operator stall loses minutes rather than queueing | `streaming/kafka-egauge-pipeline/kafka_to_anylog.py` |
| `monitoring.docker_insight` streams to a `blobs_monitoring` DBMS that is not connected, filling the error directory. Last processed 145 hours ago | operator1 |
| the master has no `blockchain` DBMS. Attaching an empty one would make it authoritative-but-empty and wipe operator1's policies on the next sync | master |
| a `ZZ Probe` object policy will not drop. Both drop forms are no-ops on this build | operator1 |
| the producer timeout and watchdog fix is not back-ported to the repository | repository |
| `water_heater` and `dishwasher` are in `COLLAPSED` and forced to `UNKNOWN`, but both are measured against real negatives in the deployed run, F1 0.984 and 0.767 at fold 4. The set predates those numbers and has not been revisited | `services/iems/training/postprocess.py` |
| the repository's working norm files are still the 14 feature set while the host runs 18. The 18 feature files are present as `.bak_18f_*` | repository |
