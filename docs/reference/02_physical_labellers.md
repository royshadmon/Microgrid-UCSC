# Physical labellers

The labellers produce the supervision the BiLSTMs train on. There is no ground
truth at this site beyond two CT measured channels, so every other label is
derived from physics and temporal structure.

**Where this code lives.** `canonical_signatures.py` is on both machines and is
byte identical, so the bands quoted below are the ones the running system uses.
The labellers themselves are **repository only**. `temporal_rule_engine.py`,
`physical_labeler.py`, `physical_labeler_v2.py` and `dual_labeler.py` are not on
Pat's box. Models are made on the Mac and shipped to Pat's box by
`~/rolling-deploy/deploy_rolling.sh`.

Line references are against the repository and were verified 2026-09-08.

| file | lines | what it decides |
|---|---|---|
| `training/canonical_signatures.py` | 336 | the signature of every appliance, and which measure its physics is read on |
| `training/temporal_rule_engine.py` | 274 | how a panel series is decomposed, how events are extracted, how confident an event is |
| `training/physical_labeler.py` | 94 | v1. Positives from scored events, negatives from band absence |
| `training/physical_labeler_v2.py` | 202 | v2. Four sources of principled negatives, plus refrigeration exclusivity |
| `training/dual_labeler.py` | 173 | CamAL strong and weak label sets with per sample weights |

## The measure is the point

Reading a load with the wrong measure is the single largest source of bad labels.
Four decompositions exist, and every appliance is assigned exactly one.

`canonical_signatures.py:313`

```python
MEASURE = {
 # Panel1: no sustained loads hide underneath -> raw + one small step load
 "heat_pump":"raw", "solar_pump":"osc",
 # Panel2: high loads raw; the two 100-300W step loads split purely by hour
 "water_heater":"raw", "hair_dryer":"raw", "sprinklers":"osc", "bath_lights":"osc",
 # Panel3: needs all four components
 "dryer":"raw", "microwave":"raw", "vacuum_cleaner":"raw",
 "refrigerator":"osc", "washing_machine":"osc", "pressure_pump":"osc",
 "computers":"floor", "tv_stereo":"floor",
 "dishwasher":"paired",
 ...
}
```

The decompositions themselves, `temporal_rule_engine.py:45`.

```python
def series(df, panel, measure):
    s = df[col].abs()
    if measure == "osc":
        # CYCLING component: what rides on top of the always-on floor.
        s = (s - s.rolling("20min", min_periods=20).min()).clip(lower=0)
    elif measure == "floor":
        # SUSTAINED component: TV/computers RAISE the floor.
        fl = s.rolling("20min", min_periods=20).min()
        hr = fl.index.tz_convert(TZ).hour
        night = pd.Series(fl.values, index=hr).groupby(level=0).median()
        base = float(night.reindex([1,2,3,4,5]).median())
        s = (fl - base).clip(lower=0)
```

The measured effect is recorded in the file. Reading a sustained load as an
excursion gave 45 events per day, reading it off the floor gives 7. Reading a
dishwasher as an excursion gave 45 per day, reading it as a pulse pair gives 2.3.
The night baseline for `floor` is the median of hours 1 through 5, which is why
`computers` and `tv_stereo` need no explicit baseline constant.

`FLOOR_WIN` and `OSC_WIN` are both `"20min"`, set at `canonical_signatures.py:334`.

## Event extraction and gap merging

`temporal_rule_engine.py:105`. A run ends only after the signal stays out of band
longer than the per kind merge gap, which is what stops one washer load
fragmenting into forty-four events.

`canonical_signatures.py:279`

```python
KIND_GAP_S = {"impulse": 10.0, "step": 30.0, "ramp": 120.0,
              "plateau": 90.0, "cycle": 240.0}

def gap_for(sig) -> float:
    return KIND_GAP_S.get(sig.kind, 20.0)
```

Cycle loads get 240 s because the inter-phase pauses of a wash cycle, fill to
agitate to rinse to spin, and a compressor's rest period, must not split the run.

Cycle counting uses a Schmitt trigger rather than mean crossings, because the
cross verification showed the mean crossing metric was noise dominated,
`temporal_rule_engine.py:92`.

```python
def schmitt_cycles(seg):
    lo, hi = float(np.min(seg)), float(np.max(seg))
    on_t, off_t = lo + 0.66*(hi-lo), lo + 0.33*(hi-lo)
```

## Confidence scoring

`temporal_rule_engine.py:150`. Three hard rejects come before any soft scoring,
and the order matters.

```python
def score(ev, sig, comp=None):
    if sig.min_dur_hard and ev["dur_s"] < sig.min_dur_hard:
        return 0.0
    if ev.get("n", 999) < sig.min_samples:
        return 0.0
    if "cv" in ev and not (sig.cv[0] <= ev["cv"] <= sig.cv[1]):
        return 0.0
    c = _soft(ev["mean"], *sig.w)                          # band
    c *= _soft(ev["dur_s"], *sig.dur_s)                    # duration
    if sig.tod and not (sig.tod[0] <= ev["hour"] <= sig.tod[1]): c *= 0.35
```

The coefficient of variation reject is what separates the washer from the dryer
at the same power. A washer is a cycle load with high intra-run variance,
`cv=(0.25, 3.0)`. A dryer is a plateau load with a constant resistive element,
`cv=(0.0, 0.35)`. Both exceed 1 kW, so variance and duration separate them and
power never does.

The soft window is Gaussian in the distance outside the band,
`temporal_rule_engine.py:144`.

```python
def _soft(x, lo, hi):
    if lo <= x <= hi: return 1.0
    span = (hi-lo) or 1.0
    d = (lo-x)/span if x<lo else (x-hi)/span
    return float(np.exp(-4*d*d))
```

## The dishwasher pulse pair

The dishwasher is the only appliance read on `paired`. Pairing is what separates
it from the microwave, cooktop and kettle, which fire once in the same power band
and are left unpaired. `temporal_rule_engine.py:247`.

```python
def extract_paired(series, w, pulse_min_s, gap_min_s, gap_max_s,
                   env_min_s, env_max_s):
    """Patent shape: MainWash(1) -> Idle(1) -> MainWash(2) -> Idle(2)."""
    for i in range(len(pulses) - 1):
        for j in range(i + 1, len(pulses)):
            gap = (pulses[j]["start"] - a["end"]).total_seconds()
            if gap > gap_max_s * 1.5: break
            env = (pulses[j]["end"] - a["start"]).total_seconds()
            if gap_min_s <= gap <= gap_max_s and env_min_s <= env <= env_max_s:
```

Parameters, `canonical_signatures.py:332`. The same dict appears at line 294 and
is redefined at 332, so the later definition is the one in force. They are
identical, but a future edit to only one of them would be silently ignored.

```python
PAIRED = {"dishwasher": dict(w=(1200,2400), pulse_min_s=240, gap_min_s=600,
                             gap_max_s=4500, env_min_s=2400, env_max_s=12000)}
```

## v1, `physical_labeler.py`

Ninety-four lines. The whole labelling decision is `physical_labeler.py:35-58`.

```python
for a in apps:
    sig = CS.SIGNATURES[a]; meas = CS.measure_of(a)
    ser = T.series(df, sig.panel, meas).reindex(idx).ffill()
    # OFF baseline (water_heater abstains: solar preheat makes silence uninformative)
    if not sig.no_confident_off:
        L.loc[ser < sig.on_thr * 0.6, a] = 0.0
        W.loc[ser < sig.on_thr * 0.6, a] = W_RULE
    if meas == "paired":
        ev = T.extract_paired(ser.dropna(), **CS.PAIRED[a])
    else:
        ev = T.extract_events(ser.dropna(), sig.w[0], sig.w[1],
                              merge_gap_s=CS.gap_for(sig),
                              min_dur_s=max(sig.dur_s[0] * 0.5, 10))
    for e in ev:
        if sig.tod and not (sig.tod[0] <= e["hour"] <= sig.tod[1]):
            continue
        c = 0.8 if meas == "paired" else T.score(e, sig)
        if c < 0.4:
            continue
        span = (idx >= e["start"]) & (idx <= e["end"])
        L.loc[span, a] = 1.0
        W.loc[span, a] = W_RULE if sig.coupled else float(min(max(c, 0.5), 1.0))
```

Weights, `physical_labeler.py:28`.

```python
W_STRONG, W_RULE, W_ABSTAIN = None, 0.25, 0.0
```

A coupled head is capped at 0.25 no matter how confident the event scored,
because a coupled guess is a guess. Non-coupled positives carry their own
confidence clamped to `[0.5, 1.0]`.

The heat pump and solar pump mutex was removed on 2026-08-05. The spec called it
a physical interlock, the site confirmed there is none, and forcing exclusivity
produced labels with zero co-occurrence so the model could never learn the
concurrent state. A 110 W circulation pump and a 4.5 kW compressor can and do run
together on Panel1. The signature still carries `mutex=()` at
`canonical_signatures.py:65` with the removal dated in a comment.

## v2, `physical_labeler_v2.py`

v1 left the label supply lopsided. The census over 705,296 rows is recorded in
the file header.

```
water_heater  4,360 pos /      0 neg   (no_confident_off -> unscoreable)
dishwasher   19,096 pos /      0 neg   (on_thr*0.6 = 30W never true on P3)
microwave    14,192 pos / 11,843 neg   (96% of timeline unlabelled)
```

v2 keeps every v1 positive untouched and only fills NaNs,
`physical_labeler_v2.py:137`.

```python
def fill(L, W, mask, app, val, wgt):
    """Fill only NaN label cells; never overwrite a v1 decision."""
    tgt = mask & L[app].isna()
```

### Negative source 1, physics OFF for the water heater

`physical_labeler_v2.py:50`

```python
WH_OFF_W   = 1600.0   # Panel2 total below this -> 2000W+ element is OFF
```

`no_confident_off` was about hot water demand being unknowable, not element
state. The element draws 2000 to 4300 W, so when the whole of Panel2 is under
1600 W the element cannot be on whatever the solar preheat is doing.

### Negative source 2, physics OFF for the dishwasher

`physical_labeler_v2.py:51`

```python
DW_OFF_W   = 400.0    # Panel3 raw below this with flat osc -> dishwasher OFF
```

Any active phase, motor above 200 W or heater above 1200 W, must lift the panel's
oscillation component, so the rule requires both a low raw draw and a flat
oscillation.

### Negative source 3, quiet-house negatives

`physical_labeler_v2.py:52` and `57`

```python
QUIET_WIN  = "30min"
QUIET_PCT  = 15       # rolling-envelope percentile that defines "quiet"
OCCUPANT_APPS = ("toaster", "coffee_maker", "microwave", "hair_dryer", ...)
```

The rolling 30 minute maximum of the three panel totals, below its own 15th
percentile, is treated as an empty house, and every occupant driven appliance
gets a negative at weight 0.85. This is vacancy mining with the data available,
since there is no Home Assistant occupancy feed in the archive.

### Negative source 4, the solar gate

`physical_labeler_v2.py:54`

```python
NIGHT_ELEV = -2.0     # sun below this -> solar_pump OFF
```

Same physics as `rules_additive._low_solar`, applied to training labels. Sun
elevation is deterministic, so this is exact for every timestamp in the archive
with no data source at all.

### Refrigeration exclusivity

`physical_labeler_v2.py:81` and `90`. Three cold appliances share Panel3's
oscillation component and one power band. Running the ordinary extractor once per
head labelled the same compressor cycles three times, measured at
215,797 / 220,179 / 218,852 positives. The fix is not a better band, it is
exclusivity.

```python
REFRIG = ("refrigerator", "garage_fridge", "garage_freezer")

def split_refrigeration(df, idx, L, W):
    ser = T.series(df, "Panel3 (Kitchen)", "osc").reindex(idx).ffill()
    lo = min(CS.SIGNATURES[a].w[0] for a in REFRIG)
    hi = max(CS.SIGNATURES[a].w[1] for a in REFRIG)
    ev = T.extract_events(ser.dropna(), lo, hi, merge_gap_s=120, min_dur_s=120)
    for k, e in enumerate(ev):
        on = float(e["dur_s"])
        period = (ev[k + 1]["start"] - e["start"]).total_seconds()
        duty = min(max(on / period, 0.0), 1.0)
        for a in REFRIG:
            sig = CS.SIGNATURES[a]
            s_ = (_soft_window(period, *sig.period_s)
                  * _soft_window(duty, *sig.duty)
                  * _soft_window(float(e["mean"]), *sig.w))
        L.loc[span, best] = 1.0
        W.loc[span, best] = float(min(max(best_s, 0.3), 0.6))
```

Losers get NaN, not zero. Another unit's cycle is no evidence that this one is
off. The one exception is that the whole band being quiet is evidence that all
three are off, and that fills at weight 0.5.

The honest limit is written into the file. Attribution is driven by duty and
period priors from the panel directory, not by measurement. At 1 to 6 s real
power on a single panel CT there is no feature that proves which box a given
compressor cycle belongs to. The aggregate of the three is the trustworthy
quantity, and per unit splits are estimates until a plug meter says otherwise.
This is why the weight is capped at 0.6.

`canonical_signatures.py:257` carries a comment saying `garage_fridge` and
`garage_freezer` were removed as heads on 2026-08-07, but both are still present
in the `PANEL_HEADS[3]` tuple at line 264 and both are still served. The comment
is stale relative to the code.

## Dual labelling, `dual_labeler.py`

CamAL taxonomy, after Petralia et al. ICDE 2025. Strong labels are per timestamp
and are fabricated for coupled loads, which makes them circular. Weak labels are
one per four hour window and stay reliable for coupled loads, because knowing a
dryer cycle happened in an afternoon does not require pinning the minute or
separating a simultaneous microwave.

`dual_labeler.py:35`

```python
WEAK_WINDOW   = "4h"
STRONG_CONF   = 0.50   # min event conf to emit a STRONG positive
WEAK_CONF     = 0.30   # min event conf to emit a WEAK positive
W_MEASURED    = 1.00
W_RULE_ONLY   = 0.25   # rule/coupled guess: present but distrusted
W_ABSTAIN     = 0.00

MEASURED = {"heat_pump": "bal240_p1", "water_heater": "bal240_p2"}
```

`MEASURED` is the only real ground truth in the system. Where a CT channel exists
it overrides everything.

```python
for a, bal in MEASURED.items():
    m = df[bal].abs()
    on = m > 300.0
    S[a] = np.where(m.notna(), on.astype("float32"), np.nan)
    SW[a] = np.where(m.notna(), W_MEASURED, W_ABSTAIN)
```

Coupled events are marked ON but distrusted rather than dropped.

```python
if e["coupled"]:
    S.loc[span, a] = 1.0
    SW.loc[span, a] = W_RULE_ONLY
elif e["conf"] >= STRONG_CONF:
    S.loc[span, a] = 1.0
    SW.loc[span, a] = float(e["conf"])
```

Outputs are `labels_strong_all.parquet`, `weights_strong_all.parquet`,
`labels_weak_all.parquet`, `weights_weak_all.parquet` and
`dual_label_summary.csv` under `services/iems/training/data`.

## The simplest labeller, `make_labels.py`

Eighty-two lines, on both machines. Kept for comparison. Fixed power thresholds
after Xue et al. 2025 section 4.1, with a hierarchical assignment on Panel3 so
the same watt is not counted as both microwave and cooktop.

```python
labels["cooktop"]    = (series > 800).astype(int)
labels["microwave"]  = ((series > 200) & (series <= 800)).astype(int)
labels["dishwasher"] = ((series > 400) & (series <= 1800)
                        & (labels["cooktop"] == 0) & (labels["microwave"] == 0)).astype(int)
labels["fridge"]     = ((series > 50) & (series <= 200)).astype(int)
```

## Environment overrides

Every labeller and trainer reads the same four variables so the pipeline can run
against the full March to July archive or the August solar overlap window without
a forked copy. Defaults reproduce the original behaviour exactly.

```
EGAUGE_PARQUET   default analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet
SOLAR_PARQUET    default analysis/solar/solar_history.parquet
LABELS_NAME      default labels_physical.parquet   (v2 default labels_physical_v2.parquet)
WEIGHTS_NAME     default weights_physical.parquet  (v2 default weights_physical_v2.parquet)
MODEL_SUFFIX     default ""
```

## Running them

From the repository root on the Mac, because every path in these files is repo
relative and none of them exist on Pat's box.

```bash
python3 services/iems/training/physical_labeler.py      # v1  -> data/labels_physical.parquet
python3 services/iems/training/physical_labeler_v2.py   # v2  -> data/labels_physical_v2.parquet
python3 services/iems/training/dual_labeler.py          # strong + weak
python3 services/iems/training/signature_crosscheck.py  # audit bands against measured events
```

`signature_crosscheck.py` is the one to run after touching any band. It extracts
events with a relaxed band of `0.6*lo` to `1.6*hi` so a wrong spec band cannot
hide the true population, which is how the heat pump error was found, and it
compares against `rules_additive.APPLIANCE_SIGNATURE` because any band
disagreement means the runtime power gate can veto predictions the labeller
considered valid.
