#!/usr/bin/env python3
"""Regenerate panel{P}_norm_bilstm.json to match the models exported by
train_all_physical.py. Reproduces that script's feature frame and z-score
stats EXACTLY (same column order, same .abs(), same ffill/bfill, same
integer local hour for tod_sin/tod_cos, same +1e-6 on std)."""
import os as _os
# Dataset paths are env-overridable so the same pipeline can run against
# the full March-July archive or the August solar-overlap window without
# a forked copy. Defaults reproduce the original behaviour exactly.
_EG   = _os.environ.get("EGAUGE_PARQUET",
        "analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet")
_SOL  = _os.environ.get("SOLAR_PARQUET", "analysis/solar/solar_history.parquet")
_LAB  = _os.environ.get("LABELS_NAME", "labels_physical.parquet")
_WGT  = _os.environ.get("WEIGHTS_NAME", "weights_physical.parquet")
_SUF  = _os.environ.get("MODEL_SUFFIX", "")

import json, sys
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path("services/iems/training")
MODELS = Path("services/iems/models")
W, STRIDE, MID = 100, 10, 50

sys.path.insert(0, str(HERE))
from model_panel1 import Panel1Net
from model_panel2 import Panel2Net
from model_panel3 import Panel3Net

print("loading consolidated parquet ...", flush=True)
d = pd.read_parquet(_EG,
                    columns=["ts", "channel", "w"])
piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
S = pd.read_parquet(HERE / "data" / _LAB)
idx = S.index
piv = piv.reindex(idx)
print(f"  rows={len(d):,}  label index={len(idx):,}", flush=True)

PNAME = {1: "HVAC", 2: "H2O", 3: "Kitchen"}
NETS = {1: Panel1Net, 2: Panel2Net, 3: Panel3Net}

for P in (1, 2, 3):
    FEATS = [f"Panel{P} ({PNAME[P]})", "Panel1 (HVAC)", "Panel2 (H2O)",
             "Panel3 (Kitchen)", "VrmsA", "VrmsB", "I31", "I32", "F1",
             "Grid Power", "Shop", "I11", "I21"]
    F = pd.DataFrame(index=idx)
    for c in FEATS:
        F[c] = piv[c].abs().values if c in piv.columns else 0.0
    F = F.ffill().bfill().fillna(0.0)
    lh = idx.tz_localize("UTC").tz_convert("America/Los_Angeles").hour if idx.tz is None \
         else idx.tz_convert("America/Los_Angeles").hour
    F["tod_sin"] = np.sin(2 * np.pi * lh / 24)
    F["tod_cos"] = np.cos(2 * np.pi * lh / 24)
    Fv = F.to_numpy("float32")
    mean, std = Fv.mean(0), Fv.std(0) + 1e-6

    thr_path = HERE / f"models/panel{P}_thresholds.json"
    thresholds = json.loads(thr_path.read_text()) if thr_path.exists() else {}

    out = {
        "features": list(F.columns),
        "mean": [float(x) for x in mean],
        "std": [float(x) for x in std],
        "window": W, "stride": STRIDE, "mid": MID,
        "heads": list(NETS[P].HEADS),
        "thresholds": thresholds,
        "_source": "gen_norm_physical.py (matches train_all_physical.py)",
    }
    dst = MODELS / f"panel{P}_norm_bilstm.json"
    dst.write_text(json.dumps(out, indent=2))
    print(f"  panel{P}: {len(out['features'])} features -> {dst}", flush=True)
    print(f"    {out['features']}", flush=True)
print("done", flush=True)
