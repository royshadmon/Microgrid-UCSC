#!/usr/bin/env python3
"""Evaluate the three-head int8 model on the held-out test split."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort

REPO = Path(__file__).resolve().parents[3]
NPZ = REPO / "data/panel1_windows.npz"
NORM_JSON = REPO / "services/iems/models/panel1_norm.json"
INT8 = REPO / "services/iems/models/nilm_panel1_int8.onnx"
ONNX = REPO / "services/iems/models/nilm_panel1.onnx"
OUT_MD = REPO / "services/iems/training/reports/panel1_eval.md"

HEADS = ("heat_pump", "solar_pump", "vacuum_cleaner")
HEAD_KEYS = ("hp", "sp", "vc")


def metrics(prob, y, thr=0.5):
    mask = ~np.isnan(y)
    n = int(mask.sum())
    yhat = (prob[mask] > thr).astype(np.int32); yt = (y[mask] > 0.5).astype(np.int32)
    tp = int(((yhat == 1) & (yt == 1)).sum()); fp = int(((yhat == 1) & (yt == 0)).sum())
    fn = int(((yhat == 0) & (yt == 1)).sum()); tn = int(((yhat == 0) & (yt == 0)).sum())
    pr = tp / (tp + fp) if (tp + fp) else 0.0
    rc = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * pr * rc / (pr + rc) if (pr + rc) else 0.0
    return {"n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": pr, "recall": rc, "f1": f1}


def main() -> int:
    data = np.load(NPZ)
    norm = json.loads(NORM_JSON.read_text())
    mean = np.array(norm["mean"], dtype=np.float32)
    std = np.array(norm["std"], dtype=np.float32)
    thrs = norm.get("thresholds", {h: 0.5 for h in HEADS})

    X_test = ((data["X_test"] - mean) / std).astype(np.float32)
    sess_int8 = ort.InferenceSession(str(INT8), providers=["CPUExecutionProvider"])
    sess_fp32 = ort.InferenceSession(str(ONNX), providers=["CPUExecutionProvider"])

    probs = [np.empty(len(X_test), dtype=np.float32) for _ in HEADS]
    for i in range(0, len(X_test), 256):
        out = sess_int8.run(None, {"window": X_test[i:i + 256]})
        for j, o in enumerate(out):
            probs[j][i:i + 256] = o.reshape(-1)

    head_metrics = []
    for j, (name, key) in enumerate(zip(HEADS, HEAD_KEYS)):
        y = data[f"y_{key}_test"].astype(np.float32)
        m = metrics(probs[j], y, thrs.get(name, 0.5))
        head_metrics.append((name, key, thrs.get(name, 0.5), m))

    # Latency
    buf = X_test[:1].copy()
    for _ in range(50): sess_int8.run(None, {"window": buf})
    N = 10_000
    t0 = time.perf_counter()
    for _ in range(N): sess_int8.run(None, {"window": buf})
    int8_ms = (time.perf_counter() - t0) * 1000 / N
    for _ in range(50): sess_fp32.run(None, {"window": buf})
    t0 = time.perf_counter()
    for _ in range(N): sess_fp32.run(None, {"window": buf})
    fp32_ms = (time.perf_counter() - t0) * 1000 / N

    lines = []
    lines.append("# Panel 1 — Eval (held-out test split, 3 heads)")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append("## Accuracy at tuned thresholds")
    lines.append("")
    lines.append("| head | thr | valid | TP | FP | FN | TN | P | R | F1 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, key, thr, m in head_metrics:
        lines.append(
            f"| `{name}` | {thr:.2f} | {m['n']} | {m['tp']} | {m['fp']} | "
            f"{m['fn']} | {m['tn']} | {m['precision']:.3f} | "
            f"{m['recall']:.3f} | **{m['f1']:.3f}** |"
        )
    lines.append("")
    lines.append("## Confusion matrices")
    lines.append("")
    for name, key, thr, m in head_metrics:
        lines.append(f"`{name}` (thr={thr:.2f}):")
        lines.append("```")
        lines.append("              pred=0   pred=1")
        lines.append(f"  actual=0   {m['tn']:6d}   {m['fp']:6d}")
        lines.append(f"  actual=1   {m['fn']:6d}   {m['tp']:6d}")
        lines.append("```")
        lines.append("")
    lines.append("## Latency (single window, Mac CPU)")
    lines.append("")
    lines.append("| variant | avg ms / window |")
    lines.append("|---|---:|")
    lines.append(f"| FP32 ONNX | {fp32_ms:.3f} |")
    lines.append(f"| int8 dynamic (MatMul-only) | {int8_ms:.3f} |")
    lines.append("")
    lines.append("## Acceptance bars")
    lines.append("")
    lines.append("| metric | target | actual | pass? |")
    lines.append("|---|---:|---:|:--:|")
    lines.append(
        f"| Heat pump F1   | ≥ 0.92 | {head_metrics[0][3]['f1']:.3f} | "
        f"{'✓' if head_metrics[0][3]['f1'] >= 0.92 else '✗'} |"
    )
    lines.append(
        f"| Solar pump F1  | ≥ 0.80 | {head_metrics[1][3]['f1']:.3f} | "
        f"{'✓' if head_metrics[1][3]['f1'] >= 0.80 else '✗'} |"
    )
    lines.append(
        f"| Vacuum F1      | (info) | {head_metrics[2][3]['f1']:.3f} | — |"
    )
    lines.append(
        f"| int8 latency ms | ≤ 1.5 | {int8_ms:.3f} | "
        f"{'✓' if int8_ms <= 1.5 else '✗'} |"
    )

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"[eval] wrote {OUT_MD}")
    for name, key, thr, m in head_metrics:
        print(f"  {name}: thr={thr:.2f}  F1={m['f1']:.3f}  P={m['precision']:.3f}  R={m['recall']:.3f}")
    print(f"  latency: int8={int8_ms:.3f}ms  fp32={fp32_ms:.3f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
