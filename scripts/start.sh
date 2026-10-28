#!/usr/bin/env bash
# Build and start the stack, wait for it, and print the addresses.
#   ./scripts/start.sh            start or update everything
#   ./scripts/start.sh --no-build start without rebuilding the local images
set -euo pipefail
source "$(dirname "$0")/_common.sh"
need_docker
[ -f .env ] || die "no .env yet. Run ./scripts/setup.sh first"
[ -n "$(envval ANYLOG_LICENSE)" ] || die "ANYLOG_LICENSE is empty in .env. See docs/guide/03_configure.md"

build=--build; [ "${1:-}" = "--no-build" ] && build=

if [ -n "$build" ]; then
  step "1. Building the local images (5 to 15 minutes the first time, seconds after that)"
  compose build --quiet 2>&1 | sed 's/^/  /' || die "a build failed, see the messages above"
  ok "images built"
fi
step "2. Starting containers (profiles: $(envval COMPOSE_PROFILES))"
if ! compose up -d --quiet-pull 2>&1 | sed 's/^/  /'; then
  bad "docker compose up failed"
  echo "  If the message mentions anylogco/anylog-network and 'pull access denied', log in to"
  echo "  Docker Hub with the account the AnyLog team gave you:  docker login"
  exit 1
fi

step "3. Waiting for the AnyLog operator"
for i in $(seq 1 60); do
  if anylog 32149 "get status" | grep -qi running; then ok "operator answers on 32149"; break; fi
  [ "$i" -eq 60 ] && { bad "operator did not answer within 5 minutes"; echo "  look at  ./scripts/logs.sh operator1"; exit 1; }
  sleep 5
done
anylog 32049 "get status" | grep -qi running && ok "master answers on 32049" || warn "master is not answering yet"
# On a brand new install the operator policy is created during the first boot,
# after the step that declares the operator has already run. One restart fixes it.
op_running() { anylog 32149 "get processes" | grep -qE "Operator +\|Running"; }
sleep 10
if op_running; then ok "operator process is running"
else
  echo "  first start, restarting operator1 once so it picks up its new policy"
  compose restart operator1 >/dev/null
  for i in $(seq 1 30); do sleep 5; op_running && break; done
  op_running && ok "operator process is running" || warn "operator process is not running yet, see ./scripts/logs.sh operator1"
fi

step "4. Language model for Ask"
model=$(envval OLLAMA_MODEL); model=${model:-qwen2.5:1.5b-instruct}
if compose exec -T ollama ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$model"; then ok "$model is present"
else echo "  downloading $model (about 1 GB for the 1.5b model, once)"; compose exec -T ollama ollama pull "$model" && ok "$model downloaded"; fi

step "5. Dashboard"
dport=$(envval DASHBOARD_PORT); dport=${dport:-47821}
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$dport/" || true)
  [ "$code" = "200" ] && { ok "dashboard is up"; break; }
  sleep 3
done

bport=$(envval BACKEND_PORT); bport=${bport:-8009}
profiles=$(envval COMPOSE_PROFILES)
step "Ready"
echo "  Dashboard       http://localhost:$dport"
echo "  Engine API      http://localhost:$bport/docs"
echo "  AnyLog REST     http://localhost:32149"
[[ ",$profiles," == *",gui,"* ]]   && echo "  Remote GUI      http://localhost:$(envval GUI_PORT)"
[[ ",$profiles," == *",tools,"* ]] && echo "  Kafka UI        http://localhost:$(envval KAFKA_UI_PORT)"
echo
echo "  Appliance results need about 10 minutes of data before the first ones appear."
echo "  Check progress with  ./scripts/status.sh"
