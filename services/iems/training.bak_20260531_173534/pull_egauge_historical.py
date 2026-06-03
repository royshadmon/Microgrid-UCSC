#!/usr/bin/env python3
"""Pull historical eGauge data directly from the device web API.

Fetches January 1 → April 30, 2026 in weekly chunks, transforms to the same
schema as panel1_60d.parquet (panel columns + weather), saves for training.

eGauge API endpoint: https://egauge18646.d.egauge.net/cgi-bin/egauge-show
Query params:
  a   = ASCII output
  m   = compact format
  n   = number of rows (or use s/e for time range)
  s   = start timestamp (unix seconds)
  e   = end timestamp (unix seconds)  
  t   = register name (repeat for each channel)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import os
import requests
from requests.auth import HTTPBasicAuth

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "data/panel1_historical.parquet"

# eGauge device + auth (set EGAUGE_USER and EGAUGE_PASSWORD env vars)
EGAUGE_HOST = "https://egauge18646.d.egauge.net"
EGAUGE_USER = os.getenv("EGAUGE_USER", "owner")  # default: owner account
EGAUGE_PASSWORD = os.getenv("EGAUGE_PASSWORD", "")  # REQUIRED
EGAUGE_CGI = f"{EGAUGE_HOST}/cgi-bin/egauge-show"

# Channels to pull (must match eGauge18646 register names exactly)
CHANNELS = [
    "Panel1 (HVAC)",
    "Panel2 (H2O)", 
    "Panel3 (Kitchen)",
    "Shop",
    "Current on Utility Tie",
    "VrmsA",
    "VrmsB",
    "F1",
]

# Weather (Open-Meteo, same as extract_panel1.py)
HOUSE_LAT = 37.2358
HOUSE_LON = -121.9624

# Date range: Jan 1 → Apr 30, 2026
START_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
END_DATE = datetime(2026, 4, 30, 23, 59, 59, tzinfo=timezone.utc)
CHUNK_DAYS = 7


def fetch_egauge_chunk(start_ts: int, end_ts: int) -> pd.DataFrame:
    """Fetch one time chunk from eGauge. Returns DataFrame with columns ts, register, value."""
    params = {
        "a": "",     # ASCII
        "m": "",     # compact
        "s": start_ts,
        "e": end_ts,
    }
    for ch in CHANNELS:
        params[f"t"] = ch  # CGI API uses repeated 't' params; requests handles it
    
    print(f"  fetching eGauge {datetime.fromtimestamp(start_ts, tz=timezone.utc)} -> "
          f"{datetime.fromtimestamp(end_ts, tz=timezone.utc)}")
    
    auth = HTTPBasicAuth(EGAUGE_USER, EGAUGE_PASSWORD) if EGAUGE_PASSWORD else None
    try:
        resp = requests.get(EGAUGE_CGI, params=params, auth=auth, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        print(f"    ERROR: {e}")
        return pd.DataFrame(columns=["ts", "register", "value"])
    
    # Parse the ASCII output. Format is CSV-like:
    # Date & Time,register1,register2,...
    # timestamp,val1,val2,...
    lines = resp.text.strip().split("\n")
    if len(lines) < 2:
        print("    empty response")
        return pd.DataFrame(columns=["ts", "register", "value"])
    
    header = lines[0].split(",")
    # First col is "Date & Time", rest are register names
    registers = [h.strip() for h in header[1:]]
    
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        ts_str = parts[0].strip()
        try:
            # eGauge timestamps are unix seconds
            ts = int(ts_str)
        except ValueError:
            continue
        for i, val_str in enumerate(parts[1:], start=0):
            if i >= len(registers):
                break
            try:
                value = float(val_str.strip())
            except ValueError:
                continue
            rows.append({"ts": ts, "register": registers[i], "value": value})
    
    if not rows:
        print("    no parseable rows")
        return pd.DataFrame(columns=["ts", "register", "value"])
    
    df = pd.DataFrame(rows)
    print(f"    got {len(df)} raw rows")
    return df


def fetch_weather(start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch Open-Meteo weather (same as extract_panel1.py)."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": HOUSE_LAT,
        "longitude": HOUSE_LON,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "hourly": "temperature_2m,shortwave_radiation",
        "timezone": "UTC",
    }
    print(f"[weather] fetching {params['start_date']} -> {params['end_date']}")
    
    try:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[weather] ERROR: {e}")
        return pd.DataFrame(columns=["ts", "outside_temp", "irradiance"])
    
    h = data.get("hourly", {})
    times = h.get("time", [])
    temps = h.get("temperature_2m", [])
    irr = h.get("shortwave_radiation", [])
    
    if not times:
        return pd.DataFrame(columns=["ts", "outside_temp", "irradiance"])
    
    df = pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "outside_temp": temps,
        "irradiance": irr,
    })
    df = df.set_index("time").resample("10s").ffill().reset_index()
    df["ts"] = df["time"].astype("int64") // 10**9
    return df[["ts", "outside_temp", "irradiance"]]


def main() -> int:
    print(f"[pull-historical] Jan 1 → Apr 30, 2026 from eGauge18646")
    print(f"  output: {OUT}")
    
    # Pull eGauge data in weekly chunks
    chunks = []
    current = START_DATE
    while current < END_DATE:
        chunk_end = min(current + pd.Timedelta(days=CHUNK_DAYS), END_DATE)
        start_ts = int(current.timestamp())
        end_ts = int(chunk_end.timestamp())
        
        chunk = fetch_egauge_chunk(start_ts, end_ts)
        if not chunk.empty:
            chunks.append(chunk)
        
        current = chunk_end
        time.sleep(2)  # rate limit
    
    if not chunks:
        print("FATAL: no data fetched")
        return 1
    
    raw = pd.concat(chunks, ignore_index=True)
    print(f"[pull-historical] fetched {len(raw):,} raw rows")
    
    # Pivot to wide
    raw["time"] = pd.to_datetime(raw["ts"], unit="s", utc=True)
    wide = raw.pivot_table(index="time", columns="register", values="value", aggfunc="mean")
    wide = wide.rename(columns={
        "Panel1 (HVAC)": "panel1_w",
        "Panel2 (H2O)": "panel2_w",
        "Panel3 (Kitchen)": "panel3_w",
        "Shop": "shop_w",
        "Current on Utility Tie": "utility_tie_current",
    })
    
    # Resample to 10s grid (match extract_panel1.py)
    wide = wide.resample("10s").mean()
    print(f"[pull-historical] resampled to 10s grid: {len(wide):,} rows")
    
    # Weather
    weather = fetch_weather(START_DATE, END_DATE)
    weather_idx = pd.to_datetime(weather["ts"], unit="s", utc=True)
    weather = weather.set_index(weather_idx)[["outside_temp", "irradiance"]]
    
    # Merge
    merged = wide.join(weather, how="left")
    merged = merged.ffill().bfill()
    
    # Add time features (same as extract_panel1.py)
    merged["hour_sin"] = np.sin(2 * np.pi * merged.index.hour / 24)
    merged["hour_cos"] = np.cos(2 * np.pi * merged.index.hour / 24)
    merged["dow_sin"] = np.sin(2 * np.pi * merged.index.dayofweek / 7)
    merged["dow_cos"] = np.cos(2 * np.pi * merged.index.dayofweek / 7)
    
    # Add panel1_w_step
    if "panel1_w" in merged.columns:
        baseline = merged["panel1_w"].rolling("30min", min_periods=30).min()
        merged["panel1_w_step"] = (merged["panel1_w"] - baseline).clip(lower=0)
    
    print(f"[pull-historical] final shape: {merged.shape}")
    print(f"  date range: {merged.index.min()} -> {merged.index.max()}")
    print(f"  columns: {list(merged.columns)}")
    
    OUT.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(OUT)
    print(f"[pull-historical] wrote {OUT}")
    
    # Stats
    for col in ["panel1_w", "panel2_w", "panel3_w"]:
        if col in merged.columns:
            n = merged[col].notna().sum()
            print(f"  {col}: {n:,}/{len(merged)} ({100*n/len(merged):.1f}%)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
