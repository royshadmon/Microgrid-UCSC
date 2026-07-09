#!/usr/bin/env python3
"""Phase 3: CT-anchored regression targets + per-panel residual.

Replaces the degenerate nominal-apportionment target (which apportioned the WHOLE
panel by rule-label nominal share -> circular). New scheme, per panel N:

  panel_N = measured_240_N (PINNED)  + sum(120V heads, apportioned)  + residual_N

  measured_240_N = bal240_pN * PF_N           # PF: apparent(I*V) -> real watts
      heat_pump  = measured_240_p1  (pinned regression target)
      water_heater = measured_240_p2
      dryer      = MASKED  (240V but shares bal240_p3 with oven/cooktop)
  remainder_120 = max(panel_N - measured_240_N, 0)
  120V heads    = apportion remainder_120 across ON heads by nominal share
  residual_N    = remainder_120 - sum(120V head targets)   (unlabeled 120V floor)

The measured terms are fixed observations, so the balance is non-degenerate: the
only free variables are the 120V heads + residual. PF_N from the Phase-0 leg
regression coefficients (real/apparent).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "services/iems/training/data"
MAP = REPO / "services/iems/training/ct_appliance_map.json"
sys.path.insert(0, str(REPO / "services"))
from iems.inference.appliance_map import APPLIANCE_NOMINAL_W as NOM  # noqa: E402

PANEL_HEADS = {
    1: ["heat_pump", "solar_pump"],
    2: ["water_heater", "hair_dryer", "sprinklers", "bath_lights"],
    3: ["dryer", "refrigerator", "dishwasher", "microwave",
        "washing_machine", "pressure_pump", "computers", "tv_stereo"],
}
PANEL_COL = {1: "Panel1 (HVAC)", 2: "Panel2 (H2O)", 3: "Panel3 (Kitchen)"}
BAL_COL = {1: "bal240_p1", 2: "bal240_p2", 3: "bal240_p3"}
LABEL_KEY = {1: "Panel1_HVAC", 2: "Panel2_H2O", 3: "Panel3_Kitchen"}
MEASURED_240 = {"heat_pump": 1, "water_heater": 2}   # head -> panel
MASKED_240 = {"dryer"}                                # 240V, not isolable


def panel_pf():
    """real/apparent per panel from Phase-0 leg coefficients (eff_volt_coef)."""
    legs = json.load(open(MAP))["legs"]
    pf = {}
    for p, (a, b) in {1: ("I11", "I12"), 2: ("I21", "I22"), 3: ("I31", "I32")}.items():
        c = legs[a]["eff_volt_coef"] + legs[b]["eff_volt_coef"]
        pf[p] = min(c / 246.0, 1.0)          # 246 = VrmsA+VrmsB nominal
    return pf


def build_targets(panel_w, bal240, labels, panel, pf):
    """All series share an index. Returns (targets{head:kW}, residual_kW, meas240_kW)."""
    heads = PANEL_HEADS[panel]
    meas240 = (bal240 * pf[panel]).clip(lower=0)                 # real watts
    remainder120 = (panel_w - meas240).clip(lower=0)
    unmet = [h for h in heads if h not in MEASURED_240 and h not in MASKED_240]

    nominal = {h: float(NOM.get(h, 500)) for h in unmet}
    on = {h: (labels[h] == 1).astype(float) for h in unmet}
    denom = sum(on[h] * nominal[h] for h in unmet)
    denom = denom.where(denom > 1e-6, 1.0)

    targets = {}
    tsum = pd.Series(0.0, index=panel_w.index)
    for h in unmet:
        share = (on[h] * nominal[h]) / denom
        t = share * remainder120
        t = t.where(labels[h] == 1, 0.0)          # OFF -> 0
        t = t.where(~labels[h].isna(), np.nan)    # unlabeled -> NaN
        targets[h] = t / 1000.0
        tsum = tsum + t.fillna(0.0)

    # measured heads: pinned to real 240V watts
    for h, p in MEASURED_240.items():
        if h in heads:
            targets[h] = (meas240 / 1000.0)
    # masked 240V head (dryer): no regression target
    for h in MASKED_240:
        if h in heads:
            targets[h] = pd.Series(np.nan, index=panel_w.index)

    residual = (remainder120 - tsum).clip(lower=0) / 1000.0
    return targets, residual, meas240 / 1000.0


LAMBDA_BAL = 0.1   # energy-balance loss weight (start ~0.1; tune up only if it
                   # does not suppress BCE, mirroring LAMBDA_REG reasoning)


def energy_balance_loss(powers, probs, residual_hat, unmet_idx, panel_kw, measured_sum_kw):
    """Phase 3.2 balance loss. Measured 240V heads enter as their fixed measured
    values (measured_sum_kw); the free variables are the unmetered 120V heads
    (powers[i]*probs[i]) plus the model residual. All tensors kW, shape (B,).
      L = mean( ( sum_unmet(p_hat*o_hat) + residual - (panel - measured) )^2 )
    """
    import torch
    free = residual_hat
    for i in unmet_idx:
        free = free + powers[i] * probs[i]
    target = (panel_kw - measured_sum_kw).clamp(min=0.0)
    return ((free - target) ** 2).mean()


def main():
    piv = pd.read_parquet(DATA / "raw_pivot_ct.parquet")
    pf = panel_pf()
    print(f"[reg_ct] panel PF (real/apparent): {pf}")
    print("=" * 74)
    print("ENERGY-BALANCE VERIFICATION (3.3): meas240 + sum(120V) + residual = panel")
    print("=" * 74)
    for P in (1, 2, 3):
        panel_w = piv[PANEL_COL[P]]
        bal = piv[BAL_COL[P]]
        lab = pd.read_parquet(DATA / f"labels_{LABEL_KEY[P]}_ct.parquet")
        tgts, resid, meas = build_targets(panel_w, bal, lab, P, pf)
        # reconstruct (kW)
        heads_120 = [h for h in PANEL_HEADS[P] if h not in MEASURED_240 and h not in MASKED_240]
        recon = meas + resid + sum(tgts[h].fillna(0.0) for h in heads_120)
        obs = panel_w.notna() & bal.notna()
        err = (recon[obs] * 1000.0 - panel_w[obs])
        print(f"\nP{P} [{PANEL_COL[P]}]  observed={int(obs.sum())}")
        print(f"  reconstruction err W: median {err.median():.1f}  MAE {err.abs().mean():.1f}  "
              f"p95 {err.abs().quantile(.95):.0f}")
        print(f"  residual W: median {resid[obs].median()*1000:.0f}  p90 {resid[obs].quantile(.9)*1000:.0f}  "
              f"max {resid[obs].max()*1000:.0f}")
        # residual should NOT swing with the 240V load (bounded floor, not a dump)
        rc = np.corrcoef(resid[obs], meas[obs])[0, 1]
        print(f"  corr(residual, measured_240) = {rc:.3f}  (near 0 => residual isn't absorbing the 240V load)")
        if P in (1, 2):
            mh = "heat_pump" if P == 1 else "water_heater"
            on = lab[mh] == 1
            print(f"  measured head '{mh}': target==meas240 (pinned); "
                  f"mean ON target {tgts[mh][on].mean()*1000:.0f}W")
    print("\n" + "=" * 74)
    print("Contrast: OLD build_reg_targets apportioned the WHOLE panel by rule-label")
    print("nominal share (circular). NEW pins the 240V loads to measurement and only")
    print("apportions the 120V remainder, with residual absorbing the unlabeled floor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
