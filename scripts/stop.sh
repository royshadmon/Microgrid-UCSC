#!/usr/bin/env bash
# Stop the stack.
#   ./scripts/stop.sh          stop, keep all data
#   ./scripts/stop.sh --wipe   stop and delete all data (database, AnyLog, Kafka, models in Ollama)
set -euo pipefail
source "$(dirname "$0")/_common.sh"
need_docker
if [ "${1:-}" = "--wipe" ]; then
  printf "  This deletes every stored reading and the downloaded language model. Type yes to continue: "
  read -r ans; [ "$ans" = "yes" ] || { echo "  nothing deleted"; exit 0; }
  compose --profile '*' down -v --remove-orphans
  ok "stopped and wiped"
else
  compose --profile '*' down --remove-orphans
  ok "stopped. Your data is kept, start again with ./scripts/start.sh"
fi
