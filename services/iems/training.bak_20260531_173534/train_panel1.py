#!/usr/bin/env python3
"""Train Panel 1 BiLSTM (three untied heads) with per-head NaN-mask BCE.

Reads  data/panel1_windows.npz
       services/iems/models/panel1_norm.json
Writes services/iems/models/nilm_panel1.pt
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
from model_panel1 import Panel1Net  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
NPZ = REPO / "data/panel1_windows.npz"
NORM_JSON = REPO / "services/iems/models/panel1_norm.json"
OUT_PT = REPO / "services/iems/models/nilm_panel1.pt"

BATCH = 256
LR = 1e-3
WD = 1e-4
MAX_EPOCHS = 60
PATIENCE = 10


def f1(prob: np.ndarray, y: np.ndarray, thr: float = 0.5) -> tuple[float, float, float]:
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


def masked_bce(prob: torch.Tensor, target: torch.Tensor, pos_weight: float = 1.0) -> torch.Tensor:
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
    y_train = {h: data[f"y_{h}_train"].astype(np.float32) for h in ("hp", "sp")}
    y_val   = {h: data[f"y_{h}_val"].astype(np.float32)   for h in ("hp", "sp")}

    print(f"[train] X_train={X_train.shape}  X_val={X_val.shape}")

    pos_w = {}
    for h in ("hp", "sp"):
        t = y_train[h][~np.isnan(y_train[h])]
        n_pos = int((t == 1).sum())
        n_neg = int((t == 0).sum())
        pos_w[h] = float(n_neg / max(n_pos, 1)) if n_pos else 1.0
        print(f"[train]   {h}: train pos={n_pos} neg={n_neg} pos_weight={pos_w[h]:.2f}")

    train_ds = TensorDataset(
        torch.from_numpy(X_train),
        torch.from_numpy(y_train["hp"]),
        torch.from_numpy(y_train["sp"]),
    )
    val_ds = TensorDataset(
        torch.from_numpy(X_val),
        torch.from_numpy(y_val["hp"]),
        torch.from_numpy(y_val["sp"]),
    )
    train_loader = DataLoader(train_ds, batch_size=BATCH, shuffle=True, drop_last=False)
    val_loader = DataLoader(val_ds, batch_size=BATCH, shuffle=False)

    torch.manual_seed(7)
    model = Panel1Net(in_features=X_train.shape[-1])
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[train] Panel1Net: {n_params:,} parameters")

    optim = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)
    best_f1 = -math.inf
    best_state = None
    best_epoch = -1
    bad = 0

    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        tloss = 0.0
        tn = 0
        for X, hp, sp in train_loader:
            p_hp, p_sp = model(X)
            loss = (
                masked_bce(p_hp, hp, pos_w["hp"])
                + masked_bce(p_sp, sp, pos_w["sp"])
            )
            optim.zero_grad()
            loss.backward()
            optim.step()
            tloss += loss.item() * X.size(0)
            tn += X.size(0)
        tloss /= max(tn, 1)

        model.eval()
        vloss = 0.0
        vn = 0
        all_p = {"hp": [], "sp": []}
        all_y = {"hp": [], "sp": []}
        with torch.no_grad():
            for X, hp, sp in val_loader:
                p_hp, p_sp = model(X)
                loss = (
                    masked_bce(p_hp, hp, pos_w["hp"])
                    + masked_bce(p_sp, sp, pos_w["sp"])
                )
                vloss += loss.item() * X.size(0)
                vn += X.size(0)
                all_p["hp"].append(p_hp.numpy()); all_p["sp"].append(p_sp.numpy())
                all_y["hp"].append(hp.numpy());   all_y["sp"].append(sp.numpy())
        vloss /= max(vn, 1)

        m = {}
        for h in ("hp", "sp"):
            pr, rc, ff = f1(np.concatenate(all_p[h]), np.concatenate(all_y[h]))
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

        print(
            f"epoch {epoch:3d}  tloss={tloss:.4f}  vloss={vloss:.4f}  "
            f"hp[F1={m['hp'][2]:.3f} P={m['hp'][0]:.3f} R={m['hp'][1]:.3f}]  "
            f"sp[F1={m['sp'][2]:.3f} P={m['sp'][0]:.3f} R={m['sp'][1]:.3f}]  "
            f"avg={avg_f1:.3f}{marker}"
        )
        if bad >= PATIENCE:
            print(f"[train] early stop @ epoch {epoch}")
            break

    if best_state is None:
        print("[train] FATAL: no improvement", file=sys.stderr)
        return 1
    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, OUT_PT)
    print(f"[train] best epoch={best_epoch}  avg_f1={best_f1:.4f}  → {OUT_PT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
