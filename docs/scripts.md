# Scripts Folder

`scripts/` — shell scripts that bring the eleven-container stack up and down in the right order. All bash, run-from-anywhere:

```
scripts/
├── start.sh          # primary start: ordered, verifies each step
├── start_all.sh      # legacy quick-start (older flow, kept for reference)
└── stop.sh           # graceful shutdown matching start.sh
```

## `start.sh`

The production bring-up script. Six ordered steps, each with a health check before the next runs.

**Main contents.** Six phases:

1. **AnyLog master** — `docker compose -f master-docker-compose.yaml up -d`, 5 s settle.
2. **AnyLog operator1** — `up -d`, then poll `get status` on the REST port for up to 50 s; once it responds, verify `Operator`, `Streamer`, and `Kafka Consumer` are all `Running`.
3. **Kafka + eGauge pipeline** — `docker compose -f docker-compose.kafka.yml up -d` from `~/kafka-egauge-pipeline`.
4. **Ollama + iems-app** — root `docker compose up -d`, then poll `/iems/health` for up to 60 s waiting for `"anylog": true`; warn if Ollama has no models pulled.
5. **Node.js dashboard** — kills any stale `server.js`, restarts it with `nohup`, waits for `/api/health` to respond.
6. **Data-flow verification** — runs an inline Python script that opens a raw socket to the operator and counts rows in `par_egauge_kafka_YYYY_MM_00_d14_insert_timestamp` over the last 2 minutes. Warns if zero.

**Helper functions** at the top:

```bash
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

wait_http() {                                                  # HTTP polling
  local url=$1 label=$2 attempts=${3:-20}
  for i in $(seq 1 $attempts); do
    curl -sf --max-time 3 "$url" > /dev/null 2>&1 && { ok "$label is up"; return 0; }
    sleep 2
  done
  fail "$label did not respond after $((attempts*2))s"
}

anylog_post() { curl -sf --max-time 8 http://127.0.0.1:32149 \
                -H "User-Agent: AnyLog/1.23" -X POST -H "command: $1" > /dev/null; }
anylog_get()  { curl -s  --max-time 8 http://127.0.0.1:32149 \
                -H "User-Agent: AnyLog/1.23" -H "command: $1"; }
```

The reason `wait_http` and these AnyLog helpers exist: a `docker up` that exits 0 doesn't mean the service is *ready*. AnyLog's operator in particular goes through policy bootstrap and Kafka-consumer registration after the container starts; `start.sh` blocks until those are visibly done.

**Output the user actually sees.** A green ✅ block at the end with the four URLs that matter:

```
Dashboard  →  http://localhost:47821
FastAPI    →  http://localhost:8000/iems/health
Kafka UI   →  http://localhost:8080
AnyLog     →  http://localhost:32149
```

**Use in the project.** This is the single command Pat (and any new collaborator) runs after `git clone` + `docker compose up -d`. The verbose verification is deliberate: silent failures in this stack — operator without Kafka consumer registered, iems-app starting before AnyLog is up, dashboard pointing at a stale port — have eaten hours in the past, and each ordered check exists to surface a real failure mode from the project history.

## `start_all.sh`

Older, simpler bring-up. No status polling, just sequential `docker-compose up -d` calls with `sleep` between them. Six numbered steps in comments: Kafka, operator health, Kafka-consumer re-registration if missing, port collision check, Ollama+IEMS up, default model pull (`mistral:7b`). It's kept for two reasons:

1. The Kafka-consumer re-registration block is the canonical example of the POST-with-`command:` shape the AnyLog REST endpoint requires (note the lack of `run client ()` — see `docs/anylog_query_cookbook.md`).
2. When `start.sh`'s health-check loops are getting in the way during debugging, `start_all.sh` is the quick-and-dirty alternative.

Prefer `start.sh` for everyday bring-up.

## `stop.sh`

Mirror of `start.sh`, in reverse, four phases:

1. Node.js dashboard — kill by PID from `/tmp/iems_server.pid`, or `pkill -f "server.js"`.
2. `iems-app` + Ollama — `docker compose stop` from the repo root.
3. Kafka stack — `docker compose -f docker-compose.kafka.yml stop`.
4. AnyLog stack — operator1 first, then master.

Uses `stop` (not `down`) so named volumes survive. Postgres is intentionally left running because it has no dependents that need to come back up with it — the trailing message tells the user how to stop it manually:

```bash
docker stop postgres1
```
