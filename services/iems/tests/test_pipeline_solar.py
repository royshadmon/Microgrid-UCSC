"""Pipeline-flow unit tests for the solar-aware NILM inference path.

Exercises the real code (no live AnyLog required): measured-solar rule gating,
solar threading through apply_rules, solar-snapshot parsing, the feature-window
builder, and an end-to-end ONNX disaggregation (model + rules) with solar.

Run:  PYTHONPATH=services python -m unittest iems.tests.test_pipeline_solar -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "services")

from iems.inference import rules_additive as R
from iems.inference.rules_additive import _low_solar, _battery_charging, apply_rules
from iems.load import anylog_query as AQ


def synth_rows(base_w, n=150, step_s=6, start=None):
    start = start or (datetime.now(timezone.utc) - timedelta(seconds=step_s * (n - 1)))
    return [{"ts": (start + timedelta(seconds=step_s * i)).strftime("%Y-%m-%d %H:%M:%S"),
             "w": base_w} for i in range(n)]


class TestMeasuredSolarGating(unittest.TestCase):
    """Measured solar_data must override the weather/time proxies."""

    def test_high_pv_overrides_overcast_weather(self):
        # Forecast says overcast/dark, but the array is measurably producing.
        self.assertFalse(_low_solar({"irradiance_6h_avg": 0, "cloud_cover_pct": 100},
                                    None, {"pv_power": 3700}))

    def test_low_pv_overrides_sunny_weather(self):
        # Forecast says bright sun, but the array is measurably not producing.
        self.assertTrue(_low_solar({"irradiance_6h_avg": 900, "cloud_cover_pct": 0},
                                   None, {"pv_power": 50}))

    def test_falls_back_to_weather_without_solar(self):
        self.assertTrue(_low_solar({"irradiance_6h_avg": 0, "cloud_cover_pct": 100}, None, None))
        # naive local noon -> daylight + sunny weather -> not low solar
        self.assertFalse(_low_solar({"irradiance_6h_avg": 900, "cloud_cover_pct": 0,
                                     "irradiance_now": 900},
                                    datetime(2026, 8, 4, 12), None))

    def test_battery_charging_measured_vs_fallback(self):
        self.assertTrue(_battery_charging({"battery_power": 2757}, None))
        self.assertFalse(_battery_charging({"battery_power": -500}, None))
        # fallback: no measurement -> time window (16:00-21:00 local)
        class _T:  # minimal ts-local stub
            hour = 18
        self.assertTrue(_battery_charging(None, _T()))
        _T.hour = 3
        self.assertFalse(_battery_charging(None, _T()))


class TestApplyRulesSolarThreading(unittest.TestCase):
    """apply_rules must consume the solar snapshot end-to-end."""

    def _preds(self, **over):
        base = {"heat_pump": {"state": 0, "confidence": 0.1, "power_w": 0.0},
                "solar_pump": {"state": 0, "confidence": 0.1, "power_w": 0.0}}
        base.update(over)
        return base

    def test_solar_pump_recovered_when_pv_high(self):
        preds = self._preds()
        out = apply_rules(preds, panel_power_w=180.0,
                          ts_local=datetime(2026, 8, 4, 12), additive=True,
                          weather={"irradiance_6h_avg": 0, "cloud_cover_pct": 100},
                          panel="Panel1 (HVAC)", solar={"pv_power": 3500})
        # High measured PV -> not low solar -> small Panel1 draw recovers the pump.
        self.assertEqual(out["solar_pump"]["state"], 1)
        self.assertEqual(out["solar_pump"]["rule"], "solar_recovery")

    def test_solar_pump_gated_off_when_pv_low(self):
        preds = self._preds(solar_pump={"state": 1, "confidence": 0.3, "power_w": 150.0})
        out = apply_rules(preds, panel_power_w=150.0,
                          ts_local=datetime(2026, 8, 4, 12), additive=True,
                          weather={"irradiance_6h_avg": 900, "cloud_cover_pct": 0},
                          panel="Panel1 (HVAC)", solar={"pv_power": 40})
        self.assertEqual(out["solar_pump"]["state"], 0)
        self.assertIn("solar_gate", out["solar_pump"]["rule"])

    def test_measured_battery_and_house_load_annotations(self):
        preds = self._preds()
        out = apply_rules(preds, panel_power_w=300.0, ts_local=datetime(2026, 8, 4, 3),
                          additive=False, panel="Panel3 (Kitchen)",
                          solar={"pv_power": 3000, "battery_power": 1500, "load_power": 1234})
        # 3am -> time window would say NOT charging, but measured battery_power says charging.
        self.assertTrue(any(p.get("battery_charging") for p in out.values()))
        self.assertTrue(all(p.get("house_load_w") == 1234.0 for p in out.values()))


class TestSolarSnapshotParsing(unittest.TestCase):
    """fetch_solar_snapshot must coerce a raw AnyLog row into typed floats."""

    def test_parse_and_types(self):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        fake = [{"ts": ts, "pv_power": "3691", "battery_power": "2757",
                 "battery_soc": "85", "grid_power": "65", "load_power": "680",
                 "device_mode": "Discharge above 50%"}]
        orig = AQ.anylog_query
        AQ.anylog_query = lambda *a, **k: fake
        try:
            snap = AQ.fetch_solar_snapshot(minutes=10)
        finally:
            AQ.anylog_query = orig
        self.assertEqual(snap["pv_power"], 3691.0)
        self.assertIsInstance(snap["battery_power"], float)
        self.assertEqual(snap["device_mode"], "Discharge above 50%")
        self.assertIn("age_s", snap)

    def test_empty_returns_empty_dict(self):
        orig = AQ.anylog_query
        AQ.anylog_query = lambda *a, **k: []
        try:
            self.assertEqual(AQ.fetch_solar_snapshot(), {})
        finally:
            AQ.anylog_query = orig


class TestFeatureBuilder(unittest.TestCase):
    def test_window_tensor_shape_and_finite(self):
        import numpy as np
        from iems.inference.feature_builder import build_panel_window
        norm = {"features": ["Panel3 (Kitchen)", "Panel1 (HVAC)", "Panel2 (H2O)",
                             "Shop", "VrmsA", "VrmsB", "I31", "I32", "F1",
                             "Grid Power", "I11", "I21", "tod_sin", "tod_cos"],
                "window": 100, "mid": 50,
                "mean": [0.0] * 14, "std": [1.0] * 14}
        rows = {ch: synth_rows(v) for ch, v in {
            "Panel1 (HVAC)": 2000, "Panel2 (H2O)": 100, "Panel3 (Kitchen)": 300,
            "Shop": 50, "VrmsA": 120, "VrmsB": 120, "I31": 5, "I32": 5, "F1": 60,
            "Grid Power": 1500, "I11": 10, "I21": 10,
            "Current on Utility Tie": 8}.items()}
        weather = {"outside_temp_f": 70, "irradiance_6h_avg": 300, "cloud_cover_pct": 20}
        tensor, mid_ts, s_ts, e_ts = build_panel_window("Panel3 (Kitchen)", rows, weather, norm)
        self.assertEqual(tensor.shape, (1, 100, 14))
        self.assertTrue(np.isfinite(tensor).all())


class TestEndToEndDisaggregation(unittest.TestCase):
    """model (ONNX) + solar-aware rules, no writeback."""

    def test_panel3_full_cycle_with_solar(self):
        try:
            import onnxruntime  # noqa
        except ImportError:
            self.skipTest("onnxruntime not installed")
        from iems.inference.onnx_disaggregator import disaggregate_panel_onnx
        rows = {ch: synth_rows(v) for ch, v in {
            "Panel1 (HVAC)": 2000, "Panel2 (H2O)": 100, "Panel3 (Kitchen)": 300,
            "Shop": 50, "VrmsA": 120, "VrmsB": 120, "I31": 5, "I32": 5, "F1": 60,
            "Grid Power": 1500, "I11": 10, "I21": 10,
            "Current on Utility Tie": 8}.items()}
        weather = {"outside_temp_f": 70, "irradiance_6h_avg": 300, "cloud_cover_pct": 20}
        solar = {"pv_power": 3000, "battery_power": 500, "battery_soc": 80,
                 "grid_power": 100, "load_power": 1200}
        try:
            res = disaggregate_panel_onnx("Panel3 (Kitchen)", rows, weather,
                                          write_to_anylog=False, solar=solar)
        except FileNotFoundError:
            self.skipTest("panel3 ONNX model not present")
        self.assertTrue(res.reconciled, "reconciled output should be non-empty")
        for head, d in res.reconciled.items():
            self.assertIn(d["state"], (0, 1))
            self.assertGreaterEqual(d["confidence"], 0.0)
        # solar threaded -> house-load annotation present on reconciled preds
        self.assertTrue(any("house_load_w" in d for d in res.reconciled.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
