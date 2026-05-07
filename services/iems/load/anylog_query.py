"""
IEMS AnyLog query module — v4 (AnyLog-native, zero psycopg2)

ALL reads and writes go through AnyLog REST only.

READ  — AnyLog local SQL (raw socket, no destination header)
  No destination header = runs locally on the operator node.
  Python computes absolute timestamps; AnyLog's NOW() is version-unreliable.
  Partition discovery via `get partitions`. Results parsed after stripping
  AnyLog's non-standard hex chunk-size markers from the HTTP response.

WRITE — AnyLog streaming PUT
  Headers: type=json, dbms=customers, table=<table>, mode=streaming
  Table schema MUST have tsd_name CHAR(3) and tsd_id INT as columns 3-4
  (after row_id, insert_timestamp) — AnyLog auto-fills these positionally.
  AnyLog routes to the correct partition based on insert_timestamp.

DATA LAYOUT
  egauge_kafka      : partitions only (AnyLog Kafka consumer writes there)
  nilm_disaggregated: partitions only (AnyLog streaming PUT routes there)

KNOWN QUIRKS (docs/anylog_query_cookbook.md)
  - SELECT DISTINCT returns key "DISTINCT col" — use GROUP BY instead
  - IN / LIKE with parenthesized channel names → empty results; workaround:
    fetch whole time window, filter by nm client-side
  - destination:network times out (Docker hairpin NAT) — never use
  - run client () returns empty body via REST — TCP/CLI only
"""

import http.client
import json
import logging
import os
import re
import socket
import statistics
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Connection config ──────────────────────────────────────────────────────────
_AL_HOST   = os.environ.get("ANYLOG_HOST",      "127.0.0.1")
_AL_PORT   = int(os.environ.get("ANYLOG_REST_PORT", "32149"))
ANYLOG_URL = os.environ.get("ANYLOG_REST_URL",  f"http://{_AL_HOST}:{_AL_PORT}")
ANYLOG_USER_AGENT = "AnyLog/1.23"
ANYLOG_DBMS       = "customers"
ANYLOG_TABLE_LIVE = "egauge_kafka"
ANYLOG_TABLE_NILM = "nilm_disaggregated"

IEMS_PANELS = (
    "Grid Power", "Generac Power",
    "Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)", "Shop",
)
PAREN_CHANNELS = frozenset({"Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"})


# ── Raw-socket AnyLog REST ─────────────────────────────────────────────────────

def _al_request(cmd: str, method: str = "GET",
                body: bytes = b"", extra_headers: dict | None = None,
                timeout: int = 25) -> str:
    """
    Send one HTTP request to AnyLog REST using a raw socket.
    Bypasses Python's broken chunked-encoding decoder.
    Returns response body with AnyLog hex chunk-size markers stripped.
    """
    hdrs = {
        "Host":       f"{_AL_HOST}:{_AL_PORT}",
        "User-Agent": ANYLOG_USER_AGENT,
        "Connection": "close",
    }
    if cmd:
        hdrs["command"] = cmd
    if extra_headers:
        hdrs.update(extra_headers)
    if body:
        hdrs["Content-Length"] = str(len(body))

    hdr_str  = "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())
    request  = f"{method} / HTTP/1.1\r\n{hdr_str}\r\n".encode() + body

    s = socket.create_connection((_AL_HOST, _AL_PORT), timeout=timeout)
    try:
        s.sendall(request)
        s.settimeout(timeout)
        buf = b""
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    finally:
        s.close()

    raw = buf.split(b"\r\n\r\n", 1)[-1].decode(errors="replace")
    # Strip AnyLog's standalone hex chunk-size lines
    return re.sub(r"(?m)^[0-9a-fA-F]+\r?\n", "", raw).strip()


def _al_sql(sql: str, timeout: int = 25) -> list[dict]:
    """
    Execute a SQL statement locally on AnyLog. Returns list of row dicts.
    Empty list on error, empty result, or AnyLog error response.
    """
    cmd = f'sql {ANYLOG_DBMS} format=json and stat=false "{sql}"'
    raw = _al_request(cmd, timeout=timeout)
    if not raw or "Empty data set" in raw:
        return []
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("_al_sql non-JSON reply: sql=%.80s raw=%.120s", sql, raw)
        return []
    if isinstance(body, dict):
        if "Query" in body:
            return body["Query"] if isinstance(body["Query"], list) else []
        if body.get("reply", "").lower().startswith("empty"):
            return []
        if "err_text" in body:
            logger.warning("_al_sql AnyLog error: sql=%.80s body=%s", sql, body)
            return []
    return body if isinstance(body, list) else []


# ── Partition cache & discovery ────────────────────────────────────────────────

_PARTITION_CACHE: dict[str, list[tuple[str, datetime, datetime]]] = {}


def _invalidate_partition_cache(table: str | None = None) -> None:
    if table:
        _PARTITION_CACHE.pop(table, None)
    else:
        _PARTITION_CACHE.clear()


def _get_partitions(table: str) -> list[tuple[str, datetime, datetime]]:
    """
    Returns [(name, start_dt, end_dt), ...] newest first.
    Cached — call _invalidate_partition_cache() to refresh.
    """
    if table in _PARTITION_CACHE:
        return _PARTITION_CACHE[table]

    raw = _al_request(f"get partitions where dbms={ANYLOG_DBMS} and table={table}")
    parts: list[tuple[str, datetime, datetime]] = []
    for line in raw.splitlines():
        m = re.match(r"(par_[^\s|]+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            try:
                start = datetime.strptime(m.group(2), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                end   = datetime.strptime(m.group(3), "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc)
                parts.append((m.group(1), start, end))
            except ValueError:
                pass

    parts.sort(key=lambda x: x[1], reverse=True)
    _PARTITION_CACHE[table] = parts
    return parts


def _current_partition(table: str) -> str | None:
    p = _get_partitions(table)
    return p[0][0] if p else None


def _partitions_for_range(table: str, since: datetime,
                           until: datetime | None = None) -> list[str]:
    """Return partition names whose date range overlaps [since, until]."""
    until = until or datetime.now(timezone.utc)
    return [
        name for name, start, end in _get_partitions(table)
        if start <= until and end >= since
    ]


# ── NOW() rewriter ─────────────────────────────────────────────────────────────

def _rewrite_now(sql: str) -> str:
    """Replace NOW() - N unit expressions with absolute ISO timestamps."""
    now = datetime.now(timezone.utc)
    def _sub(m):
        n    = int(m.group(1))
        unit = m.group(2).lower()
        if   "min"  in unit: delta = timedelta(minutes=n)
        elif "hour" in unit: delta = timedelta(hours=n)
        else:                delta = timedelta(days=n)
        return f"'{(now - delta).strftime('%Y-%m-%d %H:%M:%S')}'"
    return re.sub(r"NOW\(\)\s*-\s*(\d+)\s*(minutes?|hours?|days?)",
                  _sub, sql, flags=re.IGNORECASE)


# ── Core query dispatcher ──────────────────────────────────────────────────────

def anylog_query(sql: str, table: str = ANYLOG_TABLE_LIVE,
                 minutes: int | None = None, **_) -> list[dict]:
    """
    Execute SQL via AnyLog local SQL, targeting correct partition(s).
    Handles partition discovery, NOW() rewriting, and multi-partition merges.
    """
    rewritten = _rewrite_now(sql)

    # Determine lookback window for partition selection
    since_match = re.search(r"'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'", rewritten)
    now = datetime.now(timezone.utc)
    since_dt = (datetime.strptime(since_match.group(1), "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=timezone.utc)) if since_match else (
                now - timedelta(hours=1))

    parts = _partitions_for_range(table, since_dt)
    if not parts:
        logger.warning("No partitions for %s since %s", table, since_dt)
        return []

    if len(parts) == 1:
        q = re.sub(rf"\b{re.escape(table)}\b", parts[0], rewritten, count=1)
        return _al_sql(q)

    # Multiple partitions — query each, deduplicate on (ts, nm)
    rows: list[dict] = []
    seen: set = set()
    for part in parts:
        q = re.sub(rf"\b{re.escape(table)}\b", part, rewritten, count=1)
        for row in _al_sql(q):
            key = (row.get("ts"), row.get("nm") or row.get("circuit") or row.get("appliance"))
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def anylog_admin(command: str, timeout: int = 15) -> str:
    """Send a local admin command (no destination). Returns raw text."""
    return _al_request(command, timeout=timeout)


# ── Public surface ─────────────────────────────────────────────────────────────

def fetch_channel(channel: str, start_iso: str, end_iso: str,
                  table: str = ANYLOG_TABLE_LIVE, **_) -> list[dict]:
    if channel in PAREN_CHANNELS:
        rows = anylog_query(
            f"SELECT ts, nm, w FROM {table} "
            f"WHERE ts >= '{start_iso}' AND ts <= '{end_iso}' ORDER BY ts ASC",
            table=table,
        )
        return [r for r in rows if r.get("nm") == channel]
    return anylog_query(
        f"SELECT ts, nm, w FROM {table} "
        f"WHERE nm = '{channel}' AND ts >= '{start_iso}' AND ts <= '{end_iso}' "
        f"ORDER BY ts ASC",
        table=table,
    )


def fetch_recent_window(channel: str, minutes: int = 30,
                        table: str = ANYLOG_TABLE_LIVE, **_) -> list[dict]:
    if channel in PAREN_CHANNELS:
        rows = anylog_query(
            f"SELECT ts, nm, w FROM {table} "
            f"WHERE ts > NOW() - {minutes} minutes ORDER BY ts ASC",
            table=table, minutes=minutes,
        )
        return [r for r in rows if r.get("nm") == channel]
    return anylog_query(
        f"SELECT ts, nm, w FROM {table} "
        f"WHERE nm = '{channel}' AND ts > NOW() - {minutes} minutes ORDER BY ts ASC",
        table=table, minutes=minutes,
    )


def fetch_all_panels_recent(minutes: int = 30, table: str = ANYLOG_TABLE_LIVE,
                             **_) -> dict[str, list[dict]]:
    """One query for all panels — avoid IN-clause and paren-channel bugs."""
    rows = anylog_query(
        f"SELECT ts, nm, w FROM {table} "
        f"WHERE ts > NOW() - {minutes} minutes ORDER BY ts ASC",
        table=table, minutes=minutes,
    )
    result: dict[str, list[dict]] = {p: [] for p in IEMS_PANELS}
    for r in rows:
        nm = r.get("nm")
        if nm in result:
            result[nm].append(r)
    return result


def fetch_all_panels(start_iso: str, end_iso: str,
                     table: str = ANYLOG_TABLE_LIVE, **_) -> dict[str, list[dict]]:
    rows = anylog_query(
        f"SELECT ts, nm, w FROM {table} "
        f"WHERE ts >= '{start_iso}' AND ts <= '{end_iso}' ORDER BY ts ASC",
        table=table,
    )
    result: dict[str, list[dict]] = {p: [] for p in IEMS_PANELS}
    for r in rows:
        nm = r.get("nm")
        if nm in result:
            result[nm].append(r)
    return result


def fetch_distinct_channels(table: str = ANYLOG_TABLE_LIVE, **_) -> list[str]:
    """Distinct channel names in the current partition."""
    part = _current_partition(table)
    if not part:
        return []
    rows = _al_sql(f"SELECT nm, COUNT(*) as cnt FROM {part} GROUP BY nm ORDER BY nm")
    return [r["nm"] for r in rows if "nm" in r]


def insert_predictions(predictions: list[dict],
                       table: str = ANYLOG_TABLE_NILM,
                       anylog_url: str = ANYLOG_URL) -> bool:
    """
    Write NILM predictions via AnyLog streaming PUT.
    AnyLog routes to the correct partition based on insert_timestamp.
    Table schema must have tsd_name/tsd_id as cols 3-4 (auto-filled by AnyLog).
    """
    if not predictions:
        return True

    payload = json.dumps(predictions).encode()
    try:
        conn = http.client.HTTPConnection(_AL_HOST, _AL_PORT, timeout=15)
        conn.request("PUT", "/", body=payload, headers={
            "User-Agent":   ANYLOG_USER_AGENT,
            "type":         "json",
            "dbms":         ANYLOG_DBMS,
            "table":        table,
            "mode":         "streaming",
            "Content-Type": "text/plain",
        })
        r    = conn.getresponse()
        body = r.read().decode(errors="replace")
        if r.status == 200 and "Success" in body:
            logger.debug("insert_predictions OK (%d rows): %s", len(predictions), body[:60])
            return True
        logger.error("insert_predictions AnyLog error: %d %s", r.status, body[:120])
        return False
    except Exception as exc:
        logger.error("insert_predictions failed: %s", exc)
        return False


def health_check(anylog_url: str = ANYLOG_URL) -> dict:
    """Ping AnyLog — count recent rows and report data freshness."""
    now  = datetime.now(timezone.utc)
    five = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    part = _current_partition(ANYLOG_TABLE_LIVE)
    if not part:
        return {"ok": False, "error": "No active partition found"}

    rows = _al_sql(
        f"SELECT MAX(ts) as latest, COUNT(*) as cnt FROM {part} WHERE ts > '{five}'"
    )
    if not rows:
        return {"ok": False, "error": "No response from AnyLog"}

    r          = rows[0]
    latest_str = str(r.get("latest") or r.get("max(ts)", ""))
    cnt        = int(r.get("cnt") or r.get("count(*)", 0) or 0)
    staleness_s = None
    if latest_str:
        try:
            dt = _parse_ts(latest_str)
            staleness_s = round((datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            pass
    return {
        "ok":            cnt > 0 and (staleness_s is None or staleness_s < 120),
        "row_count_5min": cnt,
        "latest_ts":     latest_str,
        "staleness_s":   staleness_s,
    }


def resample_to_6s(rows: list[dict]) -> list[dict]:
    """Resample to 6-second grid (LLM4NILM paper standard)."""
    if len(rows) < 2:
        return rows
    resampled = []
    for i in range(len(rows) - 1):
        t0    = _parse_ts(str(rows[i]["ts"]))
        t1    = _parse_ts(str(rows[i + 1]["ts"]))
        w0    = _tofloat(rows[i].get("w", 0))
        w1    = _tofloat(rows[i + 1].get("w", 0))
        span  = max(0.001, (t1 - t0).total_seconds())
        steps = max(1, round(span / 6))
        for s in range(steps):
            frac = s / steps
            resampled.append({"ts": _ts_str(t0 + (t1 - t0) * frac),
                               "w":  round(w0 + (w1 - w0) * frac, 2)})
    resampled.append({"ts": str(rows[-1]["ts"]), "w": _tofloat(rows[-1].get("w", 0))})
    return resampled


def build_nilm_predictions(panel: str, appliance_states: dict[str, list[int]],
                            timestamps: list[str], power_values: list[float],
                            window_start: str, window_end: str,
                            model: str = "llama3.1:8b") -> list[dict]:
    """Convert per-appliance binary state arrays to nilm_disaggregated rows."""
    records = []
    n = len(timestamps)
    for appliance, states in appliance_states.items():
        appliance = appliance.replace("_status", "")
        for i, state in enumerate(states):
            if i >= n:
                break
            lo      = max(0, i - 5)
            hi      = min(len(power_values), i + 5)
            win_w   = [abs(power_values[j]) for j in range(lo, hi) if j < len(power_values)]
            records.append({
                "ts":           str(timestamps[i]),
                "circuit":      panel,
                "appliance":    appliance,
                "state":        "ON" if state == 1 else "OFF",
                "confidence":   0.75,
                "avg_w":        round(statistics.mean(win_w),   2) if win_w else 0.0,
                "median_w":     round(statistics.median(win_w), 2) if win_w else 0.0,
                "std_w":        round(statistics.stdev(win_w),  2) if len(win_w) > 1 else 0.0,
                "window_start": window_start,
                "window_end":   window_end,
                "window_n":     n,
            })
    return records


# ── Internal helpers ───────────────────────────────────────────────────────────

def _parse_ts(ts_str: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts_str!r}")


def _ts_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _tofloat(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
