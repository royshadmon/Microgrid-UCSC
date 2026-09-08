# Training pipeline

**This pipeline does not run on Pat's box.** The labellers, the rolling trainer,
`export_physical.py` and `gen_norm_physical.py` exist only in the repository, and
so does the training archive under `analysis/egauge_consolidation/` and
`analysis/solar/`. Pat's box carries an older generation of training scripts that
did not produce what it is currently serving.

Models are made on the Mac and shipped to Pat's box by
`~/rolling-deploy/deploy_rolling.sh`.

```
egauge_consolidated_all_eras.parquet  +  solar_history.parquet
        │
        ├── physical_labeler_v2.py ──▶ labels_physical_v2.parquet
        │                              weights_physical_v2.parquet
        │
        ├── solar_features.py ───────▶ sun_elev, csky_ghi (deterministic)
        │                              pv_power, pv_valid (measured where it overlaps)
        │
        └── train_rolling.py ────────▶ models/panel{N}_bilstm_physical.pt
                                       models/panel{N}_thresholds.json
                                       reports/panel{N}_rolling_unit_tests.csv
                    │
                    ├── export_physical.py ──▶ services/iems/models/nilm_panel{N}.onnx
                    └── gen_norm_physical.py ▶ services/iems/models/panel{N}_norm_bilstm.json
                                                          │
                                                          ▼
                                      ~/rolling-deploy/deploy_rolling.sh  ──▶ Pat's box
```

## What is deployed

The **18 feature** generation, live since 2026-09-08. All three model copies on
the host now agree, which was not true before this deploy.

```
window 100, mid 50, stride 10, 18 features on all three panels
Panel1 4 heads, Panel2 4 heads, Panel3 14 heads, 22 in total
```

Feature order, each panel's own channel first, then a shared tail.

```
<panel own>, <other panel>, <other panel>, VrmsA, VrmsB, I31, I32, F1,
Grid Power, Shop, I11, I21, tod_sin, tod_cos, sun_elev, csky_ghi,
pv_power, pv_valid
```

`sun_elev` and `csky_ghi` are computed from a NOAA approximation and the Haurwitz
clear sky model, so they are exact at inference with no data source. `pv_power`
comes from the live Solar Assistant snapshot and `pv_valid` flags whether it is
real, matching how the training archive encodes rows with no measured PV. The
loop logs the snapshot each tick, for example
`solar: pv=5121W batt=-36W soc=99% grid=-4007W load=768W (age=1s)`, so a
`pv_valid` of 0 in daylight is visible immediately.

### How it got there

The models were sitting on the deployment root since 2026-08-10, produced by
`deploy_rolling.sh`, and were loaded by nothing because no container bind mounts
that directory. Making them live took an image rebuild.

```bash
cd /home/pat/microgrid_manager/Microgrid-UCSC-dev_fin
sudo docker compose build iems-inference          # COPY services/iems picks up the models
sudo docker compose up -d --no-deps iems-inference
```

`iems-backend` builds `FROM microgrid-ucsc-dev_fin-iems-inference`, so it was
rebuilt straight afterwards and inherited the same models. That is why
`/iems/onnx/models` now reports 18 features instead of the stale 12 feature set
it reported before.

### Deployed thresholds

| panel | thresholds |
|---|---|
| 1 | `heat_pump` 0.95, `solar_pump` 0.95, `jacuzzi_pump` 0.50, `strip_heater` 0.50 |
| 2 | `water_heater` 0.15, `hair_dryer` 0.65, `sprinklers` 0.50, `bath_lights` 0.75 |
| 3 | `dryer` 0.50, `washing_machine` 0.90, `dishwasher` 0.80, `microwave` 0.30, `pressure_pump` 0.95, `refrigerator` 0.80, `garage_fridge` 0.80, `garage_freezer` 0.85, `computers` 0.90, `tv_stereo` 0.80, `oven` 0.90, `cooktop` 0.90, `counter_appliance` 0.70, `garage_opener` 0.85 |

## Measured performance

Rolling walk-forward, four contiguous folds, each fold predicted before it was
ever trained on. Figures below are fold 4, the final and most-trained fold, from
`services/iems/training/reports/panel{N}_rolling_unit_tests.csv`. `n_pos` is the
number of positive samples the fold contained. A head with fewer than 50
positives is reported as unmeasured rather than given a number.

### Panel 1

| head | n_pos | P | R | F1 |
|---|---|---|---|---|
| `heat_pump` | 763 | 0.856 | 1.000 | 0.923 |
| `solar_pump` | 351 | 0.066 | 0.801 | 0.121 |
| `jacuzzi_pump` | 25 | unmeasured | unmeasured | unmeasured |
| `strip_heater` | 0 | unmeasured | unmeasured | unmeasured |

`heat_pump` across folds 2, 3 and 4: F1 0.939, 0.984, 0.923. `solar_pump` across
the same folds: F1 0.107, 0.143, 0.121, with recall between 0.511 and 0.844 and
precision between 0.060 and 0.078.

### Panel 2

| head | n_pos | P | R | F1 |
|---|---|---|---|---|
| `water_heater` | 323 | 1.000 | 0.969 | 0.984 |
| `hair_dryer` | 63 | 0.558 | 1.000 | 0.716 |
| `sprinklers` | 375 | 0.326 | 0.331 | 0.328 |
| `bath_lights` | 452 | 0.227 | 0.699 | 0.343 |

`water_heater` across folds 2, 3 and 4: F1 0.934, 0.971, 0.984. `hair_dryer` and
`sprinklers` were unmeasured or 0.0 in earlier folds on small positive counts,
and reach 0.716 and 0.328 in fold 4 where they have 63 and 375 positives.

### Panel 3

| head | n_pos | P | R | F1 |
|---|---|---|---|---|
| `microwave` | 263 | 0.931 | 0.977 | 0.954 |
| `computers` | 1308 | 0.800 | 0.942 | 0.865 |
| `dishwasher` | 608 | 0.648 | 0.938 | 0.767 |
| `cooktop` | 363 | 0.600 | 1.000 | 0.750 |
| `washing_machine` | 1021 | 0.464 | 0.865 | 0.604 |
| `tv_stereo` | 780 | 0.384 | 0.888 | 0.536 |
| `garage_opener` | 79 | 0.610 | 0.456 | 0.522 |
| `counter_appliance` | 240 | 0.347 | 1.000 | 0.516 |
| `garage_fridge` | 2213 | 0.363 | 0.841 | 0.507 |
| `garage_freezer` | 1272 | 0.312 | 0.852 | 0.457 |
| `refrigerator` | 1210 | 0.230 | 0.864 | 0.363 |
| `pressure_pump` | 52 | 0.195 | 0.904 | 0.321 |
| `dryer` | 29 | unmeasured | unmeasured | unmeasured |
| `oven` | 41 | unmeasured | unmeasured | unmeasured |

`oven` measured 0.781 in fold 3 on 309 positives and `garage_opener` measured
0.542 in fold 3 on 56. `dryer` has not reached 50 positives in any fold, so it
has never been measured.

### Reading these numbers

Recall runs well ahead of precision on most heads. That shape comes from the
labelling, which fills abstentions conservatively, and from the runtime power
gate, which vetoes an ON whose own minimum on-threshold exceeds the whole
measured panel draw. The gate removes false positives after the model, so a head
can carry low standalone precision and still behave in production.

The three refrigeration heads sit between 0.363 and 0.507. They share one power
band on one panel and are separated by duty and period priors rather than by
measurement, so per unit attribution is an estimate. Their aggregate is the
trustworthy quantity.

`sun_elev`, `csky_ghi`, `pv_power` and `pv_valid` were added specifically for the
solar gated heads. `solar_pump` is the head they target and it measures 0.121 at
fold 4, which is why the runtime does not rely on the model for it.

## An open item this deploy surfaced

`postprocess.py` lists `water_heater` and `dishwasher` in `COLLAPSED`, which
forces both to `UNKNOWN` before their thresholds are ever compared. That set was
chosen after the 2026-08-07 retrain, where both scored a degenerate F1 of 1.000
on test slices that were 100 percent positive.

In the rolling run that produced the deployed models, both are measured against
real negatives.

| head | fold 2 | fold 3 | fold 4 |
|---|---|---|---|
| `water_heater` F1 | 0.934 | 0.971 | 0.984 |
| `dishwasher` F1 | 0.131 | 0.251 | 0.767 |

`COLLAPSED` predates those numbers, so two heads with measured performance are
currently reported as `UNKNOWN` and their live state comes entirely from
`rules_additive`. Removing them from `COLLAPSED` is a one line change in
`postprocess.py` followed by an `iems-inference` rebuild. It has **not** been
done, because it changes what the dashboard asserts about two appliances and
that is a call for whoever owns the site.

## The windowing contract

`W = 100, STRIDE = 10, MID = 50`. One hundred samples at a 6 s grid is ten
minutes, matching LLM4NILM. Stride ten is one minute. The label is a majority
vote over the centre ten samples, indices 45 to 54.

This contract is why `min_dur_hard` and `min_samples` exist in the signature
table. An event shorter than the effective mid sampling grain is invisible to the
model no matter how good the labels are, and `signature_crosscheck.py` reports,
per appliance, what fraction of event samples survive as mid window positives.

## Architecture

Conv front end into per head BiLSTM branches, `model_panel3.py`. Per head
branches let each appliance specialise, fridge baseline cycling against
dishwasher multi stage against microwave bursts, without the bigger heads
dominating shared parameters.

```python
class HeadBranch(nn.Module):
    def __init__(self, in_dim: int = 32):
        self.lstm1 = nn.LSTM(in_dim, 32, batch_first=True, bidirectional=True)
        self.lstm2 = nn.LSTM(64, 16, batch_first=True, bidirectional=True)
        self.head  = nn.Sequential(nn.Dropout(0.2), nn.Linear(32, 16),
                                   nn.ReLU(), nn.Linear(16, 1))
```

`Panel{N}Net.HEADS` is the ONNX output contract. `export_physical.py` reads the
head list from `canonical_signatures.PANEL_HEADS` rather than hard coding it,
because a silent mismatch between ONNX output order and the names the inference
loop expects would mislabel every appliance without raising anything. The older
`export_panel{1,2,3}.py` scripts, which are the ones still on Pat's box, hard
code both the file names and the output names, and Panel1 lists exactly two
outputs, so they cannot export the current models at all.

## Losses

`training/losses.py`. The repository copy carries six functions. The copy on
Pat's box is 61 lines and is the older, smaller version, which is another reason
the host cannot reproduce the deployed models.

| function | use |
|---|---|
| `masked_bce` | binary cross entropy with a scalar `pos_weight`, NaN targets masked out |
| `masked_focal` | focal loss after Lin et al. 2017, for severe imbalance |
| `masked_bce_weighted` | BCE with **both** a scalar class weight and the per sample trust weight the labellers emit |
| `weak_mil_loss` | multiple instance loss over four hour weak windows |
| `dual_loss` | the combined strong plus weak objective |
| `auto_loss` | picks BCE or focal by `pos_weight` against a threshold, default 50 |

The trust weight is the whole reason the labellers emit a weights parquet
alongside the labels. A coupled guess enters training at 0.25, a scored non
coupled event at its own confidence, a quiet house negative at 0.85, a solar gate
at 0.9, and a CT measurement at 1.0. An abstention enters at 0.0 and therefore
not at all.

## Rolling walk-forward training

`training/train_rolling.py` is the current trainer and is repository only. It
replaced the single 70/15/15 chronological split of `train_all_physical.py`,
which left five heads with zero test positives and therefore reported F1 0.000,
indistinguishable from a broken head.

```python
W, STRIDE, MID = 100, 10, 50
BATCH, LR = 256, 1e-3
K_FOLDS = 4
EPOCHS_FIRST = 4   # env EPOCHS_FIRST
EPOCHS_ROLL  = 2   # env EPOCHS_ROLL
PSEUDO_HI, PSEUDO_LO, PSEUDO_W = 0.92, 0.08, 0.30
POS_W_CAP, FOCAL_AT = 200.0, 50.0
MIN_POS = 50
torch.manual_seed(0); np.random.seed(0)
```

The scheme.

```
stage k = 1..3:
  1. train on folds [0..k), warm-started from the previous stage
  2. predict fold k BEFORE ever training on it, so the per-fold metrics are
     true rolling-origin numbers and never self-graded
  3. pseudo-label fold k only where the physics label ABSTAINED (NaN) and the
     model is confident, p>0.92 -> ON, p<0.08 -> OFF, weight 0.30.
     Physics labels are NEVER overridden, only abstentions filled
  4. fold k joins the training pool for stage k+1
```

Folds are contiguous, so there is no leakage across the hundred sample window.

The evaluation policy is explicit, and it exists because of specific ways the
earlier numbers lied.

```
- precision and recall ALWAYS reported, never F1 alone
- heads with fewer than MIN_POS test positives in a fold print 'unmeasured'
- pos_weight cap raised 10 -> 200; heads with pw >= 50 switch to weighted
  focal loss instead of being silently flattened
```

The weighted focal used inside the trainer.

```python
def masked_focal_weighted(prob, target, weight, gamma=2.0, alpha=0.25):
    mask = ~torch.isnan(target)
    p = prob[mask].clamp(1e-6, 1 - 1e-6); t = target[mask]; w = weight[mask]
    p_t = t * p + (1 - t) * (1 - p)
    a_t = t * alpha + (1 - t) * (1 - alpha)
    ll = -a_t * (1 - p_t).pow(gamma) * p_t.log()
    return (ll * w).sum() / w.sum().clamp(min=1e-6)
```

## Normalisation regeneration

`gen_norm_physical.py` exists because the norm file has to match the trainer bit
for bit. It reproduces the trainer's feature frame exactly, meaning the same
column order, the same `.abs()`, the same forward fill and back fill, the same
integer local hour for `tod_sin` and `tod_cos`, and the same `+1e-6` added to the
standard deviation. Any drift here silently shifts every input the model sees.

`services/iems/training/solar_features.py` holds the geometry, with
`LAT, LON = 37.2358, -121.9624` and UTC input so no daylight saving logic is
needed. `feature_builder.py` reimplements the same two functions so inference
needs no parquet.

## Running the pipeline

From the repository root on the Mac.

```bash
# 1. labels
python3 services/iems/training/physical_labeler_v2.py

# 2. train one panel, rolling walk-forward
PANEL=3 python3 services/iems/training/train_rolling.py

# 3. export and regenerate normalisation
python3 services/iems/training/export_physical.py --panel 3
python3 services/iems/training/gen_norm_physical.py

# 4. audit before deploying
python3 services/iems/training/signature_crosscheck.py
python3 services/iems/training/eval_recent_days.py
```

To run against a different data era without forking the pipeline.

```bash
EGAUGE_PARQUET=analysis/egauge_consolidation/august_overlap.parquet \
LABELS_NAME=labels_aug_solar.parquet \
WEIGHTS_NAME=weights_aug_solar.parquet \
MODEL_SUFFIX=_aug_solar \
python3 services/iems/training/train_rolling.py
```

## Deploying a retrain to Pat's box

**Read this before shipping a model.** The obvious move, copying new files onto
`services/iems/models/` on the deployment root, does nothing. Nothing bind mounts
that directory. It is the tree images are built from, and the running models are
whatever was baked into the `iems-inference` image at build time. The 18 feature
set sitting there since 2026-08-10 is the proof of that mistake already having
been made once.

`~/rolling-deploy/deploy_rolling.sh` writes to the deployment root and backs up
to `$REPO/.deploy_backups/rolling_<stamp>/`. Four such stamps are present, the
newest `rolling_20260810_155421`. On its own it does not change what is running.

The models that are running got there a different way. They were staged in
`~microgrid/nilm_deploy/` and copied into the image when `iems-inference` was
built on 2026-08-24.

So a model deploy is three steps, not one.

```bash
# 1. put the new files where the image build will pick them up
#    (the deployment root tree, and ~microgrid/nilm_deploy if you use the staging path)

# 2. rebuild the image that actually loads them
sudo docker compose -f <compose> build iems-inference
sudo docker compose -f <compose> up -d --no-deps iems-inference

# 3. confirm, from inside the container
sudo docker exec iems-inference python3 -c "
import json, glob
for f in sorted(glob.glob('/app/services/iems/models/panel?_norm_bilstm.json')):
    d = json.load(open(f))
    print(f, len(d['features']), 'features', d['heads'])
"
```

`iems-inference` also caches one ONNX session per panel at process start, so even
a correctly rebuilt image needs the container recreated, which step 2 does.

After any model change the UNS graph should be regenerated, because
`~microgrid/build_uns_graph.py` reads the head inventory live from the engine and
the appliance layer of the graph is one node per head.

```bash
python3 ~/build_uns_graph.py
```

## Verifying a deploy took

A mismatched norm file does not raise. The model runs and every input is wrong,
so this check is the difference between a working deploy and confident nonsense.

`/iems/onnx/models` is trustworthy again as of the 2026-09-08 deploy, because
`iems-backend` was rebuilt from the same base as `iems-inference` and now reports
18 features. It stops being trustworthy the moment the two are rebuilt out of
step, since it reads its own baked copy and not the one `iems-inference` loaded.

Three checks, in order of how hard they are to fool.

```bash
# 1. what the inference container actually loaded
sudo docker exec iems-inference python3 -c "
import json, glob
for f in sorted(glob.glob('/app/services/iems/models/panel?_norm_bilstm.json')):
    d = json.load(open(f))
    print(f, len(d['features']), 'features', d['heads'], d['thresholds'])
"

# 2. that the ONNX file is the one you exported
sudo docker exec iems-inference md5sum /app/services/iems/models/nilm_panel3.onnx
md5sum services/iems/models/nilm_panel3.onnx     # on the machine you built it

# 3. what is actually being written. This one cannot lie
curl -s http://127.0.0.1:32149 \
  -H "User-Agent: AnyLog/1.23" -H "destination: network" \
  -H "command: sql customers format=json and stat=false
      \"select appliance, count(*) as n from nilm_disaggregated
        where insert_timestamp >= NOW() - 300 seconds group by appliance\""
```

Check 3 should return one row per head in the contract, 22 at present, each with
a similar count. A head missing from that list is a head the model is not
emitting, whatever the norm file claims.
