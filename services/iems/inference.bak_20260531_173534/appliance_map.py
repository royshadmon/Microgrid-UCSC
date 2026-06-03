"""
Appliance → physical-panel mapping for nilm_disaggregated routing.

The Panel3 ONNX model is trained on cross-panel features and predicts heads
that physically live on either Panel3 (refrigerator/dishwasher/microwave),
Shop (dryer/washing_machine/pressure_pump), or are diffuse loads with no
single panel (computers/tv_stereo). The `circuit` stored in
nilm_disaggregated is the appliance's physical home, not the model's panel.
"""

PANEL_TO_MODEL = {
    "Panel1 (HVAC)": {
        "onnx": "services/iems/models/nilm_panel1.onnx",
        "norm": "services/iems/models/panel1_norm.json",
        "tag":  "panel1",
    },
    "Panel2 (H2O)": {
        "onnx": "services/iems/models/nilm_panel2.onnx",
        "norm": "services/iems/models/panel2_norm.json",
        "tag":  "panel2",
    },
    "Panel3 (Kitchen)": {
        "onnx": "services/iems/models/nilm_panel3.onnx",
        "norm": "services/iems/models/panel3_norm.json",
        "tag":  "panel3",
    },
}

APPLIANCE_TO_PANEL = {
    "heat_pump":         "Panel1 (HVAC)",
    "solar_pump":        "Panel1 (HVAC)",
    "water_heater":      "Panel2 (H2O)",
    "hair_dryer":        "Panel2 (H2O)",
    "sprinklers":        "Panel2 (H2O)",
    "bath_lights":       "Panel2 (H2O)",
    "refrigerator":      "Panel3 (Kitchen)",
    "dishwasher":        "Panel3 (Kitchen)",
    "microwave":         "Panel3 (Kitchen)",
    "dryer":             "Shop",
    "washing_machine":   "Shop",
    "pressure_pump":     "Shop",
    "computers":         "Panel3 (Kitchen)",
    "tv_stereo":         "Panel3 (Kitchen)",
    "vacuum_cleaner":    "Panel3 (Kitchen)",
}

APPLIANCE_NOMINAL_W = {
    "heat_pump":       3000,
    "solar_pump":       150,
    "water_heater":    3500,
    "hair_dryer":      1500,
    "sprinklers":       200,
    "bath_lights":      120,
    "refrigerator":     150,
    "dishwasher":      1200,
    "microwave":       1500,
    "dryer":           6000,
    "washing_machine":  500,
    "pressure_pump":    750,
    "computers":        180,
    "tv_stereo":        160,
    "vacuum_cleaner":  1100,
}


def appliance_panel(appliance: str) -> str:
    return APPLIANCE_TO_PANEL.get(appliance, "Panel3 (Kitchen)")
