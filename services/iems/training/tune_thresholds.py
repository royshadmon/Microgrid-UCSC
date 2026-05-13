#!/usr/bin/env python3
"""Per-head F1-optimal threshold sweep on val. Re-evaluate on test."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort

REPO = Path(__file__).resolve().parents[3]
NPZ = REPO / "data/panel1_windows.npz"
NORM_JSON = REPO / "services/iems/models/panel1_norm.json"
INT8 = REPO / "services/iems/models/nilm_panel1_int8.onnx"

HEADS = ("heat_pump", "solar_pump", "vacuum_cleaner")
HEAD_KEYS = ("hp", "sp", "vc")


def best_thr(prob, y):
    mask = ~np.isnan(y)
    p = prob[mask]; yt = (y[mask] > 0.5).astype(np.int32)
    if yt.sum() == 0 or (1 - yt).sum() == 0:
        return 0.5, 0.0, 0.0, 0.0
    best = (-1.0, 0.5, 0.0, 0.0)
    for thr in np.linspace(0.05, 0.95, 91):
        yhat = (p > thr).astype(np.int32)
        tp = int(((yhat == 1) & (yt == 1)).sum())
        fp = int(((yhat == 1) & (yt == 0)).sum())
        fn = int(((yhat == 0) & (yt == 1)).sum())
        pr = tp / (tp + fp) if (tp + fp) else 0.0
        rc = tp / (tp + fn) if (tp + fn) else 0.0
        ff = 2 * pr * rc / (pr + rc) if (pr + rc) else 0.0
        if ff > best[0]:
            best = (ff, float(thr), pr, rc)
    return best[1], best[2], best[3], best[0]


def score(prob, y, thr):
    mask = ~np.isnan(y)
    yhat = (prob[mask] > thr).astype(np.int32); yt = (y[mask] > 0.5).astype(np.int32)
    tp = int(((yhat == 1) & (yt == 1)).sum())
    fp = int(((yhat == 1) & (yt == 0)).sum())
    fn = int(((yhat == 0) & (yt == 1)).sum())
    tn = int(((yhat == 0) & (yt == 0)).sum())
    pr = tp / (tp + fp) if (tp + fp) else 0.0
    rc = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * pr * rc / (pr + rc) if (pr + rc) else 0.0
    return tp, fp, fn, tn, pr, rc, f1


def main() -> int:
    data = np.load(NPZ)
    norm = json.loads(NORM_JSON.read_text())
    mean = np.array(norm["mean"], dtype=np.float32)
    std = np.array(norm["std"], dtype=np.float32)
    sess = ort.InferenceSession(str(INT8), providers=["CPUExecutionProvider"])

    def infer(X_raw):
        X = ((X_raw - mean) / std).astype(np.float32)
        probs = [np.empty(len(X), dtype=np.float32) for _ in HEADS]
        for i in range(0, len(X), 256):
            out = sess.run(None, {"window": X[i:i + 256]})
            for j, o in enumerate(out):
                probs[j][i:i + 256] = o.reshape(-1)
        return probs

    pv = infer(data["X_val"])
    pt = infer(data["X_test"])

    thresholds = {}
    for j, (h_name, h_key) in enumerate(zip(HEADS, HEAD_KEYS)):
        y_v = data[f"y_{h_key}_val"].astype(np.float32)
        y_t = data[f"y_{h_key}_test"].astype(np.float32)
        thr, pr_v, rc_v, f1_v = best_thr(pv[j], y_v)
        thresholds[h_name] = thr
        tp, fp, fn, tn, pr, rc, f1 = score(pt[j], y_t, thr)
        print(f"[tune] {h_name}")
        print(f"  val   best thr={thr:.3f}  P={pr_v:.3f}  R={rc_v:.3f}  F1={f1_v:.3f}")
        print(f"  test  @{thr:.3f}  TP={tp} FP={fp} FN={fn} TN={tn}  "
              f"P={pr:.3f} R={rc:.3f} F1={f1:.3f}")

    norm["thresholds"] = thresholds
    NORM_JSON.write_text(json.dumps(norm, indent=2))
    print(f"[tune] persisted thresholds -> {NORM_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
