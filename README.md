# Microgrid-UCSC

Real-time energy monitoring: eGauge → Kafka → AnyLog → Postgres → Grafana.

## Files

All files are in `kafka-egauge-pipeline/`.

- `egauge_kafka_producer.py` — Polls eGauge meter every 1s, publishes to Kafka
- `kafka_to_anylog.py` — Fallback bridge: reads Kafka, REST PUTs to AnyLog
- `docker-compose.kafka.yml` — Kafka (KRaft) + producer containers
- `Dockerfile.producer` / `Dockerfile.consumer` — Container build files
- `grafana_dashboard.json` — Importable Grafana dashboard (6 panels)

## Setup

1. Create `.env` in `kafka-egauge-pipeline/` with your eGauge credentials:
```
EGAUGE_URI=https://egaugeXXXXX.egaug.es
EGAUGE_USER=owner
EGAUGE_PASS=your-password
```

2. Start Kafka and producer:
```
cd kafka-egauge-pipeline
docker-compose -f docker-compose.kafka.yml up -d
```

3. Inside AnyLog operator CLI, start the consumer:
```
run kafka consumer where ip = host.docker.internal and port = 9094 and reset = earliest and topic = (name = egauge-energy and dbms = customers and table = egauge_kafka and column.ts.timestamp = "bring [ts]" and column.dev.str = "bring [dev]" and column.nm.str = "bring [nm]" and column.tp.str = "bring [tp]" and column.w.float = "bring [w]" and column.kwh.float = "bring [kwh]")
```

4. Import `grafana_dashboard.json` in Grafana via Dashboards → Import.

## What to change

- `.env` — Your eGauge meter URL and credentials
- `grafana_dashboard.json` — Update the partition table name when it rolls over (every 14 days). Search and replace `par_egauge_kafka_2026_03_01_d14_insert_timestamp` with the current partition name from `get tables where dbms = customers` in AnyLog
- `grafana_dashboard.json` — If Grafana runs in Docker, change `localhost:32149` to `host.docker.internal:32149`
- Infinity datasource UID — If yours differs from `bffk64c6007wgf`, update the `uid` fields in the dashboard JSON

## Dashboard panels

1. **Grid Power** — Total power drawn from/fed to utility grid (watts)
2. **HVAC Power** — Heating and cooling system consumption
3. **Water Heater Power** — Hot water system consumption
4. **Kitchen Power** — Kitchen appliances consumption
5. **Voltage (Phase A & B)** — RMS voltage on both electrical phases
6. **Average Power by Register** — Bar chart of mean watts across all power registers

## 16 Registers

VrmsA, VrmsB, I11, I12, I21, I22, I31, I32, F1, Grid Power, Generac Power, Current on Utility Tie, Shop, Panel1 (HVAC), Panel2 (H2O), Panel3 (Kitchen)
