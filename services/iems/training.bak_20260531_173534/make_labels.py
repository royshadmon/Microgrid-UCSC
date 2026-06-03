#!/usr/bin/env python3
"""Derive binary ON/OFF labels from raw panel watt readings using fixed
power thresholds (Xue et al. 2025, §4.1).

Panel1 (HVAC)    → heat_pump       ON > 200 W
Panel2 (H2O)     → water_heater    ON > 300 W
Panel3 (Kitchen) → fridge / dishwasher / microwave / cooktop
                   (hierarchical, see THRESHOLDS below)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "services/iems/training/data"

THRESHOLDS = {
    "Panel1 (HVAC)": {
        "heat_pump":    200,
    },
    "Panel2 (H2O)": {
        "water_heater": 300,
    },
    "Panel3 (Kitchen)": {
        # Kitchen total is a composite — use sub-range heuristics.
        # Fridge runs continuously ~150W; microwave spikes ~1500W;
        # dishwasher ~1800W; cooktop ~800-2400W.
        "fridge":       50,
        "microwave":    200,
        "dishwasher":   400,
        "cooktop":      800,
    },
}


def make_labels() -> int:
    src = DATA / "raw_pivot.parquet"
    if not src.exists():
        print(f"FATAL: {src} not found — run pull_data.py first", file=sys.stderr)
        return 1
    pivot = pd.read_parquet(src)
    print(f"[labels] loaded {pivot.shape} from {src}")

    for panel, apps in THRESHOLDS.items():
        if panel not in pivot.columns:
            print(f"WARN: {panel} not in pivot, skipping")
            continue

        series = pivot[panel].fillna(0)

        if panel == "Panel3 (Kitchen)":
            # Hierarchical: assign to the highest-power appliance whose
            # band contains the reading, so the same watt doesn't get
            # counted as both microwave and cooktop.
            labels = pd.DataFrame(index=series.index)
            labels["cooktop"]    = (series > 800).astype(int)
            labels["microwave"]  = ((series > 200) & (series <= 800)).astype(int)
            labels["dishwasher"] = (
                (series > 400) & (series <= 1800)
                & (labels["cooktop"] == 0)
                & (labels["microwave"] == 0)
            ).astype(int)
            labels["fridge"]     = ((series > 50) & (series <= 200)).astype(int)
        else:
            labels = pd.DataFrame(index=series.index)
            for app, thresh in apps.items():
                labels[app] = (series > thresh).astype(int)

        key = panel.replace(" ", "_").replace("(", "").replace(")", "")
        out = DATA / f"labels_{key}.parquet"
        labels.to_parquet(out)
        rates = ", ".join(f"{a}={labels[a].mean() * 100:.1f}%" for a in labels.columns)
        print(f"{panel}: saved {labels.shape} — ON rates: {rates}")

    return 0


if __name__ == "__main__":
    sys.exit(make_labels())
