import json, os
TRAIN=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p=os.path.join(TRAIN,"ct_appliance_map.json")
d=json.load(open(p))
dm=d["derived_measured_appliances"]
dm["heat_pump"]["note"]=("heat_pump is the only 240V load on Panel1; balanced-leg isolates it cleanly at ~4900-5750W WHEN RUNNING (tight cluster). "
  "Runs ~1% of time (summer); spec band 1500-4000W is LOW, actual ~5-5.7kW. Trustworthy per-event; sparse until colder weather.")
dm["heat_pump"]["measured_when_on_band_W"]=[4900,5750]
dm["water_heater"]["note"]=("water_heater is the only 240V load on Panel2; balanced-leg isolates it CLEANLY at 3830-3944W (0% over 4kW ceiling). Best measured head.")
dm["dryer"]["appliance_group"]=["dryer","oven","cooktop"]
dm["dryer"]["note"]=("CONTAMINATED: balanced-240 on Panel3 is a 240V-KITCHEN AGGREGATE, not clean dryer. Spread 3.0-8.5kW, 0.08% over 7kW dryer ceiling, "
  "strong events cluster 16-18h (dinner) => oven+cooktop (both 240V per spec) mix in. Isolating dryer needs a 2nd split by run-duration/time. Walk-test must toggle dryer/oven/cooktop separately.")
dm["dryer"]["confidence"]="aggregate-240V (needs sub-split)"
d["_precheck"]={
 "P2_clean":"water_heater single 240V load, tight 3830-3944W",
 "P1_clean_when_on":"heat_pump clean ~5kW cluster, runs ~1% time, spec band too low",
 "P3_contaminated":"dryer+oven+cooktop share the 240V balanced bucket; dinner-hour concentration confirms cooking loads",
 "leg_asymmetry":"120V loads sit almost entirely on one leg/panel (P2 legA, P3 legA); opposite leg near-empty => imbal120 ~= that leg's 120V aggregate",
 "solar_pump_candidate":"P1 shows ~150-270W 120V plateau during HP-off, partially isolable; present on both legs so P1 has a 2nd 120V load (blower?) - walk-test to resolve"
}
json.dump(d,open(p,"w"),indent=2)
print("patched",p)
