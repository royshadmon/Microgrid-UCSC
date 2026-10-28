#!/usr/bin/env python3
"""Apply the production gates to the physical labels before training.

The live pipeline vetoes some model outputs after inference. Training on labels
that the gates would veto teaches the model answers production then throws
away. This pass makes the labels obey the same physics, so the network learns
the gated behaviour instead of relying on post-hoc correction.

Gates (mirrors services/iems/inference/rules_additive.py and
services/iems/training/postprocess.py):
  1. power gate      an appliance cannot be ON when the panel draw plus 120 W
                     is below that appliance's on-threshold -> OFF
  2. time of day     sprinklers only 03:00-11:59, bath_lights only 16:00-23:59
                     (house-local) -> OFF outside
  3. solar pump      only 07:00-19:59 house-local -> OFF outside

Positives are overridden only when they are physically impossible. Abstentions
(NaN) inside a gate become confident negatives. Every change is counted.

Env: EGAUGE_PARQUET, LABELS_NAME, WEIGHTS_NAME (read, then rewritten in place
with a .pregate backup).
"""
from __future__ import annotations
import os, sys, json, shutil
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path("services/iems/training"); sys.path.insert(0, str(HERE))
sys.path.insert(0, "services")
from iems.inference.rules_additive import APPLIANCE_SIGNATURE
from model_panel1 import Panel1Net
from model_panel2 import Panel2Net
from model_panel3 import Panel3Net

EG  = os.environ["EGAUGE_PARQUET"]
LAB = HERE / "data" / os.environ.get("LABELS_NAME", "labels_physical_v2.parquet")
WGT = HERE / "data" / os.environ.get("WEIGHTS_NAME", "weights_physical_v2.parquet")
MARGIN_W, W_POWER, W_TOD = 120.0, 0.8, 0.8
TOD = {"sprinklers": (3, 11), "bath_lights": (16, 23), "solar_pump": (7, 19)}
PANEL_CH = {1: "Panel1 (HVAC)", 2: "Panel2 (H2O)", 3: "Panel3 (Kitchen)"}
HEADS = {1: Panel1Net.HEADS, 2: Panel2Net.HEADS, 3: Panel3Net.HEADS}

L = pd.read_parquet(LAB); W = pd.read_parquet(WGT)
idx = L.index
print(f"labels {L.shape}, weights {W.shape}", flush=True)
d = pd.read_parquet(EG, columns=["ts", "channel", "w"],
                    filters=[("channel", "in", list(PANEL_CH.values()))])
piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
piv = piv.reindex(idx).abs().ffill().bfill()
# centred +-~90 s of samples, the same smoothing the patched runtime uses
pw = piv.rolling(31, center=True, min_periods=1).mean()
local = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert("America/Los_Angeles")
hour = np.asarray(local.hour)

report = {}
for p, heads in HEADS.items():
    panel_w = pw[PANEL_CH[p]].to_numpy()
    for h in heads:
        if h not in L.columns:
            continue
        y = L[h].to_numpy(dtype="float32").copy(); w = W[h].to_numpy(dtype="float32").copy()
        r = {"pos_before": int(np.nansum(y == 1)), "neg_before": int(np.nansum(y == 0))}
        sig = APPLIANCE_SIGNATURE.get(h)
        if sig:
            m = panel_w + MARGIN_W < sig[0]
            flip = m & (y == 1); fill_ = m & np.isnan(y)
            y[flip | fill_] = 0.0; w[flip | fill_] = np.maximum(np.where(np.isnan(w[flip | fill_]), 0, w[flip | fill_]), W_POWER)
            r["power_gate_flipped"] = int(flip.sum()); r["power_gate_filled"] = int(fill_.sum())
        if h in TOD:
            lo, hi = TOD[h]
            m = (hour < lo) | (hour > hi)
            flip = m & (y == 1); fill_ = m & np.isnan(y)
            y[flip | fill_] = 0.0; w[flip | fill_] = np.maximum(np.where(np.isnan(w[flip | fill_]), 0, w[flip | fill_]), W_TOD)
            r["tod_flipped"] = int(flip.sum()); r["tod_filled"] = int(fill_.sum())
        w[np.isnan(y)] = 0.0
        L[h] = y; W[h] = w
        r["pos_after"] = int(np.nansum(y == 1)); r["neg_after"] = int(np.nansum(y == 0))
        report[h] = r

shutil.copy(LAB, str(LAB) + ".pregate"); shutil.copy(WGT, str(WGT) + ".pregate")
L.to_parquet(LAB); W.to_parquet(WGT)
json.dump(report, open(HERE / "reports" / "gate_labels_report.json", "w"), indent=1)
for h, r in report.items():
    print(f"{h:18s} pos {r['pos_before']:>8,} -> {r['pos_after']:>8,}   neg {r['neg_before']:>9,} -> {r['neg_after']:>9,}   "
          f"flipped {r.get('power_gate_flipped',0)+r.get('tod_flipped',0):>7,}", flush=True)
print("DONE", flush=True)
