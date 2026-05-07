"""
Open-Meteo weather client for the Los Gatos microgrid.

NILM context: heat-pump and water-heater duty cycle scales with outside
temperature (Adabi 5.4.2 weather coupling). Returns None on any failure
so the prompt builder can fall back to a non-weather prompt rather than
fail the disaggregation cycle.
"""
import json
import urllib.parse
import urllib.request


def get_current_temp_f(lat: float = 37.2358, lon: float = -121.9624) -> float | None:
    """
    Fetch current outside temperature in °F from Open-Meteo (free, no key).
    Returns None on failure — callers must handle gracefully.
    """
    try:
        params = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon,
            "current_weather": "true",
            "temperature_unit": "fahrenheit",
            "forecast_days": 1,
        })
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["current_weather"]["temperature"]
    except Exception:
        return None
