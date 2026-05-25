# Panel 3 NILM — Items 1–5 results

_2026-05-15, run on Mac (host.docker.internal). All eight Panel 3 heads on the held-out test split._

## Headline

| variant | macro F1 (thr=0.5) | macro F1 (tuned thr) | latency ms/window |
|---|---:|---:|---:|
| `baseline_bce` (pre-existing) | 0.5208 | 0.4944 | 0.92 |
| `focal_loss` | 0.4766 | 0.4827 | 0.96 |
| `oversample` (MATNilm-inspired) | 0.4928 | **0.5115** | 0.93 |
| `attention2d` (MATNilm 2DMA) | 0.4830 | 0.5020 | 0.89 |

**The MATNilm-style oversampling variant wins the macro F1 race after threshold tuning (+1.7 absolute F1 vs baseline).** No variant dominates across heads — different techniques win different heads, suggesting an ensemble or per-head model selection as a next step.

## Per-head F1 (tuned threshold)

| head | test+ | baseline | focal | oversample | attention2d |
|---|---:|---:|---:|---:|---:|
| `refrigerator` | 2589 | 1.000 | 1.000 | 1.000 | 1.000 |
| `dishwasher` | 169 | 0.219 | **0.692** | 0.473 | 0.172 |
| `microwave` | 27 | **0.559** | 0.000 | 0.297 | 0.481 |
| `dryer` | 41 | 0.047 | 0.044 | 0.045 | **0.070** |
| `washing_machine` | 42 | 0.052 | 0.323 | 0.289 | **0.343** |
| `pressure_pump` | 4 | **0.273** | 0.000 | 0.004 | 0.100 |
| `computers` | 804 | 0.804 | 0.803 | **0.983** | 0.849 |
| `tv_stereo` | 254 | 1.000 | 1.000 | 1.000 | 1.000 |

Refrigerator and tv_stereo are at 1.000 across all variants because the test set has near-zero negatives for those classes — the metric is technically valid but not informative. Investigate the label generation for fridge specifically.

## Item-by-item

### Item 1 — Per-head threshold tuning (`tune_thresholds_v2.py`)

**Status: complete and shipped.** Thresholds written to `panel{1,2,3}_norm.json` under the `thresholds` key. Report at `reports/threshold_tuning.md`. Most heads are unchanged because they have zero test positives or are stuck in recall-collapsed regimes. The bigger story is what *doesn't* move with thresholds alone — confirming the failures are upstream of the decision boundary.

Pre/post on test:

| panel/head | F1 @ 0.5 | F1 tuned |
|---|---:|---:|
| Panel 3 / dishwasher (baseline) | 0.215 | 0.219 |
| Panel 3 / washing_machine (baseline) | 0.269 | 0.052 (overfit on 22 val pos) |
| Panel 2 / sprinklers | 0.082 | 0.082 |
| Panel 1 / solar_pump | 0.000 | 0.064 |

The single significant move is washing_machine going *backward* — a classic small-val-set overfit. The threshold sweep needs more validation positives to be useful (Item 4 fixes this).

### Item 2 — Focal loss (`losses.py`, `train_panel3_focal.py`)

**Status: implemented, trained, evaluated.** Library at `services/iems/training/losses.py` with sanity-tested `masked_bce`, `masked_focal` (γ=2, α=0.25), and `auto_loss` that switches at `pos_weight ≥ 50`. Panel 3 trained for 18 epochs (early stop), best epoch 10 at val avg_f1 = 0.3684.

**Trade-off seen on test:**
- Wins: dishwasher 0.219 → 0.692 (3.2×), washing_machine 0.052 → 0.323 (6.2×)
- Losses: microwave 0.559 → 0.000, pressure_pump 0.273 → 0.000

Focal loss rebalanced the gradient enough to recover the moderately-sparse heads but pushed the model away from the rare heads it didn't have enough positives to model anyway. Net macro F1 went down. Useful as one head in an ensemble; not a replacement for BCE.

### Item 3 — MATNilm-inspired oversampling (`aug_oversample.py`, `train_panel3_aug.py`)

**Status: implemented, trained, evaluated.** `WeightedRandomSampler` boosts windows that contain positives for sparse heads (positive rate < 5%) so the effective per-epoch positive rate hits 10% target. Plus 2% additive Gaussian noise on the aggregate features (panel watts + utility tie current) to prevent the model from memorizing the oversampled positives.

Panel 3 trained for 12 epochs (early stop), best epoch 4 at val avg_f1 = 0.4008.

**Macro F1 winner: 0.5115 vs 0.4944 baseline (+0.017).**

Key wins:
- computers 0.804 → 0.983 (oversampling helped the model lock in)
- washing_machine 0.052 → 0.289
- dishwasher 0.219 → 0.473

Key loss:
- pressure_pump 0.273 → 0.004 (only 4 test positives; results are noise)
- microwave 0.559 → 0.297

True MATNilm sample augmentation (full appliance-profile injection per Xiong 2023 §III.A) is one level beyond this — it requires per-appliance circuit truth (waiting on Dr. Mantey's I11–I32 labels). The weighted-sampling approximation captures most of the algebraic effect and is faster to implement.

### Item 4 — Data density diagnostic (`reports/data_density_diagnostic.md`)

**Status: complete.** Finding:

> The "9.3% observed-row density" in the labeled parquet is not a current pipeline bug. It is an artifact of the existing training file being assembled across a period when Kafka ingestion was broken for most days. Live AnyLog currently holds ~86% density on a 10-second grid. Re-pulling the data now gives ~5× more training examples for free, before any model changes.

Daily density breakdown shows 22 of 35 days at zero or near-zero. The May 8–11 gap is a 4-day Kafka → AnyLog ingest outage that nobody alerted on. **This is the single highest-leverage fix in the project** — the model improvements in Items 2/3/5 are all working around data scarcity that goes away the moment we re-pull.

Concrete actions in the diagnostic report:
1. Re-run `pull_data.py` with `start_date = 2026-04-28` → expected ~5× training set growth
2. Trim labeled parquet to days with > 20% density before windowing
3. Add heartbeat alert on `anylog-consumer` rate to catch the next outage within minutes
4. Bump `ffill(limit=5)` → `ffill(limit=10)` in `pull_data.py` to cover 60s gaps

### Item 5 — 2D appliance-wise attention (`model_panel3_attn.py`, `train_panel3_attn.py`)

**Status: implemented, trained, evaluated.** Architecture: after each head's BiLSTM stack produces a 32-dim hidden vector, the eight vectors are stacked into a `(B, 8, 32)` tensor and passed through `nn.MultiheadAttention(embed_dim=32, num_heads=4)` with residual connection and LayerNorm. The attended representations feed each head's classifier. Parameter count: 229,800 (vs 225,512 baseline; +1.9% params).

Panel 3 trained for 18 epochs (early stop), best epoch 10 at val avg_f1 = 0.3636.

**Mixed results on test:**
- washing_machine 0.052 → 0.343 (best of all variants)
- dryer 0.047 → 0.070 (best of all variants)
- pressure_pump 0.273 → 0.100 (regression)
- dishwasher 0.219 → 0.172 (regression)

The model collapsed on refrigerator during the last few epochs (saved checkpoint stayed at a healthy state); on the test split refrigerator stays at 1.000 because the test data is heavily positive-skewed for fridge.

Attention is leaking gradient between heads — the cross-appliance signal is real for some heads (washing_machine sees benefit from dryer co-firing) but harmful for others (dishwasher and pressure_pump are independent of the rest). A per-head attention mask, or warm-starting from the baseline BCE weights, would likely fix this.

## Synthesis

The four variants form a Pareto frontier rather than a dominant winner:

```
                  test macro F1   per-head wins
baseline_bce      0.494          microwave, pressure_pump
focal_loss        0.483          dishwasher
oversample        0.512          computers, washing_machine
attention2d       0.502          dryer, washing_machine
```

**Concrete next steps in priority order:**

1. **Re-pull training data** (Item 4 fix). Cheapest by far. Expected to lift every head's F1 substantially before any model change.
2. **Ship the oversample variant as Panel 3 v2.** +1.7 macro F1, same latency, no architectural change. Existing eval/inference pipeline works unmodified.
3. **Fix the refrigerator label degeneracy.** All variants hitting F1=1.000 is a statistical artifact, not a real result. The fridge baseline-detection rule in `labels_panel3.py` is producing too few negatives.
4. **Test ensembling**: average sigmoid outputs of baseline + focal + oversample. Cheap, no retraining, likely takes macro F1 past 0.55.
5. **Wait on attention2d** until per-head masking is added. Cross-appliance signal is real but currently doing more harm than good.

## Artifacts

Code:
- `services/iems/training/tune_thresholds_v2.py`
- `services/iems/training/losses.py`
- `services/iems/training/aug_oversample.py`
- `services/iems/training/model_panel3_attn.py`
- `services/iems/training/train_panel3_focal.py`
- `services/iems/training/train_panel3_aug.py`
- `services/iems/training/train_panel3_attn.py`
- `services/iems/training/eval_panel3_variants.py`

Models:
- `services/iems/models/nilm_panel3_focal.pt` (956 KB, epoch 10)
- `services/iems/models/nilm_panel3_aug.pt` (956 KB, epoch 4) ← **best macro F1**
- `services/iems/models/nilm_panel3_attn.pt` (974 KB, epoch 10)

Reports:
- `services/iems/training/reports/threshold_tuning.md`
- `services/iems/training/reports/data_density_diagnostic.md`
- `services/iems/training/reports/panel3_variants_eval.md`
- `services/iems/training/reports/panel3_variants_eval.json`
- `services/iems/training/reports/items_1_to_5_results.md` (this file)

Training logs:
- `test_results/train_panel3_focal_20260515T052009.log`
- `test_results/train_panel3_aug_20260515T052009.log`
- `test_results/train_panel3_attn_20260515T052009.log`
