# Phase 2 — Measured hard labels from the CTs

Deliverable: `make_labels_ct.py` (additive) -> per-panel `labels_{key}_ct.parquet`
(14 heads total: P1 2, P2 4, P3 8) + `measured_watts_ct.parquet`, on the CT-window
index (Jun 15 - Jul 6, tz-aware UTC). Live `rule_engine.py`, `make_labels.py`,
`labels_panel*.py` and `labels_*.parquet` are untouched.

## What is MEASURED vs what stays RULE

Only the two clean single-240V loads get measured labels (Phase 0):

| head | source | ON-thr | ON% (observed) | ON samples |
|---|---|---|---|---|
| heat_pump    | bal240_p1 | >1000 W, 2-step debounce | 1.33% | 688 |
| water_heater | bal240_p2 | >500 W, 2-step debounce  | 1.82% | 942 |

All other 12 heads keep canonical `rule_engine.py` labels. Panel-1 interlock
enforced: solar_pump forced 0 where heat_pump measured ON.

## Measured vs rule disagreement (the point of Phase 2)

- heat_pump: measured 1.33% vs naive panel>200W rule 7.06% (over all rows) - the
  rule fires ~5x too often, tagging panel baseline as heat pump. rule_engine gives
  0% here (needs weather it does not have on this window). Measured is the truth.
- water_heater: measured 1.82% vs panel>300W 1.27% vs rule_engine 0.18% - measured
  sits sensibly between the over- and under-counting rules.

Input-responsiveness (not constant-prone like the old targets):
  heat_pump    mean bal240 ON=4753W vs OFF=131W
  water_heater mean bal240 ON=3890W vs OFF=101W

## dryer stays rule-supervised (contamination)

`bal240_p3` is the dryer+oven+cooktop 240V aggregate (Phase 0), so no clean dryer
label. A provisional measured dryer (bal240_p3>4kW sustained, 0.18%/568 samples) is
written to `measured_watts_ct.parquet` for evaluation only - NOT wired into the head
set. Splitting it needs the walk-test (duration/level fingerprints).

## Regression companions (for Phase 3)

`measured_watts_ct.parquet`: heat_pump_w=bal240_p1, water_heater_w=bal240_p2,
dryer_agg_w=bal240_p3 (contaminated), dryer_provisional_label. These are the pinned
measured terms for the Phase-3 energy balance.

## Caveats

1. **Label sparsity.** heat_pump 688 / water_heater 942 ON samples over ~86h of
   real data (summer; heat_pump ~1% duty). Clean but thin - ~68/94 centered
   windows. Adequate to prove non-collapse; winter/LAN-direct data needed for
   strong F1. Same conclusion as Phase 0/1.
2. **solar_pump has no good label on this window.** Its rule needs irradiance and
   there is no weather Jun 15+. It comes out ~0%. Merge weather for the window (or
   use a weather API) before final training; it is not measurable from the CTs.
3. NaN mask preserved (262,677 unobserved rows = the 16.4% coverage gaps). Downstream
   (build_windows) currently fillna(0); train_matnilm should honor the mask.

## Rollback

Delete `labels_*_ct.parquet`, `measured_watts_ct.parquet`, `make_labels_ct.py`.
Live label pipeline unchanged.
