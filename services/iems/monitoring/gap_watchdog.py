#!/usr/bin/env python3
"""Data-gap watchdog. 70 of 136 archive days are missing, including a 46-day
hole; every one of those gaps was discovered weeks late. This catches the next
one the day it starts.

Checks the freshest timestamp per channel and alerts when any channel has been
silent longer than --max-gap-min (default 15).

Sources, in order of preference:
  1. live Postgres (energy_readings) via the docker postgres1 container
  2. the consolidated parquet (--parquet), for offline/cron use

Exit code 0 = all fresh, 1 = gap detected, 2 = source unreachable.
Cron example (checks every 10 min, mails on gap):
  */10 * * * * cd ~/microgrid-manager && .venv-training/bin/python3 \
      services/iems/monitoring/gap_watchdog.py || echo "IEMS data gap" | mail -s "IEMS gap" you@ucsc.edu
"""
from __future__ import annotations
import argparse, subprocess, sys
from datetime import datetime, timezone

CHANNELS = ["Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"]

def from_postgres():
    q = ("SELECT channel, max(ts) FROM energy_readings "
         "WHERE channel = ANY(%s) GROUP BY channel;")
    cmd = ["docker", "exec", "-e", "PGPASSWORD=passwd", "postgres1",
           "psql", "-U", "demo", "-d", "customers", "-t", "-A", "-F", "|",
           "-c", ("SELECT channel, max(ts) FROM energy_readings "
                  "GROUP BY channel;")]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    rows = {}
    for line in out.stdout.strip().splitlines():
        if "|" in line:
            ch, ts = line.split("|", 1)
            rows[ch.strip()] = datetime.fromisoformat(ts.strip())
    return rows

def from_parquet(path):
    import pandas as pd
    d = pd.read_parquet(path, columns=["ts", "channel"])
    g = d.groupby("channel")["ts"].max()
    return {ch: pd.Timestamp(t).to_pydatetime() for ch, t in g.items()}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-gap-min", type=float, default=15.0)
    ap.add_argument("--parquet",
        default="analysis/egauge_consolidation/egauge_consolidated_all_eras.parquet")
    ap.add_argument("--offline", action="store_true",
        help="skip Postgres, check the parquet only")
    a = ap.parse_args()
    rows = None
    if not a.offline:
        try:
            rows = from_postgres()
            src = "postgres"
        except Exception as e:
            print(f"[watchdog] postgres unreachable ({e}); falling back to parquet")
    if not rows:
        try:
            rows = from_parquet(a.parquet)
            src = "parquet"
        except Exception as e:
            print(f"[watchdog] no source reachable: {e}")
            sys.exit(2)
    now = datetime.now(timezone.utc)
    bad = []
    for ch in CHANNELS:
        t = rows.get(ch)
        if t is None:
            bad.append((ch, "never seen")); continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        gap = (now - t).total_seconds() / 60.0
        state = "OK" if gap <= a.max_gap_min else f"GAP {gap:.0f} min"
        print(f"[watchdog:{src}] {ch:20s} last={t:%Y-%m-%d %H:%M:%S} {state}")
        if gap > a.max_gap_min:
            bad.append((ch, f"{gap:.0f} min"))
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
