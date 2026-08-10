#!/usr/bin/env python3
"""Pull the August eGauge+solar overlap window into a training parquet.

The existing consolidated parquet ends 2026-07-20; Solar Assistant only starts
2026-08-03. There was no overlap at all until now. This builds a second,
separate dataset covering only the window where BOTH feeds exist, so solar
features can be trained on without inventing values for the months that predate
the solar feed.

Why a separate dataset rather than appending:
    If solar columns were non-zero only in August and zero for March-July, the
    missingness indicator would perfectly separate August from the rest. The
    network would learn "solar present -> August distribution" and use it as a
    date shortcut instead of learning any solar physics. Training only on the
    overlap window removes that shortcut by construction -- every sample has
    solar.

Usage:
    ANYLOG_HOST=100.119.235.24 python3 pull_august_overlap.py
    ANYLOG_HOST=100.119.235.24 python3 pull_august_overlap.py --start 2026-08-03 --end 2026-08-10
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg2

sys.path.insert(0, "services")

# Read from Postgres, not the AnyLog REST API.
#
# AnyLog's REST path is tuned for recent slices: `ts > NOW() - 30 min` returns
# in ~7s, but a historical 3-hour range took 3-5 MINUTES per chunk and one chunk
# came back malformed with 0 rows. Extracting a week that way projected to 5+
# hours with silent data loss.
#
# The operator writes through to postgres1, which is published on 5432. The
# same 6.2M-row partition counts in 1.5s there. Same data, same node -- just
# not through the query engine.
PG = dict(host=os.environ.get("PG_HOST", "100.119.235.24"),
          port=int(os.environ.get("PG_PORT", "5432")),
          dbname=os.environ.get("PG_DB", "customers"),
          user=os.environ.get("PG_USER", "admin"),
          password=os.environ.get("PG_PASS", "passwd"))


def _connect():
    return psycopg2.connect(connect_timeout=15, **PG)


def _partitions(cur, table: str) -> list[str]:
    cur.execute("""SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' AND table_name LIKE %s
                   ORDER BY table_name""", (f"par_{table}_%",))
    return [r[0] for r in cur.fetchall()]

OUT_DIR = Path("analysis/egauge_consolidation")
SOLAR_DIR = Path("analysis/solar")
STEP_S = int(os.environ.get("STEP_S", "5"))   # server-side downsample, seconds
SOLAR_COLS = ["pv_power", "battery_power", "battery_soc", "grid_power", "load_power"]


def pull_egauge(start: datetime, end: datetime) -> pd.DataFrame:
    """Pull day by day, then downsample in pandas.

    Two earlier approaches failed on this box:
      * one query for the whole week -> streamed ~4M rows, >6 min, and left
        heavy queries competing with the live inference loop;
      * `extract(epoch from ts) %% 5 = 0` server-side -> the expression defeats
        the ts index, forcing a parallel seq scan that ran >10 min.
    A plain BETWEEN on ts uses par_..._ts_index, and a day at a time keeps each
    result set small enough to stream quickly. Downsampling then happens here,
    where it costs nothing.
    """
    frames = []
    with _connect() as c:
        cur = c.cursor()
        parts = _partitions(cur, "energy_readings")
        day = start
        while day < end:
            nxt = min(day + timedelta(days=1), end)
            got = 0
            for part in parts:
                cur.execute(f"SELECT ts, nm, w FROM {part} "
                            "WHERE ts >= %s AND ts < %s ORDER BY ts ASC", (day, nxt))
                rows = cur.fetchall()
                if rows:
                    df = pd.DataFrame(rows, columns=["ts", "channel", "w"])
                    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
                    # keep one sample per channel per STEP_S bucket
                    df = (df.dropna(subset=["ts"])
                            .assign(_b=lambda x: x.ts.dt.floor(f"{STEP_S}s"))
                            .drop_duplicates(subset=["_b", "channel"], keep="last")
                            .drop(columns="_b"))
                    frames.append(df); got += len(df)
            print(f"    {day:%m-%d}: {got:>8,} rows (after {STEP_S}s downsample)", flush=True)
            day = nxt
    if not frames:
        raise SystemExit("no eGauge rows in window")
    d = pd.concat(frames, ignore_index=True)
    d["w"] = pd.to_numeric(d["w"], errors="coerce")
    d = (d.dropna(subset=["ts", "w"])
           .drop_duplicates(subset=["ts", "channel"], keep="last"))
    return d[["ts", "channel", "w"]]


def pull_solar(start: datetime, end: datetime) -> pd.DataFrame:
    with _connect() as c:
        cur = c.cursor()
        frames = []
        for part in _partitions(cur, "solar_data"):
            cur.execute(f"SELECT ts, {', '.join(SOLAR_COLS)} FROM {part} "
                        "WHERE ts >= %s AND ts < %s ORDER BY ts ASC", (start, end))
            rows = cur.fetchall()
            if rows:
                frames.append(pd.DataFrame(rows, columns=["ts"] + SOLAR_COLS))
            print(f"    {part}: {len(rows):>9,} rows", flush=True)
    if not frames:
        raise SystemExit("no solar rows in window")
    s = pd.concat(frames, ignore_index=True)
    s["ts"] = pd.to_datetime(s["ts"], errors="coerce")
    for c_ in SOLAR_COLS:
        s[c_] = pd.to_numeric(s[c_], errors="coerce")
    return (s.dropna(subset=["ts"]).drop_duplicates(subset=["ts"], keep="last")
             .set_index("ts").sort_index())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-03")
    ap.add_argument("--end", default=None)
    a = ap.parse_args()
    start = datetime.fromisoformat(a.start)
    end = datetime.fromisoformat(a.end) if a.end else datetime.utcnow()

    print(f"[1/3] eGauge {start:%Y-%m-%d %H:%M} .. {end:%Y-%m-%d %H:%M}", flush=True)
    e = pull_egauge(start, end)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_e = OUT_DIR / "egauge_august_overlap.parquet"
    e.to_parquet(out_e)
    piv = e.pivot_table(index="ts", columns="channel", values="w", aggfunc="first")
    print(f"      {len(e):,} rows -> {piv.shape[0]:,} timestamps x {piv.shape[1]} channels")
    print(f"      span {piv.index.min()} .. {piv.index.max()}")
    print(f"      wrote {out_e}")

    print("[2/3] solar", flush=True)
    s = pull_solar(start, end)
    SOLAR_DIR.mkdir(parents=True, exist_ok=True)
    out_s = SOLAR_DIR / "solar_august_overlap.parquet"
    s.to_parquet(out_s)
    hrs = (s.index.max() - s.index.min()).total_seconds() / 3600
    print(f"      {len(s):,} rows, {hrs:.1f} h, span {s.index.min()} .. {s.index.max()}")
    print(f"      wrote {out_s}")

    print("[3/3] overlap", flush=True)
    lo = max(piv.index.min(), s.index.min())
    hi = min(piv.index.max(), s.index.max())
    ov_h = (hi - lo).total_seconds() / 3600
    joined = s.reindex(piv.index, method="ffill")
    cov = float(joined["pv_power"].notna().mean()) * 100
    print(f"      overlap window : {lo} .. {hi}  ({ov_h:.1f} h)")
    print(f"      solar coverage : {cov:.1f}% of eGauge timestamps")
    print(f"      gate           : {'MET' if ov_h >= 336 else 'NOT MET'} "
          f"(pull_solar_parquet.py wants >= 336 h; have {ov_h:.0f} h)")


if __name__ == "__main__":
    main()
