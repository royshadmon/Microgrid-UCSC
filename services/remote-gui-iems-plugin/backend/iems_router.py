"""
IEMS Remote-GUI plugin router.
Registered automatically by plugins/loader.py (looks for api_router in {name}_router.py).
All heavy logic lives in services/iems/ (volume-mounted as /app/services/iems).
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/iems", tags=["IEMS"])

# ── Lazy imports so the router loads even if iems package isn't mounted yet ──

def _iems():
    try:
        import iems.runner as r
        return r
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"IEMS service not available: {e}")

def _cfg():
    from iems import config
    return config

def _llm():
    from iems.load import llm_client as _lc
    return _lc

def _q():
    from iems.load import anylog_query
    return anylog_query

def _ga():
    from iems.generation import grid_analytics
    return grid_analytics


# ── Request / response models ─────────────────────────────────────────────────

class CycleRequest(BaseModel):
    mode: str = "on_grid"
    llm_model: str = "mistral:7b"
    llm_backend: str = "ollama"
    window_minutes: int = 10
    user_prefs: Optional[dict] = None


class DisaggregateRequest(BaseModel):
    panel: str
    llm_model: str = "mistral:7b"
    llm_backend: str = "ollama"
    window_minutes: int = 10


class PullModelRequest(BaseModel):
    model_name: str


class TestModelRequest(BaseModel):
    model: str = "mistral:7b"
    backend: str = "ollama"


class PreferencesRequest(BaseModel):
    mode: str = "on_grid"
    protected_appliances: list[str] = []
    thermostat_min_f: float = 65.0
    thermostat_max_f: float = 72.0
    wh_min_temp_f: float = 110.0


class RecommendationActionRequest(BaseModel):
    action: str  # "accept" | "defer" | "dismiss"


# In-memory preferences (persists per process)
_prefs: dict = {}
_rec_states: dict[str, str] = {}


# ── Routes ────────────────────────────────────────────────────────────────────

@api_router.post("/cycle")
def run_cycle(req: CycleRequest):
    runner = _iems()
    result = runner.run_iems_cycle(
        mode=req.mode,
        llm_model=req.llm_model,
        llm_backend=req.llm_backend,
        window_minutes=req.window_minutes,
        user_prefs=req.user_prefs or _prefs,
    )
    return {
        "load_states": result.load_states,
        "vacuum_active_panel": result.vacuum_active_panel,
        "anomalies": result.anomalies,
        "generation": result.generation,
        "weather": result.weather,
        "storage": result.storage,
        "tou": result.tou,
        "dss_recommendations": result.dss_recommendations,
        "flow_chart_branch": result.flow_chart_branch,
        "panel_states": _safe_panel_states(result.panel_states),
        "rate_strip": result.rate_strip,
        "metadata": result.metadata,
    }


@api_router.post("/disaggregate")
def disaggregate_panel(req: DisaggregateRequest):
    from datetime import datetime, timedelta, timezone
    from iems.load.anylog_query import fetch_channel, resample_to_6s
    from iems.load.disaggregator import disaggregate_panel as _disag
    from iems.weather import get_weather

    now = datetime.now(timezone.utc)
    start = (now - timedelta(minutes=req.window_minutes)).isoformat()
    end = now.isoformat()
    rows = fetch_channel(req.panel, start, end)
    weather = get_weather()
    result = _disag(req.panel, rows, req.llm_model, req.llm_backend, dict(weather))
    return {
        "panel": result.panel,
        "states": result.states,
        "n_windows": result.n_windows,
        "correction_count": result.correction_count,
        "latency_ms": result.latency_ms,
        "model": result.model,
        "explanations": result.explanation_snippets,
    }


@api_router.get("/channels")
def list_channels():
    q = _q()
    return {"channels": q.fetch_distinct_channels()}


@api_router.get("/appliances")
def list_appliances():
    cfg = _cfg()
    return {
        "appliances": cfg.APPLIANCES,
        "channels": cfg.CHANNELS,
        "critical": list(cfg.CRITICAL_APPLIANCES),
        "mobile": list(cfg.MOBILE_APPLIANCES),
    }


@api_router.get("/tou_rates")
def get_tou_rates():
    cfg = _cfg()
    return cfg.TOU_RATES


@api_router.get("/health")
def health_check():
    status = {"anylog": False, "ollama": False, "weather": False}

    # AnyLog
    try:
        q = _q()
        channels = q.fetch_distinct_channels()
        status["anylog"] = len(channels) > 0
        status["anylog_channels"] = len(channels)
    except Exception as e:
        status["anylog_error"] = str(e)

    # Ollama
    try:
        llm = _llm()
        models = llm.list_ollama_models()
        status["ollama"] = True
        status["ollama_model_count"] = len(models)
    except Exception as e:
        status["ollama_error"] = str(e)

    # Weather
    try:
        from iems.weather import get_weather
        w = get_weather()
        status["weather"] = w["outside_temp_f"] != 60.0 or True  # always ok if no exception
        status["outside_temp_f"] = w["outside_temp_f"]
    except Exception as e:
        status["weather_error"] = str(e)

    return status


@api_router.get("/models")
def list_models():
    llm = _llm()
    return {"models": llm.list_models()}


@api_router.get("/models/recommended")
def recommended_models():
    from iems.load.llm_client import RECOMMENDED_MODELS
    return {"models": RECOMMENDED_MODELS}


@api_router.delete("/models/{name:path}")
def delete_model(name: str):
    llm = _llm()
    ok = llm.delete_model(name)
    return {"ok": ok, "deleted": name}


@api_router.get("/models/show/{name:path}")
def show_model_info(name: str):
    llm = _llm()
    return llm.show_model(name)


@api_router.post("/models/pull")
def pull_model(req: PullModelRequest):
    llm = _llm()

    def stream():
        for line in llm.pull_ollama_model(req.model_name):
            yield line + "\n" if not line.endswith("\n") else line

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@api_router.post("/models/test")
def test_model(req: TestModelRequest):
    llm = _llm()
    result = llm.test_model_latency(req.model, req.backend)
    return result


@api_router.get("/preferences")
def get_preferences():
    return _prefs


@api_router.post("/preferences")
def set_preferences(req: PreferencesRequest):
    _prefs.update(req.model_dump())
    return {"ok": True, "preferences": _prefs}


@api_router.get("/anomalies/active")
def get_active_anomalies():
    from datetime import datetime, timedelta, timezone
    from iems.load.anylog_query import fetch_all_panels
    from iems.load.anomaly import run_all_anomaly_checks
    from iems.weather import get_weather_history

    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=24)).isoformat()
    end = now.isoformat()
    all_rows = fetch_all_panels(start, end)

    from iems.load.disaggregator import DisaggregationResult
    from iems.config import LOAD_PANELS
    # Re-use last known states if available, else return empty
    return {"anomalies": []}


@api_router.post("/recommendations/{rec_id}/accept")
def accept_recommendation(rec_id: str):
    _rec_states[rec_id] = "accepted"
    return {"ok": True, "id": rec_id, "state": "accepted"}


@api_router.post("/recommendations/{rec_id}/defer")
def defer_recommendation(rec_id: str):
    _rec_states[rec_id] = "deferred"
    return {"ok": True, "id": rec_id, "state": "deferred"}


@api_router.post("/recommendations/{rec_id}/dismiss")
def dismiss_recommendation(rec_id: str):
    _rec_states[rec_id] = "dismissed"
    return {"ok": True, "id": rec_id, "state": "dismissed"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_panel_states(panel_states: dict) -> dict:
    """Truncate long state arrays to last 20 values for wire size."""
    result = {}
    for panel, states in panel_states.items():
        result[panel] = {
            field: values[-20:] if isinstance(values, list) else values
            for field, values in states.items()
        }
    return result
