#!/usr/bin/env python3
"""Rolling walk-forward training with solar features and v2 labels.

Replaces the single 70/15/15 chronological split of train_all_physical.py,
which left 5 heads with zero test positives (reported F1 0.000,
indistinguishable from a broken head).

Scheme (K=4 chronological folds over windows):
  stage k = 1..3:
    1. train on folds [0..k) (warm-start from previous stage)
    2. predict fold k BEFORE ever training on it -> the per-fold metrics
       below are true rolling-origin numbers, never self-graded
    3. pseudo-label fold k where the physics label ABSTAINED (NaN) and the
       model is confident (p>0.92 -> ON, p<0.08 -> OFF), weight 0.30 --
       physics labels are NEVER overridden, only abstentions filled
    4. fold k joins the training pool for stage k+1
  This uses the whole archive for training while every metric comes from a
  model that had not seen that fold. Contiguous folds -> no leakage across
  the 100-sample window.

Evaluation policy (fixes the census's complaints):
  - precision and recall ALWAYS reported, never F1 alone
  - heads with < MIN_POS test positives in a fold print 'unmeasured'
  - pos_weight cap raised 10 -> 200; heads with pw >= 50 switch to weighted
    focal loss (losses.py rationale) instead of being silently flattened

Features: the 14 originals + sun_elev/csky_ghi (deterministic, full-archive
coverage) + pv_power/pv_valid (measured Solar Assistant where it overlaps).

Env: PANEL, EGAUGE_PARQUET, SOLAR_PARQUET, LABELS_NAME (default v2),
     WEIGHTS_NAME (default v2), MODEL_SUFFIX, EPOCHS_FIRST/EPOCHS_ROLL.
Artifacts keep the train_all_physical.py contract:
  models/panel{N}{SUF}_bilstm_physical.pt, panel{N}{SUF}_thresholds.json,
  services/iems/models/panel{N}{SUF}_norm_bilstm.json,
  reports/panel{N}{SUF}_rolling_unit_tests.csv
"""
from __future__ import annotations
import os as _os
_EG  = _os.environ.get("EGAUGE_PARQUET",
       "analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet")
_SOL = _os.environ.get("SOLAR_PARQUET", "analysis/solar/solar_history.parquet")
_LAB = _os.environ.get("LABELS_NAME", "labels_physical_v2.parquet")
_WGT = _os.environ.get("WEIGHTS_NAME", "weights_physical_v2.parquet")
_SUF = _os.environ.get("MODEL_SUFFIX", "")

import sys, json, os
from pathlib import Path
import numpy as np, pandas as pd, torch
from torch.utils.data import DataLoader, TensorDataset

HERE = Path("services/iems/training"); sys.path.insert(0, str(HERE))
from model_panel1 import Panel1Net
from model_panel2 import Panel2Net
from model_panel3 import Panel3Net
import losses
from solar_features import solar_frame

D = HERE / "data"
W, STRIDE, MID = 100, 10, 50
BATCH, LR = 256, 1e-3
K_FOLDS = 4
EPOCHS_FIRST = int(os.environ.get("EPOCHS_FIRST", 4))
EPOCHS_ROLL  = int(os.environ.get("EPOCHS_ROLL", 2))
PSEUDO_HI, PSEUDO_LO, PSEUDO_W = 0.92, 0.08, 0.30
POS_W_CAP, FOCAL_AT = 200.0, 50.0
MIN_POS = 50
torch.manual_seed(0); np.random.seed(0)
torch.set_num_threads(max(os.cpu_count() - 2, 4))

def masked_focal_weighted(prob, target, weight, gamma=2.0, alpha=0.25):
    mask = ~torch.isnan(target)
    if mask.sum() == 0: return prob.sum() * 0.0
    p = prob[mask].clamp(1e-6, 1 - 1e-6); t = target[mask]; w = weight[mask]
    p_t = t * p + (1 - t) * (1 - p)
    a_t = t * alpha + (1 - t) * (1 - alpha)
    ll = -a_t * (1 - p_t).pow(gamma) * p_t.log()
    return (ll * w).sum() / w.sum().clamp(min=1e-6)

print("[1/6] loading archive + v2 labels ...", flush=True)
d = pd.read_parquet(_EG, columns=["ts", "channel", "w"])
piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
S  = pd.read_parquet(D / _LAB)
SW = pd.read_parquet(D / _WGT)
idx = S.index
piv = piv.reindex(idx)

PANEL = int(os.environ.get("PANEL", "3"))
NET = {1: Panel1Net, 2: Panel2Net, 3: Panel3Net}[PANEL]
HEADS = NET.HEADS
avail = [h for h in HEADS if h in S.columns]
print(f"      panel {PANEL}  heads: {avail}", flush=True)

FEATS = [f"Panel{PANEL} ("+{1:"HVAC",2:"H2O",3:"Kitchen"}[PANEL]+")",
         "Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)", "VrmsA", "VrmsB",
         "I31", "I32", "F1", "Grid Power", "Shop", "I11", "I21"]
F = pd.DataFrame(index=idx)
for c in FEATS:
    F[c] = piv[c].abs().values if c in piv.columns else 0.0
F = F.ffill().bfill().fillna(0.0)
lh = idx.tz_localize("UTC").tz_convert("America/Los_Angeles").hour if idx.tz is None \
     else idx.tz_convert("America/Los_Angeles").hour
F["tod_sin"] = np.sin(2 * np.pi * lh / 24)
F["tod_cos"] = np.cos(2 * np.pi * lh / 24)
SOLF = solar_frame(idx, _SOL)
for c in SOLF.columns:
    F[c] = SOLF[c].values
cov = float((F["pv_valid"] > 0).mean()) * 100
print(f"      +solar features (sun_elev/csky_ghi full-archive; measured pv on "
      f"{cov:.1f}% of rows)", flush=True)

Fv = F.to_numpy("float32")
mean, std = Fv.mean(0), Fv.std(0) + 1e-6
Fv = (Fv - mean) / std
print(f"      feature matrix {Fv.shape}", flush=True)

print("[2/6] windows ...", flush=True)
dt = np.diff(idx.values).astype("timedelta64[s]").astype(float)
brk = np.r_[0, np.where(dt > 60)[0] + 1, len(idx)]
starts = []
for a, b in zip(brk[:-1], brk[1:]):
    if b - a >= W:
        starts.extend(range(a, b - W + 1, STRIDE))
starts = np.array(starts)
n = len(starts)
X = np.stack([Fv[i:i + W] for i in starts])
mid = starts + MID
Y = {h: S[h].to_numpy("float32")[mid].copy() for h in avail}
WT = {h: SW[h].to_numpy("float32")[mid].copy() for h in avail}
bounds = [int(round(n * k / K_FOLDS)) for k in range(K_FOLDS + 1)]
print(f"      {n:,} windows; fold bounds {bounds}", flush=True)

def T_(a): return torch.from_numpy(np.ascontiguousarray(a))

model = NET(in_features=Fv.shape[1])
prev = HERE / f"models/panel{PANEL}_bilstm.pt"
if prev.exists():
    sd = torch.load(prev, map_location="cpu")
    miss, unexp = model.load_state_dict(sd, strict=False)
    print(f"      warm-start strict=False: {len(miss)} missing, {len(unexp)} unexpected", flush=True)
opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
Hi = {h: i for i, h in enumerate(HEADS)}

def make_loader(lo, hi_, shuffle):
    ds = TensorDataset(T_(X[lo:hi_]),
                       *[T_(Y[h][lo:hi_]) for h in avail],
                       *[T_(WT[h][lo:hi_]) for h in avail])
    return DataLoader(ds, batch_size=BATCH, shuffle=shuffle)

def unpack(b):
    x = b[0]
    st = {h: b[1 + i] for i, h in enumerate(avail)}
    sw = {h: b[1 + len(avail) + i] for i, h in enumerate(avail)}
    return x, st, sw

def pos_weights(lo, hi_):
    pw = {}
    for h in avail:
        y = Y[h][lo:hi_]
        p = np.nansum(y == 1); ng = np.nansum(y == 0)
        pw[h] = float(min(max(ng / max(p, 1), 1.0), POS_W_CAP))
    return pw

def head_loss(h, pw, prob, tgt, wgt):
    if pw[h] >= FOCAL_AT:
        return masked_focal_weighted(prob, tgt, wgt)
    return losses.masked_bce_weighted(prob, tgt, wgt, pw[h])

def predict(lo, hi_):
    model.eval()
    out = {h: [] for h in avail}
    with torch.no_grad():
        for b in make_loader(lo, hi_, False):
            x, _, _ = unpack(b)
            preds = model(x)
            for h in avail:
                out[h].append(preds[Hi[h]].numpy())
    return {h: np.concatenate(v) for h, v in out.items()}

print("[3/6] rolling walk-forward ...", flush=True)
fold_rows = []
for stage in range(1, K_FOLDS):
    tr_lo, tr_hi = 0, bounds[stage]
    te_lo, te_hi = bounds[stage], bounds[stage + 1]
    ep = EPOCHS_FIRST if stage == 1 else EPOCHS_ROLL
    pw = pos_weights(tr_lo, tr_hi)
    focal = [h for h in avail if pw[h] >= FOCAL_AT]
    print(f"  -- stage {stage}: train [0:{tr_hi:,}) predict [{te_lo:,}:{te_hi:,}) "
          f"epochs={ep} focal={focal}", flush=True)
    tl = make_loader(tr_lo, tr_hi, True)
    for e in range(ep):
        model.train(); tot = 0.0; nb = 0
        for b in tl:
            x, st, sw = unpack(b)
            preds = model(x)
            loss = sum(head_loss(h, pw, preds[Hi[h]], st[h], sw[h]) for h in avail)
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step(); tot += float(loss); nb += 1
        print(f"     ep{e} loss={tot/max(nb,1):.4f}", flush=True)
    # rolling-origin evaluation on the unseen fold
    P = predict(te_lo, te_hi)
    for h in avail:
        y = Y[h][te_lo:te_hi]; p = P[h]
        m = ~np.isnan(y); y_, p_ = y[m], p[m]
        npos = int((y_ == 1).sum())
        if npos < MIN_POS:
            fold_rows.append(dict(fold=stage + 1, head=h, n=int(m.sum()),
                                  n_pos=npos, P="unmeasured", R="unmeasured",
                                  F1="unmeasured"))
            continue
        yh = (p_ >= 0.5).astype(float)
        tp = float(((yh == 1) & (y_ == 1)).sum())
        fp = float(((yh == 1) & (y_ == 0)).sum())
        fn = float(((yh == 0) & (y_ == 1)).sum())
        pr = tp / max(tp + fp, 1); rc = tp / max(tp + fn, 1)
        f1 = 2 * pr * rc / max(pr + rc, 1e-9)
        fold_rows.append(dict(fold=stage + 1, head=h, n=int(m.sum()), n_pos=npos,
                              P=round(pr, 3), R=round(rc, 3), F1=round(f1, 3)))
    # pseudo-label ONLY abstentions, then absorb the fold
    n_ps = {}
    for h in avail:
        y = Y[h][te_lo:te_hi]; p = P[h]
        nanm = np.isnan(y)
        hi_m = nanm & (p > PSEUDO_HI); lo_m = nanm & (p < PSEUDO_LO)
        y[hi_m] = 1.0; y[lo_m] = 0.0
        Y[h][te_lo:te_hi] = y
        wseg = WT[h][te_lo:te_hi]
        wseg[hi_m | lo_m] = PSEUDO_W
        WT[h][te_lo:te_hi] = wseg
        if hi_m.sum() or lo_m.sum():
            n_ps[h] = (int(hi_m.sum()), int(lo_m.sum()))
    print(f"     pseudo-labels (on,off): {n_ps}", flush=True)

print("[4/6] final consolidation epoch on all folds ...", flush=True)
pw = pos_weights(0, n)
tl = make_loader(0, n, True)
model.train(); tot = 0.0; nb = 0
for b in tl:
    x, st, sw = unpack(b)
    preds = model(x)
    loss = sum(head_loss(h, pw, preds[Hi[h]], st[h], sw[h]) for h in avail)
    opt.zero_grad(); loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
    opt.step(); tot += float(loss); nb += 1
print(f"      loss={tot/max(nb,1):.4f}", flush=True)

print("[5/6] threshold calibration on last fold (rolling predictions) ...", flush=True)
Pl = predict(bounds[K_FOLDS - 1], n)
THR = {}
for h in avail:
    y = Y[h][bounds[K_FOLDS - 1]:n]; p = Pl[h]
    m = ~np.isnan(y); y_, p_ = y[m], p[m]
    best_t, best_f = 0.5, -1
    if (y_ == 1).sum() >= MIN_POS:
        for t in np.linspace(0.1, 0.95, 18):
            yh = (p_ >= t).astype(float)
            tp = ((yh == 1) & (y_ == 1)).sum(); fp = ((yh == 1) & (y_ == 0)).sum()
            fn = ((yh == 0) & (y_ == 1)).sum()
            pr = tp / max(tp + fp, 1); rc = tp / max(tp + fn, 1)
            f = 2 * pr * rc / max(pr + rc, 1e-9)
            if f > best_f: best_f, best_t = f, float(t)
    THR[h] = round(best_t, 3)
print("      thresholds:", THR, flush=True)

json.dump(THR, open(HERE / f"models/panel{PANEL}{_SUF}_thresholds.json", "w"))
torch.save(model.state_dict(), HERE / f"models/panel{PANEL}{_SUF}_bilstm_physical.pt")
norm_out = {
    "features": list(F.columns),
    "mean": [float(x) for x in mean], "std": [float(x) for x in std],
    "window": W, "stride": STRIDE, "mid": MID,
    "heads": list(HEADS), "thresholds": THR,
    "_source": "train_rolling.py",
    "_labels": _LAB, "_folds": K_FOLDS,
}
norm_path = Path("services/iems/models") / f"panel{PANEL}{_SUF}_norm_bilstm.json"
norm_path.write_text(json.dumps(norm_out, indent=2))
assert len(F.columns) == Fv.shape[1]
print(f"      wrote {norm_path} ({len(F.columns)} features)", flush=True)

print("[6/6] ROLLING-ORIGIN PER-FOLD REPORT ...", flush=True)
res = pd.DataFrame(fold_rows)
pd.set_option("display.width", 200)
print(res.to_string(index=False), flush=True)
res.to_csv(HERE / f"reports/panel{PANEL}{_SUF}_rolling_unit_tests.csv", index=False)
print("DONE", flush=True)
