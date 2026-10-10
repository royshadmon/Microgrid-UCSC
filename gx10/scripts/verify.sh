#!/usr/bin/env bash
# End-to-end health of the GX10 stack. Exit code = number of failed checks.
set -uo pipefail
cd "$(dirname "$0")/../.."
F=0
ok()  { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; F=$((F+1)); }
al()  { curl -s --max-time 20 http://127.0.0.1:32149 -H "User-Agent: AnyLog/1.23" \
          -H "destination: network" -H "command: sql customers format=json and stat=false \"$1\""; }

echo "== replay producer"
s=$(curl -s --max-time 3 http://127.0.0.1:8099/status) && ok "$(echo "$s" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["source"],"x"+str(d["speed"]),"source",d["source_time_local"][:19],"sent",d["sent"])')" || bad "replay control API :8099"

echo "== AnyLog operator"
curl -s --max-time 5 -H "User-Agent: AnyLog/1.23" -H "command: get status" http://127.0.0.1:32149 | grep -qi running \
  && ok "operator1 running" || bad "operator1 REST :32149"
for t in energy_readings egauge_kafka solar_data nilm_disaggregated; do
  n=$(al "select count(*) as n from $t where insert_timestamp >= NOW() - 5 minutes" | grep -o '"n": *[0-9]*' | grep -o '[0-9]*$')
  [ "${n:-0}" -gt 0 ] && ok "$t: $n rows in the last 5 min" || bad "$t: no rows in the last 5 min"
done
h=$(al "select count(distinct appliance) as h from nilm_disaggregated where insert_timestamp >= NOW() - 5 minutes" | grep -o '"h": *[0-9]*' | grep -o '[0-9]*$')
[ "${h:-0}" -ge 22 ] && ok "inference emitting $h heads (expect 22)" || bad "inference emitting ${h:-0} heads (expect 22; first tick lands ~30 s after start)"

echo "== models loaded by iems-inference"
docker exec iems-inference python3 -c "
import json,glob
for f in sorted(glob.glob('/app/services/iems/models/panel?_norm_bilstm.json')):
    d=json.load(open(f)); print('  ', f.rsplit('/',1)[1], len(d['features']), 'features', len(d['heads']), 'heads')
" 2>/dev/null || bad "cannot read models in iems-inference"

echo "== apps"
for u in "http://127.0.0.1:8009/iems/health iems-backend" "http://127.0.0.1:47821/api/nilm iems-dashboard" \
         "http://127.0.0.1:3001/ remote-gui" "http://127.0.0.1:8000/docs remote-gui-api"; do
  set -- $u; code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1")
  [ "$code" = 200 ] && ok "$2 $1" || bad "$2 $1 -> $code"
done

echo "== LLM"
llm=$(grep '^LLM_URL=' gx10/.env 2>/dev/null | cut -d= -f2-); llm=${llm:-http://127.0.0.1:11434}
llm=${llm/host.docker.internal/127.0.0.1}
model=$(grep '^LLM_MODEL=' gx10/.env 2>/dev/null | cut -d= -f2-); model=${model:-nemotron-3.5-lightning}
curl -s --max-time 5 "$llm/api/tags" | grep -q "${model%%:*}" && ok "$model listed at $llm" || bad "$model not listed at $llm"
t0=$(date +%s%N)
a=$(curl -s --max-time 120 "$llm/api/chat" -d "{\"model\":\"$model\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word ready.\"}]}" \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["message"]["content"].strip()[:60])' 2>/dev/null)
[ -n "$a" ] && ok "chat round trip $(( ($(date +%s%N) - t0) / 1000000 )) ms: $a" || bad "chat round trip failed"

echo; [ $F -eq 0 ] && echo "verify: all checks passed" || echo "verify: $F check(s) failed"
exit $F
