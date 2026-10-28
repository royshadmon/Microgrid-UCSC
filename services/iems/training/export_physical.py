#!/usr/bin/env python3
"""Export the retrained physical-model BiLSTMs to ONNX.

Replaces export_panel{1,2,3}.py, which hard-coded both the old file names
(nilm_panelN.pt / panelN_norm.json) and the old output names -- Panel1 listed
exactly two outputs, so it could not export a 5-head model at all.

This reads the head list from canonical_signatures.PANEL_HEADS, so the ONNX
output names always match whatever the model was actually trained with. That
coupling is the point: a silent mismatch between ONNX output order and the
names the inference loop expects would mislabel every appliance without
raising anything.

Usage:
    python3 services/iems/training/export_physical.py            # all panels
    python3 services/iems/training/export_physical.py --panel 1
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

import canonical_signatures as CS  # noqa: E402
from model_panel1 import Panel1Net  # noqa: E402
from model_panel2 import Panel2Net  # noqa: E402
from model_panel3 import Panel3Net  # noqa: E402

NETS = {1: Panel1Net, 2: Panel2Net, 3: Panel3Net}
MODELS = REPO / "services/iems/models"
TRAINED = HERE / "models"


def _inline_external_data(onnx_path: Path) -> None:
    """Keep the export a single self-contained file.

    Newer torch (the dynamo exporter, default from torch 2.9, which is what the
    NGC containers on the GX10 carry) can write the weights to a side file
    `<name>.onnx.data`. The inference images copy services/iems/models/ and
    the deploy checks md5 one file, so a side file is easy to lose and the
    model would then fail to load. Fold any external tensors back in.
    """
    import onnx
    side = onnx_path.with_name(onnx_path.name + ".data")
    m = onnx.load(str(onnx_path), load_external_data=True)
    onnx.save_model(m, str(onnx_path), save_as_external_data=False)
    if side.exists():
        side.unlink()


def export(panel: int, quantize: bool = False) -> None:
    norm_path = MODELS / f"panel{panel}_norm_bilstm.json"
    pt_path = TRAINED / f"panel{panel}_bilstm_physical.pt"
    onnx_path = MODELS / f"nilm_panel{panel}.onnx"

    if not pt_path.exists():
        raise SystemExit(f"missing {pt_path} -- run train_all_physical.py first")
    norm = json.loads(norm_path.read_text())
    feats = norm.get("features") or norm.get("feature_names")
    n_features = len(feats)
    win = int(norm.get("window", 100))

    Net = NETS[panel]
    heads = list(Net.HEADS)
    expected = list(CS.PANEL_HEADS[panel])
    if heads != expected:
        raise SystemExit(
            f"panel{panel}: model HEADS {heads} != PANEL_HEADS {expected}. "
            "Refusing to export a model whose outputs would be misnamed.")

    model = Net(in_features=n_features)
    state = torch.load(pt_path, map_location="cpu")
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing:
        print(f"      WARNING panel{panel}: {len(missing)} missing key(s), "
              f"e.g. {missing[:2]}")
    if unexpected:
        print(f"      WARNING panel{panel}: {len(unexpected)} unexpected key(s), "
              f"e.g. {unexpected[:2]}")
    model.eval()

    # Back up the incumbent before overwriting -- the head count is changing, so
    # a rollback needs the old file, not just the old weights.
    if onnx_path.exists():
        bak = onnx_path.with_suffix(f".onnx.bak_{n_features}f_{len(heads)}h")
        if not bak.exists():
            bak.write_bytes(onnx_path.read_bytes())
            print(f"      backed up incumbent -> {bak.name}")

    dummy = torch.randn(1, win, n_features)
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=["window"],
        output_names=[f"p_{h}" for h in heads],
        dynamic_axes={"window": {0: "batch"}},
        opset_version=17,
        # The TorchScript exporter, which produced every deployed model. The
        # dynamo exporter (the default from torch 2.9, so in the NGC images)
        # bakes batch=1 into the LSTM reshapes: batch 1 verifies, any larger
        # batch fails in ONNX Runtime. build_sft.py runs the teacher at 2048.
        **({"dynamo": False} if "dynamo" in inspect.signature(torch.onnx.export).parameters else {}),
    )
    _inline_external_data(onnx_path)
    print(f"[export] panel{panel}: {len(heads)} heads, {n_features} features, "
          f"win={win} -> {onnx_path.name} ({onnx_path.stat().st_size/1024:.0f} KB)")

    if quantize:
        try:
            from onnxruntime.quantization import quantize_dynamic, QuantType
            int8 = MODELS / f"nilm_panel{panel}_int8.onnx"
            quantize_dynamic(str(onnx_path), str(int8),
                             weight_type=QuantType.QInt8,
                             op_types_to_quantize=["MatMul"])
            print(f"           int8 -> {int8.name} ({int8.stat().st_size/1024:.0f} KB)")
        except Exception as e:
            print(f"           int8 skipped: {e}")


def verify(panel: int) -> None:
    """Load the exported graph and confirm shapes and names round-trip."""
    import numpy as np
    import onnxruntime as ort
    onnx_path = MODELS / f"nilm_panel{panel}.onnx"
    norm = json.loads((MODELS / f"panel{panel}_norm_bilstm.json").read_text())
    feats = norm.get("features") or norm.get("feature_names")
    win = int(norm.get("window", 100))
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    outs = [o.name for o in sess.get_outputs()]
    x = np.random.randn(1, win, len(feats)).astype("float32")
    y = sess.run(None, {"window": x})
    # the batch axis must really be dynamic: the teacher pass runs 2048 at once
    yb = sess.run(None, {"window": np.random.randn(64, win, len(feats)).astype("float32")})
    assert np.asarray(yb[0]).reshape(-1).shape[0] == 64, "batch axis is not dynamic"
    exp = [f"p_{h}" for h in CS.PANEL_HEADS[panel]]
    ok = outs == exp
    print(f"[verify] panel{panel}: {len(outs)} outputs, names {'MATCH' if ok else 'MISMATCH'}, "
          f"first value {float(np.ravel(y[0])[0]):.4f}")
    if not ok:
        print(f"         got      {outs}")
        print(f"         expected {exp}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=int, choices=[1, 2, 3])
    ap.add_argument("--quantize", action="store_true")
    a = ap.parse_args()
    panels = [a.panel] if a.panel else [1, 2, 3]
    for p in panels:
        export(p, quantize=a.quantize)
    for p in panels:
        verify(p)


if __name__ == "__main__":
    main()
