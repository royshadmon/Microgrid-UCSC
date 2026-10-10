#!/usr/bin/env python3
"""Add 24 h history, the 24 h tab, the anomaly detector and Pacific-time TOU to server.js.

Every edit is anchored on exact text and asserts it matched once, so a changed
source fails loudly instead of being half-patched.
Usage: patch_server.py <server.js> <dir with server_block.js client_block.js tab.html>
"""
import os
import sys

src, d = sys.argv[1], sys.argv[2]
s = open(src, encoding="utf-8").read()
read = lambda n: open(os.path.join(d, n), encoding="utf-8").read()


def once(old, new, label):
    global s
    n = s.count(old)
    assert n == 1, "%s: anchor found %d times" % (label, n)
    s = s.replace(old, new)


def replace_func(name, new_body, label):
    global s
    start = s.index("async function %s(" % name)
    end = s.index("\n}\n", start) + 3
    s = s[:start] + new_body + s[end:]


if "const CH_WHERE" in s:
    sys.exit("already patched")

# 1. network-routed AnyLog requests
once("function _alRequest(cmd, timeout = 20000) {",
     "function _alRequest(cmd, timeout = 20000, network = false) {", "alRequest signature")
once("      `command: ${cmd}`,\n      `Connection: close`,",
     "      `command: ${cmd}`,\n      ...(network ? ['destination: network'] : []),\n      `Connection: close`,",
     "alRequest header")

# 2. history handlers served from the rolling caches
replace_func("handleHistory", """async function handleHistory(res, params) {
  const { m, fine, agg } = rangeSpec(params.get('minutes') || '30')
  const src = fine ? H10 : M1, from = Date.now() - m * MIN_MS
  const out = []
  for (const nm of PANELS) {
    if (!src[nm]) continue
    for (const p of aggregate(src[nm], from, agg, ['w']))
      out.push({ ts: utcStr(p.t), nm, w: p.w, wmax: p.wmax, wmin: p.wmin })
  }
  out.sort((a, b) => a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0)
  json(res, out)
}
""", "handleHistory")
replace_func("handleSolarHistory", """async function handleSolarHistory(res, params) {
  const { m, fine, agg } = rangeSpec(params.get('minutes') || '180')
  const rows = aggregate(fine ? S10 : SM1, Date.now() - m * MIN_MS, agg, ['pv', 'batt', 'soc', 'load', 'grid'])
  json(res, rows.map(p => ({ ts: utcStr(p.t), pv: p.pv || 0, batt: p.batt || 0, soc: p.soc || 0,
    load: p.load || 0, grid: p.grid || 0 })))
}
""", "handleSolarHistory")

# 3. caches, NILM 24 h, detector
once("const server = http.createServer(", read("server_block.js") + "\nconst server = http.createServer(",
     "server block")

# 4. routes
once("    if (path === '/api/logs'          && req.method === 'GET')  return handleLogs(res, params)\n",
     "    if (path === '/api/logs'          && req.method === 'GET')  return handleLogs(res, params)\n"
     "    if (path === '/api/nilm-24h'      && req.method === 'GET')  return handleNilm24(res)\n"
     "    if (path === '/api/detect-preview' && req.method === 'GET') return handleDetectPreview(res)\n",
     "routes")

# 5. CSS, tab button, tab panel
once(".r-nilm{flex:1 0 auto}\n", ".r-nilm{flex:1 0 auto}\n"
     ".day-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:9px}\n"
     ".day-card{border:1px solid var(--line);border-radius:6px;padding:6px 8px 4px;background:var(--paper)}\n"
     ".day-h{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-size:11px}\n"
     ".day-h b{font-weight:600}\n"
     ".day-h span{font-family:var(--mono);font-size:9px;color:var(--ink-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n"
     ".day-card svg{width:100%;height:120px;display:block}\n", "css")
once('  <button class="tab-btn active" data-tab="general">General</button>\n',
     '  <button class="tab-btn active" data-tab="general">General</button>\n'
     '  <button class="tab-btn" data-tab="day">24 h</button>\n', "tab button")
once('<div class="tab-panel" id="tab-weather">', read("tab.html") + '<div class="tab-panel" id="tab-weather">',
     "tab panel")

# 6. client code
once("/* ── Source / link status strip ── */", read("client_block.js") + "/* ── Source / link status strip ── */",
     "client block")

# 7. TOU in Pacific wall-clock time whatever the viewer's timezone
once("const sT = ts => ts ? ptTime(ts) : '—'\n",
     "const sT = ts => ts ? ptTime(ts) : '—'\n"
     "// A Date whose local fields read as Pacific wall-clock time, for code that uses getHours().\n"
     "const ptWall = d => new Date(d.toLocaleString('en-US', { timeZone: PT_TZ }))\n", "ptWall")
once("const cur = classifyTOU(now)", "const cur = classifyTOU(ptWall(now))", "tou cur")
once("const nc = classifyTOU(f)", "const nc = classifyTOU(ptWall(f))", "tou next")
once("String(f.getHours())", "String(ptWall(f).getHours())", "tou next hour")
once("(now.getMonth()+1>=5 && now.getMonth()+1<=10 ?", "(ptWall(now).getMonth()+1>=5 && ptWall(now).getMonth()+1<=10 ?", "tou season")
once("const baseDate = new Date(now); baseDate.setHours(0,0,0,0)", "const baseDate = ptWall(now); baseDate.setHours(0,0,0,0)", "tou base")
once("const nowFrac = now.getHours() + now.getMinutes()/60",
     "const nowPT = ptWall(now), nowFrac = nowPT.getHours() + nowPT.getMinutes()/60", "tou now")
once("NOW · '+String(now.getHours()).padStart(2,'0')+':'+String(now.getMinutes()).padStart(2,'0')",
     "NOW · '+String(nowPT.getHours()).padStart(2,'0')+':'+String(nowPT.getMinutes()).padStart(2,'0')", "tou now label")

# 8. 24-hour clock: en-US with hour12:false prints midnight as 24:00, h23 prints 00:00
s = s.replace("hour12: false", "hourCycle: 'h23'")

open(src, "w", encoding="utf-8").write(s)
print("patched", src)
