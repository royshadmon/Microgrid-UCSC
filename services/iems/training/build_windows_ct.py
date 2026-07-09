#!/usr/bin/env python3
"""Phase 5.1: CT windows for the energy-balance trainer.

Additive: writes data/panel{P}_ct_windows.npz + models/panel{P}_ct_norm.json.
Live panel{P}_windows.npz untouched.

Key differences vs build_windows.py / windows_panel*.py:
  * Segment hygiene: windows are cut ONLY inside contiguous fully-observed runs
    (16.4% CT coverage arrives as clean 6s runs separated by multi-hour dropouts;
    windowing across a gap would fabricate transitions).
  * Carries the Phase-3 quantities per window midpoint: panel_kw, measured_kw
    (PF-corrected bal240), and the CT-anchored regression targets + residual.
  * Event-stratified split: contiguous ON-runs of the measured head are assigned
    whole to train/val/test, so no single compressor run straddles a split.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
TRAIN = REPO / "services/iems/training"
DATA = TRAIN / "data"
MODELS = REPO / "services/iems/models"
sys.path.insert(0, str(TRAIN))
from reg_targets_ct import build_targets, panel_pf, PANEL_HEADS, MEASURED_240, MASKED_240  # noqa

WINDOW, STRIDE, MID = 100, 10, 50
MIN_SEG = WINDOW + STRIDE
PANEL_COL = {1: "Panel1 (HVAC)", 2: "Panel2 (H2O)", 3: "Panel3 (Kitchen)"}
LABEL_KEY = {1: "Panel1_HVAC", 2: "Panel2_H2O", 3: "Panel3_Kitchen"}
BAL = {1: "bal240_p1", 2: "bal240_p2", 3: "bal240_p3"}
IMB = {1: "imbal120_p1", 2: "imbal120_p2", 3: "imbal120_p3"}
SEED = 7


def feature_frame(piv, P):
    f = pd.DataFrame(index=piv.index)
    f["panel1_w"] = piv["Panel1 (HVAC)"]
    f["panel2_w"] = piv["Panel2 (H2O)"]
    f["panel3_w"] = piv["Panel3 (Kitchen)"]
    f["shop_w"] = piv["Shop"]
    f["utility_tie_current"] = piv["Current on Utility Tie"]
    f["bal240_p"] = piv[BAL[P]]
    f["imbal120_p"] = piv[IMB[P]]
    f[f"panel{P}_w_step"] = piv[PANEL_COL[P]].diff().fillna(0.0)
    f["bal240_step"] = piv[BAL[P]].diff().fillna(0.0)
    loc = piv.index.tz_convert("America/Los_Angeles")
    hour = loc.hour + loc.minute / 60.0
    f["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    f["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    f["dow_sin"] = np.sin(2 * np.pi * loc.dayofweek / 7)
    f["dow_cos"] = np.cos(2 * np.pi * loc.dayofweek / 7)
    return f


def segments(observed):
    """Contiguous runs of True, as (start, stop) index pairs."""
    idx = np.flatnonzero(observed.values)
    if len(idx) == 0:
        return []
    brk = np.flatnonzero(np.diff(idx) != 1)
    starts = np.r_[idx[0], idx[brk + 1]]
    stops = np.r_[idx[brk], idx[-1]] + 1
    return [(s, e) for s, e in zip(starts, stops) if e - s >= MIN_SEG]


def event_ids(lab_on):
    """Contiguous ON-run id per sample; -1 where OFF/NaN."""
    on = (lab_on == 1).values
    ids = np.full(len(on), -1, dtype=np.int64)
    e = 0
    i = 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            ids[i:j] = e
            e += 1
            i = j
        else:
            i += 1
    return ids, e


def stratified_event_split(win_ev, rng, frac=(0.70, 0.15, 0.15)):
    """Assign whole ON-events to splits; negatives split by contiguous block."""
    evs = sorted({int(e) for e in win_ev if e >= 0})
    rng.shuffle(evs)
    n = len(evs)
    # guarantee >=1 event in val and test whenever >=3 events exist, else F1 is undefined
    n_va = max(int(round(frac[1] * n)), 1) if n >= 3 else 0
    n_te = max(int(round(frac[2] * n)), 1) if n >= 3 else 0
    n_tr = max(n - n_va - n_te, 1) if n else 0
    evs = evs[:n_tr] + evs[n_tr:n_tr + n_va] + evs[n_tr + n_va:]
    tr_e = set(evs[:n_tr]); va_e = set(evs[n_tr:n_tr + n_va]); te_e = set(evs[n_tr + n_va:])
    split = np.empty(len(win_ev), dtype="<U5")
    neg = np.flatnonzero(win_ev < 0)
    rng.shuffle(neg)
    a = int(frac[0] * len(neg)); b = a + int(frac[1] * len(neg))
    split[neg[:a]] = "train"; split[neg[a:b]] = "val"; split[neg[b:]] = "test"
    for i, e in enumerate(win_ev):
        if e >= 0:
            split[i] = "train" if e in tr_e else ("val" if e in va_e else "test")
    return split, len(tr_e), len(va_e), len(te_e)


def build_panel(piv, P, pf):
    heads = PANEL_HEADS[P]
    lab = pd.read_parquet(DATA / f"labels_{LABEL_KEY[P]}_ct.parquet")
    f = feature_frame(piv, P)
    feats = list(f.columns)

    panel_w = piv[PANEL_COL[P]]
    bal = piv[BAL[P]]
    tgts, resid, meas_kw = build_targets(panel_w, bal, lab, P, pf)

    observed = f.notna().all(axis=1) & panel_w.notna() & bal.notna()
    segs = segments(observed)
    print(f"[win_ct] P{P}: observed={int(observed.sum())} rows in {len(segs)} usable segments "
          f"(>= {MIN_SEG} samples)")
    if not segs:
        return None

    Fv = f.values.astype(np.float32)
    ts = piv.index.view("int64")
    # measured head for event stratification (P3 has none -> use dryer rule label)
    mh = next((h for h, p in MEASURED_240.items() if p == P), None)
    strat_head = mh if mh else "dryer"
    ev_ids, n_ev = event_ids(lab[strat_head])

    # Window starts: baseline stride grid + DENSE stride-1 starts whose midpoint
    # lands on any head's ON sample. Midpoint labeling at stride 10 otherwise
    # discards most short ON runs (heat_pump lost 10 of 29 events, 0 val/test pos).
    any_on = np.zeros(len(lab), dtype=bool)
    for h in heads:
        any_on |= (lab[h] == 1).values
    starts = []
    for s, e in segs:
        starts.extend(range(s, e - WINDOW + 1, STRIDE))
        lo, hi = s, e - WINDOW + 1
        for m in np.flatnonzero(any_on[s:e]) + s:
            i = m - MID
            if lo <= i < hi:
                starts.append(i)
    starts = sorted(set(starts))

    X, Y, R, PKW, MKW, RES, TS, EV = [], [], [], [], [], [], [], []
    for i in starts:
            m = i + MID
            X.append(Fv[i:i + WINDOW])
            Y.append([lab[h].values[m] for h in heads])
            R.append([tgts[h].values[m] for h in heads])
            PKW.append(panel_w.values[m] / 1000.0)
            MKW.append(meas_kw.values[m])
            RES.append(resid.values[m])
            TS.append(ts[m])
            EV.append(ev_ids[m])   # event of the LABELED midpoint
    X = np.asarray(X, np.float32); Y = np.asarray(Y, np.float32)
    R = np.asarray(R, np.float32)
    PKW = np.asarray(PKW, np.float32); MKW = np.asarray(MKW, np.float32)
    RES = np.asarray(RES, np.float32); TS = np.asarray(TS, np.int64)
    EV = np.asarray(EV, np.int64)

    rng = np.random.default_rng(SEED)
    split, ntr, nva, nte = stratified_event_split(EV, rng)
    print(f"[win_ct] P{P}: windows={len(X)}  strat_head={strat_head} events={n_ev} "
          f"-> train/val/test events {ntr}/{nva}/{nte}")

    out = {}
    for sp in ("train", "val", "test"):
        k = split == sp
        out[f"X_{sp}"] = X[k]
        out[f"ts_{sp}"] = TS[k]
        out[f"panel_kw_{sp}"] = PKW[k]
        out[f"measured_kw_{sp}"] = MKW[k]
        out[f"residual_kw_{sp}"] = RES[k]
        for j, h in enumerate(heads):
            out[f"y_{h}_{sp}"] = Y[k, j]
            out[f"r_{h}_{sp}"] = R[k, j]
    np.savez_compressed(DATA / f"panel{P}_ct_windows.npz", **out)

    tr = out["X_train"]
    mean = tr.reshape(-1, tr.shape[-1]).mean(0)
    std = tr.reshape(-1, tr.shape[-1]).std(0)
    std = np.where(std < 1e-6, 1.0, std)
    (MODELS / f"panel{P}_ct_norm.json").write_text(json.dumps({
        "features": feats, "mean": mean.tolist(), "std": std.tolist(),
        "window": WINDOW, "stride": STRIDE, "mid": MID, "heads": list(heads),
        "measured_heads": [h for h in heads if h in MEASURED_240],
        "masked_heads": [h for h in heads if h in MASKED_240],
    }, indent=2))

    print(f"[win_ct] P{P}: split sizes " +
          ", ".join(f"{sp}={int((split == sp).sum())}" for sp in ("train", "val", "test")))
    for j, h in enumerate(heads):
        line = f"[win_ct]   {h:16s}"
        for sp in ("train", "val", "test"):
            y = out[f"y_{h}_{sp}"]
            line += f" {sp}:pos={int(np.nansum(y == 1)):4d}"
        print(line)
    return out


def main():
    piv = pd.read_parquet(DATA / "raw_pivot_ct.parquet")
    pf = panel_pf()
    print(f"[win_ct] pivot {piv.shape}  PF={pf}")
    for P in (1, 2, 3):
        build_panel(piv, P, pf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
