#!/usr/bin/env python3
"""Build 100-timestep windows for Panel 3 (eight heads).

Reads  data/panel3_60d_labeled.parquet
Writes data/panel3_windows.npz
       services/iems/models/panel3_norm.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from split_utils import stratified_day_split  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
IN = REPO / "data/panel3_60d_labeled.parquet"
OUT_NPZ = REPO / "data/panel3_windows.npz"
OUT_NORM = REPO / "services/iems/models/panel3_norm.json"

WIN = 100
STRIDE = 1     # dense train sampling — every positive event matters
MID = 50
GAP_TOL = pd.Timedelta("10.5s")

FEATURES = [
    "panel1_w", "panel2_w", "panel3_w", "shop_w",
    "outside_temp", "irradiance",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "utility_tie_current",
    "panel3_w_step",
    "battery_window",
]
# pressure_pump deferred: Phase-3 re-label produced 0 positives (its events
# are swallowed by the broader washing_machine step-rule), so it cannot train.
# Re-add once the label rules separate it from the washer.
HEADS = (
    "refrigerator", "dishwasher", "microwave", "dryer",
    "washing_machine", "computers", "tv_stereo",
)
LABEL_COLS = {h: f"{h}_label" for h in HEADS}


def identify_runs(idx: pd.DatetimeIndex) -> np.ndarray:
    diffs = idx.to_series().diff()
    new_run = (diffs > GAP_TOL).fillna(False).astype(int)
    return new_run.cumsum().values


def main() -> int:
    df = pd.read_parquet(IN)
    _local = df.index.tz_convert("America/Los_Angeles")
    # Battery is charged daily 16:00-21:00 local at the Mantey site.
    df["battery_window"] = ((_local.hour >= 16) & (_local.hour < 21)).astype("float32")
    print(f"[windows-p3] loaded {len(df)} rows; range {df.index.min()} -> {df.index.max()}")

    baseline = df["panel3_w"].rolling("30min", min_periods=30).min()
    df["panel3_w_step"] = (df["panel3_w"] - baseline).clip(lower=0)

    needed = FEATURES + list(LABEL_COLS.values())
    df = df[needed].copy()
    df = df[df[FEATURES].notna().all(axis=1)]
    print(f"[windows-p3] rows with full feature vector: {len(df)}")

    # Stratified day split (keeps runs intact, guarantees per-head positives
    # in val AND test where the head has >=2 positive-days).
    df = df.sort_index()
    df["day"] = df.index.normalize()
    train_set, val_set, test_set, cov = stratified_day_split(
        df, LABEL_COLS, frac_val=0.15, frac_test=0.15)
    print(f"[windows-p3] split coverage (pos per head): {cov}")
    print(f"[windows-p3] split (by day): "
          f"train={len(train_set)} val={len(val_set)} test={len(test_set)}")

    def slide(split_days: set, stride: int) -> dict:
        sub = df[df["day"].isin(split_days)].sort_index()
        empty = {
            "X": np.empty((0, WIN, len(FEATURES)), dtype=np.float32),
            **{f"y_{h}": np.empty((0,), dtype=np.float32) for h in HEADS},
            "ts": pd.DatetimeIndex([], tz="UTC"),
        }
        if sub.empty:
            return empty
        runs = identify_runs(sub.index)
        feats = sub[FEATURES].values.astype(np.float32)
        ys = {h: sub[LABEL_COLS[h]].values.astype(np.float32) for h in HEADS}
        idx = sub.index
        chunks: dict = {"X": [], **{f"y_{h}": [] for h in HEADS}, "ts": []}
        for run_id in np.unique(runs):
            mask = runs == run_id
            if mask.sum() < WIN:
                continue
            r_feats = feats[mask]
            r_y = {h: ys[h][mask] for h in HEADS}
            r_ts = idx[mask]
            for i in range(0, len(r_feats) - WIN + 1, stride):
                mid_lbls = [r_y[h][i + MID] for h in HEADS]
                if all(np.isnan(v) for v in mid_lbls):
                    continue
                chunks["X"].append(r_feats[i:i + WIN])
                for h in HEADS:
                    chunks[f"y_{h}"].append(r_y[h][i + MID])
                chunks["ts"].append(r_ts[i + MID])
        if not chunks["X"]:
            return empty
        return {
            "X": np.stack(chunks["X"]).astype(np.float32),
            **{f"y_{h}": np.asarray(chunks[f"y_{h}"], dtype=np.float32) for h in HEADS},
            "ts": pd.DatetimeIndex(chunks["ts"]),
        }

    splits = {
        "train": slide(train_set, STRIDE),
        "val":   slide(val_set, 1),
        "test":  slide(test_set, 1),
    }

    for name, d in splits.items():
        X = d["X"]
        print(f"[windows-p3] {name}: X={X.shape}")
        if X.size:
            for h in HEADS:
                y = d[f"y_{h}"]
                valid = ~np.isnan(y)
                n_valid = int(valid.sum())
                pos = int((y == 1).sum())
                rate = (y[valid].mean() if valid.any() else float("nan"))
                print(f"[windows-p3]   {name}/{h:16s}: valid={n_valid}  pos={pos}  rate={rate:.4f}")

    X_train = splits["train"]["X"]
    if X_train.size == 0:
        print("[windows-p3] FATAL: train split empty", file=sys.stderr)
        return 1

    flat = X_train.reshape(-1, X_train.shape[-1])
    mean = flat.mean(axis=0)
    std = flat.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)

    norm_payload = {
        "features": FEATURES,
        "mean": mean.tolist(),
        "std":  std.tolist(),
        "window": WIN,
        "stride": STRIDE,
        "mid": MID,
        "heads": list(HEADS),
    }
    OUT_NORM.parent.mkdir(parents=True, exist_ok=True)
    OUT_NORM.write_text(json.dumps(norm_payload, indent=2))
    print(f"[windows-p3] wrote {OUT_NORM}")

    save_kwargs = {"X_train": splits["train"]["X"]}
    for h in HEADS:
        save_kwargs[f"y_{h}_train"] = splits["train"][f"y_{h}"]
        save_kwargs[f"y_{h}_val"]   = splits["val"][f"y_{h}"]
        save_kwargs[f"y_{h}_test"]  = splits["test"][f"y_{h}"]
    save_kwargs["X_val"] = splits["val"]["X"]
    save_kwargs["X_test"] = splits["test"]["X"]
    save_kwargs["ts_train"] = splits["train"]["ts"].astype("int64")
    save_kwargs["ts_val"] = splits["val"]["ts"].astype("int64")
    save_kwargs["ts_test"] = splits["test"]["ts"].astype("int64")
    np.savez_compressed(OUT_NPZ, **save_kwargs)
    print(f"[windows-p3] wrote {OUT_NPZ}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
