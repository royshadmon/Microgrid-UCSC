# Decision Support Folder

`services/iems/decision_support/` — Adabi Section 5.2.1.3 (DSS) implementation. The runner calls one entry point per file, in this order:

```
panel power + NILM states + anomalies + TOU + weather
        │
        ├─► rule_tree.determine_flow_branch()    pick Figure-5.16 branch
        ├─► rule_tree.tag_action()               AUTO vs USER per appliance
        ├─► shedding_bridge._get_shedding()      shed ranking (calls load.shedding)
        ├─► recommender.build_recommendations()  the human-readable rec list
        └─► optimizer.optimize_24h()             optional 24 h LP plan
```

---

## `optimizer.py`

**Contents.** A `scipy.optimize.linprog` formulation of Adabi eq. 5.1 (off-grid) / 5.2 (on-grid). One entry point: `optimize_24h(mode, hourly_loads_kw, hourly_rates, soc_init, capacity_kwh, max_charge_kw, max_discharge_kw, soc_min, soc_max)`.

**Use in the system.** 24-hour planning horizon, hourly granularity. Returns the optimal charge/discharge schedule and an estimated daily savings versus a no-battery baseline. Optional — the runner skips it gracefully if `scipy` is unavailable; `_stub_result()` returns a stand-in dict so callers can branch without try/except. The dispatcher in `storage/dispatch.py` consumes only the next-hour decision, not the whole schedule.

**Key signature.**
```python
def optimize_24h(mode, hourly_loads_kw, hourly_rates,
                 soc_init=0.5, capacity_kwh=13.5,
                 max_charge_kw=5.0, max_discharge_kw=5.0,
                 soc_min=0.10, soc_max=0.95) -> dict
```

---

## `recommender.py`

**Contents.** `build_recommendations(current_states, anomalies, tou_info, weather, mode, user_prefs)` — the single function that turns the four-domain snapshot into a list of dicts the UI shows as cards.

**Use in the system.** This is the dollar-denominated DSS layer. Each recommendation carries `id`, `appliance`, `action`, `audience` (auto/user, via `rule_tree.tag_action`), `savings_dollars` (priced against `iems.config.TOU_RATES[season]`), `rationale`, and `confidence`. Hard-coded rules cover dryer/dishwasher/washing-machine peak deferral, fridge anomaly hint, sprinklers in peak, and an always-on TOU summary. Anomalies from `load/anomaly.py` are surfaced as urgent recs. `_next_off_peak_hour()` reads the TOU table to pick the next off-peak boundary.

**Top of the rule list.**
```python
if current_states.get("dryer") == 1 and tou_period == "peak":
    peak_rate = TOU_RATES[season]["peak"]["rate"]
    off_rate  = TOU_RATES[season]["off_peak"]["rate"]
    savings   = round(7 * (peak_rate - off_rate), 2)   # ~7 kWh / cycle
    recs.append({
        "id": "defer_dryer",
        "appliance": "dryer",
        "action": f"Defer dryer to after {off_peak_hour} (off-peak)",
        "audience": tag_action("dryer", "shed"),
        "savings_dollars": savings,
        ...
    })
```

---

## `rule_tree.py`

**Contents.** Two small but central functions: `tag_action(appliance, action_type)` returns `"auto"` or `"user"` based on `APPLIANCES[appliance]["laxity"]`, and `determine_flow_branch(mode, load_kw, generation_kw, soc_pct)` picks one of Adabi Figure 5.16's named branches.

**Use in the system.** Every recommendation passes through `tag_action` to set its audience field, so the UI knows whether to act silently (`"auto"`) or ask the user (`"user"`). `determine_flow_branch` produces the `flow_branch` label the runner stores in the cycle result — it tags the cycle as `5.16_on_grid_load>gen`, `5.16_off_grid_discharge`, `5.16_off_grid_generac`, etc. for traceability against the thesis.

**Key signature.**
```python
def tag_action(appliance, action_type) -> str:        # "auto" | "user"
def determine_flow_branch(mode, load_kw,
                          generation_kw, soc_pct) -> str
```

---

## `shedding_bridge.py`

**Contents.** A six-line wrapper that re-exports `rank_shed_candidates` from `iems.load.shedding` under the name `_get_shedding`.

**Use in the system.** Pure plumbing — exists only to keep `recommender.py` from importing `iems.load.shedding` directly, which would create a circular import (`load.shedding` imports `iems.config`, and DSS code is also pulled in from the runner). Any future cross-domain shedding helpers should land in this file.

**The whole file.**
```python
from iems.load.shedding import rank_shed_candidates, ShedPlan

def _get_shedding(current_states, target_w, mode) -> ShedPlan:
    return rank_shed_candidates(current_states, target_w, mode)
```
