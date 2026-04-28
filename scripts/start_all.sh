#!/bin/bash
set -e

echo "[1/6] Kafka..."
cd ~/kafka-egauge-pipeline && docker-compose -f docker-compose.kafka.yml up -d
sleep 10
docker logs egauge-producer 2>&1 | tail -3

echo "[2/6] operator1 health check..."
curl -s http://127.0.0.1:32149 -H "User-Agent: AnyLog/1.23" \
  -H "command: get processes" | grep -E "Operator|REST" \
  || { echo "operator1 down — check anylog-docker-compose"; exit 1; }

echo "[3/6] Re-register Kafka consumer if absent..."
curl -s http://127.0.0.1:32149 -H "User-Agent: AnyLog/1.23" \
  -H "command: get msg client" | grep -q "egauge-energy" && \
  echo "  Kafka consumer already registered." || \
curl -s -X POST http://127.0.0.1:32149 \
  -H "User-Agent: AnyLog/1.23" \
  -H 'command: run kafka consumer where ip = host.docker.internal and port = 9094 and reset = earliest and topic = (name = egauge-energy and dbms = customers and table = egauge_kafka and column.ts.timestamp = "bring [ts]" and column.dev.str = "bring [dev]" and column.nm.str = "bring [nm]" and column.tp.str = "bring [tp]" and column.w.float = "bring [w]" and column.kwh.float = "bring [kwh]")'

echo "[4/6] Port check..."
if lsof -i :8000 2>/dev/null | grep -q LISTEN; then
  echo "  WARNING: port 8000 already in use"
fi
if lsof -i :3001 2>/dev/null | grep -q LISTEN; then
  echo "  WARNING: port 3001 already in use"
fi
if lsof -i :11434 2>/dev/null | grep -q LISTEN; then
  echo "  WARNING: port 11434 already in use (Ollama may already be running)"
fi

echo "[5/6] Ollama + IEMS up..."
cd ~/microgrid-manager && docker-compose up -d
sleep 15

echo "[6/6] Pull default model..."
docker exec ollama ollama pull mistral:7b || true

echo ""
echo "✅ IEMS stack is up."
echo "   IEMS UI:  http://localhost:3001/dashboard/iems"
echo "   API docs: http://localhost:8000/docs"
echo "   Kafka UI: http://localhost:8080"
