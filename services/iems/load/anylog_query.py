"""
SOLE AnyLog query module for IEMS.

Canonical REST shape — VERIFIED 2026-04-28 against live operator1:
  GET http://{anylog_url}
  Headers:
    User-Agent:  AnyLog/1.23
    destination: network
    command:     sql customers format=json and stat=false "<SQL>"

DO NOT use the "run client () sql ..." prefix. AnyLog REST rejects it with
err 156 ("Wrong HTTP method used") on GET. The destination=network header
is what routes the query through the cluster — "run client ()" is a
Native-CLI construct that is not accepted by REST.

KNOWN UNRELIABLE — do not use:
  - IN clause with parenthesized literals: WHERE nm IN ('Panel1 (HVAC)', ...)
    → causes IncompleteRead; use a single time-bounded query and partition
      client-side by `nm`
  - LIKE with wildcards: WHERE nm LIKE '%Panel%' → IncompleteRead
  - WHERE nm = '<paren-channel>' for Panel1 (HVAC) / Panel2 (H2O) /
    Panel3 (Kitchen) → returns empty data set (parser quirk)

PAREN_CHANNELS (literals that need the time-only-then-filter workaround):
  Panel1 (HVAC), Panel2 (H2O), Panel3 (Kitchen)

Admin commands (get columns, get tables, etc.) omit the destination header.

nilm_disaggregated schema (discovered live):
  ts, circuit, appliance, state, confidence,
  avg_w, median_w, std_w, window_start, window_end, window_n
"""
import http.client
import json
import logging
import os
import statistics
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

ANYLOG_URL = os.environ.get("ANYLOG_REST_URL", "http://host.docker.internal:32149")
ANYLOG_USER_AGENT = "AnyLog/1.23"
ANYLOG_DBMS = "customers"
ANYLOG_TABLE_LIVE = "egauge_kafka"
ANYLOG_TABLE_NILM = "nilm_disaggregated"

# Panels tracked by the IEMS
IEMS_PANELS = (
    "Grid Power",
    "Generac Power",
    "Panel1 (HVAC)",
    "Panel2 (H2O)",
    "Panel3 (Kitchen)",
    "Shop",
)

# Channel names that contain parentheses — AnyLog parser fails on
# `WHERE nm = '<paren-channel>'`. Use the time-only fetch + client-side
# filter workaround for these.
PAREN_CHANNELS = frozenset({
    "Panel1 (HVAC)",
    "Panel2 (H2O)",
    "Panel3 (Kitchen)",
})


# ─── Core helper ─────────────────────────────────────────────────────────────

def anylog_query(
    sql: str,
    anylog_url: str = ANYLOG_URL,
    timeout: int = 60,
) -> list[dict]:
    """
    Execute a SQL query via AnyLog REST.

    Verified shape (2026-04-28): the REST endpoint accepts only the bare
    `sql <dbms> ...` command form. The `run client ()` prefix returns
    err 156 ("Wrong HTTP method used"). The destination=network header is
    what fans the query out to remote operators.

    Returns the Query list; empty list on any error or empty result.
    """
    cmd = f'sql {ANYLOG_DBMS} format=json and stat=false "{sql}"'
    req = urllib.request.Request(anylog_url)
    req.add_header("User-Agent",  ANYLOG_USER_AGENT)
    req.add_header("destination", "network")
    req.add_header("command",     cmd)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except http.client.IncompleteRead as exc:
        logger.warning("anylog_query IncompleteRead — sql=%s — treating as empty", sql[:80])
        return []
    except Exception as exc:
        logger.error("anylog_query failed — sql=%s error=%s", sql[:120], exc)
        return []
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("anylog_query non-JSON reply — sql=%s — raw=%s", sql[:80], raw[:120])
        return []
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        if "Query" in body:
            return body["Query"]
        if body.get("reply", "").lower().startswith("empty"):
            return []
    return []


def anylog_admin(command: str, anylog_url: str = ANYLOG_URL, timeout: int = 30) -> str:
    """
    Send a local admin command (no destination: network).
    Returns raw response text.
    """
    req = urllib.request.Request(anylog_url)
    req.add_header("User-Agent", ANYLOG_USER_AGENT)
    req.add_header("command",    command)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.error("anylog_admin failed — cmd=%s error=%s", command, exc)
        return ""


# ─── Public surface ───────────────────────────────────────────────────────────

def fetch_channel(
    channel: str,
    start_iso: str,
    end_iso: str,
    table: str = ANYLOG_TABLE_LIVE,
    anylog_url: str = ANYLOG_URL,
) -> list[dict]:
    """
    Fetch rows for a single channel between two ISO timestamps.
    Paren channels use a time-only fetch + client-side filter.
    """
    if channel in PAREN_CHANNELS:
        sql = (
            f"SELECT ts, nm, w FROM {table} "
            f"WHERE ts >= '{start_iso}' AND ts <= '{end_iso}' "
            f"ORDER BY ts ASC"
        )
        rows = anylog_query(sql, anylog_url=anylog_url)
        return [r for r in rows if r.get("nm") == channel]

    sql = (
        f"SELECT ts, nm, w FROM {table} "
        f"WHERE nm = '{channel}' "
        f"AND ts >= '{start_iso}' AND ts <= '{end_iso}' "
        f"ORDER BY ts ASC"
    )
    return anylog_query(sql, anylog_url=anylog_url)


def fetch_recent_window(
    channel: str,
    minutes: int = 30,
    table: str = ANYLOG_TABLE_LIVE,
    anylog_url: str = ANYLOG_URL,
) -> list[dict]:
    """
    Fetch the last N minutes of data for a single channel.
    Paren channels (Panel1/2/3) use the time-only fetch + client-side
    filter workaround for the parser quirk documented in
    docs/anylog_query_cookbook.md.
    """
    if channel in PAREN_CHANNELS:
        sql = (
            f"SELECT ts, nm, w FROM {table} "
            f"WHERE ts > NOW() - {minutes} minutes "
            f"ORDER BY ts ASC"
        )
        rows = anylog_query(sql, anylog_url=anylog_url)
        return [r for r in rows if r.get("nm") == channel]

    sql = (
        f"SELECT ts, nm, w FROM {table} "
        f"WHERE nm = '{channel}' "
        f"AND ts > NOW() - {minutes} minutes "
        f"ORDER BY ts ASC"
    )
    return anylog_query(sql, anylog_url=anylog_url)


def fetch_all_panels_recent(
    minutes: int = 30,
    anylog_url: str = ANYLOG_URL,
    table: str = ANYLOG_TABLE_LIVE,
) -> dict[str, list[dict]]:
    """
    Fetch last N minutes for all IEMS panels in a single round-trip.
    One time-bounded query, then partition rows by `nm` client-side.
    Sidesteps both the IN-clause parser bug and the per-channel paren bug.
    """
    sql = (
        f"SELECT ts, nm, w FROM {table} "
        f"WHERE ts > NOW() - {minutes} minutes "
        f"ORDER BY ts ASC"
    )
    rows = anylog_query(sql, anylog_url=anylog_url)
    result: dict[str, list[dict]] = {p: [] for p in IEMS_PANELS}
    for r in rows:
        nm = r.get("nm")
        if nm in result:
            result[nm].append(r)
    return result


def fetch_all_panels(
    start_iso: str,
    end_iso: str,
    anylog_url: str = ANYLOG_URL,
    table: str = ANYLOG_TABLE_LIVE,
) -> dict[str, list[dict]]:
    """
    Fetch rows for all IEMS panels between two ISO timestamps.
    Same workaround as fetch_all_panels_recent: one time-bounded query,
    partition by `nm` client-side.
    """
    sql = (
        f"SELECT ts, nm, w FROM {table} "
        f"WHERE ts >= '{start_iso}' AND ts <= '{end_iso}' "
        f"ORDER BY ts ASC"
    )
    rows = anylog_query(sql, anylog_url=anylog_url)
    result: dict[str, list[dict]] = {p: [] for p in IEMS_PANELS}
    for r in rows:
        nm = r.get("nm")
        if nm in result:
            result[nm].append(r)
    return result


def fetch_distinct_channels(
    table: str = ANYLOG_TABLE_LIVE,
    anylog_url: str = ANYLOG_URL,
) -> list[str]:
    sql = f"SELECT DISTINCT nm FROM {table} ORDER BY nm"
    rows = anylog_query(sql, anylog_url=anylog_url)
    return [r["nm"] for r in rows if "nm" in r]


def insert_predictions(
    predictions: list[dict],
    table: str = ANYLOG_TABLE_NILM,
    anylog_url: str = ANYLOG_URL,
) -> bool:
    """
    Insert NILM disaggregated predictions into nilm_disaggregated.

    Each prediction dict must have these keys (matching discovered schema):
      ts, circuit, appliance, state, confidence,
      avg_w, median_w, std_w, window_start, window_end, window_n

    Uses AnyLog streaming ingestion: PUT / with command header.
    """
    if not predictions:
        return True

    payload = json.dumps(predictions).encode("utf-8")
    cmd = f"data put where dbms={ANYLOG_DBMS} and table={table} and mode=streaming and format=json"
    req = urllib.request.Request(anylog_url, data=payload, method="PUT")
    req.add_header("User-Agent",   ANYLOG_USER_AGENT)
    req.add_header("command",      cmd)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = resp.read().decode("utf-8", errors="replace")
        logger.debug("insert_predictions OK: %s", result[:100])
        return True
    except Exception as exc:
        logger.error("insert_predictions failed: %s", exc)
        return False


def resample_to_6s(rows: list[dict]) -> list[dict]:
    """
    Resample rows (any interval) to 6-second grid via linear interpolation.
    LLM4NILM paper standard input cadence.
    """
    if len(rows) < 2:
        return rows

    resampled = []
    for i in range(len(rows) - 1):
        t0 = _parse_ts(rows[i]["ts"])
        t1 = _parse_ts(rows[i + 1]["ts"])
        w0 = _tofloat(rows[i].get("w", 0))
        w1 = _tofloat(rows[i + 1].get("w", 0))
        span_s = max(0.001, (t1 - t0).total_seconds())
        steps = max(1, round(span_s / 6))
        for s in range(steps):
            frac = s / steps
            resampled.append({
                "ts": _ts_str(t0 + (t1 - t0) * frac),
                "w": round(w0 + (w1 - w0) * frac, 2),
            })

    resampled.append({"ts": rows[-1]["ts"], "w": _tofloat(rows[-1].get("w", 0))})
    return resampled


def health_check(anylog_url: str = ANYLOG_URL) -> dict:
    """
    Ping AnyLog: count rows in egauge_kafka in the last 5 minutes,
    and report the freshness of the most recent row.
    Returns {ok, row_count_5min, latest_ts, staleness_s, error?}
    """
    rows = anylog_query(
        f"SELECT MAX(ts) as latest, COUNT(*) as cnt FROM {ANYLOG_TABLE_LIVE} "
        f"WHERE ts > NOW() - 5 minutes",
        anylog_url=anylog_url,
    )
    if not rows:
        return {"ok": False, "error": "No response from AnyLog"}

    r = rows[0]
    latest_str = r.get("latest") or r.get("max(ts)", "")
    cnt = int(r.get("cnt") or r.get("count(*)", 0) or 0)

    staleness_s = None
    if latest_str:
        try:
            latest_dt = _parse_ts(latest_str)
            staleness_s = round((datetime.now(timezone.utc) - latest_dt).total_seconds())
        except Exception:
            pass

    ok = cnt > 0 and (staleness_s is None or staleness_s < 120)
    return {
        "ok": ok,
        "row_count_5min": cnt,
        "latest_ts": latest_str,
        "staleness_s": staleness_s,
    }


def build_nilm_predictions(
    panel: str,
    appliance_states: dict[str, list[int]],
    timestamps: list[str],
    power_values: list[float],
    window_start: str,
    window_end: str,
    model: str = "mistral:7b",
) -> list[dict]:
    """
    Convert per-appliance binary state arrays to nilm_disaggregated rows.
    Uses the ACTUAL discovered schema.
    """
    records = []
    n = len(timestamps)

    for appliance, states in appliance_states.items():
        if appliance == "vacuum_cleaner_status":
            appliance = "vacuum_cleaner"
        else:
            appliance = appliance.replace("_status", "")

        for i, state in enumerate(states):
            if i >= n:
                break
            ts = timestamps[i] if i < len(timestamps) else window_end

            # compute stats from the surrounding window
            lo = max(0, i - 5)
            hi = min(len(power_values), i + 5)
            window_w = [abs(power_values[j]) for j in range(lo, hi) if j < len(power_values)]
            avg_w = round(statistics.mean(window_w), 2) if window_w else 0.0
            median_w = round(statistics.median(window_w), 2) if window_w else 0.0
            std_w = round(statistics.stdev(window_w), 2) if len(window_w) > 1 else 0.0

            records.append({
                "ts":           ts,
                "circuit":      panel,
                "appliance":    appliance,
                "state":        "ON" if state == 1 else "OFF",
                "confidence":   0.75,
                "avg_w":        avg_w,
                "median_w":     median_w,
                "std_w":        std_w,
                "window_start": window_start,
                "window_end":   window_end,
                "window_n":     n,
            })

    return records


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _parse_ts(ts_str: str) -> datetime:
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
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
