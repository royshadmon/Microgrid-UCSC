# AnyLog Setup

`streaming/anylog/` — the docker-compose configuration that brings up the two-node AnyLog network the IEMS reads from. One master, one operator, plus a Postgres dependency that lives in `streaming/postgres/`.

```
streaming/anylog/
└── docker-makefiles/
    ├── .env                                 # INIT_TYPE=prod, IMAGE, CLI port
    ├── docker-compose-template-base.yaml    # generic AnyLog node template
    ├── docker-compose-template-ports-base.yaml
    ├── docker-compose-files/
    │   ├── master-docker-compose.yaml       # master (32048 / 32049)
    │   └── operator1-docker-compose.yaml    # operator1 (32148 / 32149 / 1883)
    ├── master-configs/
    │   ├── base_configs.env                 # ports, DB, blockchain wiring
    │   └── advance_configs.env
    └── operator1-configs/
        ├── base_configs.env                 # license, ports, DB, partition rules
        ├── advance_configs.env
        └── local_script.al                  # Kafka-consumer bootstrap (mounted RO)
```

## Main contents

**`.env`** — `INIT_TYPE=prod` (vs `bash` for shell-only debugging), the AnyLog image tag, and the Remote-CLI's `CLI_PORT=31800`.

**`docker-compose-template-base.yaml`** — generic AnyLog service template parameterized by `${NODE_NAME}`, `${ANYLOG_TYPE}` (`master` or `operator1`), and the three port env vars. Adds `extra_hosts: ["host.docker.internal:host-gateway"]` so Linux hosts resolve the host correctly (Mac M-series origin; the `host-gateway` line is required on Linux).

**`docker-compose-files/master-docker-compose.yaml`** — master node, fixed at TCP `32048` / REST `32049`, NODE_TYPE=master.

**`docker-compose-files/operator1-docker-compose.yaml`** — operator node, TCP `32148` / REST `32149` / MQTT `1883`. Two read-only bind mounts override the upstream image's start-up scripts without rebuilding:

```yaml
volumes:
  - ../../docker-makefiles/operator1-configs/local_script.al:/app/deployment-scripts/node-deployment/local_script.al:ro
  - ../../docker-makefiles/operator1-configs/patches/validate_node_policy.al:/app/deployment-scripts/node-deployment/policies/validate_node_policy.al:ro
```

**`master-configs/`** and **`operator1-configs/`** — `base_configs.env` carries license key, node name, ports, blockchain bootstrap, partition rules, and the Postgres credentials (`DB_USER=demo`, `DB_PASSWD=passwd`, `DB_IP=host.docker.internal`). `advance_configs.env` holds the optional knobs.

**`local_script.al`** — operator-only post-policy hook. Registers the Kafka consumer that pulls from `egauge-energy` and lands rows in `egauge_kafka`:

```anylog
run kafka consumer where ip = host.docker.internal and port = 9094 and reset = latest
and topic = (name = egauge-energy and dbms = customers and table = egauge_kafka
  and column.ts.timestamp = "bring [ts]"
  and column.dev.str       = "bring [dev]"
  and column.nm.str        = "bring [nm]"
  and column.tp.str        = "bring [tp]"
  and column.w.float       = "bring [w]"
  and column.kwh.float     = "bring [kwh]")
```

## Use in the project

This is the streaming substrate the entire IEMS sits on. The Kafka consumer registered by `local_script.al` is what makes `egauge_kafka` populate in the first place. Every `services/iems/load/anylog_query.py` call hits operator1's REST port (`32149`) — the IEMS app never talks to the master directly. The master is the blockchain coordinator that the operator registers its node policy against (`bcc22d1407475e2d3013e2aaf66ce2bb`).

Bring-up order matters: master first, then operator1, then the Kafka stack in `streaming/kafka-egauge-pipeline/` — that's exactly what `scripts/start.sh` enforces. Streaming-layer gotchas (the `run client ()` REST trap, `destination: network` semantics, partition naming, the 2-second flush threshold) are catalogued in [`../anylog_query_cookbook.md`](../anylog_query_cookbook.md).
