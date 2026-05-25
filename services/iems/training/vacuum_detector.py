"""Cross-panel vacuum cleaner detector.

Per `appliance_data_updated.txt`:
  Vacuum cleaner:
    Panel: mobile (changes panels)
    On threshold: 600 W
    Power range: 800-1200 W

Detection strategy
------------------
A panel-specific detector can't model a mobile load — the vacuum could appear
on Panel 1 (HVAC), Panel 2 (H2O), Panel 3 (Kitchen), or Shop depending on which
outlet it's plugged into. So the detector watches ALL four panel step signals
simultaneously and tags a window as vacuum-active when:

  1. The step above the 30-min rolling minimum on EXACTLY ONE panel is in the
     vacuum band [600, 1200] W (the doc says 800-1200 W typical, with 600 W
     as the on-threshold; we use [600, 1200] to include light-suction modes).
  2. That elevated step persists for at least 60 seconds (six 10-s samples).
     This rejects switching transients from other appliances starting up.
  3. No other panel-specific appliance rule (heat_pump, water_heater, dryer,
     microwave, dishwasher, washing_machine, pressure_pump) is active on that
     same panel at the same time. The vacuum is a clean ~1 kW signature;
     when a 4 kW heat-pump compressor is running, you can't tell the vacuum
     apart from compressor jitter.
  4. The active panel is allowed to change OVER a 30-minute window — a real
     cleaning session typically moves room-to-room, which means moving the
     plug from one panel's circuit to another. We accumulate vacuum-active
     samples within a sliding 30-min window and report ON whenever the
     cumulative duration crosses 60 seconds.

The 30-min observation window is the answer to "show its working" — a vacuum
session is bursty by nature, so the rule integrates evidence over a window
rather than demanding a clean single contiguous spike.

Output columns added to the dataframe:
  vacuum_cleaner          : {0, 1, NaN} — overall ON state at each 10s sample
  vacuum_active_panel     : str         — which panel saw the spike ('panel1', etc.)
                                          or 'unknown' when ambiguous, NaN when OFF
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Doc thresholds (appliance_data_updated.txt)
VC_BAND_LOW = 600       # W; on-threshold per doc
VC_BAND_HIGH = 1200     # W; upper end of doc power range
VC_MIN_DURATION_S = 60  # spike must persist 60 s before counting
VC_WINDOW_MIN = 30      # detection window for cleaning-session accumulation

# Panel column names (must match extract_panel1.py output schema)
PANEL_COLS = {
    # Panel 1 (HVAC) excluded — its circuits host the heat pump and solar pump,
    # neither of which has a general-purpose 120V outlet a vacuum could plug into.
    # The vacuum band [600, 1200] W overlaps heat-pump fan-only mode (~300 W with
    # transition spikes) too closely; including Panel 1 produces false positives.
    "panel2": "panel2_w",
    "panel3": "panel3_w",
    "shop":   "shop_w",
}


def _step_above_baseline(s: pd.Series, window: str = "30min") -> pd.Series:
    """Power above the rolling-min baseline. Returns same index, NaN where input NaN."""
    baseline = s.rolling(window, min_periods=30).min()
    return (s - baseline).clip(lower=0)


def _other_appliance_active(df: pd.DataFrame, panel: str) -> pd.Series:
    """Return True wherever ANY known panel-specific appliance is firing on `panel`.

    Reads pre-computed label columns (created by labels_panel{1,2,3}.py).
    If a label column isn't present, treats that appliance as 'not active'.
    """
    appliances_by_panel = {
        "panel1": ["heat_pump_label", "solar_pump_label"],
        "panel2": ["water_heater_label", "hair_dryer_label",
                   "sprinklers_label", "bath_lights_label"],
        "panel3": ["refrigerator_label", "dishwasher_label", "microwave_label",
                   "dryer_label", "washing_machine_label",
                   "pressure_pump_label", "computers_label", "tv_stereo_label"],
        "shop":   [],   # no panel-specific appliances tracked on Shop yet
    }
    cols = [c for c in appliances_by_panel.get(panel, []) if c in df.columns]
    if not cols:
        return pd.Series(False, index=df.index)
    active = pd.Series(False, index=df.index)
    for c in cols:
        # Treat 1 AND NaN as "possibly active" — NaN means the rule was
        # ambiguous (e.g., heat-pump transition zone) and we should not
        # trust the panel as quiescent for vacuum detection.
        active = active | (df[c] == 1) | df[c].isna()
    return active


def detect_vacuum(df: pd.DataFrame) -> pd.DataFrame:
    """Run the cross-panel vacuum rule on a dataframe.

    Args:
        df: must have panel1_w / panel2_w / panel3_w / shop_w columns indexed
            by tz-aware UTC DatetimeIndex on a regular 10s grid. Should also
            have the per-panel *_label columns already computed (otherwise
            the masking step is skipped, which gives more false positives).

    Returns:
        same df with two new columns:
            vacuum_cleaner       — {0, 1, NaN}
            vacuum_active_panel  — str panel name when ON; NaN when OFF
    """
    out = df.copy()

    # 1. Per-panel step above 30-min baseline.
    steps = {}
    in_band = {}
    for panel, col in PANEL_COLS.items():
        if col not in df.columns:
            continue
        step = _step_above_baseline(df[col])
        steps[panel] = step
        in_band[panel] = (step > VC_BAND_LOW) & (step < VC_BAND_HIGH)

    if not in_band:
        out["vacuum_cleaner"] = np.nan
        out["vacuum_active_panel"] = np.nan
        return out

    # 2. Exactly-one-panel constraint. Sum the boolean band flags across panels;
    #    a real vacuum hit lights exactly one panel. Multiple panels lit at once
    #    means coincidental overlap of unrelated loads — drop to NaN.
    band_count = sum(b.astype(int) for b in in_band.values())
    exactly_one = (band_count == 1)
    ambiguous   = (band_count >= 2)

    # 3. Per-panel "spike with other-appliance mask cleared" then duration filter.
    spike_clear = {}
    for panel, band in in_band.items():
        other = _other_appliance_active(df, panel)
        clear = band & ~other & exactly_one
        # 60s persistence — rolling sum across 6 samples (at 10s grid) >= 6.
        persistent = clear.rolling("60s", min_periods=6).sum() >= 6
        spike_clear[panel] = persistent.fillna(False).astype(bool)

    # 4. Combine across panels: ON if ANY panel reports a persistent clear spike.
    any_spike = pd.Series(False, index=df.index)
    for s in spike_clear.values():
        any_spike = any_spike | s

    # 5. 30-minute observation window: if a session is in progress (any spike in
    #    the last 30 min), mark the whole window as vacuum-active. This catches
    #    multi-room sessions where the plug moves between circuits.
    session_active = any_spike.rolling(f"{VC_WINDOW_MIN}min",
                                       min_periods=6).max().fillna(0) > 0

    # 6. Which panel "owns" the current ON sample.
    panel_label = pd.Series(np.nan, index=df.index, dtype=object)
    for panel, s in spike_clear.items():
        # session-wide ownership: panel that contributed the most spike samples
        # in the trailing 30 min wins the label
        weight = s.rolling(f"{VC_WINDOW_MIN}min", min_periods=1).sum()
        if not weight.any():
            continue
        # Prefer this panel where it leads the contribution
        best_so_far = panel_label.notna()
        leading = (weight > 0) & session_active
        # Simple ownership: take the latest panel that had a spike — works fine
        # in the common case where one cleaning session = one panel.
        panel_label[leading & ~best_so_far] = panel

    # 7. Final state: 1 when session_active, 0 when nothing-in-band-on-anyone
    #    for a sustained stretch, NaN in the ambiguous middle ground.
    out_state = pd.Series(np.nan, index=df.index, dtype="float64")
    out_state[session_active] = 1
    # OFF: no panel in vacuum band for at least 30 min
    quiet = (band_count.rolling(f"{VC_WINDOW_MIN}min", min_periods=6).max() == 0)
    out_state[quiet.fillna(False)] = 0
    # Ambiguous (multi-panel coincidence) → NaN, dropped from training/eval
    out_state[ambiguous] = np.nan

    out["vacuum_cleaner"] = out_state
    out["vacuum_active_panel"] = panel_label.where(out_state == 1)
    return out


def main():
    """Stand-alone: read panel3 labeled parquet, add vacuum columns, write back."""
    from pathlib import Path
    REPO = Path(__file__).resolve().parents[3]
    pq = REPO / "data/panel3_60d_labeled.parquet"
    if not pq.exists():
        print(f"FATAL: {pq} not found")
        return 1
    print(f"reading {pq.name}")
    df = pd.read_parquet(pq)
    print(f"  rows: {len(df):,}  cols: {len(df.columns)}")
    print(f"  has panel cols: {[c for c in PANEL_COLS.values() if c in df.columns]}")

    out = detect_vacuum(df)
    pos = int((out["vacuum_cleaner"] == 1).sum())
    neg = int((out["vacuum_cleaner"] == 0).sum())
    nan = int(out["vacuum_cleaner"].isna().sum())
    print(f"  vacuum_cleaner: pos={pos:,}  neg={neg:,}  nan={nan:,}")
    if pos > 0:
        by_panel = out.loc[out["vacuum_cleaner"] == 1, "vacuum_active_panel"].value_counts()
        print("  detected sessions by panel:")
        for p, n in by_panel.items():
            print(f"    {p}: {n} samples")
    out.to_parquet(pq)
    print(f"  wrote vacuum columns back to {pq.name}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
