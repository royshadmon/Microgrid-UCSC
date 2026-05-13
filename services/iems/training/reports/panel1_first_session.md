# Panel 1 — First live monitoring session

_Session captured on 2026-05-11/12 (PT) using
`services/iems/models/nilm_panel1_int8.onnx` against the live
Kafka → AnyLog stream._

## Session bounds

- **Start:** `2026-05-12T04:55:11+00:00` (Mon 21:55 PT)
- **End:**   `2026-05-12T05:58:33+00:00` (Mon 22:58 PT)
- **Duration:** 63 min 22 s
- **Total ticks:** 365 (target ≥ 360)
- **Tick interval:** 10 s nominal; observed median 10.0 s, max 13.0 s
- **Errors:** 0
- **Decision thresholds:** HP = 0.68, SP = 0.53 (chosen on val split in Phase 7)

## Per-appliance behavior

| appliance | ON ticks | OFF ticks | ON-fraction | off→on | on→off |
|---|---:|---:|---:|---:|---:|
| heat pump | 0 | 365 | 0.0% | 0 | 0 |
| solar pump | 0 | 365 | 0.0% | 0 | 0 |

The model called both heads **OFF for every tick of the session.** Both prediction probabilities were stable to within 0.001 across the full hour: HP held at **0.249 ± 0.001** (vs. 0.68 threshold), SP at **0.323 ± 0.000** (vs. 0.53 threshold).

## Off→on transitions by local hour

| hour (PT) | heat pump | solar pump |
|---:|---:|---:|
| _no transitions in session_ | — | — |

## Inference latency (full session, model only — fetch excluded)

| stat | value (ms) |
|---:|---:|
| count | 365 |
| mean | 0.462 |
| p50 | 0.379 |
| p95 | 0.901 |
| p99 | 1.971 |
| max | 3.584 |

The 2 ms bar is met at p99 (1.971 ms). One tick hit 3.58 ms (single-tick outlier, ~0.27% of ticks). Fetch dominates the per-tick wall clock — median **373 ms / tick** on AnyLog round trips, p95 **902 ms** — but is separate from the model latency the spec targets.

## Live measurements observed during the session

| signal | min | max | mean | stddev |
|---|---:|---:|---:|---:|
| `panel1_w` (W) | 314 | 398 | 337 | 28.3 |
| `panel1_w_step` (W above 30-min baseline) | 0.0 | 22.7 | — | — |
| `outside_temp` (°F) | 61.5 | 64.1 | — | — |
| `irradiance` (W/m²) | 0 | 0 | 0 | — |

## Acceptance vs Phase 9 spec

| check | target | actual | pass |
|---|---|---|:--:|
| Session duration | ≥ 1 hour | 63 min 22 s | ✓ |
| Total ticks | ≥ 360 | 365 | ✓ |
| Error count | 0 | 0 | ✓ |
| p99 inference latency over full session | ≤ 2 ms | 1.97 ms | ✓ |
| Heat pump transitions / hour | 0–15 | 0 | ✓ |
| Solar pump transitions / hour | 0–4 | 0 | ✓ |
| Event log: one line per tick, monotonic timestamps | yes | yes | ✓ |

## Anomalies and observations

1. **Near-constant probability output.** Across 365 ticks, HP probability moved by 0.003 total and SP by 0.002 — almost no response to input variation. Panel 1 power did move (314 → 398 W, σ = 28 W) and `panel1_w_step` ranged 0 → 23 W, so the *input* wasn't constant. The trunk + heads produce a near-fixed point in this operating region. This isn't a failure (the heads correctly say OFF), but it tells us the model's decision surface is steep around its prior and gentle in the operating band we sampled.

2. **No transitions to validate.** The session covered a single nighttime hour (21:55 → 22:58 PT). With irradiance ≡ 0 and Panel 1 sitting at 314–398 W (heat-pump *fan-only* range; below the 1500 W compressor threshold), the environment didn't exercise the model's transition logic. The "0 transitions" passes the 0–15 / 0–4 spec band but doesn't prove the model can fire. Daytime / heat-pump-active sessions are needed for transition validation.

3. **Latency outliers correlate with fetch hiccups.** The two ticks with inference > 2 ms (max 3.58 ms) coincided with the slowest AnyLog responses. Likely contention on the operator REST endpoint or GC pause. p99 still ≤ 2 ms; no concern.

4. **`panel1_w_step` floor at 0 is real.** The 30-min rolling minimum kept catching up to the current draw, so the live step was small (mostly 0–10 W). Consistent with a steady-state idle. This is the same signal pattern that would suppress the SP head's positive prediction.

## Plausibility check against the appliance spec

The heat-pump head was correctly OFF for the whole hour — Panel 1 sat at 314–398 W, far below the 1500 W compressor threshold in `appliance_data_updated.txt`. The fan-only band (300 W) is consistent with what we saw, and the spec is explicit that fan-only is not a heat-pump-ON state under the rule we trained against. ✓

The solar-pump head was correctly OFF — `irradiance = 0` for the entire hour (it's night), and the rule requires `irradiance > 200` for SP=ON. ✓

What this session **did not** test:

- Daytime heat-pump cycling (e.g., morning warm-up under heating mode or afternoon cooling)
- Solar irradiance ramps (the SP head needs daylight + an actual pump step to fire)
- HP/SP boundary conditions where the rule and the model disagree

The known Phase 7 weakness — the model's poor precision on the heat-pump head and its near-zero recall on solar pump in the held-out test split — was not exercised in this session because the home was idle. Useful contrast: Phase 7 said the HP head fires too eagerly; this session showed it didn't fire at all on an idle hour. Both are consistent with "model has high-recall HP head, low-precision HP head, broken SP head" — we just happened to land in a regime where neither failure mode triggered.

## Next runs that would be informative

1. **Daytime weekday hour (10:00–11:00 PT, sunny)** — should exercise the SP head and HP cooling cycles.
2. **Cold-morning hour (06:00–07:00 PT)** — should exercise HP heating cycles.
3. **Heat-pump activation event capture** — would reveal whether the model's HP probability actually rises during a real cycle.

None of these require code changes; just rerun `realtime_monitor.py` during the target window.
