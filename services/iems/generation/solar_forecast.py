"""
Solar generation forecast combining Open-Meteo irradiance with house profile.
No API key required.
"""
import logging
from iems.weather import get_weather, get_weather_history, get_24h_forecast

logger = logging.getLogger(__name__)

__all__ = [
    "get_solar_forecast",
    "get_24h_forecast",
    "irradiance_for_thermal_dump",
]

# House has no solar PV yet — this returns irradiance proxy for dispatch logic
# and water heater thermal dump decisions.


def get_solar_forecast() -> dict:
    weather = get_weather()
    history = get_weather_history(hours=6)

    return {
        "has_solar_pv": False,
        "solar_w_now": 0,
        "forecast_24h_kwh": weather["forecast_24h_kwh"],
        "irradiance_now": weather["irradiance_6h_avg"],
        "irradiance_label": weather["irradiance_label"],
        "cloud_cover_pct": weather["cloud_cover_pct"],
        "note": (
            "Solar PV not installed. Irradiance data used for water heater "
            "solar-boiler modelling and thermal-dump decisions."
        ),
    }


def irradiance_for_thermal_dump() -> bool:
    """Return True when excess solar irradiance justifies thermal dump to water heater."""
    weather = get_weather()
    return weather["irradiance_label"] == "high"
