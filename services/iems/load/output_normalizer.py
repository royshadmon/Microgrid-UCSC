"""
Normalizes LLM output per LLM4NILM Section 4.3.
Handles: length misalignment, malformed JSON, non-binary values.
"""
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def normalize(
    raw_output: str,
    expected_fields: list[str],
    window_size: int,
    panel: str = "",
    window_idx: int = 0,
) -> dict[str, list[int]]:
    parsed = _parse_json(raw_output, panel, window_idx)
    if parsed is None:
        logger.warning(
            "[%s] window=%d: malformed JSON after retries — all-zeros fallback",
            panel,
            window_idx,
        )
        return {f: [0] * window_size for f in expected_fields}

    result = {}
    for field in expected_fields:
        raw_values = parsed.get(field, [])
        binarized = _to_binary_list(raw_values, field, panel, window_idx)
        aligned = _align_length(binarized, window_size, field, panel, window_idx)
        result[field] = aligned

    return result


def _parse_json(raw: str, panel: str, window_idx: int) -> dict | None:
    cleaned = raw.strip()
    # Strip markdown fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.debug("[%s] window=%d: first JSON parse failed, trying bracket extract", panel, window_idx)

    # Try extracting first {...} block
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("[%s] window=%d: could not parse JSON", panel, window_idx)
    return None


def _to_binary_list(
    values: Any,
    field: str,
    panel: str,
    window_idx: int,
) -> list[int]:
    if not isinstance(values, list):
        logger.debug("[%s] window=%d field=%s: non-list value=%r → zeros", panel, window_idx, field, values)
        return []

    result = []
    for v in values:
        if v in (0, 1, True, False):
            result.append(int(bool(v)))
        else:
            logger.debug("[%s] window=%d field=%s: non-binary value=%r → 0", panel, window_idx, field, v)
            result.append(0)
    return result


def _align_length(
    values: list[int],
    target: int,
    field: str,
    panel: str,
    window_idx: int,
) -> list[int]:
    actual = len(values)
    if actual == target:
        return values
    if actual < target:
        logger.debug(
            "[%s] window=%d field=%s: length %d < %d — forward-padding",
            panel, window_idx, field, actual, target,
        )
        pad_value = values[-1] if values else 0
        return values + [pad_value] * (target - actual)
    logger.debug(
        "[%s] window=%d field=%s: length %d > %d — truncating",
        panel, window_idx, field, actual, target,
    )
    return values[:target]


def normalize_output(
    raw_str: str,
    appliance_names: list[str],
    expected_length: int,
    panel: str = "",
    window_idx: int = 0,
) -> dict[str, list[int]]:
    """
    Public LLM4NILM normalizer (Section 4.3) keyed by appliance names.
    Wraps the internal `normalize()` and returns one binary list per name.
    """
    return normalize(
        raw_output=raw_str,
        expected_fields=list(appliance_names),
        window_size=expected_length,
        panel=panel,
        window_idx=window_idx,
    )
