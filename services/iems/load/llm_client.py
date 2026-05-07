"""
Full Ollama HTTP API wrapper.
Also supports llama.cpp (OpenAI-compatible endpoint).
"""
import json
import logging
import os
import time
import urllib.request
from typing import Generator

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
LLAMA_CPP_URL = "http://127.0.0.1:8080"
DEFAULT_MODEL = "mistral:7b"
SMALL_MODEL_THRESHOLD_B = 7

RECOMMENDED_MODELS = [
    "mistral:7b",
    "llama3.1:8b",
    "deepseek-r1:7b",
    "qwen2.5:7b",
    "phi3:mini",
    "gemma2:9b",
]


# ── Internal ──────────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _http_post(url: str, body: dict, timeout: int = 120) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _http_delete(url: str, body: dict, timeout: int = 30) -> bool:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="DELETE",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _warn_small(model: str) -> None:
    try:
        size_b = int(model.split(":")[-1].rstrip("b"))
        if size_b < SMALL_MODEL_THRESHOLD_B:
            logger.warning(
                "Model %s < %dB — LLM4NILM paper observed format errors at "
                "high window sizes with small models.",
                model, SMALL_MODEL_THRESHOLD_B,
            )
    except (ValueError, IndexError):
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def list_models(base_url: str = OLLAMA_URL) -> list[dict]:
    """GET /api/tags → [{name, size_gb, digest, modified_at, family,
                          parameter_size, quantization}]"""
    try:
        data = _http_get(f"{base_url}/api/tags", timeout=8)
        result = []
        for m in data.get("models", []):
            details = m.get("details", {})
            result.append({
                "name":           m.get("name", ""),
                "size_gb":        round(m.get("size", 0) / 1e9, 2),
                "digest":         m.get("digest", "")[:12],
                "modified_at":    m.get("modified_at", ""),
                "family":         details.get("family", ""),
                "parameter_size": details.get("parameter_size", ""),
                "quantization":   details.get("quantization_level", ""),
            })
        return result
    except Exception as exc:
        logger.warning("list_models failed: %s", exc)
        return []


# Alias used by the IEMS plugin router's /iems/health implementation.
list_ollama_models = list_models


def pull_model_stream(
    model: str,
    base_url: str = OLLAMA_URL,
) -> Generator[dict, None, None]:
    """
    POST /api/pull  {"name": model, "stream": true}
    Yields each NDJSON line as a dict: {status, digest?, total?, completed?}
    """
    payload = json.dumps({"name": model, "stream": True}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/pull",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    yield {"status": line}
    except Exception as exc:
        yield {"error": str(exc), "status": "failed"}


def delete_model(model: str, base_url: str = OLLAMA_URL) -> bool:
    """DELETE /api/delete {"name": model}"""
    return _http_delete(f"{base_url}/api/delete", {"name": model})


def show_model(model: str, base_url: str = OLLAMA_URL) -> dict:
    """POST /api/show {"name": model} → license, modelfile, parameters, template, details"""
    try:
        return _http_post(f"{base_url}/api/show", {"name": model}, timeout=15)
    except Exception as exc:
        logger.warning("show_model failed: %s", exc)
        return {"error": str(exc)}


def call_chat(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    base_url: str = OLLAMA_URL,
    response_format: str = "json",
    timeout: int = 120,
) -> str:
    """POST /api/chat → message content string."""
    _warn_small(model)
    data = _http_post(
        f"{base_url}/api/chat",
        {"model": model, "messages": messages, "stream": False, "format": response_format},
        timeout=timeout,
    )
    return data.get("message", {}).get("content", "")


def call_ollama(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    base_url: str = OLLAMA_URL,
    timeout: int = 120,
) -> str:
    """Alias for call_chat — used by disaggregator."""
    return call_chat(messages, model=model, base_url=base_url, timeout=timeout)


def call_llama_cpp(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    base_url: str = LLAMA_CPP_URL,
    timeout: int = 120,
) -> str:
    """POST /v1/chat/completions (OpenAI-compatible llama.cpp)."""
    _warn_small(model)
    data = _http_post(
        f"{base_url}/v1/chat/completions",
        {"model": model, "messages": messages,
         "response_format": {"type": "json_object"}},
        timeout=timeout,
    )
    return data["choices"][0]["message"]["content"]


def diag_ping(model: str = DEFAULT_MODEL, base_url: str = OLLAMA_URL) -> dict:
    """
    Send a trivial JSON-output prompt and measure round-trip latency.
    Returns {ok, latency_ms, model, raw}
    """
    messages = [
        {"role": "system", "content": "Respond with valid JSON only."},
        {"role": "user",   "content": 'Reply with exactly {"ok": true}'},
    ]
    start = time.monotonic()
    try:
        raw = call_chat(messages, model=model, base_url=base_url, timeout=30)
        latency_ms = round((time.monotonic() - start) * 1000)
        ok = '"ok"' in raw and "true" in raw.lower()
        return {"ok": ok, "latency_ms": latency_ms, "model": model, "raw": raw[:200]}
    except Exception as exc:
        return {"ok": False, "latency_ms": -1, "model": model, "error": str(exc)}


def test_model_latency(
    model: str = DEFAULT_MODEL,
    backend: str = "ollama",
    base_url: str = OLLAMA_URL,
) -> dict:
    """Compatibility alias used by the API router."""
    return diag_ping(model=model, base_url=base_url)
