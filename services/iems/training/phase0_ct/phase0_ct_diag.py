"""Discriminating diagnostic: split-phase mains legs vs true branch CTs.

For each panel, look at the highest-power timesteps and ask whether BOTH
CTs on the panel move together (mains-leg 240V signature) or only one
(single-circuit branch signature). Also report the high-regime leg ratio.
"""
import glob, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PAIR = {"P1": ("I11", "I12"), "P2": ("I21", "I22"), "P3": ("I31", "I32")}
PN = {"P1": "Panel1 (HVAC)", "P2": "Panel2 (H2O)", "P3": "Panel3 (Kitchen)"}


def load():
    files = sorted(glob.glob(os.path.join(HERE, "raw_par_egauge_kafka_*.csv")))
    long = pd.concat([pd.read_csv(f, header=None, names=["ts", "nm", "w"]) for f in files],
                     ignore_index=True)
    long["ts"] = pd.to_datetime(long["ts"], utc=True)
    wide = long.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean").sort_index()
    w6 = wide.resample("6s").mean()
    for v in ("VrmsA", "VrmsB"):
        w6[v] = w6[v].ffill(limit=5)
    return w6


w = load()
for pk, (a, b) in PAIR.items():
    pn = PN[pk]
    P = w[pn].abs()
    Ia, Ib = w[a], w[b]
    m = P.notna() & Ia.notna() & Ib.notna()
    P, Ia, Ib = P[m], Ia[m], Ib[m]
    thr = P.quantile(0.99)
    hi = P >= thr
    # baseline (both legs) from low regime
    lo = P <= P.quantile(0.10)
    print("=" * 72)
    print(f"{pk} [{pn}]  n={m.sum()}  P99={thr:.0f}W  Pmax={P.max():.0f}W")
    print(f"  low-regime (P<=p10) median amps:  {a}={Ia[lo].median():.2f}  {b}={Ib[lo].median():.2f}")
    print(f"  HIGH-regime (P>=p99) median amps: {a}={Ia[hi].median():.2f}  {b}={Ib[hi].median():.2f}")
    # subtract each leg's own baseline, look at the *delta* during high events
    da = Ia[hi].median() - Ia[lo].median()
    db = Ib[hi].median() - Ib[lo].median()
    print(f"  high-minus-low delta amps:        {a}={da:.2f}  {b}={db:.2f}   ratio {b}/{a}={db/da if da else float('nan'):.2f}")
    # how often is the OTHER leg also elevated when one leg is high
    ia_hi = Ia > Ia.quantile(0.95)
    ib_hi = Ib > Ib.quantile(0.95)
    print(f"  P({b} top5% | {a} top5%) = {(ib_hi & ia_hi).sum()/max(ia_hi.sum(),1):.2f}   "
          f"P({a} top5% | {b} top5%) = {(ia_hi & ib_hi).sum()/max(ib_hi.sum(),1):.2f}")
    # correlation of the two legs restricted to the high regime
    hh = ia_hi | ib_hi
    print(f"  corr({a},{b}) in high regime = {np.corrcoef(Ia[hh], Ib[hh])[0,1]:.3f}")
    # show 6 rows at the very top events
    top = P.sort_values(ascending=False).head(6).index
    print(f"  --- top-6 P events (amps): ---")
    for t in top:
        print(f"    {t.tz_convert('America/Los_Angeles')}  P={P[t]:.0f}W  {a}={Ia[t]:.1f}A  {b}={Ib[t]:.1f}A  "
              f"VA={w['VrmsA'][t]:.0f} VB={w['VrmsB'][t]:.0f}")
print("=" * 72)
