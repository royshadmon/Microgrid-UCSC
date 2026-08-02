#!/usr/bin/env python3
"""Phase 4: decontaminated, measured-head-retired rule engine (selective policy).

Wraps the live rule_engine.py (untouched). Changes vs raw-panel rules:

  1. Retire measured heads. heat_pump, water_heater -> NaN (CT-measured, Phase 2);
     never override a measured head (merge_measured).
  2. dryer off the ISOLATED 240V aggregate (PF-corrected bal240_p3) -> cleaner
     detection, no 120V false triggers.
  3. Absolute-BAND 120V rules (hair_dryer, dishwasher, microwave) run on the
     decontaminated signal pN_120 = panelN_w - real_240 -> removes the false
     positives the 240V load caused in their power band.
  4. STEP/variance 120V rules (sprinklers, bath_lights, refrigerator,
     washing_machine, pressure_pump, computers, tv_stereo) are NOISE-sensitive, so
     instead of a noisy subtraction they keep the raw-panel rule and are GATED to
     NaN (abstain) during a strong 240V event on that panel - a small 120V load is
     genuinely unobservable under a running 240V load.

Off-event (bal240 ~ 0) the outputs are identical to the raw rules. Falls back to
raw panelN_w when bal240 columns are absent (pre-CT / live non-CT inference).

Input columns: panel1_w, panel2_w, panel3_w [, shop_w, bal240_p1/p2/p3].
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import rule_engine as base
from reg_targets_ct import panel_pf

PF = panel_pf()
BAL = {1: "bal240_p1", 2: "bal240_p2", 3: "bal240_p3"}
PCOL = {1: "panel1_w", 2: "panel2_w", 3: "panel3_w"}
EVENT_W = {1: 1000.0, 2: 500.0, 3: 4000.0}          # strong-240V thresholds (real W)

RETIRE = {1: ["heat_pump"], 2: ["water_heater"], 3: []}
DECON_BAND = {1: [], 2: ["hair_dryer"], 3: ["dishwasher", "microwave"]}
DRYER_240 = {1: [], 2: [], 3: ["dryer"]}
GATE_STEP = {1: ["solar_pump"],
             2: ["sprinklers", "bath_lights"],
             3: ["refrigerator", "washing_machine", "pressure_pump", "computers", "tv_stereo"]}
MEASURED = ("heat_pump", "water_heater")
_APPLY = {1: base.apply_panel1_rules, 2: base.apply_panel2_rules, 3: base.apply_panel3_rules}


def _real_240(df, p):
    return (df[BAL[p]] * PF[p]).clip(lower=0) if BAL[p] in df.columns else None


def _swap(df, col, sig):
    f = df.copy(); f[col] = sig; return f


def _apply_ct(df, p):
    fn, pcol = _APPLY[p], PCOL[p]
    raw = fn(df)                                       # step heads + baseline
    out = raw.copy()
    r240 = _real_240(df, p)
    if r240 is not None:
        p120 = (df[pcol] - r240).clip(lower=0)
        decon = fn(_swap(df, pcol, p120))
        for h in DECON_BAND[p]:
            if h in out: out[h] = decon[h]
        for h in DRYER_240[p]:
            if h in out: out[h] = fn(_swap(df, pcol, r240))[h]
        event = r240 > EVENT_W[p]
        for h in GATE_STEP[p]:
            if h in out: out.loc[event, h] = np.nan     # abstain under a 240V load
    for h in RETIRE[p]:
        if h in out: out[h] = base._nan_series(df.index)
    return out


def apply_panel1_rules_ct(df): return _apply_ct(df, 1)
def apply_panel2_rules_ct(df): return _apply_ct(df, 2)
def apply_panel3_rules_ct(df): return _apply_ct(df, 3)


def merge_measured(rule_out: pd.DataFrame, measured: pd.DataFrame) -> pd.DataFrame:
    out = rule_out.copy()
    for h in MEASURED:
        if h in measured.columns:
            out[h] = measured[h]
    return out


def _main():
    from pathlib import Path
    D = Path(__file__).resolve().parents[3] / "services/iems/training/data"
    piv = pd.read_parquet(D / "raw_pivot_ct.parquet")
    f = pd.DataFrame(index=piv.index)
    f["panel1_w"] = piv["Panel1 (HVAC)"]; f["panel2_w"] = piv["Panel2 (H2O)"]
    f["panel3_w"] = piv["Panel3 (Kitchen)"]; f["shop_w"] = piv.get("Shop")
    fb = f.copy()
    for p in (1, 2, 3): fb[BAL[p]] = piv[BAL[p]]

    old = {p: _APPLY[p](f) for p in (1, 2, 3)}
    new = {1: apply_panel1_rules_ct(fb), 2: apply_panel2_rules_ct(fb), 3: apply_panel3_rules_ct(fb)}
    ev = {p: (piv[BAL[p]] * PF[p] > EVENT_W[p]) for p in (1, 2, 3)}
    noev = {p: ~ev[p] for p in (1, 2, 3)}

    print("4.3a measured heads retired:",
          f"P1 heat_pump NaN={new[1]['heat_pump'].isna().all()},",
          f"P2 water_heater NaN={new[2]['water_heater'].isna().all()}")

    print("\n4.3b BAND-rule false positives DURING 240V event (old raw -> new decon):")
    for p, hs in DECON_BAND.items():
        for h in hs:
            o = (old[p][h][ev[p]] == 1).mean() * 100; n = (new[p][h][ev[p]] == 1).mean() * 100
            print(f"  P{p} {h:14s} {o:6.2f}% -> {n:6.2f}%")

    print("\n4.3c STEP heads: abstained (NaN) during 240V event, unchanged off-event:")
    for p, hs in GATE_STEP.items():
        for h in hs:
            nan_on = new[p][h][ev[p]].isna().mean() * 100
            same_off = (new[p][h][noev[p]].fillna(-9) == old[p][h][noev[p]].fillna(-9)).mean() * 100
            print(f"  P{p} {h:16s} NaN-during-event {nan_on:5.1f}%  off-event==old {same_off:5.1f}%")

    print("\n4.3d dryer off isolated 240V (old raw -> new): overall ON",
          f"{(old[3]['dryer']==1).mean()*100:.2f}% -> {(new[3]['dryer']==1).mean()*100:.2f}%")
    # noise sanity: off-event, decon band heads unchanged vs old
    print("\n4.3e off-event band heads identical to old (decon acts only on events):")
    for p, hs in DECON_BAND.items():
        for h in hs:
            same = (new[p][h][noev[p]].fillna(-9) == old[p][h][noev[p]].fillna(-9)).mean() * 100
            print(f"  P{p} {h:14s} off-event match {same:.1f}%")
    return 0


# ─────────────────────────────────────────────────────────────────────────
# Temporal-overlay label source (OPT-IN, additive; existing fns untouched).
#
# Combines the per-sample CT band rules (above) with the offline temporal
# event/signature engine (temporal_rule_engine.py: duration + cycle-shape +
# time-of-day) and emits a companion per-appliance CONFIDENCE frame.
#
# STATUS
#   * live       : high-confidence, non-coupled temporal events refine the base
#                  ON spans for the separable heads (computers, hair_dryer, tv,
#                  refrigerator). Coupled heads (microwave) are never overridden.
#   * inert      : the confidence frame is written but NOT yet consumed by
#                  training. masked_bce() takes a scalar pos_weight, not a
#                  per-sample weight. To use it, thread a weight tensor through
#                  build_windows_ct + masked_bce (weighted mean instead of mean).
#   * unvalidated: temporal spans are not proven better than base spans without a
#                  hand-labelled test set. Keep this OPT-IN until that exists.
#
# make_labels_ct.py stays on apply_panelN_rules_ct by default. To A/B the
# temporal label set, call apply_ct_temporal(df) and write labels (+ optionally
# the confidence frame) instead.
# ─────────────────────────────────────────────────────────────────────────
import temporal_rule_engine as _tre

_OVERRIDE_CONF = 0.5     # min temporal event conf to refine a base ON span
_RULE_CONF     = 0.5     # flat confidence for a rule-only (unconfirmed) label
_COUPLED_CONF  = 0.25    # confidence cap for coupled/ambiguous heads


def apply_ct_temporal(df, override_conf: float = _OVERRIDE_CONF):
    """Return (labels, confidence) DataFrames.

    labels     : {1.0, 0.0, NaN} per appliance. Base CT band rules, refined by
                 high-confidence, non-coupled temporal events.
    confidence : per-appliance per-timestamp confidence in [0, 1] (NaN where the
                 label is NaN). Rule-only labels get a flat _RULE_CONF; temporal-
                 confirmed spans get the event confidence; coupled/ambiguous heads
                 are capped at _COUPLED_CONF so the loss can down-weight them once
                 it accepts a per-sample weight.

    Offline / non-causal by design: labelling has the whole trace, so the
    temporal signatures use full past+future context (no causal restriction).
    """
    # 1. base CT labels across all three panels
    labels = pd.concat([_apply_ct(df, p) for p in (1, 2, 3)], axis=1)
    labels = labels.loc[:, ~labels.columns.duplicated()]

    # 2. seed a flat confidence from the base labels
    conf = pd.DataFrame(np.nan, index=labels.index, columns=labels.columns)
    for h in labels.columns:
        conf.loc[labels[h].notna(), h] = _RULE_CONF

    # 3. temporal event overlay (offline, whole-trace)
    ev = _tre.classify(df)
    if not ev.empty:
        for _, e in ev.iterrows():
            h = e["appliance"]
            if h not in labels.columns:
                continue  # e.g. freezer_garage (no base head / circuit unconfirmed)
            span = (labels.index >= e["start"]) & (labels.index <= e["end"])
            if e["coupled"]:
                # never override a coupled head's label; only cap its confidence
                lower = span & (conf[h] > _COUPLED_CONF)
                conf.loc[lower, h] = _COUPLED_CONF
            elif e["conf"] >= override_conf:
                labels.loc[span, h] = 1.0            # refine ON span
                conf.loc[span, h] = float(e["conf"])

    conf[labels.isna()] = np.nan
    return labels, conf


if __name__ == "__main__":
    import sys; sys.exit(_main())
