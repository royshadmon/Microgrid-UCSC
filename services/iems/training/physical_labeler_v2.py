#!/usr/bin/env python3
"""Physical labelling v2 - fixes the label SUPPLY problems the census exposed.

v1 census over 705,296 rows:
    water_heater  4,360 pos /      0 neg   (no_confident_off -> unscoreable)
    dishwasher   19,096 pos /      0 neg   (on_thr*0.6 = 30W never true on P3)
    microwave    14,192 pos / 11,843 neg   (96% of timeline unlabelled)
    thin heads: jacuzzi, strip_heater_1/2, vacuum, dryer, hair_dryer

v2 = v1 labels + four sources of PRINCIPLED negatives and solar gating:

  1. PHYSICS OFF for water_heater: the element draws 2000-4300W. When the
     whole of Panel2 is under WH_OFF_W=1600W the element cannot be on,
     whatever the solar preheat is doing. no_confident_off was about hot-water
     DEMAND being unknowable, not element STATE - the state is bounded by the
     panel total.
  2. PHYSICS OFF for dishwasher: any active phase (motor 200W+ / heater
     1200W+) must lift the panel's oscillation component. osc < 100W and
     raw < DW_OFF_W -> OFF.
  3. QUIET-HOUSE negatives: sustained periods where every panel's rolling
     30-min envelope sits at its night baseline mean no occupant-operated
     appliance is running. This is the vacancy-mining idea using the data we
     have (no Home Assistant occupancy feed in the archive).
  4. SOLAR gate: sun_elev < -2 deg -> solar_pump confidently OFF (irradiance-
     gated device; same physics as rules_additive._low_solar, applied to
     training labels).

Weights: physics negatives 0.6-0.7, quiet-house 0.85, solar-gate 0.9.
Positives are v1's, untouched. Existing v1 labels are never overwritten,
only NaNs are filled.

Env: EGAUGE_PARQUET, LABELS_NAME (default labels_physical_v2.parquet),
     WEIGHTS_NAME (default weights_physical_v2.parquet).
"""
from __future__ import annotations
import os as _os
_os.environ.setdefault("LABELS_NAME", "labels_physical_v2.parquet")
_os.environ.setdefault("WEIGHTS_NAME", "weights_physical_v2.parquet")

import sys
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path("services/iems/training"); sys.path.insert(0, str(HERE))
import temporal_rule_engine as T
import canonical_signatures as CS
import physical_labeler as V1
from solar_features import sun_elevation_deg

WH_OFF_W   = 1600.0   # Panel2 total below this -> 2000W+ element is OFF
DW_OFF_W   = 400.0    # Panel3 raw below this with flat osc -> dishwasher OFF
QUIET_WIN  = "30min"
QUIET_PCT  = 15       # rolling-envelope percentile that defines "quiet"
NIGHT_ELEV = -2.0     # sun below this -> solar_pump OFF

# appliances a quiet house proves OFF (occupant-operated, non-background)
OCCUPANT_APPS = ("toaster", "coffee_maker", "microwave", "hair_dryer",
                 "clothes_iron", "oven", "cooktop", "vacuum_cleaner",
                 "dryer", "washing_machine", "dishwasher", "garage_opener",
                 "jacuzzi_pump")

def fill(L, W, mask, app, val, wgt):
    """Fill only NaN label cells; never overwrite a v1 decision."""
    if app not in L.columns: return 0
    tgt = mask & L[app].isna()
    n = int(tgt.sum())
    if n:
        L.loc[tgt, app] = val
        W.loc[tgt, app] = wgt
    return n

def main():
    print("[1/5] v1 labelling pass ...", flush=True)
    d = pd.read_parquet(V1._EG, columns=["ts", "channel", "w"])
    piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
    df = pd.DataFrame(index=pd.DatetimeIndex(piv.index))
    for pn, c in T.PANEL_COL.items():
        if pn in piv.columns: df[c] = piv[pn].values
    L, W, S = V1.label(df)
    idx = L.index
    p1 = df["panel1_w"].abs().reindex(idx).ffill()
    p2 = df["panel2_w"].abs().reindex(idx).ffill()
    p3 = df["panel3_w"].abs().reindex(idx).ffill()

    print("[2/5] physics negatives (water_heater / dishwasher) ...", flush=True)
    n_wh = fill(L, W, p2 < WH_OFF_W, "water_heater", 0.0, 0.7)
    osc3 = T.series(df, "Panel3 (Kitchen)", "osc").reindex(idx).ffill()
    n_dw = fill(L, W, (osc3 < 100.0) & (p3 < DW_OFF_W), "dishwasher", 0.0, 0.6)
    print(f"      water_heater OFF +{n_wh:,}   dishwasher OFF +{n_dw:,}", flush=True)

    print("[3/5] quiet-house negatives ...", flush=True)
    total = (p1 + p2 + p3)
    env = total.rolling(QUIET_WIN).max()
    thr = float(np.nanpercentile(env.dropna(), QUIET_PCT))
    quiet = env < thr
    print(f"      envelope p{QUIET_PCT} = {thr:.0f}W -> {int(quiet.sum()):,} quiet samples", flush=True)
    added = {}
    for a in OCCUPANT_APPS:
        added[a] = fill(L, W, quiet, a, 0.0, 0.85)
    print("      added:", {k: v for k, v in added.items() if v}, flush=True)

    print("[4/5] solar gate (solar_pump night OFF) ...", flush=True)
    elev = sun_elevation_deg(idx)
    n_sp = fill(L, W, pd.Series(elev < NIGHT_ELEV, index=idx), "solar_pump", 0.0, 0.9)
    print(f"      solar_pump OFF +{n_sp:,}", flush=True)

    print("[5/5] census + write ...", flush=True)
    rows = []
    for c in L.columns:
        v = L[c]
        rows.append(dict(appliance=c, pos=int((v == 1).sum()),
                         neg=int((v == 0).sum()), nan=int(v.isna().sum()),
                         trusted=int((W[c] >= 0.5).sum())))
    cen = pd.DataFrame(rows)
    W[L.isna()] = 0.0
    L.to_parquet(HERE / "data" / _os.environ["LABELS_NAME"])
    W.to_parquet(HERE / "data" / _os.environ["WEIGHTS_NAME"])
    cen.to_csv(HERE / "reports/physical_label_summary_v2.csv", index=False)
    pd.set_option("display.width", 200)
    print(cen.to_string(index=False), flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
