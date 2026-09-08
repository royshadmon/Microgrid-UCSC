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

## What is actually deployed

**Three different model generations exist on Pat's box and only one of them is
running.** This is the single most misleading thing about the deployment, so
check it before trusting any number.

| copy | generation | features | source | in use |
|---|---|---|---|---|
| baked into the `iems-inference` image | **14 feature, 22 heads** | 14 | `~microgrid/nilm_deploy/`, built into the image 2026-08-24 | **yes. This is what writes `nilm_disaggregated`** |
| `services/iems/models/` on the deployment root | 18 feature | 18 | `deploy_rolling.sh`, 2026-08-10 15:54 | no. Superseded and never cleaned up |
| baked into the `iems-backend` image | 12 feature, legacy heads | 12 | the image's own base layer | no, but `/iems/onnx/*` reports it |

Verified by md5. `nilm_panel3.onnx` inside `iems-inference` is
`969c8e48d00b7382832f6214553deda9`, byte identical to
`~microgrid/nilm_deploy/nilm_panel3.onnx` **and** to the repository's
`services/iems/models/nilm_panel3.onnx`. The deployment root's copy is
`0e88caa6af6abc80e3648491e1a37493`, a different file.

**No container bind mounts the model directory.** Every one of `iems-inference`,
`iems-backend`, `iems-app` reports `Binds: null`. Each carries whatever was
copied in at image build time, which is why the files on the deployment root can
sit there looking authoritative while nothing loads them.

The consequence for the repository is the opposite of what the file dates
suggest. **The repository is in sync with what is running.** Its
`panel{N}_norm_bilstm.json` files are the 14 feature set with the same
thresholds, and its ONNX files are byte identical to the ones in the container.
The 18 feature files are the odd copy out.

### Do not verify a deploy with `/iems/onnx/models`

That endpoint reads the norm files baked into `iems-backend`, not the ones
`iems-inference` is running. It currently reports 12 features, a two head Panel1
and thresholds of 0.3 and 0.35, none of which describes the models producing
data. Ask the inference container directly instead.

```bash
sudo docker exec iems-inference python3 -c "
import json, glob
for f in sorted(glob.glob('/app/services/iems/models/panel?_norm_bilstm.json')):
    d = json.load(open(f))
    print(f, len(d['features']), 'features', d['heads'], d['thresholds'])
"
```

Cross-check against what is actually being written, which is the only test that
cannot lie.

```bash
curl -s http://127.0.0.1:32149 \
  -H "User-Agent: AnyLog/1.23" -H "destination: network" \
  -H "command: sql customers format=json and stat=false
      \"select appliance, count(*) as n from nilm_disaggregated
        where insert_timestamp >= NOW() - 300 seconds group by appliance\""
```

That returns 22 appliances at the moment, which matches the 4 + 4 + 14 head
contract.

### The running generation

```
window 100, mid 50, stride 10, 14 features on all three panels
```

Feature order, with each panel's own channel first.

```
Panel1: Panel1 (HVAC), Panel2 (H2O), Panel3 (Kitchen), VrmsA, VrmsB,
        I31, I32, F1, Grid Power, Shop, I11, I21, tod_sin, tod_cos
Panel2: Panel2 (H2O), Panel1 (HVAC), Panel3 (Kitchen), ... same tail
Panel3: Panel3 (Kitchen), Panel1 (HVAC), Panel2 (H2O), ... same tail
```

Running per-head thresholds, read out of the `iems-inference` container.

| panel | thresholds |
|---|---|
| 1 | `heat_pump` 0.95, `solar_pump` 0.75, `jacuzzi_pump` 0.50, `strip_heater` 0.50 |
| 2 | `water_heater` 0.85, `hair_dryer` 0.60, `sprinklers` 0.90, `bath_lights` 0.85 |
| 3 | `dryer` 0.85, `washing_machine` 0.95, `dishwasher` 0.95, `microwave` 0.75, `pressure_pump` 0.45, `refrigerator` 0.70, `garage_fridge` 0.65, `garage_freezer` 0.60, `computers` 0.95, `tv_stereo` 0.95, `oven` 0.95, `cooktop` 0.95, `counter_appliance` 0.95, `garage_opener` 0.90 |

Two of these are never consulted. `water_heater` and `dishwasher` are COLLAPSED
heads, forced to UNKNOWN before the threshold comparison matters. Their live
state comes entirely from `rules_additive`. See `03_rules_engines.md`.

A 0.95 threshold is not a sign of a good head. It is usually the opposite, a head
whose precision only becomes tolerable at the extreme end of its probability
range.

### The eighteen feature set

The 18 feature generation adds `sun_elev`, `csky_ghi`, `pv_power` and `pv_valid`
to the fourteen. `sun_elev` and `csky_ghi` are deterministic, computed from a
NOAA approximation and the Haurwitz clear sky model, so they have full archive
coverage with no data source at all. `pv_power` comes from measured Solar
Assistant where it overlaps and `pv_valid` flags whether it is real.

It exists on the deployment root and in the repository's `.bak_18f_*` files. It
is not running. Its thresholds, for reference if it is ever brought back, are
`solar_pump` 0.95, `water_heater` 0.15, `sprinklers` 0.50, `bath_lights` 0.75,
`dryer` 0.50, `microwave` 0.30, `pressure_pump` 0.95 and `counter_appliance`
0.70, with the rest close to the fourteen feature values.

Bringing it back means rebuilding the `iems-inference` image from a tree that
contains those files, not copying them onto the deployment root, because nothing
reads the deployment root.

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

Do **not** use `/iems/onnx/models`. It reads the copy baked into `iems-backend`,
which is a stale twelve feature legacy set and has nothing to do with what
`iems-inference` loaded.

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
