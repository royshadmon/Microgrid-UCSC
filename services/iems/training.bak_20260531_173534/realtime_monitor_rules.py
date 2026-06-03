#!/usr/bin/env python3
"""Real-time rule-based disaggregator harness.

Every TICK_S seconds:
  1. Pull the last LOOKBACK_MIN minutes of all-panel power from AnyLog
     (needs >=4h for refrigerator's quantile baseline; >=30 min for
     baseline-step rules on panels 2/3).
  2. Fetch current weather (Open-Meteo, 5-min cache).
  3. Resample to a 10s grid, normalize signs, ffill brief outages.
  4. Run rule_engine.apply_rules across panels 1/2/3.
  5. Emit predictions for the most-recent 10s bucket: per-appliance
     state (0/1) and transition (off_to_on / on_to_off / None).

Strictly read-only against AnyLog. Does not import from
services/iems/load/. Does not write to nilm_disaggregated.

Output:
  reports/realtime_rules_<stamp>.jsonl       — one event per tick
  reports/realtime_rules_<stamp>_summary.md  — written on SIGINT
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rule_engine import (  # noqa: E402
    ALL_APPLIANCES, APPLIANCE_PANEL_MAP, apply_rules,
)

# ── config ─────────────────────────────────────────────────────────────
ANYLOG = os.environ.get("ANYLOG_REST_URL", "http://127.0.0.1:32149")
TICK_S = int(os.environ.get("RULES_TICK_S", 10))
SUMMARY_EVERY = int(os.environ.get("RULES_SUMMARY_EVERY", 60))
LOOKBACK_MIN = int(os.environ.get("RULES_LOOKBACK_MIN", 270))  # 4.5 h
HOUSE_LAT = 37.2358
HOUSE_LON = -121.9624

REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = REPO / "services/iems/training/reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

STAMP = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
EVENT_LOG = REPORT_DIR / f"realtime_rules_{STAMP}.jsonl"
SUMMARY_MD = REPORT_DIR / f"realtime_rules_{STAMP}_summary.md"

POWER_CHANNELS = {
    "Panel1 (HVAC)":          "panel1_w",
    "Panel2 (H2O)":           "panel2_w",
    "Panel3 (Kitchen)":       "panel3_w",
    "Shop":                   "shop_w",
    "Current on Utility Tie": "utility_tie_current",
}

# ── state ──────────────────────────────────────────────────────────────
prev: dict[str, int | None] = {a: None for a in ALL_APPLIANCES}
counters = {
    a: {"on": 0, "off": 0, "nan": 0, "off_to_on": 0, "on_to_off": 0}
    for a in ALL_APPLIANCES
}
transitions_by_hour: dict[str, dict[int, int]] = {a: {} for a in ALL_APPLIANCES}
latencies: deque[float] = deque(maxlen=10_000)
session_start_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
session_start_t = time.time()
ticks = 0
errors = 0

_ALIAS = re.compile(r"^(.*?)\s+AS\s+(\w+)\s*$", re.IGNORECASE)


# ── AnyLog helper (direct local SQL, mirrors realtime_monitor.py) ──────
def sql(query: str, timeout: int = 30) -> list[dict]:
    cmd = f"sql customers format=json and stat=false \"{query}\""
    req = urllib.request.Request(
        ANYLOG, method="GET",
        headers={"User-Agent": "AnyLog/1.23", "command": cmd},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data, dict) and str(data.get("reply", "")).startswith("Empty data set"):
        return []
    rows = data.get("Query", [])
    out = []
    for r in rows:
        clean = {}
        for k, v in r.items():
            m = _ALIAS.match(k)
            clean[m.group(2) if m else k] = v
        out.append(clean)
    return out


def current_partition() -> str:
    ym = datetime.now(timezone.utc).strftime("%Y_%m")
    return f"par_egauge_kafka_{ym}_00_d14_insert_timestamp"


def prior_partition() -> str:
    """Previous month's partition — needed when LOOKBACK crosses month boundary."""
    now = datetime.now(timezone.utc)
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prior = first_of_month - timedelta(days=1)
    return f"par_egauge_kafka_{prior.strftime('%Y_%m')}_00_d14_insert_timestamp"


# ── Weather cache (5 min) ──────────────────────────────────────────────
_weather = {"ts": 0.0, "outside_temp": float("nan"), "irradiance": float("nan")}
WEATHER_REFRESH_S = 300


def fetch_weather_now() -> tuple[float, float]:
    now = time.time()
    if now - _weather["ts"] < WEATHER_REFRESH_S and not np.isnan(_weather["outside_temp"]):
        return _weather["outside_temp"], _weather["irradiance"]
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": HOUSE_LAT, "longitude": HOUSE_LON,
                "current": "temperature_2m,shortwave_radiation",
                "temperature_unit": "fahrenheit", "timezone": "UTC",
            },
            timeout=20,
        )
        r.raise_for_status()
        c = r.json().get("current", {})
        t = float(c.get("temperature_2m", float("nan")))
        i = float(c.get("shortwave_radiation", float("nan")))
        if not np.isnan(t):
            _weather["outside_temp"] = t
            _weather["irradiance"] = i if not np.isnan(i) else 0.0
            _weather["ts"] = now
    except Exception as e:
        print(f"[monitor] weather fetch failed: {e}", file=sys.stderr, flush=True)
    return _weather["outside_temp"], _weather["irradiance"]


# ── DataFrame builder ──────────────────────────────────────────────────
def fetch_window() -> pd.DataFrame:
    """Pull last LOOKBACK_MIN minutes of all panel data, return resampled
    10s-grid DataFrame with the columns rule_engine expects."""
    now_utc = datetime.now(timezone.utc)
    start = now_utc - timedelta(minutes=LOOKBACK_MIN)
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")

    # Query current month partition; if start is in prior month, also query it.
    parts = [current_partition()]
    if start.month != now_utc.month or start.year != now_utc.year:
        parts.append(prior_partition())

    rows: list[dict] = []
    for part in parts:
        q = (
            f"SELECT ts, nm, w FROM {part} "
            f"WHERE ts >= '{start_str}' ORDER BY ts ASC"
        )
        try:
            rows.extend(sql(q, timeout=25))
        except urllib.error.HTTPError as e:
            # Missing partition (e.g. last month had no data) is non-fatal.
            print(f"[monitor] partition {part} HTTP {e.code}", file=sys.stderr)

    if not rows:
        raise RuntimeError(f"no rows since {start_str}")

    df = pd.DataFrame(rows)
    df = df[df["nm"].isin(POWER_CHANNELS)]
    if df.empty:
        raise RuntimeError("no matching channels in fetched rows")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["w"] = pd.to_numeric(df["w"], errors="coerce")
    df = df.drop_duplicates(["ts", "nm"]).sort_values("ts")

    wide = df.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean")
    wide = wide.rename(columns=POWER_CHANNELS)
    wide = wide.sort_index().resample("10s").mean()

    # eGauge sub-panels report consumption as negative; normalize sign.
    for c in ("panel1_w", "panel2_w", "panel3_w"):
        if c in wide.columns:
            wide[c] = wide[c].abs()

    # Bridge brief Kafka producer gaps.
    for c in POWER_CHANNELS.values():
        if c in wide.columns:
            wide[c] = wide[c].bfill(limit=1).ffill(limit=18)

    # panel1_w_step needed by rule_engine.apply_panel1_rules.
    if "panel1_w" in wide.columns:
        baseline = wide["panel1_w"].rolling("30min", min_periods=30).min()
        wide["panel1_w_step"] = (wide["panel1_w"] - baseline).clip(lower=0)

    # Weather: same scalar for the whole window (rule_engine only uses the
    # most-recent row for ON tagging; older rows in the window only feed
    # rolling baselines that don't care about temp/irradiance).
    temp, irr = fetch_weather_now()
    wide["outside_temp"] = temp
    wide["irradiance"] = irr

    return wide


# ── Inference helpers ──────────────────────────────────────────────────
def latest_predictions(labels: pd.DataFrame) -> dict[str, float | None]:
    """Return the most-recent label per appliance ({0, 1, None})."""
    if labels.empty:
        return {a: None for a in ALL_APPLIANCES}
    last = labels.iloc[-1]
    out = {}
    for a in ALL_APPLIANCES:
        v = last.get(a)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out[a] = None
        else:
            out[a] = int(v)
    return out


def latest_powers(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {}
    last = df.iloc[-1]
    return {
        "panel1_w":  float(last.get("panel1_w", float("nan")) or float("nan")),
        "panel2_w":  float(last.get("panel2_w", float("nan")) or float("nan")),
        "panel3_w":  float(last.get("panel3_w", float("nan")) or float("nan")),
        "shop_w":    float(last.get("shop_w", float("nan")) or float("nan")),
    }


# ── Summary block ──────────────────────────────────────────────────────
def summary_block() -> str:
    elapsed = time.time() - session_start_t
    lat = sorted(latencies) if latencies else [0.0]

    def pct(p):
        if not lat:
            return 0.0
        idx = max(0, min(len(lat) - 1, int(round(p * (len(lat) - 1)))))
        return lat[idx]

    lines = [
        f"  session: {ticks} ticks over {elapsed:.0f}s, errors={errors}",
        f"  latency_ms: mean={np.mean(lat):.1f}  p50={pct(0.5):.1f}  "
        f"p90={pct(0.9):.1f}  p99={pct(0.99):.1f}  max={max(lat):.1f}",
        "  appliance        |   on |  off |  nan | off→on | on→off | on%",
        "  -----------------+------+------+------+--------+--------+------",
    ]
    for a in ALL_APPLIANCES:
        c = counters[a]
        denom = c["on"] + c["off"]
        on_pct = (100 * c["on"] / denom) if denom else 0.0
        lines.append(
            f"  {a:<16s} | {c['on']:4d} | {c['off']:4d} | {c['nan']:4d} | "
            f"{c['off_to_on']:6d} | {c['on_to_off']:6d} | {on_pct:5.1f}"
        )
    return "\n".join(lines)


# ── Tick ───────────────────────────────────────────────────────────────
def tick() -> None:
    global ticks, errors
    t0 = time.perf_counter()
    try:
        df = fetch_window()
        labels = apply_rules(df)
        states = latest_predictions(labels)
        powers = latest_powers(df)
        latest_ts = df.index[-1].isoformat() if not df.empty else None
        local_hour = (
            df.index[-1].tz_convert("America/Los_Angeles").hour
            if not df.empty else None
        )
    except Exception as e:
        errors += 1
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"[monitor] tick error after {elapsed:.0f}ms: {e}",
              file=sys.stderr, flush=True)
        return

    latency_ms = (time.perf_counter() - t0) * 1000
    latencies.append(latency_ms)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    event: dict = {
        "ts": now,
        "data_ts": latest_ts,
        "latency_ms": round(latency_ms, 2),
        "panel1_w": powers.get("panel1_w"),
        "panel2_w": powers.get("panel2_w"),
        "panel3_w": powers.get("panel3_w"),
        "shop_w":   powers.get("shop_w"),
        "outside_temp": float(df["outside_temp"].iloc[-1]) if "outside_temp" in df else None,
        "irradiance":   float(df["irradiance"].iloc[-1]) if "irradiance" in df else None,
        "appliances": {},
    }

    for a in ALL_APPLIANCES:
        s = states[a]
        old = prev[a]
        trans = None
        if s is None:
            counters[a]["nan"] += 1
        else:
            if old is not None and old != s:
                trans = "off_to_on" if s == 1 else "on_to_off"
                counters[a][trans] += 1
                if local_hour is not None:
                    transitions_by_hour[a][local_hour] = (
                        transitions_by_hour[a].get(local_hour, 0) + 1
                    )
            counters[a]["on" if s == 1 else "off"] += 1
            prev[a] = s
        event["appliances"][a] = {
            "panel": APPLIANCE_PANEL_MAP[a],
            "state": s,
            "transition": trans,
        }

    with EVENT_LOG.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")

    on_now = [a for a in ALL_APPLIANCES if states[a] == 1]
    on_short = ",".join(a[:4] for a in on_now) or "(none)"
    tr_now = [(a, event["appliances"][a]["transition"])
              for a in ALL_APPLIANCES if event["appliances"][a]["transition"]]
    tr_str = " ".join(f"{a[:4]}:{t.split('_')[0]}→{t.split('_')[-1]}" for a, t in tr_now)
    print(
        f"{now}  ON={on_short:30}  p1={powers.get('panel1_w',0):4.0f} "
        f"p2={powers.get('panel2_w',0):4.0f} p3={powers.get('panel3_w',0):4.0f} "
        f"sh={powers.get('shop_w',0):3.0f}W  {latency_ms:5.0f}ms  {tr_str}",
        flush=True,
    )
    ticks += 1
    if ticks % SUMMARY_EVERY == 0:
        print("\n" + summary_block() + "\n", flush=True)


# ── Lifecycle ──────────────────────────────────────────────────────────
def _shutdown(signum, frame):
    end_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"# Rule-based realtime monitor — session summary",
        "",
        f"- Session start: `{session_start_iso}`",
        f"- Session end:   `{end_iso}`",
        f"- Total ticks:   {ticks}",
        f"- Errors:        {errors}",
        f"- Event log:     `{EVENT_LOG.name}`",
        "",
        "## Per-appliance counters",
        "",
        "| appliance | panel | on | off | nan | off→on | on→off | on% |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for a in ALL_APPLIANCES:
        c = counters[a]
        denom = c["on"] + c["off"]
        pct = (100 * c["on"] / denom) if denom else 0.0
        lines.append(
            f"| `{a}` | {APPLIANCE_PANEL_MAP[a]} | {c['on']} | {c['off']} | "
            f"{c['nan']} | {c['off_to_on']} | {c['on_to_off']} | {pct:.1f} |"
        )
    lines.append("")
    if latencies:
        arr = np.array(latencies)
        lines += [
            "## Latency (ms)",
            "",
            f"- mean: {arr.mean():.1f}",
            f"- p50:  {np.percentile(arr, 50):.1f}",
            f"- p90:  {np.percentile(arr, 90):.1f}",
            f"- p99:  {np.percentile(arr, 99):.1f}",
            f"- max:  {arr.max():.1f}",
            "",
        ]
    lines += [
        "## Transition histograms (off→on counts by local hour)",
        "",
    ]
    for a in ALL_APPLIANCES:
        h = transitions_by_hour[a]
        if not h:
            continue
        lines.append(f"### {a}")
        lines.append("")
        for hour in range(24):
            n = h.get(hour, 0)
            bar = "#" * n
            lines.append(f"`{hour:02d}h` |{bar:<30}| {n}")
        lines.append("")
    SUMMARY_MD.write_text("\n".join(lines) + "\n")
    print(f"\n[monitor] wrote {SUMMARY_MD}", flush=True)
    sys.exit(0)


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def main() -> int:
    print(
        f"[monitor] starting; tick={TICK_S}s lookback={LOOKBACK_MIN}min "
        f"appliances={len(ALL_APPLIANCES)}",
        flush=True,
    )
    print(f"[monitor] event log: {EVENT_LOG}", flush=True)
    while True:
        t0 = time.time()
        tick()
        elapsed = time.time() - t0
        sleep = max(0.0, TICK_S - elapsed)
        time.sleep(sleep)


if __name__ == "__main__":
    sys.exit(main())
