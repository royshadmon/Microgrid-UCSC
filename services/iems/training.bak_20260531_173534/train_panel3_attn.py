#!/usr/bin/env python3
"""Train Panel 3 BiLSTM (eight untied heads) with per-head NaN-mask BCE.

Reads  data/panel3_windows.npz
       services/iems/models/panel3_norm.json
Writes services/iems/models/nilm_panel3_attn.pt
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_panel3_attn import Panel3NetAttn as Panel3Net  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
NPZ = REPO / "data/panel3_windows.npz"
NORM_JSON = REPO / "services/iems/models/panel3_norm.json"
OUT_PT = REPO / "services/iems/models/nilm_panel3_attn.pt"

BATCH = 256
LR = 1e-3
WD = 1e-4
MAX_EPOCHS = 40
PATIENCE = 8

HEADS = Panel3Net.HEADS


def f1_metrics(prob, y, thr=0.5):
    mask = ~np.isnan(y)
    if mask.sum() == 0:
        return float("nan"), float("nan"), float("nan")
    yhat = (prob[mask] > thr).astype(np.int32)
    yt = (y[mask] > 0.5).astype(np.int32)
    tp = int(((yhat == 1) & (yt == 1)).sum())
    fp = int(((yhat == 1) & (yt == 0)).sum())
    fn = int(((yhat == 0) & (yt == 1)).sum())
    pr = tp / (tp + fp) if (tp + fp) else 0.0
    rc = tp / (tp + fn) if (tp + fn) else 0.0
    return pr, rc, (2 * pr * rc / (pr + rc) if (pr + rc) else 0.0)


def masked_bce(prob, target, pos_weight=1.0):
    mask = ~torch.isnan(target)
    if mask.sum() == 0:
        return prob.new_zeros(())
    p = prob[mask].clamp(1e-7, 1 - 1e-7)
    t = target[mask]
    return -(pos_weight * t * p.log() + (1 - t) * (1 - p).log()).mean()


def main() -> int:
    data = np.load(NPZ)
    norm = json.loads(NORM_JSON.read_text())
    mean = np.array(norm["mean"], dtype=np.float32)
    std = np.array(norm["std"], dtype=np.float32)

    def normalize(X): return ((X - mean) / std).astype(np.float32)

    X_train = normalize(data["X_train"])
    X_val   = normalize(data["X_val"])
    y_train = {h: data[f"y_{h}_train"].astype(np.float32) for h in HEADS}
    y_val   = {h: data[f"y_{h}_val"].astype(np.float32)   for h in HEADS}

    print(f"[train-p3-attn] X_train={X_train.shape}  X_val={X_val.shape}")

    pos_w = {}
    for h in HEADS:
        t = y_train[h][~np.isnan(y_train[h])]
        n_pos = int((t == 1).sum())
        n_neg = int((t == 0).sum())
        pos_w[h] = float(n_neg / max(n_pos, 1)) if n_pos else 1.0
        print(f"[train-p3-attn]   {h:16s}: train pos={n_pos} neg={n_neg} pos_weight={pos_w[h]:.2f}")

    train_ds = TensorDataset(
        torch.from_numpy(X_train),
        *[torch.from_numpy(y_train[h]) for h in HEADS],
    )
    val_ds = TensorDataset(
        torch.from_numpy(X_val),
        *[torch.from_numpy(y_val[h]) for h in HEADS],
    )
    train_loader = DataLoader(train_ds, batch_size=BATCH, shuffle=True, drop_last=False)
    val_loader = DataLoader(val_ds, batch_size=BATCH, shuffle=False)

    torch.manual_seed(7)
    model = Panel3Net(in_features=X_train.shape[-1])
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[train-p3-attn] Panel3Net: {n_params:,} parameters")

    optim = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)
    best_f1 = -math.inf
    best_state = None
    best_epoch = -1
    bad = 0

    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        tloss = 0.0
        tn = 0
        for batch in train_loader:
            X, *ys = batch
            preds = model(X)
            loss = sum(masked_bce(preds[i], ys[i], pos_w[h]) for i, h in enumerate(HEADS))
            optim.zero_grad()
            loss.backward()
            optim.step()
            tloss += loss.item() * X.size(0)
            tn += X.size(0)
        tloss /= max(tn, 1)

        model.eval()
        vloss = 0.0
        vn = 0
        all_p = {h: [] for h in HEADS}
        all_y = {h: [] for h in HEADS}
        with torch.no_grad():
            for batch in val_loader:
                X, *ys = batch
                preds = model(X)
                loss = sum(masked_bce(preds[i], ys[i], pos_w[h]) for i, h in enumerate(HEADS))
                vloss += loss.item() * X.size(0)
                vn += X.size(0)
                for i, h in enumerate(HEADS):
                    all_p[h].append(preds[i].numpy())
                    all_y[h].append(ys[i].numpy())
        vloss /= max(vn, 1)

        m = {}
        for h in HEADS:
            pr, rc, ff = f1_metrics(np.concatenate(all_p[h]), np.concatenate(all_y[h]))
            m[h] = (pr, rc, ff)
        valids = [v[2] for v in m.values() if not math.isnan(v[2])]
        avg_f1 = sum(valids) / len(valids) if valids else float("nan")

        marker = ""
        if not math.isnan(avg_f1) and avg_f1 > best_f1:
            best_f1 = avg_f1
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            best_epoch = epoch
            bad = 0
            marker = "  *"
        else:
            bad += 1

        line = f"epoch {epoch:3d}  tloss={tloss:.4f}  vloss={vloss:.4f}  "
        line += "  ".join(
            f"{h[:4]}[F={m[h][2]:.2f} P={m[h][0]:.2f} R={m[h][1]:.2f}]"
            for h in HEADS
        )
        line += f"  avg={avg_f1:.3f}{marker}"
        print(line)
        if bad >= PATIENCE:
            print(f"[train-p3-attn] early stop @ epoch {epoch}")
            break

    if best_state is None:
        print("[train-p3-attn] FATAL: no improvement", file=sys.stderr)
        return 1
    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, OUT_PT)
    print(f"[train-p3-attn] best epoch={best_epoch}  avg_f1={best_f1:.4f}  → {OUT_PT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
