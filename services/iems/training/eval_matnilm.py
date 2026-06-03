#!/usr/bin/env python3
"""Evaluate a MATNilm dual-head ONNX model with the additive/mutex rules and
tune per-head decision thresholds.

  python eval_matnilm.py --panel {1|2|3} [--write-thresholds]

For the panel's test split it reports, per head:
  - matnilm-raw  F1/P/R at the tuned threshold (model only)
  - matnilm+rules F1/P/R after apply_rules(additive=True)
  - legacy ONNX F1 from reports/all_panels_eval.json (if present)
Thresholds are tuned on the VAL split (sweep 0.2..0.8) to maximize F1 and,
with --write-thresholds, persisted to panel{P}_norm.json["thresholds"].
It also quantifies the additive layer (additive=False vs True) and counts how
often each rule fires.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services"))
from iems.inference.rules_additive import apply_rules  # noqa: E402

MODELS = REPO / "services/iems/models"
HOUSE_TZ = "America/Los_Angeles"
PANEL_FEATURE = {1: "panel1_w", 2: "panel2_w", 3: "panel3_w"}


def prf(prob, y, thr):
    mask = ~np.isnan(y)
    yhat = (prob[mask] > thr).astype(int)
    yt = (y[mask] > 0.5).astype(int)
    tp = int((yhat & yt).sum()); fp = int((yhat & (1 - yt)).sum()); fn = int(((1 - yhat) & yt).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    return pr, rc, f1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=int, required=True, choices=(1, 2, 3))
    ap.add_argument("--write-thresholds", action="store_true")
    args = ap.parse_args()
    P = args.panel

    norm = json.loads((MODELS / f"panel{P}_norm.json").read_text())
    report = json.loads((REPO / f"services/iems/training/reports/"
                         f"panel{P}_matnilm_train.json").read_text())
    names = report["heads"]                       # canonical, in head order
    feats = norm["features"]
    mid = int(norm.get("mid", int(norm["window"]) // 2))
    pcol = feats.index(PANEL_FEATURE[P])
    mean = np.array(norm["mean"], np.float32); std = np.array(norm["std"], np.float32)
    std = np.where(std < 1e-6, 1.0, std)

    nz = np.load(REPO / f"data/panel{P}_windows.npz")
    keys = [re.match(r"y_(.+)_train$", k).group(1) for k in nz.files
            if re.match(r"y_(.+)_train$", k)]

    sess = ort.InferenceSession(str(MODELS / f"nilm_panel{P}_matnilm.onnx"),
                                providers=["CPUExecutionProvider"])
    out_names = [o.name for o in sess.get_outputs()]

    def infer(X, batch=256):
        # Batched to bound memory — the dual-head decoder's (B,T,N,D) expansion
        # blows up if the whole split is run at once (OOM on Panel 3's 7 heads).
        Xn = ((X - mean) / std).astype(np.float32)
        prob_parts = {nm: [] for nm in names}
        pow_parts = {nm: [] for nm in names}
        for s in range(0, len(Xn), batch):
            outs = sess.run(out_names, {"x": Xn[s:s + batch]})
            for nm in names:
                prob_parts[nm].append(np.asarray(outs[out_names.index(f"prob_{nm}")]).reshape(-1))
                pow_parts[nm].append(np.asarray(outs[out_names.index(f"pow_{nm}")]).reshape(-1))
        probs = {nm: np.concatenate(prob_parts[nm]) for nm in names}
        pows = {nm: np.concatenate(pow_parts[nm]) for nm in names}
        return probs, pows

    pv, _ = infer(nz["X_val"])
    pt, powt = infer(nz["X_test"])
    yval = {nm: nz[f"y_{k}_val"].astype(np.float32) for k, nm in zip(keys, names)}
    ytest = {nm: nz[f"y_{k}_test"].astype(np.float32) for k, nm in zip(keys, names)}

    # ---- threshold tuning on val ----
    thresholds = dict(norm.get("thresholds", {}))
    for nm in names:
        best = (0.5, -1.0)
        for thr in np.arange(0.20, 0.81, 0.05):
            _, _, f1 = prf(pv[nm], yval[nm], thr)
            if f1 > best[1]:
                best = (round(float(thr), 2), f1)
        thresholds[nm] = best[0]

    # ---- panel power + local ts for the rule layer ----
    panel_w_test = nz["X_test"][:, mid, pcol].astype(np.float64) * std[pcol] + mean[pcol]
    ts_local = pd.to_datetime(nz["ts_test"], utc=True).tz_convert(HOUSE_TZ)

    def states_post_rules(additive):
        n = len(panel_w_test)
        st = {nm: np.zeros(n, np.int32) for nm in names}
        fire = {"additive_recovery": 0, "overshoot_trim": 0, "mutex": 0}
        for i in range(n):
            preds = {nm: {"state": int(pt[nm][i] > thresholds[nm]),
                          "confidence": float(pt[nm][i]),
                          "power_w": float(powt[nm][i] * 1000.0)
                          if pt[nm][i] > thresholds[nm] else 0.0}
                     for nm in names}
            preds = apply_rules(preds, panel_power_w=float(panel_w_test[i]),
                                ts_local=ts_local[i].to_pydatetime(), additive=additive)
            for nm in names:
                st[nm][i] = preds[nm]["state"]
                rule = preds[nm].get("rule", "model")
                if rule == "additive_recovery":
                    fire["additive_recovery"] += 1
                elif rule == "overshoot_trim":
                    fire["overshoot_trim"] += 1
                elif rule.startswith("mutex"):
                    fire["mutex"] += 1
        return st, fire

    st_rules, fire = states_post_rules(True)
    st_norules, _ = states_post_rules(False)

    def f1_from_states(states, y):
        mask = ~np.isnan(y)
        yhat = states[mask]; yt = (y[mask] > 0.5).astype(int)
        tp = int((yhat & yt).sum()); fp = int((yhat & (1 - yt)).sum()); fn = int(((1 - yhat) & yt).sum())
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        return 2 * pr * rc / (pr + rc) if pr + rc else 0.0

    # legacy baseline: all_panels_eval.json is panelP -> {baseline:{heads:[...]}}
    legacy = {}
    leg_path = REPO / "services/iems/training/reports/all_panels_eval.json"
    if leg_path.exists():
        try:
            lj = json.loads(leg_path.read_text())
            pj = lj.get(f"panel{P}", {})
            variant = pj.get("baseline") or next(iter(pj.values()), {})
            for hd in variant.get("heads", []):
                legacy[hd["head"]] = {"f1": hd.get("f1_tuned", hd.get("f1_base", 0.0))}
        except Exception:
            legacy = {}

    print(f"\n=== Panel {P} — MATNilm eval (test split) ===")
    print(f"{'head':16s} {'thr':>4s} {'raw_F1':>7s} {'+rules':>7s} {'noadd':>7s} "
          f"{'legacy':>7s} {'n_pos':>6s}")
    for nm in names:
        thr = thresholds[nm]
        _, _, raw = prf(pt[nm], ytest[nm], thr)
        rl = f1_from_states(st_rules[nm], ytest[nm])
        nr = f1_from_states(st_norules[nm], ytest[nm])
        lg = ""
        if isinstance(legacy, dict):
            lv = legacy.get(nm)
            if isinstance(lv, dict):
                lg = f"{lv.get('f1', lv.get('F1', 0)):.3f}"
        npos = int(((ytest[nm] == 1) & ~np.isnan(ytest[nm])).sum())
        print(f"{nm:16s} {thr:>4.2f} {raw:>7.3f} {rl:>7.3f} {nr:>7.3f} {lg:>7s} {npos:>6d}")
    print(f"[rules] fired on test: {fire}")
    print(f"[thresholds] tuned: {thresholds}")

    if args.write_thresholds:
        norm["thresholds"] = thresholds
        (MODELS / f"panel{P}_norm.json").write_text(json.dumps(norm, indent=2))
        print(f"[eval] wrote tuned thresholds to panel{P}_norm.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
