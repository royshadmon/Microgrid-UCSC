#!/usr/bin/env python3
"""CamAL-style DUAL labelling for the BiLSTM: STRONG + WEAK label sets, each
with its own per-sample weight, so the model can parse and cross-check twice.

Rationale (Petralia et al. 2025, "Few Labels are all you need", ICDE):
  * STRONG = per-timestamp on/off. Expensive, and for coupled loads it is
    fabricated rather than known -> circular supervision.
  * WEAK   = one label per WINDOW ("did X run in this 4 h block?"). Cheap and,
    critically, still RELIABLE for coupled loads: you can tell a dryer cycle
    happened in an afternoon even when you cannot pin the minute or separate a
    simultaneous microwave.
CamAL shows weak labels reach comparable localization accuracy with 100-5000x
fewer labels. Here we emit BOTH so the BiLSTM gets a strong target where the
signature is unambiguous and a weak target everywhere else.

Outputs (per panel):
  labels_strong_<panel>.parquet   {1,0,NaN} per appliance, per timestamp
  weights_strong_<panel>.parquet  [0,1] per appliance, per timestamp
  labels_weak_<panel>.parquet     {1,0}   per appliance, per 4h window
  weights_weak_<panel>.parquet    [0,1]   per appliance, per 4h window

Weight semantics (consumed by the weighted loss):
  1.00  measured ground truth (CT)
  ~conf temporal-signature confirmed, non-coupled
  0.25  rule-only / coupled guess  -> heavily down-weighted, never trusted
  0.00  abstain (NaN label)
"""
from __future__ import annotations
import sys, os
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import temporal_rule_engine as tre

WEAK_WINDOW   = "4h"
STRONG_CONF   = 0.50   # min event conf to emit a STRONG positive
WEAK_CONF     = 0.30   # min event conf to emit a WEAK positive
W_MEASURED    = 1.00
W_RULE_ONLY   = 0.25   # rule/coupled guess: present but distrusted
W_ABSTAIN     = 0.00

PANEL_OF = {a: s.panel for a, s in tre.SIGNATURES.items()}
MEASURED = {"heat_pump": "bal240_p1", "water_heater": "bal240_p2"}


def _panel_frame(piv):
    df = pd.DataFrame(index=pd.DatetimeIndex(piv.index))
    for pn, col in tre.PANEL_COL.items():
        if pn in piv.columns:
            df[col] = piv[pn].values
    for b in ("bal240_p1", "bal240_p2", "bal240_p3"):
        if b in piv.columns:
            df[b] = piv[b].values
    return df


def dual_label(df, weak_window=WEAK_WINDOW):
    """Return (strong_labels, strong_weights, weak_labels, weak_weights)."""
    apps = list(tre.SIGNATURES)
    idx = df.index

    # ---------- STRONG: per-timestamp ----------
    S = pd.DataFrame(np.nan, index=idx, columns=apps, dtype="float32")
    SW = pd.DataFrame(W_ABSTAIN, index=idx, columns=apps, dtype="float32")

    ev = tre.classify(df)

    for a in apps:
        sig = tre.SIGNATURES[a]
        ser = tre.series(df, sig.panel, sig.measure).reindex(idx)
        # OFF baseline: clearly below the band floor.
        # FIX 2: heads flagged no_confident_off (water_heater) never get a
        # confident 0 from band absence - the element rarely fires, so silence
        # is not evidence of OFF.
        if not sig.no_confident_off:
            off = ser < sig.w[0] * 0.6
            S.loc[off, a] = 0.0
            SW.loc[off, a] = W_RULE_ONLY

    if not ev.empty:
        for _, e in ev.iterrows():
            a = e["appliance"]
            span = (idx >= e["start"]) & (idx <= e["end"])
            if e["coupled"]:
                # coupled -> STRONG is unreliable. Mark ON but distrust it.
                S.loc[span, a] = 1.0
                SW.loc[span, a] = W_RULE_ONLY
            elif e["conf"] >= STRONG_CONF:
                S.loc[span, a] = 1.0
                SW.loc[span, a] = float(e["conf"])

    # measured heads override everything (real CT ground truth)
    for a, bal in MEASURED.items():
        if bal in df.columns and a in S.columns:
            m = df[bal].abs()
            on = m > 300.0
            S[a] = np.where(m.notna(), on.astype("float32"), np.nan)
            SW[a] = np.where(m.notna(), W_MEASURED, W_ABSTAIN)

    SW[S.isna()] = W_ABSTAIN

    # ---------- WEAK: per-window presence ----------
    win = idx.floor(weak_window)
    uw = pd.DatetimeIndex(sorted(set(win)))
    W = pd.DataFrame(0.0, index=uw, columns=apps, dtype="float32")
    WW = pd.DataFrame(0.0, index=uw, columns=apps, dtype="float32")

    if not ev.empty:
        e2 = ev.copy()
        e2["win"] = e2["start"].dt.floor(weak_window)
        for (w0, a), g in e2.groupby(["win", "appliance"]):
            if w0 not in W.index:
                continue
            mc = float(g["conf"].max())
            if mc >= WEAK_CONF:
                W.loc[w0, a] = 1.0
                # weak labels stay trustworthy even for coupled loads: knowing
                # the appliance ran SOMEWHERE in a 4 h block does not require
                # separating it from a simultaneous load.
                WW.loc[w0, a] = mc
    # windows with no event -> negative, moderately trusted
    for a in apps:
        neg = W[a] == 0.0
        WW.loc[neg, a] = W_RULE_ONLY
    # measured heads: weak label from the CT signal directly
    for a, bal in MEASURED.items():
        if bal in df.columns and a in W.columns:
            on_any = (df[bal].abs() > 300.0).groupby(win).max()
            W[a] = on_any.reindex(uw).fillna(0).astype("float32")
            WW[a] = W_MEASURED

    return S, SW, W, WW


def summarize(S, SW, W, WW):
    rows = []
    for a in S.columns:
        lab = S[a]
        rows.append(dict(
            appliance=a, panel=PANEL_OF.get(a, "?")[:8],
            strong_n=int(lab.notna().sum()),
            strong_pos=int((lab == 1).sum()),
            strong_pos_rate=float((lab == 1).mean() * 100),
            mean_w=float(SW[a][lab.notna()].mean()) if lab.notna().any() else 0.0,
            trusted=int((SW[a] >= 0.5).sum()),
            weak_windows=int(len(W)),
            weak_fired=int((W[a] == 1).sum()),
        ))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    OUT = "services/iems/training/data"
    src = sys.argv[1] if len(sys.argv) > 1 else \
        "analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet"
    print(f"[1/4] loading {src} ...", flush=True)
    d = pd.read_parquet(src, columns=["ts", "channel", "w"])
    print(f"      {len(d):,} rows", flush=True)
    print("[2/4] pivoting to per-timestamp frame ...", flush=True)
    piv = d.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
    print(f"      {len(piv):,} timestamps x {piv.shape[1]} channels", flush=True)
    df = _panel_frame(piv)
    print("[3/4] dual labelling (strong + weak) ...", flush=True)
    S, SW, W, WW = dual_label(df)
    print("[4/4] writing ...", flush=True)
    S.to_parquet(f"{OUT}/labels_strong_all.parquet")
    SW.to_parquet(f"{OUT}/weights_strong_all.parquet")
    W.to_parquet(f"{OUT}/labels_weak_all.parquet")
    WW.to_parquet(f"{OUT}/weights_weak_all.parquet")
    summ = summarize(S, SW, W, WW)
    summ.to_csv(f"{OUT}/dual_label_summary.csv", index=False)
    print(summ.to_string(index=False), flush=True)
    print("DONE", flush=True)
