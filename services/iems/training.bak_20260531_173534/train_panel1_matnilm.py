#!/usr/bin/env python3
"""Train Panel 1 MATNilm (2DMA) with per-head NaN-mask BCE.

Reads  data/panel1_windows.npz
       services/iems/models/panel1_norm.json
Writes services/iems/models/nilm_panel1_matnilm.pt
       services/iems/training/reports/panel1_matnilm_train.json

Per-head F1 on the held-out test set is also printed and compared to the
existing BiLSTM checkpoint (nilm_panel1.pt) if present.
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
from model_panel1_matnilm import Panel1MATNilm  # noqa: E402
from _resplit import pool_and_resplit  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
NPZ = REPO / "data/panel1_windows.npz"
NORM_JSON = REPO / "services/iems/models/panel1_norm.json"
OUT_PT = REPO / "services/iems/models/nilm_panel1_matnilm.pt"
REPORT = REPO / "services/iems/training/reports/panel1_matnilm_train.json"

BATCH = 128
LR = 5e-4
WD = 1e-2
MAX_EPOCHS = 80
PATIENCE = 12
WARMUP_EPOCHS = 5
SEED = 7


def f1(prob: np.ndarray, y: np.ndarray, thr: float = 0.5):
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


def masked_bce(prob: torch.Tensor, target: torch.Tensor, pos_weight: float = 1.0):
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


def main() -> int:
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    device = pick_device()
    print(f"[train] device={device}  torch={torch.__version__}")

    _raw = np.load(NPZ)
    data = pool_and_resplit(_raw, ("hp", "sp"), seed=SEED)
    norm = json.loads(NORM_JSON.read_text())
    mean = np.array(norm["mean"], dtype=np.float32)
    std = np.array(norm["std"], dtype=np.float32)
    std = np.where(std < 1e-6, 1.0, std)

    def normalize(X):
        return ((X - mean) / std).astype(np.float32)

    X_train = normalize(data["X_train"])
    X_val = normalize(data["X_val"])
    X_test = normalize(data["X_test"])
    y_train = {h: data[f"y_{h}_train"].astype(np.float32) for h in ("hp", "sp")}
    y_val = {h: data[f"y_{h}_val"].astype(np.float32) for h in ("hp", "sp")}
    y_test = {h: data[f"y_{h}_test"].astype(np.float32) for h in ("hp", "sp")}

    print(f"[train] X_train={X_train.shape}  X_val={X_val.shape}  X_test={X_test.shape}")

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

    model = Panel1MATNilm(in_features=X_train.shape[-1]).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[train] Panel1MATNilm: {n_params:,} parameters")

    optim = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)

    def lr_lambda(epoch: int) -> float:
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
        tloss = 0.0
        tn = 0
        for X, hp, sp in train_loader:
            X = X.to(device); hp = hp.to(device); sp = sp.to(device)
            p_hp, p_sp = model(X)
            loss = masked_bce(p_hp, hp, pos_w["hp"]) + masked_bce(p_sp, sp, pos_w["sp"])
            optim.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            tloss += loss.item() * X.size(0)
            tn += X.size(0)
        sched.step()
        tloss /= max(tn, 1)

        model.eval()
        vloss = 0.0
        vn = 0
        all_p = {"hp": [], "sp": []}
        all_y = {"hp": [], "sp": []}
        with torch.no_grad():
            for X, hp, sp in val_loader:
                X = X.to(device); hp = hp.to(device); sp = sp.to(device)
                p_hp, p_sp = model(X)
                loss = masked_bce(p_hp, hp, pos_w["hp"]) + masked_bce(p_sp, sp, pos_w["sp"])
                vloss += loss.item() * X.size(0)
                vn += X.size(0)
                all_p["hp"].append(p_hp.detach().cpu().numpy())
                all_p["sp"].append(p_sp.detach().cpu().numpy())
                all_y["hp"].append(hp.detach().cpu().numpy())
                all_y["sp"].append(sp.detach().cpu().numpy())
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
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            best_epoch = epoch
            bad = 0
            marker = "  *"
        else:
            bad += 1

        cur_lr = optim.param_groups[0]["lr"]
        print(
            f"epoch {epoch:3d}  lr={cur_lr:.2e}  tloss={tloss:.4f}  vloss={vloss:.4f}  "
            f"hp[F1={m['hp'][2]:.3f} P={m['hp'][0]:.3f} R={m['hp'][1]:.3f}]  "
            f"sp[F1={m['sp'][2]:.3f} P={m['sp'][0]:.3f} R={m['sp'][1]:.3f}]  "
            f"avg={avg_f1:.3f}{marker}"
        )
        history.append({
            "epoch": epoch, "lr": cur_lr, "tloss": tloss, "vloss": vloss,
            "hp_f1": m["hp"][2], "sp_f1": m["sp"][2], "avg_f1": avg_f1,
        })
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

    # ---- Test-set evaluation on best checkpoint ----
    model.load_state_dict(best_state)
    model.eval()
    test_ds = TensorDataset(
        torch.from_numpy(X_test),
        torch.from_numpy(y_test["hp"]),
        torch.from_numpy(y_test["sp"]),
    )
    test_loader = DataLoader(test_ds, batch_size=BATCH, shuffle=False)
    all_p = {"hp": [], "sp": []}
    all_y = {"hp": [], "sp": []}
    with torch.no_grad():
        for X, hp, sp in test_loader:
            X = X.to(device)
            p_hp, p_sp = model(X)
            all_p["hp"].append(p_hp.detach().cpu().numpy())
            all_p["sp"].append(p_sp.detach().cpu().numpy())
            all_y["hp"].append(hp.numpy())
            all_y["sp"].append(sp.numpy())
    test_metrics = {}
    print("\n[test] === MATNilm 2DMA on held-out test set ===")
    for h in ("hp", "sp"):
        p = np.concatenate(all_p[h]); y = np.concatenate(all_y[h])
        pr, rc, ff = f1(p, y, 0.5)
        n_pos = int(((y == 1) & ~np.isnan(y)).sum())
        n_neg = int(((y == 0) & ~np.isnan(y)).sum())
        test_metrics[h] = {"precision": pr, "recall": rc, "f1": ff,
                           "n_pos": n_pos, "n_neg": n_neg}
        print(f"[test]   {h}: F1={ff:.4f}  P={pr:.4f}  R={rc:.4f}  pos={n_pos} neg={n_neg}")

    # ---- Compare with existing BiLSTM checkpoint, if present ----
    bilstm_pt = REPO / "services/iems/models/nilm_panel1.pt"
    bilstm_metrics = None
    if bilstm_pt.exists():
        try:
            from model_panel1 import Panel1Net
            bm = Panel1Net(in_features=X_train.shape[-1]).to(device)
            sd = torch.load(bilstm_pt, map_location=device)
            bm.load_state_dict(sd)
            bm.eval()
            all_p_b = {"hp": [], "sp": []}
            with torch.no_grad():
                for X, _hp, _sp in test_loader:
                    X = X.to(device)
                    p_hp, p_sp = bm(X)
                    all_p_b["hp"].append(p_hp.detach().cpu().numpy())
                    all_p_b["sp"].append(p_sp.detach().cpu().numpy())
            bilstm_metrics = {}
            print("\n[test] === Existing BiLSTM (nilm_panel1.pt) on same test set ===")
            for h in ("hp", "sp"):
                p = np.concatenate(all_p_b[h]); y = np.concatenate(all_y[h])
                pr, rc, ff = f1(p, y, 0.5)
                bilstm_metrics[h] = {"precision": pr, "recall": rc, "f1": ff}
                print(f"[test]   {h}: F1={ff:.4f}  P={pr:.4f}  R={rc:.4f}")
        except Exception as exc:
            print(f"[test] BiLSTM comparison skipped: {exc}")

    # ---- Persist report ----
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "model": "Panel1MATNilm",
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
