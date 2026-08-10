#!/usr/bin/env python3
"""Minimal Home Assistant REST client.

Token-only: the long-lived token is minted once by ha_mint_token.py and read
from HA_TOKEN or a file. No password ever reaches this module.

Usage:
    from iems.detect.ha_client import HA
    ha = HA()
    ha.state("climate.sensi_2a293d_thermostat")
    ha.call("climate", "set_temperature",
            {"entity_id": "climate.sensi_2a293d_thermostat", "temperature": 80})
    ha.notify("Load shed", "HVAC setpoint raised to 80F", channels=["email","sms"])
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("ha_client")

DEFAULT_URL = os.environ.get("HA_URL", "http://192.168.254.69:8123").rstrip("/")
TOKEN_FILE = os.environ.get("HA_TOKEN_FILE", str(Path.home() / "ha_token.txt"))

# Notify services present on this instance (verified 2026-08-05).
NOTIFY_SERVICES = {
    "email": "system_email",
    "sms": "mantey_sms",
    "sms_aiden": "aiden_sms",
}


class HAError(RuntimeError):
    pass


class HA:
    def __init__(self, url: str = DEFAULT_URL, token: str | None = None,
                 timeout: int = 15):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.token = token or os.environ.get("HA_TOKEN") or self._read_token_file()
        if not self.token:
            raise HAError(
                "no HA token: set HA_TOKEN, or run ha_mint_token.py to create %s"
                % TOKEN_FILE)

    @staticmethod
    def _read_token_file() -> str:
        try:
            return Path(TOKEN_FILE).read_text().strip()
        except OSError:
            return ""

    # ── transport ────────────────────────────────────────────────────────────
    def _request(self, path: str, payload: Any = None, method: str = "GET") -> Any:
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = r.read().decode()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            raise HAError("HA %s %s -> %d %s" % (method, path, e.code, detail))
        except urllib.error.URLError as e:
            raise HAError("HA unreachable at %s: %s" % (self.url, e.reason))
        return json.loads(body) if body.strip() else None

    # ── reads ────────────────────────────────────────────────────────────────
    def state(self, entity_id: str) -> dict:
        return self._request("/api/states/" + entity_id)

    def states(self) -> list[dict]:
        return self._request("/api/states")

    def ping(self) -> bool:
        try:
            self._request("/api/")
            return True
        except HAError:
            return False

    # ── writes ───────────────────────────────────────────────────────────────
    def call(self, domain: str, service: str, data: dict) -> Any:
        return self._request("/api/services/%s/%s" % (domain, service),
                             payload=data, method="POST")

    def notify(self, title: str, message: str,
               channels: list[str] | None = None) -> dict[str, bool]:
        """Send to one or more configured notify services.

        Returns per-channel success rather than raising, so a dead SMS gateway
        cannot suppress the email that would otherwise have gone out.
        """
        channels = channels or ["email"]
        results = {}
        for ch in channels:
            svc = NOTIFY_SERVICES.get(ch)
            if not svc:
                log.warning("unknown notify channel %r", ch)
                results[ch] = False
                continue
            try:
                self.call("notify", svc, {"title": title, "message": message})
                results[ch] = True
            except HAError as e:
                log.error("notify.%s failed: %s", svc, e)
                results[ch] = False
        return results

    # ── climate helpers ──────────────────────────────────────────────────────
    def climate_snapshot(self, entity_id: str) -> dict:
        s = self.state(entity_id)
        a = s.get("attributes", {})
        return {
            "entity_id": entity_id,
            "hvac_mode": s.get("state"),
            "hvac_action": a.get("hvac_action"),
            "target": a.get("temperature"),
            "current": a.get("current_temperature"),
            "min_temp": a.get("min_temp"),
            "max_temp": a.get("max_temp"),
            "friendly_name": a.get("friendly_name"),
            "last_updated": s.get("last_updated"),
        }

    def set_temperature(self, entity_id: str, temperature: float) -> None:
        self.call("climate", "set_temperature",
                  {"entity_id": entity_id, "temperature": temperature})

    def set_hvac_mode(self, entity_id: str, mode: str) -> None:
        self.call("climate", "set_hvac_mode",
                  {"entity_id": entity_id, "hvac_mode": mode})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ha = HA()
    print("reachable:", ha.ping())
    print(json.dumps(ha.climate_snapshot("climate.sensi_2a293d_thermostat"), indent=2))
