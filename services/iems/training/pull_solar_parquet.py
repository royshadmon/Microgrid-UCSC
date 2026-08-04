#!/usr/bin/env python3
"""Pull Solar Assistant history from AnyLog into a parquet for model training.

Reads solar_data via AnyLog (native, same raw-socket path as inference) and
writes analysis/solar/solar_history.parquet indexed by timestamp with the
measured PV / battery / grid / load channels. Join this against the eGauge
consolidated parquet (on ts, forward-filled) to add solar features to the NILM
models once enough solar history has accumulated.

Usage:
    ANYLOG_HOST=100.119.235.24 python services/iems/training/pull_solar_parquet.py --hours 720
"""
import argparse, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

sys.path.insert(0, "services")
from iems.load.anylog_query import anylog_query

SOLAR_COLS = ["pv_power", "battery_power", "battery_soc", "grid_power", "load_power"]

def pull(hours: int) -> pd.DataFrame:
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    rows = anylog_query(
        f"SELECT ts, {', '.join(SOLAR_COLS)} FROM solar_data "
        f"WHERE ts > '{start}' ORDER BY ts ASC",
        table="solar_data",
    )
    if not rows:
        return pd.DataFrame(columns=["ts"] + SOLAR_COLS)
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    for c in SOLAR_COLS:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    return df.dropna(subset=["ts"]).set_index("ts").sort_index()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=720)
    ap.add_argument("--out", default="analysis/solar/solar_history.parquet")
    a = ap.parse_args()
    df = pull(a.hours)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    span = f"{df.index.min()} .. {df.index.max()}" if len(df) else "empty"
    print(f"wrote {len(df):,} rows -> {out}  span={span}")
    if len(df):
        hrs = (df.index.max() - df.index.min()).total_seconds() / 3600.0
        print(f"solar history: {hrs:.1f}h  (NILM feature retrain wants >= ~336h / 2 weeks)")

if __name__ == "__main__":
    main()
