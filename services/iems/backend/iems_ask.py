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
import time
import urllib.error
import urllib.request

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List, Dict

ask_router = APIRouter(prefix="/iems", tags=["IEMS"])

OLLAMA = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
MODEL = os.environ.get("IEMS_ASK_MODEL", "qwen2.5:3b-instruct")
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


def _live():
    """A compact summary, not raw feeds.

    The first version handed the model 24 KB of JSON, including forty raw NILM
    rows. On four CPU cores that prefill alone ran past a 180 s timeout. Every
    field below is either a scalar or a short dict, and the whole bundle lands
    around 4 KB, which prefills in tens of seconds rather than minutes.

    /api/sources is skipped: it pulls 30 minutes of energy_readings and takes
    about 24 s on its own.
    """
    out = {}

    snap = _get(DASH + "/api/snapshot") or {}
    if snap:
        out["panel_watts_now"] = {k: v.get("w") for k, v in snap.items()
                                  if isinstance(v, dict)}
        out["reading_time"] = next(
            (v.get("ts") for v in snap.values() if isinstance(v, dict)), None)

    solar = _get(DASH + "/api/solar-assistant")
    if solar:
        out["solar_now"] = {k: solar.get(k) for k in
                            ("pv_power_w", "battery_power_w", "battery_soc_pct",
                             "grid_power_w", "load_power_w", "device_mode", "age_s")}

    store = _get(DASH + "/api/storage") or {}
    if store:
        b = store.get("battery") or {}
        out["battery"] = {k: b.get(k) for k in
                          ("soc_pct", "available_kwh", "headroom_kwh", "flow", "net_w")}
        out["solar_balance"] = store.get("solar")

    relay = _get(DASH + "/api/relay") or {}
    if relay:
        t = relay.get("thermostat") or {}
        out["thermostat"] = {k: t.get(k) for k in
                             ("hvac_mode", "hvac_action", "current_f", "target_f")}
        out["relay"] = {"engaged": relay.get("relay_engaged"),
                        "dss": relay.get("dss")}

    hvac = _get(DASH + "/api/hvac-24h")
    if hvac:
        out["hvac_last_24h"] = hvac

    loads = _get(DASH + "/api/loads") or {}
    if loads.get("loads"):
        out["panel_loads_amps"] = {l.get("panel"): l.get("amps")
                                   for l in loads["loads"]}

    # Only what the disaggregator currently believes is ON, with confidence.
    nilm = _get(DASH + "/api/nilm")
    if isinstance(nilm, list):
        latest = {}
        for r in nilm:
            key = (r.get("circuit"), r.get("appliance"))
            if key not in latest:
                latest[key] = r
        on = []
        for (circuit, appliance), r in latest.items():
            if str(r.get("state", "")).strip().upper() == "ON":
                on.append({"appliance": appliance, "circuit": circuit,
                           "confidence": r.get("confidence"), "avg_w": r.get("avg_w")})
        out["appliances_on_now"] = sorted(on, key=lambda x: str(x["appliance"]))
        out["appliances_tracked"] = len(latest)

    expected = ("panel_watts_now", "solar_now", "battery", "thermostat",
                "hvac_last_24h", "panel_loads_amps", "appliances_on_now")
    missing = [k for k in expected if k not in out]
    if missing:
        out["_unavailable"] = missing
        out["_note"] = ("These feeds did not return on this attempt. Say they are "
                        "unavailable rather than inferring their values.")
    return out


def _headline(live):
    """A plain-language digest of the live state, placed before the JSON.

    A 3B model given 10 KB of nested JSON answered from the rules constants and
    claimed it could not see the live state, while the live state was in the
    payload. Leading with short declarative sentences fixed that.
    """
    L = []
    s = live.get("solar_now") or {}
    if s:
        L.append("Solar is producing %s W. The battery is at %s%% and its flow is %s W "
                 "(positive charging). The grid leg reads %s W (negative exporting). "
                 "House load is %s W. Inverter mode: %s."
                 % (s.get("pv_power_w"), s.get("battery_soc_pct"),
                    s.get("battery_power_w"), s.get("grid_power_w"),
                    s.get("load_power_w"), s.get("device_mode")))
    b = live.get("battery") or {}
    if b:
        L.append("Battery model: %s%% state of charge, %s kWh available, %s kWh headroom, %s."
                 % (b.get("soc_pct"), b.get("available_kwh"),
                    b.get("headroom_kwh"), b.get("flow")))
    on = live.get("appliances_on_now")
    if on is not None:
        if on:
            L.append("Appliances the disaggregator currently reports ON: "
                     + "; ".join("%s on %s at %s W, confidence %s"
                                 % (a.get("appliance"), a.get("circuit"),
                                    a.get("avg_w"), a.get("confidence")) for a in on)
                     + ". Every other tracked appliance is OFF (%s tracked in total)."
                     % live.get("appliances_tracked"))
        else:
            L.append("The disaggregator currently reports NO appliances ON "
                     "(%s tracked)." % live.get("appliances_tracked"))
    w = live.get("panel_watts_now")
    if w:
        L.append("Panel power right now: "
                 + ", ".join("%s %s W" % (k, v) for k, v in w.items()) + ".")
    t = live.get("thermostat") or {}
    if t.get("current_f") is not None:
        L.append("Thermostat: indoor %s F, setpoint %s F, mode %s, action %s."
                 % (t.get("current_f"), t.get("target_f"),
                    t.get("hvac_mode"), t.get("hvac_action")))
    h = live.get("hvac_last_24h") or {}
    if h.get("kwh_24h") is not None:
        L.append("HVAC used %s kWh in the last 24 hours (average %s W)."
                 % (h.get("kwh_24h"), h.get("avg_w")))
    amps = live.get("panel_loads_amps")
    if amps:
        L.append("Panel currents: "
                 + ", ".join("%s %s A" % (k, v) for k, v in amps.items()) + ".")
    if live.get("_unavailable"):
        L.append("UNAVAILABLE right now, do not guess these: %s."
                 % ", ".join(live["_unavailable"]))
    return "\n".join(L) if L else "No live readings came back on this attempt."


SYSTEM = """You are the analyst for a residential microgrid in Los Gatos, California.

You answer from the CONTEXT below and nothing else. If the context does not
contain what is needed, say exactly what is missing rather than estimating.
Never invent a number. Quote figures with their units and say how recent they
are when the context gives a timestamp.

The site: an eGauge 18646 meters sixteen channels. Three sub-panels (Panel1
HVAC, Panel2 H2O, Panel3 Kitchen) plus a Shop feed, the utility tie and a
Generac. A solar array with a 13.5 kWh battery reports through Solar Assistant.
Local ONNX models disaggregate the panel power into 22 appliances. A rules
layer then corrects those predictions. PG&E E6 time-of-use pricing applies.

Be concise and concrete. Prefer a short answer with the numbers over a long one."""


class AskRequest(BaseModel):
    question: str
    model: Optional[str] = None
    include: Optional[List[str]] = None      # subset of context keys
    history: Optional[List[Dict[str, str]]] = None
    temperature: Optional[float] = 0.2
    timeout_seconds: Optional[float] = 600.0


def _build_context(include=None):
    ctx = {"live": _live(), "site_knowledge": _static()}
    if include:
        keep = set(include)
        ctx["live"] = {k: v for k, v in ctx["live"].items() if k in keep}
        ctx["site_knowledge"] = {k: v for k, v in ctx["site_knowledge"].items() if k in keep}
    return ctx


@ask_router.get("/ask/context")
def ask_context(include: str = ""):
    """The exact bundle the model is given. Useful on its own, and the first
    thing to look at when an answer is wrong."""
    ctx = _build_context([s for s in include.split(",") if s] or None)
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
            "dashboard": DASH}


@ask_router.post("/ask")
def ask(req: AskRequest):
    model = req.model or MODEL
    ctx = _build_context(req.include)

    messages = [{"role": "system", "content": SYSTEM}]
    for turn in (req.history or [])[-6:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    live = ctx.get("live", {})
    messages.append({"role": "user", "content":
        "RIGHT NOW AT THE SITE\n%s\n\n"
        "SITE KNOWLEDGE (specifications and rules, not live readings)\n%s\n\n"
        "SUPPORTING DETAIL (json)\n%s\n\n"
        "QUESTION\n%s\n\n"
        "Answer from RIGHT NOW first. The site knowledge is background only; do "
        "not present a rule constant as a live reading."
        % (_headline(live),
           json.dumps(ctx.get("site_knowledge", {}), default=str),
           json.dumps(live, default=str),
           req.question)})

    payload = json.dumps({
        "model": model, "messages": messages, "stream": False,
        "options": {"temperature": req.temperature or 0.2, "num_ctx": 4096,
                    "num_thread": int(os.environ.get("IEMS_ASK_THREADS", "3"))},
    }).encode()

    request = urllib.request.Request(
        OLLAMA + "/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=req.timeout_seconds or 600) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": "ollama %s" % exc.code,
                "detail": exc.read().decode("utf-8", "replace")[:400], "model": model}
    except Exception as exc:
        return {"ok": False, "error": "ollama unreachable", "detail": str(exc),
                "model": model, "ollama": OLLAMA}

    return {
        "ok": True,
        "answer": (body.get("message") or {}).get("content", ""),
        "model": model,
        "context_chars": len(json.dumps(ctx, default=str)),
        "live_keys": sorted(ctx.get("live", {})),
        "eval_count": body.get("eval_count"),
        "eval_duration_ms": round((body.get("eval_duration") or 0) / 1e6),
        "total_duration_ms": round((body.get("total_duration") or 0) / 1e6),
    }
