"""Post-processing gates applied to raw model probabilities before they become
ON/OFF states. Fixes low precision that the MODEL cannot fix, using external
structure (time-of-day, mutex, irradiance) and demoting heads that remain
unreliable. Loaded by the inference loop after ONNX forward pass.
"""
from __future__ import annotations
import json, os

# STEP 1 output: per-head calibrated thresholds (fall back to 0.5)
def load_thresholds(models_dir, panel):
    p = os.path.join(models_dir, f"panel{panel}_thresholds.json")
    try:
        return json.load(open(p))
    except Exception:
        return {}

# STEP 4: heads whose precision stays < ~0.4 even after gating. Not deleted -
# demoted: the UI shows them as low-confidence "possible", never a firm ON,
# and the DSS must not shed on them.
DEMOTED = {"solar_pump", "pressure_pump"}

# STEP 3: mutually-exclusive-by-time pairs sharing an identical band. The one
# outside its time window is reassigned OFF (its events belong to its partner).
TOD_EXCLUSIVE = {
    "sprinklers":  (3, 11),    # AM irrigation only
    "bath_lights": (16, 24),   # evening only
}

def apply_gates(states: dict, hour: int, panel_power: dict | None = None):
    """states: {head: (prob, threshold)} -> returns {head: (state, conf, flag)}.
    hour: local hour. panel_power: {'Panel1 (HVAC)': watts, ...} for solar_pump.
    """
    out = {}
    for h, (prob, thr) in states.items():
        on = prob >= thr
        flag = "ok"

        # STEP 3: time-of-day exclusivity (sprinklers vs bath_lights)
        if h in TOD_EXCLUSIVE:
            lo, hi = TOD_EXCLUSIVE[h]
            if not (lo <= hour <= hi):
                on = False; flag = "tod_gated"

        # STEP 2/solar_pump: irradiance + mutex gate. The pump is daylight-only
        # and cannot run while the heat pump draws (shared Panel-1 circuit).
        if h == "solar_pump":
            if not (7 <= hour <= 19):
                on = False; flag = "night_gated"
            elif panel_power and panel_power.get("Panel1 (HVAC)", 0) >= 800:
                on = False; flag = "mutex_gated"   # heat pump active -> not the pump

        # STEP 4: demoted heads never emit a firm ON; capped confidence
        if h in DEMOTED and on:
            flag = "demoted_low_precision"
            conf = min(float(prob), 0.49)          # UI renders as "possible", not ON
            out[h] = ("MAYBE", conf, flag); continue

        out[h] = ("ON" if on else "OFF", float(prob), flag)
    return out
