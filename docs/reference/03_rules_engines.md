# Rules engines

Four rules engines exist and they run at different points. Mixing them up is the
fastest way to misread a prediction.

Every file in this document is present on Pat's box and every constant quoted
here was read off that machine on 2026-09-08. Line numbers are the host's.

| engine | file | lines | when it runs | what it emits |
|---|---|---|---|---|
| canonical signature table | `training/canonical_signatures.py` | 336 | offline, read by everything | the bands, thresholds and temporal envelopes |
| threshold rules engine | `training/rule_engine.py` | 468 | offline labelling and the realtime monitor | `{1, 0, NaN}` per appliance per sample |
| probability gates | `training/postprocess.py` | 77 | **runtime**, after the ONNX forward pass | `ON`, `OFF`, `MAYBE`, `UNKNOWN` |
| additive reconciliation | `inference/rules_additive.py` | 348 | **runtime**, after the gates | final state, watts and the rule that decided it |

`postprocess.py` lives in the training folder but is imported by
`onnx_disaggregator.py` at runtime. That is deliberate and easy to miss.

---

## 1. The canonical signature table

Bands and on-thresholds are verbatim from `appliance_data_updated.txt`. The
temporal layer, meaning kind, duration, time of day and cycle structure, was
calibrated on the 11.4 M row consolidated series plus public reference data.

Five signature kinds.

```
impulse  short sharp burst <10min, sharp rising edge   -> microwave, vacuum
cycle    REPEATING multi-phase / duty-cycled structure -> washing_machine,
         dishwasher, refrigerator
plateau  CONSTANT sustained draw, near-flat            -> dryer, computers,
         tv_stereo, bath_lights
step     small level shift held for a scheduled block  -> sprinklers,
         solar_pump, pressure_pump
ramp     high sustained w/ thermostat modulation       -> heat_pump, water_heater
```

The `Sig` dataclass carries `w` band, `on_thr`, `dur_s`, `kind`, `tod`, `edge`,
`cyc_rate`, `cv`, `period_s`, `duty`, `min_samples`, `min_dur_hard`,
`no_confident_off`, `coupled`, `mutex` and a `note` recording why each value is
what it is.

### Panel 1, lines 57 to 90

| head | measure | band W | on_thr | dur_s | kind | notes |
|---|---|---|---|---|---|---|
| `heat_pump` | raw | 2500 to 5700 | 1200 | 60 to 10800 | ramp | `cv=(0.0,0.6)`. Measured, not spec. The spec said 1500 to 4000 with a question mark, and that band holds 0.39 percent of Panel1 samples against 4.78 percent for the measured band. Observed max 5691 W |
| `solar_pump` | osc | 100 to 250 | 50 | 300 to 10800 | step | `tod=(7,19)`, `mutex=()` with the interlock removal dated 2026-08-05 |
| `jacuzzi_pump` | osc | 800 to 2000 | 400 | 600 to 14400 | plateau | `cv=(0.0,0.5)`. Separated from the compressor by power and by not cycling on a thermostat rhythm |
| `strip_heater` | raw | 6000 to 12000 | 5800 | 120 to 7200 | plateau | `cv=(0.0,0.35)`, `min_samples=10`. Never fired in sample. The head exists so winter data can train it without an architecture change |

`strip_heater_1` and `strip_heater_2` were merged into one head on 2026-08-10
because the two definitions were byte identical, so two heads could never
disagree. They were one signature trained twice.

### Panel 2, lines 93 to 107

| head | measure | band W | on_thr | dur_s | kind | notes |
|---|---|---|---|---|---|---|
| `water_heater` | raw | 2000 to 4300 | 500 | 30 to 7200 | ramp | `no_confident_off=True`. Measured p50 is only 107 W, the element fires rarely, so silence is not evidence of OFF. Ceiling widened from 4000 because the CT element p95 is 4011 W |
| `hair_dryer` | raw | 1200 to 1800 | 800 | 30 to 900 | impulse | `tod=(5,23)`, `edge=500`. Measured 1559 W over 4.3 min |
| `sprinklers` | osc | 100 to 300 | 50 | 60 to 5400 | step | `tod=(3,11)`. Same band as `bath_lights`, separated by time of day |
| `bath_lights` | osc | 100 to 300 | 80 | 60 to 3600 | plateau | `tod=(16,24)`, `cv=(0.0,0.25)`. The only incandescent load, so perfectly flat |

### Panel 3, lines 110 to 239

| head | measure | band W | on_thr | dur_s | kind | discriminator |
|---|---|---|---|---|---|---|
| `dryer` | raw | 4000 to 7000 | 1000 | 300 to 5400 | plateau | `tod=(7,23)`, `cv<=0.35`, `min_dur_hard=360`, `min_samples=36`. The hard ten minute gate exists because the raw band was 97 percent short oven and cooktop bursts |
| `washing_machine` | osc | 200 to 2000 | 50 | 1800 to 7200 | cycle | `tod=(6,23)`, `cv=(0.25,3.0)` separates it from the flat dryer. Minimum duration raised from 300 to 1800 s after Kelly and Knottenbelt 2015. At 300 s the head claimed 111 minutes of washing a day |
| `dishwasher` | paired | 200 to 1800 | 50 | 1800 to 9000 | cycle | `tod=(6,24)`, `cv=(0.2,3.0)`. Pulse pairing separates it from the single burst microwave and cooktop, so it is no longer coupled |
| `microwave` | raw | 900 to 1500 | 200 | 10 to 900 | impulse | `tod=(5,24)`, `edge=500`, `coupled=True`. Degenerate with cooktop and the dishwasher heater |
| `pressure_pump` | osc | 500 to 1000 | 200 | 20 to 1200 | step | demand driven, any hour. Critical load |
| `refrigerator` | osc | 80 to 200 | 50 | 300 to 3600 | cycle | `period_s=(1200,3600)`, `duty=(0.25,0.50)`, `min_samples=20`. Kitchen unit, conditioned space, the lowest duty of the three |
| `garage_fridge` | osc | 80 to 220 | 50 | 300 to 3600 | cycle | `period_s=(900,3000)`, `duty=(0.55,0.90)`, `coupled=True`. Unconditioned space, duty is the only discriminator |
| `garage_freezer` | osc | 80 to 250 | 50 | 600 to 5400 | cycle | `period_s=(2400,9000)`, `duty=(0.20,0.55)`, `coupled=True`. Deeper setpoint and more thermal mass |
| `computers` | floor | 200 to 500 | 100 | 600 to 43200 | plateau | `tod=(6,24)`, `cv=(0.05,1.2)`. CPU load fluctuation separates it from the TV's flat draw |
| `tv_stereo` | floor | 100 to 200 | 80 | 600 to 25200 | plateau | `tod=(16,24)`, `cv=(0.0,0.15)`. Overlaps the refrigerator band exactly, separated by shape and time, never power |
| `oven` | raw | 2000 to 4000 | 1200 | 600 to 14400 | ramp | `tod=(6,22)`, `cv=(0.1,0.9)`, `cyc_rate<=8`. Thermostatic, long envelope separates it from the cooktop |
| `cooktop` | raw | 1500 to 5000 | 1200 | 120 to 5400 | ramp | `tod=(6,22)`, `cv=(0.2,1.2)`, `cyc_rate<=20`. Burner control cycles far faster than the oven |
| `counter_appliance` | raw | 800 to 1500 | 600 | 45 to 3600 | impulse | `tod=(5,23)`, `cv=(0.0,1.4)`, `min_dur_hard=45`. Unified toaster, coffee maker and clothes iron |
| `garage_opener` | raw | 300 to 800 | 250 | 3 to 25 | impulse | `min_dur_hard=2`, `min_samples=2`. Critical load, never shed |
| `vacuum_cleaner` | raw | 800 to 1200 | 600 | 60 to 3600 | impulse | `tod=(7,21)`, `edge=400`, `coupled=True`. Mobile load, not in the Panel3 head contract |

`counter_appliance` was unified on 2026-08-10. The three loads shared one power
band, 16.4 percent of all Panel3 ON steps land in 800 to 1500 W, and were split
only by duration and hour heuristics no measurement confirmed. The energy cross
check showed why that failed. `clothes_iron` alone claimed 47 minutes of ironing
every day, an implied 396 kWh a year. NEEA's RBSA metering contractor
deliberately excluded toasters, irons and hair dryers from instrumentation as too
small and intermittent to justify a meter. One honest head beats three confident
guesses.

### The head contracts

`canonical_signatures.py:254`. This is what the export reads, so ONNX output
order cannot drift from the names the inference loop expects.

```python
PANEL_HEADS = {
    1: ("heat_pump", "solar_pump", "jacuzzi_pump", "strip_heater"),
    2: ("water_heater", "hair_dryer", "sprinklers", "bath_lights"),
    3: ("dryer", "washing_machine", "dishwasher", "microwave",
        "pressure_pump", "refrigerator", "garage_fridge", "garage_freezer",
        "computers", "tv_stereo", "oven", "cooktop", "counter_appliance",
        "garage_opener"),
}
```

The comment above `PANEL_HEADS[3]` says `garage_fridge` and `garage_freezer` were
removed as heads on 2026-08-07. They were not. Both are in the tuple and both are
served by the deployed Panel3 model. Treat the comment as a record of an intent
that was reverted.

`canonical_signatures.py:249`

```python
BACKGROUND = ("toaster_oven", "disposal", "networking", "general_lighting")
CRITICAL = ("refrigerator", "garage_fridge", "garage_freezer", "garage_opener",
            "pressure_pump")
BATTERY_WINDOW = (16, 21)   # spec: battery charged daily 16:00-21:00 local
```

---

## 2. The threshold rules engine

`training/rule_engine.py`, 468 lines. Pure pandas, no model files, no LLM. One
function per panel, each returning label columns in `{1, 0, NaN}`, where NaN
means ambiguous and is dropped in training rather than forced to zero.

Diurnal rules use `America/Los_Angeles`. Every rule runs on `abs(w)` because raw
eGauge panel power is negative by convention.

### Panel 1

Constants at lines 35 to 44.

```python
HP_ON_THRESHOLD = 300 ; HP_MIN_SPEC = 1500 ; HP_MAX_SPEC = 4000
SP_ON_THRESHOLD = 50  ; SP_STEP_ON = 40 ; SP_STEP_OFF = 10 ; SP_STEP_MAX = 300
SP_RANGE_LO = 100     ; SP_RANGE_HI = 250
```

```python
p1_60s = p1.rolling("60s", min_periods=3).mean()
step   = (p1 - p1.rolling("30min", min_periods=30).min()).clip(lower=0)
weather_demand = (temp < 60) | (temp > 75)

hp_on  = (p1_60s > HP_MIN_SPEC) & weather_demand & p1.notna()
hp_off = (p1 < (HP_ON_THRESHOLD - 100)) & p1.notna()
rule_hp[(rule_hp == 1) & ((p1 < 0.5*HP_MIN_SPEC) | (p1 > 1.5*HP_MAX_SPEC))] = np.nan

sp_on = ((step > SP_STEP_ON) & (step < SP_STEP_MAX)
         & (irr > 200) & (rule_hp != 1) & p1.notna() & step.notna())
sp_off = (p1.notna() & step.notna()
          & ((irr < 50) | (step < SP_STEP_OFF) | (p1 < SP_ON_THRESHOLD)
             | (step > SP_STEP_MAX) | (rule_hp == 1)))
```

The heat pump rule is weather conditioned. It only fires outside 60 to 75 F,
because a compressor drawing 1.5 kW in mild weather is more likely something
else. Note that this engine still carries the **spec** band 1500 to 4000, while
`canonical_signatures.py` and `rules_additive.py` both carry the **measured** band
2500 to 5700. The two disagree deliberately, and the runtime uses the measured
one.

The `rule_hp != 1` term in `sp_on` is a soft precedence, not the removed mutex.

### Panel 2

Constants at lines 60 to 69. The panel2 baseline sits at 150 to 250 W on this
house, so raw power rules would tag the baseline as sprinklers or bath lights.
Small signals switch to a baseline step formulation.

```python
WH_MIN = 2000 ; WH_MAX = 4000 ; WH_OFF = 500
WH_SOLAR_PREHEAT_TEMP_F = 65 ; WH_SOLAR_DAMPED_W = 1500
HD_MIN = 1200 ; HD_MAX = 1800 ; HD_OFF = 800
SPR_STEP_MIN = 50  ; SPR_STEP_MAX = 300
SPR_AM_HOURS = (4, 7) ; SPR_PM_HOURS = (17, 21)
BL_STEP_MIN = 80 ; BL_STEP_MAX = 300
BL_EVENING_START_HOUR = 18 ; BL_EVENING_END_HOUR = 1
```

```python
p2_60s  = p2.rolling("60s", min_periods=3).mean()
p2_step = (p2 - p2.rolling("30min", min_periods=30).min()).clip(lower=0)

rule_wh[(p2_60s > WH_MIN) & (p2_60s < WH_MAX) & p2.notna()] = 1
rule_wh[(p2 < WH_OFF) & p2.notna()] = 0
irr_6h = irr.rolling("6h", min_periods=60).mean()
solar_preheat = (irr_6h > WH_SOLAR_PREHEAT_IRR_6H) & (temp > WH_SOLAR_PREHEAT_TEMP_F)
rule_wh[solar_preheat & (p2_60s < WH_SOLAR_DAMPED_W) & p2.notna()] = 0

rule_hd[(p2_60s > HD_MIN) & (p2_60s < HD_MAX) & (rule_wh != 1) & p2.notna()] = 1

am_pm = ((hour >= 4) & (hour <= 7)) | ((hour >= 17) & (hour <= 21))
rule_spr[(p2_step > 50) & (p2_step < 300) & am_pm
         & (rule_wh != 1) & (rule_hd != 1)] = 1
rule_spr[(~am_pm) & p2.notna()] = 0

evening = (hour >= 18) | (hour <= 1)
rule_bl[(p2_step > 80) & (p2_step < 300) & evening
        & (rule_wh != 1) & (rule_hd != 1) & (rule_spr != 1)] = 1
rule_bl[(~evening) & p2.notna()] = 0
```

On a bright warm day the boiler has already heated the tank, so a Panel2 draw
under 1500 W is not the electric element.

### Panel 3

Order matters. The biggest signals are decided first so smaller heads can be
conditioned on the absence of bigger appliances.

```
1. dryer      4000..7200, off below 2000
2. microwave  RISING EDGE: p3_delta > 600 and 900 < p3_60s < 1600, not dryer
3. dishwasher 700..1900, not dryer, not microwave
4. washer     step 200..2000, not dryer/microwave/dishwasher
5. pump       step 400..1000, not dryer/microwave/dishwasher/washer
6. fridge     see below
7. computers  step 100..500, hours 7..22, not any of the above
8. tv_stereo  step 80..200, hours 17..1, not any of the above
```

The microwave is the only rising edge rule, because bursts are shorter than five
minutes and window midpoint labels lose them otherwise.

The refrigerator rule was rewritten because the pre-existing baseline band rule
produced F1 exactly 1.000, which was degenerate rather than predictive. The
panel3 quiescent draw is always in the fridge range, so a head that always says
ON scores perfectly while carrying no information.

```python
p3_fridge_baseline = p3.rolling("4h", min_periods=60).quantile(0.1)
p3_cycle_activity  = p3.rolling("30min", min_periods=30).std()
fridge_band = ((p3_fridge_baseline > 80) & (p3_fridge_baseline < 200))
cycling     = p3_cycle_activity > 15.0
rule_fridge[fridge_band &  cycling & p3.notna()] = 1
rule_fridge[fridge_band & ~cycling & p3.notna() & p3_cycle_activity.notna()] = 0
rule_fridge[(p3_fridge_baseline < 40) & p3.notna()] = 0
```

ON now requires both a quiescent baseline in the fridge band and recent cycling
activity, which distinguishes a fridge cycling from a fridge present with the
compressor off.

The sequential constraint from the Panel 3 specification section 3.2.

```python
washer_recent = (rule_wm.fillna(0) > 0).rolling("90min", min_periods=1).max()
suspect_dryer = (rule_dryer == 1) & (washer_recent.fillna(0) < 1)
rule_dryer[suspect_dryer] = np.nan
```

A dryer run with no washer run in the previous ninety minutes is suspect. It is
dropped to NaN rather than forced OFF, because the evidence is weak in both
directions.

### The cross-panel vacuum rule

The vacuum is mobile and changes panels, so it cannot be a per panel head. It
runs last, after every per panel label exists, because it needs them to mask out
panels where another appliance already owns the spike. `vacuum_detector.py` gives
the band 600 to 1200 W, a 60 s minimum persistence and a 30 minute session
accumulation window.

### Repository-only extensions

`timer_differentiator.py` and `camal_pipeline.py` are **not on Pat's box**. The
first adds a second split by dwell time and thermostatic cycle rate, because the
16:00 to 19:00 dinner cluster mixes oven and cooktop into the dryer estimate.
Cooktop is short, under ten minutes, high peak above 2000 W, few toggles. Dryer
is long, at least twenty minutes, steady near 5 kW, close to zero toggles. Oven
is long-ish, moderate mean of 1.2 to 3.2 kW, and many toggles from element
cycling. The second is a detect-then-localise gate. If the per window ResNet
ensemble says the appliance did not run in this block, the rule engine may not
emit ON labels there.

---

## 3. Runtime probability gates

`training/postprocess.py`, 77 lines, imported by `onnx_disaggregator.py`. It turns
`{head: (prob, threshold)}` into `{head: (state, conf, flag)}` where state is one
of `ON`, `OFF`, `MAYBE` or `UNKNOWN`. The thresholds come from the deployed norm
files, not from this file.

```python
DEMOTED   = {"solar_pump", "pressure_pump"}
COLLAPSED = {"water_heater", "dishwasher"}
TOD_EXCLUSIVE = {
    "sprinklers":  (3, 11),    # AM irrigation only
    "bath_lights": (16, 24),   # evening only
}
```

Gate order, lines 42 to 77, verbatim.

```python
for h, (prob, thr) in states.items():
    on = prob >= thr
    flag = "ok"

    if h in TOD_EXCLUSIVE:
        lo, hi = TOD_EXCLUSIVE[h]
        if not (lo <= hour <= hi):
            on = False; flag = "tod_gated"

    if h == "solar_pump":
        if not (7 <= hour <= 19):
            on = False; flag = "night_gated"
        # MUTEX REMOVED 2026-08-05

    if h in COLLAPSED:
        out[h] = ("UNKNOWN", min(float(prob), 0.49), "collapsed_head")
        continue

    if h in DEMOTED and on:
        flag = "demoted_low_precision"
        conf = min(float(prob), 0.49)
        out[h] = ("MAYBE", conf, flag); continue

    out[h] = ("ON" if on else "OFF", float(prob), flag)
```

`COLLAPSED` was set after the 2026-08-07 retrain, where both `water_heater` and
`dishwasher` scored F1 1.000 on test slices that were 100 percent positive. With
no negatives in the slice a head that always says ON scores perfectly while
carrying no information, so both were routed to UNKNOWN rather than rendered as
permanently RUNNING.

Two consequences follow. First, the deployed `water_heater` threshold of 0.15 and
`dishwasher` threshold of 0.80 are **never consulted**, because both heads are
collapsed before the comparison happens, and their live state comes entirely from
`rules_additive`. Second, the negatives `physical_labeler_v2.py` was written to
supply now exist, and in the run that produced the deployed models both heads are
measured against them, `water_heater` at F1 0.984 and `dishwasher` at F1 0.767 at
fold 4. `COLLAPSED` has not been revisited since. See
`04_training_pipeline.md`.

`DEMOTED` holds heads whose standalone precision stays low after gating. On the
deployed models at fold 4, `solar_pump` measures P 0.066, R 0.801, F1 0.121 and
`pressure_pump` measures P 0.195, R 0.904, F1 0.321. Demoted heads render as
"possible" in the UI and the decision support layer must not shed on them.
`solar_pump` is instead driven by `solar_recovery` and `solar_gate:low_solar`
against measured Panel1 watts, which is why it appears ON in live output at a
confidence well below its 0.95 threshold.

---

## 4. Runtime additive reconciliation

`inference/rules_additive.py`, 348 lines. This is the last thing that touches a
prediction before it is written. It is also read live by the Ask endpoint, so its
constants cannot drift from what the model is told.

Call order in `apply_rules`, line 314.

```python
def apply_rules(preds, panel_power_w, ts_local=None, additive=True,
                weather=None, panel=None, solar=None):
    for p in preds.values():
        p.setdefault("rule", "model")
    if panel and "Panel1" in panel:
        preds = apply_panel1_rules(preds, panel_power_w, weather, ts_local, solar)
    preds = apply_mutual_exclusion(preds)
    if _battery_charging(solar, ts_local):
        for p in preds.values():
            p["battery_charging"] = True
    if solar and solar.get("load_power") is not None:
        for p in preds.values():
            p.setdefault("house_load_w", float(solar.get("load_power") or 0.0))
    preds = apply_power_gate(preds, panel_power_w)
    if panel and "Panel2" in panel:
        preds = apply_panel2_rules(preds, panel_power_w, weather)
    if additive:
        preds = additive_disambiguation(preds, panel_power_w)
    return preds
```

### The runtime signature table

Line 65, as `(on_threshold_w, lo_w, hi_w)`. These must stay consistent with
`canonical_signatures.py` or the power gate will veto predictions the labeller
considered valid.

```python
"heat_pump_fan":    (300,  450,  650)    "solar_pump":       (25,   100,  250)
"water_heater":     (500, 2000, 4300)    "hair_dryer":       (800, 1200, 1800)
"sprinklers":       (50,   100,  300)    "bath_lights":      (80,   100,  300)
"refrigerator":     (50,    80,  200)    "garage_fridge":    (50,    80,  220)
"garage_freezer":   (50,    80,  250)    "dishwasher":       (50,   200, 1800)
"microwave":        (200,  900, 1500)    "dryer":            (1000, 4000, 7000)
"washing_machine":  (50,   200, 2000)    "pressure_pump":    (200,  500, 1000)
"computers":        (100,  200,  500)    "tv_stereo":        (80,   100,  200)
"vacuum_cleaner":   (600,  800, 1200)    "garage_opener":    (250,  300,  800)
"heat_pump":        (1200, 2500, 5700)   "jacuzzi_pump":     (400,   800, 2000)
"strip_heater":     (5800, 7000, 12000)  "oven":             (1200, 2000, 4000)
"cooktop":          (1200, 1500, 5000)   "counter_appliance":(600,   800, 1500)
```

`solar_pump`'s floor was lowered from 50 to 25 W to admit low draw on-states.
`heat_pump_fan` is a sub-state of the compressor, not a separate appliance, and
exists so the Panel1 residual recovery can distinguish a fan-only run.

### Weather and solar gating constants

Lines 36 to 62.

```python
BATTERY_WINDOW = (16, 21)
MUTEX_GROUPS = ()          # emptied 2026-08-05
PROTECT_CONF = 0.50
SOLAR_MIN_IRRADIANCE = 150.0   # W/m^2 6h avg
SOLAR_MAX_CLOUD_PCT  = 80.0
SOLAR_DAYLIGHT_HOURS = (6, 20)
PV_MIN_W             = 200.0   # measured PV below this -> no useful solar resource
BATTERY_CHARGE_MIN_W = 50.0
PROTECTED_RULES = {"heat_pump_recovery", "water_heater_solar_fallback",
                   "additive_recovery", "solar_recovery"}
```

Measurement beats proxy wherever a measurement exists.

```python
def _low_solar(weather, ts_local, solar=None):
    if solar and solar.get("pv_power") is not None:
        return float(solar.get("pv_power", 0.0) or 0.0) < PV_MIN_W
    irr = float(w.get("irradiance_6h_avg", w.get("irradiance_now", 0.0)) or 0.0)
    # NB: explicit None-check, not `or 100.0` -- a real 0% cloud cover is falsy
    _cc = w.get("cloud_cover_pct")
    cloud = float(_cc) if _cc is not None else 100.0
    daylight = SOLAR_DAYLIGHT_HOURS[0] <= hour < SOLAR_DAYLIGHT_HOURS[1]
    return (irr < SOLAR_MIN_IRRADIANCE) or (cloud > SOLAR_MAX_CLOUD_PCT) or (not daylight)

def _battery_charging(solar, ts_local):
    if solar and solar.get("battery_power") is not None:
        return float(solar.get("battery_power", 0.0) or 0.0) >= BATTERY_CHARGE_MIN_W
    return ts_local is not None and BATTERY_WINDOW[0] <= ts_local.hour < BATTERY_WINDOW[1]
```

The cloud cover comment marks a real bug that was fixed. A genuine zero percent
cloud cover, meaning clear sky, is falsy, and `or 100.0` would have read it as
full overcast and gated the pump off on the sunniest possible day.

### Rule A, Panel 1 weather reconciliation

```python
low_solar = _low_solar(weather, ts_local, solar)

if low_solar and sp["state"] == 1:
    sp["state"] = 0; sp["power_w"] = 0.0; sp["rule"] = "solar_gate:low_solar"
elif (not low_solar) and sp["state"] == 0:
    hp_on = preds.get("heat_pump", {}).get("state", 0) == 1
    if (not hp_on) and s_thr <= panel_power_w <= s_hi + 100:
        sp["state"] = 1
        sp["power_w"] = float(min(max(panel_power_w, s_lo), s_hi))
        sp["rule"] = "solar_recovery"

if hp is not None and hp["state"] == 0:
    residual = panel_power_w - (solar_hi if solar_on else 0.0)
    if residual >= fan_lo:                       # fan_lo = 450
        hp["state"] = 1
        hp["power_w"] = float(min(max(residual, fan_lo), hp_hi))
        hp["rule"] = "heat_pump_recovery"
```

The heat pump is recovered from measured watts rather than trusted to the model,
because Panel1 carries only two loads and the residual after subtracting a
possible 250 W pump is the compressor, including its roughly 550 W fan only sub
state. Panel1 runs before the mutex call so a weather gated pump cannot win an
interlock, and it stashes its verdict for Panel2 in a module level context at
line 98.

```python
_SOLAR_CONTEXT = {"solar_pump_on": False, "solar_pump_conf": 0.0,
                  "low_solar": True, "ts": None}
```

Panels are processed in order Panel1, Panel2, Panel3 within one tick, which is
what makes that cross panel channel safe.

### Rule B, mutual exclusion

`MUTEX_GROUPS` is empty, so this is currently a no-op. It is kept because the
removal was a site fact, not a design change, and a genuinely exclusive pair may
appear later.

### Rule C, the power gate

```python
def apply_power_gate(preds, panel_power_w, margin_w=120.0):
    for a, p in preds.items():
        if p["state"] != 1: continue
        sig = APPLIANCE_SIGNATURE.get(a)
        if panel_power_w + margin_w < sig[0]:
            p["state"] = 0; p["power_w"] = 0.0; p["rule"] = "power_gate_off"
```

An appliance whose own minimum on-threshold exceeds the entire measured panel
draw plus 120 W is impossible. The gate removes those after the model, which is
what allows low thresholds to be used without the false positives they would
otherwise admit. The deployed `water_heater` threshold is 0.15 and that head
measures P 1.000, R 0.969, F1 0.984 at fold 4. Per head figures are in
`04_training_pipeline.md`.

### Rule D, Panel 2 water heater

```python
# Power gate: Panel2 above 2.5 kW almost always means water heater.
if panel_power_w > 2500:
    wh["state"] = 1
    wh["power_w"] = float(min(max(panel_power_w, wh_lo), wh_hi))
    wh["rule"] = "water_heater_power_gate"
    return preds

# Solar-thermal fallback
ctx = _SOLAR_CONTEXT
solar_off_confident = (not ctx.get("solar_pump_on", False)) and ctx.get("low_solar", True)
if wh["state"] == 0 and solar_off_confident and panel_power_w >= wh_lo:
    wh["state"] = 1
    wh["power_w"] = float(min(max(panel_power_w, wh_lo), wh_hi))
    wh["rule"] = "water_heater_solar_fallback"
```

`water_heater` is a COLLAPSED head, so it never asserts a state of its own and
power is used instead of model confidence. The fallback encodes the site's
actual plumbing. When there is no solar resource the solar thermal loop is not
heating the tank, so the electric element is the hot water fallback.

Note that the head does have measured performance in the run that produced the
deployed models, P 1.000, R 0.969, F1 0.984 at fold 4, so its presence in
`COLLAPSED` predates those numbers. See the open item in
`04_training_pipeline.md`.

### Rule E, additive recovery

```python
residual = panel_power_w - explained_hi()
while residual > on_tol_w:                       # on_tol_w = 400.0
    for a, p in preds.items():
        if p["state"] == 1 or a not in APPLIANCE_SIGNATURE: continue
        thr, lo, hi = APPLIANCE_SIGNATURE[a]
        if residual >= thr and residual <= hi + on_tol_w:
            center = (lo + hi) / 2.0
            fit = abs(residual - center)
            if best is None or fit < best[1]:
                best = (a, fit, min(max(residual, lo), hi))
    preds[a]["state"] = 1
    preds[a]["power_w"] = float(assigned_w)
    preds[a]["rule"] = "additive_recovery"
    residual = panel_power_w - explained_hi()
```

Residual beyond the ON set's band maxima switches on the single best fitting OFF
appliance, by distance from its band centre, and repeats until the residual falls
under 400 W or nothing fits.

### Rule F, overshoot trim

```python
overshoot = explained_lo() - panel_power_w
while overshoot > on_tol_w:
    if len(on) <= 1: break
    top = max(on, key=lambda ap: ap[1]["confidence"])[0]
    trimmable = [(a, p) for a, p in on
                 if a != top
                 and p["confidence"] < PROTECT_CONF
                 and p.get("rule") not in PROTECTED_RULES]
    if not trimmable: break
    victim = min(trimmable, key=lambda ap: ap[1]["confidence"])[0]
```

Deliberately soft. The top call is never trimmed, a confidence at or above 0.50
is never trimmed, and anything physics or weather set is never trimmed. That is
what `PROTECTED_RULES` is for. Without it, additive recovery and the trim would
fight each other on every tick.

### The `rule` field

Every prediction carries the rule that decided it, which is what makes a wrong
answer diagnosable from the written row alone.

| value | meaning |
|---|---|
| `model` | the ONNX probability crossed its threshold and nothing overrode it |
| `solar_gate:low_solar` | no useful solar resource, pump forced off |
| `solar_recovery` | sunny, small Panel1 draw in band, heat pump not the explanation |
| `heat_pump_recovery` | recovered from measured Panel1 residual |
| `water_heater_power_gate` | Panel2 above 2.5 kW |
| `water_heater_solar_fallback` | solar confidently off and Panel2 in the element band |
| `power_gate_off` | appliance minimum exceeds the whole panel draw |
| `additive_recovery` | switched on to explain residual watts |
| `overshoot_trim` | switched off because the ON set over-explained the panel |
| `mutex:lost_to_<other>` | currently unreachable, `MUTEX_GROUPS` is empty |

---

## 5. Decision support rules

`decision_support/rule_tree.py`, 34 lines and worth quoting in full because it
decides what the system may do without asking.

```python
def tag_action(appliance: str, action_type: str) -> str:
    app = APPLIANCES.get(appliance, {})
    laxity = app.get("laxity", "user_controlled_non_interval")
    if laxity == "auto_controlled":  return "auto"
    if laxity == "uninterruptible":  return "auto"
    return "user"

def determine_flow_branch(mode, load_kw, generation_kw, soc_pct) -> str:
    if mode == "on_grid":
        if load_kw > generation_kw: return "5.16_on_grid_load>gen"
        return "5.16_on_grid_gen>load"
    else:
        if load_kw > generation_kw and soc_pct > 10:  return "5.16_off_grid_discharge"
        if load_kw > generation_kw and soc_pct <= 10: return "5.16_off_grid_generac"
        return "5.16_off_grid_store_excess"
```

Shedding never touches the critical set, `inference/appliance_map.py:89`.

```python
CRITICAL_APPLIANCES = (
    "refrigerator", "garage_fridge", "garage_freezer",
    "pressure_pump", "garage_opener",  # + networking (unmetered)
)
MOBILE_APPLIANCES = ("vacuum_cleaner",)
```

HVAC is the only real actuator on the site, because all thirteen Home Assistant
switches are inverter charge point settings rather than appliances. It sheds by
raising the cooling setpoint rather than setting `hvac_mode=off`, so the
thermostat's own compressor protection logic decides when to stop and the
compressor is never short cycled. `detect/hvac_shed.py`, 414 lines, lists six
safety invariants, each of which exists because of a specific way this can hurt.

```
1. Original state written to disk BEFORE the first change, so a crash mid-shed
   can still be undone. Restore must not depend on memory.
2. Hard maximum shed duration, auto-restores even if the anomaly never clears.
3. Indoor temperature ceiling. Occupants outrank amps.
4. Startup deadman. A shed state file older than the max duration triggers an
   immediate restore on boot.
5. Manual override wins. If the setpoint is not what we set it to, a human moved
   it, so stand down until the next clean cycle.
6. Cooldown between sheds, so the controller cannot itself short-cycle.
```
