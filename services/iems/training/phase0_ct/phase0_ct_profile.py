#!/usr/bin/env python3
"""Phase 0.1 branch-CT signature profiling.

Reads long-format egauge dumps (ts,nm,w), pivots to a 6s wide frame,
resolves each CT's voltage reference by magnitude (panel_W ~ I_a + I_b),
profiles magnitude / duty / time-of-day / parent correlation / same-panel
co-occurrence, and emits a ranked candidate CT->appliance map.
"""
import json, glob, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CTS = ["I11", "I12", "I21", "I22", "I31", "I32"]
PAIR = {"P1": ("I11", "I12"), "P2": ("I21", "I22"), "P3": ("I31", "I32")}
PANEL_NAME = {"P1": "Panel1 (HVAC)", "P2": "Panel2 (H2O)", "P3": "Panel3 (Kitchen)"}
ON_FLOOR = 40.0        # watts
AMP_ON = 0.35          # amps, presence floor for co-occurrence
TZ = "America/Los_Angeles"

# (on_thr, lo, hi) watts, from appliance_data_updated.txt
BANDS = {
    "heat_pump": (300, 1500, 4000), "solar_pump": (50, 100, 250),
    "water_heater": (500, 2000, 4000), "hair_dryer": (800, 1200, 1800),
    "sprinklers": (50, 100, 300), "bath_lights": (80, 100, 300),
    "dryer": (1000, 4000, 7000), "washing_machine": (50, 200, 2000),
    "dishwasher": (50, 200, 1800), "microwave": (200, 900, 1500),
    "pressure_pump": (200, 500, 1000), "refrigerator": (50, 80, 200),
    "computers": (100, 200, 500), "tv_stereo": (80, 100, 200),
    "vacuum_cleaner": (600, 800, 1200),
}
PANEL_APPLIANCES = {
    "P1": ["heat_pump", "solar_pump"],
    "P2": ["water_heater", "hair_dryer", "sprinklers", "bath_lights"],
    "P3": ["dryer", "washing_machine", "dishwasher", "microwave",
           "pressure_pump", "refrigerator", "computers", "tv_stereo", "vacuum_cleaner"],
}


def load():
    files = sorted(glob.glob(os.path.join(HERE, "raw_par_egauge_kafka_*.csv")))
    frames = [pd.read_csv(f, header=None, names=["ts", "nm", "w"]) for f in files]
    long = pd.concat(frames, ignore_index=True)
    long["ts"] = pd.to_datetime(long["ts"], utc=True)
    wide = long.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean").sort_index()
    w6 = wide.resample("6s").mean()
    for v in ("VrmsA", "VrmsB"):
        if v in w6:
            w6[v] = w6[v].ffill(limit=5)
    return w6


def watts(I, w, vref):
    VA, VB = w["VrmsA"], w["VrmsB"]
    if vref == "A_120":
        return I * VA
    if vref == "B_120":
        return I * VB
    return I * (VA + VB)   # split_240


def classify_vref(coef):
    # coef ~ effective volts*pf tying panel watts to this CT's current
    if coef >= 175:
        return "split_240", 246.0
    return "A_120", 123.0


def tod_profile(series_on, idx_local):
    hrs = idx_local.hour[series_on.values]
    if len(hrs) == 0:
        return np.zeros(24), 0.0, []
    hist = np.bincount(hrs, minlength=24).astype(float)
    hist /= hist.sum()
    # max mass in any contiguous 4h window (concentration)
    ext = np.concatenate([hist, hist[:3]])
    conc = max(ext[i:i + 4].sum() for i in range(24))
    peak_hours = list(np.argsort(hist)[::-1][:4])
    return hist, float(conc), [int(h) for h in peak_hours]


def band_match(med, p90, peak, appl):
    thr, lo, hi = BANDS[appl]
    # overlap of [med, p90] with [lo, hi*1.5], plus peak-in-band bonus
    a0, a1 = med, p90
    b0, b1 = lo, hi * 1.5
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    span = max(a1 - a0, 1.0)
    score = inter / span
    if lo <= peak <= hi * 1.8:
        score += 0.25
    return round(score, 3)


def main():
    w = load()
    idx_local = w.index.tz_convert(TZ)
    for pk, pn in PANEL_NAME.items():
        w[pn + "_absW"] = w[pn].abs()

    # ---- per-panel structure ----
    struct = {}
    for pk, (a, b) in PAIR.items():
        pn = PANEL_NAME[pk]
        y = w[pn + "_absW"]
        Ia, Ib = w[a], w[b]
        m = y.notna() & Ia.notna() & Ib.notna()
        X = np.column_stack([Ia[m].values, Ib[m].values, np.ones(m.sum())])
        coef, *_ = np.linalg.lstsq(X, y[m].values, rcond=None)
        yhat = X @ coef
        ss_res = np.sum((y[m].values - yhat) ** 2)
        ss_tot = np.sum((y[m].values - y[m].mean()) ** 2)
        r2 = 1 - ss_res / ss_tot
        mm = Ia.notna() & Ib.notna()
        ct_corr = float(np.corrcoef(Ia[mm].values, Ib[mm].values)[0, 1])
        both_on = float(((Ia[mm] > AMP_ON) & (Ib[mm] > AMP_ON)).mean())
        a_on = float((Ia[mm] > AMP_ON).mean())
        b_on = float((Ib[mm] > AMP_ON).mean())
        # conditional: P(both on | either on)  -> mutex if low
        either = ((Ia[mm] > AMP_ON) | (Ib[mm] > AMP_ON))
        cond_both = float((((Ia[mm] > AMP_ON) & (Ib[mm] > AMP_ON)).sum()) / max(either.sum(), 1))
        struct[pk] = dict(coef_a=float(coef[0]), coef_b=float(coef[1]),
                          intercept=float(coef[2]), r2=float(r2),
                          ct_corr=ct_corr, both_on=both_on, a_on=a_on, b_on=b_on,
                          cond_both_given_either=cond_both)

    # ---- per-CT profile ----
    rows = []
    for ct in CTS:
        pk = "P" + ct[1]
        a, b = PAIR[pk]
        coef = struct[pk]["coef_a"] if ct == a else struct[pk]["coef_b"]
        vref, vnom = classify_vref(coef)
        pf = round(min(max(coef / vnom, 0.0), 1.10), 3)
        W = watts(w[ct], w, vref)
        I = w[ct]
        on = W > ON_FLOOR
        duty = float(on.mean())
        on_med = float(np.nanmedian(W[on])) if on.any() else 0.0
        on_p90 = float(np.nanpercentile(W[on], 90)) if on.any() else 0.0
        peak = float(np.nanmax(W))
        amp_med = float(np.nanmedian(I[on])) if on.any() else 0.0
        amp_peak = float(np.nanmax(I))
        pn = PANEL_NAME[pk]
        pm = W.notna() & w[pn + "_absW"].notna()
        parent_corr = float(np.corrcoef(W[pm].values, w[pn + "_absW"][pm].values)[0, 1])
        hist, conc, peak_hrs = tod_profile(on, idx_local)
        # band scores within this CT's panel
        scores = {ap: band_match(on_med, on_p90, peak, ap) for ap in PANEL_APPLIANCES[pk]}
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        rows.append(dict(ct=ct, panel=pk, vref=vref, coef=round(coef, 1), pf=pf,
                         duty=round(duty, 4), on_med_W=round(on_med, 1),
                         on_p90_W=round(on_p90, 1), peak_W=round(peak, 1),
                         amp_med=round(amp_med, 2), amp_peak=round(amp_peak, 2),
                         parent_corr=round(parent_corr, 3), tod_conc4h=round(conc, 3),
                         peak_hours=peak_hrs, top1=ranked[0][0], top1_score=ranked[0][1],
                         top2=ranked[1][0], top2_score=ranked[1][1]))

    prof = pd.DataFrame(rows)
    prof.to_csv(os.path.join(HERE, "ct_signature_profile.csv"), index=False)

    # ---- report ----
    print("=" * 78)
    print("PER-PANEL STRUCTURE (panel_W ~ coef_a*I_a + coef_b*I_b + b)")
    print("=" * 78)
    for pk in ("P1", "P2", "P3"):
        s = struct[pk]
        a, b = PAIR[pk]
        print(f"\n{pk} [{PANEL_NAME[pk]}]  R2={s['r2']:.3f}  intercept={s['intercept']:.0f}W")
        print(f"   coef {a}={s['coef_a']:.1f}  coef {b}={s['coef_b']:.1f}   "
              f"(≈effective V*pf: ~123→120V leg, ~246→240V split)")
        print(f"   inter-CT corr={s['ct_corr']:.3f}  P(both on)={s['both_on']:.3f}  "
              f"P(both|either)={s['cond_both_given_either']:.3f}  "
              f"[{a} on {s['a_on']:.2f} | {b} on {s['b_on']:.2f}]")
        if s['cond_both_given_either'] > 0.80 and s['ct_corr'] > 0.85:
            print(f"   >> FLAG: {a}/{b} almost always co-active & correlated -> "
                  f"likely TWO LEGS of one 240V load, not two appliances.")
        elif s['cond_both_given_either'] < 0.10:
            print(f"   >> mutex-like: {a}/{b} rarely co-active -> two distinct loads.")

    print("\n" + "=" * 78)
    print("PER-CT SIGNATURE PROFILE")
    print("=" * 78)
    cols = ["ct", "panel", "vref", "coef", "pf", "duty", "on_med_W", "on_p90_W",
            "peak_W", "amp_peak", "parent_corr", "tod_conc4h", "peak_hours",
            "top1", "top1_score", "top2", "top2_score"]
    with pd.option_context("display.width", 200, "display.max_columns", 40):
        print(prof[cols].to_string(index=False))

    # ---- candidate map ----
    cmap = build_map(prof, struct)
    with open(os.path.join(HERE, "ct_appliance_map.candidate.json"), "w") as f:
        json.dump(cmap, f, indent=2)
    print("\n" + "=" * 78)
    print("CANDIDATE ct_appliance_map (written: ct_appliance_map.candidate.json)")
    print("=" * 78)
    print(json.dumps(cmap, indent=2))


def build_map(prof, struct):
    p = prof.set_index("ct")
    cmap = {}

    def entry(ct, appl, conf, note):
        r = p.loc[ct]
        cmap[ct] = {
            "panel": PANEL_NAME[r["panel"]], "appliance": appl,
            "v_ref": r["vref"], "pf": float(r["pf"]),
            "on_med_W": float(r["on_med_W"]), "peak_W": float(r["peak_W"]),
            "duty": float(r["duty"]), "parent_corr": float(r["parent_corr"]),
            "confidence": conf, "note": note,
        }

    # P1: heat_pump vs solar_pump, or two legs of heat_pump
    a, b = PAIR["P1"]
    s1 = struct["P1"]
    two_leg = s1["cond_both_given_either"] > 0.80 and s1["ct_corr"] > 0.85
    if two_leg:
        entry(a, "heat_pump", "candidate-lowconf",
              "P1 CTs co-active+correlated: likely two legs of 240V heat_pump; solar_pump not separately metered on this CT. WALK-TEST.")
        entry(b, "heat_pump", "candidate-lowconf",
              "second leg of same 240V heat_pump circuit; confirm solar_pump routing on walk-test.")
    else:
        big = a if p.loc[a, "on_med_W"] >= p.loc[b, "on_med_W"] else b
        small = b if big == a else a
        entry(big, "heat_pump", "candidate", "higher-magnitude P1 CT; mutex expected vs solar_pump.")
        entry(small, "solar_pump", "candidate", "lower-magnitude P1 CT; verify 100-250W band + mutex on walk-test.")

    # P2: water_heater = dominant near-continuous; other by TOD/magnitude
    a, b = PAIR["P2"]
    wh = a if (p.loc[a, "duty"] * p.loc[a, "on_med_W"]) >= (p.loc[b, "duty"] * p.loc[b, "on_med_W"]) else b
    other = b if wh == a else a
    entry(wh, "water_heater", "candidate", "dominant P2 load by duty*magnitude; expect 2000-4000W, near-continuous.")
    ro = p.loc[other]
    # resolve other: hair_dryer(daytime,1200-1800,short) vs sprinklers(early-am,100-300) vs bath_lights(80-300,short)
    if ro["on_med_W"] >= 900:
        oa, onote = "hair_dryer", "high-watt short daytime load on P2."
    elif set(ro["peak_hours"]) & {4, 5, 6, 7}:
        oa, onote = "sprinklers", "low-watt early-morning time-locked load on P2."
    else:
        oa, onote = "bath_lights", "low-watt short daily load on P2; distinguish from sprinklers by hour on walk-test."
    entry(other, oa, "candidate-lowconf", onote + " AMBIGUOUS: resolve by walk-test.")

    # P3: dryer = highest peak; other = fridge(high duty,low W) vs washer(bursty)
    a, b = PAIR["P3"]
    dry = a if p.loc[a, "peak_W"] >= p.loc[b, "peak_W"] else b
    other = b if dry == a else a
    entry(dry, "dryer", "candidate", "highest-peak P3 CT (multi-kW); only 240V multi-kW P3 load.")
    ro = p.loc[other]
    if ro["duty"] >= 0.5 and ro["on_med_W"] <= 400:
        oa, onote = "refrigerator", "high-duty low-watt cyclic load on P3."
    elif ro["on_med_W"] >= 500:
        oa, onote = "pressure_pump", "moderate steady P3 load; could also be washing_machine (bursty) - walk-test."
    else:
        oa, onote = "washing_machine", "bursty moderate P3 load; resolve vs refrigerator/pressure_pump on walk-test."
    entry(other, oa, "candidate-lowconf", onote + " Panel-3 has 9 heads on 2 CTs: most stay unmetered.")
    return cmap


if __name__ == "__main__":
    main()
