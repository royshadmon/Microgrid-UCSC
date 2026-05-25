"""
ONNX-based NILM inference path.

Trained per-panel models live in services/iems/models/nilm_panel{1,2,3}.onnx
with matching panel{N}_norm.json describing features, mean/std, window/mid,
heads and per-head thresholds.
"""
from iems.inference.onnx_disaggregator import (
    disaggregate_panel_onnx,
    OnnxPanelResult,
    load_all_panel_sessions,
)
from iems.inference.feature_builder import build_panel_window
from iems.inference.appliance_map import (
    APPLIANCE_TO_PANEL,
    APPLIANCE_NOMINAL_W,
    PANEL_TO_MODEL,
    appliance_panel,
)

__all__ = [
    "disaggregate_panel_onnx",
    "OnnxPanelResult",
    "load_all_panel_sessions",
    "build_panel_window",
    "APPLIANCE_TO_PANEL",
    "APPLIANCE_NOMINAL_W",
    "PANEL_TO_MODEL",
    "appliance_panel",
]
