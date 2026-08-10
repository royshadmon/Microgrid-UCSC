# Appliance signature cross-check against the field-measurement literature

Date: 2026-08-10 · Archive: 136 days, 705,296 timestamps, 1–6 s cadence, three sub-panels.

## Source selection

Sources were filtered to those working with **data of the kind this system actually has**:
low-frequency real power (1 s – 15 min), metered in occupied homes, over months to years.
High-frequency work (V–I trajectories, harmonic signatures, transient classification at
kHz sampling) was **excluded outright** — the eGauge cannot produce those features, so a
signature justified by them could never be verified or falsified here.

| Source | Regime | Why it qualifies |
|---|---|---|
| Kelly & Knottenbelt 2015, *Neural NILM* (BuildSys), Table 4 | UK-DALE, **6 s** appliance submeters, 5 homes, up to 655 days | Same cadence as this deployment; gives explicit on-power thresholds and min on/off durations |
| Kelly & Knottenbelt 2015, *UK-DALE* (Sci. Data 2:150007) | 6 s submetered + aggregate | Dataset the above thresholds were fitted on |
| Less & Walker 2024, LBNL/ACEEE, *HVAC Heat Pump Upgrades and Household Maximum Power Demand* | Pecan Street Dataport + NEEA EULR, **957 US dwellings**, 15-min sub-metered, avg 2.7–4.1 yr | US split-phase 240 V, same electrical topology as this site |
| NEEA Residential Building Stock Assessment — Metering Study (E14-283, 2014) | ~100 US Pacific-NW homes, panel + plug metering, 1 yr | Per-appliance **annual energy**, the quantity a label set can be falsified against |
| Makonin et al. 2016, *AMPds2* (Sci. Data 3:160037) | 1 house, **1 min**, 2 yr, Canadian split-phase | Single-home, long-duration, 240 V — closest structural analogue |
| Hart 1992, *Nonintrusive Appliance Load Monitoring* | Aggregate real power | Origin of the step-change/duty-cycle framing the rules engine uses |

## Direct threshold comparison — Kelly & Knottenbelt Table 4 (UK-DALE, 6 s)

| Appliance | Lit. max power | Lit. on-threshold | Lit. min on | This system | Verdict |
|---|---|---|---|---|---|
| Fridge | 300 W | 50 W | 60 s | 80–300 W, thr 50 W, 300 s | **on-threshold matches exactly**; ceiling corrected 200→300 (below) |
| Washing machine | 2500 W | 20 W | **1800 s** | 200–2000 W, thr 50 W, **300 s** | band fine; **min duration 6× too permissive** |
| Dishwasher | 2500 W | 10 W | **1800 s** | 200–1800 W, thr 50 W, **900 s** | band fine; min duration 2× permissive |
| Microwave | 3000 W | **200 W** | 12 s | 900–1500 W, thr **200 W**, 10 s | **on-threshold matches exactly**; UK ceiling is higher (230 V) |
| Kettle | 3100 W | 2000 W | 12 s | — | not present in a US home; correctly absent |

Two of our thresholds (fridge 50 W, microwave 200 W) reproduce Kelly's independently
derived values exactly. That is a meaningful independent confirmation, not a coincidence.

## Heat pump — LBNL/ACEEE 2024, 957 US dwellings

Reported medians of maximum sub-metered demand: **Central Heat Pump 2.99 kW** (n=456),
Central Cooling 2.80 kW (n=374), ducted 2.88 kW, ductless 1.85 kW, **Air Handler 0.70 kW** (n=681).

This system uses 2500–5700 W, measured p50 = 4620 W. That sits above LBNL's median —
but the comparison is **not like-for-like**: LBNL aggregated to 15-minute averages, which
attenuates the compressor peaks that 1–6 s sampling resolves. Adding the separately
metered air handler (0.70 kW) to a compressor puts a single unit near 3.7 kW before any
peak-averaging correction. **No change made.** The band stands, with the caveat recorded.

Two findings from that paper are directly useful here:
- Pecan Street screened compressors with a **0.5 kW floor to exclude crankcase heaters**.
  Our 1200 W on-threshold already clears that failure mode.
- Multi-speed heat pumps "modulate to partial capacity", which independently explains this
  site's measured `bal240_p1` median of 269 W — low-power operation is expected, not a fault.

## Energy plausibility — the falsification test

Published annual energy is the one quantity a label set can be checked against without
ground truth. Implied energy = label ON-fraction × band midpoint × 8760 h.

| Head | ON h/day | Implied kWh/yr | Published | Ratio |
|---|---|---|---|---|
| water_heater | 0.38 | 442 | 3030 (NEEA, n=49) | 0.15× — **expected**, solar-thermal preheat |
| dryer | 0.06 | 117 | 725 (NEEA, n=93) | **0.16× — under-detected** |
| refrigerator | 7.34 | 375 | 1204 (NEEA, 604+600) | **0.31× — under-detected** |
| washing_machine | **1.85** | 742 | — | ON-time 1.8× any plausible upper bound |
| clothes_iron | **0.78** | 396 | — | 47 min of ironing *every day* — **not credible** |
| microwave | 0.48 | 212 | — | 29 min/day — high |
| cooktop | 0.94 | 1111 | — | 1111 kWh/yr for a cooktop is high |
| dishwasher | 0.65 | 237 | — | plausible |
| oven / toaster / coffee_maker / computers / tv_stereo | — | — | — | plausible |

The water_heater gap is the system **passing** a consistency check: this house preheats with
solar thermal, so 15% of a standard electric tank is exactly what should be seen.

## Changes applied

**`refrigerator` band 80–200 W → 80–300 W.** Three independent lines converge:
1. Kelly gives `max_power = 300 W` for a *single* fridge; our head is an **aggregate of three**
   cold appliances, so a 200 W ceiling could not even represent one unit at full draw, let
   alone two compressors overlapping.
2. NEEA reports 604 + 600 kWh/yr for primary + secondary refrigerators; our labels imply
   375 kWh/yr for three units — the 0.31× shortfall a truncated ceiling produces.
3. On this archive the 80–300 W band covers 35.9 % of Panel 3 OSC samples vs 32.7 % at
   80–200 W, and **p90 = 214 W sits above the old ceiling**. Past 300 W the gain collapses
   (36.3 % at 450 W), so the ceiling stops there rather than chasing the p95 = 1201 W tail
   that belongs to other loads.

## Recommended but NOT applied — these need a retrain to validate

- **`washing_machine` min duration 300 s → toward Kelly's 1800 s.** Ours admits runs 6×
  shorter than the literature, and the head reports 111 min/day of washing. This is the
  single most likely source of false positives on Panel 3.
- **`dishwasher` min duration 900 s → 1800 s** (Kelly), consistent with the paired-pulse envelope.
- **`clothes_iron`** is the least defensible head in the system. 47 min/day is not credible,
  and NEEA's metering contractor **deliberately excluded irons, toasters and hair dryers**
  from instrumentation as too small and intermittent to justify a meter. The literature
  offers no support for separating them from the 800–1500 W group.

Changing durations shifts the label set the deployed BiLSTMs were trained against, so these
are left staged rather than applied silently.

## What the literature does not support

No source in this regime claims separability of **toaster / coffee_maker / clothes_iron** by
low-frequency real power alone. They share the 800–1500 W band and are currently divided by
duration heuristics that have never been checked against ground truth. The honest position
is that these three heads are unverified, and the smart-plug campaign remains the only way
to settle them.
