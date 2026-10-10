#!/usr/bin/env python3
"""Replay producer: plays real eGauge + Solar Assistant data from Pat's house
into the GX10 stack as if the meter were live.

It is a drop-in stand-in for streaming/kafka-egauge-pipeline/egauge_kafka_producer.py
and streaming/solar-pipeline/solar_producer.py. Every message has exactly the
shape the real producers emit, only the timestamp is rewritten to "now", so
Kafka, the AnyLog operator, the inference loop and every dashboard run
unchanged. Nothing downstream can tell it is a replay.

Sources (first one found wins)
  1. $REPLAY_DIR/egauge_1s/*.csv.gz   raw 1 s readings   (pat_export_remote.sh)
  2. $REPLAY_DIR/egauge_6s/*.csv.gz   6 s grid, held for 6 ticks
  3. synthetic                        built-in generator, for bring-up only

Time alignment
  ALIGN=tod (default) starts the replay at the source sample whose local
  time of day matches the GX10's local time of day. The inference features
  tod_sin/tod_cos, sun_elev and csky_ghi are computed from the *output*
  timestamp, so a noon heat-pump trace replayed at 9 pm would contradict
  them. ALIGN=start plays from the first sample.

Speed
  SPEED=1 is real time. SPEED=N advances the source clock N seconds per wall
  second (samples in between are skipped), which time-lapses a day for a
  demo. Output timestamps are always wall-clock now.

Backfill
  BACKFILL_MINUTES=15 (default) first publishes the 15 minutes of source data
  that precede the start point, stamped with the matching past wall-clock
  times. The models read a 10 minute window (100 samples x 6 s), so the first
  inference tick after start already has a full window instead of waiting ten
  minutes for one to fill.

Control API (HTTP, CONTROL_PORT, default 8099)
  GET  /status
  POST /speed?x=10
  POST /jump?to=18:30            jump the source clock to a local time of day
  POST /inject?channel=Panel2%20(H2O)&watts=3500&seconds=300
                                 add a synthetic load on top of the replay,
                                 e.g. to show the water-heater head firing
  POST /clear                    drop all injections
"""
from __future__ import annotations

import glob
import gzip
import csv
import json
import logging
import math
import os
import random
import signal
import threading
import time
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("replay-producer")

REPLAY_DIR    = os.environ.get("REPLAY_DIR", "/data")
KAFKA_BROKER  = os.environ.get("KAFKA_BROKER", "kafka:9092")
KAFKA_TOPIC   = os.environ.get("KAFKA_TOPIC", "egauge-energy")
DEVICE_ID     = os.environ.get("DEVICE_ID", "egauge18646")
SPEED         = float(os.environ.get("SPEED", "1"))
ALIGN         = os.environ.get("ALIGN", "tod")
HOUSE_TZ      = ZoneInfo(os.environ.get("HOUSE_TZ", "America/Los_Angeles"))
SOLAR_ENABLE  = os.environ.get("SOLAR_ENABLE", "1") == "1"
SOLAR_EVERY   = float(os.environ.get("SOLAR_INTERVAL", "5"))
ANYLOG_URL    = os.environ.get("ANYLOG_URL", "http://operator1:32149")
ANYLOG_DBMS   = os.environ.get("ANYLOG_DBMS", "customers")
SOLAR_TABLE   = os.environ.get("SOLAR_TABLE", "solar_data")
CONTROL_PORT  = int(os.environ.get("CONTROL_PORT", "8099"))
DRY_RUN       = os.environ.get("DRY_RUN", "0") == "1"
BACKFILL_MIN  = float(os.environ.get("BACKFILL_MINUTES", "15"))

# eGauge register type letters, as /register?rate reports them
def reg_type(name: str) -> str:
    if name.startswith("Vrms"):
        return "V"
    if name == "F1":
        return "F"
    if name.startswith("Current") or (name[:1] == "I" and name[1:].isdigit()):
        return "I"
    return "P"


# ── data loading ─────────────────────────────────────────────────────────
class Track:
    """Time-ordered source frames: ts_list[i] -> {channel: w}."""

    def __init__(self, ts_list, frames, step_s, label):
        self.ts = ts_list
        self.frames = frames
        self.step = step_s
        self.label = label

    @property
    def span(self) -> float:
        return (self.ts[-1] - self.ts[0]).total_seconds() + self.step

    def at(self, t: datetime) -> dict:
        """Sample-and-hold lookup at source time t (wraps around)."""
        off = (t - self.ts[0]).total_seconds() % self.span
        t = self.ts[0] + timedelta(seconds=off)
        i = bisect_left(self.ts, t)
        if i >= len(self.ts) or (self.ts[i] > t and i > 0):
            i -= 1
        return self.frames[max(i, 0)]


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def load_egauge(sub: str, step: float) -> Track | None:
    files = sorted(glob.glob(os.path.join(REPLAY_DIR, sub, "*.csv.gz")))
    if not files:
        return None
    by_ts: dict[datetime, dict] = {}
    for f in files:
        with gzip.open(f, "rt", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    by_ts.setdefault(_parse(row["ts"]), {})[row["channel"]] = float(row["w"])
                except (KeyError, ValueError):
                    continue
    if not by_ts:
        return None
    ts = sorted(by_ts)
    # forward-fill channels missing from a frame so every tick is complete
    chans = sorted({c for fr in by_ts.values() for c in fr})
    last = {c: 0.0 for c in chans}
    frames = []
    for t in ts:
        last.update(by_ts[t])
        frames.append(dict(last))
    log.info("loaded %s: %d frames, %d channels, %s -> %s (%d files)",
             sub, len(ts), len(chans), ts[0], ts[-1], len(files))
    return Track(ts, frames, step, sub)


def load_solar() -> Track | None:
    for f in (os.path.join(REPLAY_DIR, "solar.csv.gz"),):
        if not os.path.exists(f):
            continue
        ts, frames = [], []
        with gzip.open(f, "rt", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    t = _parse(row["ts"])
                except (KeyError, ValueError):
                    continue
                fr = {}
                for k in ("pv_power", "battery_power", "battery_soc", "grid_power", "load_power"):
                    try:
                        fr[k] = float(row[k])
                    except (KeyError, ValueError, TypeError):
                        pass
                fr["device_mode"] = row.get("device_mode") or ""
                ts.append(t); frames.append(fr)
        if ts:
            order = sorted(range(len(ts)), key=ts.__getitem__)
            ts = [ts[i] for i in order]; frames = [frames[i] for i in order]
            log.info("loaded solar: %d rows, %s -> %s", len(ts), ts[0], ts[-1])
            return Track(ts, frames, SOLAR_EVERY, "solar")
    return None


class Synthetic:
    """Plausible house so the stack can be brought up before the export lands."""
    label = "synthetic"
    step = 1.0

    def __init__(self):
        self.rng = random.Random(0)

    def at(self, t: datetime) -> dict:
        s = t.timestamp()
        lt = t.astimezone(HOUSE_TZ)
        hour = lt.hour + lt.minute / 60
        fridge = 140 if (s % 1800) < 720 else 4
        hp = 2600 if 6 <= hour < 9 or 17 <= hour < 22 and (s % 2400) < 1500 else 0
        wh = 3800 if 7 <= hour < 7.4 or 19 <= hour < 19.3 else 0
        p1 = hp + self.rng.uniform(-40, 40) + 25
        p2 = wh + 60 + self.rng.uniform(-10, 10)
        p3 = 180 + fridge + (1100 if 18 <= hour < 18.25 else 0) + self.rng.uniform(-20, 20)
        shop = 15
        sun = max(0.0, math.sin(math.pi * (hour - 6.5) / 13)) if 6.5 < hour < 19.5 else 0.0
        load = p1 + p2 + p3 + shop
        grid = load - 5200 * sun
        v = 121 + self.rng.uniform(-0.6, 0.6)
        return {
            "Panel1 (HVAC)": -p1, "Panel2 (H2O)": -p2, "Panel3 (Kitchen)": -p3, "Shop": shop,
            "Grid Power": grid, "Generac Power": 0.0, "VrmsA": v, "VrmsB": v + 0.4,
            "F1": 60 + self.rng.uniform(-0.01, 0.01),
            "I11": p1 / 240, "I12": p1 / 240, "I21": p2 / 240, "I22": p2 / 240,
            "I31": p3 / 240, "I32": p3 / 240, "Current on Utility Tie": abs(grid) / 240,
        }

    def solar(self, t: datetime) -> dict:
        fr = self.at(t)
        lt = t.astimezone(HOUSE_TZ)
        hour = lt.hour + lt.minute / 60
        sun = max(0.0, math.sin(math.pi * (hour - 6.5) / 13)) if 6.5 < hour < 19.5 else 0.0
        load = sum(abs(fr[k]) for k in ("Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)", "Shop"))
        return {"pv_power": round(5200 * sun), "battery_power": 0.0, "battery_soc": 90.0,
                "grid_power": round(load - 5200 * sun), "load_power": round(load),
                "device_mode": "Solar first"}


# ── replay state ─────────────────────────────────────────────────────────
class State:
    def __init__(self, track, solar):
        self.track = track
        self.solar = solar
        self.speed = SPEED
        self.lock = threading.Lock()
        self.injections: list[dict] = []
        self.sent = 0
        self.wall0 = time.time()
        self.src0 = self._initial_source_time()

    def _initial_source_time(self) -> datetime:
        if not isinstance(self.track, Track):
            return datetime.now(timezone.utc)
        first = self.track.ts[0]
        if ALIGN != "tod":
            return first
        return self._tod_in_track(datetime.now(HOUSE_TZ).time())

    def _tod_in_track(self, tod) -> datetime:
        """First source instant whose house-local time of day equals tod."""
        first = self.track.ts[0].astimezone(HOUSE_TZ)
        cand = first.replace(hour=tod.hour, minute=tod.minute, second=tod.second, microsecond=0)
        if cand < first:
            cand += timedelta(days=1)
        cand = cand.astimezone(timezone.utc)
        if cand > self.track.ts[-1]:
            cand = self.track.ts[0]
        return cand

    def source_now(self) -> datetime:
        with self.lock:
            el = (time.time() - self.wall0) * self.speed
            return self.src0 + timedelta(seconds=el)

    def set_speed(self, x: float):
        with self.lock:
            now_src = self.src0 + timedelta(seconds=(time.time() - self.wall0) * self.speed)
            self.src0, self.wall0, self.speed = now_src, time.time(), max(0.1, min(x, 3600.0))

    def jump(self, hhmm: str):
        h, m = (int(x) for x in hhmm.split(":")[:2])
        from datetime import time as dtime
        target = self._tod_in_track(dtime(h, m)) if isinstance(self.track, Track) \
            else datetime.now(timezone.utc)
        with self.lock:
            self.src0, self.wall0 = target, time.time()

    def frame(self, src: datetime | None = None) -> dict:
        fr = dict(self.track.at(src or self.source_now()))
        now = time.time()
        with self.lock:
            self.injections = [j for j in self.injections if j["until"] > now]
            for j in self.injections:
                ch = j["channel"]
                base = fr.get(ch, 0.0)
                # panels report consumption as negative watts on this site
                sign = -1.0 if base < 0 or ch.startswith("Panel") else 1.0
                fr[ch] = base + sign * j["watts"]
                if "Grid Power" in fr:
                    fr["Grid Power"] = fr["Grid Power"] + j["watts"]
        return fr

    def solar_row(self) -> dict | None:
        if isinstance(self.solar, Track):
            # Solar history and the eGauge replay days need not overlap (Solar
            # Assistant stopped writing on 2026-09-30). Shift the source instant
            # by whole days into the solar range, so the sun position and the
            # time of day still agree with the eGauge trace being replayed.
            src = self.source_now()
            lo, hi = self.solar.ts[0], self.solar.ts[-1]
            if src > hi:
                src -= timedelta(days=math.ceil((src - hi) / timedelta(days=1)))
            elif src < lo:
                src += timedelta(days=math.ceil((lo - src) / timedelta(days=1)))
            return dict(self.solar.at(src))
        if isinstance(self.track, Synthetic):
            return self.track.solar(self.source_now())
        return None


# ── outputs ──────────────────────────────────────────────────────────────
def make_producer():
    if DRY_RUN:
        return None
    from confluent_kafka import Producer
    return Producer({"bootstrap.servers": KAFKA_BROKER, "client.id": "replay-producer",
                     "acks": "all", "linger.ms": 5, "enable.idempotence": True})


def wait_for_kafka(producer):
    if producer is None:
        return
    for i in range(60):
        try:
            producer.list_topics(timeout=5)
            log.info("Kafka reachable at %s", KAFKA_BROKER)
            return
        except Exception as e:  # noqa: BLE001
            log.info("waiting for Kafka (%s) ...", e)
            time.sleep(2)


def put_solar(row: dict):
    if DRY_RUN:
        log.info("solar %s", row)
        return
    headers = {"User-Agent": "AnyLog/1.23", "type": "json", "dbms": ANYLOG_DBMS,
               "table": SOLAR_TABLE, "mode": "streaming", "Content-Type": "text/plain"}
    try:
        requests.put(ANYLOG_URL, headers=headers, data=json.dumps(row), timeout=5)
    except requests.RequestException as e:
        log.warning("solar PUT failed: %s", e)


def control_server(st: State):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

        def do_GET(self):
            src = st.source_now()
            self._send(200, {
                "source": st.track.label, "speed": st.speed, "sent": st.sent,
                "source_time_utc": src.isoformat(),
                "source_time_local": src.astimezone(HOUSE_TZ).isoformat(),
                "injections": st.injections, "solar": bool(st.solar_row()),
            })

        def do_POST(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/speed":
                    st.set_speed(float(q["x"]))
                elif u.path == "/jump":
                    st.jump(q["to"])
                elif u.path == "/inject":
                    with st.lock:
                        st.injections.append({"channel": q["channel"], "watts": float(q["watts"]),
                                              "until": time.time() + float(q.get("seconds", 300))})
                elif u.path == "/clear":
                    with st.lock:
                        st.injections.clear()
                else:
                    return self._send(404, {"error": "unknown path"})
            except (KeyError, ValueError) as e:
                return self._send(400, {"error": str(e)})
            self.do_GET()

    srv = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("control API on :%d", CONTROL_PORT)


running = True


def main():
    def stop(*_):
        global running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    track = load_egauge("egauge_1s", 1.0) or load_egauge("egauge_6s", 6.0)
    if track is None:
        log.warning("no export under %s, using the synthetic generator", REPLAY_DIR)
        track = Synthetic()
    solar = load_solar() if SOLAR_ENABLE else None

    st = State(track, solar)
    control_server(st)
    producer = make_producer()
    wait_for_kafka(producer)
    log.info("replaying %s at %.1fx into %s/%s, source clock starts %s local",
             track.label, st.speed, KAFKA_BROKER, KAFKA_TOPIC,
             st.source_now().astimezone(HOUSE_TZ).strftime("%Y-%m-%d %H:%M:%S"))

    if BACKFILL_MIN > 0:
        n = int(BACKFILL_MIN * 60)
        now_wall, now_src = time.time(), st.source_now()
        for k in range(n, 0, -1):
            t_wall = now_wall - k
            src = now_src - timedelta(seconds=k * st.speed)
            ts_iso = datetime.fromtimestamp(t_wall, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            for nm, w in st.frame(src).items():
                if producer is not None:
                    producer.produce(KAFKA_TOPIC, key=nm, value=json.dumps(
                        {"ts": ts_iso, "dev": DEVICE_ID, "nm": nm, "tp": reg_type(nm),
                         "w": float(w), "kwh": 0.0}))
                st.sent += 1
            if producer is not None and k % 200 == 0:
                producer.poll(0)
                producer.flush(5)
        log.info("backfilled %d minutes (%d messages)", int(BACKFILL_MIN), st.sent)

    next_solar = 0.0
    tick = 0
    while running:
        t0 = time.time()
        ts_iso = datetime.fromtimestamp(t0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        fr = st.frame()
        for nm, w in fr.items():
            msg = {"ts": ts_iso, "dev": DEVICE_ID, "nm": nm, "tp": reg_type(nm),
                   "w": float(w), "kwh": 0.0}
            if producer is not None:
                producer.produce(KAFKA_TOPIC, key=nm, value=json.dumps(msg))
            st.sent += 1
        if producer is not None:
            producer.poll(0)
        if SOLAR_ENABLE and t0 >= next_solar:
            row = st.solar_row()
            if row:
                row = {"ts": datetime.fromtimestamp(t0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                       **row}
                threading.Thread(target=put_solar, args=(row,), daemon=True).start()
            next_solar = t0 + SOLAR_EVERY
        tick += 1
        if tick % 60 == 0:
            p = {k: round(v) for k, v in fr.items() if k.startswith("Panel")}
            log.info("tick %d | source %s | %s", tick,
                     st.source_now().astimezone(HOUSE_TZ).strftime("%m-%d %H:%M:%S"), p)
        if DRY_RUN and tick >= int(os.environ.get("DRY_RUN_TICKS", "3")):
            break
        time.sleep(max(0.0, 1.0 - (time.time() - t0)))
    if producer is not None:
        producer.flush(10)
    log.info("stopped after %d messages", st.sent)


if __name__ == "__main__":
    main()
