# Phase 0 findings — CT-to-breaker mapping

Status: 0.1 (data-driven signature profile) complete. 0.2 (on-site walk-test)
still required to finalize. Headline: the runbook's structural premise does not
hold and Phases 1-5 must be reframed before building.

## What the CTs actually are

`I11 I12 I21 I22 I31 I32` are **not** six per-appliance branch CTs. They are the
**two split-phase mains legs of each sub-panel**:

- Panel 1: I11 = leg A, I12 = leg B
- Panel 2: I21 = leg A, I22 = leg B
- Panel 3: I31 = leg A, I32 = leg B

Evidence (June 15 to July 3, 6 s frame, ~33k aligned steps per panel):

1. Per panel the two legs reconstruct the whole panel power:
   `panel_W ~= coef_a*I_a + coef_b*I_b`, R^2 = 0.999 / 0.999 / 0.997, intercepts
   7 / -67 / -98 W. All coefficients ~100-131 (i.e. ~120 V per amp), never ~240.
   If these were 2 of many branch circuits there would be large unmetered
   residual and R^2 would be well below 1.
2. At the largest events both legs carry near-equal current, the 240 V signature:
   - P1 5704 W: I11 24.7 A, I12 24.0 A (high-minus-low delta ratio 1.00, high-regime corr 0.994)
   - P2 4281 W: I21 18.2 A, I22 16.4 A (ratio 0.98)
   - P3 9192 W: I31 40.9 A, I32 35.5 A (ratio 0.95); on the June-16 event I32 > I31,
     so the leg imbalance flips with whatever 120 V loads are co-active.
3. The naive binding I12 -> solar_pump is falsified: solar_pump is 100-250 W
   (1-2 A) and the spec mutex says it is OFF when the heat pump runs, yet I12
   peaks at 24 A in lockstep with the 5.7 kW heat-pump event.

At baseline one leg carries the always-on 120 V loads and the other is near zero
(P1 0.89 A vs 0.10 A, P2 1.11 vs 0.37, P3 1.43 vs 0.27), which is why one CT per
panel reads "always on."

## What signal this still buys (vs the 3-panel training input)

The per-leg split is genuinely new information the current `raw_pivot.parquet`
(three panel columns) never had. Two things fall out of it:

1. **Each panel's sole 240 V load becomes a measured label.** The balanced-leg
   component `2*min(I_a,I_b)*120` isolates the only 240 V appliance on each panel:
   - heat_pump (P1): high-regime median 5201 W vs panel 5130 W (1.02x), baseline 25 W
   - water_heater (P2): 3852 W vs panel 4047 W (0.95x), baseline 89 W
   - dryer (P3): 6123 W vs panel 6475 W (0.93x), baseline 64 W
   This is the "heat_pump / water_heater / dryer become measured" win the runbook
   wanted, achieved through the mains legs rather than dedicated branch CTs.
2. **A coarse per-leg 120 V bucket** `|I_a - I_b|*120` = net 120 V load on the
   heavier leg. Weakly separating, but nonzero.

What it does NOT do: separate the many 120 V loads that share a leg (fridge vs
computers vs tv on P3, solar_pump vs other P1 leg loads, hair_dryer vs sprinklers
vs bath_lights on P2). Those stay rule/residual-supervised.

## Consequence for the runbook

- Phase 2 "CT-derived hard labels, one appliance per CT" is not achievable as
  written. It becomes: measured labels for the three 240 V loads via the
  balanced-leg formula, plus a per-panel 120 V leg-imbalance feature.
- Phase 1 should ingest `I11 I12 I21 I22 I31 I32` + `VrmsA VrmsB` and derive
  `bal240_p{1,2,3}` and `imbal120_p{1,2,3}`, not six independent `I##_W` heads.
- Phase 3 energy balance is unchanged in spirit but the fixed measured terms are
  the three balanced-240 loads, not six CT appliances.
- v_ref per CT: leg-A CTs -> VrmsA, leg-B CTs -> VrmsB (single 120 V leg each);
  the 240 V loads use both legs. PF from the fit: I11 ~0.82 (inductive heat-pump
  leg), others ~0.96-1.0.

## Walk-test (0.2) now confirms, not discovers

The walk-test scope narrows to:
- Confirm leg-to-phase (which physical leg is VrmsA vs VrmsB).
- Confirm each panel has exactly one 240 V load (heat_pump / water_heater / dryer)
  and no second 240 V circuit that would contaminate the balanced-leg estimate.
- Check whether any single 120 V appliance sits alone on a leg (would make that
  appliance separately measurable via the leg imbalance) - unlikely on P3.
- Read the real-power step at a known 240 V load to calibrate PF.

## Artifacts

- `phase0_ct/ct_signature_profile.csv` - per-CT profile (vref, pf, duty, on-W, peak, parent corr, TOD)
- `ct_appliance_map.json` - revised candidate map (legs + derived_measured_appliances)
- `phase0_ct/phase0_ct_profile.py`, `phase0_ct_diag.py`, `phase0_ct_finalize.py` - reproducible
- `phase0_ct/raw_par_egauge_kafka_*.csv` - pulled long-format source (delete to reclaim ~55 MB)

## Rollback

Delete `ct_appliance_map.json` and the `phase0_ct/` directory. Nothing in the
live pipeline was touched.
