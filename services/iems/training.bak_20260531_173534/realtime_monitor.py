#!/usr/bin/env python3
"""Real-time observation harness for the Panel 1 NILM model.

Polls AnyLog for the last ~35 minutes of Panel 1 data every PANEL1_TICK_S
seconds, builds a 100-step normalized feature window, runs the quantized
ONNX model, and logs every prediction with a timestamp. State transitions
per appliance are tracked, and a session summary is printed every
PANEL1_SUMMARY_EVERY ticks plus on SIGINT/SIGTERM.

Strictly read-only against AnyLog. Does not import from services/iems/load/
and does not write to nilm_disaggregated.
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
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort
import requests

# ── config ─────────────────────────────────────────────────────────────
ANYLOG = os.environ.get("ANYLOG_REST_URL", "http://127.0.0.1:32149")
TICK_S = int(os.environ.get("PANEL1_TICK_S", 10))
SUMMARY_EVERY = int(os.environ.get("PANEL1_SUMMARY_EVERY", 60))
WIN = 100                       # match training
LOOKBACK_MIN = 40                # fetch window: 30 min baseline + 10 min slop
HOUSE_LAT = 37.2358
HOUSE_LON = -121.9624

REPO = Path(__file__).resolve().parents[3]
MODEL_DIR = REPO / "services/iems/models"
REPORT_DIR = REPO / "services/iems/training/reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
EVENT_LOG = REPORT_DIR / f"realtime_panel1_{stamp}.jsonl"
SUMMARY_MD = REPORT_DIR / f"realtime_panel1_{stamp}_summary.md"

POWER_CHANNELS = {
    "Panel1 (HVAC)": "panel1_w",
    "Panel2 (H2O)":  "panel2_w",
    "Panel3 (Kitchen)": "panel3_w",
    "Shop": "shop_w",
    "Current on Utility Tie": "utility_tie_current",
}

# ── model + norm ───────────────────────────────────────────────────────
sess = ort.InferenceSession(
    str(MODEL_DIR / "nilm_panel1_int8.onnx"),
    providers=["CPUExecutionProvider"],
)
norm = json.loads((MODEL_DIR / "panel1_norm.json").read_text())
FEATURES = norm["features"]
F = len(FEATURES)
mean = np.array(norm["mean"], dtype=np.float32)
std = np.array(norm["std"], dtype=np.float32)
THRESHOLDS = norm.get("thresholds", {"heat_pump": 0.5, "solar_pump": 0.5})
THR_HP = float(THRESHOLDS["heat_pump"])
THR_SP = float(THRESHOLDS["solar_pump"])
buf = np.empty((1, WIN, F), dtype=np.float32)

# ── state ──────────────────────────────────────────────────────────────
prev = {"heat_pump": None, "solar_pump": None}
counters = {
    "heat_pump":  {"on": 0, "off": 0, "off_to_on": 0, "on_to_off": 0},
    "solar_pump": {"on": 0, "off": 0, "off_to_on": 0, "on_to_off": 0},
}
on_to_on_by_hour: dict[str, dict[int, int]] = {
    "heat_pump":  {},
    "solar_pump": {},
}
latencies: deque[float] = deque(maxlen=10_000)
session_start = time.time()
session_start_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
ticks = 0
errors = 0

_ALIAS = re.compile(r"^(.*?)\s+AS\s+(\w+)\s*$", re.IGNORECASE)


# ── helpers ────────────────────────────────────────────────────────────
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


# Weather cache
_weather_cache = {"ts": 0.0, "outside_temp": float("nan"), "irradiance": float("nan")}
WEATHER_REFRESH_S = 300


def fetch_weather_now() -> tuple[float, float]:
    """Return (outside_temp_F, irradiance_Wpm2). Cached for 5 minutes."""
    now = time.time()
    if now - _weather_cache["ts"] < WEATHER_REFRESH_S and not np.isnan(_weather_cache["outside_temp"]):
        return _weather_cache["outside_temp"], _weather_cache["irradiance"]
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": HOUSE_LAT,
                "longitude": HOUSE_LON,
                "current": "temperature_2m,shortwave_radiation",
                "temperature_unit": "fahrenheit",
                "timezone": "UTC",
            },
            timeout=20,
        )
        r.raise_for_status()
        js = r.json()
        c = js.get("current", {})
        t = float(c.get("temperature_2m", float("nan")))
        i = float(c.get("shortwave_radiation", float("nan")))
        if not np.isnan(t):
            _weather_cache["outside_temp"] = t
            _weather_cache["irradiance"] = i if not np.isnan(i) else 0.0
            _weather_cache["ts"] = now
    except Exception as e:
        print(f"[monitor] weather fetch failed: {e}", file=sys.stderr, flush=True)
    return _weather_cache["outside_temp"], _weather_cache["irradiance"]


def fetch_window() -> np.ndarray:
    """Return a (100, F) feature array for the most recent 10-second buckets."""
    # 1. Pull the last LOOKBACK_MIN minutes of all-channel data
    part = current_partition()
    now_utc = datetime.now(timezone.utc)
    start_str = (now_utc - __import__("datetime").timedelta(minutes=LOOKBACK_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    q = (
        f"SELECT ts, nm, w FROM {part} "
        f"WHERE ts >= '{start_str}' ORDER BY ts ASC"
    )
    rows = sql(q, timeout=20)
    if not rows:
        raise RuntimeError(f"no rows in {part} since {start_str}")
    import pandas as pd
    df = pd.DataFrame(rows)
    df = df[df["nm"].isin(POWER_CHANNELS)]
    if df.empty:
        raise RuntimeError("no matching channels in fetched rows")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["w"] = pd.to_numeric(df["w"], errors="coerce")
    df = df.drop_duplicates(["ts", "nm"]).sort_values("ts")
    wide = df.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean")
    # Rename to our internal names
    wide = wide.rename(columns=POWER_CHANNELS)
    # Resample to 10s grid
    wide = wide.sort_index().resample("10s").mean()

    # Sign normalization
    for c in ("panel1_w", "panel2_w", "panel3_w"):
        if c in wide.columns:
            wide[c] = wide[c].abs()

    # panel1_w_step
    if "panel1_w" in wide.columns:
        baseline = wide["panel1_w"].rolling("30min", min_periods=30).min()
        wide["panel1_w_step"] = (wide["panel1_w"] - baseline).clip(lower=0)

    # Forward-fill brief outages
    for c in list(POWER_CHANNELS.values()) + ["panel1_w_step"]:
        if c in wide.columns:
            wide[c] = wide[c].bfill(limit=1).ffill(limit=18)

    # Weather
    temp, irr = fetch_weather_now()
    wide["outside_temp"] = temp
    wide["irradiance"] = irr

    # Time encodings (local time)
    local = wide.index.tz_convert("America/Los_Angeles")
    hr = local.hour + local.minute / 60.0 + local.second / 3600.0
    dow = local.dayofweek
    wide["hour_sin"] = np.sin(2 * np.pi * hr / 24.0)
    wide["hour_cos"] = np.cos(2 * np.pi * hr / 24.0)
    wide["dow_sin"]  = np.sin(2 * np.pi * dow / 7.0)
    wide["dow_cos"]  = np.cos(2 * np.pi * dow / 7.0)

    # Select features in the exact order the model was trained on
    missing = [c for c in FEATURES if c not in wide.columns]
    if missing:
        raise RuntimeError(f"missing features in fetch: {missing}")
    feats_df = wide[FEATURES].dropna()
    if len(feats_df) < WIN:
        raise RuntimeError(f"only {len(feats_df)} contiguous 10s buckets available (need {WIN})")
    feats = feats_df.tail(WIN).values.astype(np.float32)
    if feats.shape != (WIN, F):
        raise RuntimeError(f"window shape {feats.shape} != ({WIN}, {F})")
    return feats


def transition(name: str, new_state: int) -> str | None:
    old = prev[name]
    prev[name] = new_state
    if old is None or old == new_state:
        return None
    evt = "off_to_on" if new_state == 1 else "on_to_off"
    counters[name][evt] += 1
    if evt == "off_to_on":
        local_hr = datetime.now().astimezone().hour
        bucket = on_to_on_by_hour[name]
        bucket[local_hr] = bucket.get(local_hr, 0) + 1
    return evt


def tick() -> None:
    global ticks, errors
    t_fetch_start = time.perf_counter()
    feats = fetch_window()
    t_inf_start = time.perf_counter()
    buf[0] = (feats - mean) / std
    p_hp, p_sp = sess.run(None, {"window": buf})
    t_end = time.perf_counter()
    inference_ms = (t_end - t_inf_start) * 1000.0
    fetch_ms = (t_inf_start - t_fetch_start) * 1000.0
    tick_ms = (t_end - t_fetch_start) * 1000.0
    # Track inference latency only (the spec's 2ms bar is for the model run).
    latencies.append(inference_ms)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    hp_prob = float(p_hp.reshape(-1)[0])
    sp_prob = float(p_sp.reshape(-1)[0])
    s_hp = int(hp_prob > THR_HP)
    s_sp = int(sp_prob > THR_SP)

    t_hp = transition("heat_pump", s_hp)
    t_sp = transition("solar_pump", s_sp)
    counters["heat_pump"]["on"  if s_hp else "off"] += 1
    counters["solar_pump"]["on" if s_sp else "off"] += 1

    event = {
        "ts": now,
        "heat_pump":  {"state": s_hp, "prob": hp_prob, "transition": t_hp},
        "solar_pump": {"state": s_sp, "prob": sp_prob, "transition": t_sp},
        "panel1_w":      float(feats[-1, FEATURES.index("panel1_w")]),
        "outside_temp":  float(feats[-1, FEATURES.index("outside_temp")]),
        "irradiance":    float(feats[-1, FEATURES.index("irradiance")]),
        "panel1_w_step": float(feats[-1, FEATURES.index("panel1_w_step")]),
        "inference_ms":  round(inference_ms, 3),
        "fetch_ms":      round(fetch_ms, 1),
        "tick_ms":       round(tick_ms, 1),
    }
    with EVENT_LOG.open("a") as f:
        f.write(json.dumps(event) + "\n")

    print(
        f"{now}  "
        f"hp={s_hp}({hp_prob:.2f}){' ' + t_hp if t_hp else ''}  "
        f"sp={s_sp}({sp_prob:.2f}){' ' + t_sp if t_sp else ''}  "
        f"p1={event['panel1_w']:6.0f}W  step={event['panel1_w_step']:5.0f}W  "
        f"temp={event['outside_temp']:.1f}F  irr={event['irradiance']:.0f}  "
        f"inf={inference_ms:.2f}ms  tick={tick_ms:.0f}ms",
        flush=True,
    )
    ticks += 1


def render_summary() -> str:
    lat = np.array(latencies) if latencies else np.array([0.0])
    elapsed_min = (time.time() - session_start) / 60.0
    end_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append(f"=== Panel 1 RNN session summary @ {end_iso}"
                 f" ({ticks} ticks · {elapsed_min:.1f} min) ===")
    for name in ("heat_pump", "solar_pump"):
        c = counters[name]
        total = c["on"] + c["off"]
        on_pct = 100.0 * c["on"] / total if total else 0.0
        off_pct = 100.0 - on_pct
        label = name.replace("_", " ").title() + ":"
        lines.append(
            f"{label:14}ON {c['on']:4} ticks ({on_pct:.1f}%)   "
            f"OFF {c['off']:4} ticks ({off_pct:.1f}%)"
        )
        lines.append(
            f"              {c['off_to_on']} off→on transitions   "
            f"{c['on_to_off']} on→off transitions"
        )
    lines.append(
        f"Inference:    avg {lat.mean():.2f} ms  "
        f"p50 {np.percentile(lat, 50):.2f}  "
        f"p99 {np.percentile(lat, 99):.2f}  (model only)"
    )
    if EVENT_LOG.exists():
        lines.append(f"Event log:    {EVENT_LOG}")
    lines.append(f"Errors:       {errors}")
    lines.append(
        f"Decision thresholds: HP={THR_HP:.2f}  SP={THR_SP:.2f}"
    )
    return "\n".join(lines)


def shutdown(signum, frame) -> None:
    body = render_summary()
    print("\n" + body + "\n", flush=True)
    md: list[str] = []
    md.append("# Panel 1 real-time monitor — session summary")
    md.append("")
    md.append(f"- Session start: `{session_start_iso}`")
    md.append(f"- Session end:   `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`")
    md.append(f"- Total ticks:   {ticks}")
    md.append(f"- Tick interval: {TICK_S} s")
    md.append(f"- Errors:        {errors}")
    md.append("")
    md.append("```")
    md.append(body)
    md.append("```")
    md.append("")
    md.append("## Off→on transitions by local hour")
    md.append("")
    md.append("| hour (PT) | heat pump | solar pump |")
    md.append("|---:|---:|---:|")
    hours = sorted(set(on_to_on_by_hour["heat_pump"]).union(on_to_on_by_hour["solar_pump"]))
    for h in hours:
        md.append(
            f"| {h:02d} | "
            f"{on_to_on_by_hour['heat_pump'].get(h, 0)} | "
            f"{on_to_on_by_hour['solar_pump'].get(h, 0)} |"
        )
    SUMMARY_MD.write_text("\n".join(md) + "\n")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


def main() -> int:
    print(f"[monitor] event log: {EVENT_LOG}")
    print(f"[monitor] summary on shutdown: {SUMMARY_MD}")
    print(f"[monitor] tick={TICK_S}s · summary every {SUMMARY_EVERY} ticks")
    print(f"[monitor] thresholds: HP={THR_HP:.2f}  SP={THR_SP:.2f}")
    print()
    global ticks, errors
    while True:
        try:
            tick()
        except Exception as e:
            errors += 1
            print(f"[ERROR] tick failed: {e}", file=sys.stderr, flush=True)
        if ticks and ticks % SUMMARY_EVERY == 0:
            print("\n" + render_summary() + "\n", flush=True)
        time.sleep(TICK_S)


if __name__ == "__main__":
    sys.exit(main())
