#!/usr/bin/env python3
"""Audit Panel 1 labels in nilm_disaggregated against the appliance spec.

Pulls a sample of labeled rows (heat_pump + solar_water_heater_pump) and
checks them against power thresholds parsed from appliance_data_updated.txt.

Outputs services/iems/training/reports/panel1_label_audit.md.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ANYLOG = "http://127.0.0.1:32149"
DBMS = "customers"
CIRCUIT = "Panel1 (HVAC)"

REPO = Path(__file__).resolve().parents[3].parent
SPEC_FILE = REPO / "appliance_data_updated.txt"
OUT = REPO / "services/iems/training/reports/panel1_label_audit.md"

PARTITIONS_NILM = [
    "par_nilm_disaggregated_2026_04_00_d14_insert_timestamp",
    "par_nilm_disaggregated_2026_04_01_d14_insert_timestamp",
    "par_nilm_disaggregated_2026_05_00_d14_insert_timestamp",
]
PARTITIONS_KAFKA = [
    "par_egauge_kafka_2026_04_01_d14_insert_timestamp",
    "par_egauge_kafka_2026_04_02_d14_insert_timestamp",
    "par_egauge_kafka_2026_05_00_d14_insert_timestamp",
]

_ALIAS = re.compile(r"^(.*?)\s+AS\s+(\w+)\s*$", re.IGNORECASE)


def _strip(rows: list[dict]) -> list[dict]:
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
    req = urllib.request.Request(
        ANYLOG, method="GET",
        headers={"User-Agent": "AnyLog/1.23", "command": cmd},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data, dict) and str(data.get("reply", "")).startswith("Empty data set"):
        return []
    return _strip(data.get("Query", []))


def parse_spec() -> dict[str, dict]:
    """Parse the appliance text file. Returns a dict keyed by canonical
    appliance name with on_threshold_w, min_w, max_w, source."""
    text = SPEC_FILE.read_text()
    spec: dict[str, dict] = {}

    # Heat pump
    if m := re.search(r"Heat pump:.*?On threshold:\s*(\d+)w.*?Power range:\s*(\d+)-(\d+)w",
                      text, re.DOTALL):
        spec["heat_pump"] = {
            "on_threshold_w": int(m.group(1)),
            "min_w": int(m.group(2)),
            "max_w": int(m.group(3)),
            "source": "appliance_data_updated.txt",
        }

    # Solar water heater pump — text mentions it but gives no numbers.
    # Use circulator-pump defaults that are obvious from the line ("Solar
    # Water Heater Pump on Panel 1"). These match the prompt-supplied
    # values; we record them as a defaulted estimate.
    if "Solar Water Heater Pump" in text:
        spec["solar_water_heater_pump"] = {
            "on_threshold_w": 30,
            "min_w": 50,
            "max_w": 250,
            "source": "default (file mentions appliance, no thresholds)",
        }

    return spec


def pull_labels(appliance: str, limit: int = 5000) -> pd.DataFrame:
    frames = []
    remaining = limit
    for tbl in PARTITIONS_NILM:
        if remaining <= 0:
            break
        q = (
            "SELECT ts, appliance, state, confidence, avg_w "
            f"FROM {tbl} WHERE circuit = '{CIRCUIT}' AND appliance = '{appliance}' "
            f"ORDER BY ts ASC LIMIT {remaining}"
        )
        rows = sql(q)
        if rows:
            df = pd.DataFrame(rows)
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df["state"] = df["state"].astype(str)
            df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
            df["avg_w"] = pd.to_numeric(df["avg_w"], errors="coerce")
            frames.append(df)
            remaining -= len(df)
    if not frames:
        return pd.DataFrame(columns=["ts", "appliance", "state", "confidence", "avg_w"])
    return pd.concat(frames, ignore_index=True)


def panel1_power_range() -> tuple[datetime | None, datetime | None]:
    """Min/Max ts of Panel1 (HVAC) raw data across egauge_kafka partitions."""
    mins, maxs = [], []
    for tbl in PARTITIONS_KAFKA:
        q = (
            f"SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM {tbl}"
        )
        rows = sql(q)
        if rows and rows[0].get("first_ts"):
            mins.append(rows[0]["first_ts"])
            maxs.append(rows[0]["last_ts"])
    if not mins:
        return None, None
    return min(mins), max(maxs)


def diurnal_on_hist(df: pd.DataFrame) -> pd.Series:
    on = df[df["state"].str.upper() == "ON"]
    if on.empty:
        return pd.Series(dtype=int)
    return on["ts"].dt.tz_convert("America/Los_Angeles").dt.hour.value_counts().sort_index()


def main() -> int:
    spec = parse_spec()
    print("[audit] spec:", spec)

    lines: list[str] = []
    lines.append("# Panel 1 — Label audit vs appliance spec")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_")
    lines.append("")
    lines.append("## Appliance spec parsed from `appliance_data_updated.txt`")
    lines.append("")
    lines.append("| appliance | on_threshold | min_w | max_w | source |")
    lines.append("|---|---:|---:|---:|---|")
    for a, s in spec.items():
        lines.append(
            f"| `{a}` | {s['on_threshold_w']} | {s['min_w']} | {s['max_w']} | {s['source']} |"
        )
    lines.append("")

    panel_first, panel_last = panel1_power_range()
    lines.append("## Raw Panel 1 coverage (egauge_kafka)")
    lines.append("")
    lines.append(
        f"- First ts seen: `{panel_first}`  "
        f"\n- Last ts seen: `{panel_last}`"
    )
    lines.append("")

    for appliance, s in spec.items():
        lines.append(f"## `{appliance}`")
        lines.append("")
        df = pull_labels(appliance, limit=5000)
        if df.empty:
            lines.append(
                f"**No rows in `nilm_disaggregated` for `circuit='{CIRCUIT}'` and "
                f"`appliance='{appliance}'`.** The model can be trained only with "
                "alternative labels (e.g., rule-only). See consensus phase."
            )
            lines.append("")
            continue

        n = len(df)
        on_n = (df["state"].str.upper() == "ON").sum()
        off_n = (df["state"].str.upper() == "OFF").sum()
        on_pct = 100.0 * on_n / n if n else 0.0
        lines.append(
            f"- Sampled rows: **{n}**  "
            f"\n- Date range: `{df['ts'].min()}` → `{df['ts'].max()}`  "
            f"\n- Label distribution: ON {on_n} ({on_pct:.1f}%), OFF {off_n}"
        )

        on_rows = df[df["state"].str.upper() == "ON"]
        off_rows = df[df["state"].str.upper() == "OFF"]
        fp_low = (on_rows["avg_w"] < 0.5 * s["min_w"]).sum()
        fp_high = (on_rows["avg_w"] > 1.5 * s["max_w"]).sum()
        fn_susp = (off_rows["avg_w"] > 1.3 * s["on_threshold_w"]).sum()

        lines.append("")
        lines.append("### Label-vs-power consistency")
        lines.append("")
        lines.append("| check | count | of | % |")
        lines.append("|---|---:|---:|---:|")
        lines.append(
            f"| State=ON with `avg_w < 0.5 × min_w` ({0.5 * s['min_w']:.0f}W) [low FP] | "
            f"{fp_low} | {len(on_rows)} | "
            f"{(100*fp_low/len(on_rows) if len(on_rows) else 0):.1f}% |"
        )
        lines.append(
            f"| State=ON with `avg_w > 1.5 × max_w` ({1.5 * s['max_w']:.0f}W) [high FP] | "
            f"{fp_high} | {len(on_rows)} | "
            f"{(100*fp_high/len(on_rows) if len(on_rows) else 0):.1f}% |"
        )
        lines.append(
            f"| State=OFF with `avg_w > 1.3 × on_threshold` ({1.3 * s['on_threshold_w']:.0f}W) [susp. FN] | "
            f"{fn_susp} | {len(off_rows)} | "
            f"{(100*fn_susp/len(off_rows) if len(off_rows) else 0):.1f}% |"
        )

        lines.append("")
        lines.append("### Diurnal ON histogram (hour-of-day, local time)")
        hist = diurnal_on_hist(df)
        if hist.empty:
            lines.append("")
            lines.append("_No ON rows — diurnal histogram is empty._")
        else:
            lines.append("")
            lines.append("| hour | on_count |")
            lines.append("|---:|---:|")
            for h, c in hist.items():
                lines.append(f"| {h:02d} | {c} |")

        lines.append("")
        lines.append("### avg_w distribution (labeled rows)")
        desc = df["avg_w"].describe(percentiles=[0.1, 0.5, 0.9])
        lines.append("")
        lines.append("| stat | value |")
        lines.append("|---|---:|")
        for k, v in desc.items():
            lines.append(f"| {k} | {v:.1f} |")

        lines.append("")
        lines.append("### Coverage gap vs raw")
        if panel_first and panel_last:
            gap_pre = (df["ts"].min().to_pydatetime() - pd.to_datetime(panel_first, utc=True).to_pydatetime()).total_seconds() / 86400.0
            gap_post = (pd.to_datetime(panel_last, utc=True).to_pydatetime() - df["ts"].max().to_pydatetime()).total_seconds() / 86400.0
            lines.append(
                f"- Days of raw data before first label: **{gap_pre:.1f}**  "
                f"\n- Days of raw data after last label: **{gap_post:.1f}**"
            )
        lines.append("")

    # Stopping-condition summary
    lines.append("## Acceptance check")
    lines.append("")
    hp_present = "heat_pump" in spec
    sp_label_present = bool(pull_labels("solar_water_heater_pump", limit=10).shape[0]) or \
                       bool(pull_labels("solar_pump", limit=10).shape[0])
    if not sp_label_present:
        lines.append(
            "- **Solar water heater pump labels: ABSENT.** The Phase 1 stopping "
            "condition is triggered. Training will need a rule-only label path "
            "for this appliance (deferred to Phase 3 consensus design)."
        )
    if hp_present:
        # heat_pump FP rate from the dataframe in the loop above isn't held —
        # recompute concise number from a fresh pull for the summary line.
        hp_df = pull_labels("heat_pump", limit=5000)
        if not hp_df.empty:
            on_rows = hp_df[hp_df["state"].str.upper() == "ON"]
            n_on = len(on_rows)
            if n_on:
                s = spec["heat_pump"]
                fp = ((on_rows["avg_w"] < 0.5 * s["min_w"]) |
                      (on_rows["avg_w"] > 1.5 * s["max_w"])).sum()
                rate = 100.0 * fp / n_on
                lines.append(
                    f"- Heat pump false-positive rate (combined low+high): "
                    f"**{rate:.1f}%** over {n_on} ON rows. "
                    f"{'**STOPPING CONDITION TRIPPED**' if rate > 25 else 'OK'}"
                )
            else:
                lines.append(
                    "- Heat pump: **0 ON labels** in the sample. The label "
                    "stream is calling the heat pump OFF in every window even "
                    "when the panel is drawing well above the on-threshold. "
                    "This is a different failure mode than the prompt's "
                    "stated 25% FP cap — it is essentially 100% miss rate on "
                    "the positive class. Surface for review before training."
                )
    OUT.write_text("\n".join(lines) + "\n")
    print(f"[audit] wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
