#!/usr/bin/env python3
"""Pull ~60 days of egauge_kafka panel data and pivot to wide format.

Primary path: PostgreSQL (operator pg-compat on 127.0.0.1:5432).
Secondary path: AnyLog REST on 127.0.0.1:32149.
Fallback: reload from data/panel1_60d.parquet on disk if both endpoints
          are down (the existing 35-day pivot already has Panel1/2/3
          columns — re-resample to 6s and we're done).

Output: services/iems/training/data/raw_pivot.parquet
  index: 6s-resampled UTC timestamps
  columns: "Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "services/iems/training/data"
OUT.mkdir(parents=True, exist_ok=True)

PG = dict(host="127.0.0.1", port=5432, dbname="customers",
          user="demo", password="passwd")
ANYLOG = "http://127.0.0.1:32149"

TARGET_NM = ["Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"]
FALLBACK = REPO / "data/panel1_60d.parquet"


# ── Path A: Postgres ───────────────────────────────────────────────────
def pull_pg() -> pd.DataFrame | None:
    try:
        import psycopg2
    except ImportError:
        print("[pull] psycopg2 not installed — skipping PG path")
        return None
    try:
        conn = psycopg2.connect(connect_timeout=5, **PG)
    except Exception as e:
        print(f"[pull] PG unavailable: {e}")
        return None

    cur = conn.cursor()
    cur.execute(
        "SELECT tablename FROM pg_tables "
        "WHERE tablename LIKE 'par_egauge_kafka_%' ORDER BY tablename"
    )
    partitions = [r[0] for r in cur.fetchall()]
    if not partitions:
        print("[pull] PG returned no egauge_kafka partitions")
        conn.close()
        return None
    print(f"[pull] PG partitions: {partitions}")

    nm_filter = "','".join(TARGET_NM)
    parts = []
    for tbl in partitions:
        try:
            q = (
                f"SELECT ts, nm, w FROM {tbl} "
                f"WHERE nm IN ('{nm_filter}') ORDER BY ts"
            )
            df = pd.read_sql(q, conn, parse_dates=["ts"])
            print(f"  {tbl}: {len(df)} rows")
            parts.append(df)
        except Exception as e:
            print(f"  SKIP {tbl}: {e}")
    conn.close()
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True)


# ── Path B: AnyLog REST ────────────────────────────────────────────────
def _al_sql(query: str, timeout: int = 60) -> list[dict]:
    cmd = f"sql customers format=json and stat=false \"{query}\""
    req = urllib.request.Request(
        ANYLOG, method="GET",
        headers={"User-Agent": "AnyLog/1.23", "command": cmd},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data, dict) and str(data.get("reply", "")).startswith("Empty data set"):
        return []
    return data.get("Query", [])


def pull_anylog() -> pd.DataFrame | None:
    # Probe three recent partitions (current + 2 prior months).
    now = datetime.now(timezone.utc)
    months = []
    cur = now.replace(day=1)
    for _ in range(3):
        months.append(cur.strftime("%Y_%m"))
        cur = (cur - timedelta(days=1)).replace(day=1)
    partitions = [f"par_egauge_kafka_{ym}_00_d14_insert_timestamp" for ym in months]

    nm_filter = "','".join(TARGET_NM)
    parts = []
    for tbl in partitions:
        try:
            rows = _al_sql(
                f"SELECT ts, nm, w FROM {tbl} "
                f"WHERE nm IN ('{nm_filter}') ORDER BY ts"
            )
            print(f"  {tbl}: {len(rows)} rows")
            if rows:
                df = pd.DataFrame(rows)
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                df["w"] = pd.to_numeric(df["w"], errors="coerce")
                parts.append(df)
        except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError) as e:
            print(f"  SKIP {tbl}: {e}")
            # If even one partition fails, AnyLog is likely down.
            return None
    return pd.concat(parts, ignore_index=True) if parts else None


# ── Path C: reload existing parquet (last-resort) ──────────────────────
def pull_fallback() -> pd.DataFrame | None:
    if not FALLBACK.exists():
        return None
    print(f"[pull] reading fallback {FALLBACK}")
    wide = pd.read_parquet(FALLBACK)
    # Existing extract used short column names; map back to channel labels.
    inv = {"panel1_w": "Panel1 (HVAC)",
           "panel2_w": "Panel2 (H2O)",
           "panel3_w": "Panel3 (Kitchen)"}
    cols = {short: long for short, long in inv.items() if short in wide.columns}
    if not cols:
        print(f"[pull] fallback lacks panel columns: {list(wide.columns)}")
        return None
    long = wide[list(cols.keys())].rename(columns=cols)
    # Reverse-pivot to (ts, nm, w) so the same downstream pipeline works.
    long.index.name = "ts"
    out = long.stack().rename("w").reset_index().rename(columns={"nm": "nm"})
    out.columns = ["ts", "nm", "w"]
    return out


# ── Combine and resample ───────────────────────────────────────────────
def assemble(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.dropna(subset=["ts", "nm", "w"]).copy()
    raw = raw.drop_duplicates(subset=["ts", "nm"])
    pivot = raw.pivot_table(index="ts", columns="nm", values="w", aggfunc="mean")
    pivot = pivot.sort_index()
    # eGauge sub-panel meters report consumption as negative; normalize sign.
    for c in TARGET_NM:
        if c in pivot.columns:
            pivot[c] = pivot[c].abs()
    # 6 s resample (matches LLM4NILM / MATNilm convention).
    pivot = pivot.resample("6s").mean().ffill(limit=5)
    return pivot


def pull() -> int:
    t0 = time.time()
    print(f"[pull] target channels: {TARGET_NM}")
    raw = pull_pg()
    if raw is None:
        print("[pull] PG path failed → trying AnyLog REST")
        raw = pull_anylog()
    if raw is None:
        print("[pull] AnyLog path failed → falling back to local parquet")
        raw = pull_fallback()
    if raw is None or raw.empty:
        print("[pull] FATAL: no data from any source", file=sys.stderr)
        return 1

    pivot = assemble(raw)
    out_path = OUT / "raw_pivot.parquet"
    pivot.to_parquet(out_path)
    elapsed = time.time() - t0
    print(f"[pull] saved {out_path}  shape={pivot.shape}  in {elapsed:.1f}s")
    print(f"[pull] date range: {pivot.index.min()} → {pivot.index.max()}")
    print(f"[pull] columns: {list(pivot.columns)}")
    print(f"[pull] non-null %:\n{(pivot.notna().mean() * 100).round(1)}")
    return 0


if __name__ == "__main__":
    sys.exit(pull())
