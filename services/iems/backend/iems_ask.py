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


# --- live feeds --------------------------------------------------------------
# Each context key comes from exactly one dashboard feed. Fetching all seven
# serially cost 26 s of a 42 s question, and `include` was applied only after
# the fetch, so a battery question still paid for loads and snapshot before
# throwing them away. Now only the feeds a question needs are fetched, in
# parallel, behind a short TTL cache. The meter publishes every 6 s and the
# NILM loop every 30 s, so a 30 s cache is honest about freshness rather than
# a shortcut.
_FEED_FOR = {
    "panel_watts_now":    "snapshot",
    "reading_time":       "snapshot",
    "solar_now":          "solar-assistant",
    "battery":            "storage",
    "solar_balance":      "storage",
    "thermostat":         "relay",
    "relay":              "relay",
    "hvac_last_24h":      "hvac-24h",
    "panel_loads_amps":   "loads",
    "appliances_on_now":  "nilm",
    "appliances_tracked": "nilm",
}
_ALL_FEEDS = sorted(set(_FEED_FOR.values()))
_LIVE_TTL = float(os.environ.get("IEMS_ASK_LIVE_TTL", "30"))

# Per-feed TTL, set by what each feed costs and by how fast the quantity it
# reports actually moves. snapshot, nilm, relay and solar-assistant answer in
# well under a second and carry the fast-moving numbers, so they stay short.
# storage and loads are AnyLog queries costing 7-10 s each, and battery state of
# charge and panel amps do not move meaningfully inside a minute. hvac-24h is a
# 24-hour aggregate. Caching by cost is also what keeps this endpoint from
# holding the operator's six REST threads the way /api/sources used to.
_FEED_TTL = {
    "snapshot":        15,
    "nilm":            15,
    "relay":           15,
    "solar-assistant": 15,
    "storage":         60,
    "loads":           60,
    "hvac-24h":       300,
}
_feed_cache = {}
_feed_lock = threading.Lock()


def _feed(name):
    """One dashboard feed, memoised for its own TTL."""
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


def _live(want=None):
    """A compact summary, not raw feeds.

    The first version handed the model 24 KB of JSON, including forty raw NILM
    rows. On four CPU cores that prefill alone ran past a 180 s timeout. Every
    field below is either a scalar or a short dict.

    /api/sources is skipped: it pulls 30 minutes of energy_readings.
    """
    feeds = sorted({_FEED_FOR[k] for k in (want or []) if k in _FEED_FOR}) or _ALL_FEEDS
    with ThreadPoolExecutor(max_workers=len(feeds)) as ex:
        got = dict(zip(feeds, ex.map(_feed, feeds)))

    out = {}

    snap = got.get("snapshot") or {}
    if snap:
        out["panel_watts_now"] = {k: v.get("w") for k, v in snap.items()
                                  if isinstance(v, dict)}
        out["reading_time"] = next(
            (v.get("ts") for v in snap.values() if isinstance(v, dict)), None)

    solar = got.get("solar-assistant")
    if solar:
        out["solar_now"] = {k: solar.get(k) for k in
                            ("pv_power_w", "battery_power_w", "battery_soc_pct",
                             "grid_power_w", "load_power_w", "device_mode", "age_s")}

    store = got.get("storage") or {}
    if store:
        b = store.get("battery") or {}
        out["battery"] = {k: b.get(k) for k in
                          ("soc_pct", "available_kwh", "headroom_kwh", "flow", "net_w")}
        out["solar_balance"] = store.get("solar")

    relay = got.get("relay") or {}
    if relay:
        t = relay.get("thermostat") or {}
        out["thermostat"] = {k: t.get(k) for k in
                             ("hvac_mode", "hvac_action", "current_f", "target_f")}
        out["relay"] = {"engaged": relay.get("relay_engaged"),
                        "dss": relay.get("dss")}

    hvac = got.get("hvac-24h")
    if hvac:
        out["hvac_last_24h"] = hvac

    loads = got.get("loads") or {}
    if loads.get("loads"):
        out["panel_loads_amps"] = {l.get("panel"): l.get("amps")
                                   for l in loads["loads"]}

    # Only what the disaggregator currently believes is ON, with confidence.
    nilm = got.get("nilm")
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

    # Only complain about feeds this call actually asked for.
    expected = [k for k in ("panel_watts_now", "solar_now", "battery", "thermostat",
                            "hvac_last_24h", "panel_loads_amps", "appliances_on_now")
                if _FEED_FOR[k] in feeds]
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
Never invent a number. Every figure in your answer must appear verbatim in the
CONTEXT -- copy the digits exactly as given, do not round, rescale or restate
them from memory. If a value you need is not in the CONTEXT, say it is not
available. Quote figures with their units and say how recent they are when the
context gives a timestamp.

The site: an eGauge 18646 meters sixteen channels. Three sub-panels (Panel1
HVAC, Panel2 H2O, Panel3 Kitchen) plus a Shop feed, the utility tie and a
Generac. A solar array with a 13.5 kWh battery reports through Solar Assistant.
Local ONNX models disaggregate the panel power into 22 appliances. A rules
layer then corrects those predictions. PG&E E6 time-of-use pricing applies.

Be concise and concrete. Prefer a short answer with the numbers over a long one."""


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

    if _provider(req.model) == "claude":
        result = _ask_claude(messages, req.model, req.temperature, req.timeout_seconds)
        if result.get("ok") or os.environ.get("IEMS_ASK_FALLBACK", "1") == "0":
            result.update({"context_chars": len(json.dumps(ctx, default=str)),
                           "live_keys": sorted(ctx.get("live", {})),
                           "knowledge_keys": sorted(ctx.get("site_knowledge", {}))})
            return result
        # Cloud call failed: answer locally and say why.
        cloud_error = result
        model = MODEL
    else:
        cloud_error = None

    # keep_alive -1 pins the weights: without it Ollama drops the model after
    # five minutes and the next question pays ~45 s of disk again. num_ctx 2048
    # is safe now that site_knowledge is off the default path, and halves the KV
    # cache. num_predict caps the tail, which is the one cost that scales with
    # the answer -- at a few tokens a second a 200-token reply is most of a
    # minute of pure output.
    payload = json.dumps({
        "model": model, "messages": messages, "stream": False,
        "keep_alive": _keep_alive(),
        "options": {"temperature": (0.0 if req.temperature is None
                                   else float(req.temperature)),
                    "num_ctx": int(os.environ.get("IEMS_ASK_NUM_CTX", "2048")),
                    "num_predict": int(os.environ.get("IEMS_ASK_MAX_TOKENS", "96")),
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
        "provider": "ollama",
        "cloud_error": cloud_error,
        "context_chars": len(json.dumps(ctx, default=str)),
        "live_keys": sorted(ctx.get("live", {})),
        "knowledge_keys": sorted(ctx.get("site_knowledge", {})),
        "eval_count": body.get("eval_count"),
        "eval_duration_ms": round((body.get("eval_duration") or 0) / 1e6),
        "total_duration_ms": round((body.get("total_duration") or 0) / 1e6),
    }
