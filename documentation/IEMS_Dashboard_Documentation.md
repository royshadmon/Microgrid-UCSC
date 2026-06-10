# IEMS Live Dashboard — Documentation

> **File:** `server.js`  
> **Runtime:** Node.js (no npm dependencies)  
> **Default URL:** `http://localhost:47821`

---

## Overview

The IEMS Live Dashboard is a single-file Node.js server that provides a real-time energy management interface for the **Los Gatos Microgrid**. It integrates two backend data sources — an **AnyLog** time-series database and an **IEMS FastAPI** service — and serves a self-contained browser UI for monitoring power consumption, appliance disaggregation (NILM), battery/solar status, weather, PG&E time-of-use rates, and energy optimization recommendations.

---

## Architecture

```
Browser UI (inline HTML/CSS/JS)
        │
        ▼
 Node.js HTTP Server (port 47821)
     /api/* routes
        │
   ┌────┴─────────────────────┐
   ▼                           ▼
AnyLog REST                IEMS FastAPI
127.0.0.1:32149            127.0.0.1:8000
(egauge_kafka,             (cycle, models,
 nilm_disaggregated)        health, weather/TOU)
```

---

## Configuration

All configuration is set via environment variables with sensible defaults:

| Variable       | Default       | Description                        |
|----------------|---------------|------------------------------------|
| `ANYLOG_HOST`  | `127.0.0.1`   | AnyLog node hostname               |
| `ANYLOG_PORT`  | `32149`       | AnyLog node port                   |
| `IEMS_HOST`    | `127.0.0.1`   | IEMS FastAPI service hostname      |
| `IEMS_PORT`    | `8000`        | IEMS FastAPI service port          |

**Start the server:**
```bash
node services/iems/web/server.js
```

**With custom backends:**
```bash
ANYLOG_HOST=192.168.1.10 IEMS_HOST=192.168.1.20 node server.js
```

---

## API Endpoints

### `GET /`
Serves the dashboard HTML page.

---

### `GET /api/snapshot`
Returns the latest power reading (within the last 10 minutes) for each of the 6 monitored panels.

**Response:**
```json
{
  "Grid Power":         { "ts": "2025-01-01 12:00:00", "w": 3200.0 },
  "Panel1 (HVAC)":      { "ts": "2025-01-01 12:00:00", "w": 1800.0 },
  "Panel2 (H2O)":       { "ts": "...", "w": 400.0 },
  "Panel3 (Kitchen)":   { "ts": "...", "w": 600.0 },
  "Shop":               { "ts": "...", "w": 250.0 },
  "Generac Power":      { "ts": "...", "w": 0.0 }
}
```

---

### `GET /api/history?minutes=N`
Returns up to 2,000 time-series rows from the last `N` minutes (default: 30) for all 6 panels. Used to render the raw power line graph.

| Query Param | Default | Description                        |
|-------------|---------|------------------------------------|
| `minutes`   | `30`    | Lookback window in minutes         |

**Response:** Array of `{ ts, nm, w }` rows.

---

### `GET /api/nilm`
Returns the latest 100 rows from the NILM disaggregation table, used to populate the 14-appliance inference grid.

**Response:** Array of `{ ts, circuit, appliance, state, confidence, avg_w }` rows.

---

### `GET /api/storage`
Returns the current solar production estimate, energy balance, and battery state (if available).

Solar production is **derived** (not directly metered):
```
solar_w = max(0, load - grid - generac)
```

**Response:**
```json
{
  "solar": {
    "production_w": 2100,
    "house_load_w": 3400,
    "grid_w": 1300,
    "exporting_w": 0,
    "self_consumption_w": 2100,
    "method": "derived: max(0, load - grid - generac)"
  },
  "battery": {
    "soc_pct": 78.5,
    "flow": "charging",
    "available_kwh": 7.2
  },
  "net_w": -1300
}
```

`battery` is `null` if the IEMS backend is unreachable.

---

### `GET /api/models`
Proxies `GET /iems/models` from the IEMS FastAPI service. Returns available NILM model metadata.

---

### `GET /api/health`
Checks both backend connections simultaneously and returns a combined health report.

**Response:**
```json
{
  "anylog": { "ok": true, "rows_5m": 42, "url": "127.0.0.1:32149" },
  "iems":   { ... },
  "server": { "port": 47821, "ts": "2025-01-01T12:00:00.000Z" }
}
```

---

### `POST /api/cycle`
Triggers an IEMS optimization cycle via the FastAPI backend. The request body is forwarded as-is.

**Request body:**
```json
{
  "mode":           "on_grid",
  "nilm_backend":   "onnx",
  "llm_backend":    "ollama",
  "llm_model":      "mistral:7b",
  "window_minutes": 10
}
```

**Response:** The full IEMS cycle result, including `dss_recommendations`, `metadata`, and updated NILM state.

---

## Internal Modules

### AnyLog Integration

**`_alRequest(cmd, timeout)`**  
Opens a raw TCP socket to AnyLog and sends an HTTP-formatted command. Handles chunked transfer encoding and returns the cleaned response body.

**`_getPartition(table)`**  
Resolves the latest partition name for `egauge_kafka` or `nilm_disaggregated`. Results are cached for 5 minutes to avoid repeated lookups.

**`_rewriteNow(sql)`**  
Rewrites `NOW() - N minutes/hours/days` expressions into absolute ISO timestamps before sending to AnyLog, which does not natively support relative time functions.

**`alSql(sql, timeout)`**  
High-level SQL helper. Handles partition resolution, `NOW()` rewriting, command formatting, JSON parsing, and AnyLog error messages. Returns an array of result rows or `[]` on failure.

---

### IEMS FastAPI Integration

**`iemsGet(path, timeout)`**  
Issues an HTTP GET to the IEMS FastAPI service. Returns a parsed JSON object or `{}` on error.

**`iemsPost(path, body, timeout)`**  
Issues an HTTP POST with a JSON body to the IEMS FastAPI service. Default timeout is 10 minutes to accommodate long-running cycle operations.

---

## Monitored Panels

| Display Name       | Color Token | Max (W) | "On" Threshold |
|--------------------|-------------|---------|----------------|
| Grid Power         | `--grid`    | 8,000   | 50 W           |
| Panel1 (HVAC)      | `--hvac`    | 6,000   | 1,000 W        |
| Panel2 (H2O)       | `--h2o`     | 4,000   | 200 W          |
| Panel3 (Kitchen)   | `--kit`     | 2,500   | 300 W          |
| Shop               | `--shop`    | 7,500   | 100 W          |
| Generac Power      | `--gen`     | 5,000   | 10 W           |

Grid Power is signed: **positive = importing**, **negative = exporting**.

---

## NILM Appliance Catalog

14 appliances are inferred from the 6 panel circuits using ONNX models (or Ollama as an alternative backend):

| Appliance      | Circuit            | Model File      |
|----------------|--------------------|-----------------|
| Heat Pump      | Panel1 (HVAC)      | `panel1.onnx`   |
| Solar Pump     | Panel1 (HVAC)      | `panel1.onnx`   |
| Water Heater   | Panel2 (H2O)       | `panel2.onnx`   |
| Hair Dryer     | Panel2 (H2O)       | `panel2.onnx`   |
| Sprinklers     | Panel2 (H2O)       | `panel2.onnx`   |
| Bath Lights    | Panel2 (H2O)       | `panel2.onnx`   |
| Refrigerator   | Panel3 (Kitchen)   | `panel3.onnx`   |
| Dishwasher     | Panel3 (Kitchen)   | `panel3.onnx`   |
| Microwave      | Panel3 (Kitchen)   | `panel3.onnx`   |
| Computers      | Panel3 (Kitchen)   | `panel3.onnx`   |
| Dryer          | Shop               | `shop.onnx`     |
| Shop Tools     | Shop               | `shop.onnx`     |
| EV Charger     | Shop               | `shop.onnx`     |
| Lighting       | Shop               | `shop.onnx`     |

Each card in the UI displays on/off state, wattage, circuit assignment, and inference confidence.

---

## PG&E E6 Time-of-Use Schedule

TOU classification is computed client-side via `classifyTOU(date)`:

| Period     | Hours (Weekdays)             | Summer Rate | Winter Rate |
|------------|------------------------------|-------------|-------------|
| Peak       | 15:00–19:00                  | $0.51/kWh   | $0.30/kWh   |
| Partial    | 10:00–13:00, 19:00–21:00     | $0.30/kWh   | $0.20/kWh   |
| Off-Peak   | 09:00–15:00, 13:00–19:00*    | $0.26/kWh   | $0.18/kWh   |
| Super Off  | 21:00–09:00                  | $0.19/kWh   | $0.19/kWh   |

Summer = May through October. Weekends follow off-peak/super-off rules.

The TOU graph renders 24-hour rate bands with a dashed "now" marker and displays the next rate transition.

---

## UI Layout

The dashboard is a fixed-height single-page app organized into five zones:

```
┌─────────────────────────────────────────────────────┐
│  Header: title · data-age badge · NILM mode pill    │
├─────────────────────────────────────────────────────┤
│  KPI Strip: 8 live metrics (grid, panels, solar,    │
│             generac, battery SOC)                   │
├─────────────────────────────────────────────────────┤
│  Controls: mode selector · NILM toggle · window     │
│            input · Run IEMS Cycle button            │
├──────────────────────────┬──────────────────────────┤
│  Raw Power Telemetry     │  DSS Recommendations     │
│  (30-min SVG line graph) │  (scrollable card list)  │
├──────────────────────────┴──────────────────────────┤
│  NILM Disaggregator  ·  14-appliance grid           │
├─────────────────────────────────────────────────────┤
│  Weather stats  |  PG&E TOU graph (24h)             │
└─────────────────────────────────────────────────────┘
```

### Poll Intervals

| Data Source      | Interval  |
|------------------|-----------|
| Snapshot (KPIs)  | 3 seconds |
| Power history    | 10 seconds|
| NILM grid        | 15 seconds|
| Storage/battery  | 5 seconds |
| Weather          | 5 minutes |
| TOU graph        | 60 seconds|

---

## DSS Recommendations

The Decision Support System (DSS) recommendations panel is populated after running an IEMS cycle. Each recommendation card shows:

- **Severity:** urgent (anomaly/critical), advisory (cost savings), or info
- **Action label** and optional **savings amount** in dollars
- **Rationale** text and confidence percentage
- **Actions:** Accept · Defer · Dismiss (POSTed to `/iems/recommendations/{id}/{action}`)

Dismissed/accepted recommendations are removed from the list immediately without requiring a new cycle.

---

## Design System

The dashboard uses a **cream-paper aesthetic** with monospace typography. Key CSS variables:

| Variable      | Value       | Use                        |
|---------------|-------------|----------------------------|
| `--bg`        | `#f5efdf`   | Page background            |
| `--paper`     | `#fbf6e8`   | Card background            |
| `--ink`       | `#2a241c`   | Primary text               |
| `--ok`        | `#5e8a5a`   | Good/charging state        |
| `--warn`      | `#c89a3a`   | Partial-peak / lagging     |
| `--bad`       | `#a64f3a`   | Peak rate / offline        |
| `--info`      | `#4a6b8a`   | Info / super-off rate      |
| `--mono`      | JetBrains Mono | All data labels/values  |
| `--sans`      | Inter          | UI chrome                 |

All icons are abstract inline SVG glyphs — no emoji, no external icon fonts.

---

## Notes & Known Limitations

- **Solar is derived, not metered.** There is no physical CT for PV on the eGauge meter. Solar production is estimated as `max(0, load - grid - generac)`. This has been validated against nighttime data but may drift under edge conditions (e.g., Generac running simultaneously with solar export).
- **Forecast load curve removed.** An earlier version included a hardcoded bell-curve load forecast; it was removed because it was not a real prediction.
- **AnyLog partition cache** is TTL-based (5 minutes). In high-churn partition environments, queries may briefly target a stale partition.
- **Battery SOC** is authoritative from the IEMS backend (13.5 kWh system, 50% depth-of-discharge floor). It is shown as `—` when the FastAPI service is unreachable.
- **CORS** is fully open (`Access-Control-Allow-Origin: *`) — this server is intended for local/intranet use only.
