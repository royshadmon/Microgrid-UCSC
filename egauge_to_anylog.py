#!/usr/bin/env python3
"""
egauge_to_anylog.py
Polls eGauge WebAPI for energy register data and sends to AnyLog via REST PUT.
"""

import json
import time
import requests
from datetime import datetime, timezone
from egauge import webapi

# ── Configuration (fill in before running) ─────────────────────
EGAUGE_URI    = "https://egauge18646.egaug.es"                  # e.g. "https://egauge12345.egaug.es"
EGAUGE_USER   = ""                  # eGauge username
EGAUGE_PASS   = ""                  # eGauge password

ANYLOG_CONN   = "127.0.0.1:32149"
ANYLOG_DBMS   = "customers"
ANYLOG_TABLE  = "egauge_data"
ANYLOG_MODE   = "streaming"

POLL_INTERVAL = 10

NAME_MAP = {
    "VrmsA": "VA",  "VrmsB": "VB",
    "I11": "I11",   "I12": "I12",
    "I21": "I21",   "I22": "I22",
    "I31": "I31",   "I32": "I32",
    "F1": "F1",
    "Grid Power": "GRD",
    "Generac Power": "GEN",
    "Current on Utility Tie": "UT",
    "Shop": "SHP",
    "Panel1 (HVAC)": "HVC",
    "Panel2 (H2O)": "H2O",
    "Panel3 (Kitchen)": "KIT",
}


def connect_egauge():
    dev = webapi.device.Device(EGAUGE_URI, webapi.JWTAuth(EGAUGE_USER, EGAUGE_PASS))
    print("  Connected to eGauge")
    return dev


def fetch(dev):
    resp = dev.get("/register?rate")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payloads = []
    for reg in resp.get("registers", []):
        short = NAME_MAP.get(reg["name"], reg["name"][:3])
        payloads.append({
            "ts": ts,
            "dev": "eg",
            "nm": short,
            "tp": reg.get("type", ""),
            "w": float(reg.get("rate", 0)),
            "kwh": 0.0,
        })
    return payloads


def put_data(payloads):
    headers = {
        "User-Agent":   "AnyLog/1.23",
        "type":         "json",
        "dbms":         ANYLOG_DBMS,
        "table":        ANYLOG_TABLE,
        "mode":         ANYLOG_MODE,
        "Content-Type": "text/plain",
    }
    url = "http://%s" % ANYLOG_CONN
    ok, fail = 0, 0

    for p in payloads:
        try:
            r = requests.put(url, headers=headers, data=json.dumps(p), timeout=30)
            if r.status_code == 200:
                ok += 1
                print("  %-3s | %8.1f W  -> 200 OK" % (p["nm"], p["w"]))
            else:
                fail += 1
                print("  %-3s | %8.1f W  -> %d FAIL" % (p["nm"], p["w"], r.status_code))
        except Exception as e:
            fail += 1
            print("  %-3s | PUT error: %s" % (p["nm"], e))

    return ok, fail


def main():
    print("eGauge -> AnyLog (REST PUT) | Poll: %ds" % POLL_INTERVAL)
    print("Target: %s | DB: %s | Table: %s" % (ANYLOG_CONN, ANYLOG_DBMS, ANYLOG_TABLE))
    dev = connect_egauge()

    while True:
        print("\n[%s]" % datetime.now().strftime("%H:%M:%S"))
        try:
            payloads = fetch(dev)
            ok, fail = put_data(payloads)
            print("  --- %d sent, %d failed ---" % (ok, fail))
        except Exception as e:
            print("  Err: %s" % e)
            try:
                dev = connect_egauge()
            except Exception:
                pass
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
