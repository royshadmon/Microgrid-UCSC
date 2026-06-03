"""Appliance -> physical-panel mapping for nilm_disaggregated routing.

Corrected for the actual eGauge install (no Shop panel exists):
  * Clothes washer, dryer, water pressure pump, garage refrigerator, garage
    freezer and garage openers are all on Panel 3 (Kitchen).
  * Panel 2 (H2O): water heater, hair dryer, sprinklers, and the master-bath
    mirror incandescent lights (~300 W, the only incandescent load).
  * Panel 1 (HVAC): heat pump (incl. ~550 W fan-only sub-state) and the solar
    water-heater pump. These two are mutually exclusive (interlocked).
  * Jacuzzi pump is never used and is intentionally omitted.
  * Vacuum is mobile (changes panels); routed to Panel 3 for storage.
"""

PANEL_TO_MODEL = {
    "Panel1 (HVAC)": {
        "onnx": "services/iems/models/nilm_panel1.onnx",
        "norm": "services/iems/models/panel1_norm_bilstm.json",
        "tag":  "panel1",
    },
    "Panel2 (H2O)": {
        "onnx": "services/iems/models/nilm_panel2.onnx",
        "norm": "services/iems/models/panel2_norm_bilstm.json",
        "tag":  "panel2",
    },
    "Panel3 (Kitchen)": {
        "onnx": "services/iems/models/nilm_panel3.onnx",
        "norm": "services/iems/models/panel3_norm_bilstm.json",
        "tag":  "panel3",
    },
}

APPLIANCE_TO_PANEL = {
    # Panel 1 (HVAC)
    "heat_pump":         "Panel1 (HVAC)",
    "solar_pump":        "Panel1 (HVAC)",
    # Panel 2 (H2O)
    "water_heater":      "Panel2 (H2O)",
    "hair_dryer":        "Panel2 (H2O)",
    "sprinklers":        "Panel2 (H2O)",
    "bath_lights":       "Panel2 (H2O)",
    # Panel 3 (Kitchen) — incl. former "shop" loads and garage loads
    "refrigerator":      "Panel3 (Kitchen)",
    "dishwasher":        "Panel3 (Kitchen)",
    "microwave":         "Panel3 (Kitchen)",
    "dryer":             "Panel3 (Kitchen)",
    "washing_machine":   "Panel3 (Kitchen)",
    "pressure_pump":     "Panel3 (Kitchen)",
    "garage_opener":     "Panel3 (Kitchen)",
    "computers":         "Panel3 (Kitchen)",
    "tv_stereo":         "Panel3 (Kitchen)",
    "vacuum_cleaner":    "Panel3 (Kitchen)",  # mobile
}

# Nominal ON-power (W) used for additive apportionment / DSS dollar estimates.
APPLIANCE_NOMINAL_W = {
    "heat_pump":       3000,
    "solar_pump":       150,
    "water_heater":    3500,
    "hair_dryer":      1500,
    "sprinklers":       200,
    "bath_lights":      200,
    "refrigerator":     150,
    "dishwasher":      1000,
    "microwave":       1200,
    "dryer":           6000,
    "washing_machine":  500,
    "pressure_pump":    750,
    "garage_opener":    400,
    "computers":        300,
    "tv_stereo":        150,
    "vacuum_cleaner":  1000,
}

# Critical loads (must stay powered) and mobile loads, for the DSS layer.
CRITICAL_APPLIANCES = (
    "refrigerator", "pressure_pump", "garage_opener",  # + networking (unmetered)
)
MOBILE_APPLIANCES = ("vacuum_cleaner",)


def appliance_panel(appliance: str) -> str:
    return APPLIANCE_TO_PANEL.get(appliance, "Panel3 (Kitchen)")
