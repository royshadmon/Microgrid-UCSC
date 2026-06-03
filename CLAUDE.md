# microgrid-manager · CLAUDE.md

This file is the persistent context for Claude Code sessions in this repo.
Read it first, every session, before touching any other file.

═══════════════════════════════════════════════════════════════════════════
WHAT THIS PROJECT IS
═══════════════════════════════════════════════════════════════════════════

An Intelligent Energy Management System (IEMS) for a real residential
microgrid in Los Gatos, CA. The user is harshranjan; the house is
instrumented with an eGauge18646 metering 16 channels.

The system has three jobs:
  1. Disaggregate sub-panel power into appliance-level ON/OFF states
     using a local LLM (NILM via prompt engineering, no training)
  2. Run an Intelligent Energy Management cycle that combines NILM
     output with weather, TOU rates, and battery state to produce
     dollar-denominated user recommendations and load-shedding plans
  3. Stream the live data + predictions + recommendations to a local
     webpage in real time

The user controls everything from Remote-GUI: picks/pulls local LLMs,
runs disaggregation, accepts/defers DSS recommendations.

═══════════════════════════════════════════════════════════════════════════
ARCHITECTURE — TWO RESEARCH PAPERS, FOUR FUNCTIONAL DOMAINS
═══════════════════════════════════════════════════════════════════════════

Paper 1: Xue et al. 2025 (arXiv:2505.06330) — "Prompting LLMs for
         Training-Free NILM". Provides the prompt-engineering recipe:
         per-appliance power range + duration + usage pattern injected
         into a system prompt, JSON-only output, window_size=100,
         context_length=30, 6-second sampling.

Paper 2: Adabi 2016 (UCSC PhD escholarship/uc/item/4mq64408) — "IEMS
         via NILM with User Decision Support". Provides the umbrella
         architecture: four functional domains (User · Load · Generation
         · Storage), the load-laxity taxonomy (auto-controlled /
         user-controlled-interval / user-controlled-non-interval /
         uninterruptible), the on-grid vs off-grid flow charts, the
         dollar-denominated DSS output.

LLM4NILM is the disaggregator INSIDE Adabi's Load domain, replacing
his J48 classifier.

           ┌───────────────────────────────────────────────────┐
           │   IEMS cycle (Adabi Fig 5.5)                      │
           │                                                   │
           │   USER  →  LOAD  →  GENERATION  →  STORAGE        │
           │           (NILM)    (solar+TOU)    (battery)      │
           │                                                   │
           │            ↓                                      │
           │   Decision Support  (rule tree → optimizer        │
           │                      → recommender)               │
           └───────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════
LIVE INFRASTRUCTURE (DO NOT RECREATE — DO NOT RESTART CASUALLY)
═══════════════════════════════════════════════════════════════════════════

Host:                ~harshranjan (macOS, no NVIDIA GPU — omit GPU blocks)
Project root:        ~/microgrid-manager/

Kafka stack:         ~/kafka-egauge-pipeline/docker-compose.kafka.yml
                     - egauge-producer container (runs continuously)
                     - kafka on host.docker.internal:9094
                     - kafka topic: egauge-energy

AnyLog operator1:    host.docker.internal:32148 (TCP)
                     host.docker.internal:32149 (REST)
                     host.docker.internal:1883  (broker)
AnyLog master:       host.docker.internal:32048
Operator config:     ~/docker-compose/docker-makefiles/operator1-configs/base_configs.env
                     ALREADY has OVERLAY_IP=host.docker.internal — DO NOT TOUCH
Operator policy ID:  bcc22d1407475e2d3013e2aaf66ce2bb (Cluster Member: True)
Cluster ID:          9db4d2b008516a40f98f8066c552d0d9

Database:            customers
Tables:              egauge_kafka          ← live mirror of Kafka stream
                     egauge_readings       ← may have cleaner schema (check first)
                     energy_readings       ← may have cleaner schema (check first)
                     nilm_disaggregated    ← write target for predictions
                                             schema: ts, circuit, appliance,
                                             state, confidence, avg_w, median_w,
                                             std_w, window_start, window_end,
                                             window_n

Live channels (eGauge18646, 16 total):
   Plain names (no parens — work in WHERE nm = '...'):
     Grid Power, Generac Power, Shop, VrmsA, VrmsB, F1,
     I11, I12, I21, I22, I31, I32, Current on Utility Tie
   Parenthesized names (see "AnyLog Parser Quirk" section):
     Panel1 (HVAC), Panel2 (H2O), Panel3 (Kitchen)

═══════════════════════════════════════════════════════════════════════════
HOUSE PROFILE (Los Gatos, CA)
═══════════════════════════════════════════════════════════════════════════

Coordinates:    HOUSE_LAT = 37.2358
                HOUSE_LON = -121.9624
                HOUSE_TZ  = America/Los_Angeles

Electrical layout: 3.5 sub-panels + main, all sub-metered.
  Panel1 (HVAC)     →  heat pump (~4 kW), heating + cooling
  Panel2 (H2O)      →  water heater (~4 kW peak, solar-thermal preheated),
                       PLUS bathrooms (= hair drier lands here),
                       PLUS outside outlets (= sprinklers, outdoor power)
  Panel3 (Kitchen)  →  refrigerator, dishwasher, microwave, cooktop, lights
  Shop              →  pressure pump, washing machine,
                       DRYER (7 kW — biggest single load), shop tools

NO EV CHARGER. Do not include one in the appliance taxonomy.

Solar thermal boiler PRESENT — water heater electric draw correlates
with cloud cover, not just hot-water demand.

Anomaly use cases the user explicitly wants:
  - Water heater dormant > 24h + cold + low irradiance → element fault
  - Pressure pump cycling > 2× baseline → plumbing leak (proven at this site)

Mobile load (Adabi observation): vacuum cleaner ~1 kW universal-motor
signature; appears on whichever panel its outlet is on. Reconciled
across panels via load/mobile_load.py.

═══════════════════════════════════════════════════════════════════════════
DIRECTORY LAYOUT
═══════════════════════════════════════════════════════════════════════════

~/microgrid-manager/
  CLAUDE.md                          ← this file
  docker-compose.yaml                ← Ollama + iems-backend + iems-frontend
  scripts/
    start_all.sh                     ← bring up Kafka → AnyLog → Ollama → IEMS
    stop_all.sh
    pull_models.sh
    fix_operator_location.sh         ← optional Los Gatos blockchain fix
  services/
    remote-gui/                      ← github.com/AnyLog-co/Remote-GUI
                                       ← cloned, IEMS lives as a feature plugin
    iems/                            ← the IEMS umbrella service
      api.py                         ← FastAPI router, mounted into Remote-GUI
      runner.py                      ← run_iems_cycle() — the 4-domain orchestrator
      config.py                      ← APPLIANCES, CHANNELS, TOU_RATES, HOUSE_PROFILE
      weather.py                     ← Open-Meteo for Los Gatos lat/lon

      load/                          ← Adabi's Load domain = the LLM4NILM piece
        anylog_query.py              ← SOLE AnyLog query module (see "Query Path")
        prompt_builder.py            ← per-panel LLM4NILM prompt construction
        llm_client.py                ← Ollama HTTP API wrapper
        output_normalizer.py         ← LLM4NILM Section 4.3 output cleanup
        disaggregator.py             ← per-panel NILM pipeline
        mobile_load.py               ← cross-panel vacuum reconciliation
        anomaly.py                   ← pump leak + WH dormancy detectors
        shedding.py                  ← laxity-ranked shed candidates

      generation/
        solar_forecast.py            ← Open-Meteo + Generac trace
        grid_analytics.py            ← PG&E E6 TOU classifier

      storage/
        battery_model.py             ← virtual SOC tracker (no battery yet)
        dispatch.py                  ← charge/discharge/dump recommendations

      decision_support/
        rule_tree.py                 ← AUTO vs USER_DRIVEN tagging
        optimizer.py                 ← scipy.linprog of Adabi eq 5.1 / 5.2
        recommender.py               ← dollar-denominated DSS messages

      prompts/
        base_role.txt
        load_disaggregation.txt
        anomaly_explainer.txt

      web/
        server.js                    ← single-file Node bridge, port 47821
                                       streaming dashboard (no npm/Vite)

      tests/                         ← live + offline test suites
  tests/                             ← project-level integration tests
  test_results/                      ← Claude Code writes verification logs here
  docs/
    anylog_query_cookbook.md         ← what works / what doesn't (verified)
    remote_gui_integration.md        ← which Remote-GUI routes IEMS uses

External (do not modify):
  ~/kafka-egauge-pipeline/           ← Kafka producer/consumer
  ~/docker-compose/docker-makefiles/ ← AnyLog operator/master configs
  ~/Downloads/anylog-nilm-dashboard.jsx  ← style reference for IEMS UI
  ~/Downloads/server.js              ← old standalone Node bridge (8080)

═══════════════════════════════════════════════════════════════════════════
ANYLOG QUERY PATH — THE NON-NEGOTIABLE
═══════════════════════════════════════════════════════════════════════════

There is exactly ONE place that talks to AnyLog: services/iems/load/anylog_query.py.
Every other module imports from it. No httpx/requests/aiohttp variants.

Verified working REST shape (DO NOT change without re-running the cookbook tests):

  GET http://{anylog_url}
  Headers:
    User-Agent:  AnyLog/1.23
    destination: network
    command:     sql customers format=json and stat=false "<SQL>"

  Response: {"Query":[...], "Statistics":[...]}      ← rows
            {"reply": "Empty data set"}              ← legitimate zero-row result
            {"err_code": ..., "err_text": ...}       ← parser error

DO NOT use:
  - "run client () sql ..."  → REST rejects it (err 156 GET, err 56 POST)
  - POST instead of GET      → broken
  - Omitting destination=network → silent empty results

═══════════════════════════════════════════════════════════════════════════
ANYLOG PARSER QUIRK — PARENTHESIZED CHANNEL LITERALS
═══════════════════════════════════════════════════════════════════════════

WHERE nm = 'Grid Power' AND ts > NOW() - 5 minutes              ← WORKS
WHERE nm = 'Panel1 (HVAC)' AND ts > NOW() - 5 minutes           ← Empty data set
WHERE nm IN ('Panel1 (HVAC)','Panel2 (H2O)') AND ts > ...       ← IncompleteRead
WHERE nm LIKE '%Panel%' AND ts > ...                            ← IncompleteRead

Workaround (already in fetch_recent_window):
  For channels in PAREN_CHANNELS, fetch by time window only and filter
  client-side:
    SELECT ts, nm, w FROM egauge_kafka
    WHERE ts > NOW() - {minutes} minutes ORDER BY ts ASC
  Then filter rows where nm == channel.

  fetch_all_panels_recent uses ONE such query and partitions by nm in
  Python — faster than per-panel queries.

PAREN_CHANNELS = {"Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"}

If you ever doubt this, run docs/anylog_query_cookbook.md tests first.
DO NOT introduce a new "fix" until the cookbook is updated to match.

ALTERNATIVE: energy_readings or egauge_readings tables may have cleaner
channel naming (e.g., panel1_hvac instead of "Panel1 (HVAC)"). If they
do AND have fresh data, switching ANYLOG_TABLE_LIVE to that table
sidesteps the bug entirely. Check before assuming the workaround is
permanent.

═══════════════════════════════════════════════════════════════════════════
LOCAL LLM CONTROL PLANE — REMOTE-GUI IS THE ONLY UI
═══════════════════════════════════════════════════════════════════════════

The user does not type docker exec. Every model operation happens through
Remote-GUI's IEMS page top panel:

  GET    /iems/models           → list (proxies Ollama /api/tags)
  POST   /iems/models/pull      → SSE stream of pull progress
  DELETE /iems/models/{name}    → uninstall
  POST   /iems/models/test      → diag_ping (sends 'Reply with {"ok":true}')
  GET    /iems/models/recommended → curated chip list

Recommended models (chip list shown in UI):
  mistral:7b (default) · llama3.1:8b · deepseek-r1:7b ·
  qwen2.5:7b · phi3:mini (fastest validate) · gemma2:9b

Ollama lives in the Docker stack at host.docker.internal:11434.
Models persist in the ollama-data volume.

The IEMS page also has an AnyLog query interface — freeform SQL routes
through Remote-GUI's backend, which routes through anylog_query.py. The
LLM picker selects which model is used for /iems/cycle and
/iems/disaggregate runs.

═══════════════════════════════════════════════════════════════════════════
LIVE WEBPAGE — TWO LAYERS, BOTH MUST WORK
═══════════════════════════════════════════════════════════════════════════

Layer 1 — Remote-GUI IEMS page  (production control plane)
  URL: http://localhost:3001/iems
  React, mounted as a Remote-GUI feature plugin.
  Sections: Local LLM picker · User domain · Load (4 panel cards with
  NILM states) · Generation+TOU · Storage+DSS recommendations.
  Talks to FastAPI at :8000.

Layer 2 — Standalone Node dashboard  (always-on streaming)
  URL: http://localhost:47821
  Single file: services/iems/web/server.js. No npm, no Vite.
  Polls /api/snapshot every 3s, /api/cycle every 30s.
  Used as the always-on monitoring view if Remote-GUI is being rebuilt.

Both layers use the same anylog_query.py contract. Both must pass the
Phase A5 pre-flight check (see scripts/start_all.sh).

═══════════════════════════════════════════════════════════════════════════
PORTS
═══════════════════════════════════════════════════════════════════════════

| Port  | Service             | Source                                  |
|-------|---------------------|-----------------------------------------|
| 32048 | AnyLog master       | docker-makefiles/master-configs         |
| 32148 | operator1 TCP       | docker-makefiles/operator1-configs      |
| 32149 | operator1 REST      | docker-makefiles/operator1-configs      |
|  1883 | operator1 broker    | docker-makefiles/operator1-configs      |
|  9092 | Kafka internal      | kafka-egauge-pipeline                   |
|  9094 | Kafka host bridge   | kafka-egauge-pipeline                   |
|  8000 | IEMS backend        | microgrid-manager (this repo)           |
|  3001 | Remote-GUI frontend | microgrid-manager (this repo)           |
| 11434 | Ollama              | microgrid-manager (this repo)           |
| 47821 | Node bridge UI      | microgrid-manager (this repo)           |

═══════════════════════════════════════════════════════════════════════════
WORKING RULES FOR CLAUDE CODE
═══════════════════════════════════════════════════════════════════════════

1. NEVER restart docker-compose unless you have evidence of failure.
   Specifically: check Cluster Member: True, Kafka consumer active,
   data freshness < 60s. Restarts have repeatedly broken the operator
   blockchain policy and cost long recovery sequences.

2. ALWAYS use anylog_query.py. If you find yourself about to write
   urllib.request.Request to :32149 anywhere else, stop and import
   from anylog_query.py instead. Prove it with:
     grep -rEn "(httpx|requests|aiohttp|urllib).*32149" services/iems/ \
       | grep -v "anylog_query.py"
   Must be empty.

3. PRE-FLIGHT BEFORE BUILDING. Every session, before any new feature work:
     ANYLOG_REST_URL=http://127.0.0.1:32149 python3 -c "
     import sys; sys.path.insert(0, 'services')
     from iems.load.anylog_query import health_check, fetch_all_panels_recent
     h = health_check(anylog_url='http://127.0.0.1:32149')
     print('health:', h)
     assert h['ok'] and h['staleness_s'] < 120
     panels = fetch_all_panels_recent(minutes=5,
                                      anylog_url='http://127.0.0.1:32149')
     for p,rs in panels.items():
         print(f'  {p}: {len(rs)}')
     "
   If this fails, FIX IT FIRST. Don't build features on broken data.

4. host.docker.internal RESOLVES INSIDE DOCKER ONLY. From the Mac shell,
   use 127.0.0.1:32149. From inside iems-backend or iems-frontend
   containers, use host.docker.internal:32149. Both URLs reach the
   same operator. The Python code defaults to host.docker.internal
   because most calls happen from inside containers; override with the
   ANYLOG_REST_URL env var when running scripts on the host.

5. THE PARENS QUIRK STAYS DOCUMENTED. Every time someone "fixes" it
   without running the cookbook tests, they break it. The fix is the
   workaround, not removing the workaround. Update
   docs/anylog_query_cookbook.md if a real fix is found and verified
   end-to-end against live data.

6. CITE THE PAPERS IN COMMENTS where the design comes from. Per-panel
   prompts: LLM4NILM Section 5.4. Laxity taxonomy: Adabi Section 5.3.
   On/off-grid flow: Adabi Figs 5.16/5.17. This makes future
   maintenance possible.

7. NEVER reproduce verbatim quotes from the papers in code, comments,
   or output. Paraphrase. Both papers are the design source, not the
   text source.

8. WHEN YOU TOUCH A PIECE OF CONFIG, GREP FOR ITS DUPLICATES. Channel
   names, ports, panel labels, appliance keys all appear in multiple
   files (config.py, prompt_builder.py, web/server.js, IEMSPage.jsx).
   A change in one means a change in all.

9. THE USER WANTS TO SEE LIVE DATA + APPLIANCES + RECOMMENDATIONS ON A
   WEBPAGE. If a session ends with passing tests but no visible page
   update, you've shipped half. Open localhost:3001/iems and
   localhost:47821 in the validation step every time.

10. SAVE LOGS. Every diagnostic run goes into ~/microgrid-manager/test_results/
    with a timestamped filename. Future sessions read these to avoid
    repeating diagnostics.

═══════════════════════════════════════════════════════════════════════════
KNOWN GOTCHAS WITH RECOVERY SEQUENCES
═══════════════════════════════════════════════════════════════════════════

A. "Operator not available" on run client () or empty data despite live
   Kafka: blockchain operator policy reverted to WAN IP. Fix:
     curl -s http://127.0.0.1:32149 -H "User-Agent: AnyLog/1.23" \
       -H "command: blockchain get operator"
   If ip != host.docker.internal, recovery sequence is in test_results/
   from the 2026-04-28 session — delete policy → reinsert with
   host.docker.internal → restart operator with policy
   bcc22d1407475e2d3013e2aaf66ce2bb. base_configs.env already has
   OVERLAY_IP=host.docker.internal so it survives clean restarts.

B. Cluster Member: False after operator restart:
     curl -X POST http://127.0.0.1:32149 -H "User-Agent: AnyLog/1.23" \
       -H "command: run operator where create_table = true and
                   update_tsd_info = true and archive_json = true and
                   master_node = host.docker.internal:32048 and
                   policy = bcc22d1407475e2d3013e2aaf66ce2bb and threads = 3"

C. Kafka consumer absent (get msg client returns no egauge-energy):
   Re-register sequence is in scripts/start_all.sh step [3/6].

D. IncompleteRead on a query: it's the parser quirk. Switch to time-only
   fetch + client filter. Don't blame the network.

E. Ollama model pull hangs or fails through SSE: confirm the iems-backend
   container has extra_hosts: ["host.docker.internal:host-gateway"] in
   docker-compose.yaml. Without it, the backend can't reach :11434.

═══════════════════════════════════════════════════════════════════════════
FOR EVERY NEW SESSION
═══════════════════════════════════════════════════════════════════════════

Start by reading, in order:
  1. This file (CLAUDE.md)
  2. docs/anylog_query_cookbook.md
  3. docs/remote_gui_integration.md
  4. The most recent file in test_results/ (last session's verdict)

Then run the pre-flight check (Rule 3 above).

Only after pre-flight passes, look at the user's current request.

