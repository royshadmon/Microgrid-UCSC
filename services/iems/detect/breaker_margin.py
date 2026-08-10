#!/usr/bin/env python3
"""Phase 4 - breaker-margin safety detector.

Alerts when a circuit sits at a sustained fraction of its breaker rating.
Works on per-leg RMS current from eGauge, because breakers trip on current.

Needs no learned baseline and no warm-up: the threshold comes from the
breaker rating, not from history. That is why this is the first detector to
go live.

State machine per group, with hysteresis so a load hovering at the margin
cannot flap:

    OK --(a >= margin*rating, held sustain_seconds)--> BREACH  [alert]
    BREACH --(a < clear_frac*rating)--> OK             [clear notice]

Usage:
    ANYLOG_HOST=100.119.235.24 python services/iems/detect/breaker_margin.py --once
    ANYLOG_HOST=100.119.235.24 python services/iems/detect/breaker_margin.py --loop
    python services/iems/detect/breaker_margin.py --backtest analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, "services")
from iems.load.anylog_query import (  # noqa: E402
    ANYLOG_TABLE_LIVE, anylog_query,
)

log = logging.getLogger("breaker_margin")

DEFAULT_CONFIG = Path("services/iems/detect/breaker_ratings.yaml")
SEVERITY = "critical"


# ── config ────────────────────────────────────────────────────────────────────

@dataclass
class Group:
    key: str
    label: str
    legs: list[str]
    amps_rating: float | None
    per_leg: bool = True
    margin_frac: float = 0.80
    clear_frac: float = 0.70
    sustain_seconds: int = 900
    min_samples: int = 20
    cooldown_seconds: int = 43200

    # runtime state
    breach_since: datetime | None = field(default=None, repr=False)
    in_breach: bool = field(default=False, repr=False)
    last_alert: datetime | None = field(default=None, repr=False)
    last_dropout: datetime | None = field(default=None, repr=False)

    @property
    def armed(self) -> bool:
        return self.amps_rating is not None and self.amps_rating > 0

    @property
    def margin_amps(self) -> float:
        return self.amps_rating * self.margin_frac

    @property
    def clear_amps(self) -> float:
        return self.amps_rating * self.clear_frac


def load_groups(path: Path) -> list[Group]:
    cfg = yaml.safe_load(path.read_text())
    d = cfg.get("defaults", {}) or {}
    groups = []
    for key, g in (cfg.get("groups") or {}).items():
        groups.append(Group(
            key=key,
            label=g.get("label", key),
            legs=list(g.get("legs") or []),
            amps_rating=g.get("amps_rating"),
            per_leg=bool(g.get("per_leg", True)),
            margin_frac=float(g.get("margin_frac", d.get("margin_frac", 0.80))),
            clear_frac=float(g.get("clear_frac", d.get("clear_frac", 0.70))),
            sustain_seconds=int(g.get("sustain_seconds", d.get("sustain_seconds", 900))),
            min_samples=int(g.get("min_samples", d.get("min_samples", 20))),
            cooldown_seconds=int(g.get("cooldown_seconds", d.get("cooldown_seconds", 43200))),
        ))
    return groups


# ── evaluation ────────────────────────────────────────────────────────────────

def group_current(group: Group,
                  series: dict[str, list[dict]]) -> tuple[float, str, int, list[str]]:
    """Return (representative amps, which leg, sample count, missing legs).

    per_leg: each leg is its own breaker pole, so the binding constraint is the
    worst leg -- take the max. Summing legs here would understate risk on an
    imbalanced 240 V circuit and is a classic way to miss a real overload.

    `missing` matters as much as the reading. If a leg stops reporting, the max
    is taken over the survivors and the group looks healthy while half of it is
    unmonitored. Silent half-coverage on a safety detector is worse than a
    visible outage, so callers must surface it.
    """
    best_a, best_leg, n, missing = 0.0, "", 0, []
    for leg in group.legs:
        rows = series.get(leg) or []
        vals = []
        for r in rows:
            try:
                vals.append(abs(float(r["w"])))
            except (TypeError, ValueError, KeyError):
                continue
        if not vals:
            missing.append(leg)
            continue
        n += len(vals)
        # Median over the window, not max: a single spike is inrush, not a
        # sustained overload, and this detector is explicitly about sustain.
        vals.sort()
        med = vals[len(vals) // 2]
        if med > best_a:
            best_a, best_leg = med, leg
    return best_a, best_leg, n, missing


def evaluate(groups: list[Group], series: dict[str, list[dict]],
             now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    events = []

    for g in groups:
        amps, leg, n, missing = group_current(g, series)

        # Checked BEFORE the armed gate on purpose: a dead channel is a data
        # health problem, not a threshold problem, and it needs no rating to
        # detect. Gating it behind `armed` would mean the shipped (unarmed)
        # config reports nothing at all, which is when you most want to know
        # your inputs are broken.
        if missing:
            cooled = (g.last_dropout is None
                      or (now - g.last_dropout).total_seconds() >= g.cooldown_seconds)
            if cooled:
                g.last_dropout = now
                events.append({
                    "ts": now.isoformat(),
                    "type": "leg_dropout",
                    "severity": "warning",
                    "group": g.key,
                    "label": g.label,
                    "missing_legs": missing,
                    "monitored_legs": [l for l in g.legs if l not in missing],
                    "message": (
                        f"{g.label}: no data from {', '.join(missing)}. "
                        f"This group is being monitored on "
                        f"{len(g.legs) - len(missing)} of {len(g.legs)} legs, so an "
                        f"overload on the missing leg would not be detected."
                    ),
                    "action": "Check the eGauge ingest pipeline for these channels.",
                })

        if not g.armed:
            continue

        if n < g.min_samples:
            log.debug("%s: only %d samples, skipping", g.key, n)
            continue

        pct = amps / g.amps_rating

        if amps >= g.margin_amps:
            if g.breach_since is None:
                g.breach_since = now
                log.info("%s: entered margin at %.1f A (%.0f%% of %.0f A)",
                         g.key, amps, pct * 100, g.amps_rating)
            held = (now - g.breach_since).total_seconds()
            cooled = (g.last_alert is None
                      or (now - g.last_alert).total_seconds() >= g.cooldown_seconds)
            if held >= g.sustain_seconds and not g.in_breach and cooled:
                g.in_breach = True
                g.last_alert = now
                events.append({
                    "ts": now.isoformat(),
                    "type": "breaker_margin",
                    "severity": SEVERITY,
                    "group": g.key,
                    "label": g.label,
                    "leg": leg,
                    "amps": round(amps, 2),
                    "rating_amps": g.amps_rating,
                    "pct_of_rating": round(pct * 100, 1),
                    "sustained_seconds": int(held),
                    "message": (
                        f"{g.label} has drawn {amps:.1f} A on {leg} "
                        f"({pct * 100:.0f}% of its {g.amps_rating:.0f} A rating) "
                        f"for {held / 60:.0f} minutes."
                    ),
                    "action": (
                        "Identify and shed load on this circuit. Sustained "
                        "operation near breaker rating is a thermal risk in the "
                        "conductor and terminations, not merely an efficiency issue."
                    ),
                })
        elif amps < g.clear_amps:
            if g.in_breach:
                events.append({
                    "ts": now.isoformat(),
                    "type": "breaker_margin_clear",
                    "severity": "info",
                    "group": g.key,
                    "label": g.label,
                    "amps": round(amps, 2),
                    "rating_amps": g.amps_rating,
                    "message": (f"{g.label} back to {amps:.1f} A "
                                f"({pct * 100:.0f}% of rating)."),
                })
            g.in_breach = False
            g.breach_since = None
        # Between clear_amps and margin_amps: hold state. This band is the
        # hysteresis gap and deliberately does nothing.

    return events


# ── sinks ─────────────────────────────────────────────────────────────────────

def emit(events: list[dict], out_path: Path | None) -> None:
    for e in events:
        line = json.dumps(e)
        print(line, flush=True)
        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("a") as f:
                f.write(line + "\n")


# ── modes ─────────────────────────────────────────────────────────────────────

def fetch_legs_recent(legs: list[str], minutes: int) -> dict[str, list[dict]]:
    """Fetch raw rows for exactly the channels this detector monitors.

    Deliberately NOT using iems.load.anylog_query.fetch_all_panels_recent: that
    helper filters results through the module-level IEMS_PANELS allow-list,
    which is scoped to the NILM feature tensor and omits I12 and I22. Routing a
    coverage detector through a hard-coded allow-list makes present channels
    look absent -- the detector would report a phantom outage for two legs that
    are in fact streaming normally.

    IEMS_PANELS is left alone on purpose: the inference loop builds its
    14-feature tensor from it, so widening it here would change model input.
    """
    rows = anylog_query(
        f"SELECT ts, nm, w FROM {ANYLOG_TABLE_LIVE} "
        f"WHERE ts > NOW() - {minutes} minutes ORDER BY ts ASC",
        table=ANYLOG_TABLE_LIVE, minutes=minutes,
    )
    out: dict[str, list[dict]] = {leg: [] for leg in legs}
    for r in rows or []:
        nm = r.get("nm")
        if nm in out:
            out[nm].append(r)
    return out


def run_once(groups: list[Group], lookback_min: int, out: Path | None) -> list[dict]:
    legs = sorted({leg for g in groups for leg in g.legs})
    series = fetch_legs_recent(legs, lookback_min)
    events = evaluate(groups, series)
    emit(events, out)
    return events


def run_loop(groups: list[Group], lookback_min: int, poll_s: int,
             out: Path | None) -> None:
    log.info("breaker-margin detector running; poll=%ds lookback=%dmin", poll_s, lookback_min)
    while True:
        try:
            run_once(groups, lookback_min, out)
        except Exception:
            log.exception("poll failed; continuing")
        time.sleep(poll_s)


def run_backtest(groups: list[Group], parquet: str, out: Path | None) -> None:
    """Replay historical data so thresholds can be checked before arming."""
    import pandas as pd

    armed = [g for g in groups if g.armed]
    if not armed:
        print("No group has a rating set - nothing to backtest.", file=sys.stderr)
        print("Fill in amps_rating in the config first.", file=sys.stderr)
        return

    legs = sorted({leg for g in armed for leg in g.legs})
    d = pd.read_parquet(parquet, columns=["ts", "channel", "w"])
    d = d[d.channel.isin(legs)]
    piv = (d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
             .abs().sort_index())

    print(f"backtest over {piv.index.min()} .. {piv.index.max()}  ({len(piv):,} rows)\n")
    for g in armed:
        cols = [c for c in g.legs if c in piv.columns]
        if not cols:
            continue
        worst = piv[cols].max(axis=1)
        over = worst >= g.margin_amps
        # Longest contiguous run above margin, in wall-clock seconds.
        runs, cur, longest = [], None, 0.0
        for ts, flag in over.items():
            if flag and cur is None:
                cur = ts
            elif not flag and cur is not None:
                runs.append((cur, ts)); longest = max(longest, (ts - cur).total_seconds()); cur = None
        n_alerts = sum(1 for a, b in runs if (b - a).total_seconds() >= g.sustain_seconds)
        print(f"{g.label:<18} rating={g.amps_rating:>5.0f}A  margin={g.margin_amps:>5.1f}A")
        print(f"   samples over margin : {int(over.sum()):,} / {len(over):,} "
              f"({over.mean() * 100:.3f}%)")
        print(f"   excursions          : {len(runs)}")
        print(f"   longest excursion   : {longest / 60:.1f} min")
        print(f"   would have alerted  : {n_alerts} time(s)\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--backtest", metavar="PARQUET")
    ap.add_argument("--out", default="analysis/anomalies/breaker_margin.jsonl")
    ap.add_argument("--lookback-minutes", type=int, default=30)
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    groups = load_groups(Path(a.config))
    armed = [g for g in groups if g.armed]
    unarmed = [g for g in groups if not g.armed]
    log.info("loaded %d group(s): %d armed, %d unarmed",
             len(groups), len(armed), len(unarmed))
    for g in unarmed:
        log.warning("%s (%s) has no amps_rating - SKIPPED", g.key, g.label)
    if not armed:
        log.error("No group is armed. Fill in amps_rating in %s; "
                  "the detector cannot fabricate a safety threshold.", a.config)

    out = Path(a.out) if a.out else None
    if a.backtest:
        run_backtest(groups, a.backtest, out)
    elif a.loop:
        run_loop(groups, a.lookback_minutes, a.poll_seconds, out)
    else:
        ev = run_once(groups, a.lookback_minutes, out)
        log.info("%d event(s)", len(ev))


if __name__ == "__main__":
    main()
