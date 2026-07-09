"""Pre-walk-test data checks: shrink the on-site session by answering from
history what history can answer.
  C1  second 240V load per panel (oven/cooktop contaminating dryer estimate)
  C2  is any 120V appliance alone on a leg (e.g. P1 solar_pump) -> measurable
  C3  balanced-240 mode structure per panel
"""
import glob, os
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
PAIR = {"P1":("I11","I12"),"P2":("I21","I22"),"P3":("I31","I32")}
PN = {"P1":"Panel1 (HVAC)","P2":"Panel2 (H2O)","P3":"Panel3 (Kitchen)"}
LOAD = {"P1":"heat_pump","P2":"water_heater","P3":"dryer"}
DRY_CEIL = {"P1":4000,"P2":4000,"P3":7000}  # single-240V-load spec ceilings

def load():
    fs=sorted(glob.glob(os.path.join(HERE,"raw_par_egauge_kafka_*.csv")))
    long=pd.concat([pd.read_csv(f,header=None,names=["ts","nm","w"]) for f in fs],ignore_index=True)
    long["ts"]=pd.to_datetime(long["ts"],utc=True)
    w=long.pivot_table(index="ts",columns="nm",values="w",aggfunc="mean").sort_index().resample("6s").mean()
    for v in ("VrmsA","VrmsB"): w[v]=w[v].ffill(limit=5)
    return w
w=load(); loc=w.index.tz_convert("America/Los_Angeles")

print("### C1/C3  balanced-240 structure & second-240V-load screen ###")
for pk,(a,b) in PAIR.items():
    Ia,Ib=w[a],w[b]; m=Ia.notna()&Ib.notna()
    bal=(2*np.minimum(Ia,Ib)*120.0)[m]
    on=bal>DRY_CEIL[pk]*0.15
    q=[50,75,90,95,99,100]
    pct=np.percentile(bal[on],q) if on.any() else [0]*len(q)
    over=(bal>DRY_CEIL[pk]).mean()
    print(f"\n{pk} {LOAD[pk]}  (spec single-240V ceiling {DRY_CEIL[pk]}W)")
    print(f"  balanced-ON percentiles W {dict(zip(q,[round(x) for x in pct]))}")
    print(f"  frac of ALL time balanced-240 exceeds ceiling (=>2 240V loads co-run): {over:.3%}")
    # hour histogram of the strong balanced events
    strong=bal>DRY_CEIL[pk]*0.5
    if strong.any():
        hrs=pd.Series(loc[m][strong.values]).dt.hour
        top=hrs.value_counts().head(5).sort_index()
        print(f"  strong-event hours (local): {dict(top)}")

print("\n### C2  lone-120V-on-a-leg screen (per leg, during 240V-load OFF) ###")
for pk,(a,b) in PAIR.items():
    Ia,Ib=w[a],w[b]; m=Ia.notna()&Ib.notna()
    bal=2*np.minimum(Ia,Ib)*120.0
    off=(bal< (DRY_CEIL[pk]*0.10))[m]   # 240V load essentially off
    for ct,I in ((a,Ia),(b,Ib)):
        v = (I[m][off]*120.0)
        base=v.quantile(0.10); p50=v.median(); p95=v.quantile(0.95); p99=v.quantile(0.99)
        # a lone appliance shows as a raised plateau above baseline
        elev = (v> base+80)
        print(f"  {pk} leg {ct}: base~{base:.0f}W  p50~{p50:.0f}  p95~{p95:.0f}  p99~{p99:.0f}  "
              f"frac>base+80W={elev.mean():.1%}")
