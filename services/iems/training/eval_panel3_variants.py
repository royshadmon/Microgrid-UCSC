#!/usr/bin/env python3
"""Compare Panel 3 variants: baseline BCE vs focal, oversample-aug, 2D attn."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import torch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services/iems/training"))
from model_panel3 import Panel3Net
from model_panel3_attn import Panel3NetAttn

NPZ = REPO / "data/panel3_windows.npz"
NORM = REPO / "services/iems/models/panel3_norm.json"
VARIANTS = [
    ("baseline_bce", REPO/"services/iems/models/nilm_panel3.pt", Panel3Net),
    ("focal_loss",   REPO/"services/iems/models/nilm_panel3_focal.pt", Panel3Net),
    ("oversample",   REPO/"services/iems/models/nilm_panel3_aug.pt", Panel3Net),
    ("attention2d",  REPO/"services/iems/models/nilm_panel3_attn.pt", Panel3NetAttn),
]
HEADS = ("refrigerator","dishwasher","microwave","dryer","washing_machine","pressure_pump","computers","tv_stereo")
THR_GRID = np.round(np.arange(0.05, 0.96, 0.01), 2)

def fmetrics(prob, y, thr):
    mask = ~np.isnan(y)
    if not mask.any(): return None
    yhat = (prob[mask] > thr).astype(np.int32); yt = (y[mask] > 0.5).astype(np.int32)
    tp = int(((yhat==1)&(yt==1)).sum()); fp = int(((yhat==1)&(yt==0)).sum())
    fn = int(((yhat==0)&(yt==1)).sum()); tn = int(((yhat==0)&(yt==0)).sum())
    p = tp/(tp+fp) if (tp+fp) else 0.0
    r = tp/(tp+fn) if (tp+fn) else 0.0
    f1 = 2*p*r/(p+r) if (p+r) else 0.0
    return {"tp":tp,"fp":fp,"fn":fn,"tn":tn,"p":p,"r":r,"f1":f1}

def predict_all(model, X):
    model.eval()
    probs = {h: [] for h in HEADS}
    with torch.no_grad():
        for i in range(0, len(X), 256):
            outs = model(torch.from_numpy(X[i:i+256]))
            for j, h in enumerate(HEADS):
                probs[h].append(outs[j].cpu().numpy())
    return {h: np.concatenate(probs[h]) for h in HEADS}

def main():
    data = np.load(NPZ); norm = json.loads(NORM.read_text())
    mean = np.array(norm["mean"], dtype=np.float32); std = np.array(norm["std"], dtype=np.float32)
    X_val = ((data["X_val"] - mean) / std).astype(np.float32)
    X_test = ((data["X_test"] - mean) / std).astype(np.float32)
    results = []
    for name, pt_path, ModelCls in VARIANTS:
        if not pt_path.exists():
            print(f"[skip] {name}: {pt_path.name} missing"); results.append({"name":name,"status":"missing"}); continue
        print(f"\n=== {name} ({pt_path.name}) ===")
        model = ModelCls(in_features=X_val.shape[-1])
        try:
            model.load_state_dict(torch.load(pt_path, map_location="cpu", weights_only=True))
        except Exception as e:
            print(f"  load failed: {e}"); results.append({"name":name,"status":f"load_error: {e}"}); continue
        t0 = time.perf_counter()
        probs_val = predict_all(model, X_val)
        val_ms = (time.perf_counter()-t0)*1000/len(X_val)
        probs_test = predict_all(model, X_test)
        head_results = []
        for h in HEADS:
            y_val = data[f"y_{h}_val"].astype(np.float32)
            y_test = data[f"y_{h}_test"].astype(np.float32)
            n_val_pos = int(((y_val>0.5)&~np.isnan(y_val)).sum())
            n_test_pos = int(((y_test>0.5)&~np.isnan(y_test)).sum())
            best_thr, best_f1 = 0.5, 0.0
            if n_val_pos >= 5:
                for thr in THR_GRID:
                    m = fmetrics(probs_val[h], y_val, float(thr))
                    if m and m["f1"] > best_f1: best_f1, best_thr = m["f1"], float(thr)
            base = fmetrics(probs_test[h], y_test, 0.5)
            tuned = fmetrics(probs_test[h], y_test, best_thr)
            head_results.append({"head":h,"n_val_pos":n_val_pos,"n_test_pos":n_test_pos,
                "best_thr":best_thr,"f1_at_0.5":base["f1"] if base else 0.0,
                "f1_tuned":tuned["f1"] if tuned else 0.0,
                "p_tuned":tuned["p"] if tuned else 0.0,"r_tuned":tuned["r"] if tuned else 0.0,
                "tp":tuned["tp"] if tuned else 0,"fp":tuned["fp"] if tuned else 0,"fn":tuned["fn"] if tuned else 0})
        macro_tuned = float(np.mean([r["f1_tuned"] for r in head_results]))
        macro_base = float(np.mean([r["f1_at_0.5"] for r in head_results]))
        print(f"  MACRO  thr=0.5: {macro_base:.4f}   tuned: {macro_tuned:.4f}   lat: {val_ms:.2f} ms/window")
        for r in head_results:
            print(f"  {r['head']:<18}thr={r['best_thr']:.2f}  test+={r['n_test_pos']:4d}  F1@.5={r['f1_at_0.5']:.3f}  F1tuned={r['f1_tuned']:.3f}")
        results.append({"name":name,"status":"ok","macro_f1_base":macro_base,"macro_f1_tuned":macro_tuned,"latency_ms":val_ms,"heads":head_results})

    out_json = REPO/"services/iems/training/reports/panel3_variants_eval.json"
    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_json}")
    out_md = REPO/"services/iems/training/reports/panel3_variants_eval.md"
    lines = ["# Panel 3 — variant comparison","",
             "_Baseline BCE vs focal loss vs oversampling vs 2D appliance attention._",
             "_All metrics on the held-out test split with per-head thresholds tuned on val._","",
             "## Macro-F1 summary","",
             "| variant | macro F1 @ 0.5 | macro F1 (tuned thr) | latency ms/window |",
             "|---|---:|---:|---:|"]
    for r in results:
        if r["status"] != "ok":
            lines.append(f"| `{r['name']}` | — | — | — _({r['status']})_ |"); continue
        lines.append(f"| `{r['name']}` | {r['macro_f1_base']:.4f} | {r['macro_f1_tuned']:.4f} | {r['latency_ms']:.2f} |")
    lines += ["","## Per-head F1 (tuned threshold)",""]
    ok = [r for r in results if r["status"]=="ok"]
    if ok:
        lines.append("| head | test+ |" + "".join(f" {r['name']} |" for r in ok))
        lines.append("|---|---:|" + "".join("---:|" for _ in ok))
        for i, h in enumerate(HEADS):
            row = [f"`{h}`", str(ok[0]["heads"][i]["n_test_pos"])]
            for r in ok: row.append(f"{r['heads'][i]['f1_tuned']:.3f}")
            lines.append("| " + " | ".join(row) + " |")
    out_md.write_text("\n".join(lines))
    print(f"wrote {out_md}")

if __name__ == "__main__":
    sys.exit(main() or 0)
