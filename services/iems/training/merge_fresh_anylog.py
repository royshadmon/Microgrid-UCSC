#!/usr/bin/env python3
"""Extend data/panel1_60d.parquet with fresh AnyLog rows past its current end.

The single raw training file (data/panel1_60d.parquet) is read by all three
label scripts. The current AnyLog kafka partitions only retain ~05-15 onward,
while the parquet starts 04-28, so we MERGE rather than re-extract: keep the
existing processed rows and append everything newer from AnyLog, dedupe on the
10-second timestamp grid, then re-derive weather, time encodings and
panel1_w_step over the full merged span.

AnyLog is the primary source; it has continuous coverage to ~now. eGauge is
only needed if AnyLog has a gap (it does not here).

Reuses extract_panel1.py helpers for the verified AnyLog REST shape and the
exact column/sign conventions.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_panel1 import (  # noqa: E402
    COL, POWER_CHANNELS, OUT, fetch_weather, sql,
)

# Current kafka partitions retained by the operator (probe newest first;
# missing ones are skipped). Update as AnyLog rolls partitions in.
KAFKA_PARTITIONS = [
    "par_egauge_kafka_2026_06_00_d14_insert_timestamp",
    "par_egauge_kafka_2026_05_02_d14_insert_timestamp",
    "par_egauge_kafka_2026_05_01_d14_insert_timestamp",
]


def fetch_power_since(since_ts: pd.Timestamp, page: int = 5000) -> pd.DataFrame:
    """Page every partition for power-channel rows with ts > since_ts."""
    since_str = since_ts.tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S")
    frames: list[pd.DataFrame] = []
    for tbl in KAFKA_PARTITIONS:
        last = since_str
        print(f"[merge] paging {tbl} since {since_str}")
        while True:
            q = (f"SELECT ts, nm, w FROM {tbl} WHERE ts > '{last}' "
                 f"ORDER BY ts ASC LIMIT {page}")
            t0 = time.perf_counter()
            try:
                rows = sql(q, timeout=180)
            except RuntimeError as e:
                if "No metadata" in str(e) or "err_code\": 29" in str(e):
                    print(f"  {tbl} absent — skip")
                    rows = []
                    break
                raise
            if not rows:
                break
            df = pd.DataFrame(rows)
            df = df[df["nm"].isin(POWER_CHANNELS)]
            if not df.empty:
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                df["w"] = pd.to_numeric(df["w"], errors="coerce")
                frames.append(df)
            last = rows[-1]["ts"]
            print(f"  page rows={len(rows)} kept={len(df)} last={last} "
                  f"{time.perf_counter()-t0:.1f}s")
            if len(rows) < page:
                break
    if not frames:
        return pd.DataFrame(columns=["panel1_w"])
    raw = pd.concat(frames, ignore_index=True).drop_duplicates(["ts", "nm"])
    wide = raw.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean")
    wide = wide.rename(columns=COL).sort_index()
    grid = wide.resample("10s").mean()
    # Sign convention: sub-panels report consumption as negative watts.
    for c in ("panel1_w", "panel2_w", "panel3_w"):
        if c in grid.columns:
            grid[c] = grid[c].abs()
    return grid


def main() -> int:
    base = pd.read_parquet(OUT)
    base = base.sort_index()
    base_max = base.index.max()
    print(f"[merge] base {OUT.name}: {len(base)} rows  "
          f"{base.index.min()} -> {base_max}")

    new_power = fetch_power_since(base_max)
    print(f"[merge] fresh power rows: {len(new_power)}  "
          f"({new_power.index.min() if len(new_power) else '-'} -> "
          f"{new_power.index.max() if len(new_power) else '-'})")

    power_cols = [c for c in COL.values()]
    base_power = base[[c for c in power_cols if c in base.columns]]
    merged_power = pd.concat([base_power, new_power[
        [c for c in power_cols if c in new_power.columns]]])
    merged_power = merged_power[~merged_power.index.duplicated(keep="first")]
    merged_power = merged_power.sort_index()
    # Reindex onto a contiguous 10s grid so runs/gaps are well-defined.
    full_idx = pd.date_range(merged_power.index.min(), merged_power.index.max(),
                             freq="10s", tz="UTC")
    merged_power = merged_power.reindex(full_idx)
    merged_power.index.name = "ts"
    print(f"[merge] merged power grid: {len(merged_power)} rows  "
          f"{merged_power.index.min()} -> {merged_power.index.max()}")

    # Weather over the full span.
    weather = fetch_weather(merged_power.index.min().to_pydatetime(),
                            merged_power.index.max().to_pydatetime())
    weather_grid = weather.reindex(merged_power.index, method=None)
    weather_grid = weather_grid.interpolate(method="time").ffill().bfill()

    # Time encodings (house-local for diurnal sense).
    local = merged_power.index.tz_convert("America/Los_Angeles")
    hr = local.hour + local.minute / 60.0 + local.second / 3600.0
    dow = local.dayofweek
    timefeat = pd.DataFrame({
        "hour_sin": np.sin(2 * np.pi * hr / 24.0),
        "hour_cos": np.cos(2 * np.pi * hr / 24.0),
        "dow_sin":  np.sin(2 * np.pi * dow / 7.0),
        "dow_cos":  np.cos(2 * np.pi * dow / 7.0),
    }, index=merged_power.index)

    out = pd.concat([merged_power, weather_grid, timefeat], axis=1)

    # panel1_w_step = panel1_w minus its 30-min rolling minimum.
    if "panel1_w" in out.columns:
        baseline = out["panel1_w"].rolling("30min", min_periods=30).min()
        out["panel1_w_step"] = (out["panel1_w"] - baseline).clip(lower=0)

    # Gap-fill brief outages (<=3 min) as in extract_panel1.
    fill_cols = list(COL.values()) + ["panel1_w_step"]
    for c in [c for c in fill_cols if c in out.columns]:
        out[c] = out[c].bfill(limit=1).ffill(limit=18)

    out.index.name = "ts"
    out = out.sort_index()
    out.to_parquet(OUT)
    print(f"[merge] wrote {OUT}  rows={len(out)}  "
          f"{out.index.min()} -> {out.index.max()}")
    print("[merge] NaN counts per column:")
    print(out.isna().sum())
    return 0


if __name__ == "__main__":
    sys.exit(main())
