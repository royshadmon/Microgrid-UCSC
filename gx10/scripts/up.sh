#!/usr/bin/env bash
# Build and start the GX10 stack in dependency order, then verify it.
#   bash gx10/scripts/up.sh                 # host Ollama serves Nemotron
#   PROFILES="ollama" bash gx10/scripts/up.sh
#   PROFILES="bridge" bash gx10/scripts/up.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
C=(docker compose -f gx10/docker-compose.gx10.yaml --env-file gx10/.env)
for p in ${PROFILES:-}; do C+=(--profile "$p"); done

echo "[up] 1/4 build the inference image first (iems-backend builds FROM it)"
"${C[@]}" build iems-inference
echo "[up] 2/4 build the rest"
"${C[@]}" build
echo "[up] 3/4 storage + AnyLog + Kafka"
"${C[@]}" up -d postgres master kafka
sleep 15
"${C[@]}" up -d operator1 kafka-ui
echo "      waiting for operator1 REST on :32149 ..."
for i in $(seq 1 60); do
  curl -s --max-time 3 -H "User-Agent: AnyLog/1.23" -H "command: get status" http://127.0.0.1:32149 \
    | grep -qi running && break
  sleep 5
done
echo "[up] 4/4 producers, inference, apps"
"${C[@]}" up -d
sleep 20
bash gx10/scripts/verify.sh || true
