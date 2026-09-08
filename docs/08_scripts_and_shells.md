# Scripts and shells

Three groups. Scripts that run on Pat's box, scripts that run on the dev Mac and
drive Pat's box over SSH, and Python entry points.

Two rules every deploy script on this host obeys, both learned the hard way and
both written into `deploy_gui212.sh`.

```
1. Never run `docker compose down`. Twelve services share ONE compose file, so a
   bare `down` stops the whole stack including both AnyLog nodes. Always
   `up -d --no-deps <service>`.
2. Verify the success condition, never the absence of a known failure string. A
   check that greps for a failure it has seen before passes on every failure it
   has not.
```

---

## Runs on Pat's box

These live in `~microgrid/`, not in the deployment root.

### `~/deploy_gui212.sh`

The production GUI deploy. `sudo bash ~/deploy_gui212.sh`, or
`sudo bash ~/deploy_gui212.sh --rollback <stamp>`.

Touches exactly `iems-app`. `master`, `operator1`, `postgres`, `kafka`, the
producers, `iems-inference` and `iems-dashboard` are never named and never
stopped.

```bash
IMAGE_NEW="${IMAGE_NEW:-iems-remote-gui:2.1.2-beta}"   # override for GA
SERVICE="iems-app"
BACKUP_ROOT="/home/microgrid/.gui_backups"
BE_PORT="${BE_PORT:-8000}"
FE_PORT="${FE_PORT:-3001}"
STAMP="$(date +%Y%m%d_%H%M%S)"
```

Discovery is label driven, never assumed.

```bash
CF="$(docker inspect "$SERVICE" \
      --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' \
      | cut -d, -f1)"
[ -n "$CF" ] && [ -f "$CF" ] || die "could not read $SERVICE's compose file from its labels"
WD="$(dirname "$CF")"
```

The compose footprint of the whole change is four lines.

```diff
   iems-app:
-    image: anylogco/remote-gui:2.1.1-beta
+    image: iems-remote-gui:2.1.2
     environment:
+      IEMS_BACKEND_URL: "http://host.docker.internal:8009"
+      IEMS_DASH_URL: "http://host.docker.internal:47821"
```

Its own verification checks that all pre-existing routes still register, that the
`/iems` routes are present, that IEMS is in the plugin order and enabled in the
feature config, that engine health, the dashboard feed, NILM and the ONNX
snapshot all answer, and that the IEMS page is compiled into the bundle.

There is a router shadow check. If the compose bind-mounts its own
`iems_router.py`, that file shadows the router baked into the image, and the new
`IemsPage.js` calls routes an older router lacks, so those tiles would 404 while
the rest of the page works. The script stops and asks rather than half-breaking
the page.

`--no-deps` on the restart is mandatory. Without it compose tries to recreate
postgres and kafka and dies on a container name conflict.

Backups land in `~/.gui_backups/gui212_<stamp>/` with the compose file, the
previous route list and a manifest. Last known good stamp is `20260901_155124`.

Two verification bugs this script exists to avoid. `comm -23` compared two route
lists under the locale's collation, printed "file 2 is not in sorted order", and
its answer could not be trusted, so route comparison is now a Python set
difference. And `curl … | grep -q` reported the IEMS page missing from a 3.7 MB
bundle that contained it 198 times, because `grep -q` exits on first match and
closes the pipe, curl takes SIGPIPE and the pipeline reports failure. It now
downloads first and greps the file.

### `~/deploy_anylog20.sh`

The AnyLog major version upgrade, written to the same conventions.

```
Step 0  licence gate.  Boots a throwaway container on port 42049 with the node's
        own LICENSE_KEY and aborts if `get license` reports the key is missing.
        Nothing real is touched before this passes.
Step 1  backup.  Every volume of every discovered master/operator container plus
        their compose files, to ~/.anylog_backups/anylog20_<stamp>/. Refuses to
        continue if any backup fails.
Step 2  upgrade.  Swaps the image tag in each container's ACTUAL compose file,
        read from the com.docker.compose.project.config_files label.
Step 3  verify.  Version, licence, per-node status, then `get streaming` so a
        silent data stop is visible immediately.
--rollback <stamp>  restores compose files and every volume tarball.
```

Two bugs in an early version of step 2 took the whole stack down on 2026-08-17
and both are worth carrying forward.

`( cd "$wd" && docker compose -f "$cf" down )` stopped one node on the dev Mac,
where master and operator1 have separate compose files, and stopped **all twelve
services** on Pat's box, where they share one. The discovery step had printed the
same compose path for both nodes and that signal was not acted on. The fix is
`docker compose stop <svc>` and `rm -f <svc>`, then `up -d --no-deps <svc>`.

And the local scripts seed container ran as `anylog`, uid 10001, and could not
write the volume. `cp` exited 0 while copying nothing, so the `&& ok / || bad`
idiom did not detect the failure. It needs `--user root`.

The recovery detail that cost the most time. Docker only auto-seeds a named
volume from the image when Docker itself creates that volume. A pre-created empty
volume is mounted as is, so `operator1` booted with an empty
`/app/deployment-scripts`, found no `main.al`, and idled with its port closed.

### `~/iems_grafana/remote_grafana_fix.sh`

Runs on the host with sudo. Removes root owned leftovers Docker created when an
earlier compose pointed at a path that did not exist, deletes AppleDouble `._*`
files, fixes ownership and modes, recreates `iems-grafana`, polls
`localhost:3000/api/health` for up to 180 s, and verifies the provisioning
directories are readable **inside** the container.

### `~/rolling-deploy/deploy_rolling.sh`

Writes the eighteen feature model set onto `services/iems/models/` on the
deployment root and backs up to `$REPO/.deploy_backups/rolling_<stamp>/`. Four
stamps present, newest `rolling_20260810_155421`. **On its own this does not
change what is running.** Nothing bind mounts that directory, so the models take
effect only when `iems-inference` is rebuilt from that tree. See
`04_training_pipeline.md`. `~/rolling-deploy/fix_ha_token.sh` alongside it is
redundant since the token bind mount, kept as a fallback if the compose file is
restored from a pre-2026-08-31 backup.

### `scripts/start.sh`, `start_all.sh`, `stop.sh`

Written for the split compose layout, where `master` and `operator1` have
separate compose files under `~/docker-compose/docker-makefiles/docker-compose-files`
and Kafka lives in `~/kafka-egauge-pipeline`. **That is the dev Mac layout, not
Pat's box.** On Pat's box everything is one compose file and these are not the
bring-up path.

`start.sh` is six ordered phases with a health gate between each.

```
[1/6] AnyLog master        up -d, 5 s settle
[2/6] AnyLog operator1     up -d, poll `get status` for up to 50 s, then verify
                           Operator, Streamer and Kafka Consumer are all Running
[3/6] Kafka + eGauge       docker compose -f docker-compose.kafka.yml up -d
[4/6] Ollama + iems-app    root compose up -d, poll /iems/health for '"anylog":true'
                           for up to 60 s, warn if Ollama has no models
[5/6] Node dashboard       pkill stale server.js, nohup restart, wait for /api/health
[6/6] Data-flow check      inline Python opens a raw socket to :32149 and counts
                           egauge_kafka rows in the last 2 minutes
```

Helpers, and the AnyLog call pattern every script on this project reuses.

```bash
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

anylog_get() {
  curl -s --max-time 8 http://127.0.0.1:32149 \
    -H "User-Agent: AnyLog/1.23" -H "command: $1" 2>/dev/null
}
anylog_post() {
  curl -sf --max-time 8 http://127.0.0.1:32149 \
    -H "User-Agent: AnyLog/1.23" -X POST -H "command: $1" > /dev/null 2>&1
}
```

Two things to know before reusing it. Phase 6 hard codes a `d14` partition name,
`par_egauge_kafka_2026_05_00_d14_insert_timestamp`, which is from the fourteen
day era and will not match monthly partitions. And phase 5 starts the dashboard
as a bare `node` process rather than the container, which is correct for the dev
Mac and wrong for Pat's box.

`start_all.sh` is the older flow. Its one genuinely useful piece is that it
re-registers the Kafka consumer if `get msg client` does not already mention
`egauge-energy`, with the full `run kafka consumer` command inline.

`stop.sh` mirrors `start.sh` and deliberately leaves `postgres1` running, because
it has no restart dependency.

---

## Run on the dev Mac, drive Pat's box

Every one of these shares the same SSH preamble, because the Tailscale path
intermittently returns "Can't assign requested address" and each retries between
twenty and forty times.

```bash
TARGET=microgrid@100.119.235.24
CM="-o ControlMaster=auto -o ControlPath=$HOME/.ssh/cm_pat.sock \
    -o ControlPersist=300s -o ConnectTimeout=8 -o ServerAliveInterval=15"
mkdir -p "$HOME/.ssh"
```

| script | what it does |
|---|---|
| `deploy2.sh` | scp `./server.js` to `/tmp/dash_server.js`, `docker cp` into `iems-dashboard`, restart, print the HTTP code from `localhost:47821/`. Prompts for sudo once |
| `deploy_dashboard.sh` | deploy only, assuming the file is already at `/tmp/dash_server.js`. Discovers the container by `docker ps \| grep -i dash`, backs the existing `/app/server.js` up to `/tmp/dash_server.bak_<epoch>` first, then checks both `/` and `/api/sources` |
| `fix_and_verify.sh` | deploy then run an inline Python summary of `/api/sources`, printing AnyLog rows in 30 min, Solar Assistant age and SOC, Home Assistant mode and temperatures, engine URL, and per panel OK or STALE with age and 30 minute sample count |
| `diag_sources.sh` | no deploy. `docker ps` plus pretty printed `/api/sources` and `/api/health` |
| `verify.sh` | no sudo, no deploy, no `docker ps`. Just the two endpoints, with longer timeouts |
| `deploy_grafana.sh` | four steps. Ship `grafana/` and `server.js` to `/home/microgrid/iems_grafana`, `docker cp` the dashboard server and restart, verify the seven `/api/grafana/{tiles,power,solar,status,nilm,loads,weather}` feeds, then bring Grafana up and poll `/api/health` for 120 s |
| `fix_grafana.sh` | ship the stack with `COPYFILE_DISABLE=1 tar --no-xattrs --exclude '._*' --exclude '.DS_Store'`, then run `remote_grafana_fix.sh` on the host and tee the output to `/tmp/grafana_diag.txt` |

The `COPYFILE_DISABLE` and `._*` exclusions are not cosmetic. macOS `tar` injects
AppleDouble files, and `._IemsPage.js` matches the Vite plugin glob
`./*/**Page.js`, which registers a broken plugin.

`deploy2.sh` and friends `docker cp` into the running container rather than
rebuilding. That is fast and it is also why a rebuild silently reverts the
change. For anything meant to persist, edit the file in the repository on the
host and rebuild the service.

---

## Python entry points

| script | run from | purpose |
|---|---|---|
| `~/remote-gui-overlay-212/gen_dash_module.py` | the overlay build context | regenerate `frontend/iems/iems_dash.js` from the live dashboard. `python3 gen_dash_module.py http://localhost:47821/ frontend/iems/iems_dash.js` |
| `~/remote-gui-overlay-212/enable_iems.py` | same | append the four line `iems` entry to `feature_config.json` |
| `~/build_uns_graph.py` | anywhere on the host | rebuild and publish the UNS graph. `--dry-run` writes the JSON without publishing. Idempotent |
| `~/patch_ask.py`, `~/patch_src.py` | the host | the two idempotent patch scripts actually used here. Each asserts a single match per anchor, refuses to double-patch, and for client-side JS rejects inserted code containing a backtick or `${` because it lands inside a template literal |
| `~/make_paths_json.py` | the host | UNS path assignment helper |
| `services/iems/monitoring/gap_watchdog.py` | repo root | exit 0 all fresh, 1 gap detected, 2 source unreachable |
| `services/iems/detect/breaker_margin.py` | repo root | `--once`, `--loop`, or `--backtest <parquet>` |
| `services/iems/detect/hvac_shed.py` | repo root | `--status` and the shed and restore controls |
| `scripts/probe_egauge.py` | anywhere | meter register probe |
| `scripts/download_egauge_year.py` | anywhere | bulk historical pull |
| `services/iems/training/*.py` | repo root on the Mac | the training pipeline, see `04_training_pipeline.md` |

The gap watchdog as a cron entry, from its own docstring.

```
*/10 * * * * cd ~/microgrid-manager && .venv-training/bin/python3 \
    services/iems/monitoring/gap_watchdog.py || echo "IEMS data gap" | mail -s "IEMS gap" you@ucsc.edu
```

## Container entry points

| container | command |
|---|---|
| `iems-inference` | `["--tick", "${INFERENCE_TICK_SECONDS:-30}"]` into `iems.inference.inference_loop` |
| `iems-dashboard` | `node /app/server.js`, port 47821 |
| `iems-backend` | uvicorn on `main_api:app`, container port 8000 published as 8009 |
| `iems-app` | the image's own `start.sh`, backend pinned to 8000 by `REMOTE_GUI_BE`, frontend 31800 mapped to 3001 by `REMOTE_GUI_FE` |

The port pinning matters. AnyLog EDM 2.1.x defaults the backend to 8080, which
already collides with `kafka-ui`, and `:8000/iems/*` is wired into
`iems-dashboard` and the ONNX smoke tests.

## Ad hoc tooling worth knowing about

A dependency free Chrome DevTools Protocol client was written for the plugin
parity measurements, because the box has no pip and `--dump-dom` is unreliable
against a page that polls forever. `/json/new` needs PUT on current Chrome, and
`--virtual-time-budget` never settles on a page that polls, so use
`--headless=old --timeout=N` for one-shot dumps. Every plugin versus standalone
parity number in `06_apis_and_routes.md` came from it. It lived in `/tmp` and has
since been cleared, so it would need rewriting.
