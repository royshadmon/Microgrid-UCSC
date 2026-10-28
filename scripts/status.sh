#!/usr/bin/env bash
# Is everything running, and is data actually arriving?
#   ./scripts/status.sh
set -uo pipefail
source "$(dirname "$0")/_common.sh"
need_docker

step "Containers"
compose ps --format 'table {{.Name}}\t{{.State}}\t{{.Status}}' | sed 's/^/  /'

step "AnyLog nodes"
anylog 32049 "get status" | grep -qi running && ok "master" || bad "master not answering on 32049"
anylog 32149 "get status" | grep -qi running && ok "operator1" || bad "operator1 not answering on 32149"

step "Rows received in the last 2 minutes"
for t in energy_readings egauge_kafka solar_data nilm_disaggregated; do
  n=$(recent_rows "$t")
  if [ -n "$n" ] && [ "$n" -gt 0 ]; then ok "$(printf '%-20s %s' "$t" "$n")"
  else warn "$(printf '%-20s %s' "$t" "${n:-no table yet}")"; fi
done
echo "  Expected in 2 minutes. energy_readings and egauge_kafka about 320 in demo mode or 1,900 with a"
echo "  real meter, solar_data 4 to 24, nilm_disaggregated about 90 once 10 minutes of data exist."

step "Engine and dashboard"
bport=$(envval BACKEND_PORT); bport=${bport:-8009}; dport=$(envval DASHBOARD_PORT); dport=${dport:-47821}
curl -sf --max-time 10 "http://127.0.0.1:$bport/" >/dev/null && ok "engine on $bport" || bad "engine not answering on $bport"
curl -s --max-time 20 "http://127.0.0.1:$bport/iems/ask/health" | grep -q '"model_present":true' && ok "Ask model loaded" || warn "Ask model not ready (run ./scripts/start.sh again)"
curl -sf --max-time 10 -o /dev/null "http://127.0.0.1:$dport/" && ok "dashboard on $dport" || bad "dashboard not answering on $dport"
