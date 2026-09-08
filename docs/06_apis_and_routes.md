# APIs and routes

Three HTTP surfaces, one engine. Every route list below was read from the live
OpenAPI schema or the deployed source on Pat's box on 2026-09-08.

Port 3001 is the React frontend and returns `index.html` with HTTP 200 for any
unknown path, so never test an API against it.

| surface | port | paths |
|---|---|---|
| IEMS engine, `iems-backend` | 8009 | 25 |
| standalone dashboard, `iems-dashboard` | 47821 | 19 `/api/*` plus `/` and `/index.html` |
| AnyLog EDM backend, `iems-app` | 8000 | 122, of which 26 `/iems` and 20 `/uns` |
| AnyLog EDM frontend | 3001 | React shell |

---

## 1. The engine, `:8009`

`backend/main_api.py` mounts two routers. `GET /` returns
`{"ok": true, "service": "iems-backend"}`. Twenty-five paths in total.

| method | route | purpose |
|---|---|---|
| GET | `/` | liveness |
| POST | `/iems/cycle` | run the full four domain pass. 9 to 12 s |
| POST | `/iems/disaggregate` | disaggregate one panel on demand |
| GET | `/iems/channels` | meter channels |
| GET | `/iems/appliances` | appliance catalogue with laxity and shed priority |
| GET | `/iems/tou_rates` | PG&E E6 rates and the current period |
| GET | `/iems/health` | AnyLog reachable, model count, engine state |
| GET | `/iems/storage` | battery SOC, headroom, dispatch recommendation |
| GET | `/iems/anomalies/active` | open anomalies |
| GET | `/iems/nilm/recent` | recent `nilm_disaggregated` rows |
| GET | `/iems/onnx/models` | the ONNX models **this container** loaded. Not the ones producing data, see below |
| GET | `/iems/onnx/snapshot` | the latest per panel disaggregation |
| GET | `/iems/models` | Ollama models present |
| GET | `/iems/models/recommended` | suggested models for this host |
| GET | `/iems/models/show/{name}` | model detail |
| POST | `/iems/models/pull` | pull a model |
| POST | `/iems/models/test` | test a model |
| DELETE | `/iems/models/{name}` | delete a model |
| GET, POST | `/iems/preferences` | user preferences |
| POST | `/iems/recommendations/{rec_id}/accept` | acknowledge |
| POST | `/iems/recommendations/{rec_id}/defer` | acknowledge |
| POST | `/iems/recommendations/{rec_id}/dismiss` | acknowledge |
| POST | `/iems/ask` | ask the local model a question about this site |
| GET | `/iems/ask/context` | the exact bundle that would be sent |
| GET | `/iems/ask/health` | Ask subsystem state |

`/iems/anomalies/active` used to cost **168 seconds** and hold REST threads
throughout, because it ran `fetch_all_panels(start, end)` over a 24 hour window
and then discarded the rows to return `{"anomalies": []}`. The checks it was
written for were never wired up. The dead fetch was removed on 2026-09-02 and it
now answers in 1.6 ms.

`/iems/ask/context` is the first thing to look at when an answer is wrong,
because it shows exactly what the model was given.

`/iems/onnx/models` and `/iems/onnx/snapshot` report the model set baked into the
`iems-backend` image, which is a stale twelve feature legacy copy. The models
that write `nilm_disaggregated` live in the `iems-inference` image and are a
different, fourteen feature set. Never use these two routes to verify a model
deploy. `04_training_pipeline.md` has the checks that do work.

### The Ask context

`~microgrid/iems-backend-build/iems_ask.py` on Pat's box is ahead of the
repository copy.

`_live(want=None)` fetches only the dashboard feeds the requested context keys
need, in parallel through a `ThreadPoolExecutor`, each behind its own TTL cache
declared at line 153.

| feed | TTL |
|---|---|
| `snapshot`, `nilm`, `relay`, `solar-assistant` | 15 s |
| `storage`, `loads` | 60 s |
| `hvac-24h` | 300 s |
| anything else | `IEMS_ASK_LIVE_TTL`, default 30 s |

`site_knowledge` is opt-in. It is sent when `include_knowledge: true` is passed
or when the question matches `_KNOWLEDGE_HINT`, which covers rule, spec, breaker,
rating, catalogue, threshold, capacity and wiring. It was previously 84 percent
of every prompt. The knowledge bundle is the appliance catalogue with the prose
stripped, the appliance spec, the breaker and leg map, and the rules constants
**read live out of `rules_additive.py`** rather than restated, so the summary
cannot drift from the running rules.

Any feed that fails is listed under `_unavailable` with an instruction to say so
rather than infer.

Ollama parameters, line 442. `keep_alive: -1` coerced to an integer because
Ollama rejects the bare string `"-1"` with `missing unit in duration`, `num_ctx`
2048, `num_predict` 96, `num_thread` 3. Three threads leaves a core for
ingestion. Raising it to four speeds the model up and slows everything else.

Two bugs found while verifying, both fixed and both worth remembering.
`_build_context` narrowed `site_knowledge` to keys present in `include`, so
`include=battery&knowledge=1` silently returned `{}`, because `include` names
live feeds, knowledge sections, or both. And `req.temperature or 0.2` turned an
explicit `0` back into `0.2`, so the model rounded figures, 54.3 percent became
"50 percent" and once became "0 percent". The default is now `0.0` with an
explicit None check, and the system prompt requires every figure to appear
verbatim in the context.

Measured after that work.

| call | before | after |
|---|---|---|
| `/iems/ask/context?include=battery` | 27.9 s | 8.2 s cold, 0.04 s cached |
| Ask, `include:["battery"]` | 42.6 s | 8.2 s cold, 2.7 s warm |
| Ask, no include, all feeds | about 49 s | about 49 s cold, cached feeds after |
| Ask with knowledge | — | about 80 s, 10.7 kB context |
| context size, battery only | 11,069 chars | 282 chars |

`include` is a **list**. A bare string returns 422.

```json
{"question":"What is my battery state of charge right now?","include":["battery"]}
```

---

## 2. The dashboard, `:47821`

`services/iems/web/server.js`, 2784 lines, zero dependencies. The whole page is
emitted as one 102 KB response. Six tabs: General, Weather, Appliances, Relay,
Anomalies, Ask.

Nineteen `/api/*` routes, plus `/` and `/index.html`.

| route | purpose | measured |
|---|---|---|
| `/api/snapshot` | current panel watts and the KPI tiles | 1.3 s |
| `/api/sources` | per panel freshness and counts, AnyLog, Solar Assistant, Home Assistant, engine | 6.2 s cold, 0.001 s warm |
| `/api/nilm` | current appliance states | 0.04 s |
| `/api/loads` | load breakdown | 1.4 s |
| `/api/storage` | battery | 3.8 s |
| `/api/history` | time series for the power chart | 4.1 s, 135 kB |
| `/api/hvac-24h` | 24 hour HVAC energy, 300 s cache | 2.1 s |
| `/api/solar-assistant` | live inverter snapshot | 0.03 s |
| `/api/solar-history` | solar time series | 0.4 s, 186 kB |
| `/api/models` | model list | 0.004 s |
| `/api/model-meta` | model metadata. Currently returns `{}` | 0.07 s |
| `/api/health` | dashboard self check | 7.1 s |
| `/api/logs` | recent engine logs | 0.02 s |
| `/api/cycle` | trigger an engine cycle | POST |
| `/api/ask` | forwards to `/iems/ask` on 8009 | POST |
| `/api/relay` | relay and thermostat state | 0.09 s |
| `/api/relay/config` | relay configuration | GET and POST |
| `/api/relay/set` | set the thermostat | POST |
| `/api/relay/restore` | restore the thermostat | POST |

There is **no** `/api/states` and no `/api/services/*` on this server. Those
paths appear in the source only as **upstream Home Assistant** paths that
`haReq` calls, for example `/api/states/climate.sensi_2a293d_thermostat` and
`/api/services/climate/set_temperature`. An earlier revision of this document
listed them as dashboard routes, which is why they 404.

Only this container talks to Home Assistant. `HA_URL` is
`http://192.168.254.69:8123`, a separate LAN device on the same subnet as the
meter, not on Pat's box and not on Tailscale, so it is reachable only from inside
the house network. The token is bind mounted read only from
`/home/microgrid/ha_token.txt` to `/app/.ha_token`, with `HA_TOKEN_FILE` pointing
at it. Before that mount existed it was `docker cp`ed into the container's
writable layer and every rebuild destroyed it, which rendered the thermostat
panel as "HA offline" with every control inert.

### `/api/sources`, the endpoint that kept breaking things

It cost 22 to 24 s on **every call**, because `handleSources` pulled thirty
minutes of raw `energy_readings`, roughly 28,000 rows, over REST and parsed them
as JSON purely to compute one count and one max per channel, then did it again
for `solar_data`. Its cache TTL was 15 s, shorter than the handler's own runtime,
so the cache had never once served a request.

Two surfaces poll it forever, so the operator's six REST threads were permanently
busy. The visible symptom was elsewhere entirely. The GUI's MCP client could not
connect, failing on its 10 s budget, because the SSE handshake alone took 6.15 s
from inside `iems-app`.

The fix moved counting and dating into SQL, which AnyLog pushes down to the
operator.

```sql
SELECT nm, count(*) as n, max(ts) as last_ts FROM energy_readings
WHERE ts > NOW() - 30 minutes GROUP BY nm
```

That answers in 0.12 s. The latest watt value comes from the ten minute window
`/api/snapshot` already uses. `SOURCES_TTL_MS` went to 60 s with in-flight
de-duplication so concurrent tabs collapse onto one round trip. Result, 22 s to
0.001 s warm, with `samples_30m` and `rows_30m` matching what the raw scan
produced.

### Editing `server.js`

Two hazards, both of which have shipped broken code.

The whole page lives inside a JS template literal, so a single quote inside a
nested JS string needs **two** backslashes. Three lines once lost one, the
template collapsed `\'` to a bare `'`, and the served page contained
`ackRec('+i+','accept')` inside a single quoted string. That is a syntax error
that kills the entire inline controller, not just the buttons it appeared in. The
standalone page will happily serve broken JavaScript with a 200. The cheapest
check is the overlay build, because esbuild refuses to bundle the regenerated
module.

Second, `pollSnapshot` ends with `if (newestTs) $('dt').textContent = ...`, and a
revision that dropped the `<small id="dt">` element made every poll throw on the
null. The catch turned it into a red "Power feed offline" banner while the KPI
tiles were being filled in the same pass. Audit every `$('id')` and
`getElementById` against every `id="…"` in the file before deploying.

---

## 3. The GUI plugin, `:8000`

`~microgrid/remote-gui-overlay-212/backend/iems/iems_router.py`, 277 lines. A
proxy, not a second engine. No `onnxruntime`, no model files, no copy of
`services/iems` in the GUI image. `urllib` only, so no new dependency.

```
IEMS_BACKEND_URL = http://host.docker.internal:8009
IEMS_DASH_URL    = http://host.docker.internal:47821
```

The router prefix is `/iems` with tag `IEMS`. Routes are declared explicitly
rather than as a catch-all, for two reasons. A wildcard `/iems/{path:path}` would
swallow `/iems/dash`, and the OpenAPI schema should describe the real IEMS
surface rather than one opaque path.

Twenty-six `/iems` paths are live. Twenty-four forward to 8009, one forwards
everything to 47821, and one is the router's own index.

```
GET   /iems/                       self
GET   /iems/health  channels  appliances  storage  tou_rates
GET   /iems/nilm/recent  onnx/models  onnx/snapshot  anomalies/active
GET   /iems/models  models/recommended  models/show/{name}
GET   /iems/preferences        POST /iems/preferences
GET   /iems/ask/health  ask/context   POST /iems/ask
POST  /iems/cycle  disaggregate  models/pull  models/test
DELETE /iems/models/{name}
POST  /iems/recommendations/{rec_id}/{accept,defer,dismiss}
GET,PUT,DELETE,POST  /iems/dash/{path}
```

The three `/iems/ask*` routes were added on 2026-09-03 after they were found
answering 200 on the engine and 404 through the plugin. The repository copy still
declares 23 routes and has none of them. The Ask tab itself was never affected,
because it goes through `/iems/dash/api/ask`.

The rest of the 122 GUI paths group as `uns` 20, `auth` 13, `policycreator` 12,
`reportgenerator` 11, `mcpclient` 9, `edgedatafabrictopology` 7, `nodecheck` 5,
`sql` 3, `grafana` 2, and fourteen singletons including `/version`,
`/env-config`, `/feature-config`, `send-command`, `submit-policy` and
`view-streaming`.

### The threadpool

```python
from starlette.concurrency import run_in_threadpool
```

Every forward runs inside it, in the shared helper at line 97. This is the single
most important line in the plugin. The first pass called blocking `urllib`
directly inside `async def` handlers, which blocks uvicorn's event loop for the
entire duration of the upstream call. One IEMS poll froze the whole remote-gui
backend, the client console, SQL query, blockchain manager and every other
plugin.

| measurement | before | after |
|---|---|---|
| `/version` while an IEMS call is in flight | 22.83 s | 0.023 s |
| `/version` idle | 0.007 s | 0.006 s |
| 6 concurrent `/api/snapshot` via the proxy | 29.8 s | 18.7 s |
| 6 concurrent `/api/snapshot` direct to the dashboard | 18.2 s | 14.2 s |

Per request overhead of the proxy itself is nil, `api/snapshot` 4.48 s direct
against 4.53 s proxied, `api/relay` 0.092 s against 0.098 s.

### The generated frontend

`gen_dash_module.py` fetches the live page from 47821 and emits
`frontend/iems/iems_dash.js`, about 105 KB, applying three transforms.

1. The stylesheet is scoped. Every selector is prefixed with `.iems-dash-root`,
   and `:root`, `html`, `body` and the universal reset are rewritten onto that
   root. 198 rules. The generator refuses to emit if any selector escapes
   scoping, because `*{margin:0;padding:0}` and `body{display:flex}` would
   repaint the entire GUI shell.
2. The markup is taken verbatim, minus its `<script>` tags.
3. The controller is wrapped unmodified in `mountIemsDashboard(root, apiBase)`.
   Inside that closure `document`, `fetch`, `setTimeout`, `setInterval`,
   `clearTimeout` and `clearInterval` are shadowed, so DOM lookups scope to the
   plugin root, `/api/*` becomes `{apiBase}/iems/dash/api/*`, the absolute
   `localhost:8000/iems/…` call becomes `{apiBase}/iems/…`, the absolute
   open-meteo URL is left alone, and every timer is cancellable on unmount. The
   generator aborts if the controller ever declares one of the shadowed names
   itself.

Exactly one declaration differs from the standalone page, appended after the
scoped stylesheet and labelled.

```css
.iems-dash-root { min-height: 100% }
```

The dashboard sizes itself against the viewport. Inside the GUI it is a panel
below a header and beside a sidebar, where `100vh` is always taller than the
space available.

The shimmed `fetch` returns a permanently pending promise once the page is dead,
because some calls take twenty seconds, which is ample time to click away, and a
resolved fetch would run the dashboard's own `.then` against a root that no
longer exists.

Three generator bugs, all fixed, all worth knowing.

The first version split at-rules on the first `;`, and the stylesheet's opening
line is a Google Fonts `@import` whose `url()` contains semicolons for font
weights, so it was cut in half and the remainder parsed as a selector. The
scanner now steps over strings, comments and parenthesised values.

The `document` shim originally exposed only `getElementById`, `querySelector` and
`querySelectorAll`, so anything calling `document.createElement` threw inside the
plugin while working fine standalone. The Ask tab's preset buttons rendered on
47821 and silently vanished at 3001. It is now a proxy that scopes those three
lookups plus `body` to the plugin root and forwards everything else to the real
document, correctly bound.

And macOS `tar` injects AppleDouble `._*` files, and `._IemsPage.js` matches the
Vite plugin glob `./*/**Page.js`, which registers a broken plugin. Ship with
`COPYFILE_DISABLE=1` and `--exclude '._*'`.

**Any change to `services/iems/web/server.js` needs the generator rerun and the
overlay rebuilt before it reaches the plugin.**

```bash
python3 gen_dash_module.py http://localhost:47821/ frontend/iems/iems_dash.js
sudo docker build -t iems-remote-gui:2.1.2 .
sudo docker compose up -d --no-deps --force-recreate iems-app
```

### Overlay minimality, measured

Against upstream `anylogco/remote-gui:2.1.2`.

```
upstream 314 files, overlay 316

ADDED   7  -> 5 IEMS plugin files + 2 rebuilt Vite bundle chunks
REMOVED 5  -> 5 old Vite bundle chunks (replaced by the rebuild)
CHANGED 1  -> local-cli-backend/feature_config.json
```

The one changed file differs by exactly four lines appended to the `plugins` map.

```json
"iems": {
  "enabled": true,
  "description": "IEMS Plugin - live microgrid dashboard, NILM disaggregation and DSS recommendations from the local IEMS engine"
}
```

`features` is byte identical, `plugin_order.json` is untouched, and no upstream
source, router, page or asset is modified or removed. `loader.py` appends plugins
not named in `plugin_order` after the ones that are, and the sidebar does the
same, so IEMS lands with the other unlisted plugins without reordering anything
upstream ships. The sidebar entry is the four ASCII characters `IEMS` with no
icon, because `pluginMetadata` omits `icon` and `Sidebar.js` renders
`{item.icon && …}{item.name}`.

An earlier pass added `iems` to `plugin_order` and inserted it into
`sidebar_order` and `sidebar_sections.above_divider` with a lightning icon. That
moved IEMS above plugins AnyLog had deliberately placed and modified a second
config file for no reason. Both were reverted.

### Parity with the standalone dashboard

Both pages instrumented through the DevTools protocol at the same instant,
counting rendered elements rather than eyeballing. Source tiles 10 against 10,
KPI cards 8 against 8, NILM cards 22 with 5 on against 22 with 5 on, tabs 5
against 5, regions 11 against 11, power chart paths 15 against 15, TOU schedule
rects 24 against 24, weather chart paths 3 against 3, legend items 8 against 8.
Identical in every category, with the same TOU band and rate, weather, thermostat
reading, 24 h HVAC energy and event counts.

Time for every panel to populate was 29.5 s in the plugin against 55 s on the
standalone page in the same conditions.

---

## 4. AnyLog REST, `:32149` and `:32049`

Header driven, not path driven.

```bash
# non-SQL commands
curl -s http://100.119.235.24:32149 \
  -H "User-Agent: AnyLog/1.23" -H "command: get status"

# SQL additionally needs the destination header
curl -s http://100.119.235.24:32149 \
  -H "User-Agent: AnyLog/1.23" -H "destination: network" \
  -H 'command: sql customers format=json and stat=false
      "select max(insert_timestamp) as newest from energy_readings"'
```

Verified non-SQL commands include `get status`, `get version`, `get processes`,
`get partitions`, `get databases`, `get tables where dbms = customers`,
`get columns where dbms = customers and table = energy_readings`,
`get streaming`, `get connections`, `get msg client`, `get license`,
`get mcp status`, `blockchain get uns where [parent] not declared`, and
`help <command>`.

State changing commands must be POST. A GET is refused. `connect dbms`,
`process <script>` and `run client (...) connect dbms` are refused on **both** GET
and POST with `err_code 156, Wrong HTTP method used`, because the REST layer
accepts only reads and SQL. There is no command channel to the node short of its
interactive CLI.

SQL is single table. No joins, no subqueries, no `INTERVAL`. Time filters take
the form `NOW() - 24 hours`.

### The MCP server

`http://100.119.235.24:32149/mcp/sse`, hosted by the node itself, 18 tools.

Note that `get processes` reports the MCP row as `Not declared` while the server
is plainly answering. `get mcp status` returns a live session table and
`GET /mcp/sse` holds a 200 stream open. That row refers to a separate declaration
this deployment does not use, so do not read it as an outage.

The tools group into health and topology, discovery, querying, policy and UNS
traversal, and introspection. Full argument reference is in the project history
document `claude/mcp_tools_reference.md`.

Three argument traps. `queryWithIncrement` times are raw strings, and quoting
them yields an empty range. `getPolicyChildren` requires `whereCond`, and
omitting it looks like an empty graph rather than an error. And `whereCond`
values containing spaces need double quotes, as in `name = "Panel1 (HVAC)"`.
