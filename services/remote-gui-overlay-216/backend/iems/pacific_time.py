"""Show AnyLog timestamps in Pacific time at the GUI's API boundary.

AnyLog stores and returns naive UTC ("2026-09-24 07:00:12.000000"). Browsers
parse that form as local time, so the GUI's charts and tables showed UTC digits
as though they were local. This middleware rewrites every such value in the JSON
responses of the data routes to ISO-8601 with the Pacific offset
("2026-09-24T00:00:12.000000-07:00"): an exact instant any browser parses
correctly, and plainly Pacific in a raw table. A request to the same routes gets
the inverse, so a time the UI sends back reaches AnyLog as naive UTC again.

Nothing stored is changed. Policy and metadata routes are left alone on purpose:
the Metadata Manager compares a policy byte for byte before replacing it.
"""
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
DATA_ROUTES = {"/send-command", "/uns/query-table", "/uns/query-custom", "/uns/column-details"}
_NAIVE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d{1,6})?$")
_AWARE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$")


def _parse(text):
    return datetime.fromisoformat(text.replace(" ", "T").replace("Z", "+00:00"))


def to_pacific(value):
    """Naive UTC string -> ISO-8601 in Pacific time with its offset."""
    if isinstance(value, str) and _NAIVE.match(value):
        try:
            dt = _parse(value).replace(tzinfo=timezone.utc).astimezone(PACIFIC)
            return dt.isoformat(timespec="microseconds" if "." in value else "seconds")
        except ValueError:
            return value
    return value


def to_utc_naive(value):
    """ISO-8601 with an offset or Z -> the naive UTC form AnyLog expects."""
    if isinstance(value, str) and _AWARE.match(value):
        try:
            dt = _parse(value).astimezone(timezone.utc)
            fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in value else "%Y-%m-%d %H:%M:%S"
            return dt.strftime(fmt)
        except ValueError:
            return value
    return value


def _walk(obj, fn):
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, fn) for v in obj]
    return fn(obj)


def _rewrite(body, fn):
    if not body:
        return body
    try:
        return json.dumps(_walk(json.loads(body), fn)).encode()
    except (ValueError, TypeError):
        return body


class PacificTimeMiddleware:
    """Pure ASGI, so streamed responses elsewhere in the app are untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").rstrip("/") if scope.get("type") == "http" else ""
        if path not in DATA_ROUTES:
            return await self.app(scope, receive, send)

        chunks, more = [], True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = _rewrite(b"".join(chunks), to_utc_naive)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        start, parts = None, []

        async def capture(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            if message["type"] != "http.response.body":
                return await send(message)
            parts.append(message.get("body", b""))
            if message.get("more_body"):
                return
            data = b"".join(parts)
            headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
            if b"json" in dict((k.lower(), v) for k, v in headers).get(b"content-type", b""):
                data = _rewrite(data, to_pacific)
            headers.append((b"content-length", str(len(data)).encode()))
            await send(dict(start, headers=headers))
            await send({"type": "http.response.body", "body": data, "more_body": False})

        await self.app(scope, replay, capture)


def install():
    """Attach to the running FastAPI app. Plugins are imported by load_plugins(app)
    while main is still initialising, before the middleware stack is built."""
    import sys
    from fastapi import FastAPI
    for name, module in list(sys.modules.items()):
        app = getattr(module, "app", None)
        if isinstance(app, FastAPI) and name.split(".")[-1] == "main":
            app.add_middleware(PacificTimeMiddleware)
            return name
    return None
