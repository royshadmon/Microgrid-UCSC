"""
Load shedding module (Adabi 5.3).
Shed priority is house-specific — dryer (7 kW) first, period.
Never shed: refrigerator, pressure_pump, networking.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from iems.config import APPLIANCES, CRITICAL_APPLIANCES, TOU_RATES

logger = logging.getLogger(__name__)


@dataclass
class ShedCandidate:
    appliance: str
    power_w: float
    shed_priority: int
    panel: str
    deferrable: bool
    reason: str
    savings_dollars: float = 0.0

    @property
    def expected_w_saved(self) -> float:
        return self.power_w

    @property
    def laxity(self) -> str:
        # Laxity tier label from Adabi Section 5.3:
        # uninterruptible / user-controlled-interval / user-controlled-non-interval / auto-controlled
        if self.appliance in ("dryer", "washing_machine", "dishwasher"):
            return "user-controlled-interval"
        if self.appliance in ("heat_pump", "water_heater"):
            return "auto-controlled"
        if self.appliance == "sprinklers":
            return "user-controlled-non-interval"
        return "user-controlled-non-interval"

    def __getitem__(self, key: str):
        # Dict-style access used by the verification suite and the UI.
        if key == "expected_w_saved":
            return self.expected_w_saved
        if key == "laxity":
            return self.laxity
        return getattr(self, key)

    def keys(self):
        return (
            "appliance", "power_w", "expected_w_saved", "shed_priority",
            "panel", "deferrable", "reason", "savings_dollars", "laxity",
        )

    def to_dict(self) -> dict:
        return {k: self[k] for k in self.keys()}


@dataclass
class ShedPlan:
    candidates: list[ShedCandidate]
    total_reduction_w: float
    total_savings_dollars: float
    mode: str

    def __iter__(self):
        return iter(self.candidates)

    def __len__(self) -> int:
        return len(self.candidates)

    def __getitem__(self, idx: int) -> ShedCandidate:
        return self.candidates[idx]

    def to_list(self) -> list[dict]:
        return [c.to_dict() for c in self.candidates]


def rank_shed_candidates(
    current_states: dict[str, int],
    target_reduction_w: float,
    mode: str = "on_grid",
    user_overrides: Optional[dict] = None,
) -> ShedPlan:
    """
    Returns an ordered shed plan to achieve target_reduction_w.
    Never sheds CRITICAL_APPLIANCES.
    """
    candidates = []
    overrides = user_overrides or {}

    for name, state in current_states.items():
        if state != 1:
            continue
        if name in CRITICAL_APPLIANCES:
            continue
        if overrides.get(name, {}).get("protected"):
            continue

        app = APPLIANCES.get(name)
        if not app:
            continue
        if app.get("shed_priority", 999) >= 999:
            continue

        nom_power = (app["power_range_w"][0] + app["power_range_w"][1]) / 2
        candidates.append(ShedCandidate(
            appliance=name,
            power_w=nom_power,
            shed_priority=app["shed_priority"],
            panel=app["panel"],
            deferrable=app.get("deferrable", False),
            reason=_shed_reason(name, mode),
        ))

    # Sort by shed_priority ASC, then power DESC (biggest bang first within tier)
    candidates.sort(key=lambda c: (c.shed_priority, -c.power_w))

    return ShedPlan(
        candidates=candidates,
        total_reduction_w=sum(c.power_w for c in candidates),
        total_savings_dollars=0.0,
        mode=mode,
    )


def estimate_shed_savings_dollars(
    plan: ShedPlan,
    duration_min: float,
    tou_period: str,
    season: str,
) -> float:
    rate = _get_rate(tou_period, season)
    total_kwh = sum(c.power_w / 1000 for c in plan.candidates) * (duration_min / 60)
    savings = round(total_kwh * rate, 4)

    for c in plan.candidates:
        c.savings_dollars = round((c.power_w / 1000) * (duration_min / 60) * rate, 4)

    plan.total_savings_dollars = savings
    return savings


def _get_rate(period: str, season: str) -> float:
    season_rates = TOU_RATES.get(season, TOU_RATES["winter"])
    if period == "peak":
        return season_rates["peak"]["rate"]
    if period in ("partial_peak", "weekend"):
        return season_rates.get("partial_peak", {}).get("rate", 0.20)
    return season_rates["off_peak"]["rate"]


def _shed_reason(appliance: str, mode: str) -> str:
    reasons = {
        "dryer": "Largest single load (7 kW) — highest TOU savings",
        "heat_pump": "Large thermal load — temperature tolerance permits brief shed",
        "water_heater": "Solar boiler may cover demand; thermal mass absorbs gap",
        "washing_machine": "Deferrable cycle — can restart off-peak",
        "dishwasher": "Deferrable cycle — delay to off-peak",
        "sprinklers": "Scheduled irrigation — deferrable",
    }
    return reasons.get(appliance, f"Deferrable load in {mode} mode")
