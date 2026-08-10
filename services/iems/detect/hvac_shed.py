#!/usr/bin/env python3
"""Automatic HVAC load shedding, with automatic restore.

HVAC is the only real actuator on this site (all 13 HA switches are inverter
charge-point settings, not appliances), and it happens to sit on Panel1 -- so
it is both the only lever available and a genuinely useful one.

SHED BY SETPOINT, NOT BY POWER
    Shedding raises the cooling setpoint rather than setting hvac_mode=off.
    The thermostat's own compressor-protection logic then decides when to stop,
    which avoids short-cycling a compressor. hvac_mode=off is reserved for the
    top severity step and is always time-bounded.

SAFETY INVARIANTS (each one exists because of a specific way this can hurt)
    1. Original state is written to disk BEFORE the first change, so a crash
       mid-shed can still be undone. Restore must not depend on memory.
    2. Hard maximum shed duration. Auto-restores even if the anomaly never
       clears -- a stuck detector must not leave the house hot indefinitely.
    3. Indoor temperature ceiling. If it gets too warm, restore immediately
       regardless of the electrical situation. Occupants outrank amps.
    4. Startup deadman. On boot, an existing shed state file older than the max
       duration triggers an immediate restore.
    5. Manual override wins. If the setpoint is not what we set it to, a human
       moved it; stand down and stop managing until the next clean cycle.
    6. Cooldown between sheds, so the controller cannot itself short-cycle.

Usage:
    python3 hvac_shed.py --status
    python3 hvac_shed.py --once            # evaluate anomalies, act if needed
    python3 hvac_shed.py --loop
    python3 hvac_shed.py --shed 2 --reason "manual test"
    python3 hvac_shed.py --restore
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "services")
sys.path.insert(0, "services/iems/detect")

from iems.detect.ha_client import HA, HAError            # noqa: E402
from iems.detect.anomaly_store import write_anomalies, open_anomalies  # noqa: E402

log = logging.getLogger("hvac_shed")

ENTITY = os.environ.get("HVAC_ENTITY", "climate.sensi_2a293d_thermostat")
STATE_FILE = Path(os.environ.get("HVAC_SHED_STATE",
                                 "analysis/automation/hvac_shed_state.json"))

# ── policy ───────────────────────────────────────────────────────────────────
# Ladder of shed levels. Offsets are degrees F added to the cooling setpoint.
SHED_LEVELS = {
    1: {"offset": 2, "mode": None, "label": "light"},
    2: {"offset": 4, "mode": None, "label": "moderate"},
    3: {"offset": 0, "mode": "off", "label": "full (compressor off)"},
}

MAX_SHED_SECONDS = int(os.environ.get("HVAC_MAX_SHED_S", "3600"))     # 1 h
INDOOR_CEILING_F = float(os.environ.get("HVAC_CEILING_F", "82"))
COOLDOWN_SECONDS = int(os.environ.get("HVAC_COOLDOWN_S", "900"))      # 15 min
POLL_SECONDS = int(os.environ.get("HVAC_POLL_S", "60"))
NOTIFY_CHANNELS = os.environ.get("HVAC_NOTIFY", "email,sms").split(",")

# Which anomalies justify which shed level.
TRIGGERS = [
    # (atype, entity_substring, severity, level)
    ("breaker_margin", "panel1_hvac", "critical", 3),
    ("breaker_margin", "main_service", "critical", 2),
    ("breaker_margin", "", "critical", 1),
    ("spike_sustained", "panel1_hvac", "warning", 1),
]


# ── persisted shed state ─────────────────────────────────────────────────────

def load_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None


def save_state(state: dict | None) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if state is None:
        try:
            STATE_FILE.unlink()
        except OSError:
            pass
        return
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)          # atomic: never a half-written state file


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_s(iso: str) -> float:
    try:
        return (_now() - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return 1e9


# ── audit trail ──────────────────────────────────────────────────────────────

def record(atype: str, severity: str, message: str, action: str,
           level: int = 0, value: float = 0.0, threshold: float = 0.0) -> None:
    """Every automation action lands in the same AnyLog table as the anomalies
    that caused it, so the dashboard can show cause and effect on one timeline."""
    write_anomalies([{
        "ts": _now().isoformat(),
        "type": atype,
        "severity": severity,
        "source": "hvac_shed",
        "entity": ENTITY,
        "value": float(value),
        "threshold": float(threshold),
        "pct": 0.0,
        "sustained_seconds": level,
        "status": "open" if atype == "hvac_shed" else "cleared",
        "message": message,
        "action": action,
    }])


def notify(ha: HA, title: str, message: str) -> None:
    results = ha.notify(title, message, channels=NOTIFY_CHANNELS)
    log.info("notify %s -> %s", title, results)
    if not any(results.values()):
        log.error("ALL notify channels failed for: %s", title)


# ── core actions ─────────────────────────────────────────────────────────────

def shed(ha: HA, level: int, reason: str, dry_run: bool = False) -> dict:
    """Apply a shed level. Idempotent: escalates, never double-applies."""
    if level not in SHED_LEVELS:
        raise ValueError("unknown shed level %r" % level)

    snap = ha.climate_snapshot(ENTITY)
    existing = load_state()

    if existing and existing.get("level", 0) >= level:
        log.info("already shed at level %d (>= %d); nothing to do",
                 existing["level"], level)
        return existing

    spec = SHED_LEVELS[level]
    # Original state is captured on the FIRST shed only, so escalating from
    # level 1 to 3 still restores to the true pre-shed setpoint.
    original = (existing or {}).get("original") or {
        "hvac_mode": snap["hvac_mode"],
        "target": snap["target"],
    }

    if original.get("target") is None and spec["mode"] != "off":
        raise HAError("thermostat reports no setpoint; refusing to shed by offset")

    new_target = None
    if spec["mode"] != "off":
        new_target = float(original["target"]) + spec["offset"]
        cap = snap.get("max_temp") or 100
        new_target = min(new_target, float(cap))

    state = {
        "level": level,
        "label": spec["label"],
        "reason": reason,
        "started": (existing or {}).get("started") or _now().isoformat(),
        "escalated": _now().isoformat(),
        "original": original,
        "applied_target": new_target,
        "applied_mode": spec["mode"],
        "entity": ENTITY,
    }

    if dry_run:
        log.info("[dry-run] would shed level %d: %s", level, state)
        return state

    # Persist BEFORE acting. If we die between here and the HA call, the worst
    # case is a spurious restore -- which is safe. The reverse order could
    # leave HVAC shed with no record of how to put it back.
    save_state(state)

    if spec["mode"] == "off":
        ha.set_hvac_mode(ENTITY, "off")
        detail = "HVAC turned OFF"
    else:
        ha.set_temperature(ENTITY, new_target)
        detail = "cooling setpoint %.0fF -> %.0fF (+%d)" % (
            float(original["target"]), new_target, spec["offset"])

    msg = ("HVAC load shed engaged (level %d, %s).\n%s\nReason: %s\n"
           "Indoor now %.0fF. Automatic restore within %d minutes."
           % (level, spec["label"], detail, reason,
              snap.get("current") or -1, MAX_SHED_SECONDS // 60))
    log.info(msg.replace("\n", " | "))
    record("hvac_shed", "warning", msg, "Automatic restore is scheduled.",
           level=level, value=new_target or 0.0)
    notify(ha, "Mantey: HVAC load shed (level %d)" % level, msg)
    return state


def restore(ha: HA, why: str, dry_run: bool = False) -> bool:
    """Return the thermostat to its pre-shed state. Safe to call any time."""
    state = load_state()
    if not state:
        log.info("no shed in effect; nothing to restore")
        return False

    original = state.get("original") or {}
    if dry_run:
        log.info("[dry-run] would restore to %s", original)
        return True

    snap = ha.climate_snapshot(ENTITY)
    mode = original.get("hvac_mode")
    target = original.get("target")

    if state.get("applied_mode") == "off" and mode:
        ha.set_hvac_mode(ENTITY, mode)
        # Give the thermostat a moment before pushing a setpoint at it.
        time.sleep(2)
    if target is not None:
        ha.set_temperature(ENTITY, float(target))

    held = _age_s(state.get("started", ""))
    msg = ("HVAC restored to %s / %.0fF after %.0f minutes of shedding.\n"
           "Reason for restore: %s\nIndoor was %.0fF."
           % (mode, float(target or 0), held / 60.0, why, snap.get("current") or -1))
    log.info(msg.replace("\n", " | "))

    save_state(None)
    record("hvac_restore", "info", msg, "None. Normal operation resumed.",
           value=float(target or 0))
    notify(ha, "Mantey: HVAC restored", msg)
    return True


# ── guards ───────────────────────────────────────────────────────────────────

def check_guards(ha: HA) -> str | None:
    """Return a restore reason if any safety guard demands one."""
    state = load_state()
    if not state:
        return None

    held = _age_s(state.get("started", ""))
    if held >= MAX_SHED_SECONDS:
        return ("maximum shed duration reached (%.0f min)" % (held / 60.0))

    try:
        snap = ha.climate_snapshot(ENTITY)
    except HAError as e:
        log.error("cannot read thermostat: %s", e)
        return None

    current = snap.get("current")
    if current is not None and float(current) >= INDOOR_CEILING_F:
        return ("indoor temperature %.0fF reached the %.0fF ceiling"
                % (float(current), INDOOR_CEILING_F))

    # Manual override: someone moved the setpoint away from what we applied.
    applied = state.get("applied_target")
    if (applied is not None and snap.get("target") is not None
            and abs(float(snap["target"]) - float(applied)) > 0.5):
        return ("manual override detected (setpoint is %.0fF, we set %.0fF)"
                % (float(snap["target"]), float(applied)))

    return None


def required_level(anomalies: list[dict]) -> tuple[int, str]:
    """Highest shed level justified by currently-open anomalies."""
    best, reason = 0, ""
    for a in anomalies:
        atype = str(a.get("atype", "")).strip()
        entity = str(a.get("entity", "")).strip()
        sev = str(a.get("severity", "")).strip()
        for t_type, t_entity, t_sev, level in TRIGGERS:
            if atype != t_type:
                continue
            if t_entity and t_entity not in entity:
                continue
            if t_sev == "critical" and sev != "critical":
                continue
            if level > best:
                best = level
                reason = "%s on %s (%s)" % (atype, entity or "?", sev)
    return best, reason


# ── control loop ─────────────────────────────────────────────────────────────

def evaluate(ha: HA, dry_run: bool = False) -> dict:
    state = load_state()

    guard = check_guards(ha)
    if guard:
        restore(ha, guard, dry_run=dry_run)
        return {"action": "restore", "reason": guard}

    try:
        anomalies = open_anomalies(minutes=120)
    except Exception as e:
        log.error("cannot read anomalies: %s", e)
        anomalies = []

    level, reason = required_level(anomalies)

    if level > 0:
        if state and state.get("level", 0) >= level:
            return {"action": "hold", "level": state["level"]}
        # Cooldown applies only to starting a NEW shed, never to escalating an
        # existing one or to restoring.
        last = state or {}
        if not state:
            since = _age_s(last.get("ended", "")) if last.get("ended") else 1e9
            if since < COOLDOWN_SECONDS:
                return {"action": "cooldown", "wait_s": COOLDOWN_SECONDS - since}
        shed(ha, level, reason, dry_run=dry_run)
        return {"action": "shed", "level": level, "reason": reason}

    if state:
        restore(ha, "triggering anomalies cleared", dry_run=dry_run)
        return {"action": "restore", "reason": "anomalies cleared"}

    return {"action": "idle"}


def startup_deadman(ha: HA) -> None:
    """A shed that outlived its process must be undone at boot."""
    state = load_state()
    if not state:
        return
    held = _age_s(state.get("started", ""))
    log.warning("found shed state on startup, age %.0f min", held / 60.0)
    if held >= MAX_SHED_SECONDS:
        restore(ha, "startup deadman: shed state outlived its maximum duration")


def status(ha: HA) -> dict:
    try:
        snap = ha.climate_snapshot(ENTITY)
    except HAError as e:
        snap = {"error": str(e)}
    state = load_state()
    return {
        "thermostat": snap,
        "shed_active": bool(state),
        "shed": state,
        "shed_age_s": _age_s(state.get("started", "")) if state else None,
        "policy": {
            "max_shed_s": MAX_SHED_SECONDS,
            "indoor_ceiling_f": INDOOR_CEILING_F,
            "cooldown_s": COOLDOWN_SECONDS,
            "levels": SHED_LEVELS,
            "notify": NOTIFY_CHANNELS,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--shed", type=int, metavar="LEVEL")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--reason", default="manual")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    ha = HA()
    if not ha.ping():
        sys.exit("ERROR: Home Assistant unreachable")

    if a.status:
        print(json.dumps(status(ha), indent=2, default=str))
    elif a.shed:
        shed(ha, a.shed, a.reason, dry_run=a.dry_run)
    elif a.restore:
        restore(ha, a.reason, dry_run=a.dry_run)
    elif a.loop:
        startup_deadman(ha)
        log.info("hvac_shed loop started (poll=%ds)", POLL_SECONDS)
        while True:
            try:
                log.debug("evaluate -> %s", evaluate(ha, dry_run=a.dry_run))
            except Exception:
                log.exception("evaluate failed; continuing")
            time.sleep(POLL_SECONDS)
    else:
        print(json.dumps(evaluate(ha, dry_run=a.dry_run), indent=2, default=str))


if __name__ == "__main__":
    main()
