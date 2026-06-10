"""
Open-Meteo weather for Los Gatos, CA (37.2358, -121.9624).
No API key. Free endpoint. Used by heat-pump and water-heater NILM context.
"""
import json
import logging
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

LAT = float(os.environ.get("HOUSE_LAT", "37.2358"))
LON = float(os.environ.get("HOUSE_LON", "-121.9624"))
TZ  = os.environ.get("HOUSE_TZ", "America/Los_Angeles")

#get weather api
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

#celcius to fahrenheit
def _c_to_f(c: float | None) -> float | None:
    if c is None:
        return None
    return round(c * 9 / 5 + 32, 1)

#solar irradiance level
def _irradiance_label(wm2: float) -> str:
    if wm2 >= 400:
        return "high"
    if wm2 >= 150:
        return "moderate"
    return "low"


def _fetch(params: dict) -> dict:
    url = OPEN_METEO_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ── Public API ────────────────────────────────────────────────────────────────
#get temperature, cloud coverage, wind speed, time, and irradiance
def get_current_weather() -> dict:
    """
    Returns {temp_f, cloud_cover_pct, wind_mph, fetched_at,
             irradiance_now, irradiance_label}
    """
    try:
        data = _fetch({
            "latitude": LAT, "longitude": LON,
            "current": "temperature_2m,cloud_cover,wind_speed_10m,shortwave_radiation",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": TZ,
        })
        c = data.get("current", {})
        irr = float(c.get("shortwave_radiation") or 0)
        return {
            "temp_f":          float(c.get("temperature_2m") or 60),
            "cloud_cover_pct": float(c.get("cloud_cover") or 50),
            "wind_mph":        float(c.get("wind_speed_10m") or 0),
            "irradiance_now":  irr,
            "irradiance_label": _irradiance_label(irr),
            "fetched_at":      datetime.now(timezone.utc).isoformat(),
            "source":          "open-meteo",
            "lat": LAT, "lon": LON, "city": "Los Gatos",
        }
    except Exception as exc:
        logger.warning("get_current_weather failed: %s", exc)
        return _weather_defaults()


def get_irradiance_history(hours: int = 6) -> list[dict]:
    """Returns [{ts, w_per_m2}] for the last N hours (hourly)."""
    try:
        data = _fetch({
            "latitude": LAT, "longitude": LON,
            "hourly": "shortwave_radiation",
            "past_hours": hours,
            "forecast_hours": 1,
            "timezone": TZ,
        })
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        rads  = hourly.get("shortwave_radiation", [])
        return [
            {"ts": t, "w_per_m2": float(r) if r is not None else 0.0}
            for t, r in zip(times[-hours:], rads[-hours:])
        ]
    except Exception as exc:
        logger.warning("get_irradiance_history failed: %s", exc)
        return []


def get_24h_forecast() -> dict:
    """
    Returns {
      hourly: [{ts, temp_f, cloud, irradiance}],   # next 24h
      daily:  {high_f, low_f, avg_irradiance}
    }
    """
    try:
        data = _fetch({
            "latitude": LAT, "longitude": LON,
            "hourly": "temperature_2m,cloud_cover,shortwave_radiation",
            "forecast_hours": 24,
            "temperature_unit": "fahrenheit",
            "timezone": TZ,
        })
        hourly = data.get("hourly", {})
        times  = hourly.get("time", [])
        temps  = hourly.get("temperature_2m", [])
        clouds = hourly.get("cloud_cover", [])
        rads   = hourly.get("shortwave_radiation", [])

        entries = []
        for i, t in enumerate(times[:24]):
            entries.append({
                "ts":         t,
                "temp_f":     float(temps[i])  if i < len(temps)  else 60.0,
                "cloud":      float(clouds[i]) if i < len(clouds) else 50.0,
                "irradiance": float(rads[i])   if i < len(rads)   else 0.0,
            })

        temps_f   = [e["temp_f"]     for e in entries]
        irr_vals  = [e["irradiance"] for e in entries]
        irr_vals_pos = [v for v in irr_vals if v > 0]
        avg_irr  = round(sum(irr_vals_pos) / len(irr_vals_pos), 1) if irr_vals_pos else 0.0

        return {
            "hourly": entries,
            "daily": {
                "high_f": max(temps_f, default=70.0),
                "low_f":  min(temps_f, default=50.0),
                "avg_irradiance": avg_irr,
            },
        }
    except Exception as exc:
        logger.warning("get_24h_forecast failed: %s", exc)
        return {"hourly": [], "daily": {}}


def get_weather() -> dict:
    """Unified snapshot used by runner and prompt_builder."""
    w = get_current_weather()
    hist = get_irradiance_history(hours=6)
    irr_6h = [h["w_per_m2"] for h in hist if h["w_per_m2"] > 0]
    irr_6h_avg = round(sum(irr_6h) / len(irr_6h), 1) if irr_6h else w["irradiance_now"]
    return {
        "outside_temp_f":    w["temp_f"],
        "cloud_cover_pct":   w["cloud_cover_pct"],
        "wind_mph":          w["wind_mph"],
        "irradiance_6h_avg": irr_6h_avg,
        "irradiance_label":  _irradiance_label(irr_6h_avg),
        "forecast_24h_kwh":  0.0,
        "fetched_at":        w["fetched_at"],
        "city":              "Los Gatos",
    }


def get_weather_history(hours: int = 24) -> list[dict]:
    """Returns [{ts, temp_f, irradiance}] for anomaly detection."""
    try:
        data = _fetch({
            "latitude": LAT, "longitude": LON,
            "hourly": "temperature_2m,shortwave_radiation",
            "past_hours": hours,
            "forecast_hours": 1,
            "temperature_unit": "fahrenheit",
            "timezone": TZ,
        })
        hourly = data.get("hourly", {})
        times  = hourly.get("time", [])
        temps  = hourly.get("temperature_2m", [])
        rads   = hourly.get("shortwave_radiation", [])
        return [
            {
                "ts":         t,
                "temp_f":     float(c) if c is not None else None,
                "irradiance": float(r) if r is not None else None,
            }
            for t, c, r in zip(times, temps, rads)
        ]
    except Exception as exc:
        logger.warning("get_weather_history failed: %s", exc)
        return []


def _weather_defaults() -> dict:
    return {
        "temp_f": 62.0, "cloud_cover_pct": 50.0, "wind_mph": 5.0,
        "irradiance_now": 200.0, "irradiance_label": "moderate",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "default", "lat": LAT, "lon": LON, "city": "Los Gatos",
    }
