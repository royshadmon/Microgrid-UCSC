#!/usr/bin/env python3
"""Phase 5.2: CT-anchored MATNilm trainer with energy balance + residual head.

  python train_matnilm_ct.py --panel {1|2|3} [--epochs N] [--quick]

Supervision (the Phase 0-4 consequence):
  * ALL heads      : masked BCE on states.
  * MEASURED heads : + masked MSE on the PINNED CT watt target (bal240*PF).
  * WEAK heads     : states only, no fabricated watt target. Their power is
                     constrained solely through the gate (p*o) and the balance
                     loss, so nothing circular enters the regression.
  * MASKED heads   : (dryer) no watt target; its 240V power sits in measured_kw.
  * L_balance      : sum(unmet p*o) + residual == panel - measured.

Writes services/iems/models/nilm_panel{P}_ct.pt and reports/panel{P}_ct_train.json.
Live train_matnilm.py / nilm_panel*.pt untouched.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np
import torch

REPO = Path(__file__).resolve().parents[3]
TRAIN = REPO / "services/iems/training"
DATA = TRAIN / "data"
MODELS = REPO / "services/iems/models"
REPORTS = TRAIN / "reports"
sys.path.insert(0, str(TRAIN))
from model_matnilm import MATNilm                                    # noqa
from train_matnilm import masked_bce, masked_mse, f1                 # noqa
from reg_targets_ct import energy_balance_loss, LAMBDA_BAL, MEASURED_240, MASKED_240  # noqa

LAMBDA_REG = 0.2
LR = 2.5e-4
SEED = 7
MIN_METRIC_POS = 20
SIZES = {1: dict(d_model=64, n_decoder_blocks=2, n_encoder_layers=2),
         2: dict(d_model=128, n_decoder_blocks=3, n_encoder_layers=3),
         3: dict(d_model=128, n_decoder_blocks=3, n_encoder_layers=3)}


def infer(model, X, dev, H, batch=256):
    model.eval(); pr, po, rs = [], [], []
    with torch.no_grad():
        for s in range(0, len(X), batch):
            out = model(torch.from_numpy(X[s:s + batch]).to(dev))
            pr.append(torch.stack(out[:H], 1).cpu().numpy())
            po.append(torch.stack(out[H:2 * H], 1).cpu().numpy())
            rs.append(out[2 * H].cpu().numpy())
    return np.concatenate(pr), np.concatenate(po), np.concatenate(rs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=int, required=True, choices=(1, 2, 3))
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--bs", type=int, default=128)
    a = ap.parse_args()
    P = a.panel
    max_epochs = 2 if a.quick else a.epochs
    patience = 2 if a.quick else 12

    torch.manual_seed(SEED); np.random.seed(SEED)
    dev = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")
    npz = np.load(DATA / f"panel{P}_ct_windows.npz")
    norm = json.loads((MODELS / f"panel{P}_ct_norm.json").read_text())
    heads = tuple(norm["heads"]); H = len(heads)
    measured = [h for h in heads if h in MEASURED_240]
    masked = [h for h in heads if h in MASKED_240]
    weak = [h for h in heads if h not in measured and h not in masked]
    unmet_idx = [heads.index(h) for h in weak]
    print(f"[ct] panel={P} heads={heads}\n[ct] measured={measured} masked={masked} weak={weak}")

    mean = np.array(norm["mean"], np.float32); std = np.array(norm["std"], np.float32)
    nz = lambda X: ((X - mean) / std).astype(np.float32)
    Xtr, Xva, Xte = nz(npz["X_train"]), nz(npz["X_val"]), nz(npz["X_test"])
    ytr = {h: npz[f"y_{h}_train"].astype(np.float32) for h in heads}
    yva = {h: npz[f"y_{h}_val"].astype(np.float32) for h in heads}
    yte = {h: npz[f"y_{h}_test"].astype(np.float32) for h in heads}
    rtr = {h: npz[f"r_{h}_train"].astype(np.float32) for h in heads}

    pkw_tr = torch.from_numpy(npz["panel_kw_train"]).to(dev)
    mkw_tr = torch.from_numpy(npz["measured_kw_train"]).to(dev)

    pos_w = {}
    for h in heads:
        t = ytr[h][~np.isnan(ytr[h])]
        npos, nneg = int((t == 1).sum()), int((t == 0).sum())
        pos_w[h] = float(min(nneg / max(npos, 1), 50.0)) if npos else 1.0

    model = MATNilm(heads=heads, in_features=Xtr.shape[-1], window=Xtr.shape[1],
                    mid=Xtr.shape[1] // 2, residual=True, **SIZES[P]).to(dev)
    print(f"[ct] params={sum(p.numel() for p in model.parameters()):,}  residual_head=True")
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-2)

    tX = torch.from_numpy(Xtr).to(dev)
    tY = {h: torch.from_numpy(ytr[h]).to(dev) for h in heads}
    tR = {h: torch.from_numpy(rtr[h]).to(dev) for h in heads}

    metric_heads = [h for h in heads
                    if int(((yva[h] == 1) & ~np.isnan(yva[h])).sum()) >= MIN_METRIC_POS]
    if not metric_heads:
        metric_heads = [h for h in heads if int(((yva[h] == 1) & ~np.isnan(yva[h])).sum()) > 0]
    print(f"[ct] early-stop metric heads (>= {MIN_METRIC_POS} val pos): {metric_heads}")

    n = len(tX); bs = a.bs
    best, best_state, bad, hist = -1.0, None, 0, []
    for ep in range(1, max_epochs + 1):
        model.train()
        perm = torch.randperm(n)
        tot = totb = 0.0
        for s in range(0, n, bs):
            idx = perm[s:s + bs]
            out = model(tX[idx])
            probs = list(out[:H]); powers = list(out[H:2 * H]); res = out[2 * H]
            loss = torch.zeros((), device=dev)
            for i, h in enumerate(heads):
                loss = loss + masked_bce(probs[i], tY[h][idx], pos_w[h])
                if h in measured:                       # pinned watt target only
                    loss = loss + LAMBDA_REG * masked_mse(powers[i] * probs[i],
                                                          tR[h][idx], tY[h][idx])
            lb = energy_balance_loss(powers, probs, res, unmet_idx,
                                     pkw_tr[idx], mkw_tr[idx])
            loss = loss + LAMBDA_BAL * lb
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            tot += float(loss); totb += float(lb)
        pv, _, _ = infer(model, Xva, dev, H)
        f1s = {h: f1(pv[:, i], yva[h])[2] for i, h in enumerate(heads)}
        avg = float(np.mean([f1s[h] for h in metric_heads])) if metric_heads else 0.0
        hist.append(dict(epoch=ep, loss=tot / max(1, n // bs), balance=totb / max(1, n // bs),
                         val_avg_f1=avg, val_f1={h: round(f1s[h], 4) for h in heads}))
        print(f"[ct] ep{ep:3d} loss={tot / max(1, n // bs):.4f} Lbal={totb / max(1, n // bs):.4f} "
              f"val_avgF1={avg:.4f} " + " ".join(f"{h[:8]}={f1s[h]:.3f}" for h in metric_heads))
        if avg > best:
            best, bad = avg, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience and ep >= 10:
                print(f"[ct] early stop at ep{ep} (best val_avgF1={best:.4f})"); break
    if best_state:
        model.load_state_dict(best_state)

    # ---- test metrics ----
    pt, pow_t, res_t = infer(model, Xte, dev, H)
    report = {"panel": P, "heads": list(heads), "measured": measured, "masked": masked,
              "weak": weak, "best_val_avg_f1": best, "history": hist, "test": {}}
    print(f"\n[ct] TEST metrics (panel {P})")
    print(f"{'head':>16} {'kind':>9} {'pos':>5} {'prec':>6} {'rec':>6} {'F1':>6}")
    for i, h in enumerate(heads):
        pr, rc, ff = f1(pt[:, i], yte[h])
        npos = int(((yte[h] == 1) & ~np.isnan(yte[h])).sum())
        kind = "MEASURED" if h in measured else ("masked" if h in masked else "weak")
        report["test"][h] = dict(kind=kind, pos=npos, precision=pr, recall=rc, f1=ff)
        print(f"{h:>16} {kind:>9} {npos:5d} {pr:6.3f} {rc:6.3f} {ff:6.3f}")

    # ---- non-collapse sensitivity test (the MATNilm failure signature) ----
    print(f"\n[ct] NON-COLLAPSE SENSITIVITY (panel {P})")
    base = Xte.copy()
    probes = {"zeros": np.zeros_like(base), "random": np.random.randn(*base.shape).astype(np.float32),
              "plus2sigma": base + 2.0, "minus2sigma": base - 2.0}
    p0, _, _ = infer(model, base, dev, H)
    sens = {}
    for nm, Xp in probes.items():
        pp, _, _ = infer(model, Xp.astype(np.float32), dev, H)
        d = {h: float(abs(pp[:, i].mean() - p0[:, i].mean())) for i, h in enumerate(heads)}
        sens[nm] = d
        print(f"  {nm:12s} max|dP|={max(d.values()):.4f}  " +
              " ".join(f"{h[:8]}={d[h]:.3f}" for h in heads[:4]))
    report["sensitivity"] = sens
    maxshift = max(max(d.values()) for d in sens.values())
    verdict = "RESPONSIVE (no collapse)" if maxshift > 0.05 else "COLLAPSED (constant prior)"
    print(f"  >> max prob shift across all probes = {maxshift:.4f} -> {verdict}")
    report["collapse_verdict"] = verdict
    report["max_prob_shift"] = maxshift

    # residual sanity
    report["residual_kw"] = dict(mean=float(res_t.mean()), p90=float(np.percentile(res_t, 90)))
    print(f"  residual head kW: mean={res_t.mean():.3f} p90={np.percentile(res_t, 90):.3f}")

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"panel{P}_ct_train.json").write_text(json.dumps(report, indent=2, default=float))
    torch.save(model.state_dict(), MODELS / f"nilm_panel{P}_ct.pt")
    print(f"\n[ct] saved models/nilm_panel{P}_ct.pt + reports/panel{P}_ct_train.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
