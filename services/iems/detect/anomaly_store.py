#!/usr/bin/env python3
"""Persist anomalies to AnyLog (customers.anomalies) and read them back.

Writes via the same streaming PUT path as nilm_disaggregated, so AnyLog routes
rows to the right partition from insert_timestamp and infers the schema from the
first payload. Field types must stay stable across writes -- AnyLog fixes the
column types on table creation, and a later int-where-float will be rejected.

Schema written here:
    ts            timestamp   when the anomaly was observed
    atype         varchar     breaker_margin | leg_dropout | leak_* | spike_* ...
    severity      varchar     critical | warning | info
    source        varchar     detector that produced it
    entity        varchar     register / group / appliance it concerns
    value         float       observed measurement
    threshold     float       what it was compared against
    pct           float       value as % of threshold
    sustained_s   int         how long the condition had held
    status        varchar     open | cleared
    fingerprint   varchar     stable dedup key (atype:entity)
    notified      varchar     no | email | sms | both
    message       varchar     human-readable summary
    action        varchar     recommended response

Usage:
    from iems.detect.anomaly_store import write_anomalies, recent_anomalies
"""
from __future__ import annotations

import http.client
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, "services")
from iems.load.anylog_query import (  # noqa: E402
    ANYLOG_DBMS, ANYLOG_USER_AGENT, _AL_HOST, _AL_PORT, anylog_query,
)

log = logging.getLogger("anomaly_store")

TABLE = "anomalies"

# Column order/types are load-bearing: see module docstring.
_FLOAT_FIELDS = ("value", "threshold", "pct")
_INT_FIELDS = ("sustained_s",)
_STR_FIELDS = ("atype", "severity", "source", "entity", "status",
               "fingerprint", "notified", "message", "action")


def fingerprint(atype: str, entity: str) -> str:
    """Stable identity for an ongoing condition, used for dedup and clearing."""
    return "%s:%s" % (atype, entity)


def normalise(event: dict[str, Any]) -> dict[str, Any]:
    """Coerce a detector event into the fixed anomalies schema.

    Detectors emit whatever shape suits them; this is the single place that
    decides what actually lands in the table. Missing fields get typed defaults
    rather than nulls, because AnyLog infers column types from the first row and
    a null there would poison the schema.
    """
    ts = event.get("ts") or datetime.now(timezone.utc).isoformat()
    if isinstance(ts, datetime):
        ts = ts.isoformat()
    # AnyLog wants "YYYY-MM-DD HH:MM:SS.ffffff", not ISO-8601 with T/Z.
    ts = str(ts).replace("T", " ").replace("Z", "").split("+")[0]

    atype = str(event.get("type") or event.get("atype") or "unknown")
    entity = str(event.get("group") or event.get("entity")
                 or event.get("label") or "")

    row = {
        "ts": ts,
        "atype": atype,
        "severity": str(event.get("severity") or "info"),
        "source": str(event.get("source") or "breaker_margin"),
        "entity": entity,
        "value": float(event.get("amps") or event.get("value") or 0.0),
        "threshold": float(event.get("rating_amps") or event.get("threshold") or 0.0),
        "pct": float(event.get("pct_of_rating") or event.get("pct") or 0.0),
        "sustained_s": int(event.get("sustained_seconds") or event.get("sustained_s") or 0),
        "status": str(event.get("status")
                      or ("cleared" if atype.endswith("_clear") else "open")),
        "fingerprint": str(event.get("fingerprint")
                           or fingerprint(atype.replace("_clear", ""), entity)),
        "notified": str(event.get("notified") or "no"),
        "message": str(event.get("message") or "")[:900],
        "action": str(event.get("action") or "")[:900],
    }
    for f in _FLOAT_FIELDS:
        row[f] = float(row[f])
    for f in _INT_FIELDS:
        row[f] = int(row[f])
    for f in _STR_FIELDS:
        row[f] = str(row[f])
    return row


def write_anomalies(events: list[dict[str, Any]], table: str = TABLE,
                    timeout: int = 15) -> bool:
    """Streaming PUT into AnyLog. Returns True on success."""
    if not events:
        return True
    rows = [normalise(e) for e in events]
    payload = json.dumps(rows).encode()
    try:
        conn = http.client.HTTPConnection(_AL_HOST, _AL_PORT, timeout=timeout)
        conn.request("PUT", "/", body=payload, headers={
            "User-Agent": ANYLOG_USER_AGENT,
            "type": "json",
            "dbms": ANYLOG_DBMS,
            "table": table,
            "mode": "streaming",
            "Content-Type": "text/plain",
        })
        r = conn.getresponse()
        body = r.read().decode(errors="replace")
        if r.status == 200 and "Success" in body:
            log.info("wrote %d anomaly row(s) to %s.%s", len(rows), ANYLOG_DBMS, table)
            return True
        log.error("anomaly write rejected: %d %s", r.status, body[:200])
        return False
    except Exception as exc:
        log.error("anomaly write failed: %s", exc)
        return False


def recent_anomalies(minutes: int = 1440, table: str = TABLE) -> list[dict]:
    """Read anomalies from the last `minutes`, newest first."""
    rows = anylog_query(
        "SELECT ts, atype, severity, source, entity, value, threshold, pct, "
        "sustained_s, status, fingerprint, notified, message, action "
        f"FROM {table} WHERE ts > NOW() - {minutes} minutes ORDER BY ts ASC",
        table=table, minutes=minutes,
    ) or []
    return list(reversed(rows))


def open_anomalies(minutes: int = 1440, table: str = TABLE) -> list[dict]:
    """Anomalies still open: latest row per fingerprint with status != cleared.

    Done client-side deliberately. AnyLog does not support the window function
    this would need, and the row volume here is tiny (tens per day), so pulling
    and folding in Python is both simpler and correct.
    """
    latest: dict[str, dict] = {}
    for r in reversed(recent_anomalies(minutes, table)):   # oldest -> newest
        fp = r.get("fingerprint")
        if fp:
            latest[fp] = r
    return [r for r in latest.values() if r.get("status") != "cleared"]


def _selftest() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc).isoformat()
    probe = {
        "ts": now,
        "type": "selftest",
        "severity": "info",
        "source": "anomaly_store",
        "entity": "selftest",
        "value": 1.0,
        "threshold": 2.0,
        "pct": 50.0,
        "sustained_s": 0,
        "message": "anomaly_store round-trip probe",
        "action": "none",
    }
    print("normalised row:")
    print(json.dumps(normalise(probe), indent=2))
    ok = write_anomalies([probe])
    print("write ok:", ok)
    if not ok:
        return 1
    import time
    time.sleep(3)
    rows = recent_anomalies(60)
    print("read back %d row(s) from last 60 min" % len(rows))
    for r in rows[:5]:
        print("  ", r.get("ts"), r.get("atype"), r.get("severity"), r.get("entity"))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
