#!/usr/bin/env python3
"""Train a MultiOutputClassifier(RandomForestClassifier) per panel.

Output: services/iems/models/nilm_<panel_key>.joblib
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score
from sklearn.multioutput import MultiOutputClassifier

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "services/iems/training/data"
MODELS = REPO / "services/iems/models"
MODELS.mkdir(parents=True, exist_ok=True)

PANELS = {
    "Panel1_HVAC":    ["heat_pump"],
    "Panel2_H2O":     ["water_heater"],
    "Panel3_Kitchen": ["cooktop", "microwave", "dishwasher", "fridge"],
}

FEAT_NAMES = (
    ["mean", "std", "min", "max", "median", "range"]
    + [f"last_{j}" for j in range(10)]
    + ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]
)


def train(key: str, appliances: list[str]) -> None:
    X = np.load(DATA / f"X_{key}.npy")
    y = np.load(DATA / f"y_{key}.npy")
    print(f"\n{'=' * 60}\n{key}: {X.shape[0]} windows, {len(appliances)} appliances")
    for i, a in enumerate(appliances):
        print(f"  {a:14s}: {y[:, i].mean() * 100:.2f}% ON")

    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    clf = MultiOutputClassifier(
        RandomForestClassifier(
            n_estimators=300,
            max_depth=15,
            min_samples_leaf=5,
            class_weight="balanced",
            n_jobs=-1,
            random_state=42,
        ),
        n_jobs=-1,
    )
    print(f"  Training on {len(X_train)} samples…")
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    print(f"\n  Results on held-out {len(X_test)} samples:")
    overall_f1: list[float] = []
    eval_f1: dict[str, float] = {}
    for i, a in enumerate(appliances):
        f1 = f1_score(y_test[:, i], y_pred[:, i], zero_division=0)
        eval_f1[a] = float(f1)
        overall_f1.append(f1)
        flag = " ← REVIEW" if f1 < 0.5 else ""
        print(f"  {a:20s}  F1={f1:.3f}{flag}")
    print(f"  {'MEAN':20s}  F1={float(np.mean(overall_f1)):.3f}")

    # Average feature importances across estimators (RF doesn't expose
    # one per appliance directly through MultiOutputClassifier).
    importances = np.mean(
        [e.feature_importances_ for e in clf.estimators_], axis=0
    )
    top5_idx = np.argsort(importances)[-5:][::-1]
    print(f"  Top-5 features: {[FEAT_NAMES[j] for j in top5_idx]}")

    payload = {
        "model": clf,
        "appliances": appliances,
        "panel": key,
        "feature_dim": int(X.shape[1]),
        "feature_names": FEAT_NAMES,
        "eval_f1": eval_f1,
        "train_on_rate": {a: float(y_train[:, i].mean()) for i, a in enumerate(appliances)},
        "test_on_rate": {a: float(y_test[:, i].mean()) for i, a in enumerate(appliances)},
    }
    out = MODELS / f"nilm_{key}.joblib"
    joblib.dump(payload, out)
    print(f"  Saved → {out}")


def train_all() -> int:
    for key, apps in PANELS.items():
        try:
            train(key, apps)
        except FileNotFoundError as e:
            print(f"SKIP {key}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(train_all())
