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


if __name__ == "__main__":
    import sys; sys.exit(_main())
