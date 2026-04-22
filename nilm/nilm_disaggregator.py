#!/usr/bin/env python3
import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("nilm")

ANYLOG_REST_URL = os.environ.get("ANYLOG_REST_URL", "http://127.0.0.1:32149")
ANYLOG_DBMS = "customers"
SOURCE_TABLE = "egauge_kafka"
DEST_TABLE = "nilm_disaggregated"
WINDOW_SIZE = 100

# Appliance watt-range knowledge base: (appliance, w_min, w_max)
APPLIANCE_KB = {
    "Panel1": [
        ("compressor",     1500, 3500),
        ("blower",          300,  500),
        ("standby",           5,   10),
    ],
    "Panel2": [
        ("element",        3000, 4500),
        ("standby",           0,    5),
    ],
    "Panel3": [
        ("fridge",           80,  150),
        ("microwave",      1000, 1200),
        ("dishwasher",      300, 1800),
        ("toaster",         800, 1400),
        ("coffee_maker",    600, 1200),
        ("baseline",         30,   80),
    ],
}

GET_HEADERS = {
    "User-Agent": "AnyLog/1.23",
    "destination": "network",
}

PUT_HEADERS = {
    "User-Agent": "AnyLog/1.23",
    "type": "json",
    "dbms": ANYLOG_DBMS,
    "table": DEST_TABLE,
    "mode": "streaming",
    "Content-Type": "text/plain",
}


def query_circuit(circuit: str) -> list[dict]:
    sql = (
        f"SELECT ts, w FROM {SOURCE_TABLE} "
        f"WHERE nm = '{circuit}' "
        f"ORDER BY ts DESC LIMIT {WINDOW_SIZE}"
    )
    headers = dict(GET_HEADERS)
    headers["command"] = f'run client () sql {ANYLOG_DBMS} format=json "{sql}"'
    try:
        r = requests.get(ANYLOG_REST_URL, headers=headers, timeout=30)
        r.raise_for_status()
        data = json.loads(r.text)
        return data.get("Query", [])
    except Exception as e:
        log.error("Query failed for %s: %s", circuit, e)
        return []


def disaggregate(circuit: str, power_w: float) -> list[dict]:
    appliances = APPLIANCE_KB.get(circuit, [])
    results = []
    remaining = abs(power_w)

    for name, w_min, w_max in sorted(appliances, key=lambda a: -a[1]):
        midpoint = (w_min + w_max) / 2.0
        half_range = (w_max - w_min) / 2.0 + 1.0

        if w_min <= remaining <= w_max:
            state = "ON"
            estimated_w = remaining
            confidence = round(1.0 - abs(remaining - midpoint) / half_range, 3)
            explanation = f"{name} within expected range {w_min}–{w_max}W (reading {remaining:.0f}W)"
            remaining = max(0.0, remaining - estimated_w)
        elif remaining > w_max and circuit == "Panel3":
            # Partial greedy: larger loads absorb up to w_max
            state = "ON"
            estimated_w = w_max
            confidence = 0.7
            explanation = f"{name} saturated at max {w_max}W (total load {abs(power_w):.0f}W)"
            remaining = max(0.0, remaining - estimated_w)
        else:
            state = "OFF"
            estimated_w = 0.0
            dist = min(abs(remaining - w_min), abs(remaining - w_max))
            confidence = round(max(0.3, 1.0 - dist / (midpoint + 1.0)), 3)
            explanation = f"{name} off — reading {remaining:.0f}W outside {w_min}–{w_max}W"

        results.append({
            "appliance": name,
            "state": state,
            "estimated_w": round(estimated_w, 2),
            "confidence": confidence,
            "explanation": explanation,
        })

    return results


def write_result(ts: str, circuit: str, app: dict) -> bool:
    row = {
        "ts": ts,
        "circuit": circuit,
        "appliance": app["appliance"],
        "state": app["state"],
        "estimated_w": app["estimated_w"],
        "confidence": app["confidence"],
        "explanation": app["explanation"],
    }
    try:
        r = requests.put(
            ANYLOG_REST_URL,
            headers=PUT_HEADERS,
            data=json.dumps(row),
            timeout=10,
        )
        return r.status_code in (200, 204)
    except Exception as e:
        log.error("PUT failed: %s", e)
        return False


def run_cycle() -> list[dict]:
    all_results = []
    for circuit in ("Panel1", "Panel2", "Panel3"):
        rows = query_circuit(circuit)
        if not rows:
            log.warning("%s: no data returned", circuit)
            continue

        watts = [abs(float(r["w"])) for r in rows]
        power_w = sum(watts) / len(watts)
        ts = rows[0]["ts"]

        appliance_results = disaggregate(circuit, power_w)

        for app in appliance_results:
            write_result(ts, circuit, app)
            all_results.append({"circuit": circuit, "ts": ts, **app})
            log.info(
                "%-8s  %-14s  %s  est=%.0fW  conf=%.3f",
                circuit,
                app["appliance"],
                app["state"],
                app["estimated_w"],
                app["confidence"],
            )

    return all_results


if __name__ == "__main__":
    log.info("AnyLog: %s", ANYLOG_REST_URL)
    results = run_cycle()
    print(json.dumps(results, indent=2))
