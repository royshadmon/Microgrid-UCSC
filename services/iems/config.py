"""
House-specific configuration for eGauge18646 residential microgrid.
Channel names are non-negotiable — they match egauge_kafka exactly.
"""

CHANNELS = {
    "Grid Power":       {"role": "main_signed", "signed": True},
    "Generac Power":    {"role": "fossil_backup"},
    "Panel1 (HVAC)":    {"role": "subpanel", "appliances": ["heat_pump"]},
    "Panel2 (H2O)":     {
        "role": "subpanel",
        "appliances": ["water_heater", "hair_drier", "sprinklers", "bathroom_outlets"],
        "notes": "WH preheated by solar boiler. Bathroom outlets included → hair drier lands here.",
    },
    "Panel3 (Kitchen)": {
        "role": "subpanel",
        "appliances": ["refrigerator", "dishwasher", "microwave", "cooktop", "kitchen_lights"],
    },
    "Shop": {
        "role": "subpanel",
        "appliances": ["dryer", "washing_machine", "pressure_pump", "shop_tools"],
    },
    "VrmsA": {"role": "diagnostic_voltage"},
    "VrmsB": {"role": "diagnostic_voltage"},
}

# Panels that carry load (exclude diagnostic channels)
LOAD_PANELS = ["Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)", "Shop"]

APPLIANCES = {
    # === SHED PRIORITY 1: Auto-controlled big loads ===
    "heat_pump": {
        "panel": "Panel1 (HVAC)",
        "laxity": "auto_controlled",
        "shed_priority": 1,
        "on_threshold_w": 300,
        "power_range_w": (1500, 4000),
        "avg_on_duration_min": 15,
        "typical_cycle_min": 30,
        "usage_pattern": (
            "Thermostat-driven; runs hard below 50°F outside, "
            "idle above 60°F. Reverse-cycle for cooling in summer."
        ),
        "weather_coupled": True,
        "user_visible_label": "Heat Pump (HVAC)",
    },
    "water_heater": {
        "panel": "Panel2 (H2O)",
        "laxity": "auto_controlled",
        "shed_priority": 2,
        "on_threshold_w": 500,
        "power_range_w": (2000, 4000),
        "avg_on_duration_min": 8,
        "typical_cycle_min": 0,
        "usage_pattern": (
            "Short 2-4 kW bursts on hot-water demand. "
            "Preheated by SOLAR BOILER — fires more on cloudy/cold days, "
            "RARELY on sunny days. Expect long quiet stretches in good weather; "
            "flag dormancy ONLY if sustained AND cold."
        ),
        "solar_boiler_coupled": True,
        "weather_coupled": True,
        "thermal_dump_target": True,
        "user_visible_label": "Water Heater",
    },
    "dryer": {
        "panel": "Shop",
        "laxity": "user_controlled_interval",
        "shed_priority": 1,
        "on_threshold_w": 1000,
        "power_range_w": (4000, 7000),
        "avg_on_duration_min": 60,
        "typical_cycle_min": 60,
        "usage_pattern": (
            "Sustained ~7 kW with motor cycling. Largest single load "
            "in the house — shedding/deferring gives the biggest dollar "
            "saving in TOU peak."
        ),
        "deferrable": True,
        "user_visible_label": "Clothes Dryer",
    },

    # === SHED PRIORITY 3: Smaller deferrable cycles ===
    "washing_machine": {
        "panel": "Shop",
        "laxity": "user_controlled_interval",
        "shed_priority": 3,
        "on_threshold_w": 50,
        "power_range_w": (200, 2000),
        "avg_on_duration_min": 45,
        "typical_cycle_min": 60,
        "usage_pattern": (
            "Oscillating phases, mostly low draw with brief "
            "high-draw heater/spin spikes. Modest total energy."
        ),
        "deferrable": True,
        "user_visible_label": "Washing Machine",
    },
    "dishwasher": {
        "panel": "Panel3 (Kitchen)",
        "laxity": "user_controlled_interval",
        "shed_priority": 3,
        "on_threshold_w": 50,
        "power_range_w": (200, 1800),
        "avg_on_duration_min": 75,
        "typical_cycle_min": 90,
        "usage_pattern": "Multi-stage but modest peak — not a primary shed target.",
        "deferrable": True,
        "user_visible_label": "Dishwasher",
    },

    # === NON-DEFERRABLE / IMMEDIATE-USE ===
    "microwave": {
        "panel": "Panel3 (Kitchen)",
        "laxity": "user_controlled_non_interval",
        "shed_priority": 4,
        "on_threshold_w": 200,
        "power_range_w": (900, 1500),
        "avg_on_duration_min": 3,
        "typical_cycle_min": 3,
        "usage_pattern": "Short 1-3 min bursts, very characteristic spike.",
        "deferrable": False,
        "user_visible_label": "Microwave",
    },
    "hair_drier": {
        "panel": "Panel2 (H2O)",
        "laxity": "user_controlled_non_interval",
        "shed_priority": 4,
        "on_threshold_w": 800,
        "power_range_w": (1200, 1800),
        "avg_on_duration_min": 5,
        "typical_cycle_min": 5,
        "usage_pattern": (
            "1-2 short morning/evening events. CO-OCCURS on H2O panel with "
            "water heater — disambiguate via duration "
            "(hair drier ~5 min steady, WH ~3-8 min ramp)."
        ),
        "deferrable": False,
        "co_occurs_with": ["water_heater"],
        "user_visible_label": "Hair Drier",
    },

    # === MONITORING TARGETS (tracked for anomalies) ===
    "pressure_pump": {
        "panel": "Shop",
        "laxity": "uninterruptible",
        "shed_priority": 999,
        "on_threshold_w": 200,
        "power_range_w": (500, 1000),
        "avg_on_duration_min": 1,
        "typical_cycle_min": 30,
        "usage_pattern": (
            "Brief cycles on water demand. INCREASED CYCLING FREQUENCY "
            "= leak signal (proven use case at this site)."
        ),
        "anomaly_target": True,
        "user_visible_label": "Pressure Pump",
    },
    "refrigerator": {
        "panel": "Panel3 (Kitchen)",
        "laxity": "uninterruptible",
        "shed_priority": 999,
        "on_threshold_w": 50,
        "power_range_w": (80, 200),
        "avg_on_duration_min": 12,
        "typical_cycle_min": 30,
        "usage_pattern": "Continuous compressor cycling — always present.",
        "critical": True,
        "user_visible_label": "Refrigerator",
    },

    # === MOBILE LOAD ===
    "vacuum_cleaner": {
        "panel": "MOBILE",
        "laxity": "user_controlled_non_interval",
        "shed_priority": 4,
        "on_threshold_w": 600,
        "power_range_w": (800, 1200),
        "avg_on_duration_min": 15,
        "typical_cycle_min": 15,
        "usage_pattern": (
            "Universal-motor signature — rises ~1 kW above panel baseline. "
            "APPEARS ON DIFFERENT PANELS at different times depending on "
            "which outlet it's plugged into. Match by signature, not by panel."
        ),
        "mobile": True,
        "user_visible_label": "Vacuum Cleaner",
    },

    # === CONTINUOUS BASELINE ===
    "computers_aggregate": {
        "panel": "Panel3 (Kitchen)",
        "laxity": "user_controlled_non_interval",
        "shed_priority": 4,
        "on_threshold_w": 100,
        "power_range_w": (200, 500),
        "avg_on_duration_min": 480,
        "typical_cycle_min": 480,
        "usage_pattern": (
            "Aggregate of 6-7 computers — flat-ish baseline 200-500 W. "
            "Individually flexible, dispatchable for compute-shifting."
        ),
        "user_visible_label": "Computers (6-7)",
    },
    "tv_stereo": {
        "panel": "Panel3 (Kitchen)",
        "laxity": "user_controlled_non_interval",
        "shed_priority": 4,
        "on_threshold_w": 80,
        "power_range_w": (100, 200),
        "avg_on_duration_min": 180,
        "typical_cycle_min": 180,
        "usage_pattern": "Flat ~150 W when on, often for hours.",
        "user_visible_label": "TV / Stereo",
    },
    "incandescent_lights": {
        "panel": "MULTIPLE",
        "laxity": "user_controlled_non_interval",
        "shed_priority": 4,
        "on_threshold_w": 80,
        "power_range_w": (100, 300),
        "avg_on_duration_min": 60,
        "typical_cycle_min": 60,
        "usage_pattern": (
            "A few large incandescent fixtures — step-on/step-off ~100-300 W "
            "resistive. LED fixtures below noise floor, ignore."
        ),
        "user_visible_label": "Incandescent Lights",
    },
    "sprinklers": {
        "panel": "Panel2 (H2O)",
        "laxity": "auto_controlled",
        "shed_priority": 3,
        "on_threshold_w": 50,
        "power_range_w": (100, 300),
        "avg_on_duration_min": 30,
        "typical_cycle_min": 30,
        "usage_pattern": (
            "Scheduled outdoor sprinkler controller on H2O panel via "
            "outdoor outlets. Schedulable, deferrable in island mode."
        ),
        "deferrable": True,
        "user_visible_label": "Sprinklers",
    },
}

# Appliances that must NEVER be shed
CRITICAL_APPLIANCES = {"refrigerator", "pressure_pump", "networking"}

# Appliances that are mobile (panel-agnostic signature matching)
MOBILE_APPLIANCES = {"vacuum_cleaner"}

# PG&E E6 TOU rates (Adabi 5.4.1)
TOU_RATES = {
    "summer": {
        "peak":         {"hours": [(13, 19)], "days": "weekdays", "rate": 0.51},
        "partial_peak": {"hours": [(10, 13), (19, 21)], "days": "weekdays", "rate": 0.30},
        "weekend":      {"hours": [(17, 20)], "days": "weekends", "rate": 0.30},
        "off_peak":     {"hours": [], "days": "all", "rate": 0.18},
    },
    "winter": {
        "peak":         {"hours": [(13, 19)], "days": "weekdays", "rate": 0.30},
        "partial_peak": {"hours": [(10, 13), (19, 21)], "days": "weekdays", "rate": 0.20},
        "off_peak":     {"hours": [], "days": "all", "rate": 0.16},
    },
}

HOUSE_PROFILE = {
    "has_solar_thermal_boiler": True,
    "has_solar_pv": False,
    "has_battery_storage": False,
    "has_backup_generator": True,
    "outside_temp_source": "open_meteo",
    "location": {
        "city": "Los Gatos",
        "state": "California",
        "country": "US",
        "lat": 37.2358,
        "lon": -121.9624,
        "timezone": "America/Los_Angeles",
    },
    "weather_thresholds": {
        "heat_pump_hard_demand_below_f": 50,
        "heat_pump_idle_above_f": 60,
        "water_heater_extra_usage_below_f": 50,
    },
}

# LLM4NILM paper empirical optimum (Section 5.4)
NILM_CONTEXT_LENGTH = 30
NILM_WINDOW_SIZE = 100

# AnyLog connection
# AnyLog connection — single source of truth
ANYLOG_REST_URL = "http://127.0.0.1:32149"
ANYLOG_USER_AGENT = "AnyLog/1.23"
ANYLOG_DBMS = "customers"
ANYLOG_TABLE_LIVE = "egauge_kafka"
ANYLOG_TABLE_NILM = "nilm_disaggregated"

# House coordinates (Los Gatos, CA) — overrides stale AnyLog operator policy
HOUSE_LAT = 37.2358
HOUSE_LON = -121.9624
HOUSE_TZ = "America/Los_Angeles"

# Ollama defaults
DEFAULT_LLM_MODEL = "mistral:7b"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
LLAMA_CPP_BASE_URL = "http://127.0.0.1:8080"
SMALL_MODEL_WARNING_THRESHOLD_B = 7
