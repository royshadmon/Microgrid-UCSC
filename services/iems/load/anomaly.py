"""
Anomaly detection (user-requested):
- Water heater dormancy → element failure / breaker trip / solar boiler stuck
- Pressure pump excessive cycling → plumbing leak (proven at this site)
- Phantom dryer (2-5 AM with no preceding wash cycle)
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

WATER_HEATER_FIELD = "water_heater_status"
PUMP_FIELD = "pressure_pump_status"
DRYER_FIELD = "dryer_status"
WASHER_FIELD = "washing_machine_status"


@dataclass
class Alert:
    severity: str       # "warning" | "critical"
    appliance: str
    message: str
    evidence: dict


def detect_water_heater_dormancy(
    states: dict[str, list[int]],
    weather_history: list[dict],
    lookback_hours: int = 24,
) -> Optional[Alert]:
    """
    Flag if WH never fired in lookback window AND temp was cold AND
    irradiance was not high. Suggests element failure or breaker trip.
    Dormancy in warm/sunny weather is EXPECTED (solar boiler) — do not flag.
    """
    wh_states = states.get(WATER_HEATER_FIELD, [])
    if not wh_states:
        return None

    ever_fired = any(s == 1 for s in wh_states)
    if ever_fired:
        return None

    if not weather_history:
        return None

    temps = [w.get("temp_f") for w in weather_history if w.get("temp_f") is not None]
    irradiances = [w.get("irradiance") for w in weather_history if w.get("irradiance") is not None]

    avg_temp = sum(temps) / len(temps) if temps else 60.0
    avg_irr = sum(irradiances) / len(irradiances) if irradiances else 200.0

    # Only flag if it's cold AND irradiance was not high
    # (high irradiance = solar boiler likely preheated, silence is expected)
    if avg_temp >= 55.0:
        return None
    if avg_irr >= 300.0:
        return None

    return Alert(
        severity="warning",
        appliance="water_heater",
        message=(
            f"Water heater has not fired in the last {lookback_hours}h "
            f"despite cold weather (avg {avg_temp:.0f}°F) and low solar irradiance "
            f"({avg_irr:.0f} W/m²). Possible element failure, breaker trip, or "
            f"thermostat fault. Solar boiler preheating is unlikely in these conditions."
        ),
        evidence={
            "lookback_hours": lookback_hours,
            "avg_temp_f": round(avg_temp, 1),
            "avg_irradiance_wm2": round(avg_irr, 1),
            "wh_fire_count": 0,
        },
    )


def detect_pump_anomaly(
    pump_states=None,
    baseline_cycles_per_hour: float = 2.0,
    threshold: float = 2.0,
    states: Optional[dict[str, list[int]]] = None,
) -> Optional[Alert]:
    """
    Compute pressure_pump cycles/hour over the last 6h.
    If > threshold * baseline → flag possible plumbing leak.

    Accepts either:
      - pump_states=[0,1,0,1,...] (direct ON/OFF list), or
      - states={"pressure_pump_status": [...], ...} for compatibility with
        run_all_anomaly_checks.
    """
    if isinstance(pump_states, dict) and states is None:
        # Caller passed the full states dict positionally.
        states = pump_states
        pump_states = None
    if pump_states is None:
        pump_states = (states or {}).get(PUMP_FIELD, [])
    if len(pump_states) < 2:
        return None

    # Count transitions 0→1 in last 6 hours
    # States are at 6-second intervals: 6h = 3600 samples
    lookback = min(len(pump_states), 3600)
    recent = pump_states[-lookback:]
    cycles = sum(
        1 for i in range(1, len(recent))
        if recent[i] == 1 and recent[i - 1] == 0
    )
    hours_covered = lookback * 6 / 3600
    cycles_per_hour = cycles / hours_covered if hours_covered > 0 else 0.0

    if cycles_per_hour <= threshold * baseline_cycles_per_hour:
        return None

    return Alert(
        severity="warning",
        appliance="pressure_pump",
        message=(
            f"Pressure pump cycling {cycles_per_hour:.1f}×/hr — "
            f"{cycles_per_hour / baseline_cycles_per_hour:.1f}× above baseline "
            f"({baseline_cycles_per_hour}×/hr). Possible plumbing leak in shop area. "
            f"Check for running fixtures, irrigation line break, or toilet fill valve."
        ),
        evidence={
            "cycles_per_hour": round(cycles_per_hour, 2),
            "baseline_cycles_per_hour": baseline_cycles_per_hour,
            "lookback_hours": round(hours_covered, 2),
            "total_cycles": cycles,
        },
    )


def detect_phantom_dryer(states: dict[str, list[int]]) -> Optional[Alert]:
    """
    Dryer running 2-5 AM with no preceding washing_machine cycle → flag.
    States assumed at 6-second intervals; hours extracted by index position.
    """
    dryer_states = states.get(DRYER_FIELD, [])
    washer_states = states.get(WASHER_FIELD, [])
    if not dryer_states:
        return None

    total_samples = len(dryer_states)
    # 2 AM = sample 1200, 5 AM = sample 3000 (from midnight, 6s intervals)
    # Approximate: check last 24h block for overnight window
    # Each hour = 600 samples
    samples_per_hour = 600
    night_start = 2 * samples_per_hour
    night_end = 5 * samples_per_hour

    if total_samples < night_end:
        return None

    dryer_night = dryer_states[night_start:night_end]
    dryer_on = any(s == 1 for s in dryer_night)
    if not dryer_on:
        return None

    # Check if washer ran in the 4 hours prior to 2 AM
    washer_window = washer_states[max(0, night_start - 4 * samples_per_hour):night_start]
    washer_ran = any(s == 1 for s in washer_window)

    if washer_ran:
        return None

    return Alert(
        severity="warning",
        appliance="dryer",
        message=(
            "Clothes dryer detected running between 2-5 AM with no preceding "
            "washing machine cycle. Possible forgotten restart, accidental "
            "timer activation, or load from previous day still tumbling."
        ),
        evidence={
            "dryer_on_night": True,
            "washer_preceded": False,
        },
    )


def run_all_anomaly_checks(
    states: dict[str, list[int]],
    weather_history: list[dict],
) -> list[Alert]:
    alerts = []

    wh = detect_water_heater_dormancy(states, weather_history)
    if wh:
        alerts.append(wh)

    pump = detect_pump_anomaly(states)
    if pump:
        alerts.append(pump)

    dryer = detect_phantom_dryer(states)
    if dryer:
        alerts.append(dryer)

    return alerts
