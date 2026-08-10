#!/usr/bin/env python3
"""Cross-check canonical signatures against (1) measured events in the archive,
(2) the additive rules engine bands, (3) the exact 100-step windowing IEMS acts on.

For every appliance:
  - extract events with a RELAXED band (0.6*lo .. 1.6*hi) so a wrong spec band
    cannot hide the true population (this is how the heat_pump 1500-4000 error
    was found: the measured mass sat at 2500-5700).
  - report measured p5/p50/p95 event power, duration quantiles, modal hours.
  - flag SPEC_LOW / SPEC_HIGH when the measured p10..p90 mass falls outside the
    spec band, DUR_MISMATCH when measured durations sit outside dur_s.
  - compare against rules_additive.APPLIANCE_SIGNATURE (the live engine): any
    band disagreement means the additive power gate can veto labels the
    labeller considered valid.
  - window consistency: with W=100/STRIDE=10/MID=50 (the IEMS contract), what
    fraction of event samples survive as mid-window positives. Events shorter
    than the effective mid-sampling grain are invisible to the model.

Output: reports/signature_crosscheck.csv + console summary.
"""
from __future__ import annotations
import os, sys, re
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path("services/iems/training"); sys.path.insert(0, str(HERE))
import temporal_rule_engine as T
import canonical_signatures as CS

_EG = os.environ.get("EGAUGE_PARQUET",
      "analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet")

# live additive engine bands
sys.path.insert(0, "services/iems/inference")
import rules_additive as RA

W_, STRIDE_, MID_ = 100, 10, 50

print("[1/4] loading archive ...", flush=True)
d = pd.read_parquet(_EG, columns=["ts", "channel", "w"])
piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
df = pd.DataFrame(index=pd.DatetimeIndex(piv.index))
for pn, c in T.PANEL_COL.items():
    if pn in piv.columns: df[c] = piv[pn].values
print(f"      {len(df):,} timestamps", flush=True)

# duplicate-key audit on the additive engine source (dict literals silently
# keep the LAST duplicate -- a stale first entry is dead code that reads as live)
src = Path("services/iems/inference/rules_additive.py").read_text()
m = re.findall(r'^\s*"([a-z0-9_]+)":\s*\(', src, re.M)
dups = sorted({k for k in m if m.count(k) > 1})
if dups:
    print(f"      [WARN] duplicate APPLIANCE_SIGNATURE keys in rules_additive.py: {dups}", flush=True)

print("[2/4] extracting relaxed-band events per appliance ...", flush=True)
rows = []
for a, sig in CS.SIGNATURES.items():
    meas = CS.measure_of(a)
    ser = T.series(df, sig.panel, meas)
    if ser.empty:
        continue
    lo, hi = sig.w
    if meas == "paired":
        P = CS.PAIRED[a]
        ev = T.extract_paired(ser.dropna(), **P)
    else:
        ev = T.extract_events(ser.dropna(), 0.6 * lo, 1.6 * hi,
                              merge_gap_s=CS.gap_for(sig),
                              min_dur_s=max(sig.dur_s[0] * 0.25, 5))
    if not ev:
        rows.append(dict(appliance=a, panel=sig.panel[:8], events=0))
        continue
    pw  = np.array([e.get("mean", np.nan) for e in ev], float)
    dur = np.array([e.get("dur_s", np.nan) for e in ev], float)
    hrs = np.array([e.get("hour", np.nan) for e in ev], float)
    pq = np.nanpercentile(pw, [5, 10, 50, 90, 95])
    dq = np.nanpercentile(dur, [10, 50, 90])
    flags = []
    if pq[1] > hi: flags.append("SPEC_LOW")     # measured mass above spec band
    if pq[3] < lo: flags.append("SPEC_HIGH")    # measured mass below spec band
    if dq[1] < sig.dur_s[0] * 0.5 or dq[1] > sig.dur_s[1] * 2: flags.append("DUR_MISMATCH")
    # additive engine consistency
    ra = RA.APPLIANCE_SIGNATURE.get(a)
    ra_ok = ""
    if ra is not None:
        on_thr, ra_lo, ra_hi = ra
        if abs(ra_lo - lo) > 0.25 * lo or abs(ra_hi - hi) > 0.25 * hi:
            flags.append("ENGINE_BAND_MISMATCH")
        ra_ok = f"{ra_lo}-{ra_hi}/thr{on_thr}"
    # window survival: events shorter than STRIDE_ * cadence may miss all mids
    med_cad = float(np.median(np.diff(ser.index.values).astype("timedelta64[s]").astype(float)))
    mid_grain = STRIDE_ * max(med_cad, 1.0)
    surv = float((dur >= mid_grain).mean())
    if surv < 0.5: flags.append("WINDOW_INVISIBLE")
    rows.append(dict(appliance=a, panel=sig.panel[:8], measure=meas, events=len(ev),
                     spec_band=f"{lo}-{hi}", meas_p5=round(pq[0]), meas_p50=round(pq[2]),
                     meas_p95=round(pq[4]), dur_p10=round(dq[0]), dur_p50=round(dq[1]),
                     dur_p90=round(dq[2]), spec_dur=f"{sig.dur_s[0]}-{sig.dur_s[1]}",
                     additive_band=ra_ok, mid_grain_s=round(mid_grain),
                     window_survival=round(surv, 3),
                     modal_hour=int(np.nanmedian(hrs)) if np.isfinite(np.nanmedian(hrs)) else -1,
                     flags="|".join(flags)))

print("[3/4] writing report ...", flush=True)
res = pd.DataFrame(rows)
res.to_csv(HERE / "reports/signature_crosscheck.csv", index=False)
pd.set_option("display.width", 250)
print(res.to_string(index=False), flush=True)

print("[4/4] flagged appliances:", flush=True)
bad = res[res.get("flags", "").fillna("") != ""] if "flags" in res else res.iloc[0:0]
for _, r in bad.iterrows():
    print(f"      {r['appliance']:16s} {r['flags']}  spec={r['spec_band']} measured p10-p90 around {r['meas_p50']}W", flush=True)
print("DONE", flush=True)
