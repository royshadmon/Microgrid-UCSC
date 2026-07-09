# Phase 3 — Per-panel energy balance with a residual head

Delivers 3.1 (CT-anchored targets), 3.2 (balance loss + residual head), 3.3
(reconstruction verification). Full retrain + non-collapse is Phase 5.

## 3.1 New regression targets  (`reg_targets_ct.py :: build_targets`)

Replaces the degenerate `build_reg_targets` (which apportioned the WHOLE panel by
rule-label nominal share -> circular). Per panel N:

  panel_N = measured_240_N (PINNED) + sum(120V heads apportioned) + residual_N

- `measured_240_N = bal240_pN * PF_N`  (PF converts apparent I*V -> real watts).
  PF from Phase-0 leg coefficients: P1 0.941, P2 1.000, P3 0.989.
  heat_pump <- measured_240_p1 ; water_heater <- measured_240_p2 (pinned).
- dryer: MASKED regression target (240V but shares bal240_p3 with oven/cooktop).
- 120V heads: apportion `max(panel_N - measured_240_N, 0)` across ON heads by
  nominal share (the reduced unmetered set only).
- residual_N = remainder_120 - sum(120V targets)  (unlabeled 120V floor).

The measured terms are fixed observations, so the only free variables are the 120V
heads + residual -> non-degenerate (unlike the old rule-restating target).

## 3.2 Energy-balance loss  (`reg_targets_ct.py :: energy_balance_loss`, `LAMBDA_BAL=0.1`)

  L_balance = mean( ( sum_unmet(p_hat*o_hat) + residual_hat - (panel - measured) )^2 )

Measured 240V heads enter as their fixed measured values; the free sum is the
unmetered heads + the model residual. Added a guarded residual power head to
`model_matnilm.py` (`MATNilm(..., residual=True)` -> appends one kW output).
Backward compatible: `residual=False` (default) leaves the live trainer path and
output tuple unchanged. Smoke-tested: forward + masked BCE + masked MSE + balance
loss backprop finite.

## 3.3 Verification (on the CT window, all 51,702 observed steps)

| panel | reconstruction err (W) | residual W (med/p90/max) | corr(residual, 240) | measured head ON target |
|---|---|---|---|---|
| P1 | med 0.0, MAE 0.4 | 89 / 133 / 450 | -0.065 | heat_pump 4475 W |
| P2 | med 0.0, MAE 0.1 | 66 / 160 / 1504 | 0.026 | water_heater 3890 W |
| P3 | med 0.0, MAE 0.5 | 0 / 255 / 2362 | 0.238 | (dryer masked) |

Balance reconstructs each panel exactly (identity by construction); residual is a
bounded floor that does NOT track the 240V load (near-zero corr; P3's 0.238
reflects the known bal240_p3 oven/cooktop contamination). Measured heads pinned to
PF-corrected real watts.

## Deviations from runbook (Phase 0 consequences)

- Only 2 measured pinned heads (heat_pump, water_heater), not six CT appliances.
- dryer regression MASKED; its 240V power lives in the fixed measured_240_p3 term.
- PF correction added (apparent->real) - the runbook's "PF margin" made explicit.
- Changes are additive (`reg_targets_ct.py`) + one guarded model flag, not an
  in-place rewrite of `train_matnilm.py`.

## What Phase 5 needs (not built here)

1. `build_windows_ct.py`: CT windows from `raw_pivot_ct.parquet` +
   `labels_*_ct.parquet` carrying, per window midpoint: panel_kw, measured_sum_kw,
   and the `build_targets` reg targets (incl. residual).
2. `train_matnilm_ct.py` (or a `--ct` path): loads CT windows, instantiates
   `MATNilm(residual=True)`, trains masked BCE + masked MSE (measured pinned) +
   `LAMBDA_BAL * energy_balance_loss`.
3. Non-collapse sensitivity test + honest F1 on measured heads + promotion.

## Rollback

Delete `reg_targets_ct.py`; restore `model_matnilm.py` from `model_matnilm.py.bak.*`.
`train_matnilm.py` was not modified.
