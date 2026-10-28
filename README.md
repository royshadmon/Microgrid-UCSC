# Microgrid IEMS

An intelligent energy management system for a home with solar, a battery and
an energy meter. It reads the power on each electrical sub-panel, works out
which of 22 appliances are running from that power alone (non-intrusive load
monitoring, NILM), and shows the house, the battery, the solar and advice on
when to run heavy loads on a live dashboard with a plain language Ask box.

It was built at UC Santa Cruz for a real residential microgrid in Los Gatos,
California. This repository runs the whole system on your own computer, on
recorded data first, and on your own meter if you have one.

## Run it on your computer

You need Docker Desktop (or Docker Engine on Linux) and an AnyLog license.
The full walk through, written for someone who has never used Docker, is in
**[docs/guide/](docs/guide/README.md)**.

macOS and Linux.

```bash
git clone --branch new-guide https://github.com/royshadmon/Microgrid-UCSC.git
cd Microgrid-UCSC
./scripts/setup.sh        # checks Docker, creates .env, asks for the license
./scripts/start.sh        # builds, starts, waits, prints the addresses
./scripts/status.sh       # is data flowing
```

Windows PowerShell.

```powershell
git clone --branch new-guide https://github.com/royshadmon/Microgrid-UCSC.git
cd Microgrid-UCSC
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\status.ps1
```

Then open **http://localhost:47821**. Stop it with `./scripts/stop.sh`
(`.\scripts\stop.ps1`).

## How it works

```
 eGauge meter ──▶ egauge-producer ─┐                 ┌──▶ anylog-consumer ──┐
   (or demo-replay, recorded data) ├──▶ Kafka ───────┤                      ▼
                                   │                 └──▶ AnyLog operator ──▶ Postgres
 Solar Assistant ─▶ solar-producer ┴──▶ AnyLog MQTT ─────────▲     │
                                                                    │ partitions by month
                                         AnyLog master (metadata) ◀─┘
                                                                    │
            iems-inference ◀────────────── 10 minute windows ───────┤
            per panel BiLSTM (ONNX) + physics rules                 │
            writes nilm_disaggregated ─────────────────────────────▶│
                                                                    │
  browser ◀── iems-dashboard :47821 ◀──── reads AnyLog ─────────────┘
                 │  Ask
                 ▼
            iems-backend :8009 ──▶ ollama (local language model)
```

| service | what it does | port |
|---|---|---|
| `postgres` | stores every reading | 5432 |
| `master`, `operator1` | AnyLog, the data layer that ingests, partitions and serves the readings | 32048 to 32149, 1883 |
| `kafka` | buffers the meter feed | 9092, 9094 |
| `anylog-consumer` | moves meter readings from Kafka into AnyLog | |
| `demo-replay` | plays a recorded scenario instead of real hardware (profile `demo`) | |
| `egauge-producer`, `solar-producer` | read the real meter and inverter (profile `live`) | |
| `iems-inference` | runs the appliance models every 30 s | |
| `iems-backend` | the engine API and Ask | 8009 |
| `iems-dashboard` | the live dashboard | 47821 |
| `ollama` | the local language model behind Ask | 11434 |
| `iems-app` | the AnyLog Remote GUI with the IEMS page (profile `gui`) | 3001, 8000 |
| `kafka-ui` | a web view of the Kafka topic (profile `tools`) | 8080 |

## What is in this repository

| path | contents |
|---|---|
| `scripts/` | `setup`, `start`, `stop`, `status`, `logs` for macOS and Linux (`.sh`) and Windows (`.ps1`). `scripts/ops/` holds the deployment scripts for the original site |
| `docker-compose.yaml` | the whole stack |
| `.env.example` | every setting, explained. Copy to `.env` |
| `config/` | the appliance catalogue and your Home Assistant token |
| `services/iems/` | the Python package: models, inference loop, rules, engine API, Ask, dashboard |
| `services/remote-gui-overlay-212/` | the IEMS page added to the AnyLog Remote GUI |
| `streaming/` | the producers, the demo replay, the Kafka bridge, Postgres init and AnyLog node configuration |
| `tests/` | unit tests, and `tests/scenarios/` with recorded outage and edge case data |
| `analysis/`, `tools/` | inventory data, site probes and the knowledge graph builder |
| `docs/guide/` | the step by step guide |
| `docs/reference/` | in depth notes on architecture, labelling, rules, training, inference, APIs, streaming and operations |

## The models

Three bidirectional LSTM networks, one per sub-panel, exported to ONNX and run
on the CPU. They see 18 features over a 10 minute window, the panel's own power,
the other panels, voltages, currents, time of day, sun position, clear sky
irradiance and measured solar, and output one probability per appliance. A
physics rules layer then checks every result against the measured power, the
time of day and the sun. Training is described in
[`docs/reference/04_training_pipeline.md`](docs/reference/04_training_pipeline.md)
and the measured accuracy of every appliance is listed there.

## Contact

Harsh Ranjan, hranjan@ucsc.edu
