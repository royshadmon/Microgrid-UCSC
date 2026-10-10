#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# bootstrap_gx10.sh  One-time checks and prep on a fresh ASUS Ascent GX10.
#
# Read-only except for: creating gx10/.env from the example, adding the user
# to the docker group (with your OK), and docker-loading the AnyLog arm64
# image if the tar is present. Re-run any time; it only reports.
# ---------------------------------------------------------------------------
set -uo pipefail
cd "$(dirname "$0")/../.."
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILS=$((FAILS+1)); }
FAILS=0

echo "== Hardware / OS"
[ "$(uname -m)" = "aarch64" ] && ok "arm64 (aarch64)" || warn "arch is $(uname -m), this guide targets the GX10's aarch64"
. /etc/os-release 2>/dev/null && ok "$PRETTY_NAME"
if command -v nvidia-smi >/dev/null; then
  ok "GPU: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1)"
else bad "nvidia-smi not found (DGX OS ships it; reinstall the NVIDIA driver stack)"; fi
mem=$(awk '/MemTotal/{printf "%d", $2/1048576}' /proc/meminfo); ok "unified memory ${mem} GiB"
free_gb=$(df -BG --output=avail . | tail -1 | tr -dc 0-9)
[ "${free_gb:-0}" -ge 80 ] && ok "disk free ${free_gb} GB" || warn "disk free ${free_gb} GB; images + Nemotron + data want ~80 GB"

echo "== Docker"
if docker info >/dev/null 2>&1; then ok "docker reachable as $(id -un)"
elif sudo -n docker info >/dev/null 2>&1; then
  warn "docker needs sudo. Fix once:  sudo usermod -aG docker \$USER && newgrp docker"
else bad "docker not reachable"; fi
docker compose version >/dev/null 2>&1 && ok "$(docker compose version)" || bad "docker compose v2 missing"
if docker info 2>/dev/null | grep -qi 'nvidia'; then ok "NVIDIA container runtime registered"
else warn "nvidia runtime not listed; run: sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"; fi

echo "== Network"
if command -v tailscale >/dev/null; then
  ts=$(tailscale status --self --peers=false 2>/dev/null | head -1)
  [ -n "$ts" ] && ok "tailscale: $ts" || warn "tailscale installed but not logged in (sudo tailscale up)"
  tailscale ping -c 1 --timeout 5s 100.119.235.24 >/dev/null 2>&1 \
    && ok "Pat's box 100.119.235.24 reachable" || warn "Pat's box not reachable over Tailscale (only needed to export data)"
else warn "tailscale not installed (only needed to export data): curl -fsSL https://tailscale.com/install.sh | sh"; fi

echo "== Local LLM (Nemotron 3.5 Lightning)"
tags=$(curl -s --max-time 3 http://127.0.0.1:11434/api/tags || true)
if [ -n "$tags" ]; then
  if echo "$tags" | grep -qi nemotron; then ok "Ollama on :11434 serves: $(echo "$tags" | grep -o '"name":"[^"]*nemotron[^"]*"' | head -3 | tr '\n' ' ')"
  else warn "Ollama on :11434 has no nemotron model. Pull it: ollama pull nemotron-3.5-lightning"; fi
  if ss -ltn 2>/dev/null | grep -q '127.0.0.1:11434'; then
    warn "host Ollama listens on 127.0.0.1 only; containers cannot reach it. See gx10/README.md step 4 (OLLAMA_HOST=0.0.0.0)"
  fi
else
  for p in 8000 8010; do
    if curl -s --max-time 3 "http://127.0.0.1:$p/v1/models" | grep -qi nemotron; then
      ok "OpenAI-compatible Nemotron on :$p (use --profile bridge)"
      [ "$p" = 8000 ] && warn ":8000 collides with iems-app; restart the NIM on -p 8010:8000"
    fi
  done
  warn "no Ollama on :11434; use --profile ollama or --profile bridge (README step 4)"
fi

echo "== Repo inputs"
[ -f gx10/.env ] && ok "gx10/.env present" || { cp gx10/.env.example gx10/.env; warn "created gx10/.env from the example; set ANYLOG_LICENSE"; }
grep -q '^ANYLOG_LICENSE=..' gx10/.env && ok "ANYLOG_LICENSE set" || bad "ANYLOG_LICENSE empty in gx10/.env (copy it from Pat's .env)"
img=$(grep '^ANYLOG_IMAGE=' gx10/.env | cut -d= -f2-); img=${img:-anylogco/anylog-network:local-nuitka-arm}
if docker image inspect "$img" >/dev/null 2>&1; then ok "AnyLog image $img loaded"
else
  tar=$(ls AnyLog-latest-arm.tar gx10/data/AnyLog-latest-arm.tar 2>/dev/null | head -1)
  if [ -n "$tar" ]; then echo "  loading $tar ..."; docker load -i "$tar" && ok "loaded $img"
  else bad "AnyLog arm64 image $img missing. Copy AnyLog-latest-arm.tar from the Mac and re-run"; fi
fi
n6=$(ls gx10/data/export/egauge_6s 2>/dev/null | wc -l); n1=$(ls gx10/data/export/egauge_1s 2>/dev/null | wc -l)
[ "$n6" -gt 0 ] && ok "export: $n6 training days, $n1 replay days" || warn "no export yet (gx10/scripts/export_pat_data.sh); replay will run synthetic"
python3 -c "import json;d=json.load(open('services/iems/models/panel3_norm_bilstm.json'));print(len(d['features']))" 2>/dev/null \
  | grep -q '^18$' && ok "services/iems/models carries the 18 feature set" || warn "models are not the 18 feature set"

echo
[ $FAILS -eq 0 ] && echo "bootstrap: ready. Next: bash gx10/scripts/up.sh" || echo "bootstrap: $FAILS blocking item(s) above"
exit $FAILS
