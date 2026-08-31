"""
IEMS plugin router for AnyLog remote-gui.

The IEMS engine (ONNX NILM disaggregation, DSS, storage model) runs in its own
container on this host, and the IEMS live dashboard server aggregates AnyLog
panel history, Solar Assistant, the Home Assistant thermostat and the relay
action log.  This router re-implements neither.  It registers every route those
two expose and forwards each call, so the plugin page, the standalone dashboard
and any external caller all share one engine running locally on this machine.

Every forward runs in a threadpool.  This matters more than it looks: the
upstream calls are blocking, some of them take twenty seconds against a
9-million-row table, and doing that work inside an `async def` blocks uvicorn's
event loop for the whole GUI.  Measured on this host before the fix, a single
in-flight IEMS call pushed an unrelated `/version` request from 7 ms to 22.8 s.
Nothing else in the GUI may pay for an IEMS query.

Discovered automatically by plugins/loader.py, which looks for `api_router`
in {plugin_name}_router.py.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/iems", tags=["IEMS"])

IEMS_BACKEND_URL = os.environ.get(
    "IEMS_BACKEND_URL", "http://host.docker.internal:8009").rstrip("/")
IEMS_DASH_URL = os.environ.get(
    "IEMS_DASH_URL", "http://host.docker.internal:47821").rstrip("/")

# A full IEMS cycle runs disaggregation over a window and can take a while.
PROXY_TIMEOUT = float(os.environ.get("IEMS_PROXY_TIMEOUT", "180"))

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
    "content-length",
}


def _blocking_forward(url, method, headers, body):
    """Runs in a worker thread, never on the event loop."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as resp:
            payload = resp.read()
            media = resp.headers.get("Content-Type", "application/json")
            out_headers = {k: v for k, v in resp.headers.items()
                           if k.lower() not in _HOP_BY_HOP}
            out_headers.pop("Content-Type", None)
            return Response(content=payload, status_code=resp.status,
                            media_type=media, headers=out_headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        media = "application/json"
        if exc.headers:
            media = exc.headers.get("Content-Type", "application/json")
        return Response(content=payload, status_code=exc.code, media_type=media)
    except Exception as exc:  # noqa: BLE001 - upstream down, DNS, timeout
        logger.warning("IEMS proxy failed for %s %s: %s", method, url, exc)
        return Response(
            content=json.dumps({
                "error": "IEMS upstream unreachable",
                "detail": str(exc),
                "upstream": url,
            }).encode(),
            status_code=502,
            media_type="application/json",
        )


async def _forward(base: str, path: str, request: Request,
                   body: Optional[bytes] = None,
                   method: Optional[str] = None) -> Response:
    qs = request.url.query
    url = base + path + (("?" + qs) if qs else "")

    headers = {}
    ctype = request.headers.get("content-type")
    if ctype:
        headers["Content-Type"] = ctype
    accept = request.headers.get("accept")
    if accept:
        headers["Accept"] = accept

    return await run_in_threadpool(
        _blocking_forward, url, (method or request.method).upper(), headers, body)


async def _body(request: Request) -> Optional[bytes]:
    raw = await request.body()
    return raw if raw else None


# ── Engine routes, one per upstream route ────────────────────────────────────
# Declared explicitly rather than as a catch-all so the GUI's OpenAPI schema
# lists the real IEMS surface and so /iems/dash cannot be swallowed by a
# wildcard.

@api_router.get("/health")
async def iems_health(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/health", request)


@api_router.get("/channels")
async def iems_channels(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/channels", request)


@api_router.get("/appliances")
async def iems_appliances(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/appliances", request)


@api_router.get("/storage")
async def iems_storage(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/storage", request)


@api_router.get("/tou_rates")
async def iems_tou_rates(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/tou_rates", request)


@api_router.get("/nilm/recent")
async def iems_nilm_recent(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/nilm/recent", request)


@api_router.get("/onnx/models")
async def iems_onnx_models(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/onnx/models", request)


@api_router.get("/onnx/snapshot")
async def iems_onnx_snapshot(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/onnx/snapshot", request)


@api_router.get("/anomalies/active")
async def iems_anomalies_active(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/anomalies/active", request)


@api_router.get("/models")
async def iems_models(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/models", request)


@api_router.get("/models/recommended")
async def iems_models_recommended(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/models/recommended", request)


@api_router.get("/models/show/{name}")
async def iems_models_show(name: str, request: Request):
    return await _forward(IEMS_BACKEND_URL,
                          "/iems/models/show/" + urllib.parse.quote(name), request)


@api_router.get("/preferences")
async def iems_preferences_get(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/preferences", request)


@api_router.post("/preferences")
async def iems_preferences_set(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/preferences", request,
                          await _body(request))


@api_router.post("/cycle")
async def iems_cycle(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/cycle", request,
                          await _body(request))


@api_router.post("/disaggregate")
async def iems_disaggregate(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/disaggregate", request,
                          await _body(request))


@api_router.post("/models/pull")
async def iems_models_pull(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/models/pull", request,
                          await _body(request))


@api_router.post("/models/test")
async def iems_models_test(request: Request):
    return await _forward(IEMS_BACKEND_URL, "/iems/models/test", request,
                          await _body(request))


@api_router.delete("/models/{name}")
async def iems_models_delete(name: str, request: Request):
    return await _forward(IEMS_BACKEND_URL,
                          "/iems/models/" + urllib.parse.quote(name), request)


@api_router.post("/recommendations/{rec_id}/accept")
async def iems_rec_accept(rec_id: str, request: Request):
    return await _forward(
        IEMS_BACKEND_URL,
        "/iems/recommendations/%s/accept" % urllib.parse.quote(rec_id),
        request, await _body(request))


@api_router.post("/recommendations/{rec_id}/defer")
async def iems_rec_defer(rec_id: str, request: Request):
    return await _forward(
        IEMS_BACKEND_URL,
        "/iems/recommendations/%s/defer" % urllib.parse.quote(rec_id),
        request, await _body(request))


@api_router.post("/recommendations/{rec_id}/dismiss")
async def iems_rec_dismiss(rec_id: str, request: Request):
    return await _forward(
        IEMS_BACKEND_URL,
        "/iems/recommendations/%s/dismiss" % urllib.parse.quote(rec_id),
        request, await _body(request))


# ── Dashboard feed passthrough ───────────────────────────────────────────────

@api_router.api_route("/dash/{path:path}",
                      methods=["GET", "POST", "PUT", "DELETE"])
async def iems_dash(path: str, request: Request):
    body = await _body(request) if request.method in ("POST", "PUT") else None
    return await _forward(IEMS_DASH_URL, "/" + path, request, body)


# ── Plugin self-description ──────────────────────────────────────────────────

@api_router.get("/")
async def iems_root():
    return {
        "plugin": "iems",
        "mode": "proxy",
        "engine": IEMS_BACKEND_URL,
        "dashboard": IEMS_DASH_URL,
        "note": "Inference runs locally in the IEMS backend container; this "
                "router forwards to it, off the event loop, so a slow IEMS "
                "query never stalls the rest of the GUI.",
    }
