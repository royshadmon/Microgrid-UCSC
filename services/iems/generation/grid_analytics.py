"""
PG&E E6 TOU classification (Adabi 5.4.1).
"""
from datetime import datetime, timezone
from iems.config import TOU_RATES


def classify_now(ts: datetime | None = None) -> dict:
    ts = ts or datetime.now(timezone.utc)
    season = "summer" if ts.month in range(5, 11) else "winter"
    period = _classify_period(ts, season)
    rates = TOU_RATES[season]
    rate_info = rates.get(period, rates["off_peak"])
    return {
        "period": period,
        "rate_per_kwh": rate_info["rate"],
        "season": season,
        "hour": ts.hour,
        "weekday": ts.weekday() < 5,
    }


def build_daily_rate_strip(ts: datetime | None = None) -> list[dict]:
    """Returns 24 hourly rate entries for the UI rate strip."""
    ts = ts or datetime.now(timezone.utc)
    strip = []
    for hour in range(24):
        fake_ts = ts.replace(hour=hour, minute=0, second=0, microsecond=0)
        info = classify_now(fake_ts)
        strip.append({
            "hour": hour,
            "period": info["period"],
            "rate": info["rate_per_kwh"],
        })
    return strip


def _classify_period(ts: datetime, season: str) -> str:
    hour = ts.hour
    is_weekday = ts.weekday() < 5
    rates = TOU_RATES[season]

    # Check peak (weekdays only)
    if is_weekday:
        for (h0, h1) in rates["peak"]["hours"]:
            if h0 <= hour < h1:
                return "peak"

    # Check partial_peak (weekdays only for most of E6)
    if is_weekday:
        for (h0, h1) in rates["partial_peak"]["hours"]:
            if h0 <= hour < h1:
                return "partial_peak"

    # Summer weekend partial peak
    if not is_weekday and season == "summer":
        for (h0, h1) in rates.get("weekend", {}).get("hours", []):
            if h0 <= hour < h1:
                return "weekend"

    return "off_peak"
