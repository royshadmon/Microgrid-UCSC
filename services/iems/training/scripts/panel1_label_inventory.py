#!/usr/bin/env python3
"""Inventory Panel 1 labels in nilm_disaggregated across recent partitions.

Outputs services/iems/training/reports/panel1_label_inventory.md.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ANYLOG = "http://127.0.0.1:32149"
DBMS = "customers"
CIRCUIT = "Panel1 (HVAC)"

REPO = Path(__file__).resolve().parents[3].parent
OUT = REPO / "services/iems/training/reports/panel1_label_inventory.md"


def _request(command: str) -> dict:
    req = urllib.request.Request(
        ANYLOG,
        method="GET",
        headers={"User-Agent": "AnyLog/1.23", "command": command},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_tables() -> list[str]:
    req = urllib.request.Request(
        ANYLOG,
        method="GET",
        headers={"User-Agent": "AnyLog/1.23", "command": f"get tables where dbms = {DBMS}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    names = []
    for line in body.splitlines():
        m = re.match(r"\s*\|?\s*(par_\S+)\s*\|", line)
        if m:
            names.append(m.group(1))
        else:
            m2 = re.match(r"\s*\S+\s*\|\s*(par_\S+)\s*\|", line)
            if m2:
                names.append(m2.group(1))
    # Fallback regex catches both first-column and second-column layouts.
    return sorted(set(n for n in names if n.startswith("par_nilm_disaggregated_")))


def recent_partitions(months: int = 3) -> list[str]:
    today = date.today()
    keep = set()
    for k in range(months + 1):
        d = today.replace(day=1) - timedelta(days=30 * k)
        keep.add(d.strftime("%Y_%m"))
    out = []
    for tbl in list_tables():
        m = re.search(r"par_nilm_disaggregated_(\d{4}_\d{2})_", tbl)
        if m and m.group(1) in keep:
            out.append(tbl)
    return out


_ALIAS = re.compile(r"^(.*?)\s+AS\s+(\w+)\s*$", re.IGNORECASE)


def _strip_aliases(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        clean = {}
        for k, v in r.items():
            m = _ALIAS.match(k)
            clean[m.group(2) if m else k] = v
        out.append(clean)
    return out


def sql(query: str) -> list[dict]:
    cmd = f"sql {DBMS} format=json and stat=false \"{query}\""
    data = _request(cmd)
    if isinstance(data, dict) and str(data.get("reply", "")).startswith("Empty data set"):
        return []
    return _strip_aliases(data.get("Query", []))


def per_partition_breakdown(table: str) -> list[dict]:
    # AnyLog SQL does not accept SUM(CASE ...). Run totals and ON-counts separately.
    q_all = (
        "SELECT appliance, COUNT(*) AS rows, "
        "MIN(ts) AS first_ts, MAX(ts) AS last_ts, "
        "AVG(confidence) AS avg_conf, AVG(avg_w) AS avg_panel_w "
        f"FROM {table} WHERE circuit = '{CIRCUIT}' GROUP BY appliance"
    )
    q_on = (
        "SELECT appliance, COUNT(*) AS on_count "
        f"FROM {table} WHERE circuit = '{CIRCUIT}' AND state = 'ON' GROUP BY appliance"
    )
    rows = sql(q_all)
    on_rows = {r["appliance"]: int(r["on_count"]) for r in sql(q_on)}
    for r in rows:
        r["on_count"] = on_rows.get(r["appliance"], 0)
    return rows


def main() -> int:
    partitions = recent_partitions(months=3)
    print(f"[inventory] partitions discovered: {partitions}")

    rows_by_appl: dict[str, dict] = {}
    per_partition_lines: list[str] = []
    for tbl in partitions:
        rows = per_partition_breakdown(tbl)
        if not rows:
            per_partition_lines.append(f"- `{tbl}`: empty for circuit='{CIRCUIT}'")
            continue
        per_partition_lines.append(f"- `{tbl}`: {sum(int(r['rows']) for r in rows)} rows")
        for r in rows:
            a = r["appliance"]
            agg = rows_by_appl.setdefault(
                a,
                {
                    "rows": 0,
                    "on_count": 0,
                    "first_ts": None,
                    "last_ts": None,
                    "conf_sum": 0.0,
                    "panel_w_sum": 0.0,
                },
            )
            n = int(r["rows"])
            on_n = int(r["on_count"] or 0)
            agg["rows"] += n
            agg["on_count"] += on_n
            f_ts = r["first_ts"]
            l_ts = r["last_ts"]
            if f_ts and (agg["first_ts"] is None or f_ts < agg["first_ts"]):
                agg["first_ts"] = f_ts
            if l_ts and (agg["last_ts"] is None or l_ts > agg["last_ts"]):
                agg["last_ts"] = l_ts
            agg["conf_sum"] += float(r["avg_conf"] or 0.0) * n
            agg["panel_w_sum"] += float(r["avg_panel_w"] or 0.0) * n

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Panel 1 — Label inventory")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append("## Partitions surveyed")
    lines.extend(per_partition_lines)
    lines.append("")
    lines.append("## Per-appliance totals across partitions")
    lines.append("")
    lines.append(
        "| appliance | rows | on_rows | on_pct | first_ts | last_ts | avg_conf | avg_panel_w |"
    )
    lines.append("|---|---:|---:|---:|---|---|---:|---:|")
    for a in sorted(rows_by_appl):
        agg = rows_by_appl[a]
        n = agg["rows"] or 1
        on_pct = 100.0 * agg["on_count"] / n
        avg_conf = agg["conf_sum"] / n
        avg_pw = agg["panel_w_sum"] / n
        lines.append(
            f"| `{a}` | {agg['rows']} | {agg['on_count']} | {on_pct:.1f}% | "
            f"{agg['first_ts']} | {agg['last_ts']} | {avg_conf:.3f} | {avg_pw:.1f} |"
        )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    total_rows = sum(a["rows"] for a in rows_by_appl.values())
    lines.append(
        f"Panel 1 carries {len(rows_by_appl)} labeled appliance keys across "
        f"{sum(1 for t in partitions if per_partition_breakdown(t))} active partitions "
        f"for {total_rows} total rows."
    )
    if "heat_pump" not in rows_by_appl:
        lines.append("")
        lines.append("**Warning:** `heat_pump` appliance key is **missing**.")
    if "solar_water_heater_pump" not in rows_by_appl and "solar_pump" not in rows_by_appl:
        lines.append("")
        lines.append(
            "**Warning:** No `solar_water_heater_pump` (or `solar_pump`) appliance key is "
            "present in the labels. Phase 1 acceptance condition requires explicit "
            "treatment of this gap before training."
        )
    OUT.write_text("\n".join(lines) + "\n")
    print(f"[inventory] wrote {OUT}")
    print("[inventory] appliance keys found:", sorted(rows_by_appl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
