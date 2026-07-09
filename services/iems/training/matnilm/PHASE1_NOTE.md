# Phase 1 — CT ingest into the training pull

Deliverable: `data/raw_pivot_ct.parquet` (June 15 - Jul 6, 6 s, tz-aware UTC),
produced by the additive `pull_data_ct.py`. The live `pull_data.py` and
`raw_pivot.parquet` (Apr-May, 3 cols) are untouched.

## What it contains (26 cols, drop-in superset of raw_pivot.parquet)

- 3 panels: `Panel1 (HVAC)`, `Panel2 (H2O)`, `Panel3 (Kitchen)` - abs() sign-normalized (panels ONLY).
- 6 raw leg currents `I11..I32` and voltages `VrmsA/VrmsB` - left raw (no abs).
- QA (reference only, not features): `Shop`, `Grid Power`, `Current on Utility Tie`.
- 6 per-leg watts `I##_W = I## * V_leg` (v_ref from ct_appliance_map.json: I.1->VrmsA, I.2->VrmsB).
- 6 Phase-0-correct per-panel features:
  - `bal240_p{1,2,3}` = min(I_a,I_b)*(VrmsA+VrmsB)  -> measured 240V load
  - `imbal120_p{1,2,3}` = |I_a*VrmsA - I_b*VrmsB|   -> net 120V leg load

## Deviations from the runbook (both consequences of Phase 0)

1. Additive `pull_data_ct.py` instead of editing `pull_data.py`. Cleaner rollback
   (delete the file + parquet); zero risk to the live 3-panel path.
2. Added `bal240_p*` / `imbal120_p*`. The runbook's six independent `I##_W`
   "appliance" columns are still emitted, but the mains-leg finding means the
   physically meaningful features are the balanced/imbalance pair. Phase 3 consumes
   these; the raw `I##_W` are kept for QA/traceability.

## Verification (1.2)

- Columns = 3 panels + 6 I##_W + 6 raw currents + 2 voltages (+ derived + QA). OK.
- `I31_W` max 4956 W == Phase-0 profile peak (4956.1). bal240 peaks 5878/4085/8599
  == Phase-0 finalize (5751/3944/8526) within the VrmsA+VrmsB (~246) vs 240 factor
  and the extra data through Jul 6. OK.
- bal240_p3 is the 240V-kitchen aggregate (dryer+oven+cooktop) per Phase 0, not
  clean dryer - expected, not a defect.

## Coverage caveat (blocking for FINAL training, not for Phase 1)

All channels (panels, CTs, volts) share **16.4%** non-null coverage at 6 s -
uniform, so a source property, not a CT defect, and better than the 9.6% the
production Apr-May parquet trained on. Pattern: clean 6 s when flowing (median gap
6 s) with frequent multi-hour dropouts (max ~31 h; Jun 21 dark) = the producer
SSL/RemoteDisconnected issue. ~86 h of real data over 22 days. Enough for
water_heater/dryer ON coverage; thin for heat_pump (~1% duty). Land the LAN-direct
meter connection before Phase 5 final training.

## Rollback

Delete `data/raw_pivot_ct.parquet` and `pull_data_ct.py`. Live training path
(`raw_pivot.parquet`) is unchanged.
