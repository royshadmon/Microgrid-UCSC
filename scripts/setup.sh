#!/usr/bin/env bash
# First time setup. Safe to run again at any time.
#   ./scripts/setup.sh
set -euo pipefail
source "$(dirname "$0")/_common.sh"

step "1. Docker"
need_docker
ok "Docker $(docker version --format '{{.Server.Version}}') with Compose $(docker compose version --short)"
arch=$(docker version --format '{{.Server.Arch}}'); ok "Docker engine architecture $arch"
mem=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
gb=$(( mem / 1024 / 1024 / 1024 ))
if [ "$gb" -lt 6 ]; then warn "Docker has ${gb} GB of memory. 8 GB or more is recommended (Docker Desktop, Settings, Resources)"; else ok "Docker has ${gb} GB of memory"; fi

step "2. Settings file"
if [ -f .env ]; then ok ".env already exists, leaving it as it is"
else cp .env.example .env; ok "created .env from .env.example"; fi

lic=$(envval ANYLOG_LICENSE)
if [ -z "$lic" ]; then
  if [ -t 0 ]; then
    echo
    echo "  The AnyLog nodes need a license key (see docs/guide/03_configure.md)."
    printf "  Paste it now and press Enter, or just press Enter to add it to .env later: "
    IFS= read -r lic || true
    if [ -n "$lic" ]; then
      python3 - "$lic" <<'PY' 2>/dev/null || { grep -v '^ANYLOG_LICENSE=' .env > .env.tmp; printf "ANYLOG_LICENSE='%s'\n" "$lic" >> .env.tmp; mv .env.tmp .env; }
import sys, re
lic = sys.argv[1].replace("'", "")
s = open(".env").read()
s = re.sub(r"(?m)^ANYLOG_LICENSE=.*$", lambda m: "ANYLOG_LICENSE='" + lic + "'", s)
open(".env", "w").write(s)
PY
      ok "license saved to .env"
    else warn "no license yet. Add ANYLOG_LICENSE to .env before ./scripts/start.sh"; fi
  else warn "ANYLOG_LICENSE is empty in .env. Add it before ./scripts/start.sh"; fi
else ok "ANYLOG_LICENSE is set"; fi

profiles=$(envval COMPOSE_PROFILES); ok "profiles to run: ${profiles:-none (core only)}"
if [[ ",$profiles," == *",live,"* ]]; then
  [ -n "$(envval EGAUGE_PASS)" ] || warn "profile live is on but EGAUGE_PASS is empty"
  [ -n "$(envval SA_BROKER)" ]  || warn "profile live is on but SA_BROKER is empty"
fi

step "3. Ports"
busy=0
for p in 5432 9092 9094 32048 32049 32148 32149 1883 \
         "$(envval DASHBOARD_PORT)" "$(envval BACKEND_PORT)" "$(envval OLLAMA_PORT)"; do
  [ -n "$p" ] || continue
  if port_busy "$p"; then
    if docker ps --format '{{.Ports}}' | grep -q ":$p->"; then warn "port $p is used by a container that is already running (fine if it is this stack)"
    else bad "port $p is already in use by another program"; busy=1; fi
  fi
done
[ "$busy" -eq 0 ] && ok "ports look free" || warn "free the ports above, or change the movable ones in section 7 of .env"

step "4. Download images (this takes a while the first time)"
if out=$(compose pull --ignore-buildable --quiet 2>&1); then ok "images ready"
else
  if printf '%s' "$out" | grep -q "anylog-network.*access denied\|access denied.*anylog"; then
    if docker image inspect "$(envval ANYLOG_IMAGE)" >/dev/null 2>&1; then ok "AnyLog image already on this computer"
    else bad "Docker Hub refused the AnyLog image. Run  docker login  with the account the AnyLog team gave you, then run setup again"; fi
  else printf '%s\n' "$out" | tail -5 | sed 's/^/  /'; warn "some images could not be pulled now, start will retry"; fi
fi

step "Done"
echo "  Next run  ./scripts/start.sh"
