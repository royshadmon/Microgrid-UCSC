"""
Continuous ONNX inference loop.

Run directly:
    python -m iems.inference.inference_loop --tick 30
    python -m iems.inference.inference_loop --once     # one pass, print JSON
"""
import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from iems.inference.appliance_map import PANEL_TO_MODEL
from iems.inference.feature_builder import UTIL_CHANNEL
from iems.inference.onnx_disaggregator import (
    disaggregate_panel_onnx, load_all_panel_sessions,
)
from iems.load.anylog_query import fetch_all_panels, fetch_channel
from iems.weather import get_weather

logger = logging.getLogger("iems.inference.loop")

TICK_SECONDS = 30
WINDOW_MINUTES = 12


class InferenceLoop:
    def __init__(self, tick_s=TICK_SECONDS, window_minutes=WINDOW_MINUTES):
        self.tick_s = tick_s
        self.window_minutes = window_minutes
        self._stop = False
        load_all_panel_sessions()

    def stop(self, *_):
        self._stop = True
        logger.info("Stopping inference loop…")

    def _fetch_all_inputs(self):
        now = datetime.now(timezone.utc)
        start = (now - timedelta(minutes=self.window_minutes)).isoformat()
        end = now.isoformat()
        panel_rows = fetch_all_panels(start, end)
        try:
            panel_rows[UTIL_CHANNEL] = fetch_channel(UTIL_CHANNEL, start, end)
        except Exception as exc:
            logger.warning("utility-tie fetch failed: %s", exc)
            panel_rows[UTIL_CHANNEL] = []
        return panel_rows

    def run_once(self):
        weather = get_weather()
        panel_rows = self._fetch_all_inputs()
        per_panel = {}
        for panel in PANEL_TO_MODEL.keys():
            try:
                r = disaggregate_panel_onnx(
                    panel=panel,
                    panel_rows=panel_rows,
                    weather=weather,
                    write_to_anylog=True,
                )
                per_panel[panel] = {
                    "states":        {h: s[0] for h, s in r.states.items()},
                    "probabilities": r.probabilities,
                    "latency_ms":    r.latency_ms,
                    "model":         r.model,
                    "midpoint_ts":   r.midpoint_ts,
                }
            except Exception as exc:
                logger.error("inference for %s failed: %s", panel, exc,
                             exc_info=True)
                per_panel[panel] = {"error": str(exc)}
        return per_panel

    def run(self):
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        logger.info("Inference loop starting (tick=%ds, window=%dm)",
                    self.tick_s, self.window_minutes)
        while not self._stop:
            t0 = time.monotonic()
            try:
                results = self.run_once()
                on_count = sum(
                    sum(1 for v in r.get("states", {}).values() if v == 1)
                    for r in results.values() if "error" not in r
                )
                logger.info("tick complete · %d appliances ON · %.1f s",
                            on_count, time.monotonic() - t0)
            except Exception as exc:
                logger.error("loop tick failed: %s", exc, exc_info=True)
            elapsed = time.monotonic() - t0
            sleep_for = max(1.0, self.tick_s - elapsed)
            for _ in range(int(sleep_for * 10)):
                if self._stop:
                    break
                time.sleep(0.1)


def main():
    p = argparse.ArgumentParser(description="ONNX NILM inference loop")
    p.add_argument("--tick", type=int, default=TICK_SECONDS)
    p.add_argument("--window", type=int, default=WINDOW_MINUTES)
    p.add_argument("--once", action="store_true",
                   help="Run a single pass, print JSON, exit")
    p.add_argument("--log", default="INFO")
    args = p.parse_args()

    logging.basicConfig(
        level=args.log,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    loop = InferenceLoop(tick_s=args.tick, window_minutes=args.window)
    if args.once:
        import json
        print(json.dumps(loop.run_once(), indent=2, default=str))
        return 0
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
