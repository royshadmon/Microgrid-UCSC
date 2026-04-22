# Microgrid-UCSC

Energy monitoring and NILM system for a residential microgrid (Dr. Mantey's house, UCSC).
An eGauge 18646 meter polls 16 registers at 1-second intervals. Data streams through
Kafka into AnyLog/EdgeLake, stored in PostgreSQL, and visualized via Grafana.

## Pipeline

eGauge 18646 → Kafka (topic: egauge-energy) → AnyLog native Kafka consumer → PostgreSQL → Grafana

## Directory structure

    kafka-egauge-pipeline/
        egauge_kafka_producer.py      eGauge REST → Kafka producer
        docker-compose.kafka.yml      Kafka (KRaft) + producer stack
        grafana_dashboard.json        Grafana dashboard (6 panels)
        kafka_to_anylog.py            DEPRECATED — see local_script.al
    nilm/
        nilm_disaggregator.py         Zero-shot NILM via LLM4NILM approach

## AnyLog setup

Operator REST: http://127.0.0.1:32149
Kafka consumer is started natively via local_script.al on operator1 boot.
DEPLOY_LOCAL_SCRIPT=true and OVERLAY_IP=host.docker.internal must be set
in docker-makefiles/operator1-configs/base_configs.env.

## Database

DB: customers  Table: egauge_kafka
Columns: ts, dev, nm, tp, w, kwh

NILM results: customers.nilm_disaggregated
Columns: ts, circuit, appliance, state, estimated_w, confidence, explanation

## Register names

Grid Power, Generac Power, VrmsA, VrmsB, Panel1 (HVAC), Panel2 (water heater),
Panel3 (kitchen), Current on Utility Tie, I11, I12, I21, I22, I31, I32, Shop, F1

## Useful queries

    # All registers last hour
    run client () sql customers format=table "SELECT ts, nm, w FROM egauge_kafka WHERE ts > now() - 1 hour ORDER BY ts DESC LIMIT 50"

    # Per-register stats last day
    run client () sql customers format=table "SELECT nm, COUNT(*), AVG(w), MIN(w), MAX(w) FROM egauge_kafka WHERE ts > now() - 1 day GROUP BY nm ORDER BY nm"

    # Grid Power
    run client () sql customers format=table "SELECT ts, w FROM egauge_kafka WHERE nm = 'Grid Power' AND ts > now() - 1 hour ORDER BY ts DESC LIMIT 20"

    # NILM results
    run client () sql customers format=table "SELECT ts, circuit, appliance, state, estimated_w FROM nilm_disaggregated ORDER BY ts DESC LIMIT 20"

    # Verify Kafka consumer and operator
    get processes
    get msg client
    get streaming
