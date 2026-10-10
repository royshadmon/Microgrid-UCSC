#!/usr/bin/env python3
import os, sys, json, time, signal, logging
from datetime import datetime, timezone
from confluent_kafka import Producer
from egauge import webapi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("egauge-producer")

EGAUGE_URI    = os.environ.get("EGAUGE_URI", "")
EGAUGE_USER   = os.environ.get("EGAUGE_USER", "owner")
EGAUGE_PASS   = os.environ.get("EGAUGE_PASS", "")
KAFKA_BROKER  = os.environ.get("KAFKA_BROKER", "localhost:9092")
KAFKA_TOPIC   = os.environ.get("KAFKA_TOPIC", "egauge-energy")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "1"))

running = True
def handle_signal(sig, frame):
    global running
    log.info("Shutdown signal received")
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

# ── hang guards ───────────────────────────────────────────────────────────────
# The eGauge client library issues its HTTP calls without a timeout, so a meter
# blip mid-read blocks this loop forever while PID 1 stays alive and Docker keeps
# reporting the container Up. That happened on 2026-08-29, 2026-09-01 and again
# on 2026-09-03, the last one costing twenty hours of readings. Two guards:
#   1. a default (connect, read) timeout injected into every requests call, since
#      the library gives no way to pass one through, and
#   2. a watchdog that exits the process when no poll has completed within
#      WATCHDOG_SECONDS, leaving `restart: unless-stopped` to bring it back.
import threading
import requests

HTTP_TIMEOUT  = (int(os.environ.get("EGAUGE_CONNECT_TIMEOUT", "5")),
                 int(os.environ.get("EGAUGE_READ_TIMEOUT", "10")))
WATCHDOG_SECS = int(os.environ.get("WATCHDOG_SECONDS", "120"))

_orig_session_request = requests.Session.request
def _request_with_timeout(self, method, url, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = HTTP_TIMEOUT
    return _orig_session_request(self, method, url, **kw)
requests.Session.request = _request_with_timeout

_last_poll = [time.monotonic()]

def _watchdog():
    while running:
        time.sleep(10)
        stalled = time.monotonic() - _last_poll[0]
        if stalled > WATCHDOG_SECS:
            log.error("Watchdog: no completed poll in %.0f s, exiting for restart", stalled)
            os._exit(1)

def create_producer():
    return Producer({
        "bootstrap.servers": KAFKA_BROKER,
        "client.id": "egauge-producer",
        "acks": "all",
        "linger.ms": 5,
        "batch.num.messages": 16,
        "retries": 5,
        "retry.backoff.ms": 200,
        "enable.idempotence": True,
    })

def delivery_cb(err, msg):
    if err:
        log.error("DELIVERY FAIL [%s]: %s", msg.key(), err)

def connect_egauge():
    if not EGAUGE_URI or not EGAUGE_PASS:
        log.error("EGAUGE_URI and EGAUGE_PASS required")
        sys.exit(1)
    dev = webapi.device.Device(EGAUGE_URI, webapi.JWTAuth(EGAUGE_USER, EGAUGE_PASS))
    log.info("eGauge connected: %s", EGAUGE_URI)
    return dev

def poll_and_produce(dev, producer):
    resp = dev.get("/register?rate")
    ts_float = float(resp.get("ts", "0"))
    ts_iso = datetime.fromtimestamp(ts_float, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    device_id = EGAUGE_URI.split("//")[-1].split(".")[0]
    registers = resp.get("registers", [])
    for reg in registers:
        msg = {
            "ts":  ts_iso,
            "dev": device_id,
            "nm":  reg.get("name", "unknown"),
            "tp":  reg.get("type", "P"),
            "w":   float(reg.get("rate", 0)),
            "kwh": 0.0
        }
        producer.produce(topic=KAFKA_TOPIC, key=msg["nm"], value=json.dumps(msg), callback=delivery_cb)
    producer.poll(0)
    return len(registers)

def main():
    log.info("eGauge -> Kafka | broker=%s topic=%s interval=%ds", KAFKA_BROKER, KAFKA_TOPIC, POLL_INTERVAL)
    dev = connect_egauge()
    producer = create_producer()
    threading.Thread(target=_watchdog, daemon=True).start()
    log.info("Watchdog armed: exit if no poll completes within %d s", WATCHDOG_SECS)
    poll_count = 0
    error_streak = 0
    while running:
        t0 = time.monotonic()
        try:
            n = poll_and_produce(dev, producer)
            _last_poll[0] = time.monotonic()
            poll_count += 1
            error_streak = 0
            if poll_count % 60 == 0:
                log.info("Poll #%d | %d regs | %d msg/min", poll_count, n, n * 60)
        except Exception as e:
            error_streak += 1
            log.error("Poll error #%d: %s", error_streak, e)
            if error_streak >= 3:
                try:
                    dev = connect_egauge()
                    error_streak = 0
                except Exception:
                    pass
            if error_streak >= 5:
                time.sleep(min(error_streak * 2, 30))
                continue
        elapsed = time.monotonic() - t0
        time.sleep(max(0, POLL_INTERVAL - elapsed))
    producer.flush(timeout=10)
    log.info("Done. Total polls: %d", poll_count)

if __name__ == "__main__":
    main()
