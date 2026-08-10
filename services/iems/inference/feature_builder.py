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
# Extra raw channels required by the physical-model 14-feature set.
PHYSICAL_CHANNELS = ("VrmsA", "VrmsB", "I31", "I32", "F1",
                     "Grid Power", "I11", "I21")
UTIL_CHANNEL = "Current on Utility Tie"

# House timezone. Training derives hour_sin/cos, dow_sin/cos and battery_window
# in LOCAL time (extract/window builders use America/Los_Angeles), so inference
# must too — using UTC here would shift the diurnal features by 7-8 hours.
HOUSE_TZ = ZoneInfo("America/Los_Angeles")
BATTERY_WINDOW = (16, 21)  # battery charges 16:00-21:00 local at the Mantey site




# ── Solar-geometry features (train_rolling.py / solar_features.py parity) ──
# sun_elev and csky_ghi are DETERMINISTIC (NOAA approx + Haurwitz), so they are
# exact at inference with no data source. pv_power/pv_valid come from the live
# Solar Assistant snapshot when one is passed; pv_valid=0 marks it absent,
# matching how the training archive encodes rows with no measured PV.
_SITE_LAT, _SITE_LON = 37.2358, -121.9624

def _sun_elevation_deg(t_utc):
    doy = t_utc.timetuple().tm_yday
    hh = t_utc.hour + t_utc.minute / 60.0 + t_utc.second / 3600.0
    g = 2.0 * math.pi / 365.0 * (doy - 1 + (hh - 12.0) / 24.0)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    tst = hh * 60.0 + eqt + 4.0 * _SITE_LON
    ha = math.radians(tst / 4.0 - 180.0)
    lat = math.radians(_SITE_LAT)
    sin_el = (math.sin(lat) * math.sin(decl)
              + math.cos(lat) * math.cos(decl) * math.cos(ha))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))

def _clear_sky_ghi(elev_deg):
    if elev_deg <= 0:
        return 0.0
    cz = math.sin(math.radians(elev_deg))
    return 1098.0 * cz * math.exp(-0.059 / max(cz, 1e-3))


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


def build_panel_window(panel, panel_rows, weather, norm, end_ts=None, solar=None):
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

    # Raw channels for the physical-model feature set. Training took .abs()
    # of every channel, so mirror that here.
    phys = {}
    for ch in PHYSICAL_CHANNELS:
        _, vals = _resample_uniform(panel_rows.get(ch, []), window,
                                    step_s=6, end=end_ts)
        phys[ch] = [abs(v) for v in vals]

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
        # Physical-model features: raw channel names, abs()-ed, plus
        # tod_sin/tod_cos on the INTEGER local hour (train_all_physical.py
        # uses DatetimeIndex.hour, not hour+minute/60 -- do not "improve" this).
        feat_vals["Panel1 (HVAC)"]    = abs(panel_w["Panel1 (HVAC)"][i])
        feat_vals["Panel2 (H2O)"]     = abs(panel_w["Panel2 (H2O)"][i])
        feat_vals["Panel3 (Kitchen)"] = abs(panel_w["Panel3 (Kitchen)"][i])
        feat_vals["Shop"]             = abs(panel_w["Shop"][i])
        for _ch in PHYSICAL_CHANNELS:
            feat_vals[_ch] = phys[_ch][i]
        feat_vals["tod_sin"] = math.sin(2 * math.pi * tl.hour / 24)
        feat_vals["tod_cos"] = math.cos(2 * math.pi * tl.hour / 24)
        # solar features (18-feature rolling models). Geometry is per-timestep;
        # measured PV is the snapshot value across the window (<=10 min old).
        _el = _sun_elevation_deg(t.astimezone(timezone.utc))
        feat_vals["sun_elev"] = _el
        feat_vals["csky_ghi"] = _clear_sky_ghi(_el)
        _pv = (solar or {}).get("pv_power")
        feat_vals["pv_power"] = float(_pv) if _pv is not None else 0.0
        feat_vals["pv_valid"] = 1.0 if _pv is not None else 0.0
        if i == 0:
            feat_vals[step_key] = 0.0
        else:
            prev = panel_w[src_channel][i - 1]
            feat_vals[step_key] = feat_vals[src_key] - prev

        if i == 0:
            _unknown = [n for n in features if n not in feat_vals]
            if _unknown:
                raise KeyError(
                    "norm config lists features this builder cannot produce: "
                    f"{_unknown}. Refusing to zero-fill -- that yields "
                    "confident-looking but meaningless predictions.")
        for k, name in enumerate(features):
            win[i, k] = feat_vals[name]

    win = (win - mean) / std
    tensor = win.reshape(1, window, n_feat).astype(np.float32)
    mid_ts = ts_ref[mid] if mid < len(ts_ref) else ts_ref[-1]
    start_ts = ts_ref[0]
    end_ts_out = ts_ref[-1]
    return tensor, mid_ts, start_ts, end_ts_out
