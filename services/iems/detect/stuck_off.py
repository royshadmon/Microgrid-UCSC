#!/usr/bin/env python3
"""Stuck-off detector: an appliance that always cycled has stopped entirely.

WHY THIS EXISTS
    On 2026-02-20 at ~19:30 the water heater stopped heating. The panel breaker
    was still ON, so nothing looked wrong electrically -- the ECO (thermal
    cutout on the tank) had tripped. It went unnoticed until someone took a
    lukewarm shower roughly a week later, and was only then confirmed from
    eGauge history.

    That is the failure class this detector is for. Every other detector in the
    system watches for a signal getting BIGGER: spikes, breaker margin, leaks.
    This one watches for a signal going AWAY. Silence is the symptom, and
    silence is exactly what threshold alarms never fire on.

    A tripped ECO usually means a stuck thermostat or a grounded element rather
    than a random event, so a repeat trip is a reason to call an electrician:
    https://hotwateruniversity.dozuki.com/Guide/Energy+Cutoff+(ECO)+Tripped/49

METHOD
    For each monitored appliance, learn its normal cycling rhythm from a long
    baseline window (default 21 days), then alarm when the observed gap since
    the last cycle exceeds what that rhythm can explain.

    The gap threshold is the baseline p99 inter-cycle gap, floored by a
    per-appliance minimum. p99 rather than max: one holiday absence should not
    permanently desensitise the detector.

    Deliberately NOT a fixed timeout. A water heater's normal gap is hours; a
    dryer's is days. A single "24h of silence" rule would either miss the water
    heater for a day or scream about the dryer every weekend.

SUPPRESSION
    Vacancy is the obvious false positive: nobody home means nothing cycles.
    If an occupancy entity is supplied and reads away, the detector holds fire
    and says so rather than silently skipping.

Usage:
    python3 stuck_off.py --once
    python3 stuck_off.py --backtest analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, "services")
sys.path.insert(0, "services/iems/detect")

log = logging.getLogger("stuck_off")

# Per-appliance expectations. min_gap_h is a floor on the alarm threshold so a
# noisy baseline cannot make the detector hair-trigger; max_quiet_h is a hard
# ceiling that fires regardless of baseline.
# measure: "raw" reads panel power directly (big discrete loads);
# "osc" subtracts a 20-min rolling floor first (loads that cycle ON TOP of a
# baseline). A fridge never pushes the panel 70W above zero -- it pushes it 70W
# above whatever else is running -- so reading it raw finds no cycles at all.
WATCH = {
    "water_heater": dict(panel="Panel2 (H2O)", measure="raw", on_w=2000, min_gap_h=8, max_quiet_h=36,
                         severity="critical",
                         note="ECO trip / failed element. The Feb 2026 incident."),
    "refrigerator": dict(panel="Panel3 (Kitchen)", measure="osc", on_w=70, min_gap_h=2, max_quiet_h=8,
                         severity="critical",
                         note="Food safety. Aggregate of kitchen + garage cold loads."),
    "heat_pump":    dict(panel="Panel1 (HVAC)", measure="raw", on_w=2500, min_gap_h=12, max_quiet_h=72,
                         severity="warning",
                         note="Seasonal -- expect long quiet spells in shoulder months."),
    "pressure_pump": dict(panel="Panel3 (Kitchen)", measure="osc", on_w=500, min_gap_h=12, max_quiet_h=72,
                          severity="warning", note="Well/booster pump."),
}

BASELINE_DAYS = 21


def as_measure(series: pd.Series, measure: str) -> pd.Series:
    """Match the labeller's physics: raw for discrete loads, oscillation above a
    20-min rolling floor for loads that cycle on top of a baseline."""
    v = series.abs()
    if measure == "osc":
        return v - v.rolling("20min").min()
    return v


def cycles(series: pd.Series, on_w: float, measure: str = "raw") -> pd.DatetimeIndex:
    """Timestamps where the appliance transitions OFF -> ON."""
    on = as_measure(series, measure) >= on_w
    starts = on & ~on.shift(1, fill_value=False)
    return series.index[starts]


def covered_gaps_h(starts: pd.DatetimeIndex, index: pd.DatetimeIndex,
                   cadence_s: float) -> np.ndarray:
    """Inter-cycle gaps counting only time the meter was actually reporting.

    The eGauge feed has real outages -- this dataset is missing ~70 of its 136
    calendar days, including one 46-day hole. Wall-clock gaps across an outage
    look exactly like a dead appliance, so silence is only evidence of failure
    when we were listening. Each gap is therefore measured as
    (samples observed in the interval x cadence), not as end minus start.
    """
    if len(starts) < 2:
        return np.array([])
    pos = np.searchsorted(index.values, starts.values)
    out = []
    for a, b in zip(pos[:-1], pos[1:]):
        out.append(max(b - a, 0) * cadence_s / 3600.0)
    return np.array(out)


def gap_stats(starts: pd.DatetimeIndex, index: pd.DatetimeIndex | None = None,
              cadence_s: float | None = None) -> dict:
    if len(starts) < 3:
        return {}
    if index is not None and cadence_s:
        gaps_h = covered_gaps_h(starts, index, cadence_s)
    else:
        gaps_h = np.diff(starts.values).astype("timedelta64[s]").astype(float) / 3600.0
    return {
        "n_cycles": int(len(starts)),
        "median_gap_h": float(np.median(gaps_h)),
        "p90_gap_h": float(np.percentile(gaps_h, 90)),
        "p99_gap_h": float(np.percentile(gaps_h, 99)),
        "max_gap_h": float(gaps_h.max()),
    }


def evaluate(piv: pd.DataFrame, now: datetime | None = None,
             occupied: bool | None = None) -> list[dict]:
    now = now or (piv.index.max().to_pydatetime().replace(tzinfo=timezone.utc))
    out = []
    base_start = now - timedelta(days=BASELINE_DAYS)

    for app, cfg in WATCH.items():
        col = cfg["panel"]
        if col not in piv.columns:
            continue
        s = piv[col].dropna()
        if s.empty:
            continue
        idx = s.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
            s = pd.Series(s.values, index=idx)

        base = s[(s.index >= base_start) & (s.index <= now)]
        if base.empty:
            continue
        starts = cycles(base, cfg["on_w"], cfg.get("measure", "raw"))
        cad = float(np.median(np.diff(base.index.values).astype("timedelta64[s]").astype(float))) if len(base) > 2 else 1.0
        st = gap_stats(starts, base.index, cad)
        if not st:
            out.append({"appliance": app, "status": "insufficient_baseline",
                        "n_cycles": int(len(starts))})
            continue

        last = starts.max()
        quiet_h = (now - last.to_pydatetime().replace(tzinfo=timezone.utc)).total_seconds() / 3600.0
        thresh = max(st["p99_gap_h"], float(cfg["min_gap_h"]))
        hard = float(cfg["max_quiet_h"])
        tripped = quiet_h > thresh or quiet_h > hard

        rec = {
            "appliance": app, "panel": col, "quiet_h": round(quiet_h, 1),
            "threshold_h": round(thresh, 1), "hard_ceiling_h": hard,
            "last_cycle": str(last), "baseline": {k: round(v, 2) for k, v in st.items()},
            "severity": cfg["severity"], "note": cfg["note"],
            "status": "stuck_off" if tripped else "ok",
        }

        if tripped and occupied is False:
            rec["status"] = "suppressed_vacant"
            rec["message"] = ("%s has not cycled for %.1f h, but the house reads "
                              "vacant -- holding fire." % (app, quiet_h))
        elif tripped:
            rec["message"] = (
                "%s has not run for %.1f h. Its normal gap is %.1f h "
                "(p99 %.1f h) over the last %d days. The circuit may still show "
                "power at the panel: check the appliance's own safety cutout."
                % (app, quiet_h, st["median_gap_h"], st["p99_gap_h"], BASELINE_DAYS))
            rec["action"] = ("Check the appliance thermal cutout / ECO reset before "
                             "assuming a breaker fault." if app == "water_heater"
                             else "Verify the appliance is powered and operating.")
        out.append(rec)
    return out


def load_pivot(parquet: str) -> pd.DataFrame:
    d = pd.read_parquet(parquet, columns=["ts", "channel", "w"])
    piv = d.pivot_table(index="ts", columns="channel", values="w",
                        aggfunc="first").sort_index()
    for c in piv.columns:
        piv[c] = piv[c].abs()
    return piv


def run_backtest(parquet: str) -> None:
    """Replay history, reporting the longest silence per appliance.

    The Feb 2026 water-heater outage is NOT in this dataset (it begins
    2026-03-06), so this cannot prove the detector would have caught that
    specific event. What it does show is the false-positive rate against
    normal operation, which is the part that decides whether the alarm is
    usable at all.
    """
    piv = load_pivot(parquet)
    print("backtest window: %s .. %s\n" % (piv.index.min(), piv.index.max()))
    for app, cfg in WATCH.items():
        col = cfg["panel"]
        if col not in piv.columns:
            continue
        s = piv[col].dropna()
        starts = cycles(s, cfg["on_w"], cfg.get("measure", "raw"))
        cad = float(np.median(np.diff(s.index.values).astype("timedelta64[s]").astype(float)))
        st = gap_stats(starts, s.index, cad)
        if not st:
            print("%-15s no cycles above %d W" % (app, cfg["on_w"]))
            continue
        thresh = max(st["p99_gap_h"], float(cfg["min_gap_h"]))
        gaps_h = np.diff(starts.values).astype("timedelta64[s]").astype(float) / 3600.0
        days = (piv.index.max() - piv.index.min()).days or 1
        gaps_h = covered_gaps_h(starts, s.index, cad)
        adaptive = int((gaps_h > thresh).sum())
        hard = float(cfg["max_quiet_h"])
        hard_fire = int((gaps_h > hard).sum())
        print("%-15s %-4s on>%5dW  cycles=%-6d median=%6.1fh  p99=%7.1fh  max=%7.1fh"
              % (app, cfg.get("measure", "raw"), cfg["on_w"], st["n_cycles"],
                 st["median_gap_h"], st["p99_gap_h"], st["max_gap_h"]))
        print("%-15s adaptive p99=%7.1fh -> %3d alerts (%.2f/mo)   |   "
              "hard ceiling %5.1fh -> %3d alerts (%.2f/mo)\n"
              % ("", thresh, adaptive, adaptive / days * 30,
                 hard, hard_fire, hard_fire / days * 30))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", metavar="PARQUET")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--parquet",
                    default="analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(levelname)-7s %(message)s")
    if a.backtest:
        run_backtest(a.backtest)
    else:
        piv = load_pivot(a.parquet)
        for r in evaluate(piv):
            print(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
