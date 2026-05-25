#!/usr/bin/env python3
"""Pull 6 months of eGauge data at 5-minute intervals.

Authenticated access to https://egauge18646.egaug.es
Pulls Dec 1, 2025 → May 18, 2026 at 5-minute (300s) grouping
"""
import sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "data/panel1_historical_6mo.parquet"

# eGauge access (authenticated)
EGAUGE_API = "https://egauge18646.egaug.es/api/register"
EGAUGE_USER = "hranjan"
EGAUGE_PASSWORD = "2026MGMrho"

# 6 months: Dec 1, 2025 → May 18, 2026
START = datetime(2025, 12, 1, tzinfo=timezone.utc)
END = datetime(2026, 5, 18, 23, 59, 59, tzinfo=timezone.utc)
CHUNK_DAYS = 7

LAT, LON = 37.2358, -121.9624


def fetch_chunk(start_ts, end_ts):
    params = {"start": start_ts, "end": end_ts, "group": 300}
    auth = HTTPBasicAuth(EGAUGE_USER, EGAUGE_PASSWORD)
    
    try:
        r = requests.get(EGAUGE_API, params=params, auth=auth, timeout=120)
        r.raise_for_status()
        rows = []
        for reg in r.json().get("registers", []):
            for ts, val in reg.get("data", []):
                rows.append({"ts": ts, "register": reg.get("name"), "value": val})
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["ts", "register", "value"])
    except Exception as e:
        print(f"    ERROR: {e}")
        return pd.DataFrame(columns=["ts", "register", "value"])


print(f"Pulling 6 months from {EGAUGE_API}")
print(f"  Period: {START.date()} → {END.date()}")
print(f"  Interval: 5 minutes (group=300)")
print()

chunks, curr = [], START
while curr < END:
    end_chunk = min(curr + pd.Timedelta(days=CHUNK_DAYS), END)
    print(f"  {curr.date()} → {end_chunk.date()}", end=" ")
    chunk = fetch_chunk(int(curr.timestamp()), int(end_chunk.timestamp()))
    if not chunk.empty:
        chunks.append(chunk)
        print(f"✓ {len(chunk):,}")
    else:
        print("✗")
    curr = end_chunk
    time.sleep(2)

if not chunks:
    sys.exit("FATAL: no data")

raw = pd.concat(chunks, ignore_index=True)
print(f"\nFetched {len(raw):,} total rows")

raw["time"] = pd.to_datetime(raw["ts"], unit="s", utc=True)
wide = raw.pivot_table(index="time", columns="register", values="value")
wide = wide.rename(columns={"Panel1 (HVAC)": "panel1_w", "Panel2 (H2O)": "panel2_w",
                            "Panel3 (Kitchen)": "panel3_w", "Shop": "shop_w"})
wide = wide.resample("10s").interpolate()
print(f"Resampled to 10s: {len(wide):,} rows")

# Weather
print("Fetching weather...")
url = "https://archive-api.open-meteo.com/v1/archive"
w = requests.get(url, params={"latitude": LAT, "longitude": LON,
    "start_date": START.date().isoformat(), "end_date": END.date().isoformat(),
    "hourly": "temperature_2m,shortwave_radiation", "timezone": "UTC"}, timeout=60).json()["hourly"]
weather = pd.DataFrame({"time": pd.to_datetime(w["time"], utc=True),
    "outside_temp": w["temperature_2m"], "irradiance": w["shortwave_radiation"]
}).set_index("time").resample("10s").ffill()

merged = wide.join(weather, how="left").ffill().bfill()
merged["hour_sin"] = np.sin(2*np.pi*merged.index.hour/24)
merged["hour_cos"] = np.cos(2*np.pi*merged.index.hour/24)
merged["dow_sin"] = np.sin(2*np.pi*merged.index.dayofweek/7)
merged["dow_cos"] = np.cos(2*np.pi*merged.index.dayofweek/7)

if "panel1_w" in merged.columns:
    baseline = merged["panel1_w"].rolling("30min", min_periods=30).min()
    merged["panel1_w_step"] = (merged["panel1_w"] - baseline).clip(lower=0)

OUT.parent.mkdir(parents=True, exist_ok=True)
merged.to_parquet(OUT)

print(f"\n✓ Wrote {OUT}")
print(f"  Shape: {merged.shape[0]:,} rows × {merged.shape[1]} cols")
print(f"  Range: {merged.index.min()} → {merged.index.max()}")
for col in ["panel1_w", "panel2_w", "panel3_w", "shop_w"]:
    if col in merged.columns:
        n = merged[col].notna().sum()
        print(f"  {col}: {n:,}/{len(merged)} ({100*n/len(merged):.1f}%)")
