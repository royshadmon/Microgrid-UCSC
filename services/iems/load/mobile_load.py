"""
Cross-panel vacuum cleaner reconciliation (Adabi thesis observation: vacuum
moves panel-to-panel). Each panel's disaggregator may emit vacuum_cleaner_status
independently. This module resolves conflicts into a single global timeline.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

VACUUM_FIELD = "vacuum_cleaner_status"


def reconcile_vacuum(
    panel_results: dict[str, dict[str, list[int]]],
    panel_power: dict[str, list[float]],
) -> tuple[list[int], Optional[str]]:
    """
    panel_results: {panel_name: {field: [0/1, ...]}}
    panel_power:   {panel_name: [watt_values]}

    Returns (global_vacuum_timeline, active_panel_name_or_None).
    Active panel is whichever panel had the largest unattributed residual
    when multiple panels claimed vacuum simultaneously.
    """
    panels = list(panel_results.keys())
    if not panels:
        return [], None

    # Find length from first available vacuum field
    timeline_len = 0
    for p in panels:
        v = panel_results[p].get(VACUUM_FIELD, [])
        if v:
            timeline_len = len(v)
            break
    if timeline_len == 0:
        return [], None

    global_timeline = [0] * timeline_len
    active_panel_name: Optional[str] = None

    for t in range(timeline_len):
        claiming_panels = [
            p for p in panels
            if t < len(panel_results[p].get(VACUUM_FIELD, [])) and
            panel_results[p][VACUUM_FIELD][t] == 1
        ]

        if not claiming_panels:
            continue

        if len(claiming_panels) == 1:
            global_timeline[t] = 1
            active_panel_name = claiming_panels[0]
        else:
            # Multiple panels claim vacuum: pick the one with the largest
            # unattributed residual at time t
            best_panel = _pick_highest_residual(claiming_panels, panel_power, t)
            global_timeline[t] = 1
            active_panel_name = best_panel
            for p in claiming_panels:
                if p != best_panel:
                    panel_results[p][VACUUM_FIELD][t] = 0
            logger.debug(
                "vacuum conflict at t=%d: panels %s → resolved to %s",
                t, claiming_panels, best_panel,
            )

    return global_timeline, active_panel_name


def _pick_highest_residual(
    panels: list[str],
    panel_power: dict[str, list[float]],
    t: int,
) -> str:
    best = panels[0]
    best_w = 0.0
    for p in panels:
        pw = panel_power.get(p, [])
        w = pw[t] if t < len(pw) else 0.0
        if w > best_w:
            best_w = w
            best = p
    return best


def build_vacuum_records(
    global_timeline: list[int],
    timestamps: list[str],
    active_panel: Optional[str],
    model: str,
) -> list[dict]:
    return [
        {
            "ts": timestamps[i] if i < len(timestamps) else "",
            "appliance": "vacuum_cleaner",
            "state": global_timeline[i],
            "panel": active_panel or "MOBILE",
            "confidence": 0.8,
            "model": model,
        }
        for i in range(len(global_timeline))
        if global_timeline[i] == 1
    ]
