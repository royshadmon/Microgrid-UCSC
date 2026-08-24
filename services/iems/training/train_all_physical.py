#!/usr/bin/env python3
"""Build dual-supervised windows, train Panel3 BiLSTM, run per-appliance tests.

Preserves the 8-output ONNX contract (Panel3Net.HEADS). Heads with no dual
labels keep their existing weights via strict=False warm-start.
"""
from __future__ import annotations
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

import sys, json, os
from pathlib import Path
import numpy as np, pandas as pd, torch
from torch.utils.data import DataLoader, TensorDataset

HERE = Path("services/iems/training")
sys.path.insert(0, str(HERE))
from model_panel1 import Panel1Net
from model_panel2 import Panel2Net
from model_panel3 import Panel3Net
import losses

D = HERE / "data"
W, STRIDE, MID = 100, 10, 50
BATCH, LR, EPOCHS = 256, 1e-3, int(_os.environ.get("EPOCHS","6"))
WEAK_LAMBDA = 0.0  # CamAL weak supervision REMOVED - physical model only
torch.manual_seed(0); np.random.seed(0)

print("[1/6] loading consolidated + dual labels ...", flush=True)
d = pd.read_parquet(_EG,
                    columns=["ts", "channel", "w"])
piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
S = pd.read_parquet(D / _LAB)
SW = pd.read_parquet(D / _WGT)
WK = None
WKW = None
idx = S.index
piv = piv.reindex(idx)

import canonical_signatures as CS
PANEL = int(os.environ.get("PANEL","3"))
NET = {1:Panel1Net,2:Panel2Net,3:Panel3Net}[PANEL]
HEADS = NET.HEADS
avail = [h for h in HEADS if h in S.columns]
missing = [h for h in HEADS if h not in S.columns]
print(f"      heads with labels: {avail}", flush=True)
print(f"      heads WITHOUT labels (keep prior weights): {missing}", flush=True)

# ---- features: panel3 + context channels
FEATS = [f"Panel{PANEL} ("+{1:"HVAC",2:"H2O",3:"Kitchen"}[PANEL]+")", "Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)", "VrmsA", "VrmsB",
         "I31", "I32", "F1", "Grid Power", "Shop", "I11", "I21"]
F = pd.DataFrame(index=idx)
for c in FEATS:
    F[c] = piv[c].abs().values if c in piv.columns else 0.0
F = F.ffill().bfill().fillna(0.0)
# add time-of-day (the temporal engine's key discriminator)
lh = idx.tz_localize("UTC").tz_convert("America/Los_Angeles").hour if idx.tz is None \
     else idx.tz_convert("America/Los_Angeles").hour
F["tod_sin"] = np.sin(2 * np.pi * lh / 24)
F["tod_cos"] = np.cos(2 * np.pi * lh / 24)
# Optional measured-solar features (env USE_SOLAR=1). Joins the solar_history
# parquet on ts (forward-filled). Gated: a sound solar-feature retrain needs
# weeks of overlapping solar data (see pull_solar_parquet.py); with only a short
# solar window the nonzero coverage will be tiny and the solar heads will not
# generalise -- the printed coverage makes that explicit.
if os.environ.get("USE_SOLAR"):
    _sol = pd.read_parquet(_SOL)
    _sol = _sol[~_sol.index.duplicated(keep="last")]
    _sol.index = pd.to_datetime(_sol.index)
    _sr = _sol.reindex(idx, method="ffill")
    for _c in ["pv_power", "battery_power", "battery_soc", "grid_power"]:
        F[_c] = pd.to_numeric(_sr[_c], errors="coerce").ffill().fillna(0.0).values
    _cov = float((F["pv_power"].abs() > 1.0).mean()) * 100.0
    print(f"      [USE_SOLAR] merged 4 solar features; nonzero PV coverage="
          f"{_cov:.1f}% of samples", flush=True)

Fv = F.to_numpy("float32")
mean, std = Fv.mean(0), Fv.std(0) + 1e-6
Fv = (Fv - mean) / std
print(f"      feature matrix {Fv.shape}", flush=True)

print("[2/6] building windows ...", flush=True)
# only windows inside contiguous runs (gap <= 60s)
dt = np.diff(idx.values).astype("timedelta64[s]").astype(float)
brk = np.r_[0, np.where(dt > 60)[0] + 1, len(idx)]
starts = []
for a, b in zip(brk[:-1], brk[1:]):
    if b - a >= W:
        starts.extend(range(a, b - W + 1, STRIDE))
starts = np.array(starts)
print(f"      {len(starts):,} windows", flush=True)

X = np.stack([Fv[i:i + W] for i in starts])
mid = starts + MID
ys = {h: S[h].to_numpy("float32")[mid] for h in avail}
ws = {h: SW[h].to_numpy("float32")[mid] for h in avail}
# weak: map each window's mid timestamp to its 4h window label
wkey = idx[mid].floor("4h")
wl = {h: np.zeros(len(mid),dtype="float32") for h in avail}
ww = {h: np.zeros(len(mid),dtype="float32") for h in avail}

# chronological split (no leakage across time)
n = len(starts); i1, i2 = int(n * .70), int(n * .85)
sl = {"train": slice(0, i1), "val": slice(i1, i2), "test": slice(i2, n)}
print(f"      train={i1:,} val={i2-i1:,} test={n-i2:,}", flush=True)

print("[3/6] tensors ...", flush=True)
def T(a): return torch.from_numpy(np.ascontiguousarray(a))
ds = {}
for sp, s in sl.items():
    ds[sp] = TensorDataset(T(X[s]),
        *[T(ys[h][s]) for h in avail], *[T(ws[h][s]) for h in avail],
        *[T(wl[h][s]) for h in avail], *[T(ww[h][s]) for h in avail])
tl = DataLoader(ds["train"], batch_size=BATCH, shuffle=True)
vl = DataLoader(ds["val"], batch_size=BATCH)
xl = DataLoader(ds["test"], batch_size=BATCH)

print("[4/6] model ...", flush=True)
model = NET(in_features=Fv.shape[1])
prev = HERE / "models/panel{}_bilstm.pt".format(PANEL)
if prev.exists():
    sd = torch.load(prev, map_location="cpu")
    miss, unexp = model.load_state_dict(sd, strict=False)
    print(f"      warm-start strict=False: {len(miss)} missing, {len(unexp)} unexpected", flush=True)
opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)

# pos_weight per head from the strong labels
pw = {}
for h in avail:
    y = ys[h][sl["train"]]
    p = np.nansum(y == 1); ng = np.nansum(y == 0)
    pw[h] = float(min(max(ng / max(p, 1), 1.0), 10.0))  # cap 50->10: high pos_weight forced ON-everywhere
print("      pos_weight:", {k: round(v, 1) for k, v in pw.items()}, flush=True)

H = len(avail); Hi = {h: i for i, h in enumerate(HEADS)}
def unpack(b):
    x = b[0]; o = 1
    st = {h: b[o + i] for i, h in enumerate(avail)}; o += H
    sw = {h: b[o + i] for i, h in enumerate(avail)}; o += H
    wt = {h: b[o + i] for i, h in enumerate(avail)}; o += H
    wv = {h: b[o + i] for i, h in enumerate(avail)}
    return x, st, sw, wt, wv

print("[5/6] training with dual_loss (strong + weak MIL) ...", flush=True)
best, best_state = 1e9, None
for ep in range(EPOCHS):
    model.train(); tot = 0.0; nb = 0
    for b in tl:
        x, st, sw, wt, wv = unpack(b)
        preds = model(x)
        loss = 0.0
        for h in avail:
            p = preds[Hi[h]]
            ls = losses.masked_bce_weighted(p, st[h], sw[h], pw[h])
            # MIL needs a time axis; use the batch's per-sample prob as a
            # degenerate bag of 1 -> falls back to weighted BCE on the weak label
            lw = losses.weak_mil_loss(p.unsqueeze(1), wt[h], wv[h])
            loss = loss + ls + WEAK_LAMBDA * lw
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        opt.step(); tot += float(loss); nb += 1
    model.eval(); vt = 0.0; vb = 0
    with torch.no_grad():
        for b in vl:
            x, st, sw, wt, wv = unpack(b)
            preds = model(x)
            l = 0.0
            for h in avail:
                p = preds[Hi[h]]
                l = l + losses.masked_bce_weighted(p, st[h], sw[h], pw[h]) \
                      + WEAK_LAMBDA * losses.weak_mil_loss(p.unsqueeze(1), wt[h], wv[h])
            vt += float(l); vb += 1
    vl_ = vt / max(vb, 1)
    print(f"  ep{ep:02d} train={tot/max(nb,1):.4f} val={vl_:.4f}", flush=True)
    if vl_ < best:
        best = vl_; best_state = {k: v.clone() for k, v in model.state_dict().items()}
if best_state: model.load_state_dict(best_state)

# STEP 1: per-head threshold calibration on the VALIDATION split (not 0.5).
# Low-precision heads need a higher cutoff; sparse heads a lower one.
model.eval()
vP={h:[] for h in avail}; vY={h:[] for h in avail}
with torch.no_grad():
    for b in vl:
        x,st,sw,wt,wv=unpack(b); preds=model(x)
        for h in avail:
            vP[h].append(preds[Hi[h]].numpy()); vY[h].append(st[h].numpy())
THR={}
for h in avail:
    pp=np.concatenate(vP[h]); yy=np.concatenate(vY[h]); m=~np.isnan(yy)
    pp,yy=pp[m],yy[m]
    best_t,best_f=0.5,-1
    if (yy==1).sum()>0:
        for t in np.linspace(0.1,0.95,18):
            yh=(pp>=t).astype(float)
            tp=((yh==1)&(yy==1)).sum(); fp=((yh==1)&(yy==0)).sum(); fn=((yh==0)&(yy==1)).sum()
            pr=tp/max(tp+fp,1); rc=tp/max(tp+fn,1); f=2*pr*rc/max(pr+rc,1e-9)
            if f>best_f: best_f,best_t=f,float(t)
    THR[h]=round(best_t,3)
print("      calibrated thresholds:", THR, flush=True)
import json as _json
_json.dump(THR, open(HERE/f"models/panel{PANEL}{_SUF}_thresholds.json","w"))
torch.save(model.state_dict(), HERE / "models/panel{}{}_bilstm_physical.pt".format(PANEL, _SUF))

# ---- norm config MUST be written with the model -------------------------
# Inference reconstructs the feature tensor from this file. Exporting a model
# without it silently pairs new weights with a stale feature list; that is
# what broke inference on 2026-08-01 (12-feature config vs 14-feature model).
_norm_out = {
    "features": list(F.columns),
    "mean": [float(x) for x in mean],
    "std": [float(x) for x in std],
    "window": W, "stride": STRIDE, "mid": MID,
    "heads": list(HEADS),
    "thresholds": THR,
    "_source": "train_all_physical.py",
}
_norm_path = Path("services/iems/models") / f"panel{PANEL}{_SUF}_norm_bilstm.json"
_norm_path.write_text(_json.dumps(_norm_out, indent=2))
print(f"      wrote norm config -> {_norm_path} ({len(F.columns)} features)", flush=True)
assert len(F.columns) == Fv.shape[1], "norm feature count != tensor width"

print("[6/6] PER-APPLIANCE UNIT TESTS (held-out test split) ...", flush=True)
model.eval()
P = {h: [] for h in avail}; Y = {h: [] for h in avail}; WGT = {h: [] for h in avail}
with torch.no_grad():
    for b in xl:
        x, st, sw, wt, wv = unpack(b)
        preds = model(x)
        for h in avail:
            P[h].append(preds[Hi[h]].numpy()); Y[h].append(st[h].numpy()); WGT[h].append(sw[h].numpy())
rows = []
for h in avail:
    p = np.concatenate(P[h]); y = np.concatenate(Y[h]); w = np.concatenate(WGT[h])
    m = ~np.isnan(y)
    p, y, w = p[m], y[m], w[m]
    yh = (p >= THR.get(h,0.5)).astype(float)
    tp = float(((yh == 1) & (y == 1)).sum()); fp = float(((yh == 1) & (y == 0)).sum())
    fn = float(((yh == 0) & (y == 1)).sum())
    pr = tp / max(tp + fp, 1); rc = tp / max(tp + fn, 1)
    f1 = 2 * pr * rc / max(pr + rc, 1e-9)
    # trusted-only subset (weight >= 0.5): the labels we actually believe
    t = w >= 0.5
    if t.sum() > 0:
        yt, pt = y[t], (p[t] >= THR.get(h,0.5)).astype(float)
        tp2 = float(((pt == 1) & (yt == 1)).sum()); fp2 = float(((pt == 1) & (yt == 0)).sum())
        fn2 = float(((pt == 0) & (yt == 1)).sum())
        pr2 = tp2 / max(tp2 + fp2, 1); rc2 = tp2 / max(tp2 + fn2, 1)
        f1t = 2 * pr2 * rc2 / max(pr2 + rc2, 1e-9)
    else:
        f1t = float("nan")
    # collapse diagnostics
    sens = float(np.std(p))
    rows.append(dict(head=h, n=int(m.sum()), n_pos=int((y == 1).sum()),
                     P=round(pr, 3), R=round(rc, 3), F1=round(f1, 3),
                     F1_trusted=round(f1t, 3), pred_std=round(sens, 4),
                     mean_w=round(float(w.mean()), 2),
                     collapsed=bool(sens < 0.01)))
res = pd.DataFrame(rows)
print(res.to_string(index=False), flush=True)
res.to_csv(HERE / "reports/panel{}{}_physical_unit_tests.csv".format(PANEL, _SUF), index=False)
print("DONE", flush=True)
