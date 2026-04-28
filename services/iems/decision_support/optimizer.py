"""
Linear program optimizer over Adabi eq 5.1 (off-grid) and 5.2 (on-grid).
24h horizon, hourly granularity.
Uses scipy.optimize.linprog.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from scipy.optimize import linprog
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    logger.warning("scipy not available — optimizer will return stub results")


def optimize_24h(
    mode: str,
    hourly_loads_kw: list[float],
    hourly_rates: list[float],
    soc_init: float = 0.5,
    capacity_kwh: float = 13.5,
    max_charge_kw: float = 5.0,
    max_discharge_kw: float = 5.0,
    soc_min: float = 0.10,
    soc_max: float = 0.95,
) -> dict:
    """
    Minimize total electricity cost over 24h.
    Decision variables: charge_kw[t], discharge_kw[t] for t in 0..23.
    Returns optimal schedule and estimated daily savings vs. no-battery baseline.
    """
    if not HAS_SCIPY:
        return _stub_result(mode)

    n = 24
    loads = (hourly_loads_kw + [0] * n)[:n]
    rates = (hourly_rates + [0.16] * n)[:n]

    # Variables: [charge_0..23, discharge_0..23] (48 vars)
    # Minimize sum(rates[t] * (load[t] + charge[t] - discharge[t]))
    c_obj = rates + [-r for r in rates]

    # Bounds: 0 <= charge[t] <= max_charge_kw, 0 <= discharge[t] <= max_discharge_kw
    bounds = [(0, max_charge_kw)] * n + [(0, max_discharge_kw)] * n

    # SOC constraints: soc_min <= soc[t] <= soc_max
    # soc[t] = soc_init + (sum(charge[0..t]) - sum(discharge[0..t])) / capacity_kwh
    A_ub, b_ub = [], []
    for t in range(n):
        row_max = [0.0] * 48
        row_min = [0.0] * 48
        for j in range(t + 1):
            row_max[j] = 1.0 / capacity_kwh
            row_max[n + j] = -1.0 / capacity_kwh
            row_min[j] = -1.0 / capacity_kwh
            row_min[n + j] = 1.0 / capacity_kwh
        # soc[t] <= soc_max  →  sum(charge)/cap - sum(discharge)/cap <= soc_max - soc_init
        A_ub.append(row_max)
        b_ub.append(soc_max - soc_init)
        # soc[t] >= soc_min  →  -sum(charge)/cap + sum(discharge)/cap <= -(soc_min - soc_init)
        A_ub.append(row_min)
        b_ub.append(-(soc_min - soc_init))

    try:
        result = linprog(c_obj, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
        if result.success:
            charge = result.x[:n]
            discharge = result.x[n:]
            baseline_cost = sum(r * l for r, l in zip(rates, loads))
            opt_cost = sum(
                rates[t] * (loads[t] + charge[t] - discharge[t])
                for t in range(n)
            )
            return {
                "feasible": True,
                "schedule": [
                    {"hour": t, "charge_kw": round(charge[t], 3), "discharge_kw": round(discharge[t], 3)}
                    for t in range(n)
                ],
                "daily_savings_dollars": round(baseline_cost - opt_cost, 4),
                "baseline_cost_dollars": round(baseline_cost, 4),
                "optimized_cost_dollars": round(opt_cost, 4),
            }
    except Exception as exc:
        logger.warning("linprog failed: %s", exc)

    return _stub_result(mode)


def _stub_result(mode: str) -> dict:
    return {
        "feasible": False,
        "schedule": [],
        "daily_savings_dollars": 0.0,
        "note": "scipy not available or optimization failed",
    }
