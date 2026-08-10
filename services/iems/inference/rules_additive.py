"""Post-inference rules: weather-aware Panel1 reconciliation, cross-panel
solar/water-heater coupling, physics power-gating, additive disambiguation,
mutual exclusion.

Decision policy (recall-favoring, physics- and weather-gated):
  1. Panel1 weather rules (NEW) — the solar (thermal) circulation pump only runs
     when there is sun to circulate, so it is gated on irradiance + cloud cover;
     with no solar resource it is confidently OFF. The heat pump is Panel1's big
     load and is recovered from the LIVE measured Panel1 watts vs its nominal
     band (with a ~550 W fan-only sub-state), the same live-wattage approach used
     on Panel3.
  2. mutual exclusion       — heat_pump <-> solar_pump are interlocked.
  3. power gate             — an appliance cannot be ON if its panel draws less
                              than that appliance alone needs (anti-false-positive;
                              lets the weak Panel1/Panel2 models run low thresholds).
  4. Panel2 water-heater (NEW) — solar-thermal fallback: when the solar pump is
                              confidently OFF (low solar), the electric water
                              heater on Panel2 is the hot-water fallback; it is
                              switched ON when Panel2 is actually drawing
                              water-heater-band power (~2-4 kW).
  5. additive recovery      — residual panel watts beyond the ON set switch on
                              the best-fitting OFF appliance.
  6. overshoot trim (soft)  — trims only low-confidence, non-physics-set ON
                              appliances; never the top call or a high-confidence
                              one.

Signature table (from the Mantey-site appliance inventory):
  (on_threshold_w, lo_w, hi_w)  — power band when ON.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

# Battery is charged daily 16:00-21:00 local at the Mantey site.
BATTERY_WINDOW = (16, 21)  # [start_hour, end_hour)

# At most one of each group may be ON simultaneously.
# MUTEX REMOVED 2026-08-05: heat_pump/solar_pump have no physical interlock.
# Left as an empty tuple rather than deleted so apply_mutual_exclusion stays
# available if a genuinely exclusive pair appears later.
MUTEX_GROUPS = ()

# Confidence at/above which an appliance is never trimmed by the overshoot rule.
PROTECT_CONF = 0.50

# Weather gating for the solar (thermal) circulation pump on Panel1.
SOLAR_MIN_IRRADIANCE = 150.0   # W/m^2 (6h avg); below this the collectors don't
                               # justify circulating -> pump idle.
SOLAR_MAX_CLOUD_PCT  = 80.0    # heavy overcast -> pump idle.
SOLAR_DAYLIGHT_HOURS = (6, 20) # local clock hours the pump may run.

# Measured Solar Assistant thresholds (replace the weather/time proxies when a
# live solar_data snapshot is available).
PV_MIN_W            = 200.0   # measured PV below this -> no useful solar resource
BATTERY_CHARGE_MIN_W = 50.0   # measured battery power above this -> pack charging

# Rules that physics/weather deliberately set — never undone by overshoot trim.
PROTECTED_RULES = {
    "heat_pump_recovery", "water_heater_solar_fallback",
    "additive_recovery", "solar_recovery",
}

# on_threshold_w, lo_w, hi_w
APPLIANCE_SIGNATURE = {
    "heat_pump_fan":    (300,  450,  650),
    "solar_pump":       (25,   100,  250),   # floor lowered from 50 -> 25 W to admit low-draw on-states
    "water_heater":     (500, 2000, 4300),   # CT element p95 4011W; 4000 ceiling clipped real fires
    "hair_dryer":       (800, 1200, 1800),
    "sprinklers":       (50,   100,  300),
    "bath_lights":      (80,   100,  300),   # master-bath mirror incandescent
    "refrigerator":     (50,    80,  200),   # kitchen unit, one compressor
    "garage_fridge":    (50,    80,  220),   # garage, high duty
    "garage_freezer":   (50,    80,  250),   # garage, long slow cycles   # aggregate of 3 cold loads; ceiling admits
                                             # two overlapping compressors (Kelly 2015: 300W max for ONE fridge)
    "dishwasher":       (50,   200, 1800),
    "microwave":        (200,  900, 1500),
    "dryer":            (1000, 4000, 7000),
    "washing_machine":  (50,   200, 2000),
    "pressure_pump":    (200,  500, 1000),
    "computers":        (100,  200,  500),
    "tv_stereo":        (80,   100,  200),
    "vacuum_cleaner":   (600,  800, 1200),
    "garage_opener":    (250,  300,  800),  # aligned to canonical band
    # Added 2026-08-07 from the panel directories. Bands are (on_thr, typical,
    # max) and must stay consistent with canonical_signatures, or the additive
    # power gate will veto predictions the labeller considered valid.
    "heat_pump":        (1200, 2500, 5700),   # MEASURED 2500-5700 (CT p5 3782); spec said 1500-4000
    "jacuzzi_pump":     (400,   800, 2000),  # archive events ~891W below old 1500 floor
    "strip_heater":     (5800, 7000, 12000),
    "oven":             (1200, 2000, 4000),  # aligned to canonical lo
    "cooktop":          (1200, 1500, 5000),  # aligned to canonical lo
    "counter_appliance":(600,   800, 1500),  # unified toaster/coffee/iron
}

# Cross-panel channel: Panel1 writes solar context here, Panel2 reads it.
# Panels are processed in order (Panel1 -> Panel2 -> Panel3) within a tick.
_SOLAR_CONTEXT = {"solar_pump_on": False, "solar_pump_conf": 0.0,
                  "low_solar": True, "ts": None}


def is_battery_window(ts_local: datetime) -> bool:
    return BATTERY_WINDOW[0] <= ts_local.hour < BATTERY_WINDOW[1]


def _low_solar(weather: Optional[dict], ts_local: Optional[datetime],
               solar: Optional[dict] = None) -> bool:
    """True when there is no useful solar resource for the thermal pump.

    Prefers MEASURED PV power from Solar Assistant (solar_data.pv_power) over the
    weather-derived irradiance proxy. A direct pv_power reading is authoritative:
    if the array is producing >= PV_MIN_W there is sun to circulate, regardless
    of the forecast irradiance. Falls back to the weather proxy when no live
    solar snapshot is available."""
    if solar and solar.get("pv_power") is not None:
        return float(solar.get("pv_power", 0.0) or 0.0) < PV_MIN_W
    w = weather or {}
    irr = float(w.get("irradiance_6h_avg", w.get("irradiance_now", 0.0)) or 0.0)
    # NB: use an explicit None-check, not `or 100.0` -- a real 0%% cloud cover
    # (clear sky) is falsy and would otherwise be read as full overcast.
    _cc = w.get("cloud_cover_pct")
    cloud = float(_cc) if _cc is not None else 100.0
    hour = ts_local.hour if ts_local is not None else 12
    daylight = SOLAR_DAYLIGHT_HOURS[0] <= hour < SOLAR_DAYLIGHT_HOURS[1]
    return (irr < SOLAR_MIN_IRRADIANCE) or (cloud > SOLAR_MAX_CLOUD_PCT) or (not daylight)


def _battery_charging(solar: Optional[dict], ts_local: Optional[datetime]) -> bool:
    """Prefer MEASURED battery power (solar_data.battery_power) over the fixed
    16:00-21:00 time window. battery_power >= BATTERY_CHARGE_MIN_W means the pack
    is actually charging right now; the time window is only a fallback."""
    if solar and solar.get("battery_power") is not None:
        return float(solar.get("battery_power", 0.0) or 0.0) >= BATTERY_CHARGE_MIN_W
    return ts_local is not None and BATTERY_WINDOW[0] <= ts_local.hour < BATTERY_WINDOW[1]


def apply_mutual_exclusion(preds: dict) -> dict:
    """For each mutex group, keep only the highest-confidence ON member."""
    for group in MUTEX_GROUPS:
        present = [a for a in group if a in preds]
        on = [a for a in present if preds[a]["state"] == 1]
        if len(on) > 1:
            winner = max(on, key=lambda a: preds[a]["confidence"])
            for a in on:
                if a != winner:
                    preds[a]["state"] = 0
                    preds[a]["power_w"] = 0.0
                    preds[a]["rule"] = f"mutex:lost_to_{winner}"
    return preds


def apply_power_gate(preds: dict, panel_power_w: float, margin_w: float = 120.0) -> dict:
    """Anti-false-positive: an ON appliance whose own minimum on-threshold
    exceeds the entire measured panel draw (plus a small margin) is impossible,
    so force it OFF."""
    for a, p in preds.items():
        if p["state"] != 1:
            continue
        sig = APPLIANCE_SIGNATURE.get(a)
        if not sig:
            continue
        if panel_power_w + margin_w < sig[0]:
            p["state"] = 0
            p["power_w"] = 0.0
            p["rule"] = "power_gate_off"
    return preds


def apply_panel1_rules(preds: dict, panel_power_w: float,
                       weather: Optional[dict], ts_local: Optional[datetime],
                       solar: Optional[dict] = None) -> dict:
    """Weather-gated solar pump + live-wattage heat-pump reconciliation.

    Panel1 carries only the heat pump and the solar circulation pump (mutually
    exclusive). We compare the LIVE measured Panel1 watts to each appliance's
    standard band and use irradiance/cloud cover to decide the solar pump.
    """
    low_solar = _low_solar(weather, ts_local, solar)

    sp = preds.get("solar_pump")
    if sp is not None:
        s_thr, s_lo, s_hi = APPLIANCE_SIGNATURE["solar_pump"]   # 50,100,250
        if low_solar and sp["state"] == 1:
            # No sun to circulate -> the pump cannot justifiably be running.
            sp["state"] = 0
            sp["power_w"] = 0.0
            sp["rule"] = "solar_gate:low_solar"
        elif (not low_solar) and sp["state"] == 0:
            # Sunny + a small Panel1 draw in the solar-pump band, and the heat
            # pump is not the obvious explanation -> recover the solar pump.
            hp_on = preds.get("heat_pump", {}).get("state", 0) == 1
            if (not hp_on) and s_thr <= panel_power_w <= s_hi + 100:
                sp["state"] = 1
                sp["power_w"] = float(min(max(panel_power_w, s_lo), s_hi))
                sp["rule"] = "solar_recovery"

    hp = preds.get("heat_pump")
    if hp is not None and hp["state"] == 0:
        _thr, hp_lo, hp_hi = APPLIANCE_SIGNATURE["heat_pump"]   # 300,1500,4000
        fan_lo = APPLIANCE_SIGNATURE["heat_pump_fan"][1]        # 450
        solar_on = preds.get("solar_pump", {}).get("state", 0) == 1
        solar_hi = APPLIANCE_SIGNATURE["solar_pump"][2]         # 250
        # Subtract the small solar-pump draw if it is on; the remainder on
        # Panel1 is the heat pump (incl. its ~550 W fan-only sub-state).
        residual = panel_power_w - (solar_hi if solar_on else 0.0)
        if residual >= fan_lo:
            hp["state"] = 1
            hp["power_w"] = float(min(max(residual, fan_lo), hp_hi))
            hp["rule"] = "heat_pump_recovery"

    # Stash solar context for Panel2's water-heater inference.
    sp2 = preds.get("solar_pump", {})
    _SOLAR_CONTEXT.update({
        "solar_pump_on":   sp2.get("state", 0) == 1,
        "solar_pump_conf": float(sp2.get("confidence", 0.0)),
        "low_solar":       low_solar,
        "ts":              ts_local,
    })
    return preds


def apply_panel2_rules(preds: dict, panel_power_w: float,
                       weather: Optional[dict]) -> dict:
    """Solar-thermal fallback + power-based water heater gating.
    
    Water heater is Panel2's primary large load (2-4 kW when running).
    Two gates:
    1. Power gate: if Panel2 > 2.5 kW, water heater must be running (model
       is weak on this panel; bypass it when power is obvious).
    2. Solar fallback: solar pump OFF + panel drawing water-heater-band
       power -> fire water heater.
    """
    wh = preds.get("water_heater")
    if wh is None:
        return preds
    _thr, wh_lo, wh_hi = APPLIANCE_SIGNATURE["water_heater"]   # 500,2000,4000
    
    # Power gate: Panel2 drawing >2.5kW almost always means water heater.
    # Model is weak here; trust the power signal over model confidence.
    if panel_power_w > 2500:
        wh["state"] = 1
        wh["power_w"] = float(min(max(panel_power_w, wh_lo), wh_hi))
        wh["rule"] = "water_heater_power_gate"
        return preds
    
    ctx = _SOLAR_CONTEXT
    solar_off_confident = (not ctx.get("solar_pump_on", False)) and ctx.get("low_solar", True)
    if wh["state"] == 0 and solar_off_confident and panel_power_w >= wh_lo:
        wh["state"] = 1
        wh["power_w"] = float(min(max(panel_power_w, wh_lo), wh_hi))
        wh["rule"] = "water_heater_solar_fallback"
    return preds


def additive_disambiguation(preds: dict, panel_power_w: float,
                            on_tol_w: float = 400.0) -> dict:
    """Reconcile the predicted ON set against measured panel power."""
    def hi_of(a):
        sig = APPLIANCE_SIGNATURE.get(a)
        return sig[2] if sig else max(preds[a]["power_w"], 0.0)

    def lo_of(a):
        sig = APPLIANCE_SIGNATURE.get(a)
        return sig[1] if sig else max(preds[a]["power_w"], 0.0)

    def explained_hi():
        return sum(hi_of(a) for a, p in preds.items() if p["state"] == 1)

    def explained_lo():
        return sum(lo_of(a) for a, p in preds.items() if p["state"] == 1)

    # --- additive recovery (residual beyond ON appliances' band maxima) ---
    residual = panel_power_w - explained_hi()
    while residual > on_tol_w:
        best = None
        for a, p in preds.items():
            if p["state"] == 1 or a not in APPLIANCE_SIGNATURE:
                continue
            thr, lo, hi = APPLIANCE_SIGNATURE[a]
            if residual >= thr and residual <= hi + on_tol_w:
                center = (lo + hi) / 2.0
                fit = abs(residual - center)
                if best is None or fit < best[1]:
                    best = (a, fit, min(max(residual, lo), hi))
        if best is None:
            break
        a, _, assigned_w = best
        preds[a]["state"] = 1
        preds[a]["power_w"] = float(assigned_w)
        preds[a]["rule"] = "additive_recovery"
        residual = panel_power_w - explained_hi()

    # --- overshoot trimming (soft: protect high-conf, top call, physics rules) ---
    overshoot = explained_lo() - panel_power_w
    while overshoot > on_tol_w:
        on = [(a, p) for a, p in preds.items() if p["state"] == 1]
        if len(on) <= 1:
            break
        top = max(on, key=lambda ap: ap[1]["confidence"])[0]
        trimmable = [(a, p) for a, p in on
                     if a != top
                     and p["confidence"] < PROTECT_CONF
                     and p.get("rule") not in PROTECTED_RULES]
        if not trimmable:
            break
        victim = min(trimmable, key=lambda ap: ap[1]["confidence"])[0]
        overshoot -= lo_of(victim)
        preds[victim]["state"] = 0
        preds[victim]["power_w"] = 0.0
        preds[victim]["rule"] = "overshoot_trim"
    return preds


def apply_rules(preds: dict, panel_power_w: float, ts_local: Optional[datetime] = None,
                additive: bool = True, weather: Optional[dict] = None,
                panel: Optional[str] = None, solar: Optional[dict] = None) -> dict:
    """Full post-inference reconciliation for one panel/window."""
    for p in preds.values():
        p.setdefault("rule", "model")

    # Panel1 weather/solar reconciliation runs before mutex so a weather-gated
    # solar pump cannot win the heat_pump<->solar_pump interlock.
    if panel and "Panel1" in panel:
        preds = apply_panel1_rules(preds, panel_power_w, weather, ts_local, solar)

    preds = apply_mutual_exclusion(preds)

    # Measured battery charging (solar_data.battery_power) supersedes the fixed
    # 16:00-21:00 window; annotate every appliance so downstream consumers know
    # the pack is drawing charge (context for high-load reconciliation).
    if _battery_charging(solar, ts_local):
        for p in preds.values():
            p["battery_charging"] = True

    # Energy-balance context: attach the measured whole-house load so the
    # reconciled output can be checked against the true site load downstream.
    if solar and solar.get("load_power") is not None:
        for p in preds.values():
            p.setdefault("house_load_w", float(solar.get("load_power") or 0.0))

    preds = apply_power_gate(preds, panel_power_w)

    if panel and "Panel2" in panel:
        preds = apply_panel2_rules(preds, panel_power_w, weather)

    if additive:
        preds = additive_disambiguation(preds, panel_power_w)
    return preds
