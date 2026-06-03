#!/usr/bin/env python3
"""Evaluate the retrained model on yesterday (2026-05-11) and today (2026-05-12).

Reconstructs windows for those two days from the labeled parquet (using the
same machinery as windows_panel1.py but day-keyed), runs the int8 model on
each, and reports per-day metrics + predicted-state timelines.

Output: services/iems/training/reports/panel1_recent_days_eval.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
PQ = REPO / "data/panel1_60d_labeled.parquet"
NORM = REPO / "services/iems/models/panel1_norm.json"
INT8 = REPO / "services/iems/models/nilm_panel1_int8.onnx"
OUT = REPO / "services/iems/training/reports/panel1_recent_days_eval.md"

WIN = 100
STRIDE = 1
MID = 50
GAP = pd.Timedelta("10.5s")


def slide_day(df: pd.DataFrame, features: list[str]):
    df = df.sort_index()
    diffs = df.index.to_series().diff()
    runs = (diffs > GAP).fillna(False).astype(int).cumsum().values
    fX, hp, sp, mid_ts = [], [], [], []
    for rid in np.unique(runs):
        mask = runs == rid
        if mask.sum() < WIN:
            continue
        rf = df[mask][features].values.astype(np.float32)
        rh = df[mask]["heat_pump_label"].values.astype(np.float32)
        rs = df[mask]["solar_pump_label"].values.astype(np.float32)
        idx = df[mask].index
        for i in range(0, len(rf) - WIN + 1, STRIDE):
            mh, ms = rh[i + MID], rs[i + MID]
            # keep all windows; we'll evaluate on whichever label is valid
            fX.append(rf[i:i + WIN])
            hp.append(mh)
            sp.append(ms)
            mid_ts.append(idx[i + MID])
    if not fX:
        return (np.empty((0, WIN, len(features)), dtype=np.float32),
                np.empty((0,), dtype=np.float32),
                np.empty((0,), dtype=np.float32),
                pd.DatetimeIndex([], tz="UTC"))
    return (np.stack(fX).astype(np.float32),
            np.asarray(hp, dtype=np.float32),
            np.asarray(sp, dtype=np.float32),
            pd.DatetimeIndex(mid_ts))


def metrics(prob, y, thr):
    mask = ~np.isnan(y)
    if mask.sum() == 0:
        return {"n": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0,
                "P": float("nan"), "R": float("nan"), "F1": float("nan")}
    yhat = (prob[mask] > thr).astype(np.int32)
    yt = (y[mask] > 0.5).astype(np.int32)
    tp = int(((yhat == 1) & (yt == 1)).sum())
    fp = int(((yhat == 1) & (yt == 0)).sum())
    fn = int(((yhat == 0) & (yt == 1)).sum())
    tn = int(((yhat == 0) & (yt == 0)).sum())
    P = tp / (tp + fp) if (tp + fp) else 0.0
    R = tp / (tp + fn) if (tp + fn) else 0.0
    F1 = 2 * P * R / (P + R) if (P + R) else 0.0
    return {"n": int(mask.sum()), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "P": P, "R": R, "F1": F1}


def count_transitions(preds: np.ndarray) -> dict:
    on_to_off = 0
    off_to_on = 0
    for i in range(1, len(preds)):
        if preds[i - 1] == 0 and preds[i] == 1:
            off_to_on += 1
        elif preds[i - 1] == 1 and preds[i] == 0:
            on_to_off += 1
    return {"off_to_on": off_to_on, "on_to_off": on_to_off,
            "on_ticks": int((preds == 1).sum()),
            "off_ticks": int((preds == 0).sum())}


def main() -> int:
    norm = json.loads(NORM.read_text())
    features = norm["features"]
    mean = np.array(norm["mean"], dtype=np.float32)
    std = np.array(norm["std"], dtype=np.float32)
    thr_hp = float(norm["thresholds"]["heat_pump"])
    thr_sp = float(norm["thresholds"]["solar_pump"])

    df = pd.read_parquet(PQ)
    df = df[df[features].notna().all(axis=1)]
    print(f"[recent] feature-valid rows: {len(df)}")

    sess = ort.InferenceSession(str(INT8), providers=["CPUExecutionProvider"])

    lines: list[str] = []
    lines.append("# Panel 1 — Retrained model output on recent days")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append(f"Model: `nilm_panel1_int8.onnx` (retrained 2026-05-12). "
                 f"Thresholds: HP={thr_hp:.2f}, SP={thr_sp:.2f}.")
    lines.append("")
    lines.append(
        "Day boundaries are UTC. Windows are dense (stride=1) so each "
        "prediction corresponds to one 10-second midpoint."
    )
    lines.append("")

    for day_label, day_ts in [
        ("Yesterday — 2026-05-11 UTC", pd.Timestamp("2026-05-11", tz="UTC")),
        ("Today — 2026-05-12 UTC",    pd.Timestamp("2026-05-12", tz="UTC")),
    ]:
        day_df = df[df.index.normalize() == day_ts]
        lines.append(f"## {day_label}")
        lines.append("")
        if day_df.empty:
            lines.append("_No feature-valid rows on this day._")
            lines.append("")
            continue

        X, hp, sp, ts = slide_day(day_df, features)
        if len(X) == 0:
            lines.append(
                f"_{len(day_df)} feature-valid rows but no contiguous "
                f"100-row runs._"
            )
            lines.append("")
            continue

        Xn = ((X - mean) / std).astype(np.float32)
        probs_hp = np.empty(len(Xn), dtype=np.float32)
        probs_sp = np.empty(len(Xn), dtype=np.float32)
        for i in range(0, len(Xn), 256):
            o = sess.run(None, {"window": Xn[i:i + 256]})
            probs_hp[i:i + 256] = o[0].reshape(-1)
            probs_sp[i:i + 256] = o[1].reshape(-1)

        pred_hp = (probs_hp > thr_hp).astype(np.int32)
        pred_sp = (probs_sp > thr_sp).astype(np.int32)
        m_hp = metrics(probs_hp, hp, thr_hp)
        m_sp = metrics(probs_sp, sp, thr_sp)
        t_hp = count_transitions(pred_hp)
        t_sp = count_transitions(pred_sp)

        lines.append(
            f"- Feature-valid rows: **{len(day_df)}**  "
            f"\n- Eval windows (stride=1, contiguous): **{len(X)}**  "
            f"\n- Window timespan: `{ts.min()}` → `{ts.max()}`"
        )
        lines.append("")
        lines.append("### Per-head metrics vs rule labels")
        lines.append("")
        lines.append("| head | valid windows | TP | FP | FN | TN | precision | recall | F1 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        lines.append(
            f"| heat_pump | {m_hp['n']} | {m_hp['tp']} | {m_hp['fp']} | "
            f"{m_hp['fn']} | {m_hp['tn']} | {m_hp['P']:.3f} | "
            f"{m_hp['R']:.3f} | **{m_hp['F1']:.3f}** |"
        )
        lines.append(
            f"| solar_pump | {m_sp['n']} | {m_sp['tp']} | {m_sp['fp']} | "
            f"{m_sp['fn']} | {m_sp['tn']} | {m_sp['P']:.3f} | "
            f"{m_sp['R']:.3f} | **{m_sp['F1']:.3f}** |"
        )
        lines.append("")
        lines.append("### Predicted-state behavior (independent of rule labels)")
        lines.append("")
        lines.append("| head | predicted ON ticks | predicted OFF | off→on | on→off |")
        lines.append("|---|---:|---:|---:|---:|")
        lines.append(
            f"| heat_pump | {t_hp['on_ticks']} ({100*t_hp['on_ticks']/len(pred_hp):.1f}%) | "
            f"{t_hp['off_ticks']} | {t_hp['off_to_on']} | {t_hp['on_to_off']} |"
        )
        lines.append(
            f"| solar_pump | {t_sp['on_ticks']} ({100*t_sp['on_ticks']/len(pred_sp):.1f}%) | "
            f"{t_sp['off_ticks']} | {t_sp['off_to_on']} | {t_sp['on_to_off']} |"
        )
        lines.append("")
        lines.append("### Probability distribution")
        lines.append("")
        for name, p, thr in (("heat_pump", probs_hp, thr_hp),
                              ("solar_pump", probs_sp, thr_sp)):
            lines.append(f"`{name}` (threshold {thr:.2f}):")
            lines.append(
                f"- min={p.min():.3f}  p10={np.percentile(p, 10):.3f}  "
                f"p50={np.percentile(p, 50):.3f}  p90={np.percentile(p, 90):.3f}  "
                f"max={p.max():.3f}"
            )
            lines.append("")

        # Hour-of-day predicted ON for each head (local time)
        local_hr = ts.tz_convert("America/Los_Angeles").hour
        hp_by_hr = pd.Series(pred_hp).groupby(local_hr).agg(["sum", "count"])
        sp_by_hr = pd.Series(pred_sp).groupby(local_hr).agg(["sum", "count"])
        lines.append("### Predicted ON-rate by local hour (PT)")
        lines.append("")
        lines.append("| hour | HP ON / total | SP ON / total |")
        lines.append("|---:|---:|---:|")
        for h in sorted(set(hp_by_hr.index).union(sp_by_hr.index)):
            hp_s = int(hp_by_hr.loc[h, "sum"]) if h in hp_by_hr.index else 0
            hp_n = int(hp_by_hr.loc[h, "count"]) if h in hp_by_hr.index else 0
            sp_s = int(sp_by_hr.loc[h, "sum"]) if h in sp_by_hr.index else 0
            sp_n = int(sp_by_hr.loc[h, "count"]) if h in sp_by_hr.index else 0
            lines.append(f"| {h:02d} | {hp_s} / {hp_n} | {sp_s} / {sp_n} |")
        lines.append("")

        # Plausibility hint — compare to raw observed panel1_w / irradiance
        feats_at_mid = X[:, MID, :]
        p1_idx = features.index("panel1_w")
        irr_idx = features.index("irradiance")
        step_idx = features.index("panel1_w_step")
        lines.append("### Raw signals at midpoint (for cross-check)")
        lines.append("")
        lines.append(
            f"- `panel1_w` midpoint values: min={feats_at_mid[:, p1_idx].min():.0f}W "
            f"max={feats_at_mid[:, p1_idx].max():.0f}W "
            f"mean={feats_at_mid[:, p1_idx].mean():.0f}W"
        )
        lines.append(
            f"- `panel1_w_step` midpoint: min={feats_at_mid[:, step_idx].min():.0f}W "
            f"max={feats_at_mid[:, step_idx].max():.0f}W "
            f"mean={feats_at_mid[:, step_idx].mean():.0f}W"
        )
        lines.append(
            f"- `irradiance` midpoint: min={feats_at_mid[:, irr_idx].min():.0f} "
            f"max={feats_at_mid[:, irr_idx].max():.0f} "
            f"mean={feats_at_mid[:, irr_idx].mean():.0f} W/m²"
        )
        lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"[recent] wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
