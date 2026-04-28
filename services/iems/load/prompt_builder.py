"""
Per-panel prompt builder for LLM4NILM (Xue et al. 2025).
Three extensions over the paper:
  1. Per-panel prompts — only the appliances mapped to that panel.
  2. Weather context injected for weather_coupled appliances.
  3. Mobile load (vacuum cleaner) catch field on every panel.
"""
import json
import os
from pathlib import Path
from typing import Optional

from iems.config import CHANNELS, APPLIANCES, NILM_CONTEXT_LENGTH, HOUSE_PROFILE

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Output field name for the mobile vacuum catch slot on every panel
VACUUM_CATCH_FIELD = "vacuum_cleaner_status"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if path.exists():
        return path.read_text()
    return ""


def build_system_prompt(panel: str, weather: Optional[dict] = None) -> str:
    base = _load_prompt("base_role.txt")
    disagg = _load_prompt("load_disaggregation.txt")

    panel_cfg = CHANNELS.get(panel, {})
    panel_appliances = panel_cfg.get("appliances", [])
    notes = panel_cfg.get("notes", "")

    app_descriptions = []
    weather_context = ""

    for name in panel_appliances:
        app = APPLIANCES.get(name)
        if not app:
            continue
        lo, hi = app["power_range_w"]
        desc = (
            f"- {name}: {lo}-{hi} W typical, threshold={app['on_threshold_w']} W. "
            f"{app['usage_pattern']}"
        )
        if app.get("co_occurs_with"):
            desc += f" Co-occurs with: {', '.join(app['co_occurs_with'])}."
        app_descriptions.append(desc)

        if weather and app.get("weather_coupled"):
            if name == "heat_pump" and weather:
                temp_f = weather.get("outside_temp_f", 60)
                thresholds = HOUSE_PROFILE["weather_thresholds"]
                if temp_f < thresholds["heat_pump_hard_demand_below_f"]:
                    demand = "HIGH (cold weather)"
                elif temp_f > thresholds["heat_pump_idle_above_f"]:
                    demand = "LOW (mild weather)"
                else:
                    demand = "MODERATE"
                weather_context += (
                    f"\nOutside temperature: {temp_f}°F. "
                    f"Heat pump expected demand: {demand}."
                )
            if name == "water_heater" and weather:
                irr = weather.get("irradiance_label", "moderate")
                temp_f = weather.get("outside_temp_f", 60)
                solar_note = (
                    "Solar boiler likely preheated the tank — electric draw expected MINIMAL."
                    if irr == "high"
                    else (
                        "Cloudy/cold conditions — solar boiler contribution low, "
                        "electric draw expected ELEVATED."
                        if irr == "low" and temp_f < 55
                        else "Mixed conditions — moderate electric draw possible."
                    )
                )
                weather_context += (
                    f"\nSolar irradiance (last 6h): {irr}. "
                    f"Water heater solar-boiler note: {solar_note}"
                )

    output_schema = _build_output_schema(panel_appliances)

    mobile_note = (
        "\nVACUUM CLEANER (~1 kW universal-motor signature) may appear on any panel "
        "briefly. If you see an unattributed ~1 kW step lasting 10-30 min that does "
        "not fit this panel's appliance profile, output it via the dedicated "
        f"'{VACUUM_CATCH_FIELD}' field."
    )

    prompt = (
        f"{base}\n\n"
        f"## Panel: {panel}\n"
        f"You are disaggregating the aggregate power signal for panel '{panel}'.\n"
    )
    if notes:
        prompt += f"Panel notes: {notes}\n"
    prompt += (
        f"\n## Appliances on this panel:\n"
        + "\n".join(app_descriptions)
        + weather_context
        + mobile_note
        + f"\n\n{disagg}\n\n"
        + f"## Output JSON schema:\n{json.dumps(output_schema, indent=2)}\n"
        + "\nOutput ONLY valid JSON matching this schema. No markdown fences."
    )
    return prompt


def build_user_message(
    panel: str,
    power_sequence: list[float],
    context_history: Optional[list[list[float]]] = None,
    window_idx: int = 0,
) -> str:
    window_str = ", ".join(str(round(w, 1)) for w in power_sequence)
    msg = (
        f"Window {window_idx}: aggregate power (W) at 6-second intervals:\n"
        f"[{window_str}]\n"
        f"Length: {len(power_sequence)} samples.\n"
    )
    if context_history:
        flat = [w for seq in context_history[-NILM_CONTEXT_LENGTH:] for w in seq]
        ctx_str = ", ".join(str(round(w, 1)) for w in flat[-NILM_CONTEXT_LENGTH:])
        msg += f"Recent context (last {NILM_CONTEXT_LENGTH} readings): [{ctx_str}]\n"
    msg += "Disaggregate and return JSON."
    return msg


def _build_output_schema(appliances: list[str]) -> dict:
    schema = {}
    for name in appliances:
        schema[f"{name}_status"] = [0, 1, "..."]
    schema[VACUUM_CATCH_FIELD] = [0, 1, "..."]
    schema["explanation"] = "Brief rationale for non-trivial state changes."
    return schema


def get_panel_output_fields(panel: str) -> list[str]:
    panel_cfg = CHANNELS.get(panel, {})
    fields = [f"{a}_status" for a in panel_cfg.get("appliances", [])]
    fields.append(VACUUM_CATCH_FIELD)
    return fields


def build_disaggregation_prompt(
    panel_name: str,
    power_sequence: list[float],
    window_size: int = 100,
    context_states: Optional[list[list[float]]] = None,
    context_length: int = 30,
    weather_ctx: Optional[dict] = None,
    window_idx: int = 0,
) -> list[dict]:
    """
    Build the OpenAI-style chat message list for one disaggregation window.
    Returns [{"role": "system", "content": ...}, {"role": "user", "content": ...}].
    Per LLM4NILM Section 5.4 — per-panel system prompt + window user message.
    """
    seq = list(power_sequence[:window_size]) if window_size else list(power_sequence)
    system_content = build_system_prompt(panel_name, weather=weather_ctx)
    user_content = build_user_message(
        panel=panel_name,
        power_sequence=seq,
        context_history=context_states,
        window_idx=window_idx,
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_content},
    ]
