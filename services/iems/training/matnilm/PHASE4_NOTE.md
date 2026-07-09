# Phase 4 — Shrink rule_engine to the unmeasured heads

Deliverable: `rule_engine_ct.py` (additive; wraps the untouched `rule_engine.py`)
and `make_labels_ct.py` updated to consume it. Live `rule_engine.py` unchanged.

## What changed vs the raw-panel rules

1. **Retire measured heads.** heat_pump and water_heater -> NaN (CT-measured,
   Phase 2). `merge_measured()` guarantees a rule never overrides a measured head.
2. **dryer off the isolated 240V aggregate** (PF-corrected bal240_p3) instead of
   raw panel3 -> no 120V false triggers. ON 0.16% -> 0.12%.
3. **Decontaminate BAND rules** (hair_dryer, dishwasher, microwave) with
   `pN_120 = panelN_w - real_240`. Removes the FPs the 240V load caused in their
   power band. Off-event these are ~identical to the old rules (decon acts only
   during 240V events).
4. **Gate STEP/variance rules** (sprinklers, bath_lights, refrigerator,
   washing_machine, pressure_pump, computers, tv_stereo) to NaN during a strong
   240V event, instead of a noisy subtraction. A small 120V load is genuinely
   unobservable under a running 240V load, so abstain rather than guess.

### Why selective (the first blunt pass was wrong)

Feeding `panel - bal240` to *every* rule improved the band rules but moved the
step/variance rules ambiguously (refrigerator/washing_machine jumped during dryer
events). Some of that is real masked-load recovery (washer+dryer run together),
but `bal240_p3` is the contaminated dryer+oven+cooktop aggregate, so subtracting
it injects noise into rules that key off steps/variance. Without ground truth the
two can't be separated, so those heads abstain during events rather than absorb
the noise. Band rules (absolute power) are safe to decontaminate.

## Verification (4.3, whole CT window)

- measured heads NaN in new rule output: P1 heat_pump, P2 water_heater — confirmed.
- band-rule FP during 240V event: hair_dryer 1.03->0.00%, dishwasher 3.32->0.47%,
  microwave 0.95->0.00%.
- step heads: 100% NaN during 240V events, 100% identical to old off-event.
- off-event band heads ~identical to old (>=98.9%): decon acts only on events.

## Label impact (labels_*_ct.parquet regenerated)

dishwasher ON 2553->1069 (-58%), microwave 83->3 (-96%), dryer 492->392, hair_dryer
181->170; step heads keep ON counts and gain NaN abstentions during 240V events
(sprinklers +683, bath_lights +643, tv_stereo +341, refrigerator +92). These are
the labels Phase 5 will train on.

## Known limitation

solar_pump still ~0% (its rule needs irradiance; no weather Jun 15+). Phase 4
cannot fix that - merge a weather source for the window before final training.

## Rollback

Delete `rule_engine_ct.py`; restore `make_labels_ct.py` and the
`labels_*_ct.parquet` from their `.bak.*`. Live `rule_engine.py` never touched.
