#!/usr/bin/env python3
"""Phase 2: manufacture MEASURED hard labels from the CT-derived bal240 signal;
keep canonical rule labels for every other head. Additive -> writes *_ct.parquet,
leaving the live labels_*.parquet untouched.

Measured heads (clean single-240V loads per Phase 0):
  heat_pump    <- bal240_p1   ON > HP_ON_W, 2-step debounce
  water_heater <- bal240_p2   ON > WH_ON_W, 2-step debounce
Panel-1 interlock: solar_pump forced 0 where heat_pump measured ON.
dryer stays RULE-supervised: bal240_p3 is the contaminated dryer+oven+cooktop
aggregate (Phase 0). A provisional measured dryer (sustained >4kW) is emitted for
evaluation only, not wired into the head set.
Regression companions for Phase 3: measured watts per measured head.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import rule_engine_ct as re   # Phase 4: decontaminated + measured-head-retired rules

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "services/iems/training/data"
CT = DATA / "raw_pivot_ct.parquet"

HP_ON_W = 1000.0        # clears ~294W p90 balanced floor; catches the ~5kW compressor
WH_ON_W = 500.0         # spec on-threshold; balanced floor p90 ~121W
DRYER_PROV_W = 4000.0   # provisional dryer gate (rejects most oven/cooktop)
DEBOUNCE = 2

PANELS = [
    ("Panel1 (HVAC)", "panel1_w", "Panel1_HVAC", re.apply_panel1_rules_ct),
    ("Panel2 (H2O)",  "panel2_w", "Panel2_H2O",  re.apply_panel2_rules_ct),
    ("Panel3 (Kitchen)", "panel3_w", "Panel3_Kitchen", re.apply_panel3_rules_ct),
]


def debounced_label(sig: pd.Series, thr: float, n: int = DEBOUNCE) -> pd.Series:
    on = sig > thr
    hold = on.copy()
    for k in range(1, n):
        hold &= on.shift(k, fill_value=False)
    lab = hold.astype("float64")
    lab[sig.isna()] = np.nan          # unobservable where the CT signal is missing
    return lab


def build() -> int:
    piv = pd.read_parquet(CT)
    print(f"[labels_ct] loaded {piv.shape} {piv.index.min()} -> {piv.index.max()}")

    # rule-engine input frame (short names). No weather on this window.
    f = pd.DataFrame(index=piv.index)
    f["panel1_w"] = piv["Panel1 (HVAC)"]
    f["panel2_w"] = piv["Panel2 (H2O)"]
    f["panel3_w"] = piv["Panel3 (Kitchen)"]
    f["shop_w"] = piv.get("Shop")
    f["bal240_p1"] = piv["bal240_p1"]; f["bal240_p2"] = piv["bal240_p2"]; f["bal240_p3"] = piv["bal240_p3"]  # Phase 4 decontamination inputs

    bal1, bal2, bal3 = piv["bal240_p1"], piv["bal240_p2"], piv["bal240_p3"]
    hp_meas = debounced_label(bal1, HP_ON_W)
    wh_meas = debounced_label(bal2, WH_ON_W)
    dryer_prov = debounced_label(bal3, DRYER_PROV_W)

    # panel-threshold (make_labels-style) rule ON-rates on THIS window, for the
    # apples-to-apples disagreement report.
    ml_hp = (f["panel1_w"] > 200).mean()
    ml_wh = (f["panel2_w"] > 300).mean()

    report = []
    for panel_nm, short, key, fn in PANELS:
        rules = fn(f)
        # capture rule-engine ON-rate for the measured heads BEFORE override
        if "heat_pump" in rules:
            rule_hp_rate = float((rules["heat_pump"] == 1).mean())
            rules["heat_pump"] = hp_meas
        if "water_heater" in rules:
            rule_wh_rate = float((rules["water_heater"] == 1).mean())
            rules["water_heater"] = wh_meas
        if "solar_pump" in rules:                      # Panel-1 interlock
            sp = rules["solar_pump"].copy()
            sp[hp_meas == 1] = 0
            rules["solar_pump"] = sp
        out = DATA / f"labels_{key}_ct.parquet"
        rules.to_parquet(out)
        rates = ", ".join(
            f"{c}={float((rules[c] == 1).mean()) * 100:.2f}%" for c in rules.columns
        )
        report.append((panel_nm, key, rules, rates))

    # regression companions (measured watts) for Phase 3
    mw = pd.DataFrame(index=piv.index)
    mw["heat_pump_w"] = bal1
    mw["water_heater_w"] = bal2
    mw["dryer_agg_w"] = bal3            # contaminated aggregate; Phase 3 residual/split
    mw["dryer_provisional_label"] = dryer_prov
    mw.to_parquet(DATA / "measured_watts_ct.parquet")

    # ---- Phase 2.2 verification ----
    print("\n[labels_ct] wrote per-panel labels_{key}_ct.parquet:")
    for panel_nm, key, rules, rates in report:
        print(f"  {key}: {rules.shape} heads -> {rates}")

    print("\n[labels_ct] MEASURED vs RULE ON-rate (the disagreement is the point):")
    hp_m = float((hp_meas == 1).mean()); wh_m = float((wh_meas == 1).mean())
    print(f"  heat_pump   : measured {hp_m*100:6.2f}%  | rule_engine(no weather) {rule_hp_rate*100:6.2f}%  "
          f"| panel>200W {ml_hp*100:6.2f}%")
    print(f"  water_heater: measured {wh_m*100:6.2f}%  | rule_engine {rule_wh_rate*100:6.2f}%  "
          f"| panel>300W {ml_wh*100:6.2f}%")

    print("\n[labels_ct] input-responsiveness (measured label tracks bal240):")
    for nm, lab, bal in (("heat_pump", hp_meas, bal1), ("water_heater", wh_meas, bal2)):
        on = lab == 1; off = lab == 0
        print(f"  {nm}: mean bal240 ON={bal[on].mean():.0f}W  OFF={bal[off].mean():.0f}W  "
              f"ON-samples={int(on.sum())}")

    print("\n[labels_ct] dryer contamination (why it stays rule-supervised):")
    dr = float((dryer_prov == 1).mean())
    print(f"  provisional dryer (bal240_p3>4kW sustained): {dr*100:.2f}% ON  "
          f"({int((dryer_prov==1).sum())} samples) — emitted for eval only, not wired")
    return 0


if __name__ == "__main__":
    sys.exit(build())
