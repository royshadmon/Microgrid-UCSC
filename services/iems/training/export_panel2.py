#!/usr/bin/env python3
"""Export Panel2Net to ONNX and int8-quantized ONNX (four heads)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import torch
from onnxruntime.quantization import quantize_dynamic, QuantType

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_panel2 import Panel2Net  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
MODELS = REPO / "services/iems/models"
NORM = MODELS / "panel2_norm.json"
PT = MODELS / "nilm_panel2.pt"
ONNX = MODELS / "nilm_panel2.onnx"
INT8 = MODELS / "nilm_panel2_int8.onnx"


def main() -> int:
    norm = json.loads(NORM.read_text())
    n_features = len(norm["features"])
    win = int(norm["window"])

    model = Panel2Net(in_features=n_features)
    model.load_state_dict(torch.load(PT, map_location="cpu"))
    model.eval()

    dummy = torch.randn(1, win, n_features)
    output_names = [f"p_{h}" for h in Panel2Net.HEADS]
    torch.onnx.export(
        model, dummy,
        str(ONNX),
        input_names=["window"],
        output_names=output_names,
        dynamic_axes={"window": {0: "batch"}},
        opset_version=17,
    )
    print(f"[export-p2] wrote {ONNX} ({ONNX.stat().st_size / 1024:.1f} KB)")

    quantize_dynamic(
        str(ONNX), str(INT8),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul"],
    )
    print(f"[export-p2] wrote {INT8} ({INT8.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
