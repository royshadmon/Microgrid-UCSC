"""
ONNX disaggregator — drop-in replacement for the LLM path.

One ONNX session per panel is loaded once and reused. Each call:
  1. Builds a normalized (1, window, n_features) feature tensor.
  2. Runs the session → one probability per appliance head.
  3. Applies per-head thresholds from panel{N}_norm.json.
  4. Optionally writes the predictions to nilm_disaggregated.

Latency: ~5-15 ms per panel, vs 5-60 s for the LLM path.
"""
import json
import logging
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from datetime import datetime

import numpy as np
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(__file__),'..','training'))
try:
    import postprocess as _pp
except Exception:
    _pp=None

try:
    import onnxruntime as ort
except ImportError:
    ort = None

from iems.inference.appliance_map import (
    APPLIANCE_NOMINAL_W, APPLIANCE_TO_PANEL, PANEL_TO_MODEL,
)
from iems.inference.feature_builder import build_panel_window, HOUSE_TZ
from iems.inference.rules_additive import apply_rules
from iems.load.anylog_query import insert_predictions

# Panel name -> the panel's own power feature column key.
_PANEL_POWER_FEATURE = {
    "Panel1 (HVAC)":    "panel1_w",
    "Panel2 (H2O)":     "panel2_w",
    "Panel3 (Kitchen)": "panel3_w",
}

logger = logging.getLogger(__name__)


@dataclass
class OnnxPanelResult:
    panel: str
    states: dict                          # appliance → [state] (length 1 per call)
    probabilities: dict
    n_windows: int                        # always 1 for ONNX
    latency_ms: int
    model: str                            # 'nilm_panel1.onnx' etc.
    midpoint_ts: str
    window_start_ts: str = ""
    window_end_ts: str = ""
    samples_per_window: int = 0
    correction_count: int = 0
    explanation_snippets: list = field(default_factory=list)
    # Full per-appliance reconciled output (MATNilm dual-head + rules):
    #   {appliance: {"state", "confidence", "power_w", "rule"}}
    reconciled: dict = field(default_factory=dict)


_session_cache = {}
_cache_lock = threading.Lock()


def _repo_root():
    # /repo/services/iems/inference/onnx_disaggregator.py → /repo
    return Path(__file__).resolve().parents[3]


def _load_session(panel):
    if ort is None:
        raise RuntimeError("onnxruntime is not installed. "
                           "Install with `pip install onnxruntime`.")
    with _cache_lock:
        if panel in _session_cache:
            return _session_cache[panel]
        info = PANEL_TO_MODEL.get(panel)
        if not info:
            raise ValueError(f"No ONNX model registered for panel {panel!r}")
        root = _repo_root()
        onnx_path = root / info["onnx"]
        norm_path = root / info["norm"]
        if not onnx_path.exists():
            raise FileNotFoundError(f"ONNX model not found: {onnx_path}")
        if not norm_path.exists():
            raise FileNotFoundError(f"Norm config not found: {norm_path}")
        sess = ort.InferenceSession(str(onnx_path),
                                    providers=["CPUExecutionProvider"])
        norm = json.loads(norm_path.read_text())
        logger.info("[ONNX] Loaded %s (%d heads, window=%d)",
                    info["tag"], len(norm["heads"]), norm["window"])
        _session_cache[panel] = (sess, norm)
        return _session_cache[panel]


def load_all_panel_sessions():
    for panel in PANEL_TO_MODEL:
        try:
            _load_session(panel)
        except Exception as exc:
            logger.error("[ONNX] failed to load %s: %s", panel, exc)
    return dict(_session_cache)


def disaggregate_panel_onnx(panel, panel_rows, weather,
                            write_to_anylog=True, end_ts=None):
    start = time.monotonic()
    sess, norm = _load_session(panel)
    tensor, mid_ts, start_ts, end_ts_real = build_panel_window(
        panel, panel_rows, weather, norm, end_ts=end_ts)

    inp_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {inp_name: tensor})

    heads = norm["heads"]
    thresholds = norm.get("thresholds", {}) or {}
    out_names = [o.name for o in sess.get_outputs()]
    dual_head = any(n.startswith("prob_") for n in out_names)

    # Measured panel power = mean abs() of the most recent raw samples for THIS
    # panel's own channel. These are REAL watts, used by the physics rules.
    # (The de-normalized tensor value is NOT a physical watt: the feature builder
    # applies a training-time transform, so a +300 W reading can de-normalize to
    # a negative number. Reasoning on that misfires the gate/overshoot rules, so
    # we read the raw samples instead.)
    feats = norm["features"]
    mid = int(norm.get("mid", int(norm["window"]) // 2))
    panel_w_meas = 0.0
    _own = panel_rows.get(panel, []) or []
    _recent = []
    for _r in _own[-30:]:
        try:
            _recent.append(abs(float(_r.get("w", 0) or 0)))
        except (TypeError, ValueError):
            continue
    if _recent:
        panel_w_meas = sum(_recent) / len(_recent)

    probs = {}
    preds = {}
    for head in heads:
        # Output naming varies by exporter: dual-head uses "prob_<head>",
        # older single-head used "p_<head>", train_all_physical.py exports
        # the bare head name. Accept all three.
        for _cand in ((f"prob_{head}",) if dual_head else (f"p_{head}", head)):
            if _cand in out_names:
                _idx = out_names.index(_cand)
                break
        else:
            raise KeyError(
                f"model output for head {head!r} not found; "
                f"available outputs: {out_names}")
        p = float(np.asarray(outputs[_idx]).flatten()[0])
        probs[head] = p
        thr = float(thresholds.get(head, 0.5))
        state = 1 if p >= thr else 0
        # Dual-head regression output (kW -> W); fall back to nominal.
        if dual_head and f"pow_{head}" in out_names:
            power_w = float(np.asarray(
                outputs[out_names.index(f"pow_{head}")]).flatten()[0]) * 1000.0
        else:
            power_w = float(APPLIANCE_NOMINAL_W.get(head, 100)) if state else 0.0
        preds[head] = {"state": state, "confidence": p,
                       "power_w": power_w if state else 0.0}

    # POST-PROCESSING GATES (ToD exclusivity, solar irradiance+mutex, demotion)
    if _pp is not None:
        try:
            import pandas as _pd
            _t = _pd.Timestamp(result.midpoint_ts or result.window_end_ts)
            _t = (_t.tz_localize("UTC") if _t.tz is None else _t).tz_convert("America/Los_Angeles")
            _hr = int(_t.hour)   # LOCAL hour - ToD gates are defined in Pacific time
        except Exception:
            _hr = 12
        _states = {h: (probs[h], float(thresholds.get(h, 0.5))) for h in heads}
        _gated = _pp.apply_gates(_states, _hr, {"Panel1 (HVAC)": panel_w_meas})
        for h, (st, cf, flag) in _gated.items():
            preds[h]["state"] = 0 if st in ("OFF", "MAYBE") else 1
            preds[h]["confidence"] = cf
            preds[h]["flag"] = flag

    # Post-inference reconciliation: mutex (heat_pump<->solar_pump), battery
    # window flag, additive recovery/overshoot-trim against measured panel power.
    ts_local = mid_ts.astimezone(HOUSE_TZ)
    preds = apply_rules(preds, panel_power_w=panel_w_meas,
                        ts_local=ts_local, additive=dual_head,
                        weather=weather, panel=panel)

    states = {head: [preds[head]["state"]] for head in heads}

    latency_ms = round((time.monotonic() - start) * 1000)
    result = OnnxPanelResult(
        panel=panel,
        states=states,
        probabilities=probs,
        n_windows=1,
        latency_ms=latency_ms,
        model=os.path.basename(PANEL_TO_MODEL[panel]["onnx"]),
        midpoint_ts=mid_ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
        window_start_ts=start_ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
        window_end_ts=end_ts_real.strftime("%Y-%m-%d %H:%M:%S.%f"),
        samples_per_window=int(norm["window"]),
        reconciled=preds,
    )

    if write_to_anylog:
        try:
            _write_predictions(result, panel_rows)
        except Exception as exc:
            logger.warning("nilm_disaggregated writeback failed: %s", exc)

    return result


def _write_predictions(result, panel_rows):
    """One nilm_disaggregated row per appliance head."""
    records = []
    # Stamp rows with the window-end timestamp so the dashboard reflects
    # the freshest sample, not the 5-minute-old window midpoint.
    ts_str = result.window_end_ts or result.midpoint_ts
    window_start_str = result.window_start_ts or result.midpoint_ts
    window_end_str = result.window_end_ts or result.midpoint_ts
    win_n = result.samples_per_window or 1
    for head, state_list in result.states.items():
        state = state_list[0] if state_list else 0
        circuit = APPLIANCE_TO_PANEL.get(head, result.panel)
        rows_for_circuit = panel_rows.get(circuit, [])
        recent_w = []
        for r in rows_for_circuit[-30:]:
            try:
                recent_w.append(abs(float(r.get("w", 0) or 0)))
            except (TypeError, ValueError):
                continue
        if state == 1:
            # Prefer the reconciled dual-head power estimate; fall back to nominal.
            rec_w = (result.reconciled.get(head, {}) or {}).get("power_w") or 0.0
            avg_w = float(rec_w) if rec_w > 0 else float(APPLIANCE_NOMINAL_W.get(head, 100))
        else:
            avg_w = 0.0
        std_w = round(statistics.stdev(recent_w), 2) if len(recent_w) > 1 else 0.0

        records.append({
            "ts":           ts_str,
            "circuit":      circuit,
            "appliance":    head,
            "state":        "ON" if state == 1 else "OFF",
            "confidence":   round(result.probabilities[head], 4),
            "avg_w":        round(avg_w, 2),
            "median_w":     round(avg_w, 2),
            "std_w":        std_w,
            "window_start": window_start_str,
            "window_end":   window_end_str,
            "window_n":     win_n,
        })
    insert_predictions(records)
    logger.debug("[ONNX] wrote %d nilm_disaggregated rows for %s",
                 len(records), result.panel)
