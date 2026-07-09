#!/usr/bin/env python3
"""Phase 1: pull panels + branch-leg CTs + voltages -> data/raw_pivot_ct.parquet.

Additive to pull_data.py (left untouched). Per Phase 0 the six I-channels are the
split-phase mains legs of each sub-panel, so besides raw per-leg watts this derives
the physically meaningful per-panel features:
  bal240_p{1,2,3}   = min(I_a,I_b)*(VrmsA+VrmsB)    measured 240V load
  imbal120_p{1,2,3} = |I_a*VrmsA - I_b*VrmsB|        net 120V leg load
Panels keep the abs() sign-normalization; currents and voltages are left raw.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from pull_data import PG   # reuse credentials, no drift

REPO = Path(__file__).resolve().parents[3]
TRAIN = REPO / "services/iems/training"
OUT = TRAIN / "data"
MAP = TRAIN / "ct_appliance_map.json"

PANELS = ["Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"]
CTS = ["I11", "I12", "I21", "I22", "I31", "I32"]
VOLTS = ["VrmsA", "VrmsB"]
QA = ["Shop", "Grid Power", "Current on Utility Tie"]   # reference/QA only, not features
ALL_NM = PANELS + CTS + VOLTS + QA
PAIR = {"1": ("I11", "I12"), "2": ("I21", "I22"), "3": ("I31", "I32")}


def pull_pg(channels):
    import psycopg2
    conn = psycopg2.connect(connect_timeout=5, **PG)
    cur = conn.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE tablename LIKE 'par_egauge_kafka_%' ORDER BY tablename")
    parts = [r[0] for r in cur.fetchall()]
    print("[pull_ct] partitions:", parts)
    nmf = "','".join(channels)
    frames = []
    for tbl in parts:
        try:
            q = f"SELECT ts, nm, w FROM {tbl} WHERE nm IN ('{nmf}') ORDER BY ts"
            df = pd.read_sql(q, conn, parse_dates=["ts"])
            print(f"  {tbl}: {len(df)} rows")
            frames.append(df)
        except Exception as e:
            print(f"  SKIP {tbl}: {e}")
    conn.close()
    return pd.concat(frames, ignore_index=True) if frames else None


def assemble(raw):
    raw = raw.dropna(subset=["ts", "nm", "w"]).drop_duplicates(subset=["ts", "nm"])
    piv = raw.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean").sort_index()
    for c in PANELS:                      # sign-normalize the panels ONLY
        if c in piv:
            piv[c] = piv[c].abs()
    piv = piv.resample("6s").mean().ffill(limit=5)
    if piv.index.tz is None:              # PG returns naive UTC; match raw_pivot.parquet
        piv.index = piv.index.tz_localize("UTC")
    return piv


def vref_map():
    d = json.load(open(MAP))
    return {ct: d["legs"][ct]["v_ref"] for ct in CTS}


def derive(piv, vref):
    VA, VB = piv["VrmsA"], piv["VrmsB"]
    legvolt = {"A_120": VA, "B_120": VB}
    for ct in CTS:
        v = legvolt.get(vref[ct], VA + VB)   # split_240 -> both legs
        piv[ct + "_W"] = piv[ct] * v
    for p, (a, b) in PAIR.items():
        Ia, Ib = piv[a], piv[b]
        piv[f"bal240_p{p}"] = np.minimum(Ia, Ib) * (VA + VB)
        piv[f"imbal120_p{p}"] = (Ia * VA - Ib * VB).abs()
    return piv


def main():
    t0 = time.time()
    raw = pull_pg(ALL_NM)
    if raw is None or raw.empty:
        print("[pull_ct] FATAL: no data from PG", file=sys.stderr)
        return 1
    piv = assemble(raw)
    missing = [c for c in ALL_NM if c not in piv.columns]
    if missing:
        print("[pull_ct] WARNING missing channels:", missing)
    if not all(v in piv for v in VOLTS + CTS):
        print("[pull_ct] FATAL: CT/voltage channels absent — wrong window?", file=sys.stderr)
        return 1
    piv = derive(piv, vref_map())
    outp = OUT / "raw_pivot_ct.parquet"
    piv.to_parquet(outp)

    # ---- Phase 1.2 verification ----
    print(f"\n[pull_ct] saved {outp}  shape={piv.shape}  in {time.time() - t0:.1f}s")
    print(f"[pull_ct] range {piv.index.min()} -> {piv.index.max()}  cadence "
          f"{piv.index.to_series().diff().dt.total_seconds().median():.1f}s")
    print(f"[pull_ct] columns ({len(piv.columns)}): {list(piv.columns)}")
    cov = (piv[CTS].notna().mean() * 100).round(1)
    print(f"[pull_ct] CT non-null %:\n{cov.to_string()}")
    low = [c for c in CTS if piv[c].notna().mean() < 0.90]
    print(f"[pull_ct] >> CTs under 90% coverage: {low if low else 'none'}")
    print("\n[pull_ct] per-leg I##_W percentiles (W):")
    print(piv[[c + '_W' for c in CTS]].describe(percentiles=[.5, .9, .99]).round(0).to_string())
    print("\n[pull_ct] derived per-panel features (W):")
    dcols = [f"bal240_p{p}" for p in PAIR] + [f"imbal120_p{p}" for p in PAIR]
    print(piv[dcols].describe(percentiles=[.5, .9, .99]).round(0).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
