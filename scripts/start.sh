#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# IEMS Full Stack Startup Script
# Starts all services in dependency order and verifies each before proceeding.
# Run from anywhere: ~/microgrid-manager/scripts/start.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGER_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_DIR="$HOME/docker-compose/docker-makefiles/docker-compose-files"
KAFKA_DIR="$HOME/kafka-egauge-pipeline"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

wait_http() {
  local url=$1 label=$2 attempts=${3:-20}
  for i in $(seq 1 $attempts); do
    if curl -sf --max-time 3 "$url" > /dev/null 2>&1; then
      ok "$label is up"
      return 0
    fi
    sleep 2
  done
  fail "$label did not respond after $((attempts*2))s"
}

anylog_post() {
  curl -sf --max-time 8 http://127.0.0.1:32149 \
    -H "User-Agent: AnyLog/1.23" \
    -X POST -H "command: $1" > /dev/null 2>&1
}

anylog_get() {
  curl -s --max-time 8 http://127.0.0.1:32149 \
    -H "User-Agent: AnyLog/1.23" \
    -H "command: $1" 2>/dev/null
}

echo ""
echo "  ⚡  IEMS Stack Startup"
echo "  ────────────────────────────────────────────────"

# ── 1. AnyLog master ──────────────────────────────────────────────────────────
echo ""
echo "  [1/6] AnyLog master"
cd "$COMPOSE_DIR"
docker compose -f master-docker-compose.yaml up -d 2>&1 | grep -E "Started|Running|Error" | sed 's/^/  /'
sleep 5

# ── 2. AnyLog operator1 ───────────────────────────────────────────────────────
echo ""
echo "  [2/6] AnyLog operator1"
docker compose -f operator1-docker-compose.yaml up -d 2>&1 | grep -E "Started|Running|Error" | sed 's/^/  /'

# Wait for REST to respond
echo "  Waiting for operator REST..."
for i in $(seq 1 25); do
  resp=$(curl -s --max-time 3 http://127.0.0.1:32149 \
    -H "User-Agent: AnyLog/1.23" -H "command: get status" 2>/dev/null)
  if echo "$resp" | grep -q "running"; then
    ok "Operator REST responding"
    break
  fi
  if [ $i -eq 25 ]; then fail "Operator REST timeout"; fi
  sleep 2
done

# Verify operator, streamer, kafka consumer all running
# (validate_node_policy.al overlay-fallback fix means these start automatically)
# Fallback injection only runs if a process is still Not declared after boot
sleep 5
processes=$(anylog_get "get processes")
for proc in "Operator" "Streamer" "Kafka Consumer"; do
  if echo "$processes" | grep -q "$proc.*Running"; then
    ok "$proc running"
  else
    warn "$proc NOT running — check operator logs"
  fi
done

# ── 3. Kafka + eGauge pipeline ────────────────────────────────────────────────
echo ""
echo "  [3/6] Kafka + eGauge pipeline"
cd "$KAFKA_DIR"
docker compose -f docker-compose.kafka.yml up -d 2>&1 | grep -E "Started|Running|Healthy|Error" | sed 's/^/  /'
ok "Kafka stack started"

# ── 4. Ollama + iems-app ──────────────────────────────────────────────────────
echo ""
echo "  [4/6] Ollama + iems-app (microgrid-manager)"
cd "$MANAGER_DIR"
docker compose up -d 2>&1 | grep -E "Started|Running|Error" | sed 's/^/  /'

echo "  Waiting for iems-app..."
for i in $(seq 1 20); do
  resp=$(curl -s --max-time 3 http://127.0.0.1:8000/iems/health 2>/dev/null)
  if echo "$resp" | grep -q '"anylog":true'; then
    ok "iems-app healthy (anylog=true)"
    break
  fi
  if [ $i -eq 20 ]; then
    warn "iems-app slow to start — check: docker logs iems-app"
  fi
  sleep 3
done

# Check ollama models
model_count=$(curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('models',[])))" 2>/dev/null || echo "0")
if [ "$model_count" -gt 0 ]; then
  ok "Ollama: $model_count model(s) loaded"
else
  warn "Ollama has no models — run: ollama pull llama3.1:8b"
fi

# ── 5. Node.js dashboard ──────────────────────────────────────────────────────
echo ""
echo "  [5/6] Node.js dashboard (port 47821)"
pkill -f "server.js" 2>/dev/null || true
sleep 1
nohup node "$MANAGER_DIR/services/iems/web/server.js" \
  > /tmp/iems_server.log 2>&1 &
echo $! > /tmp/iems_server.pid
sleep 4

wait_http "http://127.0.0.1:47821/api/health" "Dashboard server" 10

# ── 6. Final data flow check ──────────────────────────────────────────────────
echo ""
echo "  [6/6] Data flow verification"

# egauge_kafka freshness
rows=$(python3 -c "
import socket, re, json
from datetime import datetime, timezone, timedelta
s=socket.create_connection(('127.0.0.1',32149),timeout=10)
since=(datetime.now(timezone.utc)-timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S')
s.sendall(f'GET / HTTP/1.1\r\nHost: 127.0.0.1:32149\r\nUser-Agent: AnyLog/1.23\r\ncommand: sql customers format=json and stat=false \"SELECT COUNT(*) as cnt FROM par_egauge_kafka_2026_05_00_d14_insert_timestamp WHERE ts > \\\"{since}\\\"\"\r\nConnection: close\r\n\r\n'.encode())
s.settimeout(10); buf=b''
try:
    while True:
        c=s.recv(8192)
        if not c: break
        buf+=c
except: pass
finally: s.close()
body=buf.split(b'\r\n\r\n',1)[-1].decode(errors='replace')
r=re.sub(r'(?m)^[0-9a-fA-F]+\r\n','',body).strip()
try: print(json.loads(r)['Query'][0].get('cnt',0))
except: print(0)
" 2>/dev/null)

if [ "${rows:-0}" -gt 0 ]; then
  ok "egauge_kafka: $rows rows in last 2 min — data flowing"
else
  warn "egauge_kafka: no recent rows — Kafka consumer may need time to warm up"
fi

echo ""
echo "  ────────────────────────────────────────────────"
echo "  ✅  IEMS stack is running"
echo ""
echo "     Dashboard  →  http://localhost:47821"
echo "     FastAPI    →  http://localhost:8000/iems/health"
echo "     Kafka UI   →  http://localhost:8080"
echo "     AnyLog     →  http://localhost:32149"
echo ""
