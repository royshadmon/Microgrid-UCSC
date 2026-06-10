"""
Storage dispatch logic.
Generates dispatch_recommendation based on SOC, grid mode, and TOU period.
"""
from typing import Optional, Any

from iems.storage.battery_model import (
    get_virtual_soc, SOC_MIN, SOC_MAX, BatteryModel,
)


def get_dispatch_recommendation(
    mode: str,
    tou_period: str,
    load_kw: float,
    generation_kw: float,
    irradiance_label: str = "low",
) -> dict:
    soc = get_virtual_soc()
    soc_frac = soc["soc_pct"] / 100

    if mode == "on_grid":
        if tou_period in ("off_peak",) and soc_frac < SOC_MAX:
            action = "charge"
            rationale = "Off-peak rates — charge virtual battery from grid"
        elif tou_period in ("peak", "partial_peak", "weekend") and soc_frac > SOC_MIN:
            action = "discharge"
            rationale = f"Peak period — discharge battery to reduce grid draw"
        else:
            action = "idle"
            rationale = "SOC at limits or no TOU incentive"
    else:
        # Off-grid / island mode
        if load_kw > generation_kw and soc_frac > SOC_MIN:
            action = "discharge"
            rationale = "Off-grid: load > generation — discharging before Generac start"
        elif generation_kw > load_kw and irradiance_label == "high":
            action = "thermal_dump"
            rationale = "Excess solar irradiance in island mode — thermal dump to water heater"
        elif load_kw > generation_kw and soc_frac <= SOC_MIN:
            action = "start_generac"
            rationale = "Battery depleted and load > generation — Generac recommended"
        else:
            action = "idle"
            rationale = "On-grid balance maintained"

    return {
        "action": action,
        "rationale": rationale,
        "soc": soc,
        "load_kw": round(load_kw, 2),
        "generation_kw": round(generation_kw, 2),
    }


# Off-peak / peak / partial-peak TOU rate gaps (PG&E E6 ballpark) used to
# estimate dispatch savings.
_TOU_DISCHARGE_GAP = {
    "peak":          0.20,
    "partial_peak":  0.10,
    "weekend":       0.10,
    "off_peak":      0.0,
}


def recommend(
    battery: Any,
    mode: str,
    tou_period: str,
    load_w: float,
    gen_w: float,
    irradiance_label: str = "low",
    duration_h: float = 1.0,
) -> dict:
    """
    Recommend a dispatch action for a BatteryModel.

    Returns:
      {
        "action": "charge" | "discharge" | "idle" | "thermal_dump" | "start_generac",
        "expected_savings_dollars": float,
        "rationale": str,
        "load_w": float,
        "gen_w": float,
      }
    """
    load_kw = load_w / 1000.0
    gen_kw  = gen_w  / 1000.0

    if hasattr(battery, "soc"):
        soc = battery.soc
        soc_min = getattr(battery, "soc_min", SOC_MIN)
        soc_max = getattr(battery, "soc_max", SOC_MAX)
        max_power_kw = getattr(battery, "max_power_kw", 5.0)
    else:
        snap = get_virtual_soc()
        soc = snap["soc_pct"] / 100
        soc_min, soc_max, max_power_kw = SOC_MIN, SOC_MAX, 5.0

    if mode == "on_grid":
        if tou_period == "off_peak" and soc < soc_max:
            action = "charge"
            rationale = "Off-peak rates — charge virtual battery from grid"
        elif tou_period in ("peak", "partial_peak", "weekend") and soc > soc_min:
            action = "discharge"
            rationale = f"{tou_period.replace('_',' ').title()} — discharge battery to reduce grid draw"
        else:
            action = "idle"
            rationale = "SOC at limits or no TOU incentive"
    else:
        if load_kw > gen_kw and soc > soc_min:
            action = "discharge"
            rationale = "Off-grid: load > generation — discharge before Generac start"
        elif gen_kw > load_kw and irradiance_label == "high":
            action = "thermal_dump"
            rationale = "Excess solar irradiance in island mode — thermal dump to water heater"
        elif load_kw > gen_kw and soc <= soc_min:
            action = "start_generac"
            rationale = "Battery depleted and load > generation — Generac recommended"
        else:
            action = "idle"
            rationale = "Off-grid balance maintained"

    # Savings estimate: only the discharge action shifts grid draw across
    # rate tiers. Other actions report 0 dollars.
    if action == "discharge":
        gap = _TOU_DISCHARGE_GAP.get(tou_period, 0.0)
        kwh_shifted = min(max_power_kw, load_kw) * duration_h
        expected_savings = round(kwh_shifted * gap, 4)
    else:
        expected_savings = 0.0

    return {
        "action": action,
        "expected_savings_dollars": expected_savings,
        "rationale": rationale,
        "load_w": round(load_w, 1),
        "gen_w": round(gen_w, 1),
    }
