#!/usr/bin/env python3
"""Solar Assistant -> AnyLog producer.

Subscribes to the Solar Assistant MQTT broker on the local network, keeps the
latest value for each mapped topic, and streams one row per interval into the
AnyLog operator via REST streaming ingestion (same path the Kafka->AnyLog
bridge uses for eGauge). Columns match the solar_data table schema.
"""
import os, json, time, signal, logging, threading
import paho.mqtt.client as mqtt
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("solar-producer")

SA_BROKER   = os.environ.get("SA_BROKER", "192.168.254.48")
SA_PORT     = int(os.environ.get("SA_PORT", "1883"))
SA_USER     = os.environ.get("SA_USER", "")
SA_PASS     = os.environ.get("SA_PASS", "")
SA_PREFIX   = os.environ.get("SA_PREFIX", "solar_assistant")
ANYLOG_HOST = os.environ.get("ANYLOG_HOST", "host.docker.internal")
ANYLOG_PORT = os.environ.get("ANYLOG_PORT", "32149")
ANYLOG_DBMS = os.environ.get("ANYLOG_DBMS", "customers")
ANYLOG_TABLE= os.environ.get("ANYLOG_TABLE", "solar_data")
INTERVAL    = float(os.environ.get("INTERVAL", "5"))
# Ingestion path: "broker" publishes JSON to AnyLog's MQTT broker (AnyLog is the
# broker; a `run msg client` maps topic -> solar_data). "rest" uses streaming PUT.
INGEST_MODE   = os.environ.get("INGEST_MODE", "broker").lower()
AL_BROKER     = os.environ.get("ANYLOG_BROKER", "host.docker.internal")
AL_BROKER_PORT= int(os.environ.get("ANYLOG_BROKER_PORT", "1883"))
AL_TOPIC      = os.environ.get("ANYLOG_TOPIC", "solar")

# "<device>/<metric>" (from <prefix>/<device>/<metric>/state) -> (column, type)
# Aligned to the solar_data schema (energy-balance essentials). Extend here and
# widen the solar_data schema in step to add per-string / energy channels.
MAP = {
    "inverter_1/pv_power":              ("pv_power", float),
    "total/battery_power":              ("battery_power", float),
    "total/battery_state_of_charge":    ("battery_soc", float),
    "inverter_1/grid_power":            ("grid_power", float),
    "inverter_1/load_power":            ("load_power", float),
    "inverter_1/device_mode":           ("device_mode", str),
}

latest = {}
lock = threading.Lock()
running = True

def handle_signal(sig, frame):
    global running
    log.info("Shutdown signal received")
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(SA_PREFIX + "/#")
        log.info("Connected to SA broker %s:%s, subscribed %s/#", SA_BROKER, SA_PORT, SA_PREFIX)
    else:
        log.error("MQTT connect failed rc=%s", rc)

def on_message(client, userdata, msg):
    t = msg.topic
    if not (t.startswith(SA_PREFIX + "/") and t.endswith("/state")):
        return
    suffix = t[len(SA_PREFIX) + 1:-len("/state")]
    if suffix in MAP:
        with lock:
            latest[suffix] = msg.payload.decode("utf-8", "replace")

_al_pub = None  # paho client publishing to the AnyLog broker (broker mode)

def _connect_anylog_broker():
    c = mqtt.Client(client_id="iems-solar-pub")
    c.connect(AL_BROKER, AL_BROKER_PORT, keepalive=60)
    c.loop_start()
    log.info("Publishing to AnyLog broker %s:%s topic=%s", AL_BROKER, AL_BROKER_PORT, AL_TOPIC)
    return c

def put_to_anylog(row):
    payload = json.dumps(row)
    if INGEST_MODE == "rest":
        url = "http://%s:%s" % (ANYLOG_HOST, ANYLOG_PORT)
        headers = {"User-Agent": "AnyLog/1.23", "type": "json", "dbms": ANYLOG_DBMS,
                   "table": ANYLOG_TABLE, "mode": "streaming", "Content-Type": "text/plain"}
        try:
            return requests.put(url, headers=headers, data=payload, timeout=10).status_code == 200
        except Exception as e:
            log.error("PUT error: %s", e); return False
    # broker mode: AnyLog is the MQTT broker; the msg client maps topic->table
    global _al_pub
    try:
        if _al_pub is None:
            _al_pub = _connect_anylog_broker()
        _al_pub.publish(AL_TOPIC, payload, qos=0)
        return True
    except Exception as e:
        log.error("broker publish error: %s", e)
        try: _al_pub = None
        except Exception: pass
        return False

def main():
    log.info("Solar Assistant -> AnyLog producer")
    log.info("  Broker: %s:%s (%s/#)", SA_BROKER, SA_PORT, SA_PREFIX)
    log.info("  AnyLog: %s:%s (dbms=%s, table=%s)", ANYLOG_HOST, ANYLOG_PORT, ANYLOG_DBMS, ANYLOG_TABLE)

    client = mqtt.Client()
    if SA_USER:
        client.username_pw_set(SA_USER, SA_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    while running:
        try:
            client.connect(SA_BROKER, SA_PORT, keepalive=60)
            break
        except Exception as e:
            log.warning("Broker not reachable (%s), retry in 5s", e)
            time.sleep(5)
    client.loop_start()

    total_ok = total_fail = 0
    last_log = time.monotonic()
    nxt = time.time() + INTERVAL
    while running:
        time.sleep(0.5)
        now = time.time()
        if now < nxt:
            continue
        nxt = now + INTERVAL
        with lock:
            snap = dict(latest)
        if not snap:
            continue
        row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        for suffix, (col, typ) in MAP.items():
            row[col] = 0.0 if typ is float else ""
        for suffix, val in snap.items():
            col, typ = MAP[suffix]
            try:
                row[col] = typ(val) if typ is float else val
            except (ValueError, TypeError):
                pass
        if put_to_anylog(row):
            total_ok += 1
        else:
            total_fail += 1
        if time.monotonic() - last_log > 30:
            log.info("Stats: %d OK, %d FAIL (pv=%s soc=%s grid=%s load=%s)",
                     total_ok, total_fail, row.get("pv_power"), row.get("battery_soc"),
                     row.get("grid_power"), row.get("load_power"))
            last_log = time.monotonic()

    client.loop_stop()
    client.disconnect()
    log.info("Final: %d OK, %d FAIL", total_ok, total_fail)

if __name__ == "__main__":
    main()
