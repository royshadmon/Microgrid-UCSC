"""Physical-model labelling. Single label set - CamAL dual/weak labelling removed.

Each appliance is read with the measure matching its PHYSICS:
  raw    discrete high-power event      osc    cycling above the 20-min floor
  floor  sustained load raising floor   paired two heater pulses + idle
Confidence comes from the temporal score (band + duration + ToD + shape).
"""
from __future__ import annotations
import sys, os
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path("services/iems/training"); sys.path.insert(0, str(HERE))
import temporal_rule_engine as T
import canonical_signatures as CS

W_STRONG, W_RULE, W_ABSTAIN = None, 0.25, 0.0

def label(df):
    idx = df.index; apps = list(CS.SIGNATURES)
    L = pd.DataFrame(np.nan, index=idx, columns=apps, dtype="float32")
    W = pd.DataFrame(W_ABSTAIN, index=idx, columns=apps, dtype="float32")
    stats = []
    for a in apps:
        sig = CS.SIGNATURES[a]; meas = CS.measure_of(a)
        ser = T.series(df, sig.panel, meas).reindex(idx).ffill()
        # OFF baseline (water_heater abstains: solar preheat makes silence uninformative)
        if not sig.no_confident_off:
            L.loc[ser < sig.on_thr * 0.6, a] = 0.0
            W.loc[ser < sig.on_thr * 0.6, a] = W_RULE
        if meas == "paired":
            P = CS.PAIRED[a]
            ev = T.extract_paired(ser.dropna(), **P)
        else:
            ev = T.extract_events(ser.dropna(), sig.w[0], sig.w[1],
                                  merge_gap_s=CS.gap_for(sig),
                                  min_dur_s=max(sig.dur_s[0] * 0.5, 10))
        kept = 0
        for e in ev:
            if sig.tod and not (sig.tod[0] <= e["hour"] <= sig.tod[1]):
                continue
            c = 0.8 if meas == "paired" else T.score(e, sig)
            if c < 0.4:
                continue
            span = (idx >= e["start"]) & (idx <= e["end"])
            L.loc[span, a] = 1.0
            W.loc[span, a] = W_RULE if sig.coupled else float(min(max(c, 0.5), 1.0))
            kept += 1
        stats.append(dict(appliance=a, panel=sig.panel[:8], measure=meas,
                          events=kept, on=int((L[a] == 1).sum()),
                          off=int((L[a] == 0).sum()),
                          trusted=int((W[a] >= 0.5).sum()),
                          pct_on=round(float((L[a] == 1).mean() * 100), 2)))
    # SPEC MUTEX: heat_pump XOR solar_pump. Where both are labelled ON at the
    # same instant, the higher instantaneous power wins (heat pump >= 1500W
    # dominates the 100-250W pump). This removes the solar_pump false positives
    # that sit inside heat-pump activity.
    if "heat_pump" in L.columns and "solar_pump" in L.columns:
        hp = df["panel1_w"].abs().reindex(idx).ffill()
        both = (L["heat_pump"] == 1) & (L["solar_pump"] == 1)
        # both on -> assign to whichever the panel power supports
        L.loc[both & (hp >= 800), "solar_pump"] = 0.0
        L.loc[both & (hp < 800), "heat_pump"] = 0.0
        W.loc[both & (hp >= 800), "solar_pump"] = W_RULE
        W.loc[both & (hp < 800), "heat_pump"] = W_RULE
    W[L.isna()] = W_ABSTAIN
    return L, W, pd.DataFrame(stats)

if __name__ == "__main__":
    print("[1/3] loading ...", flush=True)
    d = pd.read_parquet("analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet",
                        columns=["ts", "channel", "w"])
    piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
    df = pd.DataFrame(index=pd.DatetimeIndex(piv.index))
    for pn, c in T.PANEL_COL.items():
        if pn in piv.columns: df[c] = piv[pn].values
    print(f"    {len(d):,} rows -> {len(df):,} timestamps", flush=True)
    print("[2/3] physical-model labelling ...", flush=True)
    L, W, S = label(df)
    print("[3/3] writing ...", flush=True)
    L.to_parquet(HERE / "data/labels_physical.parquet")
    W.to_parquet(HERE / "data/weights_physical.parquet")
    S.to_csv(HERE / "reports/physical_label_summary.csv", index=False)
    pd.set_option("display.width", 200); print(S.to_string(index=False), flush=True)
    print("DONE", flush=True)
