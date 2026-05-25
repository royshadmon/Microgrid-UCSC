#!/usr/bin/env python3
"""Pull eGauge data using CSV API endpoint (correct format).

Uses: http://egauge/cgi-bin/egauge-show?f=csv&s=...&e=...&i=300
Pulls past 6 months (Dec 2025 - May 2026) at 5-minute intervals.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from io import StringIO

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "data/panel1_historical_6mo.parquet"

# eGauge CGI endpoint (CSV format)
EGAUGE_BASE = "http://egauge18646.egaug.es"
EGAUGE_CGI = f"{EGAUGE_BASE}/cgi-bin/egauge-show"
EGAUGE_USER = "hranjan"
EGAUGE_PASSWORD = "2026MGMrho"

# 6 months: Dec 1, 2025 → May 18, 2026
START_DATE = "2025-12-01T00:00:00"
END_DATE = "2026-05-18T23:59:59"
INTERVAL = 300  # 5 minutes

LAT, LON = 37.2358, -121.9624

print(f"Pulling 6 months from eGauge CSV API")
print(f"  Endpoint: {EGAUGE_CGI}")
print(f"  Period: {START_DATE} → {END_DATE}")
print(f"  Interval: {INTERVAL}s (5 minutes)")
print(f"  Auth: {EGAUGE_USER}")
print()

# Pull data
params = {
    "f": "csv",
    "s": START_DATE,
    "e": END_DATE,
    "i": INTERVAL,
}

print("Fetching CSV data...")
try:
    resp = requests.get(
        EGAUGE_CGI,
        params=params,
        auth=(EGAUGE_USER, EGAUGE_PASSWORD),
        timeout=300  # 5 minutes for large download
    )
    resp.raise_for_status()
    print(f"  ✓ Downloaded {len(resp.content):,} bytes")
except Exception as e:
    sys.exit(f"FATAL: {e}")

# Parse CSV
print("Parsing CSV...")
csv_text = resp.content.decode('utf-8')
df = pd.read_csv(StringIO(csv_text))
print(f"  Raw shape: {df.shape}")
print(f"  Columns: {list(df.columns)}")

# Convert to our schema
# eGauge CSV format: timestamp column + one column per register
# Rename columns to match our pipeline
if 'Date & Time' in df.columns:
    df['time'] = pd.to_datetime(df['Date & Time'], utc=True)
    df = df.drop('Date & Time', axis=1)
elif 'timestamp' in df.columns:
    df['time'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.drop('timestamp', axis=1)

df = df.set_index('time')

# Rename register columns
rename_map = {
    'Panel1 (HVAC)': 'panel1_w',
    'Panel2 (H2O)': 'panel2_w',
    'Panel3 (Kitchen)': 'panel3_w',
    'Shop': 'shop_w',
    'Current on Utility Tie': 'utility_tie_current',
}
df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

# Resample to 10s for compatibility with training pipeline
print("Resampling to 10s grid...")
df = df.resample('10s').interpolate(method='linear')
print(f"  Resampled shape: {df.shape}")

# Add weather
print("Fetching weather data...")
weather_url = "https://archive-api.open-meteo.com/v1/archive"
weather_params = {
    "latitude": LAT,
    "longitude": LON,
    "start_date": "2025-12-01",
    "end_date": "2026-05-18",
    "hourly": "temperature_2m,shortwave_radiation",
    "timezone": "UTC",
}
w = requests.get(weather_url, params=weather_params, timeout=60).json()["hourly"]
weather = pd.DataFrame({
    "time": pd.to_datetime(w["time"], utc=True),
    "outside_temp": w["temperature_2m"],
    "irradiance": w["shortwave_radiation"],
}).set_index("time").resample("10s").ffill()

# Merge
df = df.join(weather, how='left').ffill().bfill()

# Add time features
df["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
df["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
df["dow_sin"] = np.sin(2 * np.pi * df.index.dayofweek / 7)
df["dow_cos"] = np.cos(2 * np.pi * df.index.dayofweek / 7)

# Add panel1_w_step
if "panel1_w" in df.columns:
    baseline = df["panel1_w"].rolling("30min", min_periods=30).min()
    df["panel1_w_step"] = (df["panel1_w"] - baseline).clip(lower=0)

# Save
OUT.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(OUT)

print(f"\n✓ Success!")
print(f"  Wrote: {OUT}")
print(f"  Shape: {df.shape[0]:,} rows × {df.shape[1]} cols")
print(f"  Date range: {df.index.min()} → {df.index.max()}")
print(f"  Duration: {(df.index.max() - df.index.min()).days} days")

# Stats
for col in ["panel1_w", "panel2_w", "panel3_w", "shop_w"]:
    if col in df.columns:
        n = df[col].notna().sum()
        pct = 100 * n / len(df)
        mean = df[col].mean()
        print(f"  {col}: {n:,}/{len(df):,} ({pct:.1f}%) mean={mean:.1f}W")
