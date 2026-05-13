#!/usr/bin/env python3
"""Sliding-window feature engineering.

Window = 100 samples (10 min at 6 s) — matches LLM4NILM.
Stride = 10 samples (1 min).

Features per window (per panel signal):
  mean, std, min, max, median, range, last-10 raw values,
  hour_sin, hour_cos, dow_sin, dow_cos      (20 floats total)
Label: majority vote over the centre 10 samples (index 45..54).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "services/iems/training/data"
WINDOW = 100
STRIDE = 10
CENTRE = slice(45, 55)

PANELS = [
    ("Panel1 (HVAC)",    "Panel1_HVAC"),
    ("Panel2 (H2O)",     "Panel2_H2O"),
    ("Panel3 (Kitchen)", "Panel3_Kitchen"),
]


def build() -> int:
    pivot_path = DATA / "raw_pivot.parquet"
    if not pivot_path.exists():
        print(f"FATAL: {pivot_path} missing — run pull_data.py first", file=sys.stderr)
        return 1
    pivot = pd.read_parquet(pivot_path)
    print(f"[windows] loaded pivot {pivot.shape}")

    for panel_nm, key in PANELS:
        if panel_nm not in pivot.columns:
            print(f"SKIP {panel_nm}")
            continue

        signal = pivot[panel_nm].fillna(0).values.astype(np.float32)
        timestamps = pivot.index

        labels_path = DATA / f"labels_{key}.parquet"
        if not labels_path.exists():
            print(f"SKIP {panel_nm}: labels not found")
            continue
        labels_df = pd.read_parquet(labels_path).reindex(pivot.index).fillna(0)

        n = len(signal)
        n_windows = max(0, (n - WINDOW) // STRIDE + 1)
        X = np.empty((n_windows, 20), dtype=np.float32)
        y = np.empty((n_windows, labels_df.shape[1]), dtype=np.int8)

        labels_arr = labels_df.values
        for wi, i in enumerate(range(0, n - WINDOW, STRIDE)):
            w = signal[i:i + WINDOW]
            ts = timestamps[i + WINDOW // 2]
            hour = ts.hour + ts.minute / 60.0
            dow = ts.dayofweek
            X[wi] = (
                w.mean(), w.std(), w.min(), w.max(),
                np.median(w), w.max() - w.min(),
                *w[-10:],
                np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24),
                np.sin(2 * np.pi * dow / 7),   np.cos(2 * np.pi * dow / 7),
            )
            centre = labels_arr[i + 45:i + 55]
            y[wi] = (centre.mean(axis=0) > 0.5).astype(np.int8)

        # Trim to actual count (the `range` upper bound may overshoot by 1).
        X = X[:wi + 1] if n_windows else X
        y = y[:wi + 1] if n_windows else y

        np.save(DATA / f"X_{key}.npy", X)
        np.save(DATA / f"y_{key}.npy", y)
        balance = ", ".join(
            f"{col}={y[:, j].mean() * 100:.2f}%"
            for j, col in enumerate(labels_df.columns)
        )
        print(f"{panel_nm}: X={X.shape}, y={y.shape}  ON-rates: {balance}")

    return 0


if __name__ == "__main__":
    sys.exit(build())
