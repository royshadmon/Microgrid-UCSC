# Microgrid IEMS — Installation Guide for Dr. Mantey's House

This is the from-scratch setup walkthrough for the residential Intelligent
Energy Management System (IEMS). Follow it top to bottom on a freshly imaged
Mac mini (or any Mac) sitting next to the eGauge meter at the house. By the
end, every service runs inside Docker and starts automatically on reboot.

If you have never seen this project before, also read
[How everything works](#how-everything-works) at the end of this document
before troubleshooting anything.

---

## 0. What you should already have at the house

| Item | Notes |
|---|---|
| Mac mini (or any macOS computer) | 16 GB RAM minimum, 256 GB disk free |
| eGauge18646 meter | Already wired to the three sub-panels + Shop |
| Ethernet from meter to LAN | The Mac and the meter must be on the same network |
| 2009 lead-acid battery bank | No instrumentation needed — SOC is modeled |
| AnyLog license key | Request from the AnyLog team if missing |
| Akave object storage credentials | Three values: access key, secret key, endpoint |
| eGauge meter credentials | Username and password from the meter admin UI |

You do **not** need: a separate PV meter, an EV charger, or a battery BMS reader.
The system derives solar from an energy balance and models battery SOC by default.
If the house also has a Solar Assistant box (measuring real PV/battery/grid/load),
point `solar-producer` at it (Section 3.3) for measured values instead.

---

## 1. Install the prerequisites (one-time, on the Mac)

Open Terminal and run these in order.

### 1.1 Xcode command line tools
```bash
xcode-select --install
```
A GUI dialog will pop up. Click *Install*, wait for it to finish (5-10 min).

### 1.2 Homebrew
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
When it finishes, copy the two `eval` lines it prints and paste them into the
terminal (this adds `brew` to your PATH).

### 1.3 Docker Desktop
```bash
brew install --cask docker
open -a Docker
```
The first time you open Docker Desktop, click through the welcome screens and
accept the terms. Wait until the Docker whale icon in the menu bar stops
animating. Confirm:
```bash
docker ps
```
You should see an empty table (no error).

### 1.4 Git
```bash
brew install git
git --version
```

### 1.5 SSH key for GitHub
```bash
ssh-keygen -t ed25519 -C "harshranjan@ucsc.edu"
# Press Enter through all prompts (no passphrase is fine for a dedicated host)
cat ~/.ssh/id_ed25519.pub
```
Copy the printed line, then open <https://github.com/settings/keys>, click
*New SSH key*, paste it, and save. Test:
```bash
ssh -T git@github.com
```
You should see `Hi harshranjan! You've successfully authenticated`.

---

## 2. Clone the repo

```bash
cd ~
git clone -b dev_fin git@github.com:royshadmon/Microgrid-UCSC.git microgrid-manager
cd microgrid-manager
```

That single clone contains **everything**: the streaming stack configs
(AnyLog, Kafka, Postgres), the eGauge producer, the NILM models, the
inference loop, the FastAPI backend, the React frontend, and the live
dashboard. There is nothing else to download.

---

## 3. Fill in the secrets

There are **two** environment files to create. Copy the templates and edit:

### 3.1 Root `.env` (most secrets live here)
```bash
cp .env.example .env
nano .env        # or open with your editor of choice
```
Fill in:
- `ANYLOG_LICENSE` — the license string from the AnyLog team
- `AKAVE_ACCESS_KEY_RC2`, `AKAVE_SECRET_KEY_RC2`, `AKAVE_ENDPOINT_RC2`
- `EGAUGE_USER`, `EGAUGE_PASS` — meter admin credentials
- `EGAUGE_URI` — usually `https://egauge18646.egaug.es` (already set)

Leave everything else at the defaults unless you are deploying somewhere
other than Los Gatos.

### 3.2 Kafka pipeline `.env` (eGauge poller picks it up too)
```bash
cp streaming/kafka-egauge-pipeline/.env.example streaming/kafka-egauge-pipeline/.env
nano streaming/kafka-egauge-pipeline/.env
```
Use the same `EGAUGE_*` values you put in the root `.env`.

The duplication is intentional: the Kafka sub-compose can be brought up on
its own for debugging, so it carries its own copy of the eGauge credentials.

### 3.3 Solar Assistant `.env` (optional — only if the house has one)
```bash
cp streaming/solar-pipeline/.env.example streaming/solar-pipeline/.env
nano streaming/solar-pipeline/.env
```
Fill in `SA_BROKER` (the Solar Assistant Pi's LAN IP), `SA_PORT` (1883),
`SA_USER`/`SA_PASS` (its Mosquitto credentials), and `SA_PREFIX`. The root
`.env` also needs the same `SA_*` values — `solar-producer` reads them from
there via `docker-compose.yaml`. Leave `INGEST_MODE=broker` at its default;
AnyLog itself acts as the MQTT broker (`run msg client`, Section 5.3) and
`solar-producer` publishes into it. Set `INGEST_MODE=rest` only if the
broker mapping isn't configured on the operator yet.

Skip this file entirely if there is no Solar Assistant installation — the
rest of the stack (eGauge, NILM inference) runs the same without it and
the rules engine falls back to weather-derived solar gating.

---

## 4. Bring up the stack

This is the moment of truth. One command:

```bash
docker compose up -d
```

The first run will take 10-15 minutes (downloading images, building three
custom containers). Subsequent starts take about 30 seconds.

Watch it come alive:
```bash
docker compose ps
```

You should see eleven containers in `Up` (or `healthy`) state, twelve if
the `SA_*` variables are filled in and `solar-producer` is enabled:

```
postgres1, master, operator1, kafka, kafka-ui, egauge-producer,
anylog-consumer, ollama, iems-app, iems-inference, iems-dashboard,
solar-producer (optional)
```

If any are `Restarting`, jump to [Troubleshooting](#8-troubleshooting).

---

## 5. Verify it is actually working

These four checks tell us the data is flowing end to end.

### 5.1 Postgres is alive
```bash
docker exec postgres1 psql -U admin -d customers -c "\dt"
```
You should see a list of tables. If the table `egauge_kafka` is missing on
the first start, give it 60 seconds — the AnyLog operator creates it on the
first Kafka message.

### 5.2 The eGauge meter is being polled
```bash
docker logs egauge-producer --tail 20
```
Look for lines like `published 16 channels`. If you see `auth failed` or
`connection refused`, recheck `EGAUGE_USER` / `EGAUGE_PASS` / `EGAUGE_URI`.

### 5.3 AnyLog is consuming and writing
```bash
docker exec postgres1 psql -U admin -d customers -t -A -c \
  "SELECT COUNT(*), MAX(ts) FROM par_egauge_kafka_$(date +%Y_%m)_00_d14_insert_timestamp;"
```
Both numbers should advance every time you re-run this command.

### 5.4 The NILM inference loop is producing predictions
```bash
docker logs iems-inference --tail 30
```
You should see a heartbeat line every 30 seconds with each appliance's
ON/OFF state and confidence. If Solar Assistant is connected, this line
also shows a `solar: pv=...W batt=...W soc=...% grid=...W load=...W` reading —
that means the loop is gating the Panel1 solar-pump rule off measured PV
instead of the weather proxy.

### 5.5 Solar Assistant is reaching AnyLog (skip if no Solar Assistant box)
```bash
docker logs solar-producer --tail 20
docker exec postgres1 psql -U admin -d customers -t -A -c \
  "SELECT COUNT(*), MAX(ts) FROM par_solar_data_$(date +%Y_%m)_insert_timestamp;"
```
The count should climb every time you re-run the query. If it stays at
zero, confirm `SA_BROKER`/`SA_USER`/`SA_PASS` in `.env` and that AnyLog's
`run msg client` mapping is active on the operator (Section 8 troubleshooting).

### 5.6 Open the dashboards in a browser

| URL | What it is |
|---|---|
| http://localhost:47821 | The live IEMS dashboard (the one we built) |
| http://localhost:3001/dashboard/iems | The React IEMS page (richer UI) |
| http://localhost:8000/docs | FastAPI auto-generated API docs |
| http://localhost:8080 | Kafka UI — useful for verifying message flow |

If the dashboard at :47821 shows live wattages and the NILM grid lights up
within a minute or two, the system is fully operational.

---

## 6. Make it survive reboots

Docker Desktop is already configured to start at login. Every container in
the compose file has `restart: unless-stopped`, so after a power cycle the
whole stack comes back automatically once Docker Desktop is running.

To confirm:
```bash
docker compose ps   # everything should be Up
```
If Docker Desktop is not set to launch at login:
*System Settings → General → Login Items → +* and add Docker.

---

## 7. Day-to-day operations

### Stop everything
```bash
cd ~/microgrid-manager && docker compose down
```
Volumes (Postgres data, AnyLog state) persist. Add `-v` to wipe them.

### Restart a single service
```bash
docker compose restart iems-inference
```

### Tail logs
```bash
docker compose logs -f iems-inference   # or iems-app, operator1, etc.
```

### Apply a code change to the inference loop
The IEMS Python code is volume-mounted into `iems-app` (live) but is baked
into the `iems-inference` image. After editing anything under
`services/iems/inference/`, `services/iems/models/`, `services/iems/training/`,
or the rules engine, rebuild and restart:
```bash
docker compose build iems-inference
docker compose up -d iems-inference
```

### Apply a code change to the FastAPI backend
The whole `services/iems/` tree is volume-mounted into `iems-app`, so a
restart is enough:
```bash
docker compose restart iems-app
```

### Pull updates from GitHub
```bash
cd ~/microgrid-manager
git pull
docker compose build
docker compose up -d
```

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `operator1` keeps restarting | `ANYLOG_LICENSE` missing or wrong | Fix `.env`, then `docker compose up -d operator1` |
| `egauge-producer` logs `auth failed` | Wrong eGauge credentials | Fix both `.env` files, then `docker compose restart egauge-producer` |
| Dashboard shows zeros for everything | No data flowing yet | Wait 2-3 minutes after first start; if still zero, check 5.2 and 5.3 |
| `iems-inference` logs `connection refused 32149` | Operator1 not ready | `docker compose restart iems-inference` after operator1 is healthy |
| AnyLog REST returns `err 156` or `err 56` | Do not prefix REST commands with `run client ()` | This is a code-level issue; report it |
| Postgres connection refused | Postgres slow to start | Wait for the `healthy` state in `docker compose ps` |
| Port already in use (5432, 8000, 8080, 47821) | Something else on the host using the port | Find it with `lsof -i :PORT` and stop it, or change the port in `docker-compose.yaml` |
| `solar-producer` logs `CONNACK rc=...` or connection refused | Wrong `SA_BROKER`/`SA_USER`/`SA_PASS`, or the Solar Assistant Pi is off the LAN | Fix `.env`, then `docker compose restart solar-producer` |
| `solar_data` count stuck at zero | AnyLog's `run msg client` topic mapping isn't active on the operator (broker mode), or the blockchain policy schema doesn't match the payload columns | Re-run the `run msg client` command from `operator1-configs/local_script.al`, or switch `INGEST_MODE=rest` and restart `solar-producer` |
| Free disk low | Old images / stopped containers | `docker system prune -a --volumes` (warning: removes data) |

For the AnyLog operator specifically, the most informative log lines are
near the top of:
```bash
docker logs operator1 2>&1 | head -100
```

---

## 9. Where things live in this repo

```
microgrid-manager/
├── docker-compose.yaml          # the master compose — brings up everything
├── .env.example                 # template you copied to .env
├── INSTALL.md                   # you are here
├── README.md                    # technical architecture reference
│
├── streaming/                   # everything needed to ingest data
│   ├── anylog/                  # AnyLog master + operator1 configs + compose
│   ├── kafka-egauge-pipeline/   # Kafka, eGauge producer, AnyLog consumer
│   ├── solar-pipeline/          # solar_producer.py — Solar Assistant MQTT -> AnyLog (optional)
│   ├── postgres/                # Postgres compose + init SQL (demo user)
│   └── launchd/                 # macOS launchd plist template (legacy)
│
├── services/
│   ├── iems/                    # the IEMS application itself
│   │   ├── inference/           # NILM ONNX disaggregator loop
│   │   │   ├── inference_loop.py
│   │   │   ├── onnx_disaggregator.py
│   │   │   ├── rules_additive.py    # physics + weather reconciliation
│   │   │   ├── feature_builder.py
│   │   │   ├── appliance_map.py
│   │   │   ├── Dockerfile
│   │   │   └── requirements.txt
│   │   ├── models/              # ONNX BiLSTM models + thresholds
│   │   ├── training/            # window builders, label rules, threshold tuning
│   │   ├── decision_support/    # DSS rule tree
│   │   ├── load/anylog_query.py
│   │   ├── storage/battery_model.py
│   │   ├── weather.py           # Open-Meteo fetcher
│   │   └── web/server.js        # zero-dep Node live dashboard
│   ├── remote-gui/              # AnyLog Remote-GUI (FastAPI + React)
│   └── remote-gui-iems-plugin/  # our IEMS-specific plugin layer
│
└── scripts/                     # legacy host-side bring-up scripts (start.sh etc.)
```

---

## How everything works

This section is for whoever is reading the project for the first time —
including any new student joining the lab. No jargon.

### The big picture

A house has electricity coming in from the grid, going out to solar (via
net-meter export), and being consumed by dozens of appliances behind three
sub-panels. The eGauge meter measures, every second, the total power in
six places (Grid, Generac, Panel1 HVAC, Panel2 H2O, Panel3 Kitchen, Shop).
That is it — the eGauge does not measure individual appliances, and it has
no PV channel. Where the house also has a Solar Assistant box, that
supplies real PV/battery/grid/load readings on a separate path (Section 3
above), used by the rules engine when available.

Our job is to figure out, in near-real-time, **which appliances are on**
and to advise the homeowner about better usage patterns. Doing this from
panel-level totals is called Non-Intrusive Load Monitoring (NILM).

### The pipeline, in five steps

```
  eGauge meter           Kafka              AnyLog              Postgres            Inference loop          Dashboards
  (LAN device)    ───>   (broker)    ───>   (operator)   ───>   (time-series   ───>  (every 30s)     ───>  (browser)
       1 sample/s          buffer           routes data         storage)             reads window,
                                            into Postgres                             runs ONNX,
                                                                                      writes results
```

1. **eGauge → Kafka.** The producer container polls the meter once per
   second and publishes 16 channels (six panel totals plus per-leg voltage,
   current, and frequency) to the Kafka topic `egauge-energy`.

1a. **Solar Assistant → AnyLog broker (optional, parallel path).** If the
   house has a Solar Assistant box, `solar-producer` subscribes to its
   local MQTT broker and republishes each reading into AnyLog's own MQTT
   broker; a `run msg client` mapping on the operator lands it in the
   `solar_data` table (pv_power, battery_power, battery_soc, grid_power,
   load_power, device_mode) — no Kafka involved on this path.

2. **Kafka → AnyLog → Postgres.** The AnyLog operator container subscribes
   to the Kafka topic and writes each message as a row into the
   `egauge_kafka` table in Postgres. AnyLog partitions tables by month so
   older data stays fast to query.

3. **Inference loop pulls a window.** Every 30 seconds the
   `iems-inference` container queries AnyLog for the last 10 minutes of
   panel power, joins it with the current outside temperature and solar
   irradiance from Open-Meteo (plus the latest `solar_data` snapshot when
   present), and shapes the result into a normalized tensor of size
   `(1, 100, 12)`.

4. **Three neural models + one rules engine.** That tensor goes to three
   separate ONNX models (one per sub-panel). Each model has a head per
   appliance that outputs a probability. Then the rules engine
   (`rules_additive.py`) reconciles those probabilities with hard physics
   facts:
   - An appliance cannot be on if its panel is not drawing enough power
     (this is the *power gate* — the single most important rule).
   - The solar circulation pump cannot be on at night — gated on measured
     `pv_power` from Solar Assistant when available, otherwise on the
     weather-derived irradiance/cloud-cover proxy.
   - The heat pump and the solar pump on Panel1 are interlocked.
   - When the solar pump is off, the electric water heater is the
     fallback hot-water source.

   The final state per appliance (`ON` / `OFF`) is written to the
   `nilm_disaggregated` table — one row per appliance per 30-second tick.

5. **Dashboards read those rows.** The live dashboard at port 47821
   refreshes every few seconds, lights up appliance cards, shows derived
   solar (from the energy balance) and modeled battery SOC, and the DSS
   panel surfaces recommendations.

### Why three models instead of one

Each sub-panel has a different mix of appliances and a wildly different
power signature. Panel3 (Kitchen) has the richest training signal because
the refrigerator and TV produce constant, distinctive patterns — that
model's F1 score is near 1.0 for those two appliances. Panel1 (HVAC) and
Panel2 (H2O) are weaker because they have fewer events per day and
labeled examples are sparse. The rules layer carries most of the weight
for those two, with the model adding probabilistic nudges.

### Why we have a rules engine at all

Neural models trained on imbalanced data will happily output false
positives. The rules engine is a safety net based on physics: real watts
into a panel sets a hard upper bound on what can be running behind it.
The rules engine is also what produces the *training labels* — the model
learns to mimic the rule engine plus subtler patterns the rules miss.

### Where the battery and solar numbers come from

The eGauge meter does not measure solar generation or battery state
directly, so by default both are estimated:

- **Solar** = `max(0, |P1| + |P2| + |P3| + |Shop| - GridImport - Generac)`.
  When loads exceed what the grid is sending in, the difference must be
  coming from the panels.
- **Battery SOC** is a software model in `storage/battery_model.py`.
  It assumes a 13.5 kWh lead-acid bank, depletes when solar cannot cover
  load, and charges (in the fallback path) when there is surplus solar
  between 4 PM and 9 PM. A 10% floor protects the bank from deep discharge.

These are best-effort estimates, not measurements, and the dashboard
labels them as derived. Where a Solar Assistant box is connected, the
rules engine (Section 4, `_low_solar` / `_battery_charging` in
`rules_additive.py`) uses its **measured** `pv_power`/`battery_power`
instead of the estimate for gating decisions — the dashboard's derived
solar/battery figures are unaffected and remain energy-balance estimates.

### What the DSS does

The Decision Support System (DSS) takes the appliance-level state plus
the current time-of-use rate and the load forecast, and surfaces small
actionable suggestions: shift the dishwasher to after 9 PM, defer the
dryer until solar is producing, that kind of thing. Each recommendation
comes with an estimated dollar savings and accept / defer / dismiss
buttons. The DSS is still under active development; some recommendations
are gated behind feature flags.

### What can go wrong, and how the system handles it

| Failure | What happens |
|---|---|
| eGauge offline | The producer logs the error and retries. AnyLog keeps serving stale data. Dashboards stop refreshing once the window has no fresh data. |
| Kafka offline | The producer buffers in memory briefly, then drops. Restart Kafka to recover. |
| AnyLog offline | Postgres still has historical data. Inference loop fails for that window and retries on the next tick. |
| One ONNX model corrupt | That panel's predictions fall back to the rules engine alone. |
| Outside temperature fetch fails | The weather module falls back to seasonal averages; rules still fire on the panel power signal. |
| Solar Assistant offline (if connected) | `solar-producer` retries the MQTT connection; `solar_data` goes stale. The rules engine's `fetch_solar_snapshot` treats a snapshot older than a few minutes as absent and falls back to the weather-derived solar/battery estimate automatically — no restart needed. |

---

## Contacts

- Project lead: Dr. Mantey (UCSC)
- Maintainer: Harsh Ranjan — harshranjan@ucsc.edu
- AnyLog support: anylog.co
