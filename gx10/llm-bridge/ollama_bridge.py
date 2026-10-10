#!/usr/bin/env python3
"""Ollama-API bridge in front of an OpenAI-compatible server (NIM, vLLM,
SGLang, llama.cpp server).

Why it exists: both LLM call sites in the stack speak the Ollama API.
  - services/iems/backend/iems_ask.py          POST /api/chat
  - remote-gui plugins/mcpclient/mcp_agent.py   POST /api/chat, GET /api/tags
On the GX10, Nemotron 3.5 Lightning may be served by NIM or vLLM rather than
Ollama. This bridge lets the stack talk to it unchanged: point OLLAMA_URL /
LLM_ENDPOINT at the bridge and the bridge at the OpenAI endpoint.

If Nemotron is served by Ollama itself, skip the bridge and point the stack
straight at Ollama.

Env
  UPSTREAM_URL   OpenAI base URL, default http://host.docker.internal:8010/v1
  UPSTREAM_MODEL model id to send upstream, default
                 nvidia/nemotron-3.5-lightning-30b-a3b. Whatever model name
                 the caller sends is mapped to this one, so old defaults like
                 qwen2.5:3b-instruct keep working.
  UPSTREAM_KEY   bearer token if the server needs one
  MODEL_ALIASES  comma list also reported by /api/tags, so health checks that
                 look for the configured Ollama name pass (default
                 nemotron-3.5-lightning)
  THINKING       0 (default) disables Nemotron reasoning for fast answers
  PORT           default 11434
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("UPSTREAM_URL", "http://host.docker.internal:8010/v1").rstrip("/")
MODEL = os.environ.get("UPSTREAM_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
KEY = os.environ.get("UPSTREAM_KEY", "")
THINKING = os.environ.get("THINKING", "0") == "1"
ALIASES = [a.strip() for a in os.environ.get("MODEL_ALIASES", "nemotron-3.5-lightning").split(",") if a.strip()]
PORT = int(os.environ.get("PORT", "11434"))
TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "600"))


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        UPSTREAM + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {KEY}"} if KEY else {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def _get(path: str) -> dict:
    req = urllib.request.Request(UPSTREAM + path,
                                 headers={"Authorization": f"Bearer {KEY}"} if KEY else {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def to_openai_messages(msgs: list[dict]) -> list[dict]:
    out = []
    for m in msgs:
        m = dict(m)
        m.pop("images", None)
        calls = m.get("tool_calls")
        if calls:
            conv = []
            for c in calls:
                fn = c.get("function", {})
                args = fn.get("arguments", {})
                conv.append({"id": c.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                             "type": "function",
                             "function": {"name": fn.get("name", ""),
                                          "arguments": args if isinstance(args, str)
                                          else json.dumps(args)}})
            m["tool_calls"] = conv
            m.setdefault("content", "")
        if m.get("role") == "tool" and "tool_call_id" not in m:
            # Ollama tool messages carry no id; pair with the last call made.
            last = next((c["id"] for o in reversed(out) for c in o.get("tool_calls", [])), None)
            if last:
                m["tool_call_id"] = last
        out.append(m)
    return out


def to_ollama_message(choice: dict) -> dict:
    msg = choice.get("message", {}) or {}
    res = {"role": "assistant", "content": msg.get("content") or ""}
    calls = []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function", {})
        args = fn.get("arguments", "{}")
        try:
            args = json.loads(args) if isinstance(args, str) else args
        except json.JSONDecodeError:
            args = {"_raw": args}
        calls.append({"id": c.get("id"), "function": {"name": fn.get("name"), "arguments": args}})
    if calls:
        res["tool_calls"] = calls
    return res


def chat(body: dict) -> dict:
    opts = body.get("options") or {}
    req = {"model": MODEL, "messages": to_openai_messages(body.get("messages", [])),
           "stream": False,
           "chat_template_kwargs": {"enable_thinking": THINKING}}
    if "temperature" in opts:
        req["temperature"] = opts["temperature"]
    if "num_predict" in opts:
        req["max_tokens"] = opts["num_predict"]
    if body.get("tools"):
        req["tools"] = body["tools"]
        req["tool_choice"] = "auto"
    t0 = time.time()
    r = _post("/chat/completions", req)
    choice = (r.get("choices") or [{}])[0]
    usage = r.get("usage") or {}
    return {"model": body.get("model") or MODEL, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "message": to_ollama_message(choice), "done": True,
            "done_reason": choice.get("finish_reason", "stop"),
            "total_duration": int((time.time() - t0) * 1e9),
            "prompt_eval_count": usage.get("prompt_tokens", 0),
            "eval_count": usage.get("completion_tokens", 0)}


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, fmt, *a):
        print("[bridge]", fmt % a, flush=True)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            try:
                ids = [m["id"] for m in _get("/models").get("data", [])]
            except Exception:  # noqa: BLE001
                ids = [MODEL]
            ids += [a for a in ALIASES if a not in ids]
            return self._send(200, {"models": [{"name": i, "model": i, "size": 0,
                                                "details": {"family": "nemotron"}} for i in ids]})
        if self.path.startswith("/api/version"):
            return self._send(200, {"version": "bridge-0.1"})
        if self.path in ("/", "/health"):
            try:
                _get("/models")
                return self._send(200, {"ok": True, "upstream": UPSTREAM, "model": MODEL})
            except Exception as e:  # noqa: BLE001
                return self._send(503, {"ok": False, "upstream": UPSTREAM, "error": str(e)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._body()
            if self.path.startswith("/api/chat"):
                return self._send(200, chat(body))
            if self.path.startswith("/api/generate"):
                msgs = ([{"role": "system", "content": body["system"]}] if body.get("system") else []) \
                       + [{"role": "user", "content": body.get("prompt", "")}]
                r = chat({**body, "messages": msgs})
                return self._send(200, {"model": r["model"], "response": r["message"]["content"],
                                        "done": True})
            if self.path.startswith("/api/show"):
                return self._send(200, {"details": {"family": "nemotron"},
                                        "capabilities": ["completion", "tools"]})
            self._send(404, {"error": "not found"})
        except urllib.error.HTTPError as e:
            self._send(e.code, {"error": e.read().decode("utf-8", "replace")[:800]})
        except Exception as e:  # noqa: BLE001
            self._send(502, {"error": f"upstream: {e}"})


if __name__ == "__main__":
    print(f"[bridge] :{PORT} -> {UPSTREAM} model={MODEL} thinking={THINKING}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
