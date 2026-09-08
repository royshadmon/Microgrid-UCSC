# Architecture

Verified against Pat's box on 2026-09-08. Where a fact is repository-only it says
so.

## The data path

```
eGauge18646  192.168.254.19
  │  HTTPS, dev.get("/register?rate"), once a second, 16 registers
  ▼
egauge-producer ──► Kafka topic egauge-energy (3 partitions, 168 h retention)
                      │                    │
                      │                    └─► operator1's own Kafka consumer
                      │                          on host.docker.internal:9094
                      │                          ──► customers.egauge_kafka
                      ▼
                    anylog-consumer
                      REST streaming PUT on :32149
                      ──► customers.energy_readings

Solar Assistant  192.168.254.48:1883
  └─► solar-producer ──► customers.solar_data          (12 rows/min)

iems-inference (30 s tick, 3 panels)
  └─► REST streaming PUT ──► customers.nilm_disaggregated   (44 rows/min)

iems-dashboard relay actions
  └─► REST streaming PUT ──► customers.anomalies       (only when the relay acts)
```

Two writers cover the eGauge path and two do not. `solar_data` and
`nilm_disaggregated` run on a different path, so a split verdict localises a
fault immediately. Both staying current while the first two freeze is the
signature of the producer, not of anything downstream.

Sampled twice on 2026-09-08, six hours apart: `energy_readings` 846 then 948,
`egauge_kafka` 848 then 950, `solar_data` 12 then 11, `nilm_disaggregated` 44
both times, `anomalies` 0 both times. Treat the eGauge pair as a 850 to 960 band
rather than a constant, since a 60 second SQL window does not align with the
one second poll.

## Surfaces and which port serves what

Port 3001 is the React frontend and returns `index.html` with HTTP 200 for any
unknown path, which masquerades as a working route. Never test an API against it.

| surface | port | routes | serves |
|---|---|---|---|
| standalone dashboard | 47821 | 19 `/api/*` plus `/` and `/index.html` | one 102 KB page, six tabs |
| IEMS engine, `iems-backend` | 8009 | 25 paths | the four-domain cycle, ONNX snapshot, Ask |
| AnyLog EDM backend | 8000 | 122 paths | 26 `/iems`, 20 `/uns`, 13 `/auth`, 12 `/policycreator`, 11 `/reportgenerator`, 9 `/mcpclient` |
| AnyLog EDM frontend | 3001 | — | React shell, plugin pages |

The Ask tab inside the plugin does not call `/iems/ask` on 8000. It reaches the
model through `/iems/dash/api/ask`, which is dashboard side, and the dashboard
forwards to `/iems/ask` on 8009.

## The engine is the single point of truth

`iems-backend` on 8009 holds the rules, the appliance catalogue and the Ask
context, and the dashboard and the plugin are both readers of it. It also holds
its own ONNX sessions, but those are a stale legacy copy and are **not** the
models producing data. The models that write `nilm_disaggregated` live in the
`iems-inference` image. See `04_training_pipeline.md`.
The plugin is a proxy with no `onnxruntime`, no model files and no copy of
`services/iems` in its image.

`runner.run_iems_cycle()` is the one function every UI calls. It runs the load,
generation, storage and decision support domains in a single pass and takes 9 to
12 s on this hardware.

## Site constants

These describe this house and do not survive a move to another site.

```
location          37.2358 N, 121.9624 W, America/Los_Angeles
meter             eGauge18646 at 192.168.254.19, 16 registers
panels            Panel1 (HVAC), Panel2 (H2O), Panel3 (Kitchen), Shop
feeds             Grid Power, Generac Power, Current on Utility Tie
instrumentation   I11 I12 I21 I22 I31 I32, VrmsA, VrmsB, F1
battery           13.5 kWh, 10 percent floor, SOC modelled not metered
tariff            PG&E E6 time of use
thermostat        climate.sensi_2a293d_thermostat via Home Assistant
NILM heads        22 across three panels
```

Raw panel power is negative by convention, so every rule and labeller runs on
`abs(w)`.

## Node identity

```
master@47.146.83.255:32048     running, 2.1.2608
operator1@47.146.83.255:32148  running, 2.1.2608
```

The operator policy carries `ip: 127.0.0.1` and `local_ip: host.docker.internal`,
which is why the node policy lookup has to match on `local_ip`.

`get processes` on operator1 reports Running for TCP, REST, Operator, Blockchain
Sync, Scheduler, Blobs Archiver, MQTT, MSG Broker, Streamer, Query Pool and Kafka
Consumer. TCP and REST each hold a six thread pool, Query Pool holds three, and
the Operator holds one.

The MCP row in that table reads `Not declared`, which is misleading. The MCP
server is answering. `get mcp status` returns a live session table and
`GET /mcp/sse` holds a 200 stream open. The `Not declared` row refers to a
separate declaration the deployment does not use.

## Databases

```
almgm        psql   system   host.docker.internal:5432
customers    psql   user     host.docker.internal:5432
monitoring   sqlite user     /app/AnyLog-Network/data/dbms/monitoring.dbms
system_query sqlite system   MEMORY
```

`customers` holds five logical tables plus monthly `par_*` partitions. The parent
tables are empty, which is why a plain `SELECT` can return `Empty data set` while
the data is right there.

Partitioning is `customers.* : (1, 'month', 'insert_timestamp')` and
`monitoring.* : (12, 'hours', 'insert_timestamp')`. Old fourteen day partitions
from before the change are still present and still resolvable, which is exactly
how the 2026-09-01 stale answer happened.

## MCP and the local LLM

Both run entirely on Pat's box. Nothing leaves the machine.

AnyLog 2.x hosts its own MCP server on the operator's REST port,
`http://100.119.235.24:32149/mcp/sse`. Nothing had to be built for it.

The GUI's MCP client plugin reads four environment variables on `iems-app`. All
four were unset originally, so it defaulted to a demo MCP server on the public
internet and to `localhost:11434`, which inside the container is the container.

```yaml
ANYLOG_MCP_SSE_URL: "http://host.docker.internal:32149/mcp/sse"
LLM_ENDPOINT:       "http://host.docker.internal:11434"
LLM_API_TYPE:       "ollama"
OLLAMA_MODEL:       "qwen2.5:1.5b-instruct"
```

`POST /mcpclient/connect` returns 18 tools.

```
checkStatus  getNodesList  dataLocation  listNetworkDatabases  listTables
listColumns  monitorNodes  listPolicyTypes  listPolicies  getRootPolicies
getPolicyChildren  listCommandsIndex  listCommandsByIndex  helpCommand
executeQuery  queryWithIncrement  getClusterNodeMapping  listNetworkConnections
```

The agent is held in process, so restarting `iems-app` drops it and the status
endpoint reports `connected: false` until the page calls `/connect` again. That
is its current state, three days after the last restart.

The model is `qwen2.5:1.5b-instruct`, 986 MB, Q4_K_M. It replaced
`qwen2.5:3b-instruct`, which was deleted. `keep_alive: -1` is sent on every Ask
and must be an integer, because Ollama rejects the bare string `"-1"` with
`missing unit in duration`. That pin lasts only until something unloads the
weights, and `/api/ps` currently reports nothing resident, so the next Ask pays
the disk load once.

The direct `/iems/ask` path is the fast and accurate one, 8.2 s cold and 2.7 s
warm for a single feed question. The agentic `/mcpclient/ask` path takes six to
nine minutes and the 1.5 B is a poor agent driver, choosing `executeQuery` where
`listTables` was asked for and omitting the `dbms` argument when told explicitly.
The cost is prompt evaluation of the 18 tool schemas rather than generation, so a
smaller model does not help that path. The fixes, in order of effect, are
pointing `LLM_ENDPOINT` at a machine with a GPU, or trimming the tool set exposed
to the client.

## UNS knowledge graph

64 objects and 64 namespace nodes live on operator1, generated by
`~microgrid/build_uns_graph.py` from the live engine inventory. Depth histogram is
1 / 7 / 24 / 32 with zero orphans, and ids are `md5("iems-object::" + namespace)`
so re-running publishes nothing new.

```
losgatos                        Los Gatos Microgrid
├── electrical/                 6 power feeds + 10 instrumentation channels -> energy_readings
├── solar/                      6 fields -> solar_data
├── appliances/panel{1,2,3}_*/  22 NILM heads -> nilm_disaggregated
├── models/{panel1,panel2,panel3}
├── anomalies                   -> customers.anomalies
├── sources/{egauge18646,solar_assistant,home_assistant}
└── infrastructure/{master,operator1}
```

The Root Query field on both UNS pages ships with
`blockchain get root policies exclude cluster`, which returns `[]` and always
will, because it is a curated cluster family command that never reads `uns`
policies. Type this instead, once per browser, and both pages persist it.

```
blockchain get uns where [parent] not declared
```

Two further points that cost time. The GUI backend runs inside the `iems-app`
container, so a bookmarked node of `localhost:32149` queries the container, not
the host. The working value is `host.docker.internal:32149`, set through
`/auth/bookmark-node/` and `/auth/set-default-bookmark/`, which is server side
state in `usr-mgm` and applies to every browser with no rebuild. And the plugin's
`save_draft_path_assignments` reuses an id extracted from the blockchain insert
acknowledgement, which on this build carries `true`, so a mixed depth batch gives
every child `parent: "true"` and every child is rejected. The builder works around
it by publishing one request per depth level, shallowest first.

## Ledger state

The master's ledger was repaired on 2026-08-31. It had no `blockchain` DBMS,
`Blockchain Sync: Not declared`, and an 11 KB file ledger holding 16 lines against
operator1's 162. operator1's ledger was a strict superset with zero master only
lines, so copying it onto the master was purely additive and made the ten second
sync a no-op instead of a hazard.

```
docker cp <backup>/op1_blockchain.json master:/app/AnyLog-Network/blockchain/blockchain.json
docker restart master
```

Attaching an empty sqlite `blockchain` DBMS on the master is still **not** done
and must not be done casually. Master config is `BLOCKCHAIN_SOURCE=master`,
`BLOCKCHAIN_DESTINATION=file`, so the DBMS ledger is the source of truth and the
file is derived. An empty DBMS would make the master authoritative but empty,
rewrite its file copy empty, and operator1's next sync would wipe all UNS
policies and its own operator policy, stopping ingestion. AnyLog's REST layer also
refuses state changing commands with `err_code 156, Wrong HTTP method used`, so
there is no command channel short of the container CLI.

## Licensing

`LICENSE_KEY` must be present in both nodes' environment. 2.1.2608 requires it,
and without it `set_params.al` prints `Missing license key, cannot continue...`
and terminates. The current licence is company Guest, type beta, expiring
2026-11-01, `max_nodes` 10.

The `license_policy.al` bind mount on `master` was removed at the 2.1.2608
upgrade. It was a one line patch, `set license where activation_key = !license_key`,
and 2.1.2608 ships that intent upstream as
`set license where activation_key = $LICENSE_KEY` while no longer assigning
`!license_key` in `set_params.al`. Keeping the mount would feed the licence step
an undefined variable.
