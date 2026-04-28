"""
LLM4NILM per-panel pipeline (Xue et al. 2025, arXiv:2505.06330).
Runs LLM disaggregation across sliding windows for a single panel.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from iems.config import NILM_WINDOW_SIZE, NILM_CONTEXT_LENGTH
from iems.load.anylog_query import (
    resample_to_6s, build_nilm_predictions, insert_predictions,
)
from iems.load.prompt_builder import (
    build_system_prompt,
    build_user_message,
    get_panel_output_fields,
)
from iems.load.llm_client import call_ollama, call_llama_cpp
from iems.load.output_normalizer import normalize

logger = logging.getLogger(__name__)


@dataclass
class DisaggregationResult:
    panel: str
    states: dict[str, list[int]]
    correction_count: int
    n_windows: int
    latency_ms: int
    model: str
    explanation_snippets: list[str] = field(default_factory=list)


def disaggregate_panel(
    panel: str,
    rows: list[dict],
    model: str = "mistral:7b",
    backend: str = "ollama",
    weather: Optional[dict] = None,
) -> DisaggregationResult:
    start = time.monotonic()

    samples = resample_to_6s(rows)
    power_values = [float(r.get("w", 0) or 0) for r in samples]

    if not power_values:
        logger.warning("disaggregate_panel(%s): no data", panel)
        return _empty_result(panel, model)

    expected_fields = get_panel_output_fields(panel)
    system_prompt = build_system_prompt(panel, weather)
    system_msg = {"role": "system", "content": system_prompt}

    n_windows = max(1, len(power_values) // NILM_WINDOW_SIZE)
    all_states: dict[str, list[int]] = {f: [] for f in expected_fields}
    correction_count = 0
    explanations = []

    context_history: list[list[float]] = []

    for i in range(n_windows):
        start_idx = i * NILM_WINDOW_SIZE
        window = power_values[start_idx: start_idx + NILM_WINDOW_SIZE]
        if len(window) < NILM_WINDOW_SIZE:
            window = window + [window[-1] if window else 0.0] * (NILM_WINDOW_SIZE - len(window))

        user_msg = build_user_message(panel, window, context_history, window_idx=i)
        messages = [system_msg, {"role": "user", "content": user_msg}]

        raw = _call_llm(messages, model, backend)
        normalized = normalize(
            raw,
            expected_fields=expected_fields,
            window_size=NILM_WINDOW_SIZE,
            panel=panel,
            window_idx=i,
        )

        for f in expected_fields:
            all_states[f].extend(normalized[f])

        explanation = _extract_explanation(raw)
        if explanation:
            explanations.append(f"Window {i}: {explanation}")

        prev_raw = _try_parse_explanation(raw)
        if prev_raw is None:
            correction_count += 1

        context_history.append(window)
        if len(context_history) > NILM_CONTEXT_LENGTH:
            context_history.pop(0)

    # Writeback to nilm_disaggregated. Best-effort — failures must not
    # block the API response.
    try:
        used = n_windows * NILM_WINDOW_SIZE
        timestamps = [str(s.get("ts", "")) for s in samples[:used]]
        if timestamps:
            records = build_nilm_predictions(
                panel=panel,
                appliance_states=all_states,
                timestamps=timestamps,
                power_values=power_values[:used],
                window_start=timestamps[0],
                window_end=timestamps[-1],
                model=model,
            )
            insert_predictions(records)
    except Exception as exc:
        logger.warning("nilm_disaggregated writeback failed: %s", exc)

    latency_ms = round((time.monotonic() - start) * 1000)
    return DisaggregationResult(
        panel=panel,
        states=all_states,
        correction_count=correction_count,
        n_windows=n_windows,
        latency_ms=latency_ms,
        model=model,
        explanation_snippets=explanations[:5],
    )


def _call_llm(messages: list[dict], model: str, backend: str) -> str:
    try:
        if backend == "llama_cpp":
            return call_llama_cpp(messages, model=model)
        return call_ollama(messages, model=model)
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return "{}"


def _extract_explanation(raw: str) -> str:
    import json, re
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.MULTILINE)
        data = json.loads(cleaned)
        return str(data.get("explanation", ""))[:200]
    except Exception:
        return ""


def _try_parse_explanation(raw: str) -> dict | None:
    import json, re
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.MULTILINE)
        return json.loads(cleaned)
    except Exception:
        return None


def _empty_result(panel: str, model: str) -> DisaggregationResult:
    return DisaggregationResult(
        panel=panel,
        states={},
        correction_count=0,
        n_windows=0,
        latency_ms=0,
        model=model,
    )
