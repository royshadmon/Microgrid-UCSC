# eGauge Poller — Dockerized Data Collector

Standalone Docker container that continuously polls eGauge energy meter
and streams register data to AnyLog via REST PUT.

## Architecture
```
eGauge (egauge18646) --GET /register?rate--> Poller Container --REST PUT--> AnyLog (port 32149) --> Postgres
```

Fetches instantaneous power readings (watts) for 16 registers every 10s.
SQLite buffer catches records during AnyLog downtime, flushes on reconnect.

## Registers

VA, VB, I11, I12, I21, I22, I31, I32, F1, Grid Power (GRD),
Generac Power (GEN), Utility Tie (UT), Shop (SHP), HVAC (HVC),
H2O, Kitchen (KIT)

## Quick Start
```bash
cp .env.example .env    # fill in eGauge credentials
docker compose build
docker compose up -d
```

## Verify
```bash
curl -s "http://127.0.0.1:32149" \
  -H "User-Agent: AnyLog/1.23" \
  -H "command: sql customers select count(*) from egauge_data"
```

## Config (env vars)

| Variable | Default | Description |
|----------|---------|-------------|
| EGAUGE_URI | https://egauge18646.egaug.es | Meter URL |
| EGAUGE_USER | - | eGauge login |
| EGAUGE_PASS | - | eGauge password |
| ANYLOG_CONN | 127.0.0.1:32149 | AnyLog operator |
| ANYLOG_DBMS | customers | Target database |
| ANYLOG_TABLE | egauge_data | Target table |
| POLL_INTERVAL | 10 | Seconds between polls |

## Files

- `egauge_poller.py` — polling loop with tenacity retry + SQLite buffer
- `healthcheck.py` — Docker HEALTHCHECK via heartbeat file
- `Dockerfile` — python:3.11-slim, non-root user
- `docker-compose.yml` — host networking, persistent volume, auto-restart
- `.env` — credentials (git-ignored)
