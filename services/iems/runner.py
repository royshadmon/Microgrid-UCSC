"""
IEMS cycle orchestrator — one run = Adabi Figure 5.5 four-domain pass.
run_iems_cycle() is the single function the UI calls.
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from iems.config import LOAD_PANELS, ANYLOG_TABLE_LIVE, DEFAULT_LLM_MODEL
from iems.weather import get_weather, get_weather_history
from iems.load.anylog_query import fetch_all_panels
from iems.load.disaggregator import disaggregate_panel, DisaggregationResult
from iems.inference.onnx_disaggregator import (
    disaggregate_panel_onnx, OnnxPanelResult,
)
from iems.inference.feature_builder import UTIL_CHANNEL
from iems.load.anylog_query import fetch_channel
from iems.load.mobile_load import reconcile_vacuum
from iems.load.anomaly import run_all_anomaly_checks, Alert
from iems.load.shedding import rank_shed_candidates, estimate_shed_savings_dollars
from iems.generation.solar_forecast import get_solar_forecast
from iems.generation.grid_analytics import classify_now, build_daily_rate_strip
from iems.storage.battery_model import get_virtual_soc, update_virtual_soc
from iems.storage.dispatch import get_dispatch_recommendation
from iems.decision_support.rule_tree import tag_action, determine_flow_branch
from iems.decision_support.recommender import build_recommendations

logger = logging.getLogger(__name__)


@dataclass
class IEMSCycleResult:
    load_states: dict[str, int]
    vacuum_active_panel: Optional[str]
    anomalies: list[dict]
    generation: dict
    weather: dict
    storage: dict
    tou: dict
    dss_recommendations: list[dict]
    flow_chart_branch: str
    metadata: dict
    panel_states: dict = field(default_factory=dict)
    rate_strip: list[dict] = field(default_factory=list)


def run_iems_cycle(
    mode: str = "on_grid",
    llm_model: str = DEFAULT_LLM_MODEL,
    llm_backend: str = "ollama",
    nilm_backend: str = "onnx",                  # "onnx" | "ollama"
    window_minutes: int = 10,
    user_prefs: Optional[dict] = None,
) -> IEMSCycleResult:
    start = time.monotonic()
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(minutes=window_minutes)).isoformat()
    window_end = now.isoformat()

    # === USER DOMAIN ===
    prefs = user_prefs or {}

    # === LOAD DOMAIN ===
    weather = get_weather()
    weather_history = get_weather_history(hours=24)

    all_rows = fetch_all_panels(window_start, window_end)
    # ONNX path also needs the utility-tie current channel.
    if nilm_backend == "onnx":
        try:
            all_rows[UTIL_CHANNEL] = fetch_channel(UTIL_CHANNEL, window_start, window_end)
        except Exception as exc:
            logger.warning("utility-tie fetch failed: %s", exc)
            all_rows[UTIL_CHANNEL] = []

    panel_results: dict[str, dict] = {}
    all_states: dict[str, list[int]] = {}
    panel_probabilities: dict[str, dict] = {}
    panel_models: dict[str, str] = {}
    total_corrections = 0
    total_windows = 0

    if nilm_backend == "onnx":
        from iems.inference.appliance_map import PANEL_TO_MODEL
        for panel in PANEL_TO_MODEL.keys():
            try:
                r: OnnxPanelResult = disaggregate_panel_onnx(
                    panel=panel,
                    panel_rows=all_rows,
                    weather=weather,
                    write_to_anylog=True,
                )
                panel_results[panel] = r.states
                all_states.update(r.states)
                panel_probabilities[panel] = r.probabilities
                panel_models[panel] = r.model
                total_windows += 1
            except Exception as exc:
                logger.error("ONNX disaggregation failed for %s: %s", panel, exc)
                panel_results[panel] = {}
    else:
        for panel in LOAD_PANELS:
            rows = all_rows.get(panel, [])
            result: DisaggregationResult = disaggregate_panel(
                panel=panel,
                rows=rows,
                model=llm_model,
                backend=llm_backend,
                weather=weather,
            )
            panel_results[panel] = result.states
            all_states.update(result.states)
            panel_models[panel] = getattr(result, "model", llm_model)
            total_corrections += result.correction_count
            total_windows += result.n_windows

    # Mobile load reconciliation works the same regardless of backend.
    panel_power = {
        panel: [float(r.get("w", 0) or 0) for r in all_rows.get(panel, [])]
        for panel in LOAD_PANELS
    }
    vacuum_timeline, vacuum_panel = reconcile_vacuum(panel_results, panel_power)

    # Collapse list states to latest value for DSS
    current_states = {
        k: (v[-1] if v else 0) for k, v in all_states.items()
    }
    if vacuum_timeline:
        current_states["vacuum_cleaner"] = vacuum_timeline[-1]

    # Anomaly detection
    raw_alerts: list[Alert] = run_all_anomaly_checks(all_states, weather_history)
    anomalies = [
        {
            "severity": a.severity,
            "appliance": a.appliance,
            "message": a.message,
            "evidence": a.evidence,
        }
        for a in raw_alerts
    ]

    # === GENERATION DOMAIN ===
    solar = get_solar_forecast()
    generac_rows = all_rows.get("Generac Power", [])
    generac_w = float(generac_rows[-1].get("w", 0) or 0) if generac_rows else 0.0
    grid_rows = all_rows.get("Grid Power", [])
    grid_w = float(grid_rows[-1].get("w", 0) or 0) if grid_rows else 0.0
    generation_kw = (generac_w + max(0.0, -grid_w)) / 1000

    generation = {
        "solar_w": 0,
        "generac_w": generac_w,
        "grid_w": grid_w,
        "forecast_24h_kwh": solar["forecast_24h_kwh"],
        "irradiance_label": solar["irradiance_label"],
    }

    # === STORAGE DOMAIN ===
    total_load_w = sum(
        float(r.get("w", 0) or 0)
        for panel in LOAD_PANELS
        for r in (all_rows.get(panel, [])[-1:] or [{}])
    )
    soc_snapshot = update_virtual_soc(
        load_kw=total_load_w / 1000,
        generation_kw=generation_kw,
    )
    tou = classify_now(now)
    dispatch = get_dispatch_recommendation(
        mode=mode,
        tou_period=tou["period"],
        load_kw=total_load_w / 1000,
        generation_kw=generation_kw,
        irradiance_label=weather["irradiance_label"],
    )

    storage = {
        "soc_virtual": soc_snapshot,
        "dispatch_recommendation": dispatch,
    }

    # === DECISION SUPPORT ===
    recs = build_recommendations(
        current_states=current_states,
        anomalies=raw_alerts,
        tou_info=tou,
        weather=weather,
        mode=mode,
        user_prefs=prefs,
    )

    flow_branch = determine_flow_branch(
        mode=mode,
        load_kw=total_load_w / 1000,
        generation_kw=generation_kw,
        soc_pct=soc_snapshot["soc_pct"],
    )

    latency_ms = round((time.monotonic() - start) * 1000)

    return IEMSCycleResult(
        load_states=current_states,
        vacuum_active_panel=vacuum_panel,
        anomalies=anomalies,
        generation=generation,
        weather=dict(weather),
        storage=storage,
        tou=tou,
        dss_recommendations=recs,
        flow_chart_branch=flow_branch,
        panel_states=panel_results,
        rate_strip=build_daily_rate_strip(now),
        metadata={
            "model": llm_model,
            "backend": llm_backend,
            "nilm_backend": nilm_backend,
            "panel_models": panel_models,
            "panel_probabilities": panel_probabilities,
            "n_windows": total_windows,
            "llm_correction_count": total_corrections,
            "latency_ms": latency_ms,
            "window_minutes": window_minutes,
            "cycle_ts": now.isoformat(),
        },
    )
