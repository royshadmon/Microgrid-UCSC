#!/usr/bin/env python3
"""Phase 0 - eGauge register inventory.

Derives the channel/register map from the consolidated eGauge parquet:
coverage, duty statistics, quantiles, and a dedicated-vs-shared
classification. Emits a CSV inventory plus a YAML skeleton for breaker
ratings that the Phase 4 breaker-margin detector consumes.

Usage:
    .venv-training/bin/python analysis/inventory/build_register_inventory.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SRC = "analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet"
OUT_DIR = Path("analysis/inventory")

# Channels that are not power registers and must never reach a power detector.
NON_POWER = {"VrmsA", "VrmsB", "F1", "Current on Utility Tie",
             "I11", "I12", "I21", "I22", "I31", "I32"}

# Known appliance counts per panel, from services/iems/training/data/dual_label_summary.csv
PANEL_APPLIANCES = {
    "Panel1 (HVAC)": ["heat_pump", "solar_pump"],
    "Panel2 (H2O)": ["water_heater", "hair_dryer", "sprinklers", "bath_lights"],
    "Panel3 (Kitchen)": ["dryer", "washing_machine", "dishwasher", "microwave",
                          "pressure_pump", "refrigerator", "computers",
                          "tv_stereo", "vacuum_cleaner"],
}

# Water-coupled loads: the leak-inference surface (design doc v0.2 section 3).
WATER_COUPLED = {"water_heater", "sprinklers", "pressure_pump", "solar_pump",
                 "dishwasher", "washing_machine"}


def classify(channel: str, n_appliances: int) -> str:
    if channel in NON_POWER:
        return "instrument"
    if channel in ("Grid Power", "Generac Power"):
        return "aggregate"
    if n_appliances == 0:
        return "unmapped"
    if n_appliances == 1:
        return "dedicated"
    return "shared"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] reading {args.src} ...", flush=True)
    d = pd.read_parquet(args.src, columns=["ts", "channel", "w"])
    d["ts"] = pd.to_datetime(d["ts"], errors="coerce")
    d = d.dropna(subset=["ts"])

    print(f"      {len(d):,} rows, {d.channel.nunique()} channels", flush=True)
    print("[2/4] computing per-register statistics ...", flush=True)

    rows = []
    for ch, g in d.groupby("channel", sort=True):
        w = pd.to_numeric(g["w"], errors="coerce").dropna()
        if w.empty:
            continue
        span_h = (g.ts.max() - g.ts.min()).total_seconds() / 3600.0
        # Sampling cadence, inferred from the median inter-sample gap.
        gaps = g.ts.sort_values().diff().dt.total_seconds().dropna()
        cadence = float(gaps.median()) if len(gaps) else float("nan")
        # Expected sample count at that cadence tells us how complete coverage is.
        expected = (span_h * 3600.0 / cadence) if cadence and cadence > 0 else np.nan
        coverage = float(len(w) / expected) if expected and expected > 0 else np.nan

        apps = PANEL_APPLIANCES.get(ch, [])
        kind = classify(ch, len(apps))
        p05, p50, p95, p99 = (float(w.quantile(q)) for q in (0.05, 0.50, 0.95, 0.99))

        rows.append({
            "channel": ch,
            "kind": kind,
            "n_appliances": len(apps),
            "appliances": ";".join(apps),
            "water_coupled": ";".join(a for a in apps if a in WATER_COUPLED),
            "n_samples": int(len(w)),
            "first_seen": g.ts.min(),
            "last_seen": g.ts.max(),
            "span_hours": round(span_h, 1),
            "cadence_s": round(cadence, 2) if cadence == cadence else None,
            "coverage_frac": round(coverage, 4) if coverage == coverage else None,
            "min_w": round(float(w.min()), 1),
            "p05_w": round(p05, 1),
            "median_w": round(p50, 1),
            "p95_w": round(p95, 1),
            "p99_w": round(p99, 1),
            "max_w": round(float(w.max()), 1),
            "mean_w": round(float(w.mean()), 1),
            "negative_frac": round(float((w < 0).mean()), 4),
            "zero_frac": round(float((w == 0).mean()), 4),
            # NILM is only worth running where a register carries >1 appliance.
            "nilm_required": kind == "shared",
        })

    inv = pd.DataFrame(rows).sort_values(["kind", "channel"])
    csv_path = out_dir / "register_inventory.csv"
    inv.to_csv(csv_path, index=False)
    print(f"      wrote {csv_path}", flush=True)

    print("[3/4] emitting breaker-rating skeleton ...", flush=True)
    # Only power registers get a breaker rating. Ratings are left null on
    # purpose: guessing them would give the Phase 4 safety detector a
    # fabricated threshold, which is worse than having no detector.
    power = inv[~inv.kind.isin(["instrument"])]
    lines = [
        "# Phase 4 breaker-margin detector - register ratings.",
        "#",
        "# FILL IN breaker_amps AND volts FOR EACH REGISTER FROM THE PANEL LABELS.",
        "# Registers left null are SKIPPED by the detector (no rating, no alert).",
        "# watts_rating is computed as breaker_amps * volts unless set explicitly.",
        "#",
        "# observed_max_w below is measured, NOT a rating - it is shown only to",
        "# sanity-check the value you enter (a rating under observed max is wrong).",
        "",
        "defaults:",
        "  sustain_minutes: 15      # dwell before a margin breach alerts",
        "  margin_frac: 0.80        # fraction of rating that counts as a breach",
        "  clear_frac: 0.70         # must drop below this to clear (hysteresis)",
        "",
        "registers:",
    ]
    for _, r in power.iterrows():
        lines += [
            f"  {json.dumps(r.channel)}:",
            f"    breaker_amps: null      # TODO  (observed_max_w={r.max_w})",
            f"    volts: null             # TODO  (240 for most US branch circuits)",
            f"    watts_rating: null      # optional explicit override",
            f"    kind: {r.kind}",
            "",
        ]
    yaml_path = out_dir / "breaker_ratings.yaml"
    yaml_path.write_text("\n".join(lines))
    print(f"      wrote {yaml_path}", flush=True)

    print("[4/4] summary", flush=True)
    for kind, g in inv.groupby("kind"):
        print(f"      {kind:<10} {len(g):>2}  {', '.join(g.channel)}")
    todo = int((~power.channel.isin([])).sum())
    print(f"\n      {todo} registers need breaker ratings filled in "
          f"before the Phase 4 detector can arm.")


if __name__ == "__main__":
    main()
