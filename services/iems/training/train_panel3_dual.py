#!/usr/bin/env python3
"""Build dual-supervised windows, train Panel3 BiLSTM, run per-appliance tests.

Preserves the 8-output ONNX contract (Panel3Net.HEADS). Heads with no dual
labels keep their existing weights via strict=False warm-start.
"""
from __future__ import annotations
import sys, json, os
from pathlib import Path
import numpy as np, pandas as pd, torch
from torch.utils.data import DataLoader, TensorDataset

HERE = Path("services/iems/training")
sys.path.insert(0, str(HERE))
from model_panel3 import Panel3Net
import losses

D = HERE / "data"
W, STRIDE, MID = 100, 10, 50
BATCH, LR, EPOCHS = 256, 1e-3, 12
WEAK_LAMBDA = 0.3
torch.manual_seed(0); np.random.seed(0)

print("[1/6] loading consolidated + dual labels ...", flush=True)
d = pd.read_parquet("analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet",
                    columns=["ts", "channel", "w"])
piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
S = pd.read_parquet(D / "labels_strong_all.parquet")
SW = pd.read_parquet(D / "weights_strong_all.parquet")
WK = pd.read_parquet(D / "labels_weak_all.parquet")
WKW = pd.read_parquet(D / "weights_weak_all.parquet")
idx = S.index
piv = piv.reindex(idx)

HEADS = Panel3Net.HEADS
avail = [h for h in HEADS if h in S.columns]
missing = [h for h in HEADS if h not in S.columns]
print(f"      heads with labels: {avail}", flush=True)
print(f"      heads WITHOUT labels (keep prior weights): {missing}", flush=True)

# ---- features: panel3 + context channels
FEATS = ["Panel3 (Kitchen)", "Panel1 (HVAC)", "Panel2 (H2O)", "VrmsA", "VrmsB",
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
wl = {h: WK[h].reindex(wkey).to_numpy("float32") for h in avail}
ww = {h: WKW[h].reindex(wkey).to_numpy("float32") for h in avail}

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
model = Panel3Net(in_features=Fv.shape[1])
prev = HERE / "models/panel3_bilstm.pt"
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
    pw[h] = float(min(max(ng / max(p, 1), 1.0), 50.0))
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
torch.save(model.state_dict(), HERE / "models/panel3_bilstm_dual.pt")

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
    yh = (p >= 0.5).astype(float)
    tp = float(((yh == 1) & (y == 1)).sum()); fp = float(((yh == 1) & (y == 0)).sum())
    fn = float(((yh == 0) & (y == 1)).sum())
    pr = tp / max(tp + fp, 1); rc = tp / max(tp + fn, 1)
    f1 = 2 * pr * rc / max(pr + rc, 1e-9)
    # trusted-only subset (weight >= 0.5): the labels we actually believe
    t = w >= 0.5
    if t.sum() > 0:
        yt, pt = y[t], (p[t] >= 0.5).astype(float)
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
res.to_csv(HERE / "reports/panel3_dual_unit_tests.csv", index=False)
print("DONE", flush=True)
