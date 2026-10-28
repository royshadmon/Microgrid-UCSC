#!/usr/bin/env python3
"""Generate synthetic eGauge and Solar Assistant data for IEMS test scenarios.

Usage
    python3 generate.py                     # every scenario in scenarios.yaml
    python3 generate.py grid_outage_islanded meter_dropout
    python3 generate.py --list

Output, one folder per scenario under output/
    energy_readings.csv   ts, dev, nm, tp, w, kwh   (same columns as the live table)
    solar_data.csv        ts, pv_power, battery_power, battery_soc, grid_power,
                          load_power, device_mode
    expect.json           what the pipeline is expected to do

All data is synthetic. Battery power is positive while charging in this
generator only. Confirm the sign against the live Solar Assistant feed before
asserting on it.
"""
import csv, json, math, random, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

HERE = Path(__file__).resolve().parent
LAT, LON = 37.24, -121.96  # rounded public coordinates, good enough for a sun curve
CHANNELS = ["Grid Power", "Generac Power", "Panel1 (HVAC)", "Panel2 (H2O)",
            "Panel3 (Kitchen)", "Shop", "VrmsA", "VrmsB", "I11", "I12", "I21",
            "I22", "I31", "I32", "F1", "Current on Utility Tie"]


def sun_elev(t):
    doy = t.timetuple().tm_yday
    decl = 23.44 * math.sin(math.radians(360 / 365 * (doy - 81)))
    hour = t.hour + t.minute / 60 + t.second / 3600 + LON / 15
    ha = 15 * (hour - 12)
    la, de, h = map(math.radians, (LAT, decl, ha))
    return math.degrees(math.asin(math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(h)))


def active(events, minute):
    flags = {}
    for e in events or []:
        if e["at_min"] <= minute < e.get("until_min", 10 ** 9):
            flags.update(e["set"])
    return flags


def iso(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


def build(name, sc, defaults):
    cfg = {**defaults, **sc}
    rnd = random.Random(cfg["seed"])
    start = datetime.fromisoformat(cfg["start"].replace("Z", "+00:00")).astimezone(timezone.utc)
    dur = int(cfg["duration_min"]) * 60
    estep, sstep = int(cfg["egauge_step_s"]), int(cfg["solar_step_s"])
    soc = float((cfg.get("initial") or {}).get("battery_soc", 85))
    out = HERE / "output" / name
    out.mkdir(parents=True, exist_ok=True)

    e_rows, s_rows, last_vals, kwh = [], [], None, {c: 0.0 for c in CHANNELS}
    for s in range(0, dur, 1):
        t = start + timedelta(seconds=s)
        f = active(cfg.get("events"), s / 60)
        on = lambda k: str(f.get(k, "")).lower() in ("on", "true", "1")

        el = sun_elev(t)
        pv = 0.0 if el <= 0 else 6200 * math.sin(math.radians(el)) * (0.9 + 0.1 * rnd.random())
        fridge = 150 if (s // 60) % 40 < 15 else 3
        p1 = 140 + (3200 if on("heat_pump") else 0) + (120 if el > 10 else 0) + rnd.uniform(-6, 6)
        p2 = 55 + rnd.uniform(-5, 5)
        p3 = 170 + fridge + rnd.uniform(-8, 8)
        shop = 9 + rnd.uniform(-2, 2)
        load = p1 + p2 + p3 + shop

        # YAML 1.1 reads a bare on/off as True/False, so accept both spellings.
        grid_up = str(f.get("grid", "on")).lower() not in ("off", "false", "0")
        gen = load if on("generac") else 0.0
        if on("blackout"):
            pv = p1 = p2 = p3 = shop = load = gen = 0.0
            batt, grid, mode = 0.0, 0.0, "Fault"
        elif grid_up:
            charge = min(3000.0, max(0.0, pv - load)) if soc < 100 else 0.0
            batt, grid, mode = charge, load + charge - pv, "Grid"
        else:
            if gen:
                batt, grid, mode = min(2000.0, max(0.0, gen + pv - load)), 0.0, "Generator"
            else:
                batt, grid, mode = pv - load, 0.0, "Battery"
        soc = max(0.0, min(100.0, soc + batt / 13500 * 100 / 3600))  # 13.5 kWh pack

        if s % sstep == 0:
            s_rows.append([iso(t), round(pv), round(batt), round(soc, 1), round(grid),
                           round(load), mode])

        if s % estep:
            continue
        if on("blackout") or on("egauge_dropout"):
            continue
        v = 105.0 if on("vsag") else (120.0 if not grid_up else 121.2)
        vals = {
            "Grid Power": grid, "Generac Power": gen,
            "Panel1 (HVAC)": p1, "Panel2 (H2O)": p2, "Panel3 (Kitchen)": p3, "Shop": shop,
            "VrmsA": v + rnd.uniform(-0.4, 0.4), "VrmsB": v + rnd.uniform(-0.4, 0.4),
            "I11": p1 / 240, "I12": p1 / 240, "I21": p2 / 240, "I22": p2 / 240,
            "I31": p3 / 240, "I32": p3 / 240, "F1": 60.0 + rnd.uniform(-0.02, 0.02),
            "Current on Utility Tie": abs(grid) / 240 if grid_up else 0.0,
        }
        if on("sign_flip"):
            for c in ("Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"):
                vals[c] = -vals[c]
        if on("frozen") and last_vals is not None:
            vals = dict(last_vals)
        last_vals = vals
        for c in CHANNELS:
            tp = "V" if c.startswith("Vrms") else "I" if c.startswith(("I", "Current")) else "F" if c == "F1" else "P"
            if tp == "P":
                kwh[c] += vals[c] * estep / 3.6e6
            e_rows.append([iso(t), "192", c, tp, round(vals[c], 3), round(kwh[c], 6)])

    with open(out / "energy_readings.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["ts", "dev", "nm", "tp", "w", "kwh"]); w.writerows(e_rows)
    with open(out / "solar_data.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "pv_power", "battery_power", "battery_soc", "grid_power", "load_power", "device_mode"])
        w.writerows(s_rows)
    (out / "expect.json").write_text(json.dumps(
        {"scenario": name, "description": sc.get("description", ""), "start": cfg["start"],
         "duration_min": cfg["duration_min"], "events": cfg.get("events", []),
         "expect": sc.get("expect", {})}, indent=1))
    return len(e_rows), len(s_rows)


def main(argv):
    spec = yaml.safe_load((HERE / "scenarios.yaml").read_text())
    scs, defaults = spec["scenarios"], spec["defaults"]
    if "--list" in argv:
        for k, v in scs.items():
            print(f"{k:24s} {v.get('description', '')}")
        return
    names = [a for a in argv if not a.startswith("-")] or list(scs)
    for n in names:
        if n not in scs:
            sys.exit(f"unknown scenario {n}")
        e, s = build(n, scs[n], defaults)
        print(f"{n:24s} energy_readings {e:6d} rows   solar_data {s:4d} rows")


if __name__ == "__main__":
    main(sys.argv[1:])
