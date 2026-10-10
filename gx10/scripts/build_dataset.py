#!/usr/bin/env python3
"""Turn the export from Pat's box into the parquet files the training
pipeline already reads, so nothing under services/iems/training is forked.

  in   gx10/data/export/egauge_6s/*.csv.gz   (pat_export_remote.sh)
       gx10/data/export/solar.csv.gz
       optional older archive, e.g.
       analysis/egauge_consolidation/egauge_merged_mar_aug.parquet

  out  gx10/data/egauge_gx10.parquet   long format: ts, channel, w
                                       (the columns train_rolling.py,
                                       physical_labeler_v2.py and
                                       gen_norm_physical.py read)
       gx10/data/solar_gx10.parquet    ts index; pv_power, battery_power,
                                       battery_soc, grid_power, load_power
                                       (the shape solar_features.solar_frame
                                       reads)

Rows are deduplicated on (ts, channel); where an archive row and an export
row collide, the export wins because it is the newer read of the same meter.

Usage
  python3 gx10/scripts/build_dataset.py \
      --export gx10/data/export \
      --archive analysis/egauge_consolidation/egauge_merged_mar_aug.parquet \
      --solar-archive analysis/solar/solar_history.parquet
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import pandas as pd

CHANNELS = {
    "Current on Utility Tie", "F1", "Generac Power", "Grid Power", "I11", "I12",
    "I21", "I22", "I31", "I32", "Panel1 (HVAC)", "Panel2 (H2O)",
    "Panel3 (Kitchen)", "Shop", "VrmsA", "VrmsB",
}
SOLAR_COLS = ["pv_power", "battery_power", "battery_soc", "grid_power", "load_power"]


def load_export(export_dir: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(export_dir, "egauge_6s", "*.csv.gz")))
    if not files:
        sys.exit(f"no egauge_6s/*.csv.gz under {export_dir}; run export_pat_data.sh first")
    parts = []
    for f in files:
        d = pd.read_csv(f, dtype={"channel": "string"})
        if len(d):
            parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d["ts"] = pd.to_datetime(d["ts"])
    d["w"] = pd.to_numeric(d["w"], errors="coerce").astype("float32")
    d = d.dropna(subset=["w"])
    print(f"export: {len(files)} days, {len(d):,} rows, {d.ts.min()} -> {d.ts.max()}")
    return d[["ts", "channel", "w"]]


def load_archive(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    if not os.path.exists(path):
        print(f"archive {path} not found, training on the export alone")
        return None
    a = pd.read_parquet(path, columns=["ts", "channel", "w"])
    a["w"] = a["w"].astype("float32")
    print(f"archive: {len(a):,} rows, {a.ts.min()} -> {a.ts.max()}")
    return a


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", default="gx10/data/export")
    ap.add_argument("--archive", default=None,
                    help="older long-format parquet to prepend (ts, channel, w)")
    ap.add_argument("--solar-archive", default=None)
    ap.add_argument("--out", default="gx10/data")
    ap.add_argument("--since", default=None, help="drop rows before this UTC date")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    d = load_export(a.export)
    arc = load_archive(a.archive)
    if arc is not None:
        d = pd.concat([arc, d], ignore_index=True)
    d = d[d["channel"].isin(CHANNELS)]
    if a.since:
        d = d[d["ts"] >= pd.Timestamp(a.since)]
    d = d.drop_duplicates(subset=["ts", "channel"], keep="last").sort_values(["ts", "channel"])
    d["channel"] = d["channel"].astype("category")
    out = os.path.join(a.out, "egauge_gx10.parquet")
    d.reset_index(drop=True).to_parquet(out, index=False)
    per = d.groupby("channel", observed=True).size()
    print(f"wrote {out}: {len(d):,} rows, {d.ts.nunique():,} timestamps, "
          f"{len(per)} channels, {d.ts.min()} -> {d.ts.max()}")

    sol_parts = []
    sf = os.path.join(a.export, "solar.csv.gz")
    if os.path.exists(sf):
        s = pd.read_csv(sf)
        s["ts"] = pd.to_datetime(s["ts"])
        sol_parts.append(s.set_index("ts")[SOLAR_COLS])
    if a.solar_archive and os.path.exists(a.solar_archive):
        sa = pd.read_parquet(a.solar_archive)
        sa.index = pd.to_datetime(sa.index)
        sol_parts.insert(0, sa[[c for c in SOLAR_COLS if c in sa.columns]])
    if sol_parts:
        s = pd.concat(sol_parts)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s = s.apply(pd.to_numeric, errors="coerce")
        s.index.name = "ts"
        sout = os.path.join(a.out, "solar_gx10.parquet")
        s.to_parquet(sout)
        print(f"wrote {sout}: {len(s):,} rows, {s.index.min()} -> {s.index.max()}")
    else:
        print("no solar data found; pv_power/pv_valid will be 0 for every row")


if __name__ == "__main__":
    main()
