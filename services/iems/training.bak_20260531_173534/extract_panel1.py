#!/usr/bin/env python3
"""Pull Panel 1 training data from AnyLog + Open-Meteo.

Writes ~/microgrid-manager/data/panel1_60d.parquet with:
  - power columns (Panel1, Panel2, Panel3, Shop, Current on Utility Tie)
  - outside_temp, irradiance (Open-Meteo)
  - heat_pump_llm_state, vacuum_cleaner_llm_state (from nilm_disaggregated)
  - hour_sin, hour_cos, dow_sin, dow_cos

Resampled to 10-second grid.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ANYLOG = "http://127.0.0.1:32149"
DBMS = "customers"

HOUSE_LAT = 37.2358
HOUSE_LON = -121.9624

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "data/panel1_60d.parquet"

# Channels to keep
POWER_CHANNELS = [
    "Panel1 (HVAC)",
    "Panel2 (H2O)",
    "Panel3 (Kitchen)",
    "Shop",
    "Current on Utility Tie",
]

# Pretty column names in the parquet
COL = {
    "Panel1 (HVAC)":          "panel1_w",
    "Panel2 (H2O)":           "panel2_w",
    "Panel3 (Kitchen)":       "panel3_w",
    "Shop":                   "shop_w",
    "Current on Utility Tie": "utility_tie_current",
}

# Partitions are probed in order; missing ones are skipped (see fetch_partition_pages).
# Add new partitions to the front of this list as AnyLog rolls them in.
KAFKA_PARTITIONS = [
    "par_egauge_kafka_2026_05_00_d14_insert_timestamp",
    "par_egauge_kafka_2026_05_01_d14_insert_timestamp",
    "par_egauge_kafka_2026_06_00_d14_insert_timestamp",
    "par_egauge_kafka_2026_04_01_d14_insert_timestamp",
    "par_egauge_kafka_2026_04_02_d14_insert_timestamp",
]
NILM_PARTITIONS = [
    "par_nilm_disaggregated_2026_05_00_d14_insert_timestamp",
]

_ALIAS = re.compile(r"^(.*?)\s+AS\s+(\w+)\s*$", re.IGNORECASE)


def _strip_aliases(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        clean = {}
        for k, v in r.items():
            m = _ALIAS.match(k)
            clean[m.group(2) if m else k] = v
        out.append(clean)
    return out


def sql(query: str, timeout: int = 120) -> list[dict]:
    cmd = f"sql {DBMS} format=json and stat=false \"{query}\""
    req = urllib.request.Request(
        ANYLOG, method="GET",
        headers={"User-Agent": "AnyLog/1.23", "command": cmd},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"AnyLog HTTP {e.code}: {body[:400]}") from None
    if isinstance(data, dict) and str(data.get("reply", "")).startswith("Empty data set"):
        return []
    return _strip_aliases(data.get("Query", []))


def fetch_partition_pages(table: str, page: int = 5_000) -> pd.DataFrame:
    """Page through a partition by ts, capturing only the channels we want."""
    frames: list[pd.DataFrame] = []
    last_ts: str | None = None
    total = 0
    print(f"[extract] paging {table} (page={page})")
    while True:
        where = f"ts > '{last_ts}'" if last_ts else "ts > '2000-01-01'"
        q = (
            f"SELECT ts, nm, w FROM {table} "
            f"WHERE {where} ORDER BY ts ASC LIMIT {page}"
        )
        t0 = time.perf_counter()
        try:
            rows = sql(q, timeout=180)
        except RuntimeError as e:
            if "No metadata info" in str(e) or "err_code\": 29" in str(e):
                print(f"  partition {table} not present in current snapshot — skip")
                return pd.DataFrame(columns=["ts", "nm", "w"])
            raise
        if not rows:
            break
        df = pd.DataFrame(rows)
        df = df[df["nm"].isin(POWER_CHANNELS)]
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df["w"] = pd.to_numeric(df["w"], errors="coerce")
            frames.append(df)
        # advance cursor regardless of filter — use last raw ts
        last_ts = rows[-1]["ts"]
        total += len(rows)
        print(f"  page rows={len(rows)} kept={len(df)} last_ts={last_ts}"
              f" elapsed={time.perf_counter() - t0:.1f}s")
        if len(rows) < page:
            break
    if not frames:
        return pd.DataFrame(columns=["ts", "nm", "w"])
    print(f"[extract] {table}: raw pulled={total}, kept={sum(len(f) for f in frames)}")
    return pd.concat(frames, ignore_index=True)


def fetch_power() -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for tbl in KAFKA_PARTITIONS:
        parts.append(fetch_partition_pages(tbl, page=2000))
    raw = pd.concat([p for p in parts if not p.empty], ignore_index=True)
    raw = raw.drop_duplicates(["ts", "nm"]).sort_values("ts")
    print(f"[extract] raw power rows total: {len(raw)}")
    print(f"[extract] channels found: {sorted(raw['nm'].unique())}")
    # Pivot to wide
    wide = raw.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean")
    wide = wide.rename(columns=COL)
    # Resample to 10s mean grid
    wide = wide.sort_index()
    grid = wide.resample("10s").mean()
    return grid


def fetch_labels() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for tbl in NILM_PARTITIONS:
        q = (
            "SELECT ts, appliance, state, confidence, avg_w "
            f"FROM {tbl} WHERE circuit = 'Panel1 (HVAC)' ORDER BY ts ASC"
        )
        rows = sql(q)
        if rows:
            df = pd.DataFrame(rows)
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df["state01"] = (df["state"].astype(str).str.upper() == "ON").astype(int)
            df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
            df["avg_w"] = pd.to_numeric(df["avg_w"], errors="coerce")
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)

    # Pivot per appliance — we only keep states; avg_w stays attached for diagnostics
    pivots: dict[str, pd.DataFrame] = {}
    for appl, g in df.groupby("appliance"):
        g = g[["ts", "state01", "confidence", "avg_w"]].set_index("ts").sort_index()
        # Resample to 10s by nearest-neighbour merge later; here we just dedupe
        g = g.rename(columns={
            "state01":   f"{appl}_llm_state",
            "confidence": f"{appl}_llm_conf",
            "avg_w":      f"{appl}_llm_avg_w",
        })
        # Keep last for duplicate timestamps
        g = g[~g.index.duplicated(keep="last")]
        pivots[appl] = g

    if not pivots:
        return pd.DataFrame()
    wide = pd.concat(pivots.values(), axis=1)
    return wide


def fetch_weather(start: datetime, end: datetime) -> pd.DataFrame:
    """Open-Meteo archive — hourly temperature_2m and shortwave_radiation."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":  HOUSE_LAT,
        "longitude": HOUSE_LON,
        "start_date": start.date().isoformat(),
        "end_date":   end.date().isoformat(),
        "hourly":    "temperature_2m,shortwave_radiation",
        "timezone":  "UTC",
        "temperature_unit": "fahrenheit",
    }
    print(f"[extract] fetching weather {params['start_date']} -> {params['end_date']}")
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    js = r.json()
    h = js["hourly"]
    df = pd.DataFrame({
        "ts": pd.to_datetime(h["time"], utc=True),
        "outside_temp": h["temperature_2m"],
        "irradiance":   h["shortwave_radiation"],
    }).set_index("ts").sort_index()
    return df


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # 1. Power
    power = fetch_power()
    if power.empty:
        print("[extract] FATAL: no power data", file=sys.stderr)
        return 1
    print(f"[extract] power grid shape={power.shape} range={power.index.min()} -> {power.index.max()}")

    # 2. Weather
    weather = fetch_weather(power.index.min().to_pydatetime(),
                            power.index.max().to_pydatetime())
    weather_grid = weather.reindex(power.index, method=None)
    # Hourly weather → 10s grid: interpolate then ffill at edges
    weather_grid = weather_grid.interpolate(method="time").ffill().bfill()

    # 3. LLM labels (kept for diagnostics; rule-only path doesn't depend on them)
    labels = fetch_labels()
    if not labels.empty:
        labels = labels.sort_index()
        labels = labels[~labels.index.duplicated(keep="last")]
        # nearest-neighbour join to 10s grid with 30s tolerance
        labels_grid = pd.merge_asof(
            pd.DataFrame(index=power.index).sort_index().reset_index(),
            labels.reset_index().sort_values("ts"),
            on="ts", direction="nearest",
            tolerance=pd.Timedelta("30s"),
        ).set_index("ts")
    else:
        labels_grid = pd.DataFrame(index=power.index)

    # 4. Time encodings (in the houses' local tz for diurnal sense)
    local = power.index.tz_convert("America/Los_Angeles")
    hr = local.hour + local.minute / 60.0 + local.second / 3600.0
    dow = local.dayofweek
    timefeat = pd.DataFrame({
        "hour_sin": np.sin(2 * np.pi * hr / 24.0),
        "hour_cos": np.cos(2 * np.pi * hr / 24.0),
        "dow_sin":  np.sin(2 * np.pi * dow / 7.0),
        "dow_cos":  np.cos(2 * np.pi * dow / 7.0),
    }, index=power.index)

    # 5. Combine
    out = pd.concat([power, weather_grid, labels_grid, timefeat], axis=1)

    # Sign convention: eGauge sub-panel meters (Panel1/2/3) report consumption
    # as NEGATIVE watts (backfeed direction). Shop and Current on Utility Tie
    # already report consumption as POSITIVE. Normalize sub-panels by taking
    # absolute value so all power columns are non-negative magnitudes.
    for c in ("panel1_w", "panel2_w", "panel3_w"):
        if c in out.columns:
            out[c] = out[c].abs()

    # panel1_w_step is panel1_w minus its 30-min rolling minimum — the same
    # signal the solar-pump rule keys off. Surfacing it as a feature lets the
    # model see directly what the rule sees; without it, the 100-step window
    # (16 minutes) is too short to reproduce the 30-min lookback.
    if "panel1_w" in out.columns:
        baseline = out["panel1_w"].rolling("30min", min_periods=30).min()
        out["panel1_w_step"] = (out["panel1_w"] - baseline).clip(lower=0)

    # Gap-fill: bridge brief Kafka producer outages (commonly 30-120 s).
    # Power signals change slowly enough at the 10-second scale that
    # holding the last value across a 3-minute outage is physically OK;
    # this preserves contiguous runs through transient drops.
    fill_cols = list(COL.values())
    if "panel1_w_step" in out.columns:
        fill_cols.append("panel1_w_step")
    for c in [c for c in fill_cols if c in out.columns]:
        out[c] = out[c].bfill(limit=1).ffill(limit=18)

    out.index.name = "ts"
    out = out.sort_index()
    out.to_parquet(OUT)
    print(f"[extract] wrote {OUT}  rows={len(out)}  cols={list(out.columns)}")
    print(f"[extract] date range: {out.index.min()} -> {out.index.max()}")
    print(f"[extract] non-null rates:\n{out.notna().mean().round(3)}")

    feature_cols = [c for c in [
        "panel1_w", "panel2_w", "panel3_w", "shop_w",
        "utility_tie_current", "outside_temp", "irradiance"
    ] if c in out.columns]
    print("\n[extract] describe() for features:")
    print(out[feature_cols].describe(percentiles=[0.1, 0.5, 0.9]).round(2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
