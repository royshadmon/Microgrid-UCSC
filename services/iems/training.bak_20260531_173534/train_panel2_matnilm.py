#!/usr/bin/env python3
"""Train Panel 2 MATNilm (2DMA) with per-head NaN-mask BCE.

Reads  data/panel2_windows.npz
       services/iems/models/panel2_norm.json
Writes services/iems/models/nilm_panel2_matnilm.pt
       services/iems/training/reports/panel2_matnilm_train.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_panel2_matnilm import Panel2MATNilm  # noqa: E402
from _resplit import pool_and_resplit  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
NPZ = REPO / "data/panel2_windows.npz"
NORM_JSON = REPO / "services/iems/models/panel2_norm.json"
OUT_PT = REPO / "services/iems/models/nilm_panel2_matnilm.pt"
REPORT = REPO / "services/iems/training/reports/panel2_matnilm_train.json"

HEADS = ("water_heater", "hair_dryer", "sprinklers", "bath_lights")

BATCH = 128
LR = 5e-4
WD = 1e-2
MAX_EPOCHS = 60
PATIENCE = 10
WARMUP_EPOCHS = 4
SEED = 7


def f1(prob, y, thr=0.5):
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


def pick_device():
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def main():
    torch.manual_seed(SEED); np.random.seed(SEED)
    device = pick_device()
    print(f"[train] device={device}")

    _raw = np.load(NPZ)
    data = pool_and_resplit(_raw, HEADS, seed=SEED)
    norm = json.loads(NORM_JSON.read_text())
    mean = np.array(norm["mean"], dtype=np.float32)
    std = np.array(norm["std"], dtype=np.float32)
    std = np.where(std < 1e-6, 1.0, std)

    def normalize(X):
        return ((X - mean) / std).astype(np.float32)

    X_train = normalize(data["X_train"])
    X_val = normalize(data["X_val"])
    X_test = normalize(data["X_test"])
    y_train = {h: data[f"y_{h}_train"].astype(np.float32) for h in HEADS}
    y_val = {h: data[f"y_{h}_val"].astype(np.float32) for h in HEADS}
    y_test = {h: data[f"y_{h}_test"].astype(np.float32) for h in HEADS}

    print(f"[train] X_train={X_train.shape}  X_val={X_val.shape}  X_test={X_test.shape}")

    pos_w = {}
    for h in HEADS:
        t = y_train[h][~np.isnan(y_train[h])]
        n_pos = int((t == 1).sum())
        n_neg = int((t == 0).sum())
        pos_w[h] = float(n_neg / max(n_pos, 1)) if n_pos else 1.0
        print(f"[train]   {h}: train pos={n_pos} neg={n_neg} pos_weight={pos_w[h]:.2f}")

    train_tensors = [torch.from_numpy(X_train)] + [torch.from_numpy(y_train[h]) for h in HEADS]
    val_tensors = [torch.from_numpy(X_val)] + [torch.from_numpy(y_val[h]) for h in HEADS]
    train_ds = TensorDataset(*train_tensors)
    val_ds = TensorDataset(*val_tensors)
    train_loader = DataLoader(train_ds, batch_size=BATCH, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH, shuffle=False)

    model = Panel2MATNilm(in_features=X_train.shape[-1]).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[train] Panel2MATNilm: {n_params:,} parameters")

    optim = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)

    def lr_lambda(epoch):
        if epoch < WARMUP_EPOCHS:
            return (epoch + 1) / max(WARMUP_EPOCHS, 1)
        progress = (epoch - WARMUP_EPOCHS) / max(MAX_EPOCHS - WARMUP_EPOCHS, 1)
        return 0.5 * (1 + math.cos(math.pi * progress))

    sched = torch.optim.lr_scheduler.LambdaLR(optim, lr_lambda)

    best_f1 = -math.inf
    best_state = None
    best_epoch = -1
    history = []
    bad = 0
    t0 = time.monotonic()

    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        tloss = 0.0; tn = 0
        for batch in train_loader:
            X = batch[0].to(device)
            ys = [b.to(device) for b in batch[1:]]
            preds = model(X)
            loss = sum(masked_bce(p, y, pos_w[h]) for p, y, h in zip(preds, ys, HEADS))
            optim.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            tloss += loss.item() * X.size(0); tn += X.size(0)
        sched.step()
        tloss /= max(tn, 1)

        model.eval()
        vloss = 0.0; vn = 0
        all_p = {h: [] for h in HEADS}
        all_y = {h: [] for h in HEADS}
        with torch.no_grad():
            for batch in val_loader:
                X = batch[0].to(device)
                ys = [b.to(device) for b in batch[1:]]
                preds = model(X)
                loss = sum(masked_bce(p, y, pos_w[h]) for p, y, h in zip(preds, ys, HEADS))
                vloss += loss.item() * X.size(0); vn += X.size(0)
                for h, p, y in zip(HEADS, preds, ys):
                    all_p[h].append(p.detach().cpu().numpy())
                    all_y[h].append(y.detach().cpu().numpy())
        vloss /= max(vn, 1)

        m = {}
        for h in HEADS:
            pr, rc, ff = f1(np.concatenate(all_p[h]), np.concatenate(all_y[h]))
            m[h] = (pr, rc, ff)
        valids = [v[2] for v in m.values() if not math.isnan(v[2])]
        avg_f1 = sum(valids) / len(valids) if valids else float("nan")

        marker = ""
        if not math.isnan(avg_f1) and avg_f1 > best_f1:
            best_f1 = avg_f1
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            best_epoch = epoch
            bad = 0
            marker = "  *"
        else:
            bad += 1

        cur_lr = optim.param_groups[0]["lr"]
        head_strs = " ".join(f"{h[:2]}[F1={m[h][2]:.2f} P={m[h][0]:.2f} R={m[h][1]:.2f}]" for h in HEADS)
        print(f"epoch {epoch:3d}  lr={cur_lr:.1e}  tloss={tloss:.3f}  vloss={vloss:.3f}  {head_strs}  avg={avg_f1:.3f}{marker}")
        history.append({"epoch": epoch, "lr": cur_lr, "tloss": tloss, "vloss": vloss,
                        **{f"{h}_f1": m[h][2] for h in HEADS}, "avg_f1": avg_f1})
        if bad >= PATIENCE:
            print(f"[train] early stop @ epoch {epoch}")
            break

    if best_state is None:
        print("[train] FATAL: no improvement", file=sys.stderr)
        return 1
    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, OUT_PT)
    elapsed = time.monotonic() - t0
    print(f"[train] best epoch={best_epoch}  val avg_f1={best_f1:.4f}  {elapsed:.1f}s  -> {OUT_PT}")

    # ---- Test-set evaluation ----
    model.load_state_dict(best_state)
    model.eval()
    test_tensors = [torch.from_numpy(X_test)] + [torch.from_numpy(y_test[h]) for h in HEADS]
    test_ds = TensorDataset(*test_tensors)
    test_loader = DataLoader(test_ds, batch_size=BATCH, shuffle=False)
    all_p = {h: [] for h in HEADS}; all_y = {h: [] for h in HEADS}
    with torch.no_grad():
        for batch in test_loader:
            X = batch[0].to(device)
            preds = model(X)
            for h, p, y in zip(HEADS, preds, batch[1:]):
                all_p[h].append(p.detach().cpu().numpy())
                all_y[h].append(y.numpy())
    test_metrics = {}
    print("\n[test] === MATNilm 2DMA on held-out test set ===")
    for h in HEADS:
        p = np.concatenate(all_p[h]); y = np.concatenate(all_y[h])
        pr, rc, ff = f1(p, y, 0.5)
        n_pos = int(((y == 1) & ~np.isnan(y)).sum())
        n_neg = int(((y == 0) & ~np.isnan(y)).sum())
        test_metrics[h] = {"precision": pr, "recall": rc, "f1": ff, "n_pos": n_pos, "n_neg": n_neg}
        print(f"[test]   {h}: F1={ff:.4f}  P={pr:.4f}  R={rc:.4f}  pos={n_pos} neg={n_neg}")

    # ---- BiLSTM comparison ----
    bilstm_pt = REPO / "services/iems/models/nilm_panel2.pt"
    bilstm_metrics = None
    if bilstm_pt.exists():
        try:
            from model_panel2 import Panel2Net
            bm = Panel2Net(in_features=X_train.shape[-1]).to(device)
            sd = torch.load(bilstm_pt, map_location=device)
            bm.load_state_dict(sd); bm.eval()
            all_p_b = {h: [] for h in HEADS}
            with torch.no_grad():
                for batch in test_loader:
                    X = batch[0].to(device)
                    preds = bm(X)
                    for h, p in zip(HEADS, preds):
                        all_p_b[h].append(p.detach().cpu().numpy())
            bilstm_metrics = {}
            print("\n[test] === Existing BiLSTM (nilm_panel2.pt) on same test set ===")
            for h in HEADS:
                p = np.concatenate(all_p_b[h]); y = np.concatenate(all_y[h])
                pr, rc, ff = f1(p, y, 0.5)
                bilstm_metrics[h] = {"precision": pr, "recall": rc, "f1": ff}
                print(f"[test]   {h}: F1={ff:.4f}  P={pr:.4f}  R={rc:.4f}")
        except Exception as exc:
            print(f"[test] BiLSTM comparison skipped: {exc}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "model": "Panel2MATNilm",
        "n_params": n_params,
        "device": str(device),
        "best_epoch": best_epoch,
        "val_avg_f1": best_f1,
        "test": test_metrics,
        "bilstm_baseline_test": bilstm_metrics,
        "history": history,
        "elapsed_s": elapsed,
    }, indent=2))
    print(f"[train] report -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
