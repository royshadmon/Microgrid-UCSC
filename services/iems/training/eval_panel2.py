#!/usr/bin/env python3
"""Evaluate Panel 2 int8 model on the held-out test split (four heads)."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort

REPO = Path(__file__).resolve().parents[3]
NPZ = REPO / "data/panel2_windows.npz"
NORM_JSON = REPO / "services/iems/models/panel2_norm.json"
INT8 = REPO / "services/iems/models/nilm_panel2_int8.onnx"
ONNX = REPO / "services/iems/models/nilm_panel2.onnx"
OUT_MD = REPO / "services/iems/training/reports/panel2_eval.md"

HEADS = ("water_heater", "hair_dryer", "sprinklers", "bath_lights")
TARGETS = {
    "water_heater": 0.90,
    "hair_dryer":   0.75,
    "sprinklers":   0.70,
    "bath_lights":  0.65,
}
LATENCY_BAR_MS = 2.5


def metrics(prob, y, thr=0.5):
    mask = ~np.isnan(y)
    n = int(mask.sum())
    if n == 0:
        return {"n": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0,
                "precision": float("nan"), "recall": float("nan"), "f1": float("nan")}
    yhat = (prob[mask] > thr).astype(np.int32)
    yt = (y[mask] > 0.5).astype(np.int32)
    tp = int(((yhat == 1) & (yt == 1)).sum())
    fp = int(((yhat == 1) & (yt == 0)).sum())
    fn = int(((yhat == 0) & (yt == 1)).sum())
    tn = int(((yhat == 0) & (yt == 0)).sum())
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

    X_test = ((data["X_test"] - mean) / std).astype(np.float32)
    if X_test.size == 0:
        print("[eval-p2] FATAL: test split empty", file=sys.stderr)
        return 1

    sess_int8 = ort.InferenceSession(str(INT8), providers=["CPUExecutionProvider"])
    sess_fp32 = ort.InferenceSession(str(ONNX), providers=["CPUExecutionProvider"])

    probs = {h: np.empty(len(X_test), dtype=np.float32) for h in HEADS}
    for i in range(0, len(X_test), 256):
        out = sess_int8.run(None, {"window": X_test[i:i + 256]})
        for j, h in enumerate(HEADS):
            probs[h][i:i + 256] = out[j].reshape(-1)

    head_metrics = []
    for h in HEADS:
        y = data[f"y_{h}_test"].astype(np.float32)
        m = metrics(probs[h], y, 0.5)
        head_metrics.append((h, m))

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

    lines = [
        "# Panel 2 — Eval (held-out test split, 4 heads)",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_",
        "",
        "## Accuracy at threshold 0.5",
        "",
        "| head | valid | TP | FP | FN | TN | P | R | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for h, m in head_metrics:
        lines.append(
            f"| `{h}` | {m['n']} | {m['tp']} | {m['fp']} | {m['fn']} | "
            f"{m['tn']} | {m['precision']:.3f} | {m['recall']:.3f} | "
            f"**{m['f1']:.3f}** |"
        )
    lines += [
        "",
        "## Confusion matrices",
        "",
    ]
    for h, m in head_metrics:
        lines += [
            f"`{h}`:",
            "```",
            "              pred=0   pred=1",
            f"  actual=0   {m['tn']:6d}   {m['fp']:6d}",
            f"  actual=1   {m['fn']:6d}   {m['tp']:6d}",
            "```",
            "",
        ]
    lines += [
        "## Latency (single window, Mac CPU)",
        "",
        "| variant | avg ms / window |",
        "|---|---:|",
        f"| FP32 ONNX | {fp32_ms:.3f} |",
        f"| int8 dynamic (MatMul-only) | {int8_ms:.3f} |",
        "",
        "## Acceptance bars (per panel2 prompt)",
        "",
        "| metric | target | actual | pass? |",
        "|---|---:|---:|:--:|",
    ]
    for h, m in head_metrics:
        tgt = TARGETS[h]
        ok = "✓" if m["f1"] >= tgt else "✗"
        lines.append(f"| {h} F1 | ≥ {tgt:.2f} | {m['f1']:.3f} | {ok} |")
    lat_ok = "✓" if int8_ms <= LATENCY_BAR_MS else "✗"
    lines.append(f"| int8 latency ms | ≤ {LATENCY_BAR_MS} | {int8_ms:.3f} | {lat_ok} |")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"[eval-p2] wrote {OUT_MD}")
    for h, m in head_metrics:
        print(f"  {h:14s}: F1={m['f1']:.3f}  P={m['precision']:.3f}  "
              f"R={m['recall']:.3f}  n={m['n']}")
    print(f"  latency: int8={int8_ms:.3f}ms  fp32={fp32_ms:.3f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
