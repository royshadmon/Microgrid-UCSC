#!/usr/bin/env python3
"""Rule-only labels for Panel 3 — eight heads.

Source: panel3_claude_code_prompt.md §3.1 + §3.2 sequential refinement,
implemented in rule_engine.py.

Heads: refrigerator, dishwasher, microwave, dryer, washing_machine,
       pressure_pump, computers, tv_stereo.

Input:  data/panel1_60d.parquet
Output: data/panel3_60d_labeled.parquet
        services/iems/training/reports/panel3_label_consensus.md
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rule_engine import (  # noqa: E402
    HOUSE_TZ, PANEL3_APPLIANCES, apply_panel3_rules,
)

REPO = Path(__file__).resolve().parents[3]
IN = REPO / "data/panel1_60d.parquet"
OUT_PQ = REPO / "data/panel3_60d_labeled.parquet"
OUT_MD = REPO / "services/iems/training/reports/panel3_label_consensus.md"


def stats(s: pd.Series) -> dict:
    return {
        "rows": int(len(s)),
        "pos":  int((s == 1).sum()),
        "neg":  int((s == 0).sum()),
        "nan":  int(s.isna().sum()),
    }


def hourly_positive(s: pd.Series, idx: pd.DatetimeIndex) -> dict[int, int]:
    local = idx.tz_convert(HOUSE_TZ)
    hours = pd.Series(local.hour, index=idx)
    pos_idx = s.index[s == 1]
    if len(pos_idx) == 0:
        return {h: 0 for h in range(24)}
    pos_hours = hours.loc[pos_idx]
    counts = pos_hours.value_counts().to_dict()
    return {h: int(counts.get(h, 0)) for h in range(24)}


def diurnal_bar(counts: dict[int, int], width: int = 30) -> str:
    mx = max(counts.values()) if counts else 0
    if mx == 0:
        return "  (no positive examples)"
    lines = []
    for h in range(24):
        n = counts[h]
        bar = "#" * int(round(width * n / mx))
        lines.append(f"  {h:02d}h |{bar:<{width}}| {n}")
    return "\n".join(lines)


def on_run_lengths(s: pd.Series) -> list[int]:
    """Return contiguous-ON run lengths in samples (10s each)."""
    vals = (s == 1).astype(int).to_numpy()
    if vals.size == 0:
        return []
    diff = np.diff(np.concatenate([[0], vals, [0]]))
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    return [int(e - s_) for s_, e in zip(starts, ends)]


def main() -> int:
    if not IN.exists():
        print(f"[labels-p3] FATAL: {IN} not found — run extract_panel1.py first", file=sys.stderr)
        return 1
    df = pd.read_parquet(IN)
    print(f"[labels-p3] loaded {len(df)} rows; range {df.index.min()} -> {df.index.max()}")

    p3_seen = df["panel3_w"].notna().sum()
    print(f"[labels-p3] panel3_w observed: {p3_seen} ({100*p3_seen/len(df):.1f}%)")

    labels = apply_panel3_rules(df)
    for a in PANEL3_APPLIANCES:
        df[f"{a}_label"] = labels[a]

    OUT_PQ.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PQ)
    print(f"[labels-p3] wrote {OUT_PQ}")

    s = {a: stats(labels[a]) for a in PANEL3_APPLIANCES}
    diurnal = {a: hourly_positive(labels[a], df.index) for a in PANEL3_APPLIANCES}
    runs = {a: on_run_lengths(labels[a]) for a in PANEL3_APPLIANCES}

    cutoff = df.index.max() - pd.Timedelta(days=7)
    recent = df.index >= cutoff
    s_recent = {a: stats(labels[a][recent]) for a in PANEL3_APPLIANCES}

    lines: list[str] = []
    lines.append("# Panel 3 — Rule labels (eight heads)")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append(
        "Heads: `refrigerator`, `dishwasher`, `microwave`, `dryer`, "
        "`washing_machine`, `pressure_pump`, `computers`, `tv_stereo`. "
        "Rule-only; no LLM supervision in this run. Starting point: "
        "`panel3_claude_code_prompt.md` §3.1 + §3.2 sequential constraint. "
        "Calibrated against 35 days of accumulated data for this house — "
        "mid-range heads (washer, pump, computers, TV) use a "
        "*baseline-step* formulation (`panel3_w − 30 min rolling minimum`) "
        "instead of raw power, because panel3 spends ~76% of time in the "
        "200–500 W always-on baseline (fridge cycling + networking + idle "
        "computers) which would otherwise be tagged as appliance activity. "
        "Large clearly-separated signals (dryer, dishwasher) keep raw-power "
        "rules. Implementation: `services/iems/training/rule_engine.py`."
    )
    lines.append("")
    lines.append(f"Data window: `{df.index.min()}` → `{df.index.max()}` "
                 f"({len(df)} rows on 10s grid; `panel3_w` observed on "
                 f"{p3_seen} rows / {100*p3_seen/len(df):.1f}%).")
    lines.append("")
    lines.append("## Rule definitions (paraphrase)")
    lines.append("")
    lines.append("Rules apply in order of signal size so smaller heads can")
    lines.append("be conditioned on the absence of bigger appliances.")
    lines.append("")
    lines.append("```")
    lines.append("p3_60s     = panel3_w.rolling('60s').mean()")
    lines.append("p3_delta   = panel3_w.diff()")
    lines.append("p3_step    = panel3_w − panel3_w.rolling('30min').min()")
    lines.append("p3_fridge  = panel3_w.rolling('4h').quantile(0.1)")
    lines.append("local_hour = ts.tz_convert('America/Los_Angeles').hour")
    lines.append("")
    lines.append("dryer         [raw] : 1 if 3500<p3_60s<7500 | 0 if panel3_w<2000")
    lines.append("microwave     [raw] : 1 if p3_delta>600 AND 800<p3_60s<1700 AND dryer!=1")
    lines.append("                      (rising-edge to catch <5-min bursts)")
    lines.append("                      0 if panel3_w<600")
    lines.append("dishwasher    [raw] : 1 if 1000<p3_60s<2000 AND dryer/mw!=1")
    lines.append("                      0 if panel3_w<600")
    lines.append("washing_mach. [step]: 1 if 500<p3_step<2000 AND dryer/mw/dw!=1")
    lines.append("                      0 if panel3_w<250")
    lines.append("pressure_pump [step]: 1 if 400<p3_step<1000 AND dryer/mw/dw/wm!=1")
    lines.append("                      0 if panel3_w<250")
    lines.append("refrigerator        : 1 if 50<p3_fridge<250 (always-on baseline)")
    lines.append("                      0 if p3_fridge<30   (very rare at this house)")
    lines.append("computers     [step]: 1 if 100<p3_step<500 AND 7<=h<=22 AND big!=1")
    lines.append("                      0 if NOT work hours OR panel3_w<100")
    lines.append("tv_stereo     [step]: 1 if 80<p3_step<200 AND (h>=17 OR h<=1) AND big/comp!=1")
    lines.append("                      0 if NOT evening OR panel3_w<70")
    lines.append("")
    lines.append("§3.2 refinement: a dryer-ON without a washer-ON in the")
    lines.append("prior 90 minutes is suspect → drop to NaN, don't force 0.")
    lines.append("```")
    lines.append("")
    lines.append("## Label counts — full window")
    lines.append("")
    lines.append("| head | rows | pos (1) | neg (0) | NaN | pos rate |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for a in PANEL3_APPLIANCES:
        ss = s[a]
        labelled = ss["pos"] + ss["neg"]
        rate = (ss["pos"] / labelled) if labelled else 0.0
        lines.append(f"| `{a}` | {ss['rows']} | {ss['pos']} | {ss['neg']} | {ss['nan']} | {rate:.4f} |")
    lines.append("")
    lines.append("## Label counts — last 7 days")
    lines.append("")
    lines.append("| head | rows | pos (1) | neg (0) | NaN |")
    lines.append("|---|---:|---:|---:|---:|")
    for a in PANEL3_APPLIANCES:
        ss = s_recent[a]
        lines.append(f"| `{a}` | {ss['rows']} | {ss['pos']} | {ss['neg']} | {ss['nan']} |")
    lines.append("")
    lines.append("## Contiguous ON-run length distribution (in 10s samples)")
    lines.append("")
    lines.append("| head | runs | mean | p50 | p90 | max |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for a in PANEL3_APPLIANCES:
        r = runs[a]
        if r:
            arr = np.array(r)
            lines.append(
                f"| `{a}` | {len(r)} | {arr.mean():.1f} | "
                f"{np.percentile(arr, 50):.0f} | {np.percentile(arr, 90):.0f} | {arr.max()} |"
            )
        else:
            lines.append(f"| `{a}` | 0 | – | – | – | – |")
    lines.append("")
    lines.append("## Diurnal histograms (positive-label counts by local hour)")
    lines.append("")
    for a in PANEL3_APPLIANCES:
        lines.append(f"### {a}")
        lines.append("```")
        lines.append(diurnal_bar(diurnal[a]))
        lines.append("```")
        lines.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"[labels-p3] wrote {OUT_MD}")
    for a in PANEL3_APPLIANCES:
        print(f"  {a:18s}  {s[a]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
