/**
 * IEMS Live Dashboard  —  zero npm, single file
 * Run:   node services/iems/web/server.js
 * Open:  http://localhost:47821
 *
 * Data sources:
 *   AnyLog REST   → 127.0.0.1:32149   (raw energy_readings + nilm_disaggregated +
 *                                      solar_data measured PV/battery/grid/load)
 *   IEMS FastAPI  → 127.0.0.1:8000    (cycle, models, health, weather/TOU)
 *
 * UI: cream-paper aesthetic, abstract SVG glyphs (no emoji), 14-appliance
 * NILM grid, raw power line graph, TOU rate + load-forecast graph, DSS.
 */

const http  = require('http')
const fs    = require('fs')
const pathm = require('path')
const PORT         = 47821
const ANYLOG_HOST  = process.env.ANYLOG_HOST  || '127.0.0.1'
const ANYLOG_PORT  = parseInt(process.env.ANYLOG_PORT  || '32149')
const IEMS_HOST    = process.env.IEMS_HOST    || '127.0.0.1'
const IEMS_PORT    = parseInt(process.env.IEMS_PORT    || '8000')

// ─── AnyLog helpers ───────────────────────────────────────────────────────────
let _partitionCache = {}
let _partitionCacheTs = {}   // per-table ts (was one shared ts -> could pin a table to a stale/dropped partition)

const PARTITION_TTL_MS = 60000   // was 300000: a 5-min pin spans a rollover

function _invalidatePartition(table) {
  delete _partitionCache[table]
  delete _partitionCacheTs[table]
}

// `get partitions` returns: par_<name>|<start-date>|<end-date>|
// Rank by END DATE (actual data recency), not by lexical name. A name sort
// silently returns a stale partition whenever a newer one is missing its
// date columns, which is how a dead partition ends up looking "latest".
async function _getPartition(table) {
  const now = Date.now()
  if (_partitionCache[table] && now - (_partitionCacheTs[table] || 0) < PARTITION_TTL_MS)
    return _partitionCache[table]
  const raw = await _alRequest(`get partitions where dbms=customers and table=${table}`)
  const parts = []
  for (const line of raw.split('\n')) {
    const m = line.match(/(par_[^\s|]+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\d{4}-\d{2}-\d{2})/)
    if (m) { parts.push({ name: m[1], end: m[3] }) }
    else {
      // No date columns (e.g. a partition created moments ago). Keep it as a
      // candidate rather than dropping it -- dropping is what strands us on
      // an old partition -- but rank it last-resort by name.
      const n = line.match(/(par_[^\s|]+)/)
      if (n) parts.push({ name: n[1], end: null })
    }
  }
  if (!parts.length) return _partitionCache[table] || null
  const dated = parts.filter(p => p.end)
  let latest
  if (dated.length) {
    dated.sort((a, b) => a.end < b.end ? -1 : a.end > b.end ? 1 : (a.name < b.name ? -1 : 1))
    latest = dated[dated.length - 1].name
    // A brand-new undated partition sorts after every dated one by name.
    const undated = parts.filter(p => !p.end).map(p => p.name).sort()
    if (undated.length && undated[undated.length - 1] > latest)
      latest = undated[undated.length - 1]
  } else {
    parts.sort((a, b) => a.name < b.name ? -1 : 1)
    latest = parts[parts.length - 1].name
  }
  if (latest) { _partitionCache[table] = latest; _partitionCacheTs[table] = now }
  return latest
}

function _rewriteNow(sql) {
  return sql.replace(/NOW\(\)\s*-\s*(\d+)\s*(minutes?|hours?|days?)/gi, (_, n, unit) => {
    const ms = unit.startsWith('min') ? n*60000 : unit.startsWith('hour') ? n*3600000 : n*86400000
    const dt = new Date(Date.now() - ms)
    return `'${dt.toISOString().replace('T',' ').slice(0,19)}'`
  })
}

function _alRequest(cmd, timeout = 20000) {
  return new Promise((resolve) => {
    const net = require('net')
    const sock = net.createConnection(ANYLOG_PORT, ANYLOG_HOST)
    const headers = [
      `GET / HTTP/1.1`,
      `Host: ${ANYLOG_HOST}:${ANYLOG_PORT}`,
      `User-Agent: AnyLog/1.23`,
      `command: ${cmd}`,
      `Connection: close`,
      ``,``,
    ].join('\r\n')
    let buf = ''
    sock.setTimeout(timeout)
    sock.on('connect', () => sock.write(headers))
    sock.on('data', d => { buf += d.toString() })
    sock.on('end', finish)
    sock.on('timeout', () => { sock.destroy(); finish() })
    sock.on('error', () => finish())
    function finish() {
      const body = buf.includes('\r\n\r\n') ? buf.split('\r\n\r\n').slice(1).join('\r\n\r\n') : buf
      const cleaned = body.replace(/(?:^|\n)[0-9a-fA-F]+\r?\n/g, '\n').trim()
      resolve(cleaned)
    }
  })
}

async function alSql(sql, timeout = 25000, _retry = true) {
  let resolved = _rewriteNow(sql)
  const substituted = []
  for (const tbl of ['energy_readings', 'nilm_disaggregated', 'solar_data']) {
    const re = new RegExp('\\b' + tbl + '\\b')
    if (re.test(resolved)) {
      const part = await _getPartition(tbl)
      if (part) { resolved = resolved.replace(re, part); substituted.push(tbl) }
    }
  }
  const cmd = `sql customers format=json and stat=false "${resolved}"`
  const raw = await _alRequest(cmd, timeout)
  // An empty result from a substituted partition usually means the cache is
  // pinned to a rolled-over partition. Drop it and re-resolve once.
  if (_retry && substituted.length &&
      (!raw || raw.includes('Empty data set') || raw.includes('"reply"'))) {
    substituted.forEach(_invalidatePartition)
    const again = await alSql(sql, timeout, false)
    if (again && again.length) return again
  }
  try {
    const j = JSON.parse(raw)
    if (Array.isArray(j)) return j
    if (j && Array.isArray(j.Query)) return j.Query
    if (j && typeof j.reply === 'string' && j.reply.toLowerCase().includes('empty')) return []
    if (j && j.err_text) { console.warn('[alSql] AnyLog error:', j.err_text, '| sql:', sql.slice(0,80)); return [] }
    return []
  } catch {
    if (raw.includes('Empty data set') || !raw) return []
    console.warn('[alSql] parse failed, raw=', raw.slice(0,120))
    return []
  }
}

// ─── IEMS FastAPI proxy helper ────────────────────────────────────────────────

function iemsGet(path, timeout = 15000) {
  return new Promise((resolve) => {
    const req = http.request({
      hostname: IEMS_HOST, port: IEMS_PORT, path, method: 'GET',
      headers: { 'Accept': 'application/json' },
    }, res => {
      let raw = ''
      res.on('data', c => raw += c)
      res.on('end', () => { try { resolve(JSON.parse(raw)) } catch { resolve({}) } })
    })
    req.setTimeout(timeout, () => req.destroy(new Error('IEMS timeout')))
    req.on('error', e => resolve({ error: e.message }))
    req.end()
  })
}

function iemsPost(path, body, timeout = 600000) {
  return new Promise((resolve) => {
    const data = JSON.stringify(body)
    const req = http.request({
      hostname: IEMS_HOST, port: IEMS_PORT, path, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    }, res => {
      let raw = ''
      res.on('data', c => raw += c)
      res.on('end', () => { try { resolve(JSON.parse(raw)) } catch { resolve({}) } })
    })
    req.setTimeout(timeout, () => req.destroy(new Error('IEMS cycle timeout')))
    req.on('error', e => resolve({ error: e.message }))
    req.write(data)
    req.end()
  })
}

// ─── API Handlers ─────────────────────────────────────────────────────────────

const PANELS = [
  'Grid Power', 'Generac Power', 'Panel1 (HVAC)',
  'Panel2 (H2O)', 'Panel3 (Kitchen)', 'Shop',
]
const PANEL_SET = new Set(PANELS)

async function handleSnapshot(res) {
  const rows = await alSql(
    "SELECT ts, nm, w FROM energy_readings " +
    "WHERE ts > NOW() - 10 minutes ORDER BY ts ASC"
  )
  const snap = {}
  for (const r of rows) {
    if (!PANEL_SET.has(r.nm)) continue
    if (!snap[r.nm] || r.ts > snap[r.nm].ts)
      snap[r.nm] = { ts: r.ts, w: parseFloat(r.w) }
  }
  json(res, snap)
}

async function handleStorage(res) {
  // Latest watts per power channel (last 10 min)
  const rows = await alSql(
    "SELECT ts, nm, w FROM energy_readings WHERE ts > NOW() - 10 minutes ORDER BY ts ASC"
  )
  const latest = {}
  for (const r of rows) {
    if (!PANEL_SET.has(r.nm)) continue
    if (!latest[r.nm] || r.ts > latest[r.nm].ts) latest[r.nm] = { ts: r.ts, w: parseFloat(r.w) }
  }
  const W = nm => latest[nm] ? latest[nm].w : 0
  const grid    = W('Grid Power')        // signed: + import / - export
  const generac = W('Generac Power')
  const loadW   = Math.abs(W('Panel1 (HVAC)')) + Math.abs(W('Panel2 (H2O)')) +
                  Math.abs(W('Panel3 (Kitchen)')) + Math.abs(W('Shop'))
  // Energy balance: no PV CT on the meter, so derive solar.  Validated vs night data.
  const solarW  = Math.max(0, loadW - grid - generac)
  const netW    = solarW - loadW
  // Battery is authoritative from the backend (13.5 kWh / 50% floor); null if backend down.
  let battery = null
  try { const sb = await iemsGet('/iems/storage'); if (sb && sb.battery) battery = sb.battery } catch (e) {}
  json(res, {
    solar: {
      production_w:       Math.round(solarW),
      house_load_w:       Math.round(loadW),
      grid_w:             Math.round(grid),
      exporting_w:        Math.round(Math.max(0, -grid)),
      self_consumption_w: Math.round(Math.min(solarW, loadW)),
      method: 'derived: max(0, load - grid - generac)',
    },
    battery,
    net_w: Math.round(netW),
  })
}

// Measured Solar Assistant telemetry (separate from the derived estimate
// above). Mirrors fetch_solar_snapshot() in services/iems/load/anylog_query.py
// so the dashboard and the rules engine agree on what "recent" means.
async function handleSolarAssistant(res) {
  const rows = await alSql(
    "SELECT ts, pv_power, battery_power, battery_soc, grid_power, load_power, device_mode " +
    "FROM solar_data WHERE ts > NOW() - 10 minutes ORDER BY ts DESC"
  )
  if (!rows.length) return json(res, { connected: false })
  const r = rows[0]
  const ageS = Math.round((Date.now() - Date.parse(r.ts.replace(' ', 'T') + 'Z')) / 1000)
  json(res, {
    connected: true,
    pv_power_w:      Math.round(parseFloat(r.pv_power) || 0),
    battery_power_w: Math.round(parseFloat(r.battery_power) || 0),
    battery_soc_pct: parseFloat(r.battery_soc) || 0,
    grid_power_w:    Math.round(parseFloat(r.grid_power) || 0),
    load_power_w:    Math.round(parseFloat(r.load_power) || 0),
    device_mode:     r.device_mode || null,
    ts: r.ts,
    age_s: Number.isFinite(ageS) ? ageS : null,
  })
}

async function handleHistory(res, params) {
  const minutes = parseInt(params.get('minutes') || '30')
  const rows = await alSql(
    "SELECT ts, nm, w FROM energy_readings " +
    `WHERE ts > NOW() - ${minutes} minutes ORDER BY ts ASC`
  )
  const filtered = rows.filter(r => PANEL_SET.has(r.nm))
  json(res, filtered.slice(-2000))
}

async function handleNilm(res) {
  const rows = await alSql(
    "SELECT ts, circuit, appliance, state, confidence, avg_w " +
    "FROM nilm_disaggregated ORDER BY ts DESC LIMIT 100"
  )
  json(res, rows)
}

async function handleCycle(req, res) {
  let body = ''
  req.on('data', c => body += c)
  req.on('end', async () => {
    let payload = {}
    try { payload = JSON.parse(body) } catch {}
    const result = await iemsPost('/iems/cycle', payload)
    json(res, result)
  })
}

function handleModelMeta(res) {
  // Per-appliance transparency: live decision threshold + held-out test F1.
  // Thresholds come from the norm jsons the inference loop actually loads;
  // F1s come from model_card.json written by the training pipeline.
  const root = pathm.join(__dirname, '..', 'models')
  const meta = {}
  for (const n of [1, 2, 3]) {
    try {
      const d = JSON.parse(fs.readFileSync(pathm.join(root, 'panel' + n + '_norm_bilstm.json'), 'utf8'))
      for (const [k, v] of Object.entries(d.thresholds || {})) meta[k] = { thr: v }
    } catch (e) {}
  }
  try {
    const card = JSON.parse(fs.readFileSync(pathm.join(root, 'model_card.json'), 'utf8'))
    for (const [k, v] of Object.entries(card.appliances || {})) {
      meta[k] = Object.assign(meta[k] || {}, { f1: v.f1, trained: card.trained_at })
    }
  } catch (e) {}
  json(res, meta)
}

async function handleModels(res) {
  const result = await iemsGet('/iems/models')
  json(res, result)
}

async function handleHealth(res) {
  const [anylogHealth, iemsHealth] = await Promise.allSettled([
    alSql("SELECT COUNT(*) as n FROM energy_readings WHERE ts > NOW() - 5 minutes"),
    iemsGet('/iems/health', 8000),
  ])
  const anylogRows = anylogHealth.status === 'fulfilled' ? anylogHealth.value : []
  const iemsData   = iemsHealth.status  === 'fulfilled' ? iemsHealth.value  : {}
  json(res, {
    anylog: { ok: anylogRows.length > 0, rows_5m: anylogRows[0]?.n || 0, url: `${ANYLOG_HOST}:${ANYLOG_PORT}` },
    iems: iemsData,
    server: { port: PORT, ts: new Date().toISOString() },
  })
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function json(res, data) {
  const body = JSON.stringify(data)
  res.writeHead(200, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Cache-Control': 'no-cache',
  })
  res.end(body)
}

function err(res, code, msg) {
  res.writeHead(code, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify({ error: msg }))
}

// ─── Router ───────────────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  const url    = new URL(req.url, `http://${req.headers.host}`)
  const path   = url.pathname
  const params = url.searchParams

  if (req.method === 'OPTIONS') {
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST' })
    res.end()
    return
  }

  try {
    if (path === '/api/snapshot' && req.method === 'GET') return handleSnapshot(res)
    if (path === '/api/history'  && req.method === 'GET') return handleHistory(res, params)
    if (path === '/api/nilm'     && req.method === 'GET') return handleNilm(res)
    if (path === '/api/cycle'    && req.method === 'POST') return handleCycle(req, res)
    if (path === '/api/models'   && req.method === 'GET') return handleModels(res)
    if (path === '/api/model-meta' && req.method === 'GET') return handleModelMeta(res)
    if (path === '/api/health'   && req.method === 'GET') return handleHealth(res)
    if (path === '/api/storage'  && req.method === 'GET') return handleStorage(res)
    if (path === '/api/solar-assistant' && req.method === 'GET') return handleSolarAssistant(res)
    if (path === '/' || path === '/index.html') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(HTML)
      return
    }
    err(res, 404, `No route for ${req.method} ${path}`)
  } catch (e) {
    console.error(`[${path}]`, e.message)
    err(res, 500, e.message)
  }
})

server.listen(PORT, () => {
  console.log(`\n  IEMS Live Dashboard`)
  console.log(`  →   http://localhost:${PORT}`)
  console.log(`  ←   AnyLog  ${ANYLOG_HOST}:${ANYLOG_PORT}`)
  console.log(`  ←   IEMS    ${IEMS_HOST}:${IEMS_PORT}\n`)
})

// ─── Inline HTML ──────────────────────────────────────────────────────────────

const HTML = /* html */`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IEMS · Los Gatos Microgrid</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700;800&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#ffffff; --paper:#ffffff; --paper-2:#ffffff;
  --ink:#2a241c; --ink-2:#5a4f3f; --ink-3:#8a7d68;
  --line:#c9bea3; --line-soft:#e3d9be;
  --grid:#b85c2e; --hvac:#4a6b8a; --h2o:#8a5a7a;
  --kit:#5e8a5a; --shop:#c89a3a; --gen:#a17a28;
  --ok:#5e8a5a; --warn:#c89a3a; --bad:#a64f3a; --info:#4a6b8a; --sa:#2e7d8a;
  --mono:'JetBrains Mono',ui-monospace,monospace;
  --sans:'Inter',system-ui,sans-serif;
  --r:9px;
}
html,body{height:100%;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:12px;line-height:1.4}
body{padding:12px 16px;display:flex;flex-direction:column;gap:9px;min-height:100vh;overflow-y:auto;overflow-x:hidden}

.hdr{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;border-bottom:1px solid var(--line);padding-bottom:7px}
.hdr h1{font-size:18px;font-weight:800;letter-spacing:-.02em;color:var(--ink)}
.hdr .sub{font-size:9px;color:var(--ink-3);font-family:var(--mono);margin-top:2px;letter-spacing:.04em}
.badge{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);font-size:9px;
  letter-spacing:.18em;color:var(--ink-2);text-transform:uppercase;margin-bottom:3px;font-weight:600}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);
  box-shadow:0 0 0 0 rgba(94,138,90,.55);animation:ring 2s ease-in-out infinite}
.dot.err{background:var(--bad);animation:none}
.dot.warn{background:var(--warn);animation:none}
@keyframes ring{0%,100%{box-shadow:0 0 0 0 rgba(94,138,90,.55)}70%{box-shadow:0 0 0 6px rgba(94,138,90,0)}}
.mode-pill{display:inline-block;padding:2px 8px;border-radius:11px;background:color-mix(in srgb,var(--info) 15%,var(--paper-2));
  color:var(--info);font-family:var(--mono);font-size:8.5px;font-weight:700;border:1px solid var(--info);letter-spacing:.06em;margin-left:6px}
.poll{font-family:var(--mono);font-size:10.5px;color:var(--ink-2);text-align:right;white-space:nowrap}
.poll small{display:block;font-size:8.5px;color:var(--ink-3);margin-top:1px}

.errbar{display:none;background:color-mix(in srgb,var(--bad) 10%,var(--paper));border:1px solid var(--bad);
  border-radius:7px;padding:7px 12px;font-family:var(--mono);font-size:10.5px;color:var(--bad)}
.errbar.show{display:block}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;flex-shrink:0}
.kpi{background:var(--paper);border:1px solid var(--line);border-radius:var(--r);padding:12px 15px;position:relative;overflow:hidden}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--c)}
.kpi .lbl{font-family:var(--mono);font-size:8px;text-transform:uppercase;letter-spacing:.14em;color:var(--ink-3);margin-bottom:3px;display:flex;align-items:center;gap:5px;font-weight:600}
.kpi .val{font-family:var(--mono);font-size:19px;font-weight:700;line-height:1.05;color:var(--ink)}
.kpi .hint{font-size:10.5px;color:var(--ink-3);margin-top:4px;font-family:var(--mono);letter-spacing:.02em;white-space:nowrap}
.kpi .hint.up{color:var(--bad)} .kpi .hint.down{color:var(--ok)}
.kpi-glyph{width:10px;height:10px;display:inline-block;color:var(--c)}

.ctrl{display:flex;align-items:center;gap:9px;flex-wrap:wrap;padding:7px 11px;background:var(--paper);border:1px solid var(--line);border-radius:var(--r);flex-shrink:0}
.ctrl label{font-family:var(--mono);font-size:9px;color:var(--ink-2);font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.ctrl select,.ctrl input[type=number]{font-family:var(--mono);font-size:10.5px;background:var(--paper-2);border:1px solid var(--line);
  color:var(--ink);border-radius:5px;padding:3px 8px;outline:none}
.ctrl select:focus,.ctrl input:focus{border-color:var(--info)}
.toggle{display:inline-flex;border:1px solid var(--line);border-radius:5px;overflow:hidden;background:var(--paper-2)}
.toggle button{font-family:var(--mono);font-size:9.5px;font-weight:600;padding:4px 11px;border:none;background:transparent;color:var(--ink-2);cursor:pointer;letter-spacing:.06em}
.toggle button.active{background:var(--ink);color:var(--paper)}
.btn{font-family:var(--mono);font-size:9.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  padding:5px 13px;border-radius:6px;border:1px solid var(--ink);cursor:pointer;transition:all .15s;background:var(--ink);color:var(--paper)}
.btn:hover{background:var(--paper);color:var(--ink)}
.btn:disabled{opacity:.5;cursor:wait}
.cycstat{font-family:var(--mono);font-size:9.5px;color:var(--ok);font-weight:600;margin-left:auto}
.spin{display:inline-block;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

.tabs{display:flex;gap:6px;border-bottom:1px solid var(--line);padding-bottom:0;flex-shrink:0}
.tab-btn{font-family:var(--mono);font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  padding:7px 16px;border:1px solid var(--line);border-bottom:none;border-radius:7px 7px 0 0;background:var(--bg);
  color:var(--ink-3);cursor:pointer;position:relative;top:1px}
.tab-btn:hover{color:var(--ink-2)}
.tab-btn.active{background:var(--paper);color:var(--ink);border-color:var(--line);border-bottom:1px solid var(--paper)}
.tab-panel{display:none;flex-direction:column;gap:9px;flex:1 0 auto;min-height:0}
.tab-panel.active{display:flex}

.gridmain{display:grid;grid-template-columns:1.3fr 1fr;grid-template-rows:minmax(300px,auto) minmax(220px,auto);gap:9px;flex:1 0 auto;min-height:0}
.region{background:var(--paper);border:1px solid var(--line);border-radius:var(--r);padding:9px 12px;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.region h2{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.16em;color:var(--ink-2);margin-bottom:7px;display:flex;align-items:center;gap:7px;font-family:var(--mono);flex-shrink:0}
.region h2 .gly{width:12px;height:12px;color:var(--ink)}
.region h2 .tag{font-size:8px;letter-spacing:.05em;padding:2px 7px;border-radius:18px;background:var(--bg);color:var(--ink-3);font-weight:500;border:1px solid var(--line-soft);margin-left:auto;font-family:var(--mono)}
.region h2 .tag.ok{color:var(--ok);border-color:var(--ok);background:color-mix(in srgb,var(--ok) 10%,var(--paper))}
.region h2 .tag.warn{color:var(--warn);border-color:var(--warn);background:color-mix(in srgb,var(--warn) 10%,var(--paper))}
.region h2 .tag.bad{color:var(--bad);border-color:var(--bad);background:color-mix(in srgb,var(--bad) 10%,var(--paper))}

.r-power{grid-column:1;grid-row:1}
.r-dss{grid-column:2;grid-row:1}
.r-tou{grid-column:1 / -1;grid-row:2}
.r-nilm{flex:1 0 auto}
.r-weather-tab{flex:1 0 auto}

.pwr-content{display:flex;flex-direction:column;gap:6px;flex:1;min-height:0}
.legend{display:flex;flex-wrap:wrap;gap:8px;font-family:var(--mono);font-size:8.5px;color:var(--ink-2);flex-shrink:0}
.legend-item{display:flex;align-items:center;gap:4px}
.legend-sw{width:12px;height:3px;border-radius:1.5px;background:var(--c)}
.pwr-graph-wrap{flex:1;min-height:0;position:relative}
.pwr-graph{width:100%;height:100%}
.pwr-stat-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:6px 0 0;flex:1;align-items:center}
.pwr-stat{text-align:center;font-family:var(--mono);background:var(--paper-2);border:1px solid var(--line-soft);border-radius:7px;padding:10px 8px;display:flex;flex-direction:column;justify-content:center;gap:4px;min-height:70px}
.pwr-stat .lbl{font-size:8.5px;text-transform:uppercase;letter-spacing:.12em;color:var(--ink-3);font-weight:700}
.pwr-stat .val{font-size:17px;font-weight:800;color:var(--c);line-height:1}

.nilm-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:7px;flex:1;min-height:200px}
.nc{border:1px solid var(--line);border-radius:7px;padding:7px 9px;background:var(--paper-2);display:flex;flex-direction:column;min-height:90px;position:relative;transition:border-color .3s,background .3s}
.nc.on{border-color:var(--c);background:color-mix(in srgb,var(--c) 7%,var(--paper-2))}
.nc-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px}
.nc-gly{width:13px;height:13px;color:var(--c);flex-shrink:0}
.nc.off .nc-gly{color:var(--ink-3)}
.nc-state{width:6px;height:6px;border-radius:50%;background:var(--c);box-shadow:0 0 0 1.5px color-mix(in srgb,var(--c) 30%,transparent)}
.nc.off .nc-state{background:var(--ink-3);box-shadow:none}
.nc-name{font-family:var(--mono);font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-2);margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nc-watt{font-family:var(--mono);font-size:13px;font-weight:800;line-height:1;color:var(--c);margin-bottom:3px}
.nc.off .nc-watt{color:var(--ink-3)}
.nc-circuit{font-family:var(--mono);font-size:7.5px;color:var(--ink-3);letter-spacing:.04em;margin-bottom:4px}
.nc-conf{display:flex;align-items:center;gap:4px;margin-top:auto}
.nc-conf .cb{flex:1;height:2.5px;background:var(--line-soft);border-radius:1.5px;overflow:hidden}
.nc-conf .cf{height:100%;background:var(--c);border-radius:1.5px}
.nc-conf .cp{font-family:var(--mono);font-size:7px;color:var(--ink-3);font-weight:700}
.nc.off .cf{background:var(--ink-3)}
.nilm-empty{grid-column:1/-1;font-family:var(--mono);font-size:10px;color:var(--ink-3);padding:18px;text-align:center}

.wtou-content{display:grid;grid-template-columns:240px 1fr;gap:10px;flex:1;min-height:0}
.wcol{display:flex;flex-direction:column;gap:5px;min-height:0}
.weather-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;flex:1;min-height:0}
.weather-grid .wstat{min-height:70px}
.wstat{background:var(--paper-2);border:1px solid var(--line-soft);border-radius:7px;padding:5px 9px;display:flex;align-items:center;gap:7px;flex:1;min-height:0}
.wstat-gly{width:18px;height:18px;color:var(--c);flex-shrink:0}
.wstat-body{flex:1;min-width:0}
.wstat .wl{font-family:var(--mono);font-size:7.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-3);margin-bottom:1px;font-weight:600}
.wstat .wv{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--ink);line-height:1.1}
.wstat .wu{font-family:var(--mono);font-size:8.5px;color:var(--ink-3);margin-left:2px}

.tou-block{background:var(--paper-2);border:1px solid var(--line-soft);border-radius:7px;padding:8px 11px;flex:1;min-height:0;display:flex;flex-direction:column}
.tou-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;flex-shrink:0}
.tou-head-left{display:flex;align-items:center;gap:9px}
.tou-pill{padding:3px 10px;border-radius:14px;font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.08em;border:1.5px solid;background:var(--paper)}
.tou-pill.peak{border-color:var(--bad);color:var(--bad)}
.tou-pill.off{border-color:var(--ok);color:var(--ok)}
.tou-pill.super{border-color:var(--info);color:var(--info)}
.tou-pill.partial{border-color:var(--warn);color:var(--warn)}
.tou-rate{font-family:var(--mono);font-size:11.5px;color:var(--ink);font-weight:700}
.tou-next{font-family:var(--mono);font-size:9px;color:var(--ink-3)}
.tou-graph-wrap{flex:1;min-height:0;position:relative}
.tou-graph{width:100%;height:100%}
.tou-legend{display:flex;flex-wrap:wrap;gap:8px;font-family:var(--mono);font-size:8px;color:var(--ink-2);margin-top:3px;flex-shrink:0}
.tou-legend-item{display:flex;align-items:center;gap:3px}
.tou-legend-sw{width:10px;height:7px;border-radius:2px}

.dss-list{display:flex;flex-direction:column;gap:6px;flex:1;min-height:200px;overflow-y:auto;padding-right:2px}
.dss-rec{border:1px solid var(--line);border-radius:7px;padding:7px 10px;display:grid;grid-template-columns:22px 1fr;gap:9px;align-items:start;background:var(--paper-2);position:relative}
.dss-rec.urgent{border-color:var(--bad);background:color-mix(in srgb,var(--bad) 5%,var(--paper-2))}
.dss-rec.advisory{border-color:var(--warn);background:color-mix(in srgb,var(--warn) 5%,var(--paper-2))}
.dss-rec.info{border-color:var(--info);background:color-mix(in srgb,var(--info) 5%,var(--paper-2))}
.dss-rec.ok{border-color:var(--ok);background:color-mix(in srgb,var(--ok) 5%,var(--paper-2))}
.dss-icon{width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:1.4px solid var(--rc);color:var(--rc);background:var(--paper);flex-shrink:0}
.dss-icon svg{width:10px;height:10px}
.dss-body .dt{font-size:11px;font-weight:700;margin-bottom:1px;color:var(--ink);line-height:1.3;display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.dss-body .dt .amount{font-family:var(--mono);font-size:10.5px;color:var(--rc);font-weight:800;flex-shrink:0}
.dss-body .dd{font-size:9.5px;color:var(--ink-2);line-height:1.4}
.dss-body .dm{font-family:var(--mono);font-size:8.5px;color:var(--rc);margin-top:3px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}
.dss-actions{display:flex;gap:4px;margin-top:5px}
.dss-btn{font-family:var(--mono);font-size:8px;padding:2.5px 7px;border-radius:4px;border:1px solid var(--line);cursor:pointer;background:var(--paper);color:var(--ink-2);font-weight:600;letter-spacing:.06em;text-transform:uppercase}
.dss-btn:hover{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.dss-empty{font-family:var(--mono);font-size:10px;color:var(--ink-3);padding:18px;text-align:center}

::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:2px}
::-webkit-scrollbar-track{background:transparent}
</style>
</head>
<body>

<div class="hdr">
  <div>
    <div class="badge"><div class="dot" id="dot"></div><span id="stxt">CONNECTING…</span><span class="mode-pill" id="nilm-mode">ONNX</span></div>
    <h1>IEMS · Los Gatos Microgrid</h1>
    <div class="sub">eGauge18646 · AnyLog · ONNX disaggregator · Adabi DSS</div>
  </div>
  <div class="poll"><div id="pt">--:--:--</div><small id="dt">—</small></div>
</div>

<div class="errbar" id="errbar"></div>

<!-- KPI strip -->
<div class="kpis">
  <div class="kpi" style="--c:var(--grid)">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1 L3 8 L7 8 L6 13 L11 6 L7 6 Z"/></svg>Grid Power</div>
    <div class="val" id="kg">—</div><div class="hint" id="kgh">—</div>
  </div>
  <div class="kpi" style="--c:var(--hvac)">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M7 1 V13 M1 7 H13 M2.5 2.5 L11.5 11.5 M11.5 2.5 L2.5 11.5"/></svg>Panel1 HVAC</div>
    <div class="val" id="kh">—</div><div class="hint" id="khh">—</div>
  </div>
  <div class="kpi" style="--c:var(--h2o)">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M7 1 C 4 5 3 7 3 9 A4 4 0 0 0 11 9 C 11 7 10 5 7 1 Z"/></svg>Panel2 H2O</div>
    <div class="val" id="kw">—</div><div class="hint" id="kwh">—</div>
  </div>
  <div class="kpi" style="--c:var(--kit)">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><circle cx="7" cy="8" r="4.5"/><path d="M2.5 8 H11.5 M5 4 V2 M9 4 V2"/></svg>Panel3 Kitchen</div>
    <div class="val" id="kk">—</div><div class="hint" id="kkh">—</div>
  </div>
  <div class="kpi" style="--c:var(--shop)">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><circle cx="7" cy="7" r="5"/><circle cx="7" cy="7" r="2"/></svg>Shop / Dryer</div>
    <div class="val" id="ks">—</div><div class="hint" id="ksh">—</div>
  </div>
  <div class="kpi" style="--c:var(--gen)">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="2" y="3" width="9" height="8" rx="1"/><rect x="11" y="5" width="2" height="4"/></svg>Generac</div>
    <div class="val" id="kgn">—</div><div class="hint" id="kgnh">standby</div>
  </div>
  <div class="kpi" style="--c:#caa12e">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="7" cy="7" r="3"/><path d="M7 1V2 M7 12V13 M1 7H2 M12 7H13 M3 3l.8.8 M10.2 10.2l.8.8 M11 3l-.8.8 M3.8 10.2l-.8.8"/></svg>Solar (est.)</div>
    <div class="val" id="ksol">—</div><div class="hint" id="ksolh">—</div>
  </div>
  <div class="kpi" style="--c:var(--sa)">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="7" cy="7" r="3"/><path d="M7 1V2 M7 12V13 M1 7H2 M12 7H13 M3 3l.8.8 M10.2 10.2l.8.8 M11 3l-.8.8 M3.8 10.2l-.8.8"/></svg>Solar Assistant (measured)</div>
    <div class="val" id="ksa">—</div><div class="hint" id="ksah">—</div>
  </div>
  <div class="kpi" style="--c:#4a8a5a">
    <div class="lbl"><svg class="kpi-glyph" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="2" y="4" width="9" height="6" rx="1"/><rect x="11" y="6" width="1.5" height="2"/></svg>Battery SOC</div>
    <div class="val" id="kbat">—</div><div class="hint" id="kbath">13.5 kWh · 10% floor</div>
  </div>
</div>

<!-- Controls -->
<div class="ctrl">
  <label>Mode</label>
  <select id="sel-mode">
    <option value="on_grid">on_grid</option>
    <option value="off_grid">off_grid</option>
    <option value="export">export</option>
  </select>
  <label>NILM</label>
  <div class="toggle" id="nilm-toggle">
    <button data-v="onnx" class="active">ONNX</button>
    <button data-v="ollama">Ollama</button>
  </div>
  <label>Window</label>
  <input type="number" id="sel-win" value="10" min="2" max="60" style="width:48px"> <span style="font-family:var(--mono);font-size:9px;color:var(--ink-3)">min</span>
  <button class="btn" id="run-btn">▷ Run IEMS Cycle</button>
  <span class="cycstat" id="cycle-status">no cycle yet</span>
</div>

<!-- Tab bar -->
<div class="tabs">
  <button class="tab-btn active" data-tab="general">General</button>
  <button class="tab-btn" data-tab="weather">Weather</button>
  <button class="tab-btn" data-tab="appliances">Appliances</button>
</div>

<!-- General tab: panel KPIs (above), raw power, dss, TOU/forecast -->
<div class="tab-panel active" id="tab-general">
<div class="gridmain">

  <!-- Raw Power -->
  <div class="region r-power">
    <h2><svg class="gly" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 11 L4 7 L7 9 L10 4 L13 6"/><path d="M1 13 H13"/></svg>
      Raw Power Telemetry  ·  last 30 min
      <span class="tag" id="pwr-age">—</span>
    </h2>
    <div class="pwr-content">

      <div class="pwr-stat-row">
        <div class="pwr-stat" style="--c:var(--grid)"><div class="lbl">Σ Demand</div><div class="val" id="stat-sum">—</div></div>
        <div class="pwr-stat" style="--c:var(--ok)"><div class="lbl">Σ 30min</div><div class="val" id="stat-kwh">—</div></div>
        <div class="pwr-stat" style="--c:var(--bad)"><div class="lbl">Peak</div><div class="val" id="stat-peak">—</div></div>
        <div class="pwr-stat" style="--c:var(--ink-2)"><div class="lbl">Avg</div><div class="val" id="stat-avg">—</div></div>
      </div>
    </div>
  </div>

  <!-- DSS -->
  <div class="region r-dss">
    <h2><svg class="gly" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><polygon points="7,1 13,7 7,13 1,7"/><path d="M7 4 V10 M4 7 H10"/></svg>
      DSS Recommendations
      <span class="tag" id="dss-branch">—</span>
    </h2>
    <div class="dss-list" id="dss-list"><div class="dss-empty">Run an IEMS cycle to get recommendations.</div></div>
  </div>

  <!-- PG&E TOU schedule & forecast load -->
  <div class="region r-tou">
    <h2><svg class="gly" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="5" cy="6" r="2"/><path d="M5 1 V2.5 M1 6 H2.5"/><path d="M7 11 A3 3 0 1 1 13 11 H7 Z" fill="none"/></svg>
      PG&amp;E E6 TOU schedule  &amp;  forecast load
      <span class="tag" id="wtou-age">—</span>
    </h2>
    <div class="tou-block">
      <div class="tou-head">
        <div class="tou-head-left">
          <div class="tou-pill" id="tou-pill">—</div>
          <div class="tou-rate" id="tou-rate">—</div>
        </div>
        <div class="tou-next" id="tou-info">—</div>
      </div>
      <div class="tou-graph-wrap"><svg class="tou-graph" id="tou-graph" viewBox="0 0 600 130" preserveAspectRatio="none"></svg></div>
      <div class="tou-legend">
        <span class="tou-legend-item"><span class="tou-legend-sw" style="background:#4a6b8a;opacity:.5"></span>Super off</span>
        <span class="tou-legend-item"><span class="tou-legend-sw" style="background:#5e8a5a;opacity:.55"></span>Off-peak</span>
        <span class="tou-legend-item"><span class="tou-legend-sw" style="background:#c89a3a;opacity:.6"></span>Partial</span>
        <span class="tou-legend-item"><span class="tou-legend-sw" style="background:#a64f3a;opacity:.7"></span>Peak</span>
        <span class="tou-legend-item" style="margin-left:auto"><span class="tou-legend-sw" style="background:#2a241c;height:2px"></span>$/kWh</span>
      </div>
    </div>
  </div>

</div>
</div>

<!-- Weather tab -->
<div class="tab-panel" id="tab-weather">
  <div class="region r-weather-tab">
    <h2><svg class="gly" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="5" cy="6" r="2"/><path d="M5 1 V2.5 M1 6 H2.5"/><path d="M7 11 A3 3 0 1 1 13 11 H7 Z" fill="none"/></svg>
      Weather
    </h2>
    <div class="weather-grid">
      <div class="wstat" style="--c:var(--bad)">
        <svg class="wstat-gly" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="3.5"/><path d="M12 2 V5 M12 19 V22 M2 12 H5 M19 12 H22"/></svg>
        <div class="wstat-body"><div class="wl">Temp</div><div class="wv" id="w-temp">—<span class="wu">°F</span></div></div>
      </div>
      <div class="wstat" style="--c:var(--info)">
        <svg class="wstat-gly" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M6 16 A4 4 0 1 1 9 8 A5 5 0 0 1 19 11 A4 4 0 0 1 18 18 H7 A3 3 0 0 1 6 16 Z"/></svg>
        <div class="wstat-body"><div class="wl">Cloud</div><div class="wv" id="w-cloud">—<span class="wu">%</span></div></div>
      </div>
      <div class="wstat" style="--c:var(--warn)">
        <svg class="wstat-gly" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="4"/></svg>
        <div class="wstat-body"><div class="wl">Irradiance</div><div class="wv" id="w-irr">—<span class="wu">W/m²</span></div></div>
      </div>
      <div class="wstat" style="--c:var(--ok)">
        <svg class="wstat-gly" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8 H14 A3 3 0 1 0 11 5 M3 13 H18 A3 3 0 1 1 15 16"/></svg>
        <div class="wstat-body"><div class="wl">Wind</div><div class="wv" id="w-wind">—<span class="wu">mph</span></div></div>
      </div>
    </div>
  </div>
</div>

<!-- Appliances tab -->
<div class="tab-panel" id="tab-appliances">
  <div class="region r-nilm">
    <h2><svg class="gly" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="3.5" cy="3.5" r="1.8"/><circle cx="10.5" cy="3.5" r="1.8"/><circle cx="3.5" cy="10.5" r="1.8"/><circle cx="10.5" cy="10.5" r="1.8"/><path d="M3.5 5.3 V8.7 M10.5 5.3 V8.7 M5.3 3.5 H8.7 M5.3 10.5 H8.7"/></svg>
      NILM Disaggregator  ·  14 appliances inferred from 6 panels
      <span class="tag" id="nilm-age">—</span>
    </h2>
    <div class="nilm-grid" id="nilm-grid"><div class="nilm-empty">No predictions yet — run a cycle to populate.</div></div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id)

/* ── Tabs ── */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'))
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'))
    btn.classList.add('active')
    $('tab-' + btn.dataset.tab).classList.add('active')
  }
})

/* ── PANEL META ── */
const PANELS = [
  {nm:'Grid Power',      key:'g',  c:'#b85c2e', max:8000, onW:50},
  {nm:'Panel1 (HVAC)',   key:'h',  c:'#4a6b8a', max:6000, onW:1000},
  {nm:'Panel2 (H2O)',    key:'w',  c:'#8a5a7a', max:4000, onW:200},
  {nm:'Panel3 (Kitchen)',key:'k',  c:'#5e8a5a', max:2500, onW:300},
  {nm:'Shop',            key:'s',  c:'#c89a3a', max:7500, onW:100},
  {nm:'Generac Power',   key:'gn', c:'#a17a28', max:5000, onW:10},
]

/* ── 14-appliance NILM catalog (abstract SVG glyphs, no emoji) ── */
const NILM_APPLIANCES = [
  {key:'heat_pump',       label:'Heat Pump',     circuit:'Panel1 (HVAC)',    model:'panel1', c:'#4a6b8a',
    glyph:'<circle cx="7" cy="7" r="5"/><path d="M3 5 L11 9 M3 9 L11 5"/>'},
  {key:'solar_pump',      label:'Solar Pump',    circuit:'Panel1 (HVAC)',    model:'panel1', c:'#a17a28',
    glyph:'<circle cx="7" cy="7" r="3"/><path d="M7 1 V3 M7 11 V13 M1 7 H3 M11 7 H13"/>'},
  {key:'water_heater',    label:'Water Heater',  circuit:'Panel2 (H2O)',     model:'panel2', c:'#8a5a7a',
    glyph:'<path d="M7 1 C 4 5 3 7 3 9 A4 4 0 0 0 11 9 C 11 7 10 5 7 1 Z"/>'},
  {key:'hair_dryer',      label:'Hair Dryer',    circuit:'Panel2 (H2O)',     model:'panel2', c:'#8a5a7a',
    glyph:'<path d="M2 5 H8 L10 4 V10 L8 9 H2 Z M8 7 H12"/>'},
  {key:'sprinklers',      label:'Sprinklers',    circuit:'Panel2 (H2O)',     model:'panel2', c:'#8a5a7a',
    glyph:'<path d="M3 12 H11 M5 12 V8 M7 12 V6 M9 12 V8"/>'},
  {key:'bath_lights',     label:'Bath Lights',   circuit:'Panel2 (H2O)',     model:'panel2', c:'#8a5a7a',
    glyph:'<path d="M7 2 A 3.5 3.5 0 0 1 10 8 L9 10 H5 L4 8 A 3.5 3.5 0 0 1 7 2 Z M5 11 H9"/>'},
  {key:'refrigerator',    label:'Refrigerator',  circuit:'Panel3 (Kitchen)', model:'panel3', c:'#5e8a5a',
    glyph:'<rect x="3" y="2" width="8" height="11" rx="1"/><line x1="3" y1="6.5" x2="11" y2="6.5"/>'},
  {key:'dishwasher',      label:'Dishwasher',    circuit:'Panel3 (Kitchen)', model:'panel3', c:'#5e8a5a',
    glyph:'<rect x="2.5" y="2" width="9" height="11" rx="1"/><line x1="2.5" y1="4.5" x2="11.5" y2="4.5"/><circle cx="7" cy="9" r="2.5"/>'},
  {key:'microwave',       label:'Microwave',     circuit:'Panel3 (Kitchen)', model:'panel3', c:'#5e8a5a',
    glyph:'<rect x="1.5" y="3" width="11" height="8" rx="1"/><rect x="3" y="4.5" width="6" height="5"/>'},
  {key:'computers',       label:'Computers',     circuit:'Panel3 (Kitchen)', model:'panel3', c:'#5e8a5a',
    glyph:'<rect x="2" y="3" width="10" height="6" rx="1"/><path d="M1 12 H13"/>'},
  {key:'tv_stereo',       label:'TV / Stereo',   circuit:'Panel3 (Kitchen)', model:'panel3', c:'#5e8a5a',
    glyph:'<rect x="1.5" y="3" width="11" height="7" rx="1"/><path d="M5 12 H9"/>'},
  {key:'dryer',           label:'Dryer',         circuit:'Shop',             model:'panel3', c:'#c89a3a',
    glyph:'<rect x="2.5" y="2" width="9" height="11" rx="1"/><circle cx="7" cy="8.5" r="3"/><circle cx="7" cy="8.5" r="1"/>'},
  {key:'washing_machine', label:'Washer',        circuit:'Shop',             model:'panel3', c:'#c89a3a',
    glyph:'<rect x="2.5" y="2" width="9" height="11" rx="1"/><circle cx="7" cy="8" r="3"/>'},
  {key:'pressure_pump',   label:'Pressure Pump', circuit:'Shop',             model:'panel3', c:'#c89a3a',
    glyph:'<circle cx="7" cy="8" r="3.5"/><path d="M7 4.5 V2 M5 2 H9"/>'},
]

const prevStates = {}
let lastCycleResult = null
let cycleRunning = false
let nilmBackend = 'onnx'

/* ── Formatters ── */
const fW  = w => Math.abs(w) >= 1000 ? (Math.abs(w)/1000).toFixed(2)+' kW' : Math.round(Math.abs(w))+' W'
const sT  = ts => {
  if (!ts) return '—'
  const d = new Date(ts.includes && ts.includes('T') ? ts : (ts+'').replace(' ','T')+'Z')
  return d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})
}
const fmtAge = sec => {
  if (sec < 60) return sec + 's'
  if (sec < 3600) return Math.floor(sec/60) + 'm'
  return Math.floor(sec/3600) + 'h'
}
const fAge = ts => {
  if (!ts) return '—'
  const t = new Date(ts.includes && ts.includes('T') ? ts : (ts+'').replace(' ','T')+'Z').getTime()
  const s = Math.round((Date.now() - t) / 1000)
  return s < 60 ? s+'s ago' : Math.floor(s/60)+'m ago'
}

/* ── KPI hint ── */
function hint(p, w) {
  const aw = Math.abs(w)
  if (p.nm === 'Grid Power') return w < -20 ? '↓ exporting' : w > 20 ? '▲ importing' : 'balanced'
  return aw >= p.onW ? 'ON' : aw > 20 ? 'standby' : 'off'
}

/* ── Snapshot polling — drives KPIs ── */
async function pollSnapshot() {
  try {
    const snap = await fetch('/api/snapshot').then(r => r.json())
    let newestTs = ''
    let count = 0
    PANELS.forEach(p => {
      const v = snap[p.nm]; if (!v) return
      count++
      if (v.ts > newestTs) newestTs = v.ts
      const w = v.w
      $('k'+p.key).textContent = fW(w)
      const h = hint(p, w)
      const hel = $('k'+p.key+'h'); hel.textContent = h
      hel.className = 'hint ' + (h.startsWith('▲') ? 'up' : h.startsWith('↓') ? 'down' : '')
    })
    // Color-code badge based on data lag — never go blank just because data is slow.
    let ageSec = 9999
    if (newestTs) ageSec = Math.round((Date.now() - new Date((newestTs+'').replace(' ','T')+'Z').getTime()) / 1000)
    const dotEl = $('dot')
    if (count === 0) {
      dotEl.className = 'dot err'
      $('stxt').textContent = 'NO DATA · check ingestion'
    } else if (ageSec > 300) {
      dotEl.className = 'dot err'
      $('stxt').textContent = 'STALE · ' + count + ' ch · ' + fmtAge(ageSec) + ' old'
    } else if (ageSec > 60) {
      dotEl.className = 'dot warn'
      $('stxt').textContent = 'LAGGING · ' + count + ' ch · ' + fmtAge(ageSec) + ' old'
    } else {
      dotEl.className = 'dot'
      $('stxt').textContent = 'LIVE · ' + count + ' ch · ' + fmtAge(ageSec)
    }
    $('pt').textContent = new Date().toLocaleTimeString()
    if (newestTs) $('dt').textContent = 'data: ' + sT(newestTs)
    $('errbar').className = 'errbar'
  } catch (e) {
    $('dot').className = 'dot err'
    $('stxt').textContent = 'OFFLINE'
    $('errbar').className = 'errbar show'
    $('errbar').textContent = 'Power feed offline — ' + e.message
  }
  setTimeout(pollSnapshot, 3000)
}

/* ── History → SVG line graph ── */
async function pollHistory() {
  try {
    const rows = await fetch('/api/history?minutes=30').then(r => r.json())
    renderPwrGraph(rows)
  } catch {}
  setTimeout(pollHistory, 10000)
}

function renderPwrGraph(rows) {
  const ids = ['stat-sum','stat-kwh','stat-peak','stat-avg']
  if (!rows || rows.length === 0) {
    ids.forEach(id => { const e = $(id); if (e) e.textContent = '\u2014' })
    const a = $('pwr-age'); if (a) a.textContent = 'no data'
    return
  }
  const series = {}
  let tMax = -Infinity
  rows.forEach(r => {
    const t = new Date((r.ts+'').replace(' ','T')+'Z').getTime()
    if (!series[r.nm]) series[r.nm] = []
    series[r.nm].push({ t, w: parseFloat(r.w) || 0 })
    if (t > tMax) tMax = t
  })
  let sumW = 0, peakW = 0, n = 0
  Object.values(series).forEach(arr => arr.forEach(pt => {
    sumW += Math.abs(pt.w); if (Math.abs(pt.w) > peakW) peakW = Math.abs(pt.w); n++
  }))
  const avgW = n > 0 ? sumW / n : 0
  const lastByPanel = Object.fromEntries(Object.entries(series).map(([k, arr]) => [k, arr[arr.length-1].w]))
  const currentDemand = PANELS.slice(1, 5).reduce((acc, p) => acc + Math.abs(lastByPanel[p.nm] || 0), 0) + Math.abs(lastByPanel['Shop'] || 0)
  const kwh = avgW * 0.5 / 1000
  $('stat-sum').textContent  = fW(currentDemand)
  $('stat-kwh').textContent  = kwh.toFixed(2) + ' kWh'
  $('stat-peak').textContent = fW(peakW)
  $('stat-avg').textContent  = fW(avgW)
  if (tMax > 0) $('pwr-age').textContent = 'live \u00b7 ' + sT(new Date(tMax).toISOString())
}

let MODEL_META = {}
fetch('/api/model-meta').then(r => r.json()).then(m => { MODEL_META = m || {} }).catch(() => {})
function metaLine(a) {
  const m = MODEL_META[a.key] || {}
  let s = a.model + '.onnx'
  if (m.thr != null) s += ' · thr ' + Math.round(m.thr * 100) + '%'
  if (m.f1  != null) s += ' · F1 ' + Number(m.f1).toFixed(2)
  return s
}
/* ── NILM polling ── */
async function pollNilm() {
  try {
    const rows = await fetch('/api/nilm').then(r => r.json())
    renderNilm(rows)
  } catch {}
  setTimeout(pollNilm, 15000)
}

function renderNilm(rows) {
  if (!rows || rows.length === 0) {
    $('nilm-grid').innerHTML = NILM_APPLIANCES.map(a => emptyCard(a)).join('')
    $('nilm-age').textContent = 'awaiting cycle'
    return
  }
  const latest = {}
  rows.forEach(r => { if (!latest[r.appliance] || r.ts > latest[r.appliance].ts) latest[r.appliance] = r })
  const newestTs = rows.reduce((a, r) => r.ts > a ? r.ts : a, '')
  const ageSec = newestTs ? Math.round((Date.now() - new Date((newestTs+'').replace(' ','T')+'Z').getTime()) / 1000) : 9999
  const ageCls = ageSec > 300 ? 'bad' : ageSec > 90 ? 'warn' : 'ok'
  $('nilm-age').textContent = fAge(newestTs)
  $('nilm-age').className = 'tag ' + ageCls
  $('nilm-grid').innerHTML = NILM_APPLIANCES.map(a => {
    const r = latest[a.key]
    const on = r && (r.state === 'ON' || r.state === 'on' || r.state === '1' || r.state === 1 || r.state === true)
    const w = r ? parseFloat(r.avg_w) || 0 : 0
    const conf = r ? Math.round((parseFloat(r.confidence) || 0) * 100) : 0
    return '<div class="nc '+(on?'on':'off')+'" style="--c:'+a.c+'">' +
      '<div class="nc-head"><svg class="nc-gly" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5">'+a.glyph+'</svg><div class="nc-state"></div></div>' +
      '<div class="nc-name">'+a.label+'</div>' +
      '<div class="nc-watt" title="On/off state inferred by the model">'+(on ? 'ON' : 'OFF')+'</div>' +
      '<div class="nc-circuit" title="decision threshold and held-out test F1">'+metaLine(a)+'</div>' +
      '<div class="nc-conf"><div class="cb"><div class="cf" style="width:'+conf+'%"></div></div><div class="cp">'+conf+'%</div></div>' +
    '</div>'
  }).join('')
}

function emptyCard(a) {
  return '<div class="nc off" style="--c:'+a.c+'">' +
    '<div class="nc-head"><svg class="nc-gly" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5">'+a.glyph+'</svg><div class="nc-state"></div></div>' +
    '<div class="nc-name">'+a.label+'</div>' +
    '<div class="nc-watt">—</div>' +
    '<div class="nc-circuit">'+metaLine(a)+'</div>' +
    '<div class="nc-conf"><div class="cb"><div class="cf" style="width:0%"></div></div><div class="cp">—</div></div>' +
  '</div>'
}
renderNilm([])  // bootstrap empty cards

/* ── Weather (Open-Meteo) ── */
async function pollWeather() {
  try {
    const lat = 37.2358, lon = -121.9624
    const url = 'https://api.open-meteo.com/v1/forecast?latitude='+lat+'&longitude='+lon+'&current=temperature_2m,cloud_cover,wind_speed_10m,shortwave_radiation&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FLos_Angeles'
    const d = await fetch(url).then(r => r.json())
    const c = d.current || {}
    if (c.temperature_2m !== undefined)     $('w-temp').innerHTML  = (c.temperature_2m).toFixed(1) + '<span class="wu">°F</span>'
    if (c.cloud_cover !== undefined)        $('w-cloud').innerHTML = c.cloud_cover + '<span class="wu">%</span>'
    if (c.shortwave_radiation !== undefined)$('w-irr').innerHTML   = c.shortwave_radiation + '<span class="wu">W/m²</span>'
    if (c.wind_speed_10m !== undefined)     $('w-wind').innerHTML  = c.wind_speed_10m.toFixed(1) + '<span class="wu">mph</span>'
    $('wtou-age').textContent = sT(new Date().toISOString())
  } catch {}
  setTimeout(pollWeather, 300000)
}

/* ── TOU pill + graph ── */
function classifyTOU(date) {
  const h = date.getHours(), dow = date.getDay(), mon = date.getMonth() + 1
  const summer = mon >= 5 && mon <= 10
  const weekday = dow >= 1 && dow <= 5
  if (weekday && h >= 15 && h < 19) return summer ? {p:'PEAK',r:0.51,cls:'peak'} : {p:'PEAK',r:0.30,cls:'peak'}
  if (weekday && ((h >= 10 && h < 13) || (h >= 19 && h < 21))) return {p:'PARTIAL',r:summer?0.30:0.20,cls:'partial'}
  if (h < 9 || h >= 21) return {p:'SUPER OFF',r:0.19,cls:'super'}
  return {p:'OFF-PEAK',r:summer?0.26:0.18,cls:'off'}
}

function renderTOU() {
  const now = new Date()
  const cur = classifyTOU(now)
  $('tou-pill').textContent = cur.p
  $('tou-pill').className = 'tou-pill ' + cur.cls
  $('tou-rate').innerHTML = '$' + cur.r.toFixed(2) + '<span style="color:var(--ink-3);font-size:9px">/kWh</span>'

  // Compute next transition for "next" label
  let nxt = ''
  for (let dh = 1; dh <= 12; dh++) {
    const f = new Date(now.getTime() + dh*3600*1000)
    const nc = classifyTOU(f)
    if (nc.p !== cur.p) { nxt = '→ ' + nc.p + ' ' + String(f.getHours()).padStart(2,'0') + ':00  (' + dh + 'h)'; break }
  }
  $('tou-info').textContent = nxt || (now.getMonth()+1>=5 && now.getMonth()+1<=10 ? 'Summer' : 'Winter') + ' · PG&E E6'

  // Build TOU graph: 24-hour bands + forecast load
  const svg = $('tou-graph')
  let out = ''
  // axes / gridlines
  out += '<g font-family="JetBrains Mono" font-size="7.5" fill="#8a7d68">' +
    '<text x="32" y="18" text-anchor="end">$0.50</text>' +
    '<text x="32" y="50" text-anchor="end">$0.35</text>' +
    '<text x="32" y="82" text-anchor="end">$0.20</text>' +
    '<text x="32" y="110" text-anchor="end">$0.10</text></g>'
  out += '<g font-family="JetBrains Mono" font-size="7.5" fill="#8a7d68">'
  for (let h=0; h<=24; h+=4) out += '<text x="'+(40 + h*525/24)+'" y="125" text-anchor="middle">'+String(h).padStart(2,'0')+'</text>'
  out += '</g>'
  out += '<g stroke="#c9bea3" stroke-width=".5" opacity=".4">' +
    '<line x1="40" y1="16" x2="565" y2="16"/>' +
    '<line x1="40" y1="48" x2="565" y2="48"/>' +
    '<line x1="40" y1="80" x2="565" y2="80"/>' +
    '<line x1="40" y1="112" x2="565" y2="112"/></g>'

  // Build per-hour rate
  const baseDate = new Date(now); baseDate.setHours(0,0,0,0)
  const rates = []
  for (let h = 0; h < 24; h++) {
    const d = new Date(baseDate.getTime() + h*3600*1000)
    rates.push(classifyTOU(d))
  }
  const colorFor = {peak:'#a64f3a',partial:'#c89a3a',off:'#5e8a5a',super:'#4a6b8a'}
  const opFor = {peak:.42,partial:.38,off:.3,super:.25}
  // rate $→y: map $0.10→112, $0.51→22
  const yRate = r => 112 - ((r - 0.10) / (0.51 - 0.10)) * 90
  const xH = h => 40 + h * 525/24

  // rate bands (rect per hour, height to current line)
  for (let h = 0; h < 24; h++) {
    const r = rates[h], y = yRate(r.r)
    out += '<rect x="'+xH(h)+'" y="'+y+'" width="'+(525/24)+'" height="'+(112-y)+'" fill="'+colorFor[r.cls]+'" opacity="'+opFor[r.cls]+'"/>'
  }
  // rate stepped line
  let dline = 'M' + xH(0) + ',' + yRate(rates[0].r)
  for (let h = 1; h <= 24; h++) {
    const r = rates[Math.min(h, 23)].r
    dline += ' L' + xH(h) + ',' + yRate(rates[Math.min(h, 23)].r)
    if (h < 24) dline += ' L' + xH(h) + ',' + yRate(rates[h].r)
  }
  out += '<path d="'+dline+'" stroke="#2a241c" stroke-width="1.4" fill="none"/>'

  // forecast load curve removed — was a hardcoded bell shape, not a real prediction

  // now marker
  const nowFrac = now.getHours() + now.getMinutes()/60
  const nowX = xH(nowFrac)
  out += '<line x1="'+nowX+'" y1="16" x2="'+nowX+'" y2="116" stroke="#2a241c" stroke-width="1.4" stroke-dasharray="3 2"/>'
  out += '<circle cx="'+nowX+'" cy="'+yRate(cur.r)+'" r="3" fill="#2a241c"/>'
  out += '<text x="'+nowX+'" y="12" text-anchor="middle" font-family="JetBrains Mono" font-size="7.5" font-weight="700" fill="#2a241c">NOW · '+String(now.getHours()).padStart(2,'0')+':'+String(now.getMinutes()).padStart(2,'0')+'</text>'

  out += '<line x1="40" y1="116" x2="565" y2="116" stroke="#2a241c" stroke-width="1"/>'
  out += '<line x1="40" y1="14" x2="40" y2="116" stroke="#2a241c" stroke-width="1"/>'

  svg.innerHTML = out
}
setInterval(renderTOU, 60000)
renderTOU()

/* ── DSS ── */
function renderDss(result) {
  if (!result) return
  const recs = result.dss_recommendations || []
  $('dss-branch').textContent = result.flow_chart_branch || (recs.length ? 'branch '+recs.length : '—')
  if (recs.length === 0) {
    $('dss-list').innerHTML = '<div class="dss-empty">No actions required this cycle.</div>'
    return
  }
  $('dss-list').innerHTML = recs.map((r, i) => {
    const isAnomaly = r.is_anomaly || r.severity === 'critical' || r.severity === 'high'
    const savings = parseFloat(r.savings_dollars || 0)
    const c = isAnomaly ? 'urgent' : (savings > 0 ? 'advisory' : 'info')
    const rc = c === 'urgent' ? 'var(--bad)' : c === 'advisory' ? 'var(--warn)' : 'var(--info)'
    const icon = isAnomaly
      ? '<svg viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M7 2 L13 12 H1 Z M7 6 V9 M7 10.5 V11"/></svg>'
      : (savings > 0
        ? '<svg viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M7 2 V11 M3 7 L7 11 L11 7"/></svg>'
        : '<svg viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="7" cy="7" r="5"/><path d="M7 7 V10 M7 4 V4.5"/></svg>')
    const amount = savings > 0 ? '<span class="amount">+ $'+savings.toFixed(2)+'</span>' : ''
    return '<div class="dss-rec '+c+'" style="--rc:'+rc+'">' +
      '<div class="dss-icon">'+icon+'</div>' +
      '<div class="dss-body">' +
        '<div class="dt"><span>'+(r.action || r.label || 'Recommendation')+'</span>'+amount+'</div>' +
        '<div class="dd">'+(r.rationale || r.reason || r.message || '')+'</div>' +
        '<div class="dm">'+(r.audience || r.type || 'INFO').toUpperCase()+(r.confidence ? '  ·  '+Math.round(r.confidence*100)+'% conf' : '')+'</div>' +
        '<div class="dss-actions">' +
          '<button class="dss-btn" onclick="ackRec('+i+',\\'accept\\')">Accept</button>' +
          '<button class="dss-btn" onclick="ackRec('+i+',\\'defer\\')">Defer</button>' +
          '<button class="dss-btn" onclick="ackRec('+i+',\\'dismiss\\')">Dismiss</button>' +
        '</div>' +
      '</div>' +
    '</div>'
  }).join('')
}

window.ackRec = function(idx, action) {
  if (!lastCycleResult) return
  const recs = lastCycleResult.dss_recommendations || []
  const rec  = recs[idx]; if (!rec) return
  const id   = rec.id || ('rec_'+idx)
  fetch('http://localhost:8000/iems/recommendations/'+id+'/'+action, {method:'POST'}).catch(() => {})
  recs.splice(idx, 1)
  renderDss(lastCycleResult)
}

/* ── NILM backend toggle ── */
document.querySelectorAll('#nilm-toggle button').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('#nilm-toggle button').forEach(b => b.classList.remove('active'))
    btn.classList.add('active')
    nilmBackend = btn.dataset.v
    $('nilm-mode').textContent = nilmBackend.toUpperCase()
  }
})

/* ── Cycle ── */
$('run-btn').onclick = async () => {
  if (cycleRunning) return
  cycleRunning = true
  const btn = $('run-btn')
  btn.disabled = true
  btn.innerHTML = '<span class="spin">⟳</span> RUNNING…'
  $('cycle-status').innerHTML = '<span class="spin">⟳</span> calling backend…'
  const payload = {
    mode:           $('sel-mode').value,
    nilm_backend:   nilmBackend,
    llm_backend:    'ollama',
    llm_model:      'mistral:7b',
    window_minutes: parseInt($('sel-win').value),
  }
  try {
    const result = await fetch('/api/cycle', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    }).then(r => r.json())
    lastCycleResult = result
    const tag = (result.metadata?.nilm_backend || nilmBackend).toUpperCase()
    $('nilm-mode').textContent = tag
    renderDss(result)
    renderNilmFromCycle(result)
    const lat = result.metadata?.latency_ms ? (result.metadata.latency_ms/1000).toFixed(1)+'s' : ''
    $('cycle-status').textContent = '✓ ' + new Date().toLocaleTimeString() + (lat ? ' · '+lat : '')
  } catch (e) {
    $('cycle-status').textContent = '✗ ' + e.message
  }
  btn.disabled = false
  btn.textContent = '▷ Run IEMS Cycle'
  cycleRunning = false
}

function renderNilmFromCycle(result) {
  // Fetch real DB rows — never synthesize avg_w:0 placeholder rows.
  // The inference loop has already written fresh predictions; pull them honestly.
  fetch('/api/nilm').then(r => r.json()).then(renderNilm).catch(() => {})
}

async function pollStorage() {
  try {
    const s = await fetch('/api/storage').then(r => r.json())
    if (s.solar) {
      $('ksol').textContent = fW(s.solar.production_w)
      const exp = s.solar.exporting_w || 0
      const sh = $('ksolh')
      sh.textContent = exp > 20 ? '\u2191 export ' + fW(exp) : 'self-use ' + fW(s.solar.self_consumption_w)
      sh.className = 'hint ' + (exp > 20 ? 'up' : '')
    }
    const bel = $('kbat'), bh = $('kbath')
    if (s.battery) {
      bel.textContent = (s.battery.soc_pct).toFixed(1) + '%'
      const flow = s.battery.flow || 'idle'
      bh.textContent = flow + ' \u00b7 ' + s.battery.available_kwh + ' kWh avail'
      bh.className = 'hint ' + (flow === 'charging' ? 'up' : flow === 'discharging' ? 'down' : '')
    } else {
      bel.textContent = '\u2014'; bh.textContent = 'backend offline'; bh.className = 'hint'
    }
  } catch (e) {}
  setTimeout(pollStorage, 5000)
}

async function pollSolarAssistant() {
  try {
    const sa = await fetch('/api/solar-assistant').then(r => r.json())
    const el = $('ksa'), h = $('ksah')
    if (sa.connected) {
      el.textContent = fW(sa.pv_power_w)
      const parts = [
        (sa.battery_power_w >= 0 ? 'batt +' : 'batt ') + fW(sa.battery_power_w),
        sa.battery_soc_pct.toFixed(0) + '% soc',
        'load ' + fW(sa.load_power_w),
      ]
      if (sa.age_s != null && sa.age_s > 120) parts.push(sa.age_s + 's old')
      h.textContent = parts.join(' \u00b7 ')
      h.className = 'hint ' + (sa.age_s != null && sa.age_s > 120 ? 'down' : '')
    } else {
      el.textContent = '\u2014'; h.textContent = 'no Solar Assistant data'; h.className = 'hint'
    }
  } catch (e) {}
  setTimeout(pollSolarAssistant, 5000)
}

/* \u2500\u2500 Boot \u2500\u2500 */
pollSnapshot()
pollHistory()
pollNilm()
pollWeather()
pollStorage()
pollSolarAssistant()
</script>
</body>
</html>`
