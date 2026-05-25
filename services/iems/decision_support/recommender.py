"""
Dollar-denominated DSS recommendations (Adabi Ch 5 + user requirements).
"""
from datetime import datetime, timezone
from typing import Optional

from iems.config import APPLIANCES, TOU_RATES
from iems.decision_support.rule_tree import tag_action
from iems.decision_support.shedding_bridge import _get_shedding
from iems.load.anomaly import Alert


def build_recommendations(
    current_states: dict[str, int],
    anomalies: list[Alert],
    tou_info: dict,
    weather: dict,
    mode: str = "on_grid",
    user_prefs: Optional[dict] = None,
) -> list[dict]:
    recs = []
    prefs = user_prefs or {}

    tou_period = tou_info.get("period", "off_peak")
    rate = tou_info.get("rate_per_kwh", 0.18)
    season = tou_info.get("season", "winter")

    # === Dryer deferral recommendation ===
    if current_states.get("dryer") == 1 and tou_period == "peak":
        peak_rate = TOU_RATES[season]["peak"]["rate"]
        off_rate = TOU_RATES[season]["off_peak"]["rate"]
        # dryer ~7 kW for 1 hour = 7 kWh
        savings = round(7 * (peak_rate - off_rate), 2)
        off_peak_hour = _next_off_peak_hour(tou_info)
        recs.append({
            "id": "defer_dryer",
            "appliance": "dryer",
            "action": f"Defer dryer to after {off_peak_hour} (off-peak)",
            "audience": tag_action("dryer", "shed"),
            "savings_dollars": savings,
            "rationale": (
                f"Dryer running during peak at ${peak_rate}/kWh. "
                f"Deferring 1 load to off-peak (${off_rate}/kWh) saves ~${savings}."
            ),
            "confidence": 0.9,
        })

    # === Heat pump efficiency recommendation ===
    temp_f = weather.get("outside_temp_f", 60)
    if current_states.get("heat_pump") == 1 and temp_f < 50:
        recs.append({
            "id": "hp_cold_mode",
            "appliance": "heat_pump",
            "action": "Lower thermostat 2°F to reduce heat pump duty cycle",
            "audience": "user",
            "savings_dollars": 0.60,
            "rationale": (
                f"Outside is {temp_f}°F — heat pump running hard. "
                f"Reducing setpoint 2°F saves ~$0.60/day in COP-adjusted draw."
            ),
            "confidence": 0.7,
        })

    # === Water heater pre-heat recommendation ===
    irr = weather.get("irradiance_label", "low")
    if irr == "high" and tou_period == "peak":
        recs.append({
            "id": "wh_solar_preheat",
            "appliance": "water_heater",
            "action": "Solar irradiance is high — water heater likely pre-heated by boiler",
            "audience": "auto",
            "savings_dollars": 0.0,
            "rationale": (
                "High irradiance detected. Solar thermal boiler is likely keeping "
                "the tank hot, so electric element should be idle. No action needed."
            ),
            "confidence": 0.85,
        })

    # === Anomaly alerts → recommendations ===
    for alert in anomalies:
        recs.append({
            "id": f"anomaly_{alert.appliance}",
            "appliance": alert.appliance,
            "action": alert.message,
            "audience": "user",
            "savings_dollars": 0.0,
            "rationale": str(alert.evidence),
            "confidence": 1.0,
            "is_anomaly": True,
            "severity": alert.severity,
        })

    # === Off-peak load shift ===
    if tou_period == "off_peak":
        deferrable_on = [
            k for k, v in current_states.items()
            if v == 1 and APPLIANCES.get(k, {}).get("deferrable")
        ]
        if deferrable_on:
            for app_name in deferrable_on:
                app = APPLIANCES[app_name]
                lo, hi = app["power_range_w"]
                kwh = ((lo + hi) / 2) / 1000 * (app["avg_on_duration_min"] / 60)
                recs.append({
                    "id": f"run_offpeak_{app_name}",
                    "appliance": app_name,
                    "action": f"Good time to run {app['user_visible_label']} (off-peak now)",
                    "audience": "user",
                    "savings_dollars": round(kwh * rate, 4),
                    "rationale": f"Off-peak rate ${rate}/kWh — best time to run this load.",
                    "confidence": 0.8,
                })

    # === Refrigerator anomaly (Panel3 model, F1=1.00 — high confidence) ===
    fridge_on = current_states.get("refrigerator") == 1
    if fridge_on and tou_period == "peak":
        recs.append({
            "id": "fridge_peak_advisory",
            "appliance": "refrigerator",
            "action": "Fridge cycling normally during peak — no action needed",
            "audience": "auto",
            "savings_dollars": 0.0,
            "rationale": "Critical load. Never shed even in peak.",
            "confidence": 0.95,
        })

    # === Dishwasher TOU deferral (Panel3 F1=0.73) ===
    if current_states.get("dishwasher") == 1 and tou_period == "peak":
        peak_rate = TOU_RATES[season]["peak"]["rate"]
        off_rate  = TOU_RATES[season]["off_peak"]["rate"]
        savings = round(1.8 * (peak_rate - off_rate), 2)   # ~1.8 kWh per cycle
        recs.append({
            "id": "defer_dishwasher",
            "appliance": "dishwasher",
            "action": "Defer dishwasher to off-peak (after 21:00)",
            "audience": "user",
            "savings_dollars": savings,
            "rationale": (
                f"Dishwasher in peak at ${peak_rate}/kWh. "
                f"Off-peak ${off_rate}/kWh saves ~${savings}/cycle."
            ),
            "confidence": 0.85,
        })

    # === Washing machine + dryer pair (Shop panel, Panel3 model) ===
    if current_states.get("washing_machine") == 1 and tou_period == "peak":
        recs.append({
            "id": "wm_peak_warning",
            "appliance": "washing_machine",
            "action": "Washer running in peak — let cycle finish but defer dryer",
            "audience": "user",
            "savings_dollars": round(7.0 * (TOU_RATES[season]["peak"]["rate"]
                                           - TOU_RATES[season]["off_peak"]["rate"]), 2),
            "rationale": "Dryer is the largest deferrable load (7 kWh / cycle).",
            "confidence": 0.9,
        })

    # === Sprinklers (Panel2 model, F1=0.36 — usable but noisy) ===
    if current_states.get("sprinklers") == 1:
        if tou_period == "peak":
            recs.append({
                "id": "sprinklers_peak",
                "appliance": "sprinklers",
                "action": "Sprinklers active in peak — reschedule to pre-dawn",
                "audience": "user",
                "savings_dollars": round(0.4 * (TOU_RATES[season]["peak"]["rate"]
                                              - TOU_RATES[season]["off_peak"]["rate"]), 2),
                "rationale": "Sprinklers should run 04:00–06:00 to minimize evaporation and TOU cost.",
                "confidence": 0.7,
            })

    # === Always-on TOU summary (informational) ===
    # Ensures the DSS panel always has at least one dollar-denominated entry.
    if not recs:
        if tou_period == "peak":
            msg = (
                f"Currently in PEAK rate period (${rate}/kWh). "
                f"Avoid starting the dryer, dishwasher or washing machine until off-peak."
            )
            est = round(7.0 * (rate - TOU_RATES[season]['off_peak']['rate']), 2)
        elif tou_period in ("partial_peak", "weekend"):
            msg = f"Partial-peak rate ${rate}/kWh — minor TOU savings available by deferring large loads."
            est = round(7.0 * (rate - TOU_RATES[season]['off_peak']['rate']), 2)
        else:
            msg = f"Off-peak rate ${rate}/kWh — best time to run deferrable loads."
            est = 0.0
        recs.append({
            "id": "tou_summary",
            "appliance": "grid",
            "action": msg,
            "audience": "user",
            "savings_dollars": est,
            "rationale": f"Current TOU period is {tou_period} at ${rate}/kWh.",
            "confidence": 1.0,
            "is_anomaly": False,
        })

    return recs[:5]


def _next_off_peak_hour(tou_info: dict) -> str:
    hour = tou_info.get("hour", 12)
    season = tou_info.get("season", "winter")
    for h in range(hour + 1, 24):
        fake_ts = datetime.now(timezone.utc).replace(hour=h)
        from iems.generation.grid_analytics import classify_now
        info = classify_now(fake_ts)
        if info["period"] == "off_peak":
            return f"{h}:00"
    return "21:00"
