"""
/iems/ask — grounded question answering over the microgrid, using the local LLM.

The AnyLog MCP server already gives a model SQL access to the tables. What it
cannot reach is the part of this system that lives in code and YAML rather than
in the ledger: the post-inference rules, the breaker/leg mapping, the canonical
appliance spec, and the live disaggregation state. This endpoint assembles all
of that into one context bundle and asks the model against it, so answers are
grounded in what the site actually is rather than in what the model remembers.

Nothing here calls out to the internet. The model runs in the local Ollama
container on this host.
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List, Dict

ask_router = APIRouter(prefix="/iems", tags=["IEMS"])

OLLAMA = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
MODEL = os.environ.get("IEMS_ASK_MODEL", "qwen2.5:1.5b-instruct")
DASH = os.environ.get("IEMS_DASH_URL", "http://host.docker.internal:47821").rstrip("/")
REPO = os.environ.get("IEMS_REPO", "/app/services")

# Static site knowledge. Loaded once per process; these files change rarely and
# a stale read is worse than a slightly slow first request.
_STATIC = {}


def _read(path, limit=6000):
    try:
        with open(path) as fh:
            return fh.read()[:limit]
    except Exception:
        return ""


def _breaker_summary():
    """The leg map and ratings only. The file is mostly a comment block
    explaining why the ratings are still null, which the model does not need."""
    raw = _read(os.path.join(REPO, "iems", "detect", "breaker_ratings.yaml"), 20000)
    body = raw.split("groups:", 1)
    head = [l for l in body[0].splitlines() if l.strip().startswith(("margin_frac",
            "clear_frac", "sustain_seconds"))]
    tail = [l for l in (body[1].splitlines() if len(body) > 1 else [])
            if l.strip() and not l.strip().startswith("#")]
    note = ("amps_rating is null for every group, so the breaker-margin "
            "detector is skipping them; ratings must be read off the handles.")
    return "\n".join(head + tail)[:1200] + "\nNOTE: " + note


def _static():
    if _STATIC:
        return _STATIC
    _STATIC["appliance_spec"] = _read(os.path.join(REPO, "..", "appliance_data_updated.txt"), 1800)
    _STATIC["breaker_ratings"] = _breaker_summary()
    try:
        from iems.config import APPLIANCES
        # Drop the long prose fields; keep the numbers a question might turn on.
        keep = ("panel", "laxity", "shed_priority", "on_threshold_w",
                "power_range_w", "avg_on_duration_min", "typical_cycle_min",
                "deferrable", "critical", "weather_coupled", "anomaly_target")
        slim = {k: {f: v[f] for f in keep if f in v}
                for k, v in APPLIANCES.items() if isinstance(v, dict)}
        _STATIC["appliance_catalogue"] = json.dumps(slim)[:4500]
    except Exception as exc:
        _STATIC["appliance_catalogue"] = "unavailable: %s" % exc
    _STATIC["rules"] = _rules_summary()
    return _STATIC


def _rules_summary():
    """Read the tunable constants straight out of the rules module rather than
    restating them here, so the summary cannot drift from the running rules."""
    try:
        from iems.inference import rules_additive as r
        out = {}
        for name in ("BATTERY_WINDOW", "PROTECT_CONF", "SOLAR_MIN_IRRADIANCE",
                     "SOLAR_MAX_CLOUD_PCT", "SOLAR_DAYLIGHT_HOURS", "PV_MIN_W",
                     "BATTERY_CHARGE_MIN_W", "PROTECTED_RULES", "MUTEX_GROUPS"):
            if hasattr(r, name):
                v = getattr(r, name)
                out[name] = list(v) if isinstance(v, (set, tuple)) else v
        out["_applied_in_order"] = [
            "apply_mutual_exclusion  keep only the highest-confidence ON member of a mutex group",
            "apply_power_gate        force OFF any appliance whose on-threshold exceeds the panel's measured watts",
            "apply_panel1_rules      weather-gate the solar pump, reconcile the heat pump against live wattage",
            "apply_panel2_rules      solar-thermal fallback and power-based water-heater gating",
        ]
        return json.dumps(out)[:4000]
    except Exception as exc:
        return "unavailable: %s" % exc


def _get(url, timeout=30, tries=3):
    """Retry: the dashboard's AnyLog queries intermittently come back empty
    because its partition-name cache goes stale, and an omitted feed made the
    model answer "I cannot see the live state" while looking authoritative."""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = json.loads(resp.read())
            if data not in ({}, [], None):
                return data
        except Exception:
            pass
        if attempt < tries - 1:
            time.sleep(1.5)
    return None


# ── live feeds (2026-10-26 rewrite) ─────────────────────────────────────────
# Every figure the model sees is MEASURED. The old bundle also carried the
# dashboard's simulated lead-acid battery (/api/storage, "SOC modeled, not
# metered"), and qwen quoted it: "charging at 48.9%" while the pack read 99%.
# Battery, solar, grid and house load now come only from Solar Assistant.
# eGauge subpanel CTs report negative watts, so panel power is sent as
# magnitudes. Appliance confidence is P(ON) and is shown as a percentage.
_FEED_FOR = {
    "panel_watts_now":    "snapshot",
    "reading_time":       "snapshot",
    "solar_now":          "solar-assistant",
    "battery":            "solar-assistant",
    "solar_balance":      "solar-assistant",
    "thermostat":         "relay",
    "relay":              "relay",
    "hvac_last_24h":      "hvac-24h",
    "panel_loads_amps":   "loads",
    "appliances_on_now":  "nilm",
    "appliances_tracked": "nilm",
}
_ALL_FEEDS = sorted(set(_FEED_FOR.values()))
_LIVE_TTL = float(os.environ.get("IEMS_ASK_LIVE_TTL", "30"))
_FEED_TTL = {"snapshot": 10, "nilm": 15, "relay": 15, "solar-assistant": 10,
             "loads": 60, "hvac-24h": 300}
_feed_cache = {}
_feed_lock = threading.Lock()

FRIENDLY = {
    "heat_pump": "Heat pump", "solar_pump": "Solar water pump", "jacuzzi_pump": "Jacuzzi pump",
    "strip_heater": "Backup strip heater", "water_heater": "Water heater", "hair_dryer": "Hair dryer",
    "sprinklers": "Sprinklers", "bath_lights": "Bathroom lights", "dryer": "Clothes dryer",
    "washing_machine": "Washing machine", "dishwasher": "Dishwasher", "microwave": "Microwave",
    "pressure_pump": "Water pressure pump", "refrigerator": "Kitchen fridge",
    "garage_fridge": "Garage fridge", "garage_freezer": "Garage freezer", "computers": "Computers",
    "tv_stereo": "TV and stereo", "oven": "Oven", "cooktop": "Cooktop",
    "counter_appliance": "Countertop appliance", "garage_opener": "Garage door opener",
}
PANEL_FRIENDLY = {"Panel1 (HVAC)": "Heating and cooling panel", "Panel2 (H2O)": "Water panel",
                  "Panel3 (Kitchen)": "Kitchen panel", "Shop": "Shop", "Grid Power": "Grid",
                  "Generac Power": "Generator"}


def _feed(name):
    ttl = _FEED_TTL.get(name, _LIVE_TTL)
    now = time.time()
    with _feed_lock:
        hit = _feed_cache.get(name)
        if hit and now - hit[0] < ttl:
            return hit[1]
    data = _get(DASH + "/api/" + name)
    with _feed_lock:
        _feed_cache[name] = (time.time(), data)
    return data


def _n(x, nd=0):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return int(round(v)) if nd == 0 else round(v, nd)


def _age_s(ts):
    if not ts:
        return None
    try:
        t = datetime.strptime(str(ts)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - t).total_seconds()))
    except Exception:
        return None


def _pt(ts=None):
    """Pacific wall-clock time for display. Storage stays UTC."""
    try:
        t = (datetime.strptime(str(ts)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
             if ts else datetime.now(timezone.utc))
        return t.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%-I:%M %p")
    except Exception:
        return None


def _live(want=None):
    feeds = sorted({_FEED_FOR[k] for k in (want or []) if k in _FEED_FOR}) or _ALL_FEEDS
    with ThreadPoolExecutor(max_workers=len(feeds)) as ex:
        got = dict(zip(feeds, ex.map(_feed, feeds)))
    out = {}

    snap = got.get("snapshot") or {}
    if snap:
        out["panel_watts_now"] = {k: abs(_n(v.get("w")) or 0) for k, v in snap.items()
                                  if isinstance(v, dict) and k not in ("Grid Power",)}
        out["reading_time"] = next((v.get("ts") for v in snap.values() if isinstance(v, dict)), None)

    s = got.get("solar-assistant") or {}
    if s and s.get("connected", True) and s.get("battery_soc_pct") is not None:
        bw = _n(s.get("battery_power_w")) or 0
        gw = _n(s.get("grid_power_w")) or 0
        out["solar_now"] = {"pv_power_w": _n(s.get("pv_power_w")), "battery_power_w": bw,
                            "battery_soc_pct": _n(s.get("battery_soc_pct")),
                            "grid_power_w": gw, "load_power_w": _n(s.get("load_power_w")),
                            "device_mode": s.get("device_mode"), "age_s": _n(s.get("age_s")),
                            "ts": s.get("ts")}
        out["battery"] = {"soc_pct": _n(s.get("battery_soc_pct")),
                          "flow": "charging" if bw > 50 else "discharging" if bw < -50 else "holding steady",
                          "power_w": abs(bw), "capacity_kwh": 13.5,
                          "stored_kwh": round(13.5 * (_n(s.get("battery_soc_pct")) or 0) / 100, 1)}
        out["solar_balance"] = {"solar_w": _n(s.get("pv_power_w")), "house_load_w": _n(s.get("load_power_w")),
                                "grid_direction": "importing" if gw > 20 else "exporting" if gw < -20 else "balanced",
                                "grid_w": abs(gw)}

    relay = got.get("relay") or {}
    if relay:
        t = relay.get("thermostat") or {}
        out["thermostat"] = {k: t.get(k) for k in ("hvac_mode", "hvac_action", "current_f", "target_f")}
        out["relay"] = {"engaged": relay.get("relay_engaged"), "dss": relay.get("dss")}

    hvac = got.get("hvac-24h")
    if hvac:
        out["hvac_last_24h"] = hvac

    loads = got.get("loads") or {}
    if loads.get("loads"):
        out["panel_loads_amps"] = {l.get("panel"): l.get("amps") for l in loads["loads"]
                                   if l.get("amps") is not None}

    nilm = got.get("nilm")
    if isinstance(nilm, list):
        latest = {}
        for r in nilm:
            key = (r.get("circuit"), r.get("appliance"))
            if key not in latest:
                latest[key] = r
        on, unsure = [], []
        for (circuit, appliance), r in latest.items():
            p = _n(r.get("confidence"), 3) or 0.0
            item = {"appliance": FRIENDLY.get(appliance, appliance), "key": appliance,
                    "where": PANEL_FRIENDLY.get(circuit, circuit),
                    "likelihood_pct": int(round(p * 100)), "watts": _n(r.get("avg_w"))}
            if str(r.get("state", "")).strip().upper() == "ON":
                on.append(item)
            elif 0.35 <= p < 0.65:
                unsure.append(item)
        out["appliances_on_now"] = sorted(on, key=lambda x: -x["likelihood_pct"])
        out["appliances_unsure"] = sorted(unsure, key=lambda x: -x["likelihood_pct"])
        out["appliances_tracked"] = len(latest)
        out["nilm_time"] = next(iter(latest.values()), {}).get("ts") if latest else None

    expected = [k for k in ("panel_watts_now", "solar_now", "thermostat", "hvac_last_24h",
                            "panel_loads_amps", "appliances_on_now") if _FEED_FOR[k] in feeds]
    missing = [k for k in expected if k not in out]
    if missing:
        out["_unavailable"] = missing
    return out


def _facts(live):
    """The exact numbers an answer may use, with source and age. Shown under
    every answer so a reader can check it."""
    F = []
    s = live.get("solar_now") or {}
    sa_age = s.get("age_s")
    if s:
        b = live.get("battery") or {}
        F.append({"label": "Battery", "value": "%s%%" % b.get("soc_pct"), "detail": b.get("flow") +
                  ("" if b.get("flow") == "holding steady" else " at %s W" % b.get("power_w")),
                  "source": "Solar Assistant", "age_s": sa_age})
        F.append({"label": "Solar", "value": "%s W" % s.get("pv_power_w"), "source": "Solar Assistant", "age_s": sa_age})
        g = live.get("solar_balance") or {}
        F.append({"label": "Grid", "value": "%s W" % g.get("grid_w"), "detail": g.get("grid_direction"),
                  "source": "Solar Assistant", "age_s": sa_age})
        F.append({"label": "House use", "value": "%s W" % s.get("load_power_w"), "source": "Solar Assistant", "age_s": sa_age})
    w = live.get("panel_watts_now") or {}
    snap_age = _age_s(live.get("reading_time"))
    for k, v in w.items():
        if k in ("Generac Power",) and not v:
            continue
        F.append({"label": PANEL_FRIENDLY.get(k, k), "value": "%s W" % v, "source": "eGauge meter", "age_s": snap_age})
    on = live.get("appliances_on_now")
    if on is not None:
        F.append({"label": "Running now", "value": ", ".join(a["appliance"] for a in on) or "nothing detected",
                  "source": "appliance detector", "age_s": _age_s(live.get("nilm_time"))})
    t = live.get("thermostat") or {}
    if t.get("current_f") is not None:
        F.append({"label": "Indoor temperature", "value": "%s F" % t.get("current_f"),
                  "detail": "HVAC %s" % (t.get("hvac_action") or t.get("hvac_mode")), "source": "Thermostat"})
    h = live.get("hvac_last_24h") or {}
    if h.get("kwh_24h") is not None:
        F.append({"label": "Heating and cooling, last 24 h", "value": "%s kWh" % h.get("kwh_24h"), "source": "eGauge meter"})
    return F


def _headline(live):
    L = []
    s = live.get("solar_now") or {}
    b = live.get("battery") or {}
    g = live.get("solar_balance") or {}
    if s:
        L.append("Measured at %s Pacific (Solar Assistant): solar is producing %s W. The battery is %s%% full and %s%s. "
                 "The house is using %s W. The grid is %s%s."
                 % (_pt(s.get("ts")), s.get("pv_power_w"), b.get("soc_pct"), b.get("flow"),
                    "" if b.get("flow") == "holding steady" else " at %s W" % b.get("power_w"),
                    s.get("load_power_w"), g.get("grid_direction"),
                    "" if g.get("grid_direction") == "balanced" else " %s W" % g.get("grid_w")))
    on = live.get("appliances_on_now")
    if on is not None:
        if on:
            L.append("Appliances detected ON: " + "; ".join(
                "%s (%s, %s%% likely)" % (a["appliance"], a["where"], a["likelihood_pct"]) for a in on)
                + ". Everything else of the %s tracked appliances is off." % live.get("appliances_tracked"))
        else:
            L.append("No appliances are detected ON right now (%s tracked)." % live.get("appliances_tracked"))
    w = live.get("panel_watts_now")
    if w:
        L.append("Panel power right now: " + ", ".join("%s %s W" % (PANEL_FRIENDLY.get(k, k), v)
                                                         for k, v in w.items()) + ".")
    t = live.get("thermostat") or {}
    if t.get("current_f") is not None:
        L.append("Thermostat: indoor %s F, setpoint %s, mode %s, currently %s."
                 % (t.get("current_f"), t.get("target_f") if t.get("target_f") is not None else "not set",
                    t.get("hvac_mode"), t.get("hvac_action")))
    h = live.get("hvac_last_24h") or {}
    if h.get("kwh_24h") is not None:
        L.append("Heating and cooling used %s kWh in the last 24 hours." % h.get("kwh_24h"))
    if live.get("_unavailable"):
        L.append("UNAVAILABLE right now, do not guess these: %s." % ", ".join(live["_unavailable"]))
    return "\n".join(L) if L else "No live readings came back on this attempt."


# PG&E E6 periods, identical to the dashboard's classifyTOU.
def _tou(dt):
    h, dow, mon = dt.hour, dt.weekday(), dt.month
    summer, weekday = 5 <= mon <= 10, dow < 5
    if weekday and 15 <= h < 19:
        return "peak"
    if weekday and (10 <= h < 13 or 19 <= h < 21):
        return "partial-peak"
    if h < 9 or h >= 21:
        return "super off-peak"
    return "off-peak"


def _direct(question, live):
    """Answer the common questions straight from the measured numbers.
    Returns None when the question needs the model."""
    q = (question or "").lower()
    s = live.get("solar_now") or {}
    b = live.get("battery") or {}
    g = live.get("solar_balance") or {}
    when = _pt(s.get("ts")) or _pt()
    parts = []
    if re.search(r"batter|soc|state of charge|charg", q) and b:
        parts.append("The battery is %s%% full (about %s of %s kWh) and is %s%s."
                     % (b["soc_pct"], b["stored_kwh"], b["capacity_kwh"], b["flow"],
                        "" if b["flow"] == "holding steady" else " at %s W" % b["power_w"]))
    if re.search(r"\bsolar\b|\bpv\b|panels? produc|sun", q) and s and "solar pump" not in q:
        pv = s.get("pv_power_w") or 0
        parts.append("Solar is producing %s W%s." % (pv, " (it is dark or overcast)" if pv < 50 else
                     ", covering %s%% of the house's %s W" % (min(100, int(round(100 * pv / max(1, s.get('load_power_w') or 1)))), s.get("load_power_w"))))
    if re.search(r"\bgrid\b|import|export|utility|pg&?e", q) and g:
        parts.append("The house is %s %s W %s the grid." % (g["grid_direction"], g["grid_w"],
                     "from" if g["grid_direction"] == "importing" else "to") if g["grid_direction"] != "balanced"
                     else "Grid flow is about zero.")
    if re.search(r"how much power|using|consum|house load|drawing", q) and s and not re.search(r"appliance|which", q):
        parts.append("The house is using %s W right now." % s.get("load_power_w"))
    if re.search(r"(which|what) appliances|what('s| is) (on|running)|running now|turned on|is on", q) \
            and live.get("appliances_on_now") is not None:
        on = live["appliances_on_now"]; un = live.get("appliances_unsure") or []
        if on:
            parts.append("Running now: " + "; ".join("%s (%s%% likely)" % (a["appliance"], a["likelihood_pct"]) for a in on) + ".")
        else:
            parts.append("No appliances are detected running right now.")
        if un:
            parts.append("Not sure about: " + ", ".join(a["appliance"] for a in un) + ".")
    if re.search(r"which panel|panels? (draw|using)|most power", q) and live.get("panel_watts_now"):
        w = {k: v for k, v in live["panel_watts_now"].items() if k != "Generac Power"}
        top = max(w, key=w.get)
        parts.append("%s is drawing the most at %s W. " % (PANEL_FRIENDLY.get(top, top), w[top]) +
                     ", ".join("%s %s W" % (PANEL_FRIENDLY.get(k, k), v)
                               for k, v in sorted(w.items(), key=lambda kv: -kv[1]) if k != top) + ".")
    t = live.get("thermostat") or {}
    if re.search(r"thermostat|temperature|indoor|warm|cold|hvac (mode|doing)", q) and t.get("current_f") is not None:
        parts.append("Indoors it is %s F. The heating and cooling is %s (mode %s)."
                     % (t["current_f"], t.get("hvac_action") or "idle", t.get("hvac_mode")))
    h = live.get("hvac_last_24h") or {}
    if re.search(r"(hvac|heating|cooling|heat pump).*(24|day|today|yesterday)|last 24", q) and h.get("kwh_24h") is not None:
        parts.append("Heating and cooling used %s kWh over the last 24 hours (average %s W)." % (h["kwh_24h"], h.get("avg_w")))
    if re.search(r"defer|shift|best time|when should|cheap|peak", q):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        cur = _tou(now)
        nxt = None
        for dh in range(1, 25):
            f = now + timedelta(hours=dh)
            if _tou(f) in ("off-peak", "super off-peak") and _tou(f) != cur:
                nxt = f.replace(minute=0); break
        pv = (s.get("pv_power_w") or 0); soc = b.get("soc_pct") or 0
        if cur in ("peak", "partial-peak"):
            parts.append("It is %s pricing now. Hold the dryer, dishwasher and laundry until %s%s."
                         % (cur, nxt.strftime("%-I %p") if nxt else "the next off-peak period",
                            " (battery is %s%% and can cover small loads meanwhile)" % soc if soc >= 50 else ""))
        elif pv > 1500:
            parts.append("Good time now: %s pricing and solar is producing %s W, so heavy loads will mostly run on sunshine." % (cur, pv))
        else:
            parts.append("It is %s pricing now, a fine time for the dryer, dishwasher or laundry. "
                         "Avoid weekdays 3 to 7 PM, the peak period." % cur)
    if not parts:
        return None
    return " ".join(parts) + " (as of %s Pacific)" % when


_NUM = re.compile(r"(?<![A-Za-z])-?\d+(?:[.,]\d+)?")


def _verify(answer, ctx_text):
    """Every number in a model answer must appear in the context it was given."""
    allowed = set(x.replace(",", "") for x in _NUM.findall(ctx_text))
    bad = [x for x in _NUM.findall(answer or "") if x.replace(",", "") not in allowed
           and x.replace(",", "").lstrip("-") not in allowed and len(x.replace(",", "")) > 1]
    return bad


SYSTEM = """You answer questions about one family's home energy system in Los Gatos, California.

Use ONLY the facts under RIGHT NOW AT THE HOME. Copy every number exactly as written there,
with its unit. Never estimate, never do arithmetic, never use a number that is not written there.
If the facts do not answer the question, say plainly which reading is not available.

Write for a homeowner, not an engineer: two or three short sentences, plain words,
no JSON keys, no panel codes. Say "importing from the grid" or "sending power to the grid",
"the battery is charging" or "the battery is running the house"."""


# ── Cloud model: Anthropic Claude ─────────────────────────────────────────────
# Used when an API key is available, unless IEMS_ASK_PROVIDER=ollama. The same
# grounded context goes to the model either way; the local Ollama model remains
# the fallback when the key is missing or the API cannot be reached.
ANTHROPIC_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
_CLAUDE_MODEL_CACHE = {}


def _anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    for path in ("/run/secrets/anthropic_api_key", "/app/.anthropic.env"):
        try:
            for line in open(path):
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
                if line and "=" not in line:
                    return line
        except OSError:
            pass
    return ""


def _provider(requested_model=None):
    if requested_model and requested_model.startswith("claude"):
        return "claude"
    if requested_model:
        return "ollama"
    want = os.environ.get("IEMS_ASK_PROVIDER", "auto").lower()
    if want in ("claude", "ollama"):
        return want
    return "claude" if _anthropic_key() else "ollama"


def _claude_model(key):
    """Explicit IEMS_ASK_CLAUDE_MODEL wins; otherwise the newest Sonnet the key can
    use, read from the Models API once per process rather than hard-coded."""
    explicit = os.environ.get("IEMS_ASK_CLAUDE_MODEL", "").strip()
    if explicit:
        return explicit
    if "id" in _CLAUDE_MODEL_CACHE:
        return _CLAUDE_MODEL_CACHE["id"]
    req = urllib.request.Request(ANTHROPIC_URL + "/v1/models?limit=100", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        models = [m.get("id", "") for m in json.loads(resp.read()).get("data", [])]
    chosen = next((m for m in models if "sonnet" in m), models[0] if models else "")
    _CLAUDE_MODEL_CACHE["id"] = chosen
    return chosen


def _ask_claude(messages, requested_model, temperature, timeout):
    key = _anthropic_key()
    if not key:
        return {"ok": False, "error": "no Anthropic API key", "provider": "claude"}
    try:
        model = requested_model if (requested_model or "").startswith("claude") else _claude_model(key)
    except Exception as exc:
        return {"ok": False, "error": "could not list Claude models", "detail": str(exc), "provider": "claude"}
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
    payload = json.dumps({
        "model": model,
        "max_tokens": int(os.environ.get("IEMS_ASK_CLAUDE_MAX_TOKENS", "800")),
        "temperature": 0.0 if temperature is None else float(temperature),
        "system": system + "\n\nAll times you mention are Pacific time (America/Los_Angeles).",
        "messages": turns,
    }).encode()
    req = urllib.request.Request(ANTHROPIC_URL + "/v1/messages", data=payload, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=min(timeout or 120, 180)) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": "claude %s" % exc.code, "provider": "claude", "model": model,
                "detail": exc.read().decode("utf-8", "replace")[:400]}
    except Exception as exc:
        return {"ok": False, "error": "claude unreachable", "detail": str(exc), "provider": "claude", "model": model}
    text = "".join(part.get("text", "") for part in body.get("content", []) if part.get("type") == "text")
    usage = body.get("usage", {})
    return {"ok": True, "answer": text, "model": body.get("model", model), "provider": "claude",
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
            "total_duration_ms": round((time.time() - started) * 1000)}


class AskRequest(BaseModel):
    question: str
    model: Optional[str] = None
    include: Optional[List[str]] = None      # subset of context keys
    include_knowledge: Optional[bool] = None # None = decide from the question
    history: Optional[List[Dict[str, str]]] = None
    temperature: Optional[float] = 0.0
    timeout_seconds: Optional[float] = 600.0


# site_knowledge is 84% of the prompt (appliance_spec 4.0 KB, catalogue 3.4 KB)
# and contributes nothing to "what is the battery doing". It is now opt-in: sent
# when the caller asks for it, or when the question is about the specifications
# and rules rather than the live state.
_KNOWLEDGE_HINT = re.compile(
    r"rule|spec|breaker|\bleg\b|rating|catalog|catalogue|threshold|constant|"
    r"capacit|wiring|panel map|which appliances (exist|are tracked)", re.I)


def _keep_alive():
    """Ollama wants a number of seconds or a duration string; the bare string
    "-1" is rejected with `missing unit in duration`. -1 means never unload,
    which is the point: without it the weights are dropped after five minutes
    and the next question pays the disk load again."""
    raw = os.environ.get("IEMS_ASK_KEEP_ALIVE", "-1")
    try:
        val = float(raw)
        return int(val) if val.is_integer() else val
    except ValueError:
        return raw


def _build_context(include=None, question=None, want_knowledge=None):
    live = _live(include)
    if include:
        keep = set(include)
        live = {k: v for k, v in live.items() if k in keep or k.startswith("_")}
    if want_knowledge is None:
        want_knowledge = bool(question and _KNOWLEDGE_HINT.search(question))
    knowledge = _static() if want_knowledge else {}
    if include and knowledge:
        # include names live feeds ("battery"), knowledge sections
        # ("appliance_spec"), or both. Only narrow the knowledge when the
        # caller actually named a knowledge section -- otherwise
        # include=battery&knowledge=1 silently returned nothing.
        keep = set(include) & set(knowledge)
        if keep:
            knowledge = {k: v for k, v in knowledge.items() if k in keep}
    return {"live": live, "site_knowledge": knowledge}


@ask_router.get("/ask/context")
def ask_context(include: str = "", knowledge: int = 0, question: str = ""):
    """The exact bundle the model is given. Useful on its own, and the first
    thing to look at when an answer is wrong."""
    ctx = _build_context([s for s in include.split(",") if s] or None,
                         question or None,
                         True if knowledge else (None if question else False))
    return {"model": MODEL, "ollama": OLLAMA,
            "context_chars": len(json.dumps(ctx)),
            "live_keys": sorted(ctx.get("live", {})),
            "knowledge_keys": sorted(ctx.get("site_knowledge", {})),
            "context": ctx}


@ask_router.get("/ask/health")
def ask_health():
    tags = _get(OLLAMA + "/api/tags", timeout=20) or {}
    models = [m.get("name") for m in tags.get("models", [])]
    return {"ollama": OLLAMA, "reachable": bool(tags), "models": models,
            "configured_model": MODEL, "model_present": MODEL in models,
            "dashboard": DASH,
            "provider": _provider(),
            "claude_key_present": bool(_anthropic_key()),
            "claude_model": os.environ.get("IEMS_ASK_CLAUDE_MODEL") or _CLAUDE_MODEL_CACHE.get("id")}


@ask_router.post("/ask")
def ask(req: AskRequest):
    model = req.model or MODEL
    ctx = _build_context(req.include, req.question, req.include_knowledge)
    live = ctx.get("live", {})
    base = {"facts": _facts(live),
            "as_of_pt": _pt((live.get("solar_now") or {}).get("ts") or live.get("reading_time")),
            "context_chars": len(json.dumps(ctx, default=str)),
            "live_keys": sorted(live), "knowledge_keys": sorted(ctx.get("site_knowledge", {}))}

    # 1. Questions the numbers answer on their own never go to a model.
    direct = None if req.include_knowledge else _direct(req.question, live)
    if direct:
        return {"ok": True, "answer": direct, "model": "live readings", "provider": "live",
                "answer_source": "live readings", "verified": True, **base}

    head = _headline(live)
    knowledge = json.dumps(ctx.get("site_knowledge", {}), default=str)
    messages = [{"role": "system", "content": SYSTEM}]
    for turn in (req.history or [])[-4:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content":
        "RIGHT NOW AT THE HOME\n%s\n\n%sQUESTION\n%s"
        % (head, ("BACKGROUND (house specifications, not live readings)\n%s\n\n" % knowledge)
           if ctx.get("site_knowledge") else "", req.question)})

    cloud_error = None
    if _provider(req.model) == "claude":
        result = _ask_claude(messages, req.model, req.temperature, req.timeout_seconds)
        if result.get("ok"):
            bad = _verify(result.get("answer"), head + knowledge)
            result.update({"answer_source": "claude", "verified": not bad, "unmatched_numbers": bad, **base})
            return result
        cloud_error = result
        model = MODEL

    payload = json.dumps({
        "model": model, "messages": messages, "stream": False,
        "keep_alive": _keep_alive(),
        "options": {"temperature": 0.0 if req.temperature is None else float(req.temperature),
                    "num_ctx": int(os.environ.get("IEMS_ASK_NUM_CTX", "2048")),
                    "num_predict": int(os.environ.get("IEMS_ASK_MAX_TOKENS", "120")),
                    "num_thread": int(os.environ.get("IEMS_ASK_THREADS", "3"))},
    }).encode()
    request = urllib.request.Request(OLLAMA + "/api/chat", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=req.timeout_seconds or 600) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": "ollama %s" % exc.code,
                "detail": exc.read().decode("utf-8", "replace")[:400], "model": model, **base}
    except Exception as exc:
        return {"ok": False, "error": "ollama unreachable", "detail": str(exc), "model": model, **base}

    answer = ((body.get("message") or {}).get("content") or "").strip()
    # 2. A model answer that quotes a number not in its context is not shown as fact.
    bad = _verify(answer, head + knowledge)
    if bad:
        answer = ("I could not confirm part of that answer against the live readings, "
                  "so here is what the readings say: " + head.replace("\n", " "))
    return {"ok": True, "answer": answer, "model": model, "provider": "ollama",
            "answer_source": "local model" if not bad else "live readings (model answer rejected)",
            "verified": not bad, "unmatched_numbers": bad, "cloud_error": cloud_error,
            "eval_count": body.get("eval_count"),
            "total_duration_ms": round((body.get("total_duration") or 0) / 1e6), **base}
