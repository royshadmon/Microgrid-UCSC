"""Thin bridge to avoid circular imports between recommender and shedding."""
from iems.load.shedding import rank_shed_candidates, ShedPlan


def _get_shedding(current_states: dict, target_w: float, mode: str) -> ShedPlan:
    return rank_shed_candidates(current_states, target_w, mode)
