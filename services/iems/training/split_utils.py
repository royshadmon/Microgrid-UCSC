"""Stratified day-based train/val/test split for window builders.

The legacy splits (chronological-by-day, or by observed-row position) can
strand every positive of a rare head in a single split, producing val/test
F1 == 0 on heads that actually trained fine (this was the Panel-2 collapse).

`stratified_day_split` keeps whole days atomic — so contiguous runs are not
torn across splits — but assigns them so that every head with at least two
positive-days gets a positive day in BOTH val and test. Days with the
heaviest positive mass for a rare head are left in train (we seed val/test
from the head's *lightest* positive days), so train keeps the bulk of signal.
"""
from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd


def _spread(pool: list, k: int) -> list:
    """Pick k items spread evenly across an ordered pool."""
    if k <= 0 or not pool:
        return []
    if k >= len(pool):
        return list(pool)
    step = len(pool) / k
    return [pool[min(len(pool) - 1, int(i * step))] for i in range(k)]


def stratified_day_split(
    df: pd.DataFrame,
    label_cols: Dict[str, str],
    frac_val: float = 0.15,
    frac_test: float = 0.15,
    day_col: str = "day",
) -> Tuple[set, set, set, dict]:
    """Return (train_days, val_days, test_days, coverage_report).

    df must carry `day_col` and the label columns (values in {0,1,NaN}).
    """
    days = sorted(pd.unique(df[day_col]))
    n = len(days)
    n_val = max(1, round(n * frac_val))
    n_test = max(1, round(n * frac_test))

    # positive-count per day, per head
    posday: Dict[str, Dict] = {}
    for h, col in label_cols.items():
        grp = (df[col] == 1).groupby(df[day_col]).sum()
        posday[h] = {d: int(c) for d, c in grp.items() if c > 0}

    val: set = set()
    test: set = set()

    # rarest head first (fewest positive-days). Seed val/test from the head's
    # HEAVIEST positive days — light days often have their few positives inside
    # sub-window runs that don't survive the 100-sample slide, leaving val/test
    # empty. Reserve the single richest positive day for train so train keeps
    # the strongest signal.
    order = sorted(label_cols, key=lambda h: len(posday[h]))
    for h in order:
        pdays = [d for d, _ in sorted(posday[h].items(), key=lambda kv: -kv[1])]
        if not pdays:
            continue
        reserve = 1 if len(pdays) >= 3 else 0
        pool = pdays[reserve:] or pdays  # candidates for val/test
        if not any(d in val for d in pdays):
            for d in (pool + pdays):
                if d not in test:
                    val.add(d)
                    break
        if not any(d in test for d in pdays):
            for d in (pool + pdays):
                if d not in val:
                    test.add(d)
                    break

    # fill val/test up to target with remaining days, spread across time
    remaining = [d for d in days if d not in val and d not in test]
    for d in _spread(remaining, max(0, n_test - len(test))):
        test.add(d)
    remaining = [d for d in days if d not in val and d not in test]
    for d in _spread(remaining, max(0, n_val - len(val))):
        val.add(d)
    train = set(days) - val - test

    report = {}
    for h in label_cols:
        report[h] = {
            "pos_days": len(posday[h]),
            "train_pos": sum(posday[h].get(d, 0) for d in train),
            "val_pos": sum(posday[h].get(d, 0) for d in val),
            "test_pos": sum(posday[h].get(d, 0) for d in test),
        }
    return train, val, test, report
