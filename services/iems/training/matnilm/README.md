# MATNilm label-quality overhaul (Phases 0-5)

CT-anchored labelling, decontaminated rules, and an energy-balance trainer for the
Los Gatos residential microgrid. This directory consolidates the design notes,
measured results, and the plan for what comes next.

The work replaces rule-manufactured supervision with **measured** supervision
wherever the hardware permits, and makes every remaining weak label explicit
rather than pretending it is ground truth.

---

## 1. Why this exists

The original pipeline supervised 14 appliance heads with rules that guessed
appliance state from three sub-panel power totals. Regression targets were then
derived by apportioning those same panel totals across the heads the rules had
just declared ON. The targets were therefore a deterministic function of the
labels, and the labels a deterministic function of the model input.

MATNilm collapsed under this supervision: it learned constant per-appliance
priors. The diagnostic signature was that a plus/minus 2-sigma shift of the panel
input moved output confidence by **0.0004**. The BiLSTM was retained in production
only because it demonstrably responded to its input.

The root cause is circularity, not model capacity. Phases 0-5 attack the labels.

---

## 2. Phase 0 - what the CT channels actually are

The overhaul was planned around six eGauge current channels (I11 I12 I21 I22 I31
I32) assumed to be per-appliance branch CTs. Phase 0 existed to verify that
premise. It falsified it.

**The six channels are the two split-phase mains legs of each sub-panel**
(I.1 = leg A, I.2 = leg B), not per-appliance CTs.

Evidence, over Jun 15 - Jul 3, 6 s cadence, ~33k aligned steps per panel:

| test | result |
|---|---|
| panel_W regressed on the two leg currents | R2 = 0.999 / 0.999 / 0.997, intercepts 7 / -67 / -98 W |
| regression coefficients | all ~100-131 (i.e. ~120 V per amp), never ~240 |
| P1 5704 W event | I11 = 24.7 A, I12 = 24.0 A (delta ratio 1.00, high-regime corr 0.994) |
| P2 4281 W event | I21 = 18.2 A, I22 = 16.4 A (delta ratio 0.98) |
| P3 9192 W event | I31 = 40.9 A, I32 = 35.5 A (delta ratio 0.95), imbalance flips between events |

A magnitude-ranking heuristic produced a plausible but **wrong** map
(heat_pump on I11, solar_pump on I12). It was caught only by a discriminating
spike test: solar_pump is a 100-250 W load and is spec-mutexed OFF while the heat
pump runs, yet I12 peaks at 24 A in lockstep with the 5.7 kW heat-pump event.
Aggregate statistics produce confident wrong answers; only falsification against
specific physical events settles the question.

### What the legs still buy

Two derived quantities per panel, absent from the old 3-panel training input:

    bal240_pN   = min(I_a, I_b) * (VrmsA + VrmsB)    measured 240 V load
    imbal120_pN = |I_a*VrmsA - I_b*VrmsB|            net 120 V leg load

The balanced component isolates each panel's sole 240 V appliance as a **measured
label**:

| appliance | balanced (high regime) | panel (high regime) | ratio | baseline |
|---|---|---|---|---|
| heat_pump (P1) | 5201 W | 5130 W | 1.02x | 25 W |
| water_heater (P2) | 3852 W | 4047 W | 0.95x | 89 W |
| dryer (P3) | 6123 W | 6475 W | 0.93x | 64 W |

Energy coverage, not appliance coverage, is the honest framing: over the window
the three 240 V loads carry **54% of the 68 kWh** of sub-panel energy, but are only
3 of 14 heads. The remaining 46% sits in the 120 V leg bucket where many loads
share a leg and cannot be separated.

### Pre-check findings that changed the plan

| finding | consequence |
|---|---|
| water_heater balanced-ON band is 3830-3944 W, 0.000% over its 4 kW ceiling | clean single 240 V load, best measured head |
| heat_pump clusters ~4900-5750 W when running, ~1% duty (summer) | clean per event; spec band 1500-4000 W is **too low**; sparse until winter |
| P3 balanced spreads 3.0-8.5 kW, 0.08% over the 7 kW dryer ceiling, strong events concentrate 16-18 h | **contaminated**: bal240_p3 is a dryer + oven + cooktop aggregate |
| 120 V loads sit almost entirely on one leg per panel (P2 leg A, P3 leg A) | imbal120 approximates that leg's 120 V aggregate |
| P1 shows a 150-270 W 120 V plateau on **both** legs during heat-pump-off | a second P1 120 V load exists (blower?); solar_pump leg unresolved |

Step-based PF measured from a historical heat-pump event: **0.96**.

---

## 3. Phase 1 - CT ingest

`pull_data_ct.py` (additive; `pull_data.py` untouched) produces
`data/raw_pivot_ct.parquet`: Jun 15 - Jul 6, 6 s, tz-aware UTC, 26 columns. It is
a drop-in superset of `raw_pivot.parquet` (same three panels, same panel-only
abs() sign normalization, same cadence and ffill) plus the six raw leg currents,
both voltages, six per-leg `I##_W`, and the six derived `bal240_p*` /
`imbal120_p*` features.

Verification: `I31_W` max 4956 W matches the Phase-0 profile peak (4956.1);
`bal240` peaks 5878 / 4085 / 8599 match Phase-0 finalize (5751 / 3944 / 8526)
within the VrmsA+VrmsB (~246) versus 240 shorthand plus the extra days.

**Coverage caveat.** All channels share **16.4%** non-null coverage at 6 s. This
is uniform across panels, CTs and voltages, so it is a source property, not a CT
defect, and it is better than the 9.6% the production Apr-May parquet trained on.
When data flows it is clean 6 s (median gap 6.0 s); dropouts are multi-hour (max
~31 h; Jun 21 fully dark) and trace to the producer SSL/RemoteDisconnected issue.
Net: **~86 hours of real data over 22 days**.

---

## 4. Phase 2 - measured hard labels

`make_labels_ct.py` (additive) writes `labels_{key}_ct.parquet` for all 14 heads
plus `measured_watts_ct.parquet`. Only the two clean single-240 V loads become
measured; the rest keep canonical rule labels.

| head | source | ON-rate (observed) | ON samples | ON vs OFF power |
|---|---|---|---|---|
| heat_pump | bal240_p1 > 1000 W, 2-step debounce | 1.33% | 688 | 4753 W vs 131 W |
| water_heater | bal240_p2 > 500 W, 2-step debounce | 1.82% | 942 | 3890 W vs 101 W |

The disagreement is the point:

| head | measured | naive panel threshold | rule_engine |
|---|---|---|---|
| heat_pump | 1.33% | 7.06% (panel > 200 W) | 0.00% (needs weather) |
| water_heater | 1.82% | 1.27% (panel > 300 W) | 0.18% |

The naive rule over-fires ~5x on heat_pump, tagging panel baseline as compressor
runs. The measured label is input-responsive (ON mean 4753 W vs OFF 131 W), unlike
the constant-prone targets that caused the collapse.

**dryer deliberately stays rule-supervised.** A measured dryer label drawn from
the contaminated `bal240_p3` would teach the head to fire on cooking. A provisional
measured dryer (sustained > 4 kW, 568 samples) is written for evaluation only and
is not wired into the head set.

Panel-1 interlock enforced at the label layer: solar_pump forced 0 where
heat_pump is measured ON.

---

## 5. Phase 3 - CT-anchored targets, residual head, energy balance

Replaces the degenerate `build_reg_targets` (whole panel apportioned by
rule-label nominal share). Per panel:

    panel_N = measured_240_N (PINNED) + sum(120 V heads, apportioned) + residual_N
    measured_240_N = bal240_pN * PF_N

Only the 120 V **remainder** is apportioned, across the reduced unmetered set.
Because the measured terms are fixed by real current, the free variables are the
120 V heads plus residual, so the decomposition is non-degenerate.

**Power-factor correction.** `bal240` is apparent power (I*V); the panel register
is real power. Without PF the 120 V remainder goes negative on the reactive heat
pump. PF from the Phase-0 leg coefficients: **P1 0.941, P2 1.000, P3 0.989**. This
is why heat_pump's pinned target is 4475 W real, not 4753 W apparent.

**Balance loss** (`LAMBDA_BAL = 0.1`):

    L_balance = mean( ( sum_unmet(p_hat * o_hat) + residual_hat - (panel - measured) )^2 )

A guarded residual power head was added to `model_matnilm.py`
(`MATNilm(..., residual=True)`); `residual=False` (the live default) returns the
identical output tuple, verified.

Verification on all 51,702 observed CT steps:

| panel | reconstruction err (W) | residual W (med / p90 / max) | corr(residual, 240 V) | measured ON target |
|---|---|---|---|---|
| P1 | med 0.0, MAE 0.4 | 89 / 133 / 450 | -0.065 | heat_pump 4475 W |
| P2 | med 0.0, MAE 0.1 | 66 / 160 / 1504 | 0.026 | water_heater 3890 W |
| P3 | med 0.0, MAE 0.5 | 0 / 255 / 2362 | 0.238 | (dryer masked) |

The identity holds by construction; the residual is a bounded floor that does not
track the 240 V load. P3's 0.238 correlation reflects the known bal240_p3
contamination.

---

## 6. Phase 4 - shrink and decontaminate the rule engine

`rule_engine_ct.py` (additive; wraps the untouched `rule_engine.py`).

1. **Measured heads retired.** heat_pump and water_heater return NaN.
   `merge_measured()` guarantees a rule never overrides a measured head.
2. **dryer runs off the isolated 240 V aggregate** (PF-corrected bal240_p3)
   instead of raw panel3. ON 0.16% -> 0.12%.
3. **Band rules decontaminated** (hair_dryer, dishwasher, microwave) on
   `p120 = panel - real_240`.
4. **Step/variance rules gated** (sprinklers, bath_lights, refrigerator,
   washing_machine, pressure_pump, computers, tv_stereo): abstain to NaN during a
   strong 240 V event instead of taking a noisy subtraction.

### Why selective, not blanket

The first pass subtracted `bal240` from every rule's input. Band rules improved,
but step/variance rules moved ambiguously: refrigerator and washing_machine ON
rates jumped during dryer events. Part of that is genuine masked-load recovery
(washer and dryer run together); part is noise injected from the contaminated P3
aggregate. Without ground truth the two cannot be separated, so those heads
abstain rather than absorb the noise. This is strictly more honest than the old
behaviour, which silently labelled them OFF during large events.

### Measured effect

| check | result |
|---|---|
| measured heads NaN in rule output | confirmed (P1 heat_pump, P2 water_heater) |
| hair_dryer false positives during 240 V event | 1.03% -> 0.00% |
| dishwasher during 240 V event | 3.32% -> 0.47% |
| microwave during 240 V event | 0.95% -> 0.00% |
| step heads during 240 V event | 100% NaN (abstain) |
| step heads off-event | 100% identical to old rules |
| band heads off-event | >= 98.9% identical to old rules |

Regenerated label counts: dishwasher ON 2553 -> 1069 (-58%), microwave 83 -> 3
(-96%), dryer 492 -> 392, hair_dryer 181 -> 170. Step heads keep their ON counts
and gain NaN abstentions during 240 V events (sprinklers +683, bath_lights +643,
tv_stereo +341, refrigerator +92).

---

## 7. Phase 5 - windows, supervision rewiring, training

### 7.1 Window builder (`build_windows_ct.py`)

Writes `data/panel{P}_ct_windows.npz` and `models/panel{P}_ct_norm.json`.

* **Segment hygiene.** Windows are cut only inside contiguous fully-observed runs.
  At 16.4% coverage, windowing across a dropout would fabricate transitions.
  51,702 observed rows resolve into **80 usable segments**.
* **Event-centred dense sampling.** Baseline stride 10 plus stride-1 starts whose
  midpoint lands on any ON sample. Stride-10 midpoint labelling alone discarded
  most short ON runs (heat_pump kept only 19 train positives and **zero** val and
  test positives).
* **Event-stratified split.** Whole ON-runs are assigned to train/val/test so no
  compressor run straddles a split, with at least one event guaranteed to val and
  test.
* Carries per window midpoint: `panel_kw`, `measured_kw`, `residual_kw`, and the
  Phase-3 regression targets.

Resulting positives:

| panel | windows | head positives (train / val / test) |
|---|---|---|
| P1 | 2350 | heat_pump 135/4/32, solar_pump 0/0/0 |
| P2 | 3410 | water_heater 333/32/29, hair_dryer 64/7/12, sprinklers 386/91/86, bath_lights 202/62/41 |
| P3 | 15199 | dryer 145/20/11, refrigerator 6452/1347/1364, dishwasher 238/38/43, microwave 0/0/0, washing_machine 1039/224/214, pressure_pump 0/0/0, computers 3332/744/694, tv_stereo 1877/395/435 |

### 7.2 Supervision (`train_matnilm_ct.py`)

Following the ESATED result that binary-state weak labels can supervise
disaggregation through an auxiliary-task structure:

* **All heads**: masked BCE on states.
* **Measured heads**: additionally masked MSE against the **pinned** CT watt
  target. This is the only direct watt supervision in the system.
* **Weak heads**: states only. **No fabricated watt targets.** Their power is
  constrained solely through the subtask gate (p*o) and the balance loss, so
  nothing circular re-enters the regression.
* **Masked head** (dryer): no watt target; its 240 V power lives in `measured_kw`.
* Plus `LAMBDA_BAL * energy_balance_loss`.

Model: `MATNilm(residual=True)`, MPS, AdamW lr 2.5e-4, grad clip 5.0,
event-stratified early stopping on heads with >= 20 val positives.

---

## 8. Results

### 8.1 Non-collapse (the headline)

The original failure signature was a max probability shift of **0.0004** under a
plus/minus 2-sigma input perturbation. Under CT-anchored targets plus the balance
loss and residual head:

| panel | zeros | random | +2 sigma | -2 sigma | max shift | verdict |
|---|---|---|---|---|---|---|
| P1 | 0.0810 | 0.0738 | 0.3818 | 0.0448 | **0.3818** | RESPONSIVE |
| P2 | 0.2193 | 0.2485 | 0.8134 | 0.2512 | **0.8134** | RESPONSIVE |

That is a **~950x to ~2000x** increase in input sensitivity versus the collapsed
model. MATNilm now responds to its input rather than emitting a constant prior.
This is the phase's primary claim and it is measured, not asserted.

### 8.2 Panel 1 (40 epochs requested, early-stopped at 19)

| head | kind | test pos | precision | recall | F1 |
|---|---|---|---|---|---|
| heat_pump | MEASURED | 32 | 1.000 | 1.000 | **1.000** |
| solar_pump | weak | 0 | 0.000 | 0.000 | 0.000 |

`L_balance` 0.0166 -> 0.0034. Residual mean 0.0001 kW.

**Read this with care.** heat_pump's 32 test positives come from a **single ON
event**, and val held only 4 positives. F1 = 1.000 means the model separated one
clean 5 kW event from baseline. It is not a generalization claim. solar_pump has
zero positives anywhere (its rule needs irradiance; no weather exists after Jun
15), so its 0.000 is undefined rather than a failure.

### 8.3 Panel 2 (15 epochs)

| head | kind | test pos | precision | recall | F1 |
|---|---|---|---|---|---|
| water_heater | MEASURED | 29 | 0.967 | 1.000 | **0.983** |
| hair_dryer | weak | 12 | 1.000 | 1.000 | 1.000 |
| sprinklers | weak | 86 | 0.940 | 0.919 | 0.929 |
| bath_lights | weak | 41 | 1.000 | 1.000 | 1.000 |

`L_balance` 0.0563 -> 0.0049 (11x reduction). Residual mean 0.036 kW, p90 0.090 kW.
Best val avg F1 0.9828.

water_heater's **0.983 is the strongest honest number in this work**: it is scored
against measured labels, over 29 test positives drawn from a held-out event.

### 8.4 Panel 3 (stopped at epoch 3 of 6)

Training was halted deliberately; the model was still improving.

| epoch | val avg F1 | dryer | refrigerator | dishwasher | washing_machine | computers | tv_stereo |
|---|---|---|---|---|---|---|---|
| 1 | 0.8051 | 0.851 | 0.221 | 0.916 | 0.876 | 0.975 | 0.992 |
| 2 | 0.8196 | 0.784 | 0.374 | 0.950 | 0.828 | 0.983 | 0.999 |
| 3 | 0.8335 | 0.833 | 0.412 | 0.938 | 0.821 | 0.999 | 0.997 |

`L_balance` 0.0145 -> 0.0062. No test report was written; P3 must be rerun to
completion (bs 128 on MPS; bs 512 exhausts MPS memory at d_model 128).

The refrigerator F1 of 0.221-0.412 is the most informative number on this panel.
It confirms the degenerate label diagnosed earlier: the fridge rule reports ON for
96.7% of the rows where it speaks at all. A near-constant label supplies almost no
information, and the head cannot learn from it. This is a label defect, not a
model defect.

### 8.5 The circularity that remains

**Weak-head F1 values are scored against the rule labels that generated them.**
For 12 of 14 heads this is grading the student with its own answer key. Only
heat_pump and water_heater have honest F1. The high weak-head numbers (hair_dryer
1.000, tv_stereo 0.997) demonstrate that the network can reproduce the rules, not
that the rules are right.

Removing that circularity requires ground truth the current hardware does not
provide. The walk-test is the cheapest source of it.

### 8.6 Summary of what changed

| dimension | before | after |
|---|---|---|
| measured heads | 0 of 14 | 2 of 14 (54% of sub-panel energy via 3 x 240 V loads) |
| regression targets | panel apportioned by rule labels (circular) | measured pinned + 120 V remainder + residual |
| weak-head watt targets | fabricated | none (states-only supervision) |
| MATNilm input sensitivity | 0.0004 | 0.3818 (P1) / 0.8134 (P2) |
| rule false positives under 240 V load | present | removed (band) or abstained (step) |
| honest F1 available for | 0 heads | 2 heads |

---

## 9. Files

Training code (all additive; live pipeline untouched):

    pull_data_ct.py        Phase 1  panels + legs + volts -> raw_pivot_ct.parquet
    make_labels_ct.py      Phase 2  measured + rule labels -> labels_*_ct.parquet
    reg_targets_ct.py      Phase 3  CT-anchored targets, PF, energy_balance_loss
    rule_engine_ct.py      Phase 4  decontaminated, measured-head-retired rules
    build_windows_ct.py    Phase 5  segment-hygienic, event-stratified windows
    train_matnilm_ct.py    Phase 5  balance trainer + non-collapse test
    model_matnilm.py       modified: guarded residual head (residual=False default)

Phase 0 analysis and the walk-test kit:

    phase0_ct/phase0_ct_profile.py          per-CT signature profile
    phase0_ct/phase0_ct_diag.py             split-phase vs branch-CT discriminator
    phase0_ct/phase0_ct_finalize.py         candidate map + balanced-leg extraction
    phase0_ct/phase0_ct_energy.py           energy accounting (54% coverage figure)
    phase0_ct/phase0_walktest_precheck.py   history-side screen
    phase0_ct/phase0_walktest_queries.py    walk-test verifier (validated on a real event)
    ct_appliance_map.json                   legs + derived measured appliances

Artifacts:

    data/raw_pivot_ct.parquet        26 cols, Jun 15 - Jul 6
    data/labels_*_ct.parquet         14 heads, NaN-masked
    data/measured_watts_ct.parquet   pinned regression terms
    data/panel{P}_ct_windows.npz     windows + panel_kw/measured_kw/residual_kw
    models/nilm_panel{1,2}_ct.pt     trained CT models
    reports/panel{1,2}_ct_train.json full metrics, history, sensitivity

Rollback: delete the `*_ct` files and restore `model_matnilm.py` from its `.bak`.
The live path (`pull_data.py`, `rule_engine.py`, `make_labels.py`,
`train_matnilm.py`, `raw_pivot.parquet`, `labels_*.parquet`, production ONNX)
was never modified.

---

## 10. Known limitations

1. **Coverage 16.4%.** ~86 hours of real data over 22 days. Every count above is
   bounded by this. Producer SSL dropouts.
2. **heat_pump sparsity.** 29 ON events total, ~5 usable after segmentation; 1
   test event. Summer duty ~1%. Its F1 is not a generalization claim.
3. **solar_pump, pressure_pump, microwave: zero positives.** solar_pump needs
   irradiance (no weather after Jun 15); pressure_pump's rule never fires;
   microwave fell to n=3 after decontamination, which may have pruned real events
   alongside false ones.
4. **refrigerator label degenerate.** 96.7% ON where the rule speaks. F1 0.22-0.41
   is the label's fault.
5. **bal240_p3 contaminated.** dryer + oven + cooktop share the balanced bucket.
   dryer has no measured label until the walk-test fingerprints split them.
6. **Weak-head F1 is circular.** Only heat_pump and water_heater have honest F1.
7. **Panel 3 incomplete.** 3 of 6 epochs; no test report.
8. **PF is a regression estimate.** 0.941 / 1.000 / 0.989 from leg coefficients; a
   step-based measurement on a real heat-pump event gives 0.96. Walk-test should
   pin this per load.

---

## 11. Roadmap

Ordered by leverage. Items 1 and 2 multiply everything downstream.

### Tier 1 - substrate (do first, cheap, unblocks everything)

**1. LAN-direct eGauge ingestion.** Coverage 16.4% -> ~100%. heat_pump 29 events
-> ~180; microwave n=3 -> ~20; refrigerator gains the OFF samples that make its
label non-degenerate. This is a one-line ingestion change and is the single
highest-leverage action available. No labelling cleverness beats a 6x data
multiplier.

**2. Walk-test (Phase 0.2).** The protocol and verifier are written and validated
(`WALKTEST_PROTOCOL.md`, `phase0_ct/phase0_walktest_queries.py`, which correctly
read the Jun 19 heat-pump event: both legs, 5737 W balanced vs 5682 W panel,
PF 0.96). Priorities, in order:
   * separate dryer / oven / cooktop on P3 (level and duration fingerprints) - the
     only way to split bal240_p3 and promote dryer to measured;
   * identify solar_pump's leg (P1 shows a 120 V plateau on both legs, so a second
     P1 load exists, likely a blower);
   * confirm leg-to-phase;
   * measure isolated real-power steps to pin PF per load.

   The logged toggle windows become the **gold test set**: the only honest
   event-level F1 available for the 12 rule-labelled heads. Treat as evaluation
   data first, profile source second, never as training data.

**3. Merge a weather source** for the CT window (historical API is sufficient) to
revive solar_pump's irradiance rule, or exclude the head from headline metrics
until it has positives.

### Tier 2 - make label quality measurable

**4. Synthetic injection harness.** Composite known appliance traces onto real
measured quiet baselines, run `rule_engine` on the composite, score its labels
against the injected truth. This yields per-rule precision, recall, and timing
error with real ground truth, on demand. Every subsequent rule change then ships
with a before/after score instead of a plausibility argument.

Precedent: AMBAL extracts parametrised signature models from real datasets and
drives a trace generator; SynD releases 180 days of synthetic aggregate plus
per-appliance power built from real appliance traces; SmartSim does the same for
25 appliances. Copy from SynD specifically:
   * **category-aware handling** (periodical fridge = repeated recorded cycles;
     multi-pattern dishwasher and washing machine = random programme selection -
     one walk-test cycle is not enough for these);
   * **duration interpolation only for user-controlled appliances** (microwave,
     hair dryer), drawn from per-appliance bounds;
   * **nested uniform -> normal start-time placement** so injected events never
     align, respecting the Switch Continuity Principle;
   * **representativeness validation** via Hellinger and Jensen-Shannon distance
     between injected and observed power PMFs, plus daily-energy and load-profile
     comparison.

This harness improves on SynD in one respect by construction: SynD's mains is a
sum of appliance signals and therefore lacks the noise of unmetered loads, whereas
compositing onto **real measured panel baselines** retains the true noise floor.
SynD also could not monitor split-phase loads such as electric water heaters; here
those are already measured via bal240.

**5. Retroactive backtest.** Run the old rules against the ~30 verified heat_pump
and water_heater events to quantify each rule *type's* error profile (band rules
over-fire under co-load ~5x; step rules miss under masking). Use that as the trust
prior for the 12 heads that cannot be measured.

**6. Truth-free regression tests.** Label flip-rate (chatter) and duty/duration
plausibility against the appliance cards. Cheap gates on every rule change.

### Tier 3 - rule engine v2 (all 14 heads kept)

**7. Event-based labelling instead of per-sample thresholding.** Detect rising
edges, match to falling edges of compatible magnitude within a duration window,
label the enclosed span as one event. This is Hart's original formulation and the
standard fix for switching-sensitive loads. It kills boundary chatter, yields
duration for free, and directly addresses two current pathologies:
   * refrigerator: require **cycling structure** (bounded ON durations with
     periodicity). A fridge that never cycles off is baseline misattribution.
   * microwave: a 900-1500 W edge pair lasting 30 s to 10 min is a crisp signature
     that survives dinner-hour contamination far better than a band threshold.

**8. Data-derived appliance feature cards.** Replace nameplate specs with
statistically extracted per-appliance cards: standby power, ON power range, mean
ON duration, usage pattern, cycle duration. Phase 0 already proved the need (spec
said heat_pump 1500-4000 W; measurement says 4900-5750 W). Per the LLM4NILM
ablation, power range is the most critical field, with pattern and duration
complementary; duration is precisely the axis that separates same-band appliances,
which is how dryer / oven / cooktop will be split.

**9. Consensus gate from the legs.** `imbal120` is an independent second estimate
of the panel's 120 V total. Where `p120` and `imbal120` agree, trust the 120 V
signal; where they diverge, abstain. This replaces Phase 4's blanket
abstain-during-any-240 V-event with a finer criterion.

**10. Label-level sum constraint.** Before emitting, check that the summed nominal
watts of ON heads does not exceed `p120` plus tolerance; on violation, flip the
lowest-confidence head to NaN. This applies the Phase-3 energy balance at
labelling time and prevents rules from jointly claiming more power than physically
exists. Precedent: the sum-to-k constraint in S2K-NMF.

**11. Confidence-weighted labels.** Emit {0, 1, NaN} plus a weight (measured and
multi-rule consensus 1.0; single marginal rule ~0.3) and train with weighted BCE,
so weak labels stop impersonating truth in the loss. Theoretically this treats the
rules as noisy labelling functions, per the label-noise NILM literature and
programmatic weak supervision.

### Tier 4 - training

**12. Finish Panel 3** (bs 128 on MPS; bs 512 OOMs at d_model 128), and rerun P1
and P2 once coverage improves.

**13. Profile pool and on-the-fly augmentation.** Import UK-DALE activations for
fridge, dishwasher, microwave and washing machine (same 6 s cadence,
near-identical appliance set), scale into this house's bands, composite onto
measured baselines. Then apply MATNilm sample augmentation per batch: sample a
profile, scale magnitude by alpha ~ N(1, sigma^2), scale duration by
beta ~ N(1, sigma^2), subtract the old trace from the aggregate, add the modified
profile, update the state label. Every synthetic positive descends from a real
signature, so its label is true by construction. MATNilm's S2 -> S3 result (one
day of labels plus profiles matching full-dataset training) is the direct evidence
this escapes the ~30-events-per-head regime. The walk-test toggles and the 29/30
measured events are already a native profile pool.

**14. Mixed strong and soft labels.** CamAL reports that supervised models trained
on soft labels lose little accuracy, and that when strong labels are scarce,
combining strong and soft labels improves results between 34% and 1200%. That is
exactly this system's regime (2 measured heads plus 12 weak). The cautionary
companion result: weak-only MIL (Tanoni's CRNN without strong labels) averages
F1 ~0.16, so the measured heads are what make the mixture work.

**15. Escalation path for stubborn heads.** If refrigerator or computers remain
poor after the above, train a per-appliance detection ResNet ensemble (kernel
sizes {5, 7, 9, 15, 25}) on window-level weak labels over the decontaminated
`p120` substrate, localize via averaged class activation maps with sigmoid
attention masking, and set power = state x mean power, clipped by the aggregate.
This is CamAL's mechanism; its power step independently validates the existing
nominal-watt lookup plus power-gate design in `rules_additive.py`. Reported label
efficiency: baselines needed on average 144x more labels to match it. This is a
weekend experiment, not an architecture migration.

**16. Noise-robust losses** for the weak heads (the label-noise literature's
result that networks fit clean statistics before noise).

### Tier 5 - promotion

**17. A/B protocol.** Freeze current labels as baseline; regenerate with engine v2;
evaluate at three levels:
   * **rules**: injection-harness scores per head, old vs new (most of the
     improvement should be demonstrable here **before any training run**);
   * **labels**: flip-rate, duty plausibility, sum-constraint violation rate;
   * **model**: identical BiLSTMs trained on old vs new labels, compared only on
     the walk-test gold events and the measured heads' truth - **never** on rule
     labels.

   Promotion rule: new labels win on the harness and the gold set, or they do not
   ship. Do not promote any CT model to ONNX production until the measured heads
   beat the incumbent BiLSTM on the gold set.

**18. Winter data** for heat_pump event density. No amount of method substitutes
for the compressor actually running.

### Sequencing

    LAN-direct  ->  injection harness  ->  backtest  ->  feature cards
        ->  rule engine v2  ->  walk-test (gold set + fingerprints)
        ->  profile pool + augmentation  ->  mixed-supervision retrain  ->  A/B  ->  promote

LAN-direct lands as early as possible because it multiplies every count downstream.

---

## 12. References

1. Xiong, J., Hong, T., Zhao, D., Zhang, Y. *MATNilm: Multi-appliance-task NILM
   with Limited Labeled Data.* arXiv:2307.14778 (2023). Sample augmentation,
   appliance operation-profile pools, S2/S3 limited-data scenarios, preprocessing
   hygiene (exclude 20 continuous missing or 1200 continuously unchanged samples),
   subtask-gated MSE + BCE loss.
2. Xue, J., Wang, X., He, X., Liu, S., Wang, Y., Tang, G. *Prompting Large Language
   Models for Training-Free Non-Intrusive Load Monitoring* (2025). Ground-truth
   states by thresholding submetered channels; appliance feature cards; ablation
   ranking power range above pattern and duration; ON-focused F1 under class
   imbalance.
3. Xia, P., Zhou, H., Yang, T., Zhou, W., Liu, Z., Wang, X., Li, X.-Y. *ESATED:
   Leveraging Extra-weak Supervision with Auxiliary Task for Enhanced
   Non-intrusiveness in Energy Disaggregation.* Proc. ACM IMWUT 8(4) (2024).
   Binary-state-only labels supervising disaggregation via an auxiliary state
   classification task; basis for the states-only supervision of weak heads.
4. Tanoni, G., Principi, E., Squartini, S. *Multilabel Appliance Classification
   with Weakly Labeled Data for NILM.* IEEE Trans. Smart Grid 14(1):440-452 (2023).
   Multiple-Instance Learning formulation of segment-level weak labels.
5. Petralia, A., et al. *Few Labels Are All You Need: A Weakly Supervised Framework
   for Appliance Localization (CamAL).* arXiv:2506.05895 (2025). Detection-only
   ensemble plus CAM localization; soft-label mixing; 144x label efficiency.
6. Klemenjak, C., et al. *SynD: A Synthetic Energy Dataset for NILM.* Nature
   Scientific Data 7:108 (2020). Category-aware generation, start-time placement,
   Switch Continuity Principle, Hellinger / Jensen-Shannon validation.
7. Buneeva, N., Reinhardt, A. *AMBAL: Realistic Load Signature Generation* (2017);
   Chen, D., et al. *SmartSim* (2016). Parametrised signature models extracted from
   real data driving a trace generator.
8. Rahimpour, A., Qi, H., Fugate, D., Kuruganti, T. *Non-Intrusive Energy
   Disaggregation Using NMF with Sum-to-k Constraint.* arXiv:1704.07308. The
   sum-to-total constraint lineage behind the Phase-3 energy balance.
9. Hart, G. *Nonintrusive Appliance Load Monitoring.* Proc. IEEE 80(12) (1992).
   The original event-based edge-matching formulation.
10. Nolasco, L., Lazzaretti, A., Mulinari, B. *DeepDFML-NILM.* IEEE Sensors J.
    22(1) (2022); *eFHMM-TS*, arXiv:2107.12582. Modern event detection and
    classification designs.
11. Kelly, J., Knottenbelt, W. *UK-DALE.* Nature Scientific Data (2015). 6 s
    cadence profile source for the injection pool.
12. Adabi, A. *Intelligent Energy Management System framework* (UCSC, 2016). The
    four-domain IEMS framing this system implements.
13. Label noise in time-series classification: arXiv:2105.00349. Programmatic weak
    supervision label models (FABLE line). Footing for confidence-weighted labels.

---

## 13. One-paragraph summary

The CT channels are split-phase mains legs, not per-appliance branch CTs, and that
falsification reshaped every subsequent phase. What the legs do give is a clean
measured label for each panel's sole 240 V load, covering 54% of sub-panel energy
across three appliances, of which two (heat_pump, water_heater) are clean enough
to pin regression targets and one (dryer) is contaminated by oven and cooktop.
Pinning those targets, apportioning only the 120 V remainder, adding a residual
head and an energy-balance loss, and removing fabricated watt targets from the
weak heads moved MATNilm's input sensitivity from 0.0004 to 0.38-0.81 and produced
the first honest F1 numbers in the project: water_heater 0.983 on measured truth.
Everything else remains rule-supervised, and the F1 reported for those heads
measures agreement with the rules rather than with reality. Closing that gap needs
data volume (LAN-direct ingestion), ground truth (the walk-test as a gold set),
and grounded synthesis (profile pools and injection) - in that order.
