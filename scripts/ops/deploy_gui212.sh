#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Swap iems-app onto the IEMS overlay of AnyLog remote-gui 2.1.2-beta.
#
# Touches exactly two services: iems-app, and iems-backend (only to bring the
# hand-started IEMS engine container under compose so it survives a restart).
# master, operator1, postgres, kafka, the producers, iems-inference and
# iems-dashboard are never named and never stopped.
#
# Two rules this script exists to obey, both learned the hard way on this host:
#
#   1. Never run `docker compose down`.  Every service here shares ONE compose
#      file, so a bare `down` stops the whole stack including both AnyLog
#      nodes.  Always `up -d --no-deps <service>`.
#   2. Verify the success condition, never the absence of a known failure
#      string.  A check that greps for a failure it has seen before passes on
#      every failure it has not.
#
# Usage:
#   sudo bash deploy_gui212.sh
#   sudo bash deploy_gui212.sh --rollback <stamp>
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

IMAGE_NEW="${IMAGE_NEW:-iems-remote-gui:2.1.2-beta}"
SERVICE="iems-app"
BACKUP_ROOT="/home/microgrid/.gui_backups"
BE_PORT="${BE_PORT:-8000}"
FE_PORT="${FE_PORT:-3001}"
STAMP="$(date +%Y%m%d_%H%M%S)"

hdr() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '  [ok]   %s\n' "$*"; }
bad() { printf '  [FAIL] %s\n' "$*"; }
inf() { printf '         %s\n' "$*"; }
die() { printf '\nABORT: %s\n' "$*" >&2; exit 1; }

# ── discovery ────────────────────────────────────────────────────────────────
hdr "discover"
CF="$(docker inspect "$SERVICE" \
      --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' \
      2>/dev/null | cut -d, -f1)"
[ -n "$CF" ] && [ -f "$CF" ] || die "could not read $SERVICE's compose file from its labels"
WD="$(dirname "$CF")"
ok "compose: $CF"

CUR_IMAGE="$(docker inspect "$SERVICE" --format '{{.Config.Image}}' 2>/dev/null)"
ok "current image: $CUR_IMAGE"

# Every service in that file, so we can prove afterwards that we only touched
# the ones we meant to.
mapfile -t ALL_SERVICES < <(cd "$WD" && docker compose -f "$CF" config --services 2>/dev/null | sort)
[ "${#ALL_SERVICES[@]}" -gt 0 ] || die "compose file lists no services -- refusing to touch it"
inf "services in this file: ${ALL_SERVICES[*]}"

# ── rollback ─────────────────────────────────────────────────────────────────
# Placed before the deploy flow on purpose: an earlier version of this script
# had the handler at the bottom, where it ran the whole upgrade first.
if [ "${1:-}" = "--rollback" ]; then
  RB="${2:-}"
  [ -n "$RB" ] || die "usage: $0 --rollback <stamp>"
  DIR="$BACKUP_ROOT/gui212_$RB"
  [ -d "$DIR" ] || die "no backup at $DIR"
  hdr "rollback $RB"
  cp -a "$DIR/$(basename "$CF")" "$CF" || die "could not restore compose file"
  ok "compose file restored from $DIR"
  ( cd "$WD" && docker compose -f "$CF" up -d --no-deps "$SERVICE" ) \
    || die "compose up failed during rollback"
  ok "$SERVICE recreated from the restored file"
  docker ps --filter "name=$SERVICE" --format '  {{.Names}} {{.Image}} {{.Status}}'
  exit 0
fi

# ── preconditions ────────────────────────────────────────────────────────────
hdr "preconditions"
docker image inspect "$IMAGE_NEW" >/dev/null 2>&1 \
  || die "image $IMAGE_NEW is not present -- build it first"
ok "image present: $IMAGE_NEW"

# The plugin proxies to these two; if they are not answering, the new page
# would come up empty and look like the deploy broke it.
for probe in "IEMS engine|http://localhost:8009/iems/health" \
             "IEMS dashboard|http://localhost:47821/api/sources"; do
  name="${probe%%|*}"; url="${probe##*|}"
  if curl -sf -m 60 "$url" >/dev/null 2>&1; then
    ok "$name reachable"
  else
    die "$name is not answering at $url -- fix that before swapping the GUI"
  fi
done

# Capture the CURRENT route surface so we can prove no upstream router was lost.
BEFORE_ROUTES="/tmp/gui212_routes_before_$STAMP.txt"
curl -sf -m 60 "http://localhost:$BE_PORT/openapi.json" 2>/dev/null \
  | python3 -c 'import sys,json;[print(p) for p in sorted(json.load(sys.stdin)["paths"])]' \
  > "$BEFORE_ROUTES" 2>/dev/null
BEFORE_N="$(wc -l < "$BEFORE_ROUTES" 2>/dev/null || echo 0)"
[ "$BEFORE_N" -gt 0 ] || die "could not read the current route list from :$BE_PORT"
ok "current backend exposes $BEFORE_N routes (recorded)"

# ── backup ───────────────────────────────────────────────────────────────────
hdr "backup"
DIR="$BACKUP_ROOT/gui212_$STAMP"
mkdir -p "$DIR" || die "could not create $DIR"
cp -a "$CF" "$DIR/" || die "could not back up the compose file"
cp -a "$BEFORE_ROUTES" "$DIR/routes_before.txt"
{
  echo "stamp=$STAMP"
  echo "compose=$CF"
  echo "previous_image=$CUR_IMAGE"
  echo "new_image=$IMAGE_NEW"
} > "$DIR/manifest.txt"
ok "backup: $DIR"

# ── rewrite compose ──────────────────────────────────────────────────────────
hdr "rewrite compose"
python3 - "$CF" "$IMAGE_NEW" "$SERVICE" <<'PYEOF' || die "compose rewrite failed"
import io, re, sys

path, image, service = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path).read()
lines = src.split("\n")

def service_span(name):
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^  %s:\s*$" % re.escape(name), ln):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln.strip() and not ln.startswith("   ") and not ln.startswith("\t"):
            end = j
            break
    return start, end

span = service_span(service)
if not span:
    sys.exit("service '%s' not found in %s" % (service, path))
s, e = span
block = lines[s:e]

# image
changed_image = False
for i, ln in enumerate(block):
    if re.match(r"^    image:\s", ln):
        block[i] = "    image: %s" % image
        changed_image = True
        break
if not changed_image:
    block.insert(1, "    image: %s" % image)

# a build: stanza would shadow the image, so drop it if present
out, skip = [], False
for ln in block:
    if re.match(r"^    build:\s*$", ln) or re.match(r"^    build:\s+\S", ln):
        skip = True
        continue
    if skip:
        if re.match(r"^      \S", ln):
            continue
        skip = False
    out.append(ln)
block = out

# environment: point the plugin at the engine and the dashboard
env_idx = None
for i, ln in enumerate(block):
    if re.match(r"^    environment:\s*$", ln):
        env_idx = i
        break
if env_idx is None:
    block.append("    environment:")
    env_idx = len(block) - 1
have = "\n".join(block)
add = []
if "IEMS_BACKEND_URL" not in have:
    add.append('      IEMS_BACKEND_URL: "http://host.docker.internal:8009"')
if "IEMS_DASH_URL" not in have:
    add.append('      IEMS_DASH_URL: "http://host.docker.internal:47821"')
block = block[:env_idx + 1] + add + block[env_idx + 1:]

lines = lines[:s] + block + lines[e:]
new = "\n".join(lines)

# sanity: still valid YAML, and the same set of services
try:
    import yaml
    before = yaml.safe_load(src)
    after = yaml.safe_load(new)
except Exception as exc:
    sys.exit("could not parse compose YAML: %s" % exc)

if set(before["services"]) != set(after["services"]):
    sys.exit("service set changed: %s -> %s"
             % (sorted(before["services"]), sorted(after["services"])))
if after["services"][service].get("image") != image:
    sys.exit("image was not applied")
if "build" in after["services"][service]:
    sys.exit("a build stanza survived and would shadow the image")

open(path, "w").write(new)
print("  [ok]   %s image -> %s" % (service, image))
print("  [ok]   %d services intact: %s"
      % (len(after["services"]), ", ".join(sorted(after["services"]))))
PYEOF

grep -q "$IMAGE_NEW" "$CF" || die "new image tag is not in the compose file after the rewrite"
grep -q "$CUR_IMAGE" "$CF" && inf "note: previous image string still appears elsewhere in the file"
ok "compose rewritten"

# ── swap ─────────────────────────────────────────────────────────────────────
hdr "swap $SERVICE"
inf "compose up -d --no-deps $SERVICE   (no other service is named)"
( cd "$WD" && docker compose -f "$CF" up -d --no-deps "$SERVICE" ) || {
  bad "compose up failed -- restoring the previous compose file"
  cp -a "$DIR/$(basename "$CF")" "$CF"
  ( cd "$WD" && docker compose -f "$CF" up -d --no-deps "$SERVICE" )
  die "swap failed and was rolled back"
}
ok "$SERVICE recreated"

# ── verify ───────────────────────────────────────────────────────────────────
hdr "verify"

# The first request into the plugin warms a cold import chain, so poll for the
# success condition instead of sampling once and calling it dead.
AFTER_ROUTES="/tmp/gui212_routes_after_$STAMP.txt"
got=0
for i in $(seq 1 20); do
  sleep 6
  if curl -sf -m 30 "http://localhost:$BE_PORT/openapi.json" 2>/dev/null \
     | python3 -c 'import sys,json;[print(p) for p in sorted(json.load(sys.stdin)["paths"])]' \
     > "$AFTER_ROUTES" 2>/dev/null && [ -s "$AFTER_ROUTES" ]; then
    got=1; break
  fi
  printf '.'
done
printf '\n'
[ "$got" = 1 ] || die "backend never served /openapi.json on :$BE_PORT after the swap"

AFTER_N="$(wc -l < "$AFTER_ROUTES")"
# comm compares by the locale's collation, which does not match the byte order
# python's sorted() produced -- it warned "file 2 is not in sorted order" and
# its answer could not be trusted.  Do the set difference where the data is.
LOST="$(python3 -c '
import sys
before = set(open(sys.argv[1]).read().split())
after = set(open(sys.argv[2]).read().split())
print("\n".join(sorted(before - after)))
' "$BEFORE_ROUTES" "$AFTER_ROUTES")"
if [ -n "$LOST" ]; then
  bad "routes present before the swap and missing after:"
  echo "$LOST" | sed 's/^/           /'
  die "an upstream router was lost -- roll back with: $0 --rollback $STAMP"
fi
ok "all $BEFORE_N pre-existing routes still registered (now $AFTER_N)"

IEMS_N="$(grep -c '^/iems' "$AFTER_ROUTES" || true)"
[ "${IEMS_N:-0}" -ge 20 ] \
  || die "only ${IEMS_N:-0} /iems routes registered -- expected the full plugin surface"
ok "$IEMS_N /iems routes registered"

if curl -sf -m 30 "http://localhost:$BE_PORT/plugins/order" 2>/dev/null | grep -q '"iems"'; then
  ok "iems listed in /plugins/order"
else
  die "iems is not in /plugins/order -- plugin_order merge did not take"
fi

# feature_config gates the backend plugin, and a plugin missing from it loads
# silently and 404s on every route.  Assert it positively.
if curl -sf -m 30 "http://localhost:$BE_PORT/feature-config" 2>/dev/null | grep -q '"iems"'; then
  ok "iems enabled in feature-config"
else
  die "iems is absent from feature-config -- every /iems route would 404"
fi

for probe in "engine health|/iems/health|anylog" \
             "dashboard feed|/iems/dash/api/sources|anylog" \
             "live NILM|/iems/nilm/recent?minutes=5|" \
             "ONNX snapshot|/iems/onnx/snapshot|"; do
  name="${probe%%|*}"; rest="${probe#*|}"; url="${rest%%|*}"; want="${rest##*|}"
  body="$(curl -sf -m 90 "http://localhost:$BE_PORT$url" 2>/dev/null)"
  if [ -z "$body" ]; then
    bad "$name: no response from $url"
  elif [ -n "$want" ] && ! printf '%s' "$body" | grep -q "$want"; then
    bad "$name: response did not contain '$want'"
    inf "$(printf '%s' "$body" | head -c 200)"
  else
    ok "$name: $(printf '%s' "$body" | wc -c) bytes from $url"
  fi
done

# Frontend: the Vite bundle must actually contain the compiled IEMS page.
FE_HTML="$(curl -sf -m 30 "http://localhost:$FE_PORT/" 2>/dev/null)"
ASSET="$(printf '%s' "$FE_HTML" | grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' | head -1)"
if [ -n "$ASSET" ]; then
  ok "frontend serving the Vite build ($ASSET)"
  # Download first, then search.  Piping a 3.7 MB bundle into `grep -q` makes
  # grep exit on the first match and close the pipe, curl takes SIGPIPE, and
  # the pipeline reports failure on a bundle that actually matched.
  BUNDLE="/tmp/gui212_bundle_$STAMP.js"
  if curl -sf -m 90 -o "$BUNDLE" "http://localhost:$FE_PORT$ASSET" 2>/dev/null \
     && [ -s "$BUNDLE" ]; then
    HITS="$(grep -c 'iems-dash-root' "$BUNDLE" || true)"
    if [ "${HITS:-0}" -gt 0 ]; then
      ok "IEMS page is compiled into the bundle ($(wc -c < "$BUNDLE") bytes)"
    else
      bad "bundle does not contain the IEMS page"
    fi
    rm -f "$BUNDLE"
  else
    bad "could not download $ASSET to check it"
  fi
else
  bad "frontend on :$FE_PORT is not serving a Vite build"
fi

# ── prove nothing else moved ─────────────────────────────────────────────────
hdr "everything else"
for svc in "${ALL_SERVICES[@]}"; do
  [ "$svc" = "$SERVICE" ] && continue
  cname="$(cd "$WD" && docker compose -f "$CF" ps -q "$svc" 2>/dev/null)"
  if [ -z "$cname" ]; then
    inf "$svc: not running (was it running before? this script never stopped it)"
    continue
  fi
  st="$(docker inspect "$cname" --format '{{.State.Status}} up {{.State.StartedAt}}' 2>/dev/null)"
  inf "$(printf '%-18s %s' "$svc" "$st")"
done

hdr "done"
echo "  new image : $IMAGE_NEW"
echo "  backup    : $DIR"
echo "  rollback  : sudo bash $0 --rollback $STAMP"
