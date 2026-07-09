# Phase 0.2 walk-test protocol (on-site, Los Gatos)

Purpose: confirm the split-phase mains-leg reading and resolve the four items
history could not settle. Requires a person at the sub-panels + someone able to
run the verify queries (below) same-day. Budget ~60-75 min.

The historical pre-check already settled most of it, so this session is short and
targeted. Only these questions remain:

1. Leg-to-phase: which physical leg is VrmsA vs VrmsB (cosmetic for watts, matters
   only if we later want true real-power cross terms).
2. P3 de-contamination: separate dryer / oven / cooktop, which all share the P3
   240V balanced bucket.
3. P1: confirm heat_pump ~5kW on both legs; find which leg solar_pump is on and
   whether the 2nd P1 120V plateau (~155W) is a blower or something else.
4. PF calibration: real-power step / VA step at each 240V load.

## Prep (before toggling anything)

- Quiet the house: turn OFF dryer, oven, cooktop, water-heater breaker if safe,
  hair dryer, sprinklers controller. Leave fridges/networking (unavoidable base).
- Sync the phone clock to the same source the eGauge uses (both to network time).
  All events are matched by wall-clock, so drift is the main error source.
- Note a 2-min "all quiet" baseline window at the start; write its start/stop.
- Logging: one row per toggle. Columns: appliance, action(ON/OFF), local_time
  (HH:MM:SS), note. Use a single sheet; times are the only thing that matters.

## Toggle sequence (2 min ON, 2 min OFF each; wait for quiet between)

Do the 240V loads first (cleanest signal), one panel at a time.

P1 - HVAC:
- heat_pump: force a call for heat/cool so the compressor runs. ON 2 min, OFF 2 min.
  Watch: both I11 and I12 should step up ~equally (~20-24 A each).
- solar_pump: force the solar circulation on (or wait for a sunny window and toggle
  its breaker). ON 2 min, OFF 2 min. Watch: only ONE of I11/I12 steps by ~1-2 A;
  that identifies solar_pump's leg. Note which.
- If a blower/air-handler fan can run alone (fan-only mode): ON 2 min, OFF 2 min.
  This is the suspected 2nd P1 120V load; confirm which leg it sits on.

P2 - H2O:
- water_heater: breaker ON 2 min, OFF 2 min. Watch: both I21/I22 step ~equally
  (~16-18 A). Confirms ~3850W clean.
- sprinklers: one zone ON 2 min, OFF 2 min. Watch: leg-A (I21) small step ~1-2 A.
- bath_lights: ON 2 min, OFF 2 min. Watch: leg-A small step.
- hair_dryer: ON 30 s (it is high-watt, short is fine), OFF. Watch: leg-A large step
  (~10-15 A).

P3 - Kitchen (the de-contamination that matters most):
- dryer: ON 3 min (needs a moment to spin up heat), OFF. Watch: both I31/I32 step
  ~equally; record the exact ON/OFF window - this is the dryer signature.
- oven: set to bake, let the element cycle ON, hold 3 min, OFF. Watch: both legs
  step ~equally at a LOWER level than dryer (~8-16 A). This is the contaminant.
- cooktop: one 240V burner to high 1 min, OFF. Watch: both legs, short step.
- microwave: ON 1 min, OFF. Watch: ONE leg steps ~8-10 A (120V).
- refrigerator: do NOT toggle; instead note it runs on leg-A base continuously.

## During/after: run the verify queries

Hand the logged sheet (as a CSV: appliance,action,local_time) to whoever runs
`phase0_walktest_queries.py` (see that file). It pulls each toggle window from the
live partition and reports, per appliance: which leg(s) stepped, the step in amps
and watts, the balanced-240 step, and PF = (panel real-W step)/(CT VA step).

## Acceptance / what confirms the map

- heat_pump, water_heater, dryer, oven, cooktop: BOTH legs step ~equally -> 240V,
  balanced-240 formula valid. PF recorded.
- dryer vs oven vs cooktop now have distinct (level, duration) fingerprints ->
  usable to split the P3 240V aggregate downstream.
- solar_pump, hair_dryer, sprinklers, bath_lights, microwave: ONE leg steps ->
  120V; note the leg. Any appliance that is the SOLE stepping load on its leg with
  a clean baseline is separately measurable via leg current.
- Leg-to-phase fixed by matching a known single-leg step to VrmsA vs VrmsB.

## If time is short

Priority order: (1) dryer + oven + cooktop separation on P3, (2) solar_pump leg on
P1, (3) PF at water_heater. Everything else the pre-check already bounds.
