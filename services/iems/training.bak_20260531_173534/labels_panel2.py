#!/usr/bin/env python3
"""Rule-only labels for Panel 2 — four heads.

Source: panel2_claude_code_prompt.md §3.1, implemented in rule_engine.py.
Heads: water_heater, hair_dryer, sprinklers, bath_lights.

Input:  data/panel1_60d.parquet (contains panel2_w + weather; the file is
        named after Panel 1 but extract_panel1.py pulls all panel columns).
Output: data/panel2_60d_labeled.parquet
        services/iems/training/reports/panel2_label_consensus.md
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rule_engine import (  # noqa: E402
    HOUSE_TZ, PANEL2_APPLIANCES, apply_panel2_rules,
)

REPO = Path(__file__).resolve().parents[3]
IN = REPO / "data/panel1_60d.parquet"
OUT_PQ = REPO / "data/panel2_60d_labeled.parquet"
OUT_MD = REPO / "services/iems/training/reports/panel2_label_consensus.md"


def stats(s: pd.Series) -> dict:
    return {
        "rows": int(len(s)),
        "pos":  int((s == 1).sum()),
        "neg":  int((s == 0).sum()),
        "nan":  int(s.isna().sum()),
    }


def hourly_positive(s: pd.Series, idx: pd.DatetimeIndex) -> dict[int, int]:
    """Count positive labels (state=1) per local hour-of-day."""
    local = idx.tz_convert(HOUSE_TZ)
    hours = pd.Series(local.hour, index=idx)
    pos_idx = s.index[s == 1]
    if len(pos_idx) == 0:
        return {h: 0 for h in range(24)}
    pos_hours = hours.loc[pos_idx]
    counts = pos_hours.value_counts().to_dict()
    return {h: int(counts.get(h, 0)) for h in range(24)}


def diurnal_bar(counts: dict[int, int], width: int = 30) -> str:
    """Tiny ASCII bar chart for a 24-bucket diurnal histogram."""
    mx = max(counts.values()) if counts else 0
    if mx == 0:
        return "  (no positive examples)"
    lines = []
    for h in range(24):
        n = counts[h]
        bar = "#" * int(round(width * n / mx))
        lines.append(f"  {h:02d}h |{bar:<{width}}| {n}")
    return "\n".join(lines)


def main() -> int:
    if not IN.exists():
        print(f"[labels-p2] FATAL: {IN} not found — run extract_panel1.py first", file=sys.stderr)
        return 1
    df = pd.read_parquet(IN)
    print(f"[labels-p2] loaded {len(df)} rows; range {df.index.min()} -> {df.index.max()}")

    # Only rows where panel2_w is observed are useful here.
    p2_seen = df["panel2_w"].notna().sum()
    print(f"[labels-p2] panel2_w observed: {p2_seen} ({100*p2_seen/len(df):.1f}%)")

    labels = apply_panel2_rules(df)
    for a in PANEL2_APPLIANCES:
        df[f"{a}_label"] = labels[a]

    OUT_PQ.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PQ)
    print(f"[labels-p2] wrote {OUT_PQ}")

    s = {a: stats(labels[a]) for a in PANEL2_APPLIANCES}
    diurnal = {a: hourly_positive(labels[a], df.index) for a in PANEL2_APPLIANCES}

    # Recent slice
    cutoff = df.index.max() - pd.Timedelta(days=7)
    recent = df.index >= cutoff
    s_recent = {a: stats(labels[a][recent]) for a in PANEL2_APPLIANCES}

    lines: list[str] = []
    lines.append("# Panel 2 — Rule labels (four heads)")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append(
        "Heads: `water_heater`, `hair_dryer`, `sprinklers`, `bath_lights`. "
        "Rule-only labels; no LLM supervision in this run. Starting point: "
        "`panel2_claude_code_prompt.md` §3.1. Calibrated against 35 days of "
        "accumulated data for this house — small-signal rules "
        "(sprinklers, bath_lights) use a *baseline-step* formulation "
        "(`panel2_w − 30 min rolling minimum`) instead of raw power, "
        "because the always-on panel2 baseline (150–250 W on this site) "
        "would otherwise be tagged as appliance activity. "
        "Implementation: `services/iems/training/rule_engine.py`."
    )
    lines.append("")
    lines.append(f"Data window: `{df.index.min()}` → `{df.index.max()}` "
                 f"({len(df)} rows on 10s grid; `panel2_w` observed on "
                 f"{p2_seen} rows / {100*p2_seen/len(df):.1f}%).")
    lines.append("")
    lines.append("## Rule definitions (paraphrase)")
    lines.append("")
    lines.append("```")
    lines.append("p2_60s     = panel2_w.rolling('60s').mean()")
    lines.append("p2_step    = panel2_w − panel2_w.rolling('30min').min()")
    lines.append("irr_6h     = irradiance.rolling('6h').mean()")
    lines.append("local_hour = ts.tz_convert('America/Los_Angeles').hour")
    lines.append("")
    lines.append("water_heater:                              [raw power]")
    lines.append("  1  if  2000 < p2_60s < 4500")
    lines.append("  0  if  panel2_w < 300")
    lines.append("  0  if  irr_6h > 500 AND outside_temp > 65°F AND p2_60s < 1500")
    lines.append("        (solar boiler preheated the tank)")
    lines.append("")
    lines.append("hair_dryer:                                [raw power]")
    lines.append("  1  if  1100 < p2_60s < 1900 AND water_heater != 1")
    lines.append("  0  if  panel2_w < 300")
    lines.append("")
    lines.append("sprinklers:                                [baseline step]")
    lines.append("  am_pm = local_hour in [4..7] or [17..21]")
    lines.append("  1  if  50 < p2_step < 250 AND am_pm AND wh/hd != 1")
    lines.append("  0  if  NOT am_pm")
    lines.append("  0  if  p2_step < 25")
    lines.append("")
    lines.append("bath_lights:                               [baseline step]")
    lines.append("  evening = local_hour >= 18 OR local_hour <= 1")
    lines.append("  1  if  50 < p2_step < 250 AND evening AND wh/hd/spr != 1")
    lines.append("  0  if  NOT evening")
    lines.append("  0  if  p2_step < 25")
    lines.append("```")
    lines.append("")
    lines.append("## Label counts — full window")
    lines.append("")
    lines.append("| head | rows | pos (1) | neg (0) | NaN | pos rate |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for a in PANEL2_APPLIANCES:
        ss = s[a]
        labelled = ss["pos"] + ss["neg"]
        rate = (ss["pos"] / labelled) if labelled else 0.0
        lines.append(f"| `{a}` | {ss['rows']} | {ss['pos']} | {ss['neg']} | {ss['nan']} | {rate:.4f} |")
    lines.append("")
    lines.append("## Label counts — last 7 days")
    lines.append("")
    lines.append("| head | rows | pos (1) | neg (0) | NaN |")
    lines.append("|---|---:|---:|---:|---:|")
    for a in PANEL2_APPLIANCES:
        ss = s_recent[a]
        lines.append(f"| `{a}` | {ss['rows']} | {ss['pos']} | {ss['neg']} | {ss['nan']} |")
    lines.append("")
    lines.append("## Diurnal histograms (positive-label counts by local hour)")
    lines.append("")
    for a in PANEL2_APPLIANCES:
        lines.append(f"### {a}")
        lines.append("```")
        lines.append(diurnal_bar(diurnal[a]))
        lines.append("```")
        lines.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"[labels-p2] wrote {OUT_MD}")
    for a in PANEL2_APPLIANCES:
        print(f"  {a:14s}  {s[a]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
