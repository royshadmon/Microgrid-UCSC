#!/usr/bin/env python3
"""Export a trained MATNilm 2DMA dual-head model to ONNX, with parity check.

  python export_matnilm.py --panel {1|2|3}

Rebuilds the MATNilm module from the saved config + heads in
reports/panel{P}_matnilm_train.json, loads models/nilm_panel{P}_matnilm.pt,
and exports models/nilm_panel{P}_matnilm.onnx with a dynamic batch axis
(opset 17, input `x` shape [B,100,13]). Output names are prob_<head>... then
pow_<head>... in head order (the forward returns tuple(probs)+tuple(powers)).

Then verifies PyTorch vs onnxruntime agree to < 1e-4 max abs prob diff on 64
val windows. No int8 quantization (the legacy _int8.onnx are left in place).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_matnilm import MATNilm  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
MODELS = REPO / "services/iems/models"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=int, required=True, choices=(1, 2, 3))
    args = ap.parse_args()
    P = args.panel

    report = json.loads((REPO / f"services/iems/training/reports/"
                         f"panel{P}_matnilm_train.json").read_text())
    norm = json.loads((MODELS / f"panel{P}_norm.json").read_text())
    heads = tuple(report["heads"])
    cfg = report["config"]
    win = int(norm["window"])
    mid = int(norm["mid"])
    in_features = len(norm["features"])
    assert in_features == int(report["in_features"]), "feature-count mismatch"
    assert mid == win // 2, f"mid {mid} != window//2 {win // 2}"

    model = MATNilm(heads=heads, in_features=in_features, window=win, mid=mid, **cfg)
    pt = MODELS / f"nilm_panel{P}_matnilm.pt"
    model.load_state_dict(torch.load(pt, map_location="cpu"))
    model.eval()
    print(f"[export] panel{P} heads={heads} in_features={in_features} "
          f"window={win} mid={mid} cfg={cfg}")

    onnx_path = MODELS / f"nilm_panel{P}_matnilm.onnx"
    out_names = [f"prob_{h}" for h in heads] + [f"pow_{h}" for h in heads]
    dummy = torch.randn(1, win, in_features)
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=["x"], output_names=out_names,
        dynamic_axes={"x": {0: "batch"}, **{n: {0: "batch"} for n in out_names}},
        opset_version=17,
    )
    size_kb = onnx_path.stat().st_size / 1024
    print(f"[export] wrote {onnx_path} ({size_kb:.1f} KB)")

    # ---- parity check: PyTorch vs onnxruntime on 64 val windows ----
    import onnxruntime as ort
    npz = np.load(REPO / f"data/panel{P}_windows.npz")
    Xva = npz["X_val"][:64]
    mean = np.array(norm["mean"], np.float32)
    std = np.array(norm["std"], np.float32)
    std = np.where(std < 1e-6, 1.0, std)
    Xn = ((Xva - mean) / std).astype(np.float32)

    with torch.no_grad():
        tout = model(torch.from_numpy(Xn))
    H = len(heads)
    t_probs = np.stack([tout[i].numpy() for i in range(H)], axis=1)  # (64, H)

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    oout = sess.run(out_names, {"x": Xn})
    o_probs = np.stack([np.asarray(oout[i]).reshape(-1) for i in range(H)], axis=1)

    max_diff = float(np.max(np.abs(t_probs - o_probs)))
    ok = max_diff < 1e-4
    print(f"[parity] panel{P} prob max|diff|={max_diff:.2e}  "
          f"{'PASS' if ok else 'FAIL'} (threshold 1e-4)")
    if not ok:
        return 1
    print(f"[export] panel{P} OK -> {onnx_path.name} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
