#!/usr/bin/env python3
"""Detector dedup: one event per step, not one per minute while the window slides.

A live run re-evaluates every minute, and during a ramp the strongest minute
moves forward, so each run found the same step at a new minute and wrote it
again under a new fingerprint. An event is now skipped when one of the same
type on the same channel is already recorded within 30 minutes, and the
strongest candidate of a batch is taken first.
Usage: patch_v3.py <server.js>
"""
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "DET_RECORDED" in s:
    sys.exit("already patched")

def once(old, new, label):
    global s
    assert s.count(old) == 1, label
    s = s.replace(old, new)

once("const DET_SEEN = new Set()\n",
     "const DET_SEEN = new Set()\n"
     "const DET_RECORDED = []   // {entity, atype, t} of events already in customers.anomalies\n"
     "const nearRecorded = e => DET_RECORDED.some(r => r.entity === e.entity && r.atype === e.atype && Math.abs(r.t - e.ts) <= 30 * MIN_MS)\n",
     "recorded")
once("  const rows = await alSqlNet(`select fingerprint from anomalies where ts > '${utcStr(Date.now() - 2 * DAY_MS)}'`)\n"
     "  rows.forEach(r => DET_SEEN.add(String(r.fingerprint || '').trim()))\n",
     "  const rows = await alSqlNet(`select ts, atype, entity, fingerprint from anomalies where ts > '${utcStr(Date.now() - 2 * DAY_MS)}'`)\n"
     "  rows.forEach(r => {\n"
     "    DET_SEEN.add(String(r.fingerprint || '').trim())\n"
     "    DET_RECORDED.push({ entity: String(r.entity || '').trim(), atype: String(r.atype || '').trim(), t: utcMs(r.ts) })\n"
     "  })\n",
     "load")
once("  const ev = candidateAnomalies().filter(e => !DET_SEEN.has(e.fingerprint))\n",
     "  const ev = []\n"
     "  candidateAnomalies().filter(e => !DET_SEEN.has(e.fingerprint))\n"
     "    .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))\n"
     "    .forEach(e => { if (!nearRecorded(e) && !ev.some(x => x.entity === e.entity && x.atype === e.atype && Math.abs(x.ts - e.ts) <= 30 * MIN_MS)) ev.push(e) })\n",
     "filter")
once("    ev.forEach(e => DET_SEEN.add(e.fingerprint))\n",
     "    ev.forEach(e => { DET_SEEN.add(e.fingerprint); DET_RECORDED.push({ entity: e.entity, atype: e.atype, t: e.ts }) })\n",
     "after write")
open(p, "w", encoding="utf-8").write(s)
print("patched", p)
