#!/usr/bin/env python3
"""Generic MATNilm 2DMA trainer for any panel (dual head + hour curriculum).

  python train_matnilm.py --panel {1|2|3} [--epochs N] [--quick]

Reads  data/panel{P}_windows.npz, services/iems/models/panel{P}_norm.json
Writes services/iems/models/nilm_panel{P}_matnilm.pt
       services/iems/training/reports/panel{P}_matnilm_train.json

Heads are auto-detected from the npz (y_<head>_train keys). Regression targets
are derived on the fly: the measured panel power at the window midpoint is
apportioned across the ON appliances by nominal signature, giving per-appliance
watt targets that sum to the panel total (the additive property). Loss is
per-head masked BCE (on/off) + masked MSE on the subtask-gated power p*o.
Training iterates the data hour-of-day by hour-of-day (curriculum).
"""
from __future__ import annotations

import argparse, json, math, re, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_matnilm import MATNilm            # noqa: E402
from _resplit import pool_and_resplit        # noqa: E402

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services"))
from iems.inference.appliance_map import APPLIANCE_NOMINAL_W  # noqa: E402

# npz head-key -> canonical appliance name (panel1 uses short keys)
KEY_TO_NAME = {"hp": "heat_pump", "sp": "solar_pump"}
SIZES = {  # per-panel capacity, scaled to labeled-window count
    1: dict(d_model=64,  n_decoder_blocks=2, n_encoder_layers=2),
    2: dict(d_model=128, n_decoder_blocks=3, n_encoder_layers=3),
    3: dict(d_model=128, n_decoder_blocks=3, n_encoder_layers=3),
}
# Regression (watt) loss weight. Kept well below 1.0 so the kW-scale MSE on
# big loads (water heater, dryer) cannot dominate and destabilize the on/off
# classification — the all-zero collapse seen at LAMBDA_REG=1.0, lr=5e-4.
LAMBDA_REG = 0.2
LR = 2.5e-4
# Heads with fewer than this many val positives are too noisy to drive the
# early-stop metric (a single lucky epoch on a 3-positive head hijacked it),
# so they are excluded from avg-F1 — still trained, still reported.
MIN_METRIC_POS = 20
SEED = 7


def detect_heads(npz):
    heads = []
    for k in npz.files:
        m = re.match(r"y_(.+)_train$", k)
        if m:
            heads.append(m.group(1))
    return tuple(heads)


def f1(prob, y, thr=0.5):
    mask = ~np.isnan(y)
    if mask.sum() == 0:
        return float("nan"), float("nan"), float("nan")
    yhat = (prob[mask] > thr).astype(np.int32)
    yt = (y[mask] > 0.5).astype(np.int32)
    tp = int(((yhat == 1) & (yt == 1)).sum()); fp = int(((yhat == 1) & (yt == 0)).sum())
    fn = int(((yhat == 0) & (yt == 1)).sum())
    pr = tp / (tp + fp) if (tp + fp) else 0.0
    rc = tp / (tp + fn) if (tp + fn) else 0.0
    return pr, rc, (2 * pr * rc / (pr + rc) if (pr + rc) else 0.0)


def masked_bce(prob, target, pos_weight=1.0):
    mask = ~torch.isnan(target)
    if mask.sum() == 0:
        return prob.new_zeros(())
    p = prob[mask].clamp(1e-7, 1 - 1e-7); t = target[mask]
    return -(pos_weight * t * p.log() + (1 - t) * (1 - p).log()).mean()


def masked_mse(power_kw, target_kw, label):
    mask = ~torch.isnan(label)
    if mask.sum() == 0:
        return power_kw.new_zeros(())
    return ((power_kw[mask] - target_kw[mask]) ** 2).mean()


def build_reg_targets(X_raw, ys, heads, panel_col, names):
    """Per-appliance watt target (kW) by apportioning panel mid-power across ON heads."""
    n, _, _ = X_raw.shape
    mid = X_raw.shape[1] // 2
    panel_w = X_raw[:, mid, panel_col].astype(np.float64)          # measured watts
    nominal = np.array([APPLIANCE_NOMINAL_W.get(names[h], 500) for h in heads], dtype=np.float64)
    Y = np.stack([ys[h] for h in heads], axis=1)                   # (n, H) on/off/NaN
    on = (Y == 1).astype(np.float64)
    denom = (on * nominal[None, :]).sum(axis=1)                    # sum nominal of ON
    denom = np.where(denom < 1e-6, 1.0, denom)
    share = (on * nominal[None, :]) / denom[:, None]               # apportion fractions
    tgt_w = share * panel_w[:, None]                               # watts per head
    tgt_w[Y != 1] = 0.0                                            # OFF -> 0 W
    tgt = (tgt_w / 1000.0).astype(np.float32)                      # kW
    tgt[np.isnan(Y)] = np.nan                                      # mask unlabeled
    return {h: tgt[:, i] for i, h in enumerate(heads)}


def batched_infer(model, X, dev, H, heads, batch=512):
    """Run the model over X in chunks to bound MPS memory. Returns (probs, powers)."""
    probs = {h: [] for h in heads}
    powers = {h: [] for h in heads}
    model.eval()
    with torch.no_grad():
        for s in range(0, len(X), batch):
            xb = torch.from_numpy(X[s:s + batch]).to(dev)
            out = model(xb)
            for i, h in enumerate(heads):
                probs[h].append(out[i].cpu().numpy())
                powers[h].append(out[H + i].cpu().numpy())
    return ({h: np.concatenate(probs[h]) for h in heads},
            {h: np.concatenate(powers[h]) for h in heads})


def hour_buckets(ts_int64):
    local = pd.to_datetime(ts_int64, utc=True).tz_convert("America/Los_Angeles")
    h = np.asarray(local.hour)
    return {hr: np.where(h == hr)[0] for hr in range(24) if (h == hr).any()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=int, required=True, choices=(1, 2, 3))
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--quick", action="store_true", help="2 epochs, pipeline smoke test")
    args = ap.parse_args()
    P = args.panel
    max_epochs = 2 if args.quick else args.epochs
    patience = 3 if args.quick else 15
    min_epochs = 0 if args.quick else 20  # don't early-stop before signals settle

    torch.manual_seed(SEED); np.random.seed(SEED)
    dev = torch.device("mps") if torch.backends.mps.is_available() else (
        torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu"))
    print(f"[train] panel={P} device={dev} torch={torch.__version__}")

    npz = np.load(REPO / f"data/panel{P}_windows.npz")
    heads = detect_heads(npz)
    names = {h: KEY_TO_NAME.get(h, h) for h in heads}
    print(f"[train] heads={heads}")
    # Use the npz splits directly. The window builder now produces a stratified
    # day split with positives in val AND test and no same-run leakage. The old
    # pool_and_resplit shuffled overlapping stride-1 windows across splits, which
    # leaked neighbors and inflated val/test metrics; it is no longer needed.
    data = {k: npz[k] for k in npz.files}
    print("[train] split per head (pos/neg, from npz stratified split):")
    for h in heads:
        for split in ("train", "val", "test"):
            y = data[f"y_{h}_{split}"].astype(np.float32)
            npos = int(((y == 1) & ~np.isnan(y)).sum())
            nneg = int(((y == 0) & ~np.isnan(y)).sum())
            print(f"[train]   {h:16s} {split:5s}: pos={npos:5d} neg={nneg:6d}")

    norm = json.loads((REPO / f"services/iems/models/panel{P}_norm.json").read_text())
    feats = norm["features"]; panel_col = feats.index(f"panel{P}_w")
    mean = np.array(norm["mean"], np.float32); std = np.array(norm["std"], np.float32)
    std = np.where(std < 1e-6, 1.0, std)

    Xtr_raw, Xva_raw, Xte_raw = data["X_train"], data["X_val"], data["X_test"]
    ytr = {h: data[f"y_{h}_train"].astype(np.float32) for h in heads}
    yva = {h: data[f"y_{h}_val"].astype(np.float32) for h in heads}
    yte = {h: data[f"y_{h}_test"].astype(np.float32) for h in heads}
    rtr = build_reg_targets(Xtr_raw, ytr, heads, panel_col, names)
    rva = build_reg_targets(Xva_raw, yva, heads, panel_col, names)

    norm_X = lambda X: ((X - mean) / std).astype(np.float32)
    Xtr, Xva, Xte = norm_X(Xtr_raw), norm_X(Xva_raw), norm_X(Xte_raw)
    hb = hour_buckets(data["ts_train"])
    print(f"[train] hour buckets: {len(hb)} hours, sizes "
          f"{ {k: len(v) for k, v in sorted(hb.items())} }")

    pos_w = {}
    for h in heads:
        t = ytr[h][~np.isnan(ytr[h])]; npos = int((t == 1).sum()); nneg = int((t == 0).sum())
        pos_w[h] = float(min(nneg / max(npos, 1), 50.0)) if npos else 1.0

    tX = torch.from_numpy(Xtr).to(dev)
    tY = {h: torch.from_numpy(ytr[h]).to(dev) for h in heads}
    tR = {h: torch.from_numpy(rtr[h]).to(dev) for h in heads}

    cfg = SIZES[P]
    model = MATNilm(heads=heads, in_features=Xtr.shape[-1], window=Xtr.shape[1],
                    mid=Xtr.shape[1] // 2, **cfg).to(dev)
    print(f"[train] params={sum(p.numel() for p in model.parameters()):,}")
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-2)
    H = len(heads)
    # Heads that drive the early-stop metric (enough val positives to be stable).
    metric_heads = [h for h in heads
                    if int(((yva[h] == 1) & ~np.isnan(yva[h])).sum()) >= MIN_METRIC_POS]
    if not metric_heads:
        metric_heads = list(heads)
    print(f"[train] early-stop metric over heads: {[names[h] for h in metric_heads]}")

    best_f1, best_state, best_epoch, bad, hist = -math.inf, None, -1, 0, []
    t0 = time.monotonic()
    BATCH = 128
    for epoch in range(1, max_epochs + 1):
        model.train()
        order = sorted(hb.keys())                 # iterate hour-of-day in order
        np.random.shuffle(order)                  # but shuffle which hour starts
        tloss = 0.0; ntot = 0
        for hr in order:                          # ---- per-hour curriculum ----
            idx = hb[hr].copy(); np.random.shuffle(idx)
            for s in range(0, len(idx), BATCH):
                b = idx[s:s + BATCH]
                bt = torch.as_tensor(b, device=dev)
                out = model(tX[bt]); probs, powers = out[:H], out[H:]
                loss = 0.0
                for i, h in enumerate(heads):
                    lab = tY[h][bt]
                    loss = loss + masked_bce(probs[i], lab, pos_w[h])
                    loss = loss + LAMBDA_REG * masked_mse(powers[i] * probs[i], tR[h][bt], lab)
                opt.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                tloss += float(loss) * len(b); ntot += len(b)
        tloss /= max(ntot, 1)

        # ---- validation (batched to bound MPS memory) ----
        vprob, _ = batched_infer(model, Xva, dev, H, heads)
        ms = {h: f1(vprob[h], yva[h]) for h in heads}
        valids = [ms[h][2] for h in metric_heads if not math.isnan(ms[h][2])]
        avg = sum(valids) / len(valids) if valids else float("nan")
        mark = ""
        if not math.isnan(avg) and avg > best_f1:
            best_f1 = avg; best_epoch = epoch; bad = 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            mark = "  *"
        else:
            bad += 1
        print(f"epoch {epoch:3d}  tloss={tloss:.4f}  avgF1={avg:.3f}" +
              "  " + " ".join(f"{h}={ms[h][2]:.2f}" for h in heads) + mark)
        hist.append({"epoch": epoch, "tloss": tloss, "avg_f1": avg,
                     **{f"{h}_f1": ms[h][2] for h in heads}})
        if bad >= patience and epoch >= min_epochs:
            print(f"[train] early stop @ {epoch}"); break

    if best_state is None:
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    out_pt = REPO / f"services/iems/models/nilm_panel{P}_matnilm.pt"
    torch.save(best_state, out_pt)
    elapsed = time.monotonic() - t0
    print(f"[train] best epoch={best_epoch} val_avgF1={best_f1:.4f} {elapsed:.1f}s -> {out_pt}")

    # ---- test ----
    model.load_state_dict(best_state); model.eval()
    tprob, tpow = batched_infer(model, Xte, dev, H, heads)
    test_metrics = {}
    print("[test] === MATNilm 2DMA dual-head ===")
    for h in heads:
        pr, rc, ff = f1(tprob[h], yte[h])
        npos = int(((yte[h] == 1) & ~np.isnan(yte[h])).sum())
        test_metrics[names[h]] = {"f1": ff, "precision": pr, "recall": rc, "n_pos": npos}
        print(f"[test]   {names[h]:16s} F1={ff:.3f} P={pr:.3f} R={rc:.3f} pos={npos}")

    rep = REPO / f"services/iems/training/reports/panel{P}_matnilm_train.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({
        "model": f"Panel{P}MATNilm-2DMA-dualhead", "heads": [names[h] for h in heads],
        "config": cfg, "in_features": int(Xtr.shape[-1]),
        "best_epoch": best_epoch, "val_avg_f1": best_f1, "test": test_metrics,
        "elapsed_s": elapsed, "history": hist,
    }, indent=2))
    print(f"[train] report -> {rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
