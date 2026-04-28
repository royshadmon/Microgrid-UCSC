# Microgrid-UCSC

Residential microgrid monitoring and disaggregation pipeline for
Dr. Mantey's site. eGauge 18646 register data is published to Kafka,
ingested by an AnyLog operator via its native Kafka consumer,
persisted to Postgres, optionally disaggregated by an LLM-based NILM
module, and visualized through the AnyLog Remote-GUI.

## Architecture

```
eGauge 18646 ──▶ Kafka (egauge-energy) ──▶ AnyLog operator1 ──▶ Postgres
                                                  │
                                                  ├──▶ NILM (LLM4NILM) ──▶ nilm_disaggregated
                                                  │
                                                  └──▶ Remote-GUI / IEMS
```

The site has three sub-panels behind the main and a backup generator:
Panel1 (HVAC, ~4 kW heat pump), Panel2 (H2O, ~4 kW water heater
preheated by a solar thermal boiler, plus bathrooms and outside
outlets), Panel3 (Kitchen: fridge, microwave, dishwasher, cooktop),
Shop, plus VrmsA/VrmsB voltage. Generac Power is the fossil backup.

## Repository layout

`kafka-egauge-pipeline/` — eGauge poller + Kafka broker compose stack.
The producer publishes 1-second JSON records to the `egauge-energy`
topic. AnyLog consumes the topic natively (see `anylog-config/`), so
the legacy `kafka_to_anylog.py` bridge is deprecated and kept only
for reference.

`anylog-config/` — `local_script.al` and `base_configs.env` for the
AnyLog operator. The script registers the native Kafka consumer
against the `egauge-energy` topic and writes incoming rows to
`customers.egauge_kafka`.

`nilm/` — Standalone disaggregator (`nilm_disaggregator.py`) used as
a one-shot script. Pulls a recent power window per circuit from
AnyLog, runs disaggregation, and writes per-appliance state back to
`customers.nilm_disaggregated`.

`services/iems/` — Intelligent Energy Management System. Implements
the four-domain architecture (User · Load · Generation · Storage)
from Adabi 2016 (UCSC PhD, escholarship/uc/item/4mq64408). The Load
domain uses the LLM4NILM disaggregator from Xue et al. 2025
(arXiv:2505.06330) to replace Adabi's J48 classifier. Two operating
modes: on-grid (cost optimization against PG&E E6 TOU) and off-grid
(laxity-based load shedding). Entry point is `runner.run_iems_cycle()`.
Subpackages: `load/` (disaggregation, anomaly, shedding),
`generation/` (solar forecast, grid analytics), `storage/` (virtual
SoC + dispatch), `decision_support/` (rule tree, optimizer,
recommender). `web/server.js` is a zero-dependency Node dashboard on
:47821 that consumes both the AnyLog REST and the IEMS FastAPI.

`services/remote-gui-iems-plugin/` — IEMS feature plugin for the
AnyLog Remote-GUI. Remote-GUI itself is an external dependency
(github.com/AnyLog-co/Remote-GUI) and is NOT vendored here; see
`services/remote-gui-iems-plugin/INSTALL.md` for how to overlay these
files (and the three small upstream patches under `upstream-patches/`)
onto a Remote-GUI checkout.

`docker-compose.yaml` — top-level compose for Ollama and the
`iems-app` container. The `iems-app` build context points at a local
Remote-GUI clone with the IEMS plugin overlay applied (see above);
clone Remote-GUI into `services/remote-gui/` before `docker compose up`.

`scripts/start_all.sh` — brings up the Kafka stack, verifies
operator1 is healthy with the Kafka consumer registered, and starts
Ollama plus the IEMS containers.

`tests/` — pytest suite covering the AnyLog query layer, the prompt
builder, the LLM output normalizer, the load-shedding ranker, the
on-grid and off-grid optimizers, and an end-to-end runner smoke test.

## Run

Bring up Kafka and the producer:

```
cd kafka-egauge-pipeline
cp .env.example .env       # set EGAUGE_URI, EGAUGE_USER, EGAUGE_PASS
docker compose -f docker-compose.kafka.yml up -d
```

Start AnyLog operator1 with `anylog-config/local_script.al`. The
native consumer will pick up `egauge-energy` and write to
`customers.egauge_kafka`. Verify:

```
curl -s http://127.0.0.1:32149 \
  -H "User-Agent: AnyLog/1.23" \
  -H "destination: network" \
  -H 'command: sql customers format=json "SELECT MAX(ts), COUNT(*) FROM egauge_kafka WHERE ts >= NOW() - 5 minute"'
```

Bring up Ollama and the IEMS app:

```
./scripts/start_all.sh
```

Run NILM standalone (without the IEMS umbrella):

```
python nilm/nilm_disaggregator.py
```

## Data schema

Database `customers`. Live Kafka mirror: `egauge_kafka(ts, dev, nm,
tp, w, kwh)`. Channel names live in `nm`: `Grid Power`, `Generac
Power`, `Panel1 (HVAC)`, `Panel2 (H2O)`, `Panel3 (Kitchen)`, `Shop`,
`VrmsA`, `VrmsB`. NILM output table is `nilm_disaggregated`.

## Endpoints

```
AnyLog operator1 REST   http://127.0.0.1:32149
AnyLog operator1 TCP    127.0.0.1:32148
AnyLog operator1 broker 127.0.0.1:1883
AnyLog master           host.docker.internal:32048
Postgres                host.docker.internal:5432  (user demo / passwd)
Kafka broker            host.docker.internal:9094
IEMS API                http://127.0.0.1:8000
IEMS UI (Remote-GUI)    http://127.0.0.1:3001
IEMS dashboard (node)   http://127.0.0.1:47821
Ollama                  http://127.0.0.1:11434
```

## Notes

The Panel2 water heater is preheated by a solar thermal boiler, so
its electric draw is highly weather-dependent. Long zero-draw stretches
on cold cloudy days are an anomaly worth flagging, not a healthy
state. The Panel1 heat pump is COP-dependent and dominates winter
load below ~50 °F. Appliance priors in `services/iems/config.py`
reflect both behaviours.
