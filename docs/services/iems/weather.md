# `weather.py`

`services/iems/weather.py` — single-file Open-Meteo client for Los Gatos, CA (37.2358, −121.9624). No API key, free endpoint, `urllib` only.

## Main contents

Three public getters and two small helpers:

| Function                              | Returns                                                        |
|---------------------------------------|----------------------------------------------------------------|
| `get_current_weather()`               | dict with `temp_c`, `temp_f`, `cloud_cover_pct`, `wind_kph`, `solar_irradiance_wm2`, `irradiance_label`, `time` |
| `get_irradiance_history(hours=6)`     | list of hourly `{ts, irradiance_wm2}` dicts                    |
| `get_24h_forecast()`                  | dict of next-24h hourly arrays                                 |
| `get_weather()`                       | merged "snapshot for the runner" — current + forecast headline |
| `get_weather_history(hours=24)`       | list of hourly weather dicts going back N hours                |
| `_c_to_f(c)`                          | Celsius → Fahrenheit                                           |
| `_irradiance_label(wm2)`              | `"high"` ≥ 400, `"moderate"` ≥ 150, else `"low"`               |
| `_weather_defaults()`                 | offline fallback when Open-Meteo is unreachable                |

Coordinates and timezone come from env vars (`HOUSE_LAT`, `HOUSE_LON`, `HOUSE_TZ`) with the Los Gatos defaults baked in.

## Use in the project

Weather is an input to two domains:

1. **Load (NILM).** `prompt_builder.build_system_prompt()` injects current weather and irradiance into the LLM prompt for Panel1 (HVAC → heat pump) and Panel2 (H2O → water heater + solar boiler). The ONNX feature builder also pulls weather columns into the input tensor. Cold + low irradiance is what makes `anomaly.detect_water_heater_dormancy()` actually fire — see `test_water_heater_dormancy_only_fires_when_cold_AND_low_irradiance`.

2. **Generation.** `solar_forecast.get_solar_forecast()` consumes `get_24h_forecast()` to project tomorrow's PV.

`runner.run_iems_cycle()` calls `get_weather()` once at the top of every cycle and threads the dict through the four domains so they all see the same snapshot.

## Key lines

```python
LAT = float(os.environ.get("HOUSE_LAT", "37.2358"))
LON = float(os.environ.get("HOUSE_LON", "-121.9624"))
TZ  = os.environ.get("HOUSE_TZ", "America/Los_Angeles")

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

def _irradiance_label(wm2):
    if wm2 >= 400: return "high"
    if wm2 >= 150: return "moderate"
    return "low"
```

If Open-Meteo is unreachable, `_weather_defaults()` returns a sane mid-day stub so the rest of the cycle still runs.
