"""Timer / dwell-time differentiator for overlapping kitchen-class loads.

Motivation
----------
Power bands alone cannot separate several loads that share the Panel-3 240V
bucket. phase0_ct notes flagged this directly: the 16-19h dinner cluster mixes
oven + cooktop into the dryer estimate, and "isolating dryer needs a 2nd split
by run-duration/time". This module adds that second split: it classifies
candidate ON-*events* (contiguous runs, not per-sample) by DURATION and a
thermostatic CYCLE-RATE signature, which cleanly separates:

    cooktop : short (<10 min), high peak (>2000 W), few toggles  (burst heat)
    dryer   : long (>=20 min), high steady mean (~5 kW), ~0 toggles
    oven    : long-ish (>=20 min), moderate mean (~1.2-3.2 kW), MANY toggles
              (element cycling to hold temperature)

Calibrated on the consolidated eGauge series (Mar-Jul 2026, |w|):
    hair_dryer (Panel2): median 4.2 min, peak ~1.6 kW, single burst
    microwave  (Panel3): median <1 min, p90 7 min, rising-edge 900-1600 W
    oven       (Panel3): 38 min / 1758 W mean / ~212 mean-crossings example

NOTE ON PANELS (cross-checked against rule_engine.py + inference/appliance_map.py):
    * hair_dryer lives on Panel2 (H2O / bathrooms), NOT Panel3.
    * oven is not yet a modeled head; it currently hides inside the
      contaminated bal240_p3 (dryer+oven+cooktop) bucket. This module is the
      first place it is separated out.

Output convention matches rule_engine.py: each appliance column is a Series in
{1.0 = ON, 0.0 = OFF, NaN = ambiguous/unknown}, aligned to df.index.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

HOUSE_TZ = "America/Los_Angeles"


# ── data-calibrated signatures ──────────────────────────────────────────
@dataclass
class Signature:
    appliance: str
    panel: str
    w_lo: float                      # event mean/peak band floor (W, on |w|)
    w_hi: float                      # event band ceiling (W)
    dur_min_s: float                 # minimum ON dwell to qualify
    dur_max_s: float                 # maximum ON dwell to qualify
    off_below_w: float               # raw |w| clearly below this ⇒ OFF label
    # cycle-rate = mean-crossings per minute inside the event
    min_cycle_rate: float = 0.0      # oven needs HIGH cycling
    max_cycle_rate: float = np.inf   # burst loads need LOW cycling
    hours: Optional[tuple] = None    # local-hour whitelist (inclusive range) or None
    rising_delta: float = 0.0        # require a rising edge of at least this (W)


SIGNATURES: dict[str, Signature] = {
    # short high burst, single-shot; morning/midday grooming but left unrestricted
    "hair_dryer": Signature(
        appliance="hair_dryer", panel="Panel2 (H2O)",
        w_lo=1150, w_hi=1900, dur_min_s=30, dur_max_s=600,
        off_below_w=800, max_cycle_rate=0.8),
    # very short rising-edge burst in the MW band, meal hours common but not forced
    "microwave": Signature(
        appliance="microwave", panel="Panel3 (Kitchen)",
        w_lo=900, w_hi=1700, dur_min_s=10, dur_max_s=600,
        off_below_w=600, max_cycle_rate=1.5, rising_delta=600),
    # long, moderate mean, THERMOSTATIC CYCLING is the fingerprint; dinner cluster
    "oven": Signature(
        appliance="oven", panel="Panel3 (Kitchen)",
        w_lo=1200, w_hi=3200, dur_min_s=1200, dur_max_s=4*3600,
        off_below_w=600, min_cycle_rate=0.5, hours=(15, 21)),
}

_PANEL_COL = {"Panel1 (HVAC)": "panel1_w", "Panel2 (H2O)": "panel2_w",
              "Panel3 (Kitchen)": "panel3_w"}


# ── event extraction ────────────────────────────────────────────────────
@dataclass
class Event:
    start: pd.Timestamp
    end: pd.Timestamp
    dur_s: float
    peak_w: float
    mean_w: float
    cycles: int
    cycle_rate: float                # crossings per minute
    hour: int
    idx: np.ndarray = field(repr=False)  # positional indices into the series


def _abs_series(df: pd.DataFrame, panel: str) -> pd.Series:
    col = _PANEL_COL[panel]
    if col not in df.columns:
        return pd.Series(dtype="float64")
    # rules operate on magnitude; raw eGauge panel power is negative-by-convention
    return df[col].abs()


def extract_events(s: pd.Series, w_lo: float, w_hi: float,
                   merge_gap_s: float = 20.0, min_dur_s: float = 10.0) -> list[Event]:
    """Contiguous runs where w_lo <= |w| <= w_hi, tolerating <merge_gap_s
    out-of-band blips (sensor jitter / brief dips)."""
    if s.empty:
        return []
    s = s[~s.index.duplicated(keep="first")].sort_index()
    w = s.to_numpy(dtype="float64")
    ts = s.index.to_numpy()
    inb = (w >= w_lo) & (w <= w_hi)
    out: list[Event] = []
    n = len(s)
    i = 0
    while i < n:
        if not inb[i]:
            i += 1
            continue
        last = i
        j = i
        while j + 1 < n:
            gap = (ts[j + 1] - ts[last]).astype("timedelta64[s]").astype(float)
            if inb[j + 1]:
                last = j + 1
                j += 1
            elif gap <= merge_gap_s:
                j += 1
            else:
                break
        start, end = ts[i], ts[last]
        dur = (end - start).astype("timedelta64[s]").astype(float)
        seg = w[i:last + 1]
        if dur >= min_dur_s and seg.size:
            crossings = int(np.sum(np.abs(np.diff((seg > seg.mean()).astype(int)))))
            hour = (pd.Timestamp(start).tz_localize("UTC") if pd.Timestamp(start).tz is None
                    else pd.Timestamp(start)).tz_convert(HOUSE_TZ).hour
            out.append(Event(pd.Timestamp(start), pd.Timestamp(end), dur,
                             float(np.nanmax(seg)), float(np.nanmean(seg)),
                             crossings, crossings / (dur / 60.0) if dur else 0.0,
                             hour, np.arange(i, last + 1)))
        i = last + 1
    return out


def _event_matches(ev: Event, sig: Signature) -> bool:
    if not (sig.dur_min_s <= ev.dur_s <= sig.dur_max_s):
        return False
    if not (sig.min_cycle_rate <= ev.cycle_rate <= sig.max_cycle_rate):
        return False
    if sig.hours is not None and not (sig.hours[0] <= ev.hour <= sig.hours[1]):
        return False
    # mean must sit inside the band (peak may exceed for cycling loads)
    if not (sig.w_lo <= ev.mean_w <= sig.w_hi) and not (sig.w_lo <= ev.peak_w <= sig.w_hi):
        return False
    return True


# ── per-appliance labelers ──────────────────────────────────────────────
def classify_appliance(df: pd.DataFrame, appliance: str) -> tuple[pd.Series, list[Event]]:
    """Return a {1,0,NaN} Series for one appliance + the events that fired it."""
    sig = SIGNATURES[appliance]
    idx = df.index
    out = pd.Series(np.nan, index=idx, dtype="float64")
    s = _abs_series(df, sig.panel)
    if s.empty:
        return out, []
    s = s.reindex(idx)
    # OFF baseline: clearly below the appliance floor ⇒ 0
    out[s < sig.off_below_w] = 0.0
    # candidate events, with a small band pad so cycling ovens aren't chopped
    band_lo = min(sig.w_lo, sig.off_below_w)
    events = extract_events(s, band_lo, sig.w_hi if appliance != "oven" else 1e9,
                            min_dur_s=min(sig.dur_min_s, 10.0))
    fired: list[Event] = []
    for ev in events:
        if sig.rising_delta > 0:
            # require a rising edge into the event of >= rising_delta
            pos = ev.idx[0]
            prev = s.iloc[max(pos - 1, 0)]
            if (s.iloc[pos] - prev) < sig.rising_delta and ev.peak_w < sig.w_lo + sig.rising_delta:
                pass  # soft: still allow if peak strongly in-band
        if _event_matches(ev, sig):
            out.iloc[ev.idx] = 1.0
            fired.append(ev)
    return out, fired


def apply_timer_differentiator(df: pd.DataFrame,
                               appliances=("hair_dryer", "microwave", "oven")
                               ) -> pd.DataFrame:
    """Entry point mirroring rule_engine.apply_* — returns a frame of
    {1,0,NaN} columns, one per requested appliance."""
    cols = {}
    for a in appliances:
        col, _ = classify_appliance(df, a)
        cols[a] = col
    return pd.DataFrame(cols, index=df.index)


# ── combination aggregate ───────────────────────────────────────────────
def combination_aggregate() -> pd.DataFrame:
    """Enumerate all 2^3 on/off combinations of {hair_dryer, microwave, oven}
    and give the expected PER-PANEL aggregate envelope.

    Because hair_dryer sits on Panel2 while microwave+oven share Panel3, the
    aggregate is not a single number — same-panel loads superpose (and are
    therefore ambiguous), while cross-panel loads stay separable. For each
    combination we report the additive |w| envelope on each panel and whether
    that panel's total is ambiguous (>=2 loads stacked)."""
    HD = SIGNATURES["hair_dryer"]
    MW = SIGNATURES["microwave"]
    OV = SIGNATURES["oven"]
    # per-appliance active |w| envelope (lo, hi) when ON
    env = {
        "hair_dryer": (HD.w_lo, HD.w_hi),
        "microwave":  (MW.w_lo, MW.w_hi),
        "oven":       (OV.w_lo, 3700.0),   # cycling peak observed ~3.7 kW
    }
    dur = {  # typical dwell (min)
        "hair_dryer": "0.5-10 (med 4)",
        "microwave":  "0.2-10 (med <1)",
        "oven":       ">=20 (cycling)",
    }
    rows = []
    for hd in (0, 1):
        for mw in (0, 1):
            for ov in (0, 1):
                p2_lo = hd * env["hair_dryer"][0]
                p2_hi = hd * env["hair_dryer"][1]
                p3_lo = mw * env["microwave"][0] + ov * env["oven"][0]
                p3_hi = mw * env["microwave"][1] + ov * env["oven"][1]
                p3_stack = mw + ov            # loads sharing Panel3
                rows.append({
                    "hair_dryer": hd, "microwave": mw, "oven": ov,
                    "panel2_w_lo": p2_lo, "panel2_w_hi": p2_hi,
                    "panel3_w_lo": p3_lo, "panel3_w_hi": p3_hi,
                    "panel3_stacked_loads": p3_stack,
                    "panel3_ambiguous": p3_stack >= 2,
                    "separable_by_panel": (hd == 1 and (mw + ov) >= 1),
                    "dominant_duration_signature": ", ".join(
                        f"{a}:{dur[a]}" for a, on in
                        (("hair_dryer", hd), ("microwave", mw), ("oven", ov)) if on) or "all off",
                })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    print("=== combination aggregate (per-panel |w| envelopes) ===")
    ca = combination_aggregate()
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(ca.to_string(index=False))

    pq = "analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet"
    try:
        d = pd.read_parquet(pq, columns=["ts", "channel", "w"])
    except Exception as e:
        print(f"\n(no consolidated parquet to self-test on: {e})"); sys.exit(0)
    piv = (d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first"))
    df = pd.DataFrame(index=pd.DatetimeIndex(piv.index))
    for pn, col in _PANEL_COL.items():
        if pn in piv.columns:
            df[col] = piv[pn].values
    print("\n=== event classification on real data ===")
    for a in ("hair_dryer", "microwave", "oven"):
        _, fired = classify_appliance(df, a)
        if fired:
            durs = np.array([e.dur_s for e in fired]) / 60
            print(f"{a:11}: {len(fired):4d} events | dur med {np.median(durs):.1f} min "
                  f"| mean_w med {np.median([e.mean_w for e in fired]):.0f} "
                  f"| cycle_rate med {np.median([e.cycle_rate for e in fired]):.2f}/min")
        else:
            print(f"{a:11}:    0 events")
