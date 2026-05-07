"""
Appliance knowledge base for the eGauge18646 house in Los Gatos, CA.

Schema follows Xue et al. 2025 (LLM4NILM, §3.1–3.2) — each appliance
has a power_range (most critical field per §5.2), standby_w, typical
duration, and a usage_pattern string that the LLM consumes verbatim
in the per-panel prompt.

Appliance keys map directly to "<key>_status" output keys in the LLM
JSON response (Adabi 5.3 / LLM4NILM 4.2).
"""

APPLIANCE_CONFIGS = {

    # ── Panel1 (HVAC) ──────────────────────────────────────────────────
    "heat_pump": {
        "panel":               "Panel1 (HVAC)",
        "standby_w":           50,
        "power_range":         [500, 4000],
        "typical_duration_min": 20,
        "usage_pattern": (
            "Variable-speed compressor; cycles on/off based on thermostat. "
            "Load increases significantly when outside temp drops below 60°F "
            "and again below 50°F. Los Gatos climate is mild so large sustained "
            "draws are uncommon except winter mornings."
        ),
    },

    # ── Panel2 (H2O) ───────────────────────────────────────────────────
    "water_heater": {
        "panel":               "Panel2 (H2O)",
        "standby_w":           10,
        "power_range":         [800, 4000],
        "typical_duration_min": 20,
        "usage_pattern": (
            "Solar boiler pre-heats; electric element only fires when solar "
            "input is insufficient. Short high-power spikes (~4 kW, 10–20 min) "
            "correspond to showers and dishwasher hot-fill cycles. If no spike "
            "is observed for >4 hours during normal occupancy hours, flag as "
            "possible heater fault or solar bypass issue."
        ),
        "anomaly_note": "No spike for >4 hr during 6am–10pm = anomaly",
    },
    "bathroom_lights_outlets": {
        "panel":               "Panel2 (H2O)",
        "standby_w":           0,
        "power_range":         [60, 800],
        "typical_duration_min": 15,
        "usage_pattern": (
            "Incandescent fixtures contribute a noticeable baseline (~60–200 W). "
            "Hair dryer adds a sharp spike up to 1500 W; usually only one in use "
            "at a time. Outside outlets on this panel: occasional transient loads."
        ),
    },
    "hair_dryer": {
        "panel":               "Panel2 (H2O)",
        "standby_w":           0,
        "power_range":         [1000, 1800],
        "typical_duration_min": 8,
        "usage_pattern": (
            "Sharp spike on Panel2 (H2O), typically morning. Usually only one "
            "dryer running. Short duration, high instantaneous draw."
        ),
    },

    # ── Panel3 (Kitchen) ───────────────────────────────────────────────
    "refrigerator": {
        "panel":               "Panel3 (Kitchen)",
        "standby_w":           5,
        "power_range":         [80, 200],
        "typical_duration_min": 10,
        "usage_pattern": (
            "Periodic compressor cycling, always-on. Creates a low regular "
            "background draw. Multiple refrigerators may be present in the house."
        ),
    },
    "microwave": {
        "panel":               "Panel3 (Kitchen)",
        "standby_w":           3,
        "power_range":         [900, 1600],
        "typical_duration_min": 3,
        "usage_pattern": (
            "Short sharp spike, meal times. Rarely overlaps other high kitchen loads."
        ),
    },
    "dishwasher": {
        "panel":               "Panel3 (Kitchen)",
        "standby_w":           2,
        "power_range":         [200, 1200],
        "typical_duration_min": 90,
        "usage_pattern": (
            "Multi-stage cycle: fill, wash, heat, rinse, dry. Overall power draw "
            "is relatively modest compared to other appliances. Evening use typical. "
            "Hot-fill demand may briefly register on Panel2 water heater."
        ),
    },
    "cooktop": {
        "panel":               "Panel3 (Kitchen)",
        "standby_w":           0,
        "power_range":         [1200, 7200],
        "typical_duration_min": 25,
        "usage_pattern": (
            "High variance — one to four burners, each up to 1800 W. "
            "Meal-time spikes. Load level depends heavily on which burners "
            "are active."
        ),
    },

    # ── Shop panel ─────────────────────────────────────────────────────
    "washer": {
        "panel":               "Shop",
        "standby_w":           1,
        "power_range":         [300, 1500],
        "typical_duration_min": 45,
        "usage_pattern": (
            "Oscillating load, alternates agitation and spin phases. "
            "Moderate power draw, often precedes dryer use."
        ),
    },
    "dryer": {
        "panel":               "Shop",
        "standby_w":           5,
        "power_range":         [5000, 7000],
        "typical_duration_min": 60,
        "usage_pattern": (
            "Sustained high resistive element draw, ~7 kW. Highest single "
            "load in the house aside from heat pump peaks. Usually follows "
            "washer by 45–90 min."
        ),
    },
    "pressure_pump": {
        "panel":               "Shop",
        "standby_w":           0,
        "power_range":         [750, 1500],
        "typical_duration_min": 2,
        "usage_pattern": (
            "Short bursts triggered by water demand. Cycle normally <5 min. "
            "Previously used to detect water leaks: abnormal sustained cycling "
            "outside irrigation hours indicates a leak."
        ),
        "anomaly_note": "Cycling >10 min outside 6am–8pm = possible water leak",
    },

    # ── Whole-house mobile/shared loads ────────────────────────────────
    "vacuum_cleaner": {
        "panel":               "any",
        "standby_w":           0,
        "power_range":         [800, 1200],
        "typical_duration_min": 20,
        "usage_pattern": (
            "~1 kW load that appears on different sub-panels depending on which "
            "room it is used in. Characteristic sustained moderate draw. "
            "Moving load — signature can shift between Panel2, Panel3, or Shop."
        ),
    },
    "computers": {
        "panel":               "any",
        "standby_w":           10,
        "power_range":         [100, 700],
        "typical_duration_min": 240,
        "usage_pattern": (
            "Six to seven computers; flexible, not high power individually. "
            "Collectively 200–700 W sustained during work hours. Low-priority "
            "load for shedding."
        ),
    },
    "tv_stereo": {
        "panel":               "any",
        "standby_w":           15,
        "power_range":         [80, 400],
        "typical_duration_min": 120,
        "usage_pattern": (
            "TV and stereo system pull a constant baseline load. Standby draw "
            "is detectable even outside viewing hours."
        ),
    },
    "incandescent_lights": {
        "panel":               "any",
        "standby_w":           0,
        "power_range":         [60, 600],
        "typical_duration_min": 120,
        "usage_pattern": (
            "Incandescent fixtures in several rooms; semi-large load where "
            "present. Step changes on sunset/sunrise or room entry are "
            "distinguishable in aggregate."
        ),
    },
    "outdoor_sprinklers": {
        "panel":               "Panel2 (H2O)",
        "standby_w":           0,
        "power_range":         [200, 600],
        "typical_duration_min": 30,
        "usage_pattern": (
            "Scheduled irrigation cycles, typically early morning. "
            "Load is pump + solenoid valves."
        ),
    },
}

# Panels that are instrumented with direct eGauge channels:
IEMS_PANELS = [
    "Panel1 (HVAC)",
    "Panel2 (H2O)",
    "Panel3 (Kitchen)",
    "Shop",
    "Grid Power",
    "Generac Power",
]

# Channels whose names contain parentheses — AnyLog WHERE nm= predicate
# silently returns empty for these; always filter client-side:
PAREN_CHANNELS = frozenset({
    "Panel1 (HVAC)",
    "Panel2 (H2O)",
    "Panel3 (Kitchen)",
})
