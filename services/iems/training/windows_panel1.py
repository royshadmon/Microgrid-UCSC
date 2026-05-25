#!/usr/bin/env python3
"""Build 100-timestep windows for Panel 1 (three heads).

Reads  data/panel1_60d_labeled.parquet
Writes data/panel1_windows.npz
       services/iems/models/panel1_norm.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
IN = REPO / "data/panel1_60d_labeled.parquet"
OUT_NPZ = REPO / "data/panel1_windows.npz"
OUT_NORM = REPO / "services/iems/models/panel1_norm.json"

WIN = 100
STRIDE = 10
MID = 50
GAP_TOL = pd.Timedelta("10.5s")

FEATURES = [
    "panel1_w", "panel2_w", "panel3_w", "shop_w",
    "outside_temp", "irradiance",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "utility_tie_current",
    "panel1_w_step",
]
HEAD_LABELS = {
    "hp": "heat_pump_label",
    "sp": "solar_pump_label",
}


def identify_runs(idx: pd.DatetimeIndex) -> np.ndarray:
    diffs = idx.to_series().diff()
    new_run = (diffs > GAP_TOL).fillna(False).astype(int)
    return new_run.cumsum().values


def main() -> int:
    df = pd.read_parquet(IN)
    print(f"[windows] loaded {len(df)} rows")
    needed = FEATURES + list(HEAD_LABELS.values())
    df = df[needed].copy()
    df = df[df[FEATURES].notna().all(axis=1)]
    print(f"[windows] rows with full feature vector: {len(df)}")

    df["day"] = df.index.normalize()
    days = sorted(df["day"].unique())
    n = len(days)
    # Chronological split tuned for label sparsity. May 5 in train (postgres
    # union added ~13 hours there). Val pairs May 6 + 7 so both the HP head
    # (May 6 dominant) and the SP head (May 7 dominant) get a non-trivial
    # validation signal. Test is the tail (May 11, 12) where we observe live
    # behavior.
    #   train = April 21 → May 5   (11 days, idx 0..10)
    #   val   = May 6, 7            (2 days, idx 11..12)
    #   test  = May 11, 12          (2 days, idx 13..14)
    if n == 15:
        train_days = set(days[:11])
        val_days   = set(days[11:13])
        test_days  = set(days[13:])
    else:
        n_train = int(round(n * 0.70))
        n_val = int(round(n * 0.10))
        train_days = set(days[:n_train])
        val_days = set(days[n_train:n_train + n_val])
        test_days = set(days[n_train + n_val:])
    print(f"[windows] days: total={n}  train={len(train_days)}  "
          f"val={len(val_days)}  test={len(test_days)}")
    for split, ds in [("train", train_days), ("val", val_days), ("test", test_days)]:
        print(f"[windows] {split}: {sorted(ds)}")

    def slide(split_days: set, stride: int) -> dict:
        sub = df[df["day"].isin(split_days)].sort_index()
        if sub.empty:
            return {
                "X": np.empty((0, WIN, len(FEATURES)), dtype=np.float32),
                "y_hp": np.empty((0,), dtype=np.float32),
                "y_sp": np.empty((0,), dtype=np.float32),
                "ts":   pd.DatetimeIndex([], tz="UTC"),
            }
        runs = identify_runs(sub.index)
        feats = sub[FEATURES].values.astype(np.float32)
        ys = {k: sub[v].values.astype(np.float32) for k, v in HEAD_LABELS.items()}
        idx = sub.index
        chunks = {"X": [], "y_hp": [], "y_sp": [], "ts": []}
        for run_id in np.unique(runs):
            mask = runs == run_id
            if mask.sum() < WIN:
                continue
            r_feats = feats[mask]
            r_y = {k: ys[k][mask] for k in ys}
            r_ts = idx[mask]
            for i in range(0, len(r_feats) - WIN + 1, stride):
                mid_lbls = [r_y[k][i + MID] for k in ("hp", "sp")]
                # keep window if at least ONE head has a valid label
                if all(np.isnan(v) for v in mid_lbls):
                    continue
                chunks["X"].append(r_feats[i:i + WIN])
                chunks["y_hp"].append(r_y["hp"][i + MID])
                chunks["y_sp"].append(r_y["sp"][i + MID])
                chunks["ts"].append(r_ts[i + MID])
        if not chunks["X"]:
            return {
                "X": np.empty((0, WIN, len(FEATURES)), dtype=np.float32),
                "y_hp": np.empty((0,), dtype=np.float32),
                "y_sp": np.empty((0,), dtype=np.float32),
                "ts":   pd.DatetimeIndex([], tz="UTC"),
            }
        return {
            "X": np.stack(chunks["X"]).astype(np.float32),
            "y_hp": np.asarray(chunks["y_hp"], dtype=np.float32),
            "y_sp": np.asarray(chunks["y_sp"], dtype=np.float32),
            "ts":   pd.DatetimeIndex(chunks["ts"]),
        }

    splits = {
        "train": slide(train_days, STRIDE),
        "val":   slide(val_days, 1),
        "test":  slide(test_days, 1),
    }

    for name, d in splits.items():
        X = d["X"]
        if X.size:
            for h in ("hp", "sp"):
                y = d[f"y_{h}"]
                valid = ~np.isnan(y)
                n_valid = int(valid.sum())
                pos = int((y == 1).sum())
                rate = (y[valid].mean() if valid.any() else float("nan"))
                print(f"[windows] {name}/{h}: valid={n_valid}  pos={pos}  rate={rate:.3f}")
        print(f"[windows] {name}: X={X.shape}")

    X_train = splits["train"]["X"]
    if X_train.size == 0:
        print("[windows] FATAL: train split empty", file=sys.stderr)
        return 1

    flat = X_train.reshape(-1, X_train.shape[-1])
    mean = flat.mean(axis=0)
    std = flat.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)

    # Preserve existing thresholds from norm.json if present
    existing = {}
    if OUT_NORM.exists():
        try:
            existing = json.loads(OUT_NORM.read_text())
        except Exception:
            existing = {}
    norm_payload = {
        "features": FEATURES,
        "mean": mean.tolist(),
        "std":  std.tolist(),
        "window": WIN,
        "stride": STRIDE,
        "mid": MID,
        "heads": ["heat_pump", "solar_pump"],
    }
    if "thresholds" in existing:
        norm_payload["thresholds"] = existing["thresholds"]
    OUT_NORM.parent.mkdir(parents=True, exist_ok=True)
    OUT_NORM.write_text(json.dumps(norm_payload, indent=2))
    print(f"[windows] wrote {OUT_NORM}")

    np.savez_compressed(
        OUT_NPZ,
        X_train=splits["train"]["X"],
        y_hp_train=splits["train"]["y_hp"], y_sp_train=splits["train"]["y_sp"],
        X_val=splits["val"]["X"],
        y_hp_val=splits["val"]["y_hp"], y_sp_val=splits["val"]["y_sp"],
        X_test=splits["test"]["X"],
        y_hp_test=splits["test"]["y_hp"], y_sp_test=splits["test"]["y_sp"],
        ts_train=splits["train"]["ts"].astype("int64"),
        ts_val=splits["val"]["ts"].astype("int64"),
        ts_test=splits["test"]["ts"].astype("int64"),
    )
    print(f"[windows] wrote {OUT_NPZ}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
