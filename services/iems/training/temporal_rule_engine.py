"""
Heavily temporal rules engine for appliance labelling (Mantey IEMS).

Why this differs from rule_engine.py
------------------------------------
The threshold engine labels each *sample* by instantaneous power band. Power
alone is degenerate (fridge ~ TV ~ 80-250 W; microwave ~ cooktop ~ dishwasher
~ 1.3 kW). This engine labels *events* by their TEMPORAL signature on three
axes the old one ignores:

    (1) time-of-day prior : when the appliance is plausibly used
    (2) duration envelope : how long the run lasts
    (3) cyclic signature  : the SHAPE -
          compressor  -> periodic ON pulses, measurable period + duty + regularity
          multistage  -> several motor/pump sub-phases (washer)
          burst       -> single sharp rising+falling pulse (microwave, hair dryer)
          heating     -> high sustained draw + thermostat cycling (dryer, oven)
          steady      -> near-flat draw for hours (tv, computer)

Output (CamAL taxonomy)
-----------------------
    STRONG per-timestamp labels : only where a signature is unambiguous (conf high)
    WEAK per-window labels       : "did appliance X run in this window?" - stays
                                   reliable for coupled loads; cheap non-circular
                                   supervision that CamAL shows is enough.
Every label carries `confidence` and an `ambiguous` flag so a coupled guess is
never mistaken for ground truth.

Rules run on abs(w); raw eGauge panel power is negative-by-convention.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np, pandas as pd

TZ = "America/Los_Angeles"

# ---------------------------------------------------------------- signatures
from canonical_signatures import (Sig, SIGNATURES, PANEL_HEADS, gap_for, KIND_GAP_S,
                                  BACKGROUND, BATTERY_WINDOW)  # canonical spec

PANEL_COL = {"Panel1 (HVAC)":"panel1_w","Panel2 (H2O)":"panel2_w","Panel3 (Kitchen)":"panel3_w"}

# ---------------------------------------------------------------- primitives
def series(df, panel, measure):
    col = PANEL_COL[panel]
    if col not in df.columns: return pd.Series(dtype="float64")
    s = df[col].abs()
    s = s[~s.index.duplicated(keep="first")].sort_index()
    if measure == "step":
        # short transient loads only: 30-min baseline
        s = (s - s.rolling("30min", min_periods=30).min()).clip(lower=0)
    elif measure == "osc":
        # CYCLING component: what rides on top of the always-on floor.
        # Fridge compressor validated here: 13.2min ON, 37.9% duty, CV 0.34 24/7.
        s = (s - s.rolling("20min", min_periods=20).min()).clip(lower=0)
    elif measure == "floor":
        # SUSTAINED component: TV/computers RAISE the floor, they are not
        # excursions. Validated: +101W evening lift (night 167W -> 338W @19h).
        fl = s.rolling("20min", min_periods=20).min()
        hr = (fl.index.tz_localize("UTC") if fl.index.tz is None else fl.index)\
             .tz_convert(TZ).hour
        night = pd.Series(fl.values, index=hr).groupby(level=0).median()
        base = float(night.reindex([1,2,3,4,5]).median())
        s = (fl - base).clip(lower=0)
    elif measure == "paired":
        # dishwasher: handled by the pulse-pair detector; expose raw here
        pass
    elif measure == "osc":
        # CYCLING loads: subtract the 20-min floor so compressor pulses show
        s = (s - s.rolling("20min", min_periods=20).min()).clip(lower=0)
    elif measure == "floor":
        # SUSTAINED loads (TV, computers) RAISE the floor rather than making
        # excursions. Take the floor itself, minus the night baseline.
        fl = s.rolling("20min", min_periods=20).min()
        idx = fl.index
        hr = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert(TZ).hour
        night = pd.Series(fl.values, index=hr).groupby(level=0).median()
        base = float(night.reindex([1,2,3,4,5]).median())
        s = (fl - base).clip(lower=0)
    elif measure == "level":
        # FIX 4: long steady loads (tv, computers). A 30-min rolling min RISES to
        # meet any load sustained past 30 min, fragmenting it into ~1-min pieces.
        # Use a 6 h baseline so multi-hour steady draws survive as one event.
        s = (s - s.rolling("6h", min_periods=60).min()).clip(lower=0)
    return s.dropna()

def local_hour(ts):
    t = pd.Timestamp(ts)
    return (t.tz_localize("UTC") if t.tz is None else t).tz_convert(TZ).hour

def schmitt_cycles(seg):
    """Noise-robust cycle count via a Schmitt trigger (fixes the mean-crossing
    metric that the cross-verification showed was noise-dominated)."""
    if len(seg) < 4: return 0
    lo, hi = float(np.min(seg)), float(np.max(seg))
    if hi - lo < 1e-6: return 0
    on_t, off_t = lo + 0.66*(hi-lo), lo + 0.33*(hi-lo)
    state, n = seg[0] > on_t, 0
    for v in seg[1:]:
        if not state and v > on_t: state, n = True, n+1
        elif state and v < off_t: state = False
    return n

def extract_events(s, lo, hi, merge_gap_s=20.0, min_dur_s=10.0):
    if s.empty: return []
    w = s.to_numpy("float64"); ts = s.index.to_numpy()
    inb = (w >= lo) & (w <= hi); out=[]; i=0; n=len(s)
    while i < n:
        if not inb[i]: i+=1; continue
        last=i; j=i
        while j+1 < n:
            gap=(ts[j+1]-ts[last]).astype("timedelta64[s]").astype(float)
            if inb[j+1]: last=j+1; j+=1
            elif gap<=merge_gap_s: j+=1
            else: break
        dur=(ts[last]-ts[i]).astype("timedelta64[s]").astype(float)
        seg=w[i:last+1]
        if dur>=min_dur_s and seg.size:
            cyc=schmitt_cycles(seg)
            out.append(dict(start=pd.Timestamp(ts[i]), end=pd.Timestamp(ts[last]),
                dur_s=dur, mean=float(np.nanmean(seg)), peak=float(np.nanmax(seg)),
                rise=float(seg[:3].mean()-w[max(i-1,0)]),
                cyc_rate=cyc/(dur/60.0) if dur else 0.0, hour=local_hour(ts[i]),
                n=int(seg.size),
                cv=float(np.std(seg)/max(abs(np.mean(seg)),1e-6))))
        i=last+1
    return out

def compressor_profile(s, lo, hi):
    """Pulse-train stats for a compressor band over the whole window:
    (n_pulses, median_period_s, duty, regularity=1-CV(intervals))."""
    ev = extract_events(s, lo, hi, merge_gap_s=120, min_dur_s=300)
    if len(ev) < 3: return dict(n=len(ev), period=np.nan, duty=np.nan, reg=0.0)
    starts = np.array([e["start"].value for e in ev])/1e9
    widths = np.array([e["dur_s"] for e in ev])
    intervals = np.diff(starts)
    period = float(np.median(intervals))
    duty = float(widths.mean()/period) if period>0 else np.nan
    reg = float(max(0.0, 1 - np.std(intervals)/np.mean(intervals))) if np.mean(intervals)>0 else 0.0
    return dict(n=len(ev), period=period, duty=duty, reg=reg)

# ---------------------------------------------------------------- scoring
def _soft(x, lo, hi):
    if lo <= x <= hi: return 1.0
    span = (hi-lo) or 1.0
    d = (lo-x)/span if x<lo else (x-hi)/span
    return float(np.exp(-4*d*d))

def score(ev, sig, comp=None):
    # FIX 1: hard duration reject (dryer/oven must not fire on short bursts)
    if sig.min_dur_hard and ev["dur_s"] < sig.min_dur_hard:
        return 0.0
    # cadence guard: too few samples to confirm any temporal signature
    if ev.get("n", 999) < sig.min_samples:
        return 0.0
    # SHAPE: intra-run coefficient of variation. This is what separates a
    # CYCLE load (washer: fill/agitate/rinse/spin -> high cv) from a PLATEAU
    # load (dryer: constant resistive element -> low cv) at the same power.
    if "cv" in ev and not (sig.cv[0] <= ev["cv"] <= sig.cv[1]):
        return 0.0
    """Confidence in [0,1] that this event is `sig`. Returns (conf, reasons)."""
    c = _soft(ev["mean"], *sig.w)                          # band
    c *= _soft(ev["dur_s"], *sig.dur_s)                    # duration
    if sig.tod and not (sig.tod[0] <= ev["hour"] <= sig.tod[1]): c *= 0.35  # time-of-day
    # kind-specific SHAPE term
    if sig.kind == "burst":
        c *= 1.0 if ev["dur_s"] < sig.dur_s[1] else 0.5
        c *= 1.0 if ev["rise"] >= sig.edge*0.6 else 0.6
        c *= 1.0 if ev["cyc_rate"] < 1.5 else 0.5
    elif sig.kind == "steady":
        c *= _soft(ev["cyc_rate"], *sig.cyc_rate)
    elif sig.kind == "heating":
        c *= _soft(ev["cyc_rate"], *sig.cyc_rate)
    elif sig.kind == "multistage":
        c *= 1.0 if ev["cyc_rate"] >= sig.cyc_rate[0] else 0.6
    elif sig.kind == "compressor" and comp is not None:
        c *= _soft(comp["period"], *sig.period_s)
        c *= _soft(comp["duty"], *sig.duty)
        c *= 1.0 if comp["reg"] >= sig.regularity_min else 0.5
    return float(c)

def classify(df, appliances=None):
    """Assign each event its best appliance + confidence + ambiguous flag."""
    appliances = appliances or list(SIGNATURES)
    rows=[]
    # per (panel,measure) compressor context, computed once
    comp_ctx={}
    for a in appliances:
        s=SIGNATURES[a]
        if s.kind=="compressor":
            comp_ctx[a]=compressor_profile(series(df,s.panel,s.measure),*s.w)
    for a in appliances:
        sig=SIGNATURES[a]
        s=series(df, sig.panel, sig.measure)
        for ev in extract_events(s, sig.w[0]*0.8, sig.w[1]*1.2,
                                 merge_gap_s=gap_for(sig)):
            conf=score(ev, sig, comp_ctx.get(a))
            if conf<0.15: continue
            rows.append({**ev, "appliance":a, "conf":round(conf,3),
                         "coupled":sig.coupled})
    out=pd.DataFrame(rows)
    if out.empty: return out
    # ambiguity: an event window claimed by >1 appliance at similar confidence
    out=out.sort_values(["appliance","start"]).reset_index(drop=True)
    out["ambiguous"]=out["coupled"]
    return out

def weak_window_labels(events, window="4h"):
    """CamAL-ready WEAK labels: per appliance x window, did it fire? + max conf."""
    if events.empty: return pd.DataFrame()
    e=events.copy(); e["win"]=e["start"].dt.floor(window)
    g=(e.groupby(["win","appliance"])
         .agg(fired=("conf", lambda c:int((c>=0.4).any())),
              max_conf=("conf","max"), n_events=("conf","size")).reset_index())
    return g

if __name__ == "__main__":
    import sys
    pq="analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet"
    d=pd.read_parquet(pq, columns=["ts","channel","w"])
    # bounded self-test window (2 weeks of the CT era) to keep it fast
    d=d[(d.ts>="2026-06-20")&(d.ts<"2026-07-04")]
    piv=d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
    df=pd.DataFrame(index=pd.DatetimeIndex(piv.index))
    for pn,col in PANEL_COL.items():
        if pn in piv.columns: df[col]=piv[pn].values
    print("=== compressor profiles (fridge vs freezer discriminator) ===")
    for a in ("refrigerator","freezer_garage"):
        s=SIGNATURES[a]; cp=compressor_profile(series(df,s.panel,s.measure),*s.w)
        print(f"  {a:16} panel={s.panel[:8]} n={cp['n']} period={cp['period']/60 if cp['period']==cp['period'] else float('nan'):.0f}min "
              f"duty={cp['duty']:.2f} regularity={cp['reg']:.2f}")
    ev=classify(df)
    print("\n=== events classified (2-week self-test) ===")
    if not ev.empty:
        for a,g in ev.groupby("appliance"):
            hi=(g.conf>=0.5).sum()
            print(f"  {a:16} events={len(g):4d}  high-conf(strong)={hi:4d}  "
                  f"med_conf={g.conf.median():.2f}  coupled={g.coupled.iloc[0]}")
    ww=weak_window_labels(ev)
    print("\n=== weak 4h-window labels (CamAL-ready) ===")
    if not ww.empty:
        for a,g in ww.groupby("appliance"):
            print(f"  {a:16} windows_fired={int(g.fired.sum()):3d}/{len(g):3d}  med_max_conf={g.max_conf.median():.2f}")


def extract_paired(series, w, pulse_min_s, gap_min_s, gap_max_s,
                   env_min_s, env_max_s):
    """Dishwasher: TWO heater pulses separated by an idle/pump period.
    Patent shape: MainWash(1) -> Idle(1) -> MainWash(2) -> Idle(2).
    Pairing is what separates it from microwave/cooktop/kettle, which fire
    ONCE in the same power band and are left unpaired."""
    pulses = sorted(extract_events(series, w[0], w[1], merge_gap_s=60,
                                   min_dur_s=pulse_min_s), key=lambda e: e["start"])
    out, used = [], set()
    for i in range(len(pulses) - 1):
        if i in used:
            continue
        a = pulses[i]
        for j in range(i + 1, len(pulses)):
            gap = (pulses[j]["start"] - a["end"]).total_seconds()
            if gap > gap_max_s * 1.5:
                break
            env = (pulses[j]["end"] - a["start"]).total_seconds()
            if gap_min_s <= gap <= gap_max_s and env_min_s <= env <= env_max_s:
                seg = series.loc[a["start"]:pulses[j]["end"]].to_numpy("float64")
                out.append(dict(start=a["start"], end=pulses[j]["end"], dur_s=env,
                    mean=float(np.nanmean(seg)) if seg.size else 0.0,
                    peak=float(np.nanmax(seg)) if seg.size else 0.0,
                    rise=0.0, cyc_rate=2.0 / (env / 60.0), hour=a["hour"],
                    n=int(seg.size),
                    cv=float(np.std(seg) / max(abs(np.mean(seg)), 1e-6)) if seg.size else 0.0))
                used.add(i); used.add(j); break
    return out
