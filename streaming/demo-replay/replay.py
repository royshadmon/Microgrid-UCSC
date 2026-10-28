#!/usr/bin/env python3
"""Demo replay, a stand-in for the eGauge meter and Solar Assistant.

Reads one scenario from tests/scenarios/output/<DEMO_SCENARIO>/ and plays it
in real time (or faster, DEMO_SPEED) with the timestamps moved to now.
eGauge rows go to Kafka in exactly the shape egauge-producer publishes, and
Solar Assistant rows go to the AnyLog MQTT broker in exactly the shape
solar-producer publishes, so everything downstream runs unchanged. The
scenario loops when it reaches the end.
"""
import csv, json, os, signal, sys, time, logging
from collections import defaultdict
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from confluent_kafka import Producer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("demo-replay")

SCENARIO = os.environ.get("DEMO_SCENARIO", "baseline_normal")
SPEED = max(0.1, float(os.environ.get("DEMO_SPEED", "1")))
ROOT = os.environ.get("SCENARIO_DIR", "/scenarios")
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "kafka:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "egauge-energy")
AL_BROKER = os.environ.get("ANYLOG_BROKER", "host.docker.internal")
AL_PORT = int(os.environ.get("ANYLOG_BROKER_PORT", "1883"))
AL_TOPIC = os.environ.get("ANYLOG_TOPIC", "solar")
DEVICE = os.environ.get("DEMO_DEVICE", "demo")

running = True


def _stop(*_):
    global running
    running = False


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def load():
    base = os.path.join(ROOT, SCENARIO)
    if not os.path.isdir(base):
        have = sorted(os.listdir(ROOT)) if os.path.isdir(ROOT) else []
        log.error("scenario %r not found in %s. Available: %s", SCENARIO, ROOT, ", ".join(have))
        sys.exit(1)
    egauge = defaultdict(list)
    with open(os.path.join(base, "energy_readings.csv")) as f:
        for r in csv.DictReader(f):
            egauge[_parse(r["ts"])].append(r)
    solar = {}
    with open(os.path.join(base, "solar_data.csv")) as f:
        for r in csv.DictReader(f):
            solar[_parse(r["ts"])] = r
    t0 = min(min(egauge), min(solar) if solar else min(egauge))
    t1 = max(max(egauge), max(solar) if solar else max(egauge))
    events = sorted([(t - t0, "e", rows) for t, rows in egauge.items()] +
                    [(t - t0, "s", row) for t, row in solar.items()], key=lambda e: e[0])
    log.info("scenario %s, %d eGauge ticks, %d solar rows, %.0f min, speed x%g",
             SCENARIO, len(egauge), len(solar), (t1 - t0) / 60, SPEED)
    return events, (t1 - t0) + 6


def connect():
    while running:
        try:
            p = Producer({"bootstrap.servers": KAFKA_BROKER, "client.id": "demo-replay",
                          "linger.ms": 50})
            p.list_topics(timeout=10)
            break
        except Exception as e:
            log.warning("Kafka not ready (%s), retry in 5 s", e)
            time.sleep(5)
    m = mqtt.Client(client_id="iems-demo-replay")
    while running:
        try:
            m.connect(AL_BROKER, AL_PORT, keepalive=60)
            m.loop_start()
            break
        except Exception as e:
            log.warning("AnyLog broker %s:%s not ready (%s), retry in 5 s", AL_BROKER, AL_PORT, e)
            time.sleep(5)
    return p, m


def main():
    events, span = load()
    producer, mq = connect()
    loop = 0
    sent_e = sent_s = 0
    while running:
        start = time.time()
        loop += 1
        log.info("loop %d starting", loop)
        for offset, kind, payload in events:
            if not running:
                break
            due = start + offset / SPEED
            while running and time.time() < due:
                time.sleep(min(0.5, due - time.time()))
            # Real time stamps, so the dashboard and the models see live data.
            now = datetime.now(timezone.utc)
            if kind == "e":
                ts = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                for r in payload:
                    msg = {"ts": ts, "dev": DEVICE, "nm": r["nm"], "tp": r.get("tp") or "P",
                           "w": float(r["w"] or 0), "kwh": float(r.get("kwh") or 0)}
                    producer.produce(KAFKA_TOPIC, key=msg["nm"], value=json.dumps(msg))
                producer.poll(0)
                sent_e += 1
            else:
                row = {"ts": now.strftime("%Y-%m-%d %H:%M:%S")}
                for k in ("pv_power", "battery_power", "battery_soc", "grid_power", "load_power"):
                    try:
                        row[k] = float(payload.get(k) or 0)
                    except ValueError:
                        row[k] = 0.0
                row["device_mode"] = payload.get("device_mode") or ""
                mq.publish(AL_TOPIC, json.dumps(row), qos=0)
                sent_s += 1
            if (sent_e + sent_s) % 100 == 0:
                log.info("sent %d eGauge ticks and %d solar rows", sent_e, sent_s)
        # pad to the scenario length before looping
        rest = start + span / SPEED - time.time()
        if running and rest > 0:
            time.sleep(rest)
    producer.flush(10)
    mq.loop_stop()
    log.info("stopped")


if __name__ == "__main__":
    main()
