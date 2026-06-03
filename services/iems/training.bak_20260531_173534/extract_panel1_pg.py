#!/usr/bin/env python3
"""Extract Panel 1 training data directly from Postgres, combining
`egauge_kafka` and `energy_readings` partitions (same underlying eGauge stream,
deduplicated by (ts, nm)).

This gets every row the operator node holds without going through the AnyLog
REST parser. Net gain over the AnyLog-only extractor: roughly 13 extra hours
of May 5 (energy_readings has rows kafka missed that day) plus minor gains
elsewhere. Earliest usable Panel-1 timestamp is 2026-04-21 — no deeper
history exists in the operator.

Writes:
  data/panel1_60d.parquet            (same columns as before)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import requests

PG = dict(host="127.0.0.1", port=5432, user="demo",
          password="passwd", dbname="customers")

HOUSE_LAT = 37.2358
HOUSE_LON = -121.9624

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "data/panel1_60d.parquet"

POWER_CHANNELS = [
    "Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)",
    "Shop", "Current on Utility Tie",
]
COL = {
    "Panel1 (HVAC)":          "panel1_w",
    "Panel2 (H2O)":           "panel2_w",
    "Panel3 (Kitchen)":       "panel3_w",
    "Shop":                   "shop_w",
    "Current on Utility Tie": "utility_tie_current",
}

# All partitions that hold Panel 1 power rows (verified 2026-05-12).
POWER_PARTITIONS = [
    "par_egauge_kafka_2026_04_01_d14_insert_timestamp",
    "par_egauge_kafka_2026_04_02_d14_insert_timestamp",
    "par_egauge_kafka_2026_05_00_d14_insert_timestamp",
    "par_energy_readings_2026_04_01_d14_insert_timestamp",
    "par_energy_readings_2026_04_02_d14_insert_timestamp",
    "par_energy_readings_2026_05_00_d14_insert_timestamp",
]
NILM_PARTITIONS = [
    "par_nilm_disaggregated_2026_05_00_d14_insert_timestamp",
]


def fetch_power(con) -> pd.DataFrame:
    """One big UNION across all six partitions, filtered to our channels,
    deduped by (ts, nm). All happens inside Postgres."""
    chans = ", ".join(f"'{c}'" for c in POWER_CHANNELS)
    union = " UNION ALL ".join(
        f"SELECT ts, nm, w FROM {p} WHERE nm IN ({chans})"
        for p in POWER_PARTITIONS
    )
    q = f"""
        SELECT ts, nm, AVG(w::double precision) AS w
        FROM ({union}) u
        GROUP BY ts, nm
    """
    t0 = time.perf_counter()
    df = pd.read_sql(q, con)
    print(f"[extract-pg] power union: {len(df)} unique (ts, nm) rows  "
          f"in {time.perf_counter() - t0:.1f}s")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.dropna(subset=["w"])
    df = df.sort_values("ts")
    return df


def fetch_labels(con) -> pd.DataFrame:
    frames = []
    for p in NILM_PARTITIONS:
        q = (f"SELECT ts, appliance, state, confidence, avg_w "
             f"FROM {p} WHERE circuit = 'Panel1 (HVAC)' ORDER BY ts ASC")
        df = pd.read_sql(q, con)
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df["state01"] = (df["state"].astype(str).str.upper() == "ON").astype(int)
            df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
            df["avg_w"] = pd.to_numeric(df["avg_w"], errors="coerce")
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    pivots = {}
    for appl, g in df.groupby("appliance"):
        g = g[["ts", "state01", "confidence", "avg_w"]].set_index("ts").sort_index()
        g = g.rename(columns={
            "state01":    f"{appl}_llm_state",
            "confidence": f"{appl}_llm_conf",
            "avg_w":      f"{appl}_llm_avg_w",
        })
        g = g[~g.index.duplicated(keep="last")]
        pivots[appl] = g
    return pd.concat(pivots.values(), axis=1) if pivots else pd.DataFrame()


def fetch_weather(start: datetime, end: datetime) -> pd.DataFrame:
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": HOUSE_LAT, "longitude": HOUSE_LON,
        "start_date": start.date().isoformat(),
        "end_date":   end.date().isoformat(),
        "hourly":     "temperature_2m,shortwave_radiation",
        "timezone":   "UTC",
        "temperature_unit": "fahrenheit",
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    h = r.json()["hourly"]
    return pd.DataFrame({
        "ts": pd.to_datetime(h["time"], utc=True),
        "outside_temp": h["temperature_2m"],
        "irradiance":   h["shortwave_radiation"],
    }).set_index("ts").sort_index()


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = psycopg2.connect(**PG)
    try:
        raw = fetch_power(con)
        print(f"[extract-pg] channels: {sorted(raw['nm'].unique())}")
        print(f"[extract-pg] date range: {raw['ts'].min()} -> {raw['ts'].max()}")
        wide = raw.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean")
        wide = wide.rename(columns=COL).sort_index()
        grid = wide.resample("10s").mean()
        print(f"[extract-pg] 10s grid shape: {grid.shape}")

        weather = fetch_weather(grid.index.min().to_pydatetime(),
                                grid.index.max().to_pydatetime())
        weather_grid = weather.reindex(grid.index).interpolate(method="time").ffill().bfill()

        labels = fetch_labels(con)
        if not labels.empty:
            labels = labels.sort_index()
            labels = labels[~labels.index.duplicated(keep="last")]
            labels_grid = pd.merge_asof(
                pd.DataFrame(index=grid.index).sort_index().reset_index(),
                labels.reset_index().sort_values("ts"),
                on="ts", direction="nearest",
                tolerance=pd.Timedelta("30s"),
            ).set_index("ts")
        else:
            labels_grid = pd.DataFrame(index=grid.index)

        local = grid.index.tz_convert("America/Los_Angeles")
        hr = local.hour + local.minute / 60.0 + local.second / 3600.0
        dow = local.dayofweek
        timefeat = pd.DataFrame({
            "hour_sin": np.sin(2 * np.pi * hr / 24.0),
            "hour_cos": np.cos(2 * np.pi * hr / 24.0),
            "dow_sin":  np.sin(2 * np.pi * dow / 7.0),
            "dow_cos":  np.cos(2 * np.pi * dow / 7.0),
        }, index=grid.index)

        out = pd.concat([grid, weather_grid, labels_grid, timefeat], axis=1)

        for c in ("panel1_w", "panel2_w", "panel3_w"):
            if c in out.columns:
                out[c] = out[c].abs()

        if "panel1_w" in out.columns:
            baseline = out["panel1_w"].rolling("30min", min_periods=30).min()
            out["panel1_w_step"] = (out["panel1_w"] - baseline).clip(lower=0)

        fill_cols = list(COL.values()) + ["panel1_w_step"]
        for c in [c for c in fill_cols if c in out.columns]:
            out[c] = out[c].bfill(limit=1).ffill(limit=18)

        out.index.name = "ts"
        out = out.sort_index()
        out.to_parquet(OUT)
        print(f"[extract-pg] wrote {OUT}  rows={len(out)}  cols={list(out.columns)}")

        feature_cols = [c for c in [
            "panel1_w", "panel2_w", "panel3_w", "shop_w",
            "utility_tie_current", "outside_temp", "irradiance"
        ] if c in out.columns]
        print("\n[extract-pg] describe():")
        print(out[feature_cols].describe(percentiles=[0.1, 0.5, 0.9]).round(2))
        print("\n[extract-pg] non-null rates (key columns):")
        for c in feature_cols + ["panel1_w_step"]:
            if c in out.columns:
                print(f"  {c:<22} {out[c].notna().mean():.3f}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
