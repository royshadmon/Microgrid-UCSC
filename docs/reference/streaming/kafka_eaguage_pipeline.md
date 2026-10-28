# Kafka to eGauge Streaming

`streaming/kafka-egauge-pipeline/` — the bridge between the physical eGauge meter at the Los Gatos site and AnyLog's `egauge_kafka` table. Two Python services and a single-broker Kafka, all in one Compose file:

```
streaming/kafka-egauge-pipeline/
├── docker-compose.kafka.yml      # kafka + egauge-producer + anylog-consumer + kafka-ui
├── Dockerfile.producer           # builds the producer image
├── Dockerfile.consumer           # builds the consumer image
├── egauge_kafka_producer.py      # eGauge poll loop → Kafka topic
├── kafka_to_anylog.py            # Kafka topic → AnyLog streaming PUT
└── .env.example                  # eGauge URI/user/password placeholders
```

## Main contents

### `docker-compose.kafka.yml`

Single-broker Apache Kafka 3.9.2 in KRaft mode (no Zookeeper). Two listeners — `PLAINTEXT://kafka:9092` for the in-Docker producer/consumer and `EXTERNAL://host.docker.internal:9094` for clients outside the compose network (the AnyLog operator runs in a sibling stack, which is why this matters). `KAFKA_AUTO_CREATE_TOPICS_ENABLE=true`, 3 partitions, 7-day retention.

Brings up four containers:

- `kafka` — the broker
- `egauge-producer` — `Dockerfile.producer`, runs the poll loop
- `anylog-consumer` — `Dockerfile.consumer`, runs the bridge (legacy: the production stack uses AnyLog's own native Kafka consumer registered by `streaming/anylog/.../local_script.al`)
- `kafka-ui` — provectus/kafka-ui at port `8080`

### `egauge_kafka_producer.py`

Polls the eGauge meter once per `POLL_INTERVAL` seconds using the official `egauge` package (`webapi.device.Device` + `JWTAuth`), packs each register reading as JSON, and produces it to topic `egauge-energy`. Idempotent producer with `acks=all` and retries=5.

Top of file:

```python
EGAUGE_URI    = os.environ.get("EGAUGE_URI", "")
EGAUGE_USER   = os.environ.get("EGAUGE_USER", "owner")
EGAUGE_PASS   = os.environ.get("EGAUGE_PASS", "")
KAFKA_BROKER  = os.environ.get("KAFKA_BROKER", "localhost:9092")
KAFKA_TOPIC   = os.environ.get("KAFKA_TOPIC", "egauge-energy")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "1"))

def create_producer():
    return Producer({
        "bootstrap.servers":  KAFKA_BROKER,
        "client.id":          "egauge-producer",
        "acks":               "all",
        "linger.ms":          5,
        "batch.num.messages": 16,
        "retries":            5,
        "enable.idempotence": True,
    })

def connect_egauge():
    dev = webapi.device.Device(EGAUGE_URI,
              webapi.JWTAuth(EGAUGE_USER, EGAUGE_PASS))
    return dev
```

Credentials at this site are `EGAUGE_USER=hranjan`, `EGAUGE_PASS=2026MGMrho`, and `EGAUGE_URI` currently points at `egaug.es` (the cloud relay); the planned switch to a direct LAN IP is one env-var change.

### `kafka_to_anylog.py`

Consumer that pulls from `egauge-energy` and streams each batch to the AnyLog operator's REST endpoint as a streaming PUT:

```python
def put_to_anylog(payload):
    url = "http://%s:%s" % (ANYLOG_HOST, ANYLOG_PORT)
    headers = {
        "User-Agent":  "AnyLog/1.23",
        "type":        "json",
        "dbms":        ANYLOG_DBMS,        # customers
        "table":       ANYLOG_TABLE,       # egauge_readings (legacy)
        "mode":        "streaming",
        "Content-Type":"text/plain",
    }
    r = requests.put(url, headers=headers, data=payload, timeout=10)
```

Group id `anylog-bridge`, `auto.offset.reset=earliest`, manual commit, configurable `BATCH_SIZE` / `BATCH_TIMEOUT`. Effectively superseded by AnyLog's native Kafka consumer (registered in `streaming/anylog/docker-makefiles/operator1-configs/local_script.al`), but kept here as a reference implementation and a debugging tool when the native consumer mis-registers.

### `Dockerfile.producer` / `Dockerfile.consumer`

Slim Python images that install `confluent-kafka` plus the eGauge SDK (producer) or `requests` (consumer) and run the matching script as PID 1.

## Use in the project

This is how raw meter data physically gets into the system. The data path is:

```
eGauge meter (egauge18646)
        │  HTTP register poll, JWT auth, 1 Hz
        ▼
egauge_kafka_producer.py  ──►  Kafka topic: egauge-energy
                                       │
                                       ▼
                  AnyLog Kafka consumer (in operator1, registered by local_script.al)
                                       │
                                       ▼
                  Postgres table: egauge_kafka (via par_egauge_kafka_YYYY_MM_00_d14_*)
                                       │
                                       ▼
                  services/iems/load/anylog_query.fetch_all_panels()
```

The folder hosts two consumers because the project migrated from the standalone `kafka_to_anylog.py` bridge to AnyLog's native consumer — the standalone version stays in the tree as a fallback and as the canonical example of how an AnyLog streaming PUT should be shaped.
