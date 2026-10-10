#!/usr/bin/env python3
"""Fold the 24 h tab into the General tab: one range selector drives everything.

The main power chart gains house load, inverter grid flow and anomaly markers
(with the anomaly text in its hover readout). The per-series charts, the NILM
activity strip and the anomaly list move under it and follow the same range
buttons (30 m to 24 h) instead of a fixed 24 h.

Usage: patch_v2.py <server.js> <dir holding the v1 tab.html and client_block.js> <dir holding v2 blocks>
"""
import os
import sys

src, v1, v2 = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(src, encoding="utf-8").read()
rd = lambda d, n: open(os.path.join(d, n), encoding="utf-8").read()


def once(old, new, label):
    global s
    n = s.count(old)
    assert n == 1, "%s: anchor found %d times" % (label, n)
    s = s.replace(old, new)


if "refreshDetail" in s:
    sys.exit("already patched")

# 1. drop the separate tab
once('  <button class="tab-btn" data-tab="day">24 h</button>\n', "", "tab button")
once(rd(v1, "tab.html"), "", "tab panel")

# 2. the same content inside the General tab, below the power chart
once("  <!-- DSS -->\n", rd(v2, "general_regions.html") + "  <!-- DSS -->\n", "general regions")
once(".day-grid{", ".r-detail{grid-column:1 / -1;grid-row:3}.r-nilm24{grid-column:1 / -1;grid-row:4}"
     ".r-anom24{grid-column:1 / -1;grid-row:5}\n.day-grid{", "css")

# 3. client: range-driven detail replaces the fixed 24 h poller
# v1 applied hour12 -> hourCycle over the whole file after inserting its block
once(rd(v1, "client_block.js").replace("hour12: false", "hourCycle: 'h23'"), rd(v2, "client_block_v2.js"),
     "client block")
once("  SOL_ROWS = (sol && sol.length) ? sol : null\n  renderCombined()\n}",
     "  SOL_ROWS = (sol && sol.length) ? sol : null\n  renderCombined()\n  refreshDetail().catch(() => {})\n}",
     "chart hook")

# 4. main chart: two more solar series and anomaly markers
once("    .concat([{ nm: 'PV (measured)', c: '#caa12e' }, { nm: 'Battery SOC', c: '#2e7d8a' }])",
     "    .concat([{ nm: 'PV (measured)', c: '#caa12e' }, { nm: 'Battery SOC', c: '#2e7d8a' },\n"
     "             { nm: 'House load', c: '#6b5a8a' }, { nm: 'Grid flow (inverter)', c: '#9a6b4a' }])", "legend")
once("  if (pvOn) sol.forEach(r => { if (r.pv > yMax) yMax = r.pv })\n",
     "  if (pvOn) sol.forEach(r => { if (r.pv > yMax) yMax = r.pv })\n"
     "  if (!SERIES_OFF['House load']) sol.forEach(r => { if (Math.abs(r.load) > yMax) yMax = Math.abs(r.load) })\n"
     "  if (!SERIES_OFF['Grid flow (inverter)']) sol.forEach(r => { if (Math.abs(r.grid) > yMax) yMax = Math.abs(r.grid) })\n",
     "ymax")
once("  vis.forEach(p => {\n    const arr = series[p.nm]\n",
     "  ;[['House load', 'load', '#6b5a8a'], ['Grid flow (inverter)', 'grid', '#9a6b4a']].forEach(function (x) {\n"
     "    if (SERIES_OFF[x[0]] || sol.length < 2) return\n"
     "    let dl = ''\n"
     "    sol.forEach(function (r, k) { dl += (k ? ' L' : 'M') + xT(tsMs(r.ts)).toFixed(1) + ',' + yW(Math.abs(r[x[1]] || 0)).toFixed(1) })\n"
     "    out += '<path d=\"' + dl + '\" stroke=\"' + x[2] + '\" stroke-width=\"1.4\" fill=\"none\" opacity=\".9\"/>'\n"
     "  })\n"
     "  vis.forEach(p => {\n    const arr = series[p.nm]\n", "extra series")
once("  out += '<g id=\"pwr-cross\"></g>'\n",
     "  // anomaly markers: dashed line plus a flag, text in the hover readout\n"
     "  const marks = (ANOM_ROWS || []).map(a => ({ t: tsMs(a.ts), a })).filter(k => k.t >= tMin && k.t <= tMax)\n"
     "  marks.forEach(k => {\n"
     "    const x = xT(k.t)\n"
     "    out += '<line x1=\"' + x.toFixed(1) + '\" x2=\"' + x.toFixed(1) + '\" y1=\"' + T + '\" y2=\"' + plotB + '\" stroke=\"#a64f3a\" stroke-width=\"1.1\" stroke-dasharray=\"3 2\" opacity=\".85\"/>' +\n"
     "      '<path d=\"M' + (x - 4).toFixed(1) + ',' + (T - 2) + ' L' + (x + 4).toFixed(1) + ',' + (T - 2) + ' L' + x.toFixed(1) + ',' + (T + 5) + ' Z\" fill=\"#a64f3a\"/>'\n"
     "  })\n"
     "  out += '<g id=\"pwr-cross\"></g>'\n", "markers")
once("  svg.__meta = { tMin, tMax, yMax, L, R, T, W, H, plotB, series, vis, sol, pvOn, socOn }",
     "  svg.__meta = { tMin, tMax, yMax, L, R, T, W, H, plotB, series, vis, sol, pvOn, socOn, marks }", "meta")
once("      if (m.pvOn)  html += ",
     "      if (!SERIES_OFF['House load']) html += '<div class=\"tr\"><span class=\"sw\" style=\"background:#6b5a8a\"></span>House load · <b>' + fW(r.load) + '</b></div>'\n"
     "      if (!SERIES_OFF['Grid flow (inverter)']) html += '<div class=\"tr\"><span class=\"sw\" style=\"background:#9a6b4a\"></span>Grid flow (inverter) · <b>' + fW(r.grid) + '</b></div>'\n"
     "      if (m.pvOn)  html += ", "tooltip series")
once("    tip.innerHTML = html\n",
     "    if (m.marks && m.marks.length) {\n"
     "      const tol = (m.tMax - m.tMin) / 60\n"
     "      m.marks.filter(k => Math.abs(k.t - t) <= tol).forEach(k => {\n"
     "        html += '<div class=\"tr\" style=\"color:#a64f3a\">⚠ ' + String(k.a.message || k.a.atype).trim() + '</div>'\n"
     "      })\n"
     "    }\n"
     "    tip.innerHTML = html\n", "tooltip anomalies")

# 5. server: NILM activity follows the requested range
start = s.index("let _NILM24 = { at: 0, val: null }")
end = s.index("\n}\n", s.index("async function handleNilm24(res)", start)) + 3
s = s[:start] + rd(v2, "nilm_range.js") + s[end:]
once("return handleNilm24(res)", "return handleNilm24(res, params)", "nilm route")

open(src, "w", encoding="utf-8").write(s)
print("patched", src)
