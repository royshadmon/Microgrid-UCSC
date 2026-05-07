#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# IEMS Full Stack Stop Script
# Stops all services cleanly without removing volumes or data.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGER_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_DIR="$HOME/docker-compose/docker-makefiles/docker-compose-files"
KAFKA_DIR="$HOME/kafka-egauge-pipeline"

GREEN='\033[0;32m'; NC='\033[0m'
ok() { echo -e "${GREEN}  ✓ $1${NC}"; }

echo ""
echo "  ⛔  IEMS Stack Shutdown"
echo "  ────────────────────────────────────────────────"

# Stop Node.js dashboard
echo ""
echo "  [1/4] Node.js dashboard"
if [ -f /tmp/iems_server.pid ]; then
  PID=$(cat /tmp/iems_server.pid)
  kill "$PID" 2>/dev/null && ok "server.js stopped (PID $PID)" || true
  rm -f /tmp/iems_server.pid
else
  pkill -f "server.js" 2>/dev/null && ok "server.js stopped" || ok "server.js was not running"
fi

# Stop iems-app + ollama
echo ""
echo "  [2/4] Ollama + iems-app"
cd "$MANAGER_DIR"
docker compose stop 2>&1 | grep -E "Stopped|Error" | sed 's/^/  /'
ok "iems-app + ollama stopped"

# Stop Kafka stack
echo ""
echo "  [3/4] Kafka + eGauge pipeline"
cd "$KAFKA_DIR"
docker compose -f docker-compose.kafka.yml stop 2>&1 | grep -E "Stopped|Error" | sed 's/^/  /'
ok "Kafka stack stopped"

# Stop AnyLog stack (master + operator1)
echo ""
echo "  [4/4] AnyLog master + operator1"
cd "$COMPOSE_DIR"
docker compose -f operator1-docker-compose.yaml stop 2>&1 | grep -E "Stopped|Error" | sed 's/^/  /'
docker compose -f master-docker-compose.yaml stop 2>&1 | grep -E "Stopped|Error" | sed 's/^/  /'
ok "AnyLog stack stopped"

echo ""
echo "  ────────────────────────────────────────────────"
echo "  Postgres (postgres1) left running — it has no restart dependency."
echo "  To stop it:  docker stop postgres1"
echo ""
