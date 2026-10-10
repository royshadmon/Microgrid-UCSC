#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# export_pat_data.sh  Pull real house data + the deployed models off Pat's box.
#
# Run on the GX10 (or the Mac) while it is on the tailnet. It uploads
# pat_export_remote.sh, runs it on Pat's box against the production Postgres,
# then rsyncs the result to gx10/data/export/. Re-running only fetches days
# that are not already exported.
#
#   PAT=microgrid@100.119.235.24   ssh target (default)
#   START=2026-08-18 END=2026-10-10 REPLAY_DAYS=3 TABLE=egauge_kafka
#
#   bash gx10/scripts/export_pat_data.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/../.."

PAT="${PAT:-microgrid@100.119.235.24}"
DEST="${DEST:-gx10/data/export}"
SSH_OPTS=(-o ServerAliveInterval=30 -o ServerAliveCountMax=10)
mkdir -p "$DEST"

echo "[export] reaching $PAT over Tailscale ..."
ssh "${SSH_OPTS[@]}" -o ConnectTimeout=15 "$PAT" 'hostname' \
  || { echo "cannot ssh to $PAT. Is this machine on the tailnet? (tailscale status)"; exit 1; }

ssh "${SSH_OPTS[@]}" "$PAT" 'cat > ~/gx10_export_remote.sh && chmod +x ~/gx10_export_remote.sh' \
  < gx10/scripts/pat_export_remote.sh

# docker on Pat's box needs sudo for the microgrid user. The password goes over
# stdin, never onto a command line.
if [ -z "${SUDO_PASS:-}" ]; then
  read -r -s -p "sudo password for ${PAT%@*} on Pat's box (Enter if not needed): " SUDO_PASS; echo
fi

ENVS="START='${START:-}' END='${END:-}' REPLAY_DAYS='${REPLAY_DAYS:-3}' TABLE='${TABLE:-egauge_kafka}'"
printf '%s\n' "$SUDO_PASS" | ssh "${SSH_OPTS[@]}" "$PAT" \
  "read -r SUDO_PASS; export SUDO_PASS; $ENVS bash ~/gx10_export_remote.sh 2>&1 | grep -v '^\[sudo\]'"

echo "[export] copying to $DEST ..."
rsync -az --partial -e "ssh -o ServerAliveInterval=30" "$PAT:gx10_export/" "$DEST/"
echo "[export] $(ls "$DEST/egauge_6s" | wc -l) training days, $(ls "$DEST/egauge_1s" 2>/dev/null | wc -l) replay days"
( cd "$DEST" && grep -E '^[0-9a-f]{32}' MANIFEST.txt | md5sum -c --quiet ) && echo "[export] checksums OK"
