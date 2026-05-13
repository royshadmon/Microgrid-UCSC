#!/usr/bin/env python3
"""Quick sanity check: load each NILM joblib and run one random window."""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np

REPO = Path(__file__).resolve().parents[3]
MODELS = REPO / "services/iems/models"


def main() -> int:
    files = sorted(MODELS.glob("nilm_*.joblib"))
    if not files:
        print(f"FATAL: no nilm_*.joblib in {MODELS}", file=sys.stderr)
        return 1
    rng = np.random.default_rng(0)
    for f in files:
        payload = joblib.load(f)
        clf = payload["model"]
        apps = payload["appliances"]
        dim = payload["feature_dim"]
        f1s = payload.get("eval_f1", {})
        x = rng.standard_normal((1, dim)).astype(np.float32)
        pred = clf.predict(x)[0]
        print(f"\n{f.stem}")
        for a, p in zip(apps, pred):
            f1 = f1s.get(a)
            f1_str = f"{f1:.3f}" if isinstance(f1, (int, float)) else "n/a"
            print(f"  {a:14s}: pred={int(p)}  eval_F1={f1_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
