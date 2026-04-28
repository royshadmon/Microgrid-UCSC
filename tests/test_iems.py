"""
IEMS test suite — all 12 required cases must pass.
Run from ~/microgrid-manager/:
  PYTHONPATH=services pytest tests/ -v
"""
import sys
import os

# Allow importing iems.* directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Config tests
# ─────────────────────────────────────────────────────────────────────────────

def test_no_ev_charger_anywhere():
    from iems.config import APPLIANCES, CHANNELS
    all_names = list(APPLIANCES.keys())
    for name in all_names:
        assert "ev" not in name.lower(), f"EV charger found in APPLIANCES: {name}"
        assert "charger" not in name.lower(), f"EV charger found in APPLIANCES: {name}"
    for panel, cfg in CHANNELS.items():
        for app in cfg.get("appliances", []):
            assert "ev" not in app.lower(), f"EV charger found in channel {panel}: {app}"
            assert "charger" not in app.lower(), f"EV charger found in channel {panel}: {app}"


def test_dryer_ranked_first_in_shed_priority():
    from iems.config import APPLIANCES
    dryer = APPLIANCES["dryer"]
    # dryer must have shed_priority=1 and highest power
    assert dryer["shed_priority"] == 1, "Dryer must be shed_priority=1"
    assert dryer["power_range_w"][1] >= 7000, "Dryer peak must be >= 7000 W"
    # No other deferrable appliance should outrank dryer
    for name, app in APPLIANCES.items():
        if name == "dryer":
            continue
        if app.get("deferrable") and app.get("shed_priority", 999) < 999:
            assert app["shed_priority"] >= dryer["shed_priority"], (
                f"{name} has higher shed priority than dryer"
            )


def test_refrigerator_pump_networking_never_shed():
    from iems.config import CRITICAL_APPLIANCES
    assert "refrigerator" in CRITICAL_APPLIANCES
    assert "pressure_pump" in CRITICAL_APPLIANCES

    from iems.load.shedding import rank_shed_candidates
    # All critical appliances are ON — they must not appear in shed plan
    states = {name: 1 for name in ["refrigerator", "pressure_pump", "dryer"]}
    plan = rank_shed_candidates(states, target_reduction_w=10000)
    shed_names = [c.appliance for c in plan.candidates]
    assert "refrigerator" not in shed_names, "refrigerator must never be shed"
    assert "pressure_pump" not in shed_names, "pressure_pump must never be shed"


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder tests
# ─────────────────────────────────────────────────────────────────────────────

def test_panel2_prompt_lists_water_heater_AND_hair_drier_AND_sprinklers():
    from iems.load.prompt_builder import build_system_prompt
    prompt = build_system_prompt("Panel2 (H2O)")
    assert "water_heater" in prompt
    assert "hair_drier" in prompt
    assert "sprinklers" in prompt


def test_solar_boiler_note_present_in_water_heater_prompt():
    from iems.load.prompt_builder import build_system_prompt
    prompt = build_system_prompt("Panel2 (H2O)")
    assert "solar" in prompt.lower() or "boiler" in prompt.lower(), (
        "Solar boiler note missing from Panel2 prompt"
    )


def test_weather_context_injected_when_panel1_or_panel2():
    from iems.load.prompt_builder import build_system_prompt
    weather = {"outside_temp_f": 42.0, "irradiance_label": "low", "irradiance_6h_avg": 50.0}
    prompt1 = build_system_prompt("Panel1 (HVAC)", weather=weather)
    assert "42" in prompt1 or "temperature" in prompt1.lower(), (
        "Weather context not injected for Panel1"
    )
    prompt2 = build_system_prompt("Panel2 (H2O)", weather=weather)
    assert "solar" in prompt2.lower() or "boiler" in prompt2.lower(), (
        "Solar/boiler note missing from Panel2 with weather context"
    )


def test_vacuum_cleaner_field_present_in_every_panel_output_schema():
    from iems.load.prompt_builder import build_system_prompt, VACUUM_CATCH_FIELD
    from iems.config import LOAD_PANELS
    for panel in LOAD_PANELS:
        prompt = build_system_prompt(panel)
        assert VACUUM_CATCH_FIELD in prompt, (
            f"vacuum_cleaner_status field missing from {panel} prompt"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly detection tests
# ─────────────────────────────────────────────────────────────────────────────

def test_pump_anomaly_fires_above_2x_baseline_cycles():
    from iems.load.anomaly import detect_pump_anomaly
    # 3600 samples = 6 hours at 6s intervals
    # At baseline = 2 cycles/hr * 6h = 12 cycles, threshold = 2x → fires at > 24 cycles
    # Create 50 ON→OFF transitions (50 cycles) in 3600 samples
    states = []
    for i in range(3600):
        # cycle every 72 samples ≈ 7.2 min → ~50 cycles in 6h
        states.append(1 if (i % 72) < 36 else 0)

    alert = detect_pump_anomaly(
        {"pressure_pump_status": states},
        baseline_cycles_per_hour=2.0,
        threshold=2.0,
    )
    assert alert is not None, "Pump anomaly should fire at >2x baseline"
    assert alert.appliance == "pressure_pump"
    assert alert.evidence["cycles_per_hour"] > 4.0


def test_water_heater_dormancy_only_fires_when_cold_AND_low_irradiance():
    from iems.load.anomaly import detect_water_heater_dormancy

    dormant_states = {"water_heater_status": [0] * 100}

    # Cold + low irradiance → should fire
    cold_dark = [{"temp_f": 40.0, "irradiance": 50.0}] * 24
    alert = detect_water_heater_dormancy(dormant_states, cold_dark)
    assert alert is not None, "Should alert when cold and low irradiance"

    # Cold + HIGH irradiance → solar boiler covers it, do NOT alert
    cold_sunny = [{"temp_f": 40.0, "irradiance": 600.0}] * 24
    no_alert = detect_water_heater_dormancy(dormant_states, cold_sunny)
    assert no_alert is None, "Must NOT alert when sunny — solar boiler explains silence"

    # Warm + low irradiance → also should not alert (warm = no WH needed)
    warm_dark = [{"temp_f": 70.0, "irradiance": 50.0}] * 24
    no_alert2 = detect_water_heater_dormancy(dormant_states, warm_dark)
    assert no_alert2 is None, "Must NOT alert when warm — WH not expected to fire"


# ─────────────────────────────────────────────────────────────────────────────
# Output normalizer tests
# ─────────────────────────────────────────────────────────────────────────────

def test_output_normalizer_handles_malformed_json():
    from iems.load.output_normalizer import normalize
    result = normalize(
        "this is not json at all !!!",
        expected_fields=["heat_pump_status"],
        window_size=10,
        panel="Panel1 (HVAC)",
        window_idx=0,
    )
    assert result["heat_pump_status"] == [0] * 10


def test_output_normalizer_pads_short_output():
    import json
    from iems.load.output_normalizer import normalize
    raw = json.dumps({"heat_pump_status": [1, 1, 1]})
    result = normalize(raw, ["heat_pump_status"], window_size=10)
    assert len(result["heat_pump_status"]) == 10
    assert result["heat_pump_status"][:3] == [1, 1, 1]
    assert result["heat_pump_status"][3] == 1  # forward-padded with last value


# ─────────────────────────────────────────────────────────────────────────────
# Grid analytics / TOU tests
# ─────────────────────────────────────────────────────────────────────────────

def test_tou_classify_peak_summer_weekday():
    from datetime import datetime, timezone
    from iems.generation.grid_analytics import classify_now
    # Tuesday 14:00 UTC in July → summer peak (13-19)
    ts = datetime(2026, 7, 14, 14, 0, 0, tzinfo=timezone.utc)
    result = classify_now(ts)
    assert result["period"] == "peak"
    assert result["season"] == "summer"


def test_tou_classify_off_peak_winter_weekend():
    from datetime import datetime, timezone
    from iems.generation.grid_analytics import classify_now
    ts = datetime(2026, 1, 10, 3, 0, 0, tzinfo=timezone.utc)  # Saturday 3 AM
    result = classify_now(ts)
    assert result["period"] == "off_peak"
    assert result["season"] == "winter"


# ─────────────────────────────────────────────────────────────────────────────
# Plugin / integration smoke tests (offline)
# ─────────────────────────────────────────────────────────────────────────────

def test_iems_cycle_returns_all_four_domain_blocks():
    """Verify IEMSCycleResult has all four Adabi domain fields."""
    from iems.runner import IEMSCycleResult
    import dataclasses
    fields = {f.name for f in dataclasses.fields(IEMSCycleResult)}
    # Load domain
    assert "load_states" in fields
    assert "anomalies" in fields
    # Generation domain
    assert "generation" in fields
    assert "weather" in fields
    # Storage domain
    assert "storage" in fields
    # Decision support
    assert "dss_recommendations" in fields
    assert "flow_chart_branch" in fields


def test_remote_gui_feature_registers_in_nav():
    """iems must be in plugin_order.json and feature_config.json."""
    import json
    from pathlib import Path
    base = Path(__file__).parent.parent / "services" / "remote-gui" / "CLI" / "local-cli-backend"

    order = json.loads((base / "plugins" / "plugin_order.json").read_text())
    assert "iems" in order["plugin_order"], "iems not in plugin_order.json"

    config = json.loads((base / "feature_config.json").read_text())
    assert "iems" in config["plugins"], "iems not in feature_config.json plugins"
    assert config["plugins"]["iems"]["enabled"] is True


def test_ollama_model_list_proxy():
    """Verify list_ollama_models returns a list (even if empty on offline host)."""
    from iems.load.llm_client import list_ollama_models
    result = list_ollama_models(base_url="http://localhost:11434")
    # Should return a list (may be empty if Ollama not running in CI)
    assert isinstance(result, list)


def test_mobile_vacuum_reconciliation_resolves_conflict():
    """When two panels claim vacuum, the one with higher residual wins."""
    from iems.load.mobile_load import reconcile_vacuum

    panel_results = {
        "Panel2 (H2O)": {"vacuum_cleaner_status": [1, 1, 0]},
        "Shop": {"vacuum_cleaner_status": [1, 1, 0]},
    }
    panel_power = {
        "Panel2 (H2O)": [900.0, 950.0, 0.0],
        "Shop": [1200.0, 1100.0, 0.0],  # Shop has higher residual
    }
    timeline, active_panel = reconcile_vacuum(panel_results, panel_power)
    assert timeline[0] == 1
    assert active_panel == "Shop"  # higher wattage wins
    # Panel2 vacuum_cleaner_status[0] should be zeroed out
    assert panel_results["Panel2 (H2O)"]["vacuum_cleaner_status"][0] == 0
