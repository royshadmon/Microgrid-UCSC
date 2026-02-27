#!/usr/bin/env python3
"""
egauge_to_anylog.py
Polls eGauge WebAPI for energy register data and publishes to AnyLog via MQTT.
"""

import json
import time
import random
from datetime import datetime, timezone
from egauge import webapi
from paho.mqtt import client as mqtt_client

# ── Configuration (fill in before running) ─────────────────────
EGAUGE_URI  = ""  # e.g. "https://egauge12345.egaug.es"
EGAUGE_USER = ""  # eGauge username
EGAUGE_PASS = ""  # eGauge password
MQTT_BROKER = ""  # e.g. "127.0.0.1"
MQTT_PORT   = 1883
MQTT_TOPIC  = "egauge/energy"
POLL_INTERVAL = 10

# ── Register name mapping (raw name -> short name ≤3 chars) ───
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
    """Authenticate with eGauge device via JWT and return device handle."""
    dev = webapi.device.Device(EGAUGE_URI, webapi.JWTAuth(EGAUGE_USER, EGAUGE_PASS))
    print("  Connected to eGauge")
    return dev


def fetch(dev):
    """Fetch instantaneous register readings via GET /register?rate.
    Maps raw names to short names and returns list of JSON payloads."""
    resp = dev.get("/register?rate")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payloads = []
    for reg in resp.get("registers", []):
        short = NAME_MAP.get(reg["name"], reg["name"][:3])
        payloads.append({
            "ts": ts, "dev": "eg", "nm": short,
            "tp": reg.get("type", ""),
            "w": float(reg.get("rate", 0)),
            "kwh": 0.0
        })
    return payloads


def publish(payloads):
    """Publish each reading as JSON to AnyLog MQTT broker with QoS 1."""
    c = mqtt_client.Client(client_id="eg-%d" % random.randint(0, 9999))
    c.connect(host=MQTT_BROKER, port=MQTT_PORT)
    for p in payloads:
        c.publish(topic=MQTT_TOPIC, payload=json.dumps(p), qos=1)
        print("  %-3s | %8.1f W" % (p["nm"], p["w"]))
    c.disconnect()


def main():
    """Poll loop: fetch eGauge data every POLL_INTERVAL seconds, publish to AnyLog.
    Auto-reconnects on JWT expiry or network errors."""
    print("eGauge -> AnyLog | Poll: %ds" % POLL_INTERVAL)
    dev = connect_egauge()
    while True:
        print("\n[%s]" % datetime.now().strftime("%H:%M:%S"))
        try:
            payloads = fetch(dev)
            publish(payloads)
        except Exception as e:
            print("  Err: %s" % e)
            try: dev = connect_egauge()
            except: pass
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
