"""
Rule tree for tagging DSS outputs as AUTO or USER_DRIVEN (Adabi 5.2.1.3).
AUTO = system can act without asking; USER_DRIVEN = needs human confirmation.
"""
from iems.config import APPLIANCES


def tag_action(appliance: str, action_type: str) -> str:
    app = APPLIANCES.get(appliance, {})
    laxity = app.get("laxity", "user_controlled_non_interval")

    if laxity == "auto_controlled":
        return "auto"
    if laxity == "uninterruptible":
        return "auto"
    return "user"


def determine_flow_branch(
    mode: str,
    load_kw: float,
    generation_kw: float,
    soc_pct: float,
) -> str:
    if mode == "on_grid":
        if load_kw > generation_kw:
            return "5.16_on_grid_load>gen"
        return "5.16_on_grid_gen>load"
    else:
        if load_kw > generation_kw and soc_pct > 10:
            return "5.16_off_grid_discharge"
        if load_kw > generation_kw and soc_pct <= 10:
            return "5.16_off_grid_generac"
        return "5.16_off_grid_store_excess"
