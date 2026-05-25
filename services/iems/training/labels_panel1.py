#!/usr/bin/env python3
"""Rule-only labels for Panel 1 — three heads.

Per the appliance spec (`appliance_data_updated.txt`):
  - heat_pump (Panel 1):   on-threshold 300 W, range 1500–4000 W
  - solar water heater pump (Panel 1, no thresholds in the spec):
                           defaulted 30 W on, 50–250 W range

Each head is labeled INDEPENDENTLY from a rule on Panel-1 raw and weather/
irradiance signals. Conflict policy: heat-pump cycles mask the other two
appliances (their meters can't separate when 4 kW of compressor is on).

Output:
  data/panel1_60d_labeled.parquet
  reports/panel1_label_consensus.md
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
IN = REPO / "data/panel1_60d.parquet"
OUT_PQ = REPO / "data/panel1_60d_labeled.parquet"
OUT_MD = REPO / "services/iems/training/reports/panel1_label_consensus.md"

# Heat pump (appliance_data_updated.txt)
HP_ON_THRESHOLD = 300
HP_MIN_SPEC = 1500
HP_MAX_SPEC = 4000

# Solar water heater pump (file mentions appliance, defaulted thresholds)
SP_ON_THRESHOLD = 30
SP_STEP_ON  = 40
SP_STEP_OFF = 10
SP_STEP_MAX = 300

# Vacuum cleaner intentionally not labeled here: per appliance_data_updated.txt
# it is a MOBILE load that changes panels; a Panel-1 specific detector
# would only see it intermittently. Future work: cross-panel vacuum detector.


def stats(s: pd.Series) -> dict:
    return {
        "rows": len(s),
        "pos":  int((s == 1).sum()),
        "neg":  int((s == 0).sum()),
        "nan":  int(s.isna().sum()),
    }


def main() -> int:
    df = pd.read_parquet(IN)
    print(f"[labels] loaded {len(df)} rows; "
          f"panel1_w non-null {df['panel1_w'].notna().sum()}")

    if "panel1_w_step" not in df.columns:
        raise RuntimeError("panel1_w_step missing — re-run extract first")

    panel1_60s = df["panel1_w"].rolling("60s", min_periods=3).mean()
    weather_demand = (df["outside_temp"] < 60) | (df["outside_temp"] > 75)
    step = df["panel1_w_step"]
    p1 = df["panel1_w"]

    # ── heat_pump ──────────────────────────────────────────────────
    rule_hp = pd.Series(np.nan, index=df.index, dtype="float64")
    hp_on = (panel1_60s > HP_MIN_SPEC) & weather_demand & p1.notna()
    hp_off = (p1 < (HP_ON_THRESHOLD - 100)) & p1.notna()
    rule_hp[hp_on] = 1
    rule_hp[hp_off] = 0
    hp_low, hp_high = 0.5 * HP_MIN_SPEC, 1.5 * HP_MAX_SPEC
    hp_inconsistent = (rule_hp == 1) & ((p1 < hp_low) | (p1 > hp_high))
    rule_hp[hp_inconsistent] = np.nan
    dropped_hp = int(hp_inconsistent.sum())

    # ── solar_pump (small step + irradiance + not HP) ───────────────
    rule_sp = pd.Series(np.nan, index=df.index, dtype="float64")
    sp_on = (
        (step > SP_STEP_ON) & (step < SP_STEP_MAX)
        & (df["irradiance"] > 200)
        & (rule_hp != 1)
        & p1.notna() & step.notna()
    )
    sp_off = (
        p1.notna() & step.notna()
        & (
            (df["irradiance"] < 50)
            | (step < SP_STEP_OFF)
            | (p1 < SP_ON_THRESHOLD)
            | (step > SP_STEP_MAX)
            | (rule_hp == 1)
        )
    )
    rule_sp[sp_on] = 1
    rule_sp[sp_off] = 0
    sp_inconsistent = (rule_sp == 1) & ((p1 < 100) | (p1 > 500))
    rule_sp[sp_inconsistent] = np.nan
    dropped_sp = int(sp_inconsistent.sum())

    # ── Persist ────────────────────────────────────────────────────
    df["heat_pump_label"] = rule_hp
    df["solar_pump_label"] = rule_sp
    df.to_parquet(OUT_PQ)
    print(f"[labels] wrote {OUT_PQ}")

    s_hp = stats(rule_hp)
    s_sp = stats(rule_sp)
    recent = df.index >= pd.Timestamp("2026-05-06", tz="UTC")
    s_hp_r = stats(rule_hp[recent])
    s_sp_r = stats(rule_sp[recent])

    lines: list[str] = []
    lines.append("# Panel 1 — Rule labels (three heads)")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append(
        "Heads: `heat_pump`, `solar_pump`. Rule-only; "
        "no LLM supervision. Heat-pump cycles mask the other two "
        "(their meters can't see a 100-W pump while the compressor draws "
        "4 kW)."
    )
    lines.append("")
    lines.append("## Rule definitions")
    lines.append("")
    lines.append("```")
    lines.append("panel1_60s_mean = panel1_w.rolling('60s', min_periods=3).mean()")
    lines.append("step            = panel1_w_step  (panel1_w − 30-min rolling min)")
    lines.append("weather_demand  = outside_temp < 60 OR outside_temp > 75")
    lines.append("")
    lines.append("heat_pump:")
    lines.append(f"  1  if  panel1_60s > {HP_MIN_SPEC} AND weather_demand")
    lines.append(f"  0  if  panel1_w < {HP_ON_THRESHOLD - 100}")
    lines.append(f"  drop->NaN if 1 and panel1_w ∉ [{hp_low:.0f}, {hp_high:.0f}]")
    lines.append("")
    lines.append("solar_pump:")
    lines.append(f"  1  if  {SP_STEP_ON}<step<{SP_STEP_MAX} AND irradiance>200 AND heat_pump!=1")
    lines.append(f"  0  if  irradiance<50 OR step<{SP_STEP_OFF} OR panel1_w<{SP_ON_THRESHOLD} "
                 f"OR step>{SP_STEP_MAX} OR heat_pump=1")
    lines.append("  drop->NaN if 1 and panel1_w ∉ [100, 500]")
    lines.append("")
    lines.append("  0  if  step<100 OR panel1_w<100 OR heat_pump=1 OR step>1500")
    lines.append("```")
    lines.append("")
    lines.append("## Label counts — all data in parquet")
    lines.append("")
    lines.append("| head | rows | pos (1) | neg (0) | NaN |")
    lines.append("|---|---:|---:|---:|---:|")
    lines.append(f"| `heat_pump_label`      | {s_hp['rows']} | {s_hp['pos']} | {s_hp['neg']} | {s_hp['nan']} |")
    lines.append(f"| `solar_pump_label`     | {s_sp['rows']} | {s_sp['pos']} | {s_sp['neg']} | {s_sp['nan']} |")
    lines.append("")
    lines.append("## Label counts — May 6 onward (recent slice)")
    lines.append("")
    lines.append("| head | rows | pos (1) | neg (0) | NaN |")
    lines.append("|---|---:|---:|---:|---:|")
    lines.append(f"| `heat_pump_label`      | {s_hp_r['rows']} | {s_hp_r['pos']} | {s_hp_r['neg']} | {s_hp_r['nan']} |")
    lines.append(f"| `solar_pump_label`     | {s_sp_r['rows']} | {s_sp_r['pos']} | {s_sp_r['neg']} | {s_sp_r['nan']} |")
    lines.append("")
    lines.append("## Drops by power-consistency")
    lines.append("")
    lines.append(f"- Heat pump rule positives dropped: **{dropped_hp}**")
    lines.append(f"- Solar pump rule positives dropped: **{dropped_sp}**")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"[labels] wrote {OUT_MD}")
    print(f"[labels] all:    HP {s_hp}")
    print(f"[labels] all:    SP {s_sp}")
    print(f"[labels] May 6+: HP {s_hp_r}")
    print(f"[labels] May 6+: SP {s_sp_r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
