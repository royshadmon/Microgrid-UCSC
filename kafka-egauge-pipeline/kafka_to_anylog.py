# DEPRECATED: AnyLog native Kafka consumer is used instead.
# The run kafka consumer command in local_script.al handles ingestion directly.
# This file is kept for reference only — do not run it.
#!/usr/bin/env python3
import os, json, time, signal, logging, requests
from confluent_kafka import Consumer, KafkaError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("kafka-to-anylog")

KAFKA_BROKER  = os.environ.get("KAFKA_BROKER", "localhost:9092")
KAFKA_TOPIC   = os.environ.get("KAFKA_TOPIC", "egauge-energy")
KAFKA_GROUP   = os.environ.get("KAFKA_GROUP", "anylog-bridge")
ANYLOG_HOST   = os.environ.get("ANYLOG_HOST", "127.0.0.1")
ANYLOG_PORT   = os.environ.get("ANYLOG_PORT", "32149")
ANYLOG_DBMS   = os.environ.get("ANYLOG_DBMS", "customers")
ANYLOG_TABLE  = os.environ.get("ANYLOG_TABLE", "egauge_readings")
BATCH_SIZE    = int(os.environ.get("BATCH_SIZE", "16"))
BATCH_TIMEOUT = float(os.environ.get("BATCH_TIMEOUT", "1.0"))

running = True
def handle_signal(sig, frame):
    global running
    log.info("Shutdown signal received")
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def create_consumer():
    conf = {
        "bootstrap.servers": KAFKA_BROKER,
        "group.id": KAFKA_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
    consumer = Consumer(conf)
    consumer.subscribe([KAFKA_TOPIC])
    log.info("Subscribed to %s @ %s (group=%s)", KAFKA_TOPIC, KAFKA_BROKER, KAFKA_GROUP)
    return consumer

def put_to_anylog(payload):
    url = "http://%s:%s" % (ANYLOG_HOST, ANYLOG_PORT)
    headers = {
        "User-Agent": "AnyLog/1.23",
        "type": "json",
        "dbms": ANYLOG_DBMS,
        "table": ANYLOG_TABLE,
        "mode": "streaming",
        "Content-Type": "text/plain",
    }
    try:
        r = requests.put(url, headers=headers, data=payload, timeout=10)
        return r.status_code == 200
    except requests.exceptions.ConnectionError:
        return False
    except Exception as e:
        log.error("PUT error: %s", e)
        return False

def wait_for_anylog():
    url = "http://%s:%s" % (ANYLOG_HOST, ANYLOG_PORT)
    headers = {"User-Agent": "AnyLog/1.23", "command": "get status"}
    attempt = 0
    while running:
        attempt += 1
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                log.info("AnyLog reachable at %s:%s", ANYLOG_HOST, ANYLOG_PORT)
                return True
        except Exception:
            pass
        if attempt % 10 == 0:
            log.warning("Waiting for AnyLog... (attempt %d)", attempt)
        time.sleep(3)
    return False

def main():
    log.info("Kafka -> AnyLog Bridge")
    log.info("  Kafka:  %s / %s", KAFKA_BROKER, KAFKA_TOPIC)
    log.info("  AnyLog: %s:%s (dbms=%s, table=%s)", ANYLOG_HOST, ANYLOG_PORT, ANYLOG_DBMS, ANYLOG_TABLE)

    if not wait_for_anylog():
        return

    consumer = create_consumer()
    total_ok = 0
    total_fail = 0
    batch = []
    last_log = time.monotonic()

    try:
        while running:
            msg = consumer.poll(timeout=BATCH_TIMEOUT)

            if msg is not None:
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    log.error("Consumer error: %s", msg.error())
                    continue
                batch.append(msg.value().decode("utf-8"))

            if len(batch) >= BATCH_SIZE or (batch and msg is None):
                ok = 0
                fail = 0
                for payload in batch:
                    if put_to_anylog(payload):
                        ok += 1
                    else:
                        fail += 1
                        if fail >= 3:
                            log.error("AnyLog down, pausing 10s...")
                            time.sleep(10)
                            break
                total_ok += ok
                total_fail += fail
                if ok > 0:
                    consumer.commit(asynchronous=False)
                batch = []

            now = time.monotonic()
            if now - last_log > 30:
                log.info("Stats: %d OK, %d FAIL", total_ok, total_fail)
                last_log = now

    except Exception as e:
        log.error("Fatal: %s", e)
    finally:
        if batch:
            for payload in batch:
                if put_to_anylog(payload):
                    total_ok += 1
                else:
                    total_fail += 1
            consumer.commit(asynchronous=False)
        consumer.close()
        log.info("Final: %d OK, %d FAIL", total_ok, total_fail)

if __name__ == "__main__":
    main()
