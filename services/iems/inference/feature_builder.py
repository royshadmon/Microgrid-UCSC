"""
Build the per-panel feature window expected by the trained NILM ONNX models.

Feature order (must match training; see services/iems/models/panel{N}_norm.json):
    panel1_w, panel2_w, panel3_w, shop_w,
    outside_temp, irradiance,
    hour_sin, hour_cos, dow_sin, dow_cos,
    utility_tie_current,
    panel{N}_w_step

The training pipeline ran on 6-second resampled grids (window=100, mid=50).
"""
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np

from iems.load.anylog_query import _parse_ts

logger = logging.getLogger(__name__)

PANEL_CHANNELS = ("Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)", "Shop")
UTIL_CHANNEL = "Current on Utility Tie"

# House timezone. Training derives hour_sin/cos, dow_sin/cos and battery_window
# in LOCAL time (extract/window builders use America/Los_Angeles), so inference
# must too — using UTC here would shift the diurnal features by 7-8 hours.
HOUSE_TZ = ZoneInfo("America/Los_Angeles")
BATTERY_WINDOW = (16, 21)  # battery charges 16:00-21:00 local at the Mantey site


def _resample_uniform(rows, window, step_s=6, end=None):
    """
    Return (timestamps, values) of length `window`, sampled every `step_s`
    seconds, ending at `end` (default = newest available row).

    Forward-fills gaps. Zero-fills entirely-missing channels.
    """
    if not rows:
        end = end or datetime.now(timezone.utc)
        ts_grid = [end - timedelta(seconds=step_s * (window - 1 - i))
                   for i in range(window)]
        return ts_grid, [0.0] * window

    pairs = []
    for r in rows:
        try:
            t = _parse_ts(str(r["ts"]))
            v = float(r.get("w", 0) or 0)
            pairs.append((t, v))
        except (ValueError, KeyError, TypeError):
            continue
    if not pairs:
        return _resample_uniform([], window, step_s, end)

    pairs.sort(key=lambda x: x[0])
    end = end or pairs[-1][0]
    ts_grid = [end - timedelta(seconds=step_s * (window - 1 - i))
               for i in range(window)]

    out = []
    j = 0
    last_v = pairs[0][1]
    for tg in ts_grid:
        while j < len(pairs) and pairs[j][0] <= tg:
            last_v = pairs[j][1]
            j += 1
        out.append(last_v)
    return ts_grid, out


def build_panel_window(panel, panel_rows, weather, norm, end_ts=None):
    """
    Build a (1, window, n_features) float32 tensor for ONNX inference.

    Returns (tensor, midpoint_ts, window_start_ts, window_end_ts).
    """
    features = norm["features"]
    window = int(norm["window"])
    mid = int(norm.get("mid", window // 2))
    mean = np.asarray(norm["mean"], dtype=np.float32)
    std = np.asarray(norm["std"], dtype=np.float32)
    std = np.where(std < 1e-6, 1.0, std)

    # Anchor all channels to a single end timestamp so the per-feature grids
    # align across panels. Pick the newest sample available across the four
    # power channels; fall back to now().
    if end_ts is None:
        latest_seen = None
        for ch in PANEL_CHANNELS:
            for r in panel_rows.get(ch, []) or []:
                try:
                    t = _parse_ts(str(r["ts"]))
                    if latest_seen is None or t > latest_seen:
                        latest_seen = t
                except (ValueError, KeyError, TypeError):
                    continue
        end_ts = latest_seen or datetime.now(timezone.utc)

    panel_w = {}
    ts_ref = []
    for ch in PANEL_CHANNELS:
        ts_grid, vals = _resample_uniform(panel_rows.get(ch, []), window,
                                          step_s=6, end=end_ts)
        if not ts_ref:
            ts_ref = ts_grid
        panel_w[ch] = vals

    _, util_vals = _resample_uniform(panel_rows.get(UTIL_CHANNEL, []),
                                     window, step_s=6, end=end_ts)

    temp = float(weather.get("outside_temp_f", 65.0) or 65.0)
    irr = float(weather.get("irradiance_6h_avg",
                            weather.get("irradiance_now", 0)) or 0)

    step_key = {
        "Panel1 (HVAC)":    "panel1_w_step",
        "Panel2 (H2O)":     "panel2_w_step",
        "Panel3 (Kitchen)": "panel3_w_step",
        "Shop":             "shop_w_step",
    }[panel]
    src_key = step_key.replace("_step", "")
    src_channel = {
        "panel1_w": "Panel1 (HVAC)",
        "panel2_w": "Panel2 (H2O)",
        "panel3_w": "Panel3 (Kitchen)",
        "shop_w":   "Shop",
    }[src_key]

    n_feat = len(features)
    win = np.zeros((window, n_feat), dtype=np.float32)
    for i, t in enumerate(ts_ref):
        # Diurnal features in house-local time (match training).
        tl = t.astimezone(HOUSE_TZ)
        hour = tl.hour + tl.minute / 60.0
        dow = tl.weekday()
        battery_window = 1.0 if BATTERY_WINDOW[0] <= tl.hour < BATTERY_WINDOW[1] else 0.0
        feat_vals = {
            "panel1_w":            panel_w["Panel1 (HVAC)"][i],
            "panel2_w":            panel_w["Panel2 (H2O)"][i],
            "panel3_w":            panel_w["Panel3 (Kitchen)"][i],
            "shop_w":              panel_w["Shop"][i],
            "outside_temp":        temp,
            "irradiance":          irr,
            "hour_sin":            math.sin(2 * math.pi * hour / 24),
            "hour_cos":            math.cos(2 * math.pi * hour / 24),
            "dow_sin":             math.sin(2 * math.pi * dow / 7),
            "dow_cos":             math.cos(2 * math.pi * dow / 7),
            "utility_tie_current": util_vals[i],
            "battery_window":      battery_window,
        }
        if i == 0:
            feat_vals[step_key] = 0.0
        else:
            prev = panel_w[src_channel][i - 1]
            feat_vals[step_key] = feat_vals[src_key] - prev

        for k, name in enumerate(features):
            win[i, k] = feat_vals.get(name, 0.0)

    win = (win - mean) / std
    tensor = win.reshape(1, window, n_feat).astype(np.float32)
    mid_ts = ts_ref[mid] if mid < len(ts_ref) else ts_ref[-1]
    start_ts = ts_ref[0]
    end_ts_out = ts_ref[-1]
    return tensor, mid_ts, start_ts, end_ts_out
