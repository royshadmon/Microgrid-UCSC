#!/usr/bin/env python3
"""
egauge_poller.py
Dockerized eGauge → AnyLog continuous poller.
Based on working egauge_to_anylog.py, adds: env config, signal
handling, SQLite fallback buffer, healthcheck heartbeat.
"""

import os, sys, json, time, signal, logging
from datetime import datetime, timezone

import requests
from egauge import webapi
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type,
)
import persistqueue

# ── Config from env (defaults match your current setup) ──────────
EGAUGE_URI    = os.getenv("EGAUGE_URI", "https://egauge18646.egaug.es")
EGAUGE_USER   = os.getenv("EGAUGE_USER", "")
EGAUGE_PASS   = os.getenv("EGAUGE_PASS", "")
ANYLOG_CONN   = os.getenv("ANYLOG_CONN", "127.0.0.1:32149")
ANYLOG_DBMS   = os.getenv("ANYLOG_DBMS", "customers")
ANYLOG_TABLE  = os.getenv("ANYLOG_TABLE", "egauge_data")
ANYLOG_MODE   = os.getenv("ANYLOG_MODE", "streaming")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
DATA_DIR      = os.getenv("DATA_DIR", "/app/data")
LOG_LEVEL     = os.getenv("LOG_LEVEL", "INFO")

HEARTBEAT = os.path.join(DATA_DIR, "heartbeat")
BUFFER_DB = os.path.join(DATA_DIR, "buffer.db")

# ── Your register short-name map ────────────────────────────────
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

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("egauge-poller")

# ── Graceful shutdown ────────────────────────────────────────────
shutdown_flag = False

def handle_signal(signum, _frame):
    global shutdown_flag
    log.info(f"Signal {signum} received, shutting down...")
    shutdown_flag = True

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

# ── SQLite fallback buffer ───────────────────────────────────────
os.makedirs(DATA_DIR, exist_ok=True)
buffer = persistqueue.SQLiteAckQueue(BUFFER_DB, auto_commit=True)

# ── eGauge ───────────────────────────────────────────────────────
def connect_egauge():
    dev = webapi.device.Device(EGAUGE_URI, webapi.JWTAuth(EGAUGE_USER, EGAUGE_PASS))
    log.info(f"Connected to eGauge at {EGAUGE_URI}")
    return dev

def fetch(dev):
    """Poll /register?rate — returns instantaneous watts per register."""
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

# ── AnyLog REST PUT ──────────────────────────────────────────────
ANYLOG_URL = f"http://{ANYLOG_CONN}"
PUT_HEADERS = {
    "User-Agent":   "AnyLog/1.23",
    "type":         "json",
    "dbms":         ANYLOG_DBMS,
    "table":        ANYLOG_TABLE,
    "mode":         ANYLOG_MODE,
    "Content-Type": "text/plain",
}

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
)
def put_single(payload: dict):
    """PUT one record to AnyLog with retry."""
    r = requests.put(ANYLOG_URL, headers=PUT_HEADERS,
                     data=json.dumps(payload), timeout=30)
    r.raise_for_status()

def put_data(payloads):
    """Send all payloads; failures go to SQLite buffer."""
    ok, fail = 0, 0
    for p in payloads:
        try:
            put_single(p)
            ok += 1
            log.info("  %-3s | %8.1f W  -> OK" % (p["nm"], p["w"]))
        except Exception as e:
            fail += 1
            log.warning("  %-3s | buffered (AnyLog err: %s)" % (p["nm"], e))
            buffer.put(json.dumps(p))
    return ok, fail

def flush_buffer():
    """Drain buffered records that piled up while AnyLog was down."""
    flushed = 0
    while buffer.size > 0:
        try:
            raw = buffer.get(block=False)
            payload = json.loads(raw)
            put_single(payload)
            buffer.ack(raw)
            flushed += 1
        except persistqueue.Empty:
            break
        except Exception:
            break   # AnyLog still down, retry next cycle
    if flushed:
        log.info(f"Flushed {flushed} buffered records")

def touch_heartbeat():
    with open(HEARTBEAT, "w") as f:
        f.write(str(time.time()))

# ── Main loop ────────────────────────────────────────────────────
def main():
    log.info("eGauge -> AnyLog (REST PUT) | Poll: %ds" % POLL_INTERVAL)
    log.info("Target: %s | DB: %s | Table: %s" % (ANYLOG_CONN, ANYLOG_DBMS, ANYLOG_TABLE))

    dev = connect_egauge()

    while not shutdown_flag:
        log.info("[%s]" % datetime.now().strftime("%H:%M:%S"))
        try:
            payloads = fetch(dev)
            ok, fail = put_data(payloads)
            log.info("  --- %d sent, %d failed ---" % (ok, fail))
            flush_buffer()
            touch_heartbeat()
        except Exception as e:
            log.error("Poll cycle error: %s" % e, exc_info=True)
            try:
                dev = connect_egauge()
            except Exception:
                pass

        # Sleep in small ticks so SIGTERM is caught fast
        for _ in range(POLL_INTERVAL * 10):
            if shutdown_flag:
                break
            time.sleep(0.1)

    log.info("Shutdown complete.")

if __name__ == "__main__":
    main()
