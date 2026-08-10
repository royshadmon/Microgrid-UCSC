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
 "strip_heater_1": Sig("strip_heater_1", "Panel1 (HVAC)", "raw", (6000, 12000), 5800,
    (120, 7200), "plateau", cv=(0.0, 0.35), min_samples=10,
    note="resistance backup heat. Flat, high, no modulation. Observed max on "
         "Panel1 is 5691W = compressor+fan, so this never fired in-sample."),
 "strip_heater_2": Sig("strip_heater_2", "Panel1 (HVAC)", "raw", (6000, 12000), 5800,
    (120, 7200), "plateau", cv=(0.0, 0.35), min_samples=10,
    note="second strip heater, marked 'off to save $' on the directory."),

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
    (300, 5400), "cycle", tod=(6, 23), cyc_rate=(0.15, 8.0), cv=(0.25, 3.0),
    min_samples=40,
    note="canonical 200-2000W on-thr 50W. CYCLES fill/agitate/rinse/spin -> HIGH "
         "intra-run variance cv>=0.25. This separates it from the flat dryer."),
 "dishwasher": Sig("dishwasher", "Panel3 (Kitchen)", "paired", (200, 1800), 50,
    (900, 9000), "cycle", tod=(6, 24), cyc_rate=(0.1, 8.0), cv=(0.2, 3.0),
    min_samples=40,
    note="canonical 200-1800W on-thr 50W. Two heater pulses (MainWash1->Idle->"
         "MainWash2) separated by ~30min idle. Pulse PAIRING separates it from the "
         "single-burst microwave/cooktop -> no longer coupled."),
 "microwave": Sig("microwave", "Panel3 (Kitchen)", "raw", (900, 1500), 200,
    (10, 900), "impulse", tod=(5, 24), edge=500, cyc_rate=(0.0, 3.0), coupled=True,
    note="canonical 900-1500W on-thr 200W. Sharp impulse <10min, meal hours. "
         "DEGENERATE with cooktop + dishwasher-heater -> weak-only."),
 "pressure_pump": Sig("pressure_pump", "Panel3 (Kitchen)", "osc", (500, 1000), 200,
    (20, 1200), "step", cyc_rate=(0.0, 4.0),
    note="canonical 500-1000W on-thr 200W. Demand-driven short steps, any hour. Critical."),
 "refrigerator": Sig("refrigerator", "Panel3 (Kitchen)", "osc", (80, 300), 50,
    (300, 3600), "cycle", cyc_rate=(0.0, 4.0), period_s=(1200, 9000),
    duty=(0.15, 0.85), min_samples=20,
    note="AGGREGATE of kitchen fridge + garage fridge + garage FREEZER -> 2-3 "
         "SUPERPOSED duty cycles, so the ceiling must admit two compressors at "
         "once. Widened 200->300W 2026-08-10 on three converging lines of "
         "evidence: (1) Kelly & Knottenbelt 2015 give max_power=300W / "
         "on_power_threshold=50W for a SINGLE fridge in UK-DALE (6s cadence, "
         "same regime as this site) -- our on_thr already matched at 50W but "
         "the ceiling sat below one unit's maximum; (2) NEEA RBSA metering "
         "reports 604 kWh/yr primary + 600 kWh/yr secondary refrigerator, so a "
         "3-unit aggregate should imply ~1200+ kWh/yr, while these labels imply "
         "375 kWh/yr -- 0.31x, the gap a truncated ceiling produces; (3) on this "
         "archive the 80-300W band covers 35.9% of Panel3 OSC samples vs 32.7% "
         "for 80-200W, and p90=214W sits ABOVE the old ceiling. Beyond 300W the "
         "gain collapses (36.3% at 450W), which is why the ceiling stops there "
         "rather than chasing the p95=1201W tail that belongs to other loads."),
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
 "toaster": Sig("toaster", "Panel3 (Kitchen)", "raw", (800, 1500), 600,
    (60, 240), "plateau", tod=(5, 11), cv=(0.0, 0.4), min_dur_hard=45,
    note="counter recept. 1-4 min, morning, flat. Shortest of the 800-1500W "
         "group apart from the microwave."),
 "coffee_maker": Sig("coffee_maker", "Panel3 (Kitchen)", "raw", (800, 1500), 600,
    (240, 900), "cycle", tod=(4, 12), cv=(0.2, 1.0),
    note="counter recept. Brew 4-15 min then warming-plate cycling."),
 "clothes_iron": Sig("clothes_iron", "Panel3 (Kitchen)", "raw", (1000, 1800), 700,
    (600, 3600), "cycle", cyc_rate=(2.0, 30.0), cv=(0.3, 1.4), duty=(0.15, 0.75),
    note="counter recept. Thermostatic: long envelope, many short fires, low "
         "duty. The cycling is what separates it from a toaster."),

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
BACKGROUND = ("toaster_oven", "disposal", "networking", "general_lighting",
              "garage_fridge", "garage_freezer")
CRITICAL = ("refrigerator", "garage_fridge", "garage_freezer", "garage_opener",
            "pressure_pump")  # spec: never shed these
BATTERY_WINDOW = (16, 21)   # spec: battery charged daily 16:00-21:00 local

PANEL_HEADS = {
    1: ("heat_pump", "solar_pump", "jacuzzi_pump",
        "strip_heater_1", "strip_heater_2"),
    2: ("water_heater", "hair_dryer", "sprinklers", "bath_lights"),
    # garage_fridge / garage_freezer REMOVED as heads 2026-08-07. All three
    # refrigeration loads are 80-200W oscillators on one panel; labelling them
    # separately produced ~208k positives each -- the same compressor cycles
    # counted three times. `refrigerator` now means "aggregate refrigeration"
    # and the spec's three critical cold loads are covered by that one head.
    # Separating them needs a sub-meter, not a better model.
    3: ("dryer", "washing_machine", "dishwasher", "microwave",
        "pressure_pump", "refrigerator", "computers", "tv_stereo",
        "oven", "cooktop", "toaster", "coffee_maker", "clothes_iron",
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
 "jacuzzi_pump":"osc", "strip_heater_1":"raw", "strip_heater_2":"raw",
 # Panel3 additions: 240V cooking and counter loads are discrete events;
 # the two garage refrigeration loads ride on the baseline like the kitchen one.
 "oven":"raw", "cooktop":"raw", "toaster":"raw", "coffee_maker":"raw",
 "clothes_iron":"raw", "garage_opener":"raw",
}
# dishwasher pulse-pair parameters (ref: 1200-2400W stages, ~30min apart)
PAIRED = {"dishwasher": dict(w=(1200,2400), pulse_min_s=240, gap_min_s=600,
                             gap_max_s=4500, env_min_s=2400, env_max_s=12000)}
FLOOR_WIN, OSC_WIN = "20min", "20min"

def measure_of(app): return MEASURE.get(app, "raw")
