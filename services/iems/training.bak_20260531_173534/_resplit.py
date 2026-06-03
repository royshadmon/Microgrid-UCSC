"""Shared helper: pool the broken sequential train/val/test windows and re-split
with shuffling so each class is represented in val and test.

The original splits in data/panel*_windows.npz are sequential time blocks and
landed val on positive-free days for Panel 2. For training comparison we need
val/test to actually have positives.
"""
import numpy as np


def pool_and_resplit(npz, heads, seed=7, val_frac=0.15, test_frac=0.15):
    X_all = np.concatenate([npz["X_train"], npz["X_val"], npz["X_test"]], axis=0)
    ts_all = np.concatenate([npz["ts_train"], npz["ts_val"], npz["ts_test"]], axis=0)
    y_all = {}
    for h in heads:
        y_all[h] = np.concatenate(
            [npz[f"y_{h}_train"], npz[f"y_{h}_val"], npz[f"y_{h}_test"]], axis=0
        ).astype(np.float32)

    n = X_all.shape[0]
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    n_test = int(round(test_frac * n))
    n_val = int(round(val_frac * n))
    n_train = n - n_val - n_test
    idx_train = idx[:n_train]
    idx_val = idx[n_train:n_train + n_val]
    idx_test = idx[n_train + n_val:]

    out = {
        "X_train": X_all[idx_train], "X_val": X_all[idx_val], "X_test": X_all[idx_test],
        "ts_train": ts_all[idx_train], "ts_val": ts_all[idx_val], "ts_test": ts_all[idx_test],
    }
    for h in heads:
        out[f"y_{h}_train"] = y_all[h][idx_train]
        out[f"y_{h}_val"] = y_all[h][idx_val]
        out[f"y_{h}_test"] = y_all[h][idx_test]

    print(f"[resplit] pooled n={n}  train={n_train}  val={n_val}  test={n_test}")
    for h in heads:
        for split, ix in (("train", idx_train), ("val", idx_val), ("test", idx_test)):
            y = y_all[h][ix]
            n_pos = int(((y == 1) & ~np.isnan(y)).sum())
            n_neg = int(((y == 0) & ~np.isnan(y)).sum())
            n_nan = int(np.isnan(y).sum())
            print(f"[resplit]   {h:14s} {split:5s}: pos={n_pos:5d} neg={n_neg:5d} nan={n_nan:5d}")
    return out
