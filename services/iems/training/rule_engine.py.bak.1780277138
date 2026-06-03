"""Rule-based NILM disaggregator.

Pure pandas. No model files, no LLM. One function per panel; each returns
a DataFrame of label columns aligned to the input index, where each column
is a Series in {0, 1, NaN}:
  - 1   = appliance ON (high-confidence rule trigger)
  - 0   = appliance OFF (high-confidence baseline)
  - NaN = ambiguous (drop in training; "unknown" at inference time)

Rule sources:
  - Panel 1: appliance_data_updated.txt + labels_panel1.py (already in repo)
  - Panel 2: panel2_claude_code_prompt.md §3.1
  - Panel 3: panel3_claude_code_prompt.md §3.1 + §3.2 sequential refinement

Expected input frame columns (index = UTC tz-aware DatetimeIndex):
  panel1_w, panel2_w, panel3_w, shop_w
  outside_temp, irradiance
Optional: panel1_w_step (computed here if absent).

Diurnal rules use America/Los_Angeles local time (the house tz).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from vacuum_detector import detect_vacuum  # cross-panel mobile-load rule

HOUSE_TZ = "America/Los_Angeles"

# ── Panel 1 thresholds (mirror labels_panel1.py) ────────────────────────
HP_ON_THRESHOLD = 300
HP_MIN_SPEC = 1500
HP_MAX_SPEC = 4000

SP_ON_THRESHOLD = 30
SP_STEP_ON = 40
SP_STEP_OFF = 10
SP_STEP_MAX = 300

# Vacuum cleaner constants kept for compatibility; vacuum is a mobile load
# (per appliance_data_updated.txt) and is not predicted from Panel 1 alone.
VC_STEP_MIN = 500
VC_STEP_MAX = 1400
VC_PANEL_MAX = 2000


# ── Panel 2 thresholds ──────────────────────────────────────────────────
# Calibrated against 35 days of data: panel2_w baseline (always-on, no
# appliance running) sits at 150–250 W on this house. Raw-power rules
# from the prompt would tag the baseline as sprinklers/bath_lights, so
# the small-signal rules switch to a baseline-step formulation:
# step = panel2_w − rolling_30min_min, only counts as ON when the
# *increment* above quiescent baseline lands in the appliance range.
WH_MIN = 2000
WH_MAX = 4000   # appliance_data_updated.txt: 2000-4000W
WH_OFF = 300
WH_SOLAR_PREHEAT_IRR_6H = 500
WH_SOLAR_PREHEAT_TEMP_F = 65
WH_SOLAR_DAMPED_W = 1500

HD_MIN = 1200   # appliance_data_updated.txt: 1200-1800W
HD_MAX = 1800   # appliance_data_updated.txt: 1200-1800W
HD_OFF = 500   # below doc on-threshold 800W

SPR_STEP_MIN = 50      # increment above panel2 baseline
SPR_STEP_MAX = 300   # appliance_data_updated.txt: 100-300W
SPR_AM_HOURS = (4, 7)
SPR_PM_HOURS = (17, 21)

BL_STEP_MIN = 80    # appliance_data_updated.txt: on=80W
BL_STEP_MAX = 300   # appliance_data_updated.txt: 100-300W
BL_EVENING_START_HOUR = 18
BL_EVENING_END_HOUR = 1


# ── Panel 3 thresholds ──────────────────────────────────────────────────
# Calibrated against 35 days of data: panel3_w spends ~76% of time in the
# 200–500 W baseline band (fridge cycling + always-on networking + idle
# computers). Raw-power rules from the prompt overfire on baseline, so
# small/medium signals switch to the baseline-step formulation. Large
# clearly-separated signals (dryer 3.5–7.5 kW; dishwasher ≥1 kW after
# microwave is masked) keep raw-power rules.
DRYER_MIN = 4000   # appliance_data_updated.txt: 4000-7000W
DRYER_MAX = 7200   # appliance_data_updated.txt: 4000-7000W (+margin)
DRYER_OFF = 2000           # well below dryer floor, above panel3 baseline

MW_DELTA = 600             # rising-edge magnitude (panel3.diff)
MW_MIN = 900    # appliance_data_updated.txt: 900-1500W               # raw panel3 in the burst band
MW_MAX = 1600   # appliance_data_updated.txt: 900-1500W (+margin)
MW_OFF = 600               # any non-burst < 600 W is not microwave

DW_MIN = 700    # appliance_data_updated.txt: 200-1800W (kept >baseline)              # raw panel3 (dishwasher dominant when running)
DW_MAX = 1900   # appliance_data_updated.txt: 200-1800W (+margin)
DW_OFF = 600               # below dishwasher signature

WM_STEP_MIN = 200  # appliance_data_updated.txt: 200-2000W          # step above baseline (rejects fridge+comp baseline)
WM_STEP_MAX = 2000
WM_OFF = 250               # below typical washer activity

PP_STEP_MIN = 400  # appliance_data_updated.txt: range 500-1000W; 400+margin to clear washer
# (washer claims 200-400W step band; pressure pump must clear it)          # step above baseline
PP_STEP_MAX = 1000
PP_OFF = 250

FRIDGE_BASELINE_MIN = 80    # appliance_data_updated.txt: 80-200W
FRIDGE_BASELINE_MAX = 200   # appliance_data_updated.txt: 80-200W
FRIDGE_OFF_BASELINE = 40    # below doc on-threshold 50W   # very rare; fridge is always-on at this house

COMP_STEP_MIN = 100  # appliance_data_updated.txt: on=100W (range 200-500W is full-draw)        # step above quiescent panel3 baseline
COMP_STEP_MAX = 500
COMP_OFF = 100             # below comp ON threshold
COMP_WORK_HOURS = (7, 22)

TV_STEP_MIN = 80
TV_STEP_MAX = 200
TV_OFF = 70
TV_EVENING_START_HOUR = 17
TV_EVENING_END_HOUR = 1


# ── Panel 1 appliance set (already labeled by labels_panel1.py — re-derived
#    here so realtime monitor doesn't depend on the offline labeler)
PANEL1_APPLIANCES = ("heat_pump", "solar_pump")  # vacuum_cleaner dropped: mobile load per appliance_data_updated.txt

PANEL2_APPLIANCES = ("water_heater", "hair_dryer", "sprinklers", "bath_lights")

PANEL3_APPLIANCES = (
    "refrigerator", "dishwasher", "microwave", "dryer",
    "washing_machine", "pressure_pump", "computers", "tv_stereo",
)

ALL_APPLIANCES = PANEL1_APPLIANCES + PANEL2_APPLIANCES + PANEL3_APPLIANCES


@dataclass
class AppliancePanel:
    appliance: str
    panel: str  # one of: "Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"


APPLIANCE_PANEL_MAP: dict[str, str] = {
    "heat_pump":        "Panel1 (HVAC)",
    "solar_pump":       "Panel1 (HVAC)",
    "water_heater":     "Panel2 (H2O)",
    "hair_dryer":       "Panel2 (H2O)",
    "sprinklers":       "Panel2 (H2O)",
    "bath_lights":      "Panel2 (H2O)",
    "vacuum_cleaner":   "mobile",   # cross-panel rule (vacuum_detector.py)
    "refrigerator":     "Panel3 (Kitchen)",
    "dishwasher":       "Panel3 (Kitchen)",
    "microwave":        "Panel3 (Kitchen)",
    "dryer":            "Panel3 (Kitchen)",
    "washing_machine":  "Panel3 (Kitchen)",
    "pressure_pump":    "Panel3 (Kitchen)",
    "computers":        "Panel3 (Kitchen)",
    "tv_stereo":        "Panel3 (Kitchen)",
}


def _nan_series(idx: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(np.nan, index=idx, dtype="float64")


def _local_hour(idx: pd.DatetimeIndex) -> pd.Series:
    """Return integer hour-of-day in the house's local timezone."""
    local = idx.tz_convert(HOUSE_TZ) if idx.tz is not None else idx.tz_localize("UTC").tz_convert(HOUSE_TZ)
    return pd.Series(local.hour, index=idx)


def _ensure_panel1_step(df: pd.DataFrame) -> pd.Series:
    """Recreate panel1_w_step if it's not already on the frame."""
    if "panel1_w_step" in df.columns and df["panel1_w_step"].notna().any():
        return df["panel1_w_step"]
    if "panel1_w" not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    baseline = df["panel1_w"].rolling("30min", min_periods=30).min()
    return (df["panel1_w"] - baseline).clip(lower=0)


# ───────────────────────────────────────────────────────────────────────
# Panel 1 — three rule heads (mirrors labels_panel1.py)
# ───────────────────────────────────────────────────────────────────────

def apply_panel1_rules(df: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame with columns heat_pump, solar_pump, vacuum_cleaner."""
    out = pd.DataFrame(index=df.index)
    if "panel1_w" not in df.columns:
        for a in PANEL1_APPLIANCES:
            out[a] = _nan_series(df.index)
        return out

    p1 = df["panel1_w"]
    p1_60s = p1.rolling("60s", min_periods=3).mean()
    step = _ensure_panel1_step(df)
    temp = df.get("outside_temp", pd.Series(np.nan, index=df.index))
    irr = df.get("irradiance", pd.Series(np.nan, index=df.index))
    weather_demand = (temp < 60) | (temp > 75)

    # heat_pump
    rule_hp = _nan_series(df.index)
    hp_on = (p1_60s > HP_MIN_SPEC) & weather_demand & p1.notna()
    hp_off = (p1 < (HP_ON_THRESHOLD - 100)) & p1.notna()
    rule_hp[hp_on] = 1
    rule_hp[hp_off] = 0
    hp_low, hp_high = 0.5 * HP_MIN_SPEC, 1.5 * HP_MAX_SPEC
    rule_hp[(rule_hp == 1) & ((p1 < hp_low) | (p1 > hp_high))] = np.nan

    # solar_pump
    rule_sp = _nan_series(df.index)
    sp_on = (
        (step > SP_STEP_ON) & (step < SP_STEP_MAX)
        & (irr > 200) & (rule_hp != 1)
        & p1.notna() & step.notna()
    )
    sp_off = (
        p1.notna() & step.notna()
        & (
            (irr < 50) | (step < SP_STEP_OFF)
            | (p1 < SP_ON_THRESHOLD) | (step > SP_STEP_MAX)
            | (rule_hp == 1)
        )
    )
    rule_sp[sp_on] = 1
    rule_sp[sp_off] = 0
    rule_sp[(rule_sp == 1) & ((p1 < 100) | (p1 > 500))] = np.nan

    out["heat_pump"] = rule_hp
    out["solar_pump"] = rule_sp
    return out


# ───────────────────────────────────────────────────────────────────────
# Panel 2 — four rule heads (Panel 2 prompt §3.1)
# ───────────────────────────────────────────────────────────────────────

def apply_panel2_rules(df: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame with columns water_heater, hair_dryer, sprinklers, bath_lights."""
    out = pd.DataFrame(index=df.index)
    if "panel2_w" not in df.columns:
        for a in PANEL2_APPLIANCES:
            out[a] = _nan_series(df.index)
        return out

    p2 = df["panel2_w"]
    p2_60s = p2.rolling("60s", min_periods=3).mean()
    # Baseline-step: the *increment* above the 30-min rolling minimum.
    # This separates real load activations from the house's always-on
    # panel2 baseline (150–250 W on this site).
    p2_baseline = p2.rolling("30min", min_periods=30).min()
    p2_step = (p2 - p2_baseline).clip(lower=0)
    temp = df.get("outside_temp", pd.Series(np.nan, index=df.index))
    irr = df.get("irradiance", pd.Series(np.nan, index=df.index))
    hour = _local_hour(df.index)

    # Water heater — solar boiler can preheat the tank on bright warm days.
    rule_wh = _nan_series(df.index)
    rule_wh[(p2_60s > WH_MIN) & (p2_60s < WH_MAX) & p2.notna()] = 1
    rule_wh[(p2 < WH_OFF) & p2.notna()] = 0
    irr_6h = irr.rolling("6h", min_periods=60).mean()
    solar_preheat = (irr_6h > WH_SOLAR_PREHEAT_IRR_6H) & (temp > WH_SOLAR_PREHEAT_TEMP_F)
    rule_wh[solar_preheat & (p2_60s < WH_SOLAR_DAMPED_W) & p2.notna()] = 0

    # Hair dryer — short bursts in the WH-clear band.
    rule_hd = _nan_series(df.index)
    rule_hd[(p2_60s > HD_MIN) & (p2_60s < HD_MAX) & (rule_wh != 1) & p2.notna()] = 1
    rule_hd[(p2 < HD_OFF) & p2.notna()] = 0

    # Sprinklers — small load, AM and PM clusters only. Detect the
    # *increment* above the panel2 baseline so we don't tag the always-on
    # baseline as sprinkler activity.
    am_pm = (
        ((hour >= SPR_AM_HOURS[0]) & (hour <= SPR_AM_HOURS[1]))
        | ((hour >= SPR_PM_HOURS[0]) & (hour <= SPR_PM_HOURS[1]))
    )
    rule_spr = _nan_series(df.index)
    rule_spr[
        (p2_step > SPR_STEP_MIN) & (p2_step < SPR_STEP_MAX) & am_pm
        & (rule_wh != 1) & (rule_hd != 1) & p2.notna() & p2_step.notna()
    ] = 1
    rule_spr[(~am_pm) & p2.notna()] = 0       # outside AM/PM → OFF
    rule_spr[(p2_step < SPR_STEP_MIN * 0.5) & p2_step.notna()] = 0

    # Master bath mirror lights — evening cluster, small load.
    evening = (hour >= BL_EVENING_START_HOUR) | (hour <= BL_EVENING_END_HOUR)
    rule_bl = _nan_series(df.index)
    rule_bl[
        (p2_step > BL_STEP_MIN) & (p2_step < BL_STEP_MAX) & evening
        & (rule_wh != 1) & (rule_hd != 1) & (rule_spr != 1)
        & p2.notna() & p2_step.notna()
    ] = 1
    rule_bl[(~evening) & p2.notna()] = 0      # outside evening → OFF
    rule_bl[(p2_step < BL_STEP_MIN * 0.5) & p2_step.notna()] = 0

    out["water_heater"] = rule_wh
    out["hair_dryer"] = rule_hd
    out["sprinklers"] = rule_spr
    out["bath_lights"] = rule_bl
    return out


# ───────────────────────────────────────────────────────────────────────
# Panel 3 — eight rule heads (Panel 3 prompt §3.1 + §3.2)
# ───────────────────────────────────────────────────────────────────────

def apply_panel3_rules(df: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame with the eight Panel 3 appliance columns."""
    out = pd.DataFrame(index=df.index)
    if "panel3_w" not in df.columns:
        for a in PANEL3_APPLIANCES:
            out[a] = _nan_series(df.index)
        return out

    p3 = df["panel3_w"]
    p3_60s = p3.rolling("60s", min_periods=3).mean()
    p3_delta = p3.diff()
    # 30-min baseline: fridge + always-on networking + idle computers.
    # Step is the increment above that baseline — the right signal for
    # mid-range appliances (washer, pump, computers, TV) that otherwise
    # get washed out by the ~200–500 W panel3 baseline on this house.
    p3_baseline = p3.rolling("30min", min_periods=30).min()
    p3_step = (p3 - p3_baseline).clip(lower=0)
    hour = _local_hour(df.index)

    # Order: biggest signals first so smaller heads can be conditioned on
    # the absence of bigger appliances (mirrors prompt §3.1 ordering).

    # Dryer (4–7 kW, 240V) — distinctive large draw.
    rule_dryer = _nan_series(df.index)
    rule_dryer[(p3_60s > DRYER_MIN) & (p3_60s < DRYER_MAX) & p3.notna()] = 1
    rule_dryer[(p3 < DRYER_OFF) & p3.notna()] = 0

    # Microwave — rising-edge detection because bursts are short (<5 min);
    # window-midpoint labels lose them otherwise.
    rising_mw = (p3_delta > MW_DELTA) & (p3_60s > MW_MIN) & (p3_60s < MW_MAX)
    rule_mw = _nan_series(df.index)
    rule_mw[rising_mw & (rule_dryer != 1) & p3.notna()] = 1
    rule_mw[(p3 < MW_OFF) & p3.notna()] = 0

    # Dishwasher — multi-stage; stage-1 heater is the easiest signature.
    rule_dw = _nan_series(df.index)
    rule_dw[
        (p3_60s > DW_MIN) & (p3_60s < DW_MAX)
        & (rule_dryer != 1) & (rule_mw != 1) & p3.notna()
    ] = 1
    rule_dw[(p3 < DW_OFF) & p3.notna()] = 0

    # Washing machine — multi-stage 20–60 min runs. Use baseline step
    # to reject the panel3 baseline (~200–500 W on this house).
    rule_wm = _nan_series(df.index)
    rule_wm[
        (p3_step > WM_STEP_MIN) & (p3_step < WM_STEP_MAX)
        & (rule_dryer != 1) & (rule_mw != 1) & (rule_dw != 1)
        & p3.notna() & p3_step.notna()
    ] = 1
    rule_wm[(p3 < WM_OFF) & p3.notna()] = 0
    # Step well below washer minimum → OFF even if raw panel is in baseline.
    rule_wm[(p3_step < WM_STEP_MIN * 0.4) & p3_step.notna() & (rule_dryer != 1)
            & (rule_mw != 1) & (rule_dw != 1)] = 0

    # Pressure pump — short cycles in the 400–1000W band above baseline.
    rule_pp = _nan_series(df.index)
    rule_pp[
        (p3_step > PP_STEP_MIN) & (p3_step < PP_STEP_MAX)
        & (rule_dryer != 1) & (rule_mw != 1) & (rule_dw != 1)
        & (rule_wm != 1) & p3.notna() & p3_step.notna()
    ] = 1
    rule_pp[(p3 < PP_OFF) & p3.notna()] = 0
    rule_pp[(p3_step < PP_STEP_MIN * 0.4) & p3_step.notna() & (rule_dryer != 1)
            & (rule_mw != 1) & (rule_dw != 1) & (rule_wm != 1)] = 0

    # Refrigerator — detect ACTIVE compressor cycles, not the always-on baseline.
    # The pre-existing baseline-band rule produced F1=1.000 because the panel3
    # quiescent draw is always in the fridge range — degenerate, not predictive.
    # New rule: ON requires both (a) quiescent baseline in fridge band AND
    # (b) recent cycling activity (panel3 std over last 30 min > 15 W) to
    # distinguish "fridge cycling" from "fridge present but compressor off".
    p3_fridge_baseline = p3.rolling("4h", min_periods=60).quantile(0.1)
    p3_cycle_activity = p3.rolling("30min", min_periods=30).std()
    fridge_band = ((p3_fridge_baseline > FRIDGE_BASELINE_MIN)
                   & (p3_fridge_baseline < FRIDGE_BASELINE_MAX))
    cycling = p3_cycle_activity > 15.0    # absolute std on a panel-watts series
    rule_fridge = _nan_series(df.index)
    rule_fridge[fridge_band & cycling & p3.notna()] = 1
    rule_fridge[fridge_band & ~cycling & p3.notna() & p3_cycle_activity.notna()] = 0
    rule_fridge[(p3_fridge_baseline < FRIDGE_OFF_BASELINE) & p3.notna()] = 0

    # Computers — small daytime load above baseline.
    work_hours = (hour >= COMP_WORK_HOURS[0]) & (hour <= COMP_WORK_HOURS[1])
    rule_comp = _nan_series(df.index)
    rule_comp[
        (p3_step > COMP_STEP_MIN) & (p3_step < COMP_STEP_MAX) & work_hours
        & (rule_dryer != 1) & (rule_mw != 1) & (rule_dw != 1)
        & (rule_wm != 1) & (rule_pp != 1)
        & p3.notna() & p3_step.notna()
    ] = 1
    rule_comp[(~work_hours) & p3.notna()] = 0
    rule_comp[(p3 < COMP_OFF) & p3.notna()] = 0

    # TV/stereo — small evening load above baseline. Overlaps computers;
    # time-of-day is the discriminator.
    evening = (hour >= TV_EVENING_START_HOUR) | (hour <= TV_EVENING_END_HOUR)
    rule_tv = _nan_series(df.index)
    rule_tv[
        (p3_step > TV_STEP_MIN) & (p3_step < TV_STEP_MAX) & evening
        & (rule_dryer != 1) & (rule_mw != 1) & (rule_dw != 1)
        & (rule_wm != 1) & (rule_pp != 1) & (rule_comp != 1)
        & p3.notna() & p3_step.notna()
    ] = 1
    rule_tv[(~evening) & p3.notna()] = 0
    rule_tv[(p3 < TV_OFF) & p3.notna()] = 0

    # §3.2 sequential constraint: a dryer-ON without a recent washer-ON is
    # suspect. Drop those rule positives to NaN rather than forcing OFF.
    washer_recent = (rule_wm.fillna(0) > 0).rolling("90min", min_periods=1).max()
    suspect_dryer = (rule_dryer == 1) & (washer_recent.fillna(0) < 1)
    rule_dryer[suspect_dryer] = np.nan

    out["refrigerator"] = rule_fridge
    out["dishwasher"] = rule_dw
    out["microwave"] = rule_mw
    out["dryer"] = rule_dryer
    out["washing_machine"] = rule_wm
    out["pressure_pump"] = rule_pp
    out["computers"] = rule_comp
    out["tv_stereo"] = rule_tv
    return out


# ───────────────────────────────────────────────────────────────────────
# Unified entry point
# ───────────────────────────────────────────────────────────────────────

def apply_rules(df: pd.DataFrame,
                panels: Iterable[str] = ("panel1", "panel2", "panel3")) -> pd.DataFrame:
    """Run rule labelers for all requested panels and return a single frame.

    Each output column is named after the appliance (e.g. `water_heater`)
    and is a Series in {0, 1, NaN}.
    """
    frames = []
    if "panel1" in panels:
        frames.append(apply_panel1_rules(df))
    if "panel2" in panels:
        frames.append(apply_panel2_rules(df))
    if "panel3" in panels:
        frames.append(apply_panel3_rules(df))
    # Cross-panel vacuum detector. Needs per-panel labels already computed
    # (they're used to mask out panels where another appliance owns the spike),
    # so apply it last. The detector adds two columns: vacuum_cleaner (state)
    # and vacuum_active_panel (which panel saw the spike, for debugging).
    if frames:
        merged = pd.concat([df] + frames, axis=1)
        # Rename label cols to match what detect_vacuum expects (suffix _label)
        rename_map = {a: f"{a}_label" for f in frames for a in f.columns}
        merged = merged.rename(columns=rename_map)
        vac_out = detect_vacuum(merged)
        frames.append(vac_out[["vacuum_cleaner", "vacuum_active_panel"]])
    return pd.concat(frames, axis=1) if frames else pd.DataFrame(index=df.index)
