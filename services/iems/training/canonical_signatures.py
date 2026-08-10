"""Canonical appliance signatures - source: appliance_data_updated.txt

Bands/on-thresholds VERBATIM from that spec. Temporal layer (kind, duration,
time-of-day, cycle structure) added on top, calibrated on the 11.4M-row
consolidated eGauge series + public reference data.

SIGNATURE TYPES (kind)
  impulse  short sharp burst <10min, sharp rising edge   -> microwave, vacuum
  cycle    REPEATING multi-phase / duty-cycled structure -> washing_machine,
           dishwasher, refrigerator (compressor duty cycle)
  plateau  CONSTANT sustained draw, near-flat            -> dryer, computers,
           tv_stereo, bath_lights
  step     small level shift held for a scheduled block  -> sprinklers,
           solar_pump, pressure_pump
  ramp     high sustained w/ thermostat modulation       -> heat_pump, water_heater

WASHER vs DRYER (the spec's key contrast):
  washing_machine kind=cycle   -> HIGH intra-run variance, repeated level changes
  dryer           kind=plateau -> LOW variance, ONE long flat block
Both exceed 1 kW, so VARIANCE + DURATION separate them, never power alone.

CADENCE: AnyLog median inter-sample spacing is ~1s (not the nominal 6s), ~0.9%
of samples follow a >30s gap. All dur_s are SECONDS and cyc_rate is per MINUTE,
so bounds are cadence-independent; min_samples guards thin confirmations.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class Sig:
    name: str
    panel: str
    measure: str
    w: tuple
    on_thr: float
    dur_s: tuple
    kind: str
    tod: Optional[tuple] = None
    edge: float = 0.0
    cyc_rate: tuple = (0.0, np.inf)
    cv: tuple = (0.0, np.inf)
    period_s: tuple = (0.0, np.inf)
    duty: tuple = (0.0, 1.0)
    min_samples: int = 5
    min_dur_hard: float = 0.0
    no_confident_off: bool = False
    coupled: bool = False
    mutex: tuple = ()
    note: str = ""


SIGNATURES: dict[str, Sig] = {
 # ---------------- PANEL 1 (HVAC) ----------------
 "heat_pump": Sig("heat_pump", "Panel1 (HVAC)", "raw", (2500, 5700), 1200,
    (60, 10800), "ramp", cyc_rate=(0.0, 6.0), cv=(0.0, 0.6),
    mutex=(),  # interlock removed 2026-08-05
    note="MEASURED 2500-5700W (spec said 1500-4000W with a '???' -- that band "
         "holds only 0.39% of Panel1 samples vs 4.78% for the measured band; "
         "the spec was low). Observed max 5691W. "
         "MEASURED bal240_p1 p50=269W so low-power mode dominates. No mutex."),
 "solar_pump": Sig("solar_pump", "Panel1 (HVAC)", "osc", (100, 250), 50,
    (300, 10800), "step", tod=(7, 19), cyc_rate=(0.0, 3.0), mutex=(),  # interlock removed 2026-08-05
    note="canonical 100-250W on-thr 50W. Irradiance-gated -> daylight only. May run concurrently with heat_pump (no interlock)."),

 # Jacuzzi pump, breaker 13/15. Spa circulation ~1.5kW with jets.
 "jacuzzi_pump": Sig("jacuzzi_pump", "Panel1 (HVAC)", "osc", (800, 2000), 400,
    (600, 14400), "plateau", cyc_rate=(0.0, 3.0), cv=(0.0, 0.5),
    note="240V spa pump. Long plateau, low variance. Distinguished from the "
         "compressor by power (1-2kW vs 2.5-5kW) and by NOT cycling on a "
         "thermostat rhythm."),

 # Strip heaters, breakers 6/8 and 10/12. Resistance backup heat: 4.5-10kW.
 # NO POSITIVE LABELS EXPECTED from Mar-Jul data -- these are winter loads and
 # one is switched off at the panel. Heads exist so that winter data can train
 # them without another architecture change; until then they stay all-zero and
 # their metrics are meaningless rather than good.
 # Strip heaters, breakers 6/8 and 10/12. Resistance backup heat 4.5-10kW.
 # MERGED to one head 2026-08-10: the two Sig definitions were byte-identical
 # (same band, threshold, duration, kind), so two heads could never disagree --
 # they were one signature trained twice. Both are winter loads and one is
 # switched off at the panel, so neither has a positive label in Mar-Jul data.
 "strip_heater": Sig("strip_heater", "Panel1 (HVAC)", "raw", (6000, 12000), 5800,
    (120, 7200), "plateau", cv=(0.0, 0.35), min_samples=10,
    note="resistance backup heat, both elements. Flat, high, no modulation. "
         "Observed Panel1 max is 5691W = compressor+fan, so this never fired "
         "in-sample; the head exists so winter data can train it without an "
         "architecture change, and stays honestly all-zero until then."),

 # ---------------- PANEL 2 (H2O) ----------------
 "water_heater": Sig("water_heater", "Panel2 (H2O)", "raw", (2000, 4300), 500,
    (30, 7200), "ramp", cyc_rate=(0.0, 6.0), no_confident_off=True,
    note="canonical 2000-4000W, hi widened to 4300 (CT element p95=4011W). MEASURED "
         "p50 only 107W. Element fires RARE -> silence is NOT evidence of OFF."),
 "hair_dryer": Sig("hair_dryer", "Panel2 (H2O)", "raw", (1200, 1800), 800,
    (30, 900), "impulse", tod=(5, 23), edge=500, cyc_rate=(0.0, 2.0),
    note="canonical 1200-1800W on-thr 800W. Measured 1559W/4.3min = excellent match."),
 "sprinklers": Sig("sprinklers", "Panel2 (H2O)", "osc", (100, 300), 50,
    (60, 5400), "step", tod=(3, 11), cyc_rate=(0.0, 2.0),
    note="canonical 100-300W on-thr 50W. Scheduled AM irrigation. Same band as "
         "bath_lights -> separated by TIME-OF-DAY."),
 "bath_lights": Sig("bath_lights", "Panel2 (H2O)", "osc", (100, 300), 80,
    (60, 3600), "plateau", tod=(16, 24), cyc_rate=(0.0, 1.0), cv=(0.0, 0.25),
    note="canonical 100-300W on-thr 80W. Only incandescent load -> perfectly FLAT, "
         "short daily evening use. Same band as sprinklers -> TIME + flatness."),

 # ---------------- PANEL 3 (Kitchen + garage) ----------------
 "dryer": Sig("dryer", "Panel3 (Kitchen)", "raw", (4000, 7000), 1000,
    (300, 5400), "plateau", tod=(7, 23), cyc_rate=(0.0, 2.0), cv=(0.0, 0.35),
    min_dur_hard=360.0, min_samples=36,
    note="canonical 4000-7000W on-thr 1000W. CONSTANT element -> LOW variance, "
         "ONE flat block 20-90min. Hard >=10min gate: raw band was 97% short "
         "oven/cooktop bursts (unlabeled background per spec)."),
 "washing_machine": Sig("washing_machine", "Panel3 (Kitchen)", "osc", (200, 2000), 50,
    (1800, 7200), "cycle", tod=(6, 23), cyc_rate=(0.15, 8.0), cv=(0.25, 3.0),
    min_samples=40,
    note="canonical 200-2000W on-thr 50W. CYCLES fill/agitate/rinse/spin -> HIGH "
         "intra-run variance cv>=0.25, which separates it from the flat dryer. "
         "MIN DURATION RAISED 300 -> 1800s 2026-08-10 to match Kelly & "
         "Knottenbelt 2015 (UK-DALE, 6s cadence) whose get_activations uses "
         "min_on_duration=1800s for a washer. At 300s the head claimed 111 "
         "min/day of washing and an implied 742 kWh/yr; no wash cycle is 5 "
         "minutes long, so those short runs were fragments of other loads."),
 "dishwasher": Sig("dishwasher", "Panel3 (Kitchen)", "paired", (200, 1800), 50,
    (1800, 9000), "cycle", tod=(6, 24), cyc_rate=(0.1, 8.0), cv=(0.2, 3.0),
    min_samples=40,
    note="canonical 200-1800W on-thr 50W. Min duration 900->1800s (Kelly 2015). "
         "Two heater pulses (MainWash1->Idle->"
         "MainWash2) separated by ~30min idle. Pulse PAIRING separates it from the "
         "single-burst microwave/cooktop -> no longer coupled."),
 "microwave": Sig("microwave", "Panel3 (Kitchen)", "raw", (900, 1500), 200,
    (10, 900), "impulse", tod=(5, 24), edge=500, cyc_rate=(0.0, 3.0), coupled=True,
    note="canonical 900-1500W on-thr 200W. Sharp impulse <10min, meal hours. "
         "DEGENERATE with cooktop + dishwasher-heater -> weak-only."),
 "pressure_pump": Sig("pressure_pump", "Panel3 (Kitchen)", "osc", (500, 1000), 200,
    (20, 1200), "step", cyc_rate=(0.0, 4.0),
    note="canonical 500-1000W on-thr 200W. Demand-driven short steps, any hour. Critical."),
 # ── REFRIGERATION: three cold appliances on one panel ────────────────────
 # Split back into three heads 2026-08-10 at the researcher's direction. They
 # were merged on 2026-08-07 because labelling them separately produced ~208k
 # positives each -- the same compressor cycles counted three times. The split
 # below avoids that by giving each head a DISJOINT duty/period window instead
 # of a shared power band, so one cycle can only score well against one head.
 #
 # HONEST LIMIT: at 1-6 s real power on a single panel CT there is no feature
 # that proves WHICH box a given compressor cycle belongs to. The separation
 # rests on duty-cycle and period priors from the panel directory (garage units
 # sit in an unconditioned space and run a much higher duty than the kitchen
 # unit; a chest freezer cycles longer and less often than a fridge). Treat
 # per-unit attribution as a prior-driven estimate until a sub-meter or plug
 # meter confirms it. The aggregate of the three remains trustworthy.
 "refrigerator": Sig("refrigerator", "Panel3 (Kitchen)", "osc", (80, 200), 50,
    (300, 3600), "cycle", cyc_rate=(0.0, 4.0), period_s=(1200, 3600),
    duty=(0.25, 0.50), min_samples=20,
    note="KITCHEN unit. Conditioned space -> the LOWEST duty of the three "
         "(field validation on this house measured 37.9% duty, ~13 min "
         "compressor ON, ~33 cycles/day). Kelly & Knottenbelt 2015 give "
         "max_power=300W / on_thr=50W for a single fridge in UK-DALE at 6s; "
         "our on_thr already matched, and 200W bounds ONE compressor."),
 "garage_fridge": Sig("garage_fridge", "Panel3 (Kitchen)", "osc", (80, 220), 50,
    (300, 3600), "cycle", cyc_rate=(0.0, 5.0), period_s=(900, 3000),
    duty=(0.55, 0.90), min_samples=20, coupled=True,
    note="GARAGE refrigerator, breaker 5/6. Unconditioned space -> the spec "
         "gives 70-80% duty against the kitchen unit's 33-40%. DUTY is the "
         "only discriminator; power alone cannot separate it, hence coupled."),
 "garage_freezer": Sig("garage_freezer", "Panel3 (Kitchen)", "osc", (80, 250), 50,
    (600, 5400), "cycle", cyc_rate=(0.0, 2.5), period_s=(2400, 9000),
    duty=(0.20, 0.55), min_samples=20, coupled=True,
    note="GARAGE freezer, breaker 5/6. Deeper setpoint and more thermal mass "
         "-> LONGER, LESS FREQUENT cycles than either fridge (period 40-150 "
         "min vs 20-60). Period is the discriminator; coupled, as above."),

 "computers": Sig("computers", "Panel3 (Kitchen)", "floor", (200, 500), 100,
    (600, 43200), "plateau", tod=(6, 24), cyc_rate=(0.02, 2.0), cv=(0.05, 1.2),
    min_samples=120,
    note="canonical 200-500W on-thr 100W. Multi-hour sustained w/ CPU-load "
         "fluctuation (cv>0.05) - separates it from the TV's flat draw."),
 "tv_stereo": Sig("tv_stereo", "Panel3 (Kitchen)", "floor", (100, 200), 80,
    (600, 25200), "plateau", tod=(16, 24), cyc_rate=(0.0, 0.3), cv=(0.0, 0.15),
    min_samples=120,
    note="canonical 100-200W on-thr 80W. Near-FLAT evening block. Overlaps the "
         "refrigerator band exactly -> separated by SHAPE + TIME, never power."),
 "vacuum_cleaner": Sig("vacuum_cleaner", "Panel3 (Kitchen)", "raw", (800, 1200), 600,
    (60, 3600), "impulse", tod=(7, 21), edge=400, coupled=True,
    note="canonical 800-1200W on-thr 600W. MOBILE load routed to Panel3 per spec. "
         "Not in the P3 head contract -> weak-only."),
 # ---------------- PANEL 3 additions (from the panel directory) ----------
 # 240V cooking. Breaker 8/10 = oven, 12/14 = range/cooktop. Observed Panel3
 # steps show a 3000-4500W band (2.0%) and a 5000-6000W band (1.0%).
 "oven": Sig("oven", "Panel3 (Kitchen)", "raw", (2000, 4000), 1200,
    (600, 14400), "ramp", cyc_rate=(0.0, 8.0), cv=(0.1, 0.9), tod=(6, 22),
    note="240V oven, breaker 8/10. Thermostatic: heats hard, cycles down, "
         "reheats -> ramp with moderate CV. Long envelope separates it from "
         "the cooktop."),
 "cooktop": Sig("cooktop", "Panel3 (Kitchen)", "raw", (1500, 5000), 1200,
    (120, 5400), "ramp", cyc_rate=(0.0, 20.0), cv=(0.2, 1.2), tod=(6, 22),
    note="240V range, breaker 12/14. Burner control cycles far faster than the "
         "oven and runs shorter overall."),

 # 800-1500W counter loads. Power CANNOT separate these -- 16.4% of all Panel3
 # ON-steps land in this band. Duration and hour do the work.
 # 800-1500 W COUNTER LOADS -- ONE head, not three.
 # Unified 2026-08-10. toaster, coffee_maker and clothes_iron shared a single
 # power band (16.4% of all Panel3 ON-steps land in 800-1500W) and were split
 # only by duration/hour heuristics that no measurement ever confirmed. The
 # energy cross-check showed why that failed: clothes_iron alone claimed 47
 # minutes of ironing EVERY DAY (396 kWh/yr implied). The field literature
 # gives no support for the split either -- NEEA's RBSA metering contractor
 # deliberately excluded toasters, irons and hair dryers from instrumentation
 # as too small and intermittent to justify a meter.
 # One honest head beats three confident guesses; a plug meter can split it later.
 "counter_appliance": Sig("counter_appliance", "Panel3 (Kitchen)", "raw", (800, 1500), 600,
    (45, 3600), "impulse", tod=(5, 23), cv=(0.0, 1.4), min_dur_hard=45,
    note="UNIFIED toaster + coffee_maker + clothes_iron (kitchen counter "
         "receptacles). Resistive 800-1500W loads on Panel3, separable from "
         "each other only by duration and hour -- heuristics that were never "
         "checked against ground truth and produced implausible run-times. "
         "Reported as one head until a plug meter can attribute them."),

 # Impulse loads.
 "garage_opener": Sig("garage_opener", "Panel3 (Kitchen)", "raw", (300, 800), 250,
    (3, 25), "impulse", min_dur_hard=2, min_samples=2,
    note="breaker 13/14. 5-20s motor burst. Critical load -- never shed."),

 # Second and third refrigeration loads on the garage receptacles (breaker 5/6).
 # Same signature as the kitchen fridge; they are separable only by count of
 # concurrent cycles, so confidence is intentionally capped by `coupled`.
 # (demoted to BACKGROUND -- see PANEL_HEADS note)
 # "garage_fridge": Sig("garage_fridge", "Panel3 (Kitchen)", "osc", (80, 200), 50,
 #     (600, 3600), "cycle", cyc_rate=(0.5, 4.0), coupled=True,
 #     note="garage recepts. Indistinguishable from the kitchen fridge by power "
 #          "alone -> coupled, low weight. Critical load."),
 # (demoted to BACKGROUND -- see PANEL_HEADS note)
 # "garage_freezer": Sig("garage_freezer", "Panel3 (Kitchen)", "osc", (80, 200), 50,
 #     (600, 5400), "cycle", cyc_rate=(0.5, 3.0), coupled=True,
 #     note="garage recepts. Longer, less frequent cycles than a fridge. "
 #          "Critical load."),

}

# spec: toaster, toaster_oven, coffee_maker, oven 240V, cooktop 240V, clothes_iron
# = unlabeled background, no dedicated heads. garage_opener deferred.
# Promoted to real heads 2026-08-07 from the panel directories: toaster,
# coffee_maker, oven, cooktop, clothes_iron, garage_opener, garage_fridge,
# garage_freezer, jacuzzi_pump, strip_heater_1/2. What remains background is
# genuinely unlabelled: general lighting, receptacles, networking, disposal.
BACKGROUND = ("toaster_oven", "disposal", "networking", "general_lighting")
CRITICAL = ("refrigerator", "garage_fridge", "garage_freezer", "garage_opener",
            "pressure_pump")  # spec: never shed these
BATTERY_WINDOW = (16, 21)   # spec: battery charged daily 16:00-21:00 local

PANEL_HEADS = {
    1: ("heat_pump", "solar_pump", "jacuzzi_pump", "strip_heater"),
    2: ("water_heater", "hair_dryer", "sprinklers", "bath_lights"),
    # garage_fridge / garage_freezer REMOVED as heads 2026-08-07. All three
    # refrigeration loads are 80-200W oscillators on one panel; labelling them
    # separately produced ~208k positives each -- the same compressor cycles
    # counted three times. `refrigerator` now means "aggregate refrigeration"
    # and the spec's three critical cold loads are covered by that one head.
    # Separating them needs a sub-meter, not a better model.
    3: ("dryer", "washing_machine", "dishwasher", "microwave",
        "pressure_pump", "refrigerator", "garage_fridge", "garage_freezer",
        "computers", "tv_stereo", "oven", "cooktop", "counter_appliance",
        "garage_opener"),
}


# Per-KIND gap merge (seconds). A run is terminated only after the signal stays
# out-of-band longer than this. Calibrated from the frequency census, which
# showed one washer load fragmenting into ~44 "events" at a flat 10 s gap:
#   impulse : genuinely short, no bridging wanted
#   step    : scheduled blocks, small dips
#   ramp    : thermostat modulation between fires
#   plateau : brief dips inside a sustained block
#   cycle   : multi-PHASE loads - the inter-phase pauses (fill->agitate->rinse->
#             spin, or fridge compressor rest) must NOT split the run
KIND_GAP_S = {"impulse": 10.0, "step": 30.0, "ramp": 120.0,
              "plateau": 90.0, "cycle": 240.0}

def gap_for(sig) -> float:
    return KIND_GAP_S.get(sig.kind, 20.0)


# Per-panel PHYSICAL DECOMPOSITION (validated against reference data):
#   raw    : discrete high-power events, appliance owns its band alone
#   osc    : signal - 20min rolling floor  -> CYCLING loads (compressor, pumps)
#   floor  : 20min rolling min - night baseline -> SUSTAINED loads (TV, computers)
#   paired : two heater pulses + idle gap -> dishwasher (MainWash1/Idle/MainWash2)
# Panel1 needs only raw+osc (two non-overlapping loads).
# Panel2 needs raw (high) + osc (small, split by time-of-day).
# Panel3 needs all three: floor(TV/computers) + osc(fridge) + raw/paired(discrete).
PAIRED = {"dishwasher": dict(w=(1200,2400), pulse_min_s=240, gap_min_s=600,
                             gap_max_s=4500, env_min_s=2400, env_max_s=12000)}
OSC_FLOOR_WIN = "20min"


# ─────────────────────────────────────────────────────────────────────────
# PER-PANEL PHYSICAL DECOMPOSITION  (validated against reference + 11.4M rows)
#
#   raw    : discrete high-power event on the panel signal itself
#   osc    : signal - 20min rolling floor  -> CYCLING loads riding on a baseline
#   floor  : 20min rolling floor - night baseline -> SUSTAINED loads that RAISE
#            the floor rather than creating excursions (TV, computers)
#   paired : two heater pulses separated by an idle period (dishwasher:
#            MainWash1 -> Idle -> MainWash2, patent-documented 4-section shape)
#
# The measure must match the load's PHYSICS. Reading a sustained load as an
# excursion gave 45 events/day; reading it off the floor gives 7. Reading a
# dishwasher as an excursion gave 45/day; as a pulse PAIR gives 2.3/day.
# ─────────────────────────────────────────────────────────────────────────
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
 # Panel1 additions
 "jacuzzi_pump":"osc", "strip_heater":"raw",
 # Panel3 additions: 240V cooking and counter loads are discrete events;
 # the two garage refrigeration loads ride on the baseline like the kitchen one.
 "oven":"raw", "cooktop":"raw", "counter_appliance":"raw", "garage_opener":"raw",
 # all three cold appliances ride on the panel baseline like the kitchen one
 "garage_fridge":"osc", "garage_freezer":"osc",
}
# dishwasher pulse-pair parameters (ref: 1200-2400W stages, ~30min apart)
PAIRED = {"dishwasher": dict(w=(1200,2400), pulse_min_s=240, gap_min_s=600,
                             gap_max_s=4500, env_min_s=2400, env_max_s=12000)}
FLOOR_WIN, OSC_WIN = "20min", "20min"

def measure_of(app): return MEASURE.get(app, "raw")
