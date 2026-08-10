#!/usr/bin/env python3
"""Unit tests for the Phase 0 register inventory.

Covers the channel classifier and asserts the generated inventory matches what
the Phase 4 detector assumes about the panel topology. If these two drift apart,
the detector silently monitors the wrong channels -- so the coupling is pinned
here on purpose.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
INV_PY = REPO / "analysis" / "inventory" / "build_register_inventory.py"
INV_CSV = REPO / "analysis" / "inventory" / "register_inventory.csv"

spec = importlib.util.spec_from_file_location("build_register_inventory", INV_PY)
inv = importlib.util.module_from_spec(spec)
sys.modules["build_register_inventory"] = inv
spec.loader.exec_module(inv)


class TestClassify:
    def test_instrument_channels(self):
        for ch in ["VrmsA", "VrmsB", "F1", "I11", "I32", "Current on Utility Tie"]:
            assert inv.classify(ch, 0) == "instrument"

    def test_instrument_wins_over_appliance_count(self):
        """A current channel is never a load register, whatever the count says."""
        assert inv.classify("I11", 5) == "instrument"

    def test_aggregate_channels(self):
        assert inv.classify("Grid Power", 0) == "aggregate"
        assert inv.classify("Generac Power", 0) == "aggregate"

    def test_shared_requires_multiple_appliances(self):
        assert inv.classify("Panel1 (HVAC)", 2) == "shared"
        assert inv.classify("Panel3 (Kitchen)", 9) == "shared"

    def test_single_appliance_is_dedicated(self):
        assert inv.classify("Some Circuit", 1) == "dedicated"

    def test_unknown_power_channel_is_unmapped(self):
        assert inv.classify("Shop", 0) == "unmapped"


class TestWaterCoupling:
    def test_water_coupled_set_is_subset_of_known_appliances(self):
        known = {a for apps in inv.PANEL_APPLIANCES.values() for a in apps}
        unknown = inv.WATER_COUPLED - known
        assert not unknown, f"water-coupled names not in any panel: {unknown}"

    def test_each_panel_has_at_least_one_water_coupled_load(self):
        """All three panels carry leak-relevant signal; none can be ignored."""
        for panel, apps in inv.PANEL_APPLIANCES.items():
            assert set(apps) & inv.WATER_COUPLED, f"{panel} has none"


@pytest.mark.skipif(not INV_CSV.exists(), reason="inventory not generated yet")
class TestGeneratedInventory:
    @staticmethod
    @pytest.fixture(scope="class")
    def rows():
        import csv
        with INV_CSV.open() as f:
            return {r["channel"]: r for r in csv.DictReader(f)}

    def test_all_sixteen_channels_present(self, rows):
        assert len(rows) == 16

    def test_panels_classified_shared(self, rows):
        for p in ["Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"]:
            assert rows[p]["kind"] == "shared"
            assert rows[p]["nilm_required"] == "True"

    def test_instruments_not_flagged_for_nilm(self, rows):
        for ch, r in rows.items():
            if r["kind"] == "instrument":
                assert r["nilm_required"] == "False", ch

    def test_detector_legs_exist_as_channels(self, rows):
        """Every leg the Phase 4 config monitors must be a real eGauge channel."""
        for leg in ["I11", "I12", "I21", "I22", "I31", "I32",
                    "Current on Utility Tie"]:
            assert leg in rows, f"detector references missing channel {leg}"

    def test_panel_channels_are_negative_convention(self, rows):
        """eGauge records panel loads negative; detectors must use abs()."""
        for p in ["Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)"]:
            assert float(rows[p]["negative_frac"]) == 1.0, p

    def test_shop_is_unmapped_and_therefore_invisible(self, rows):
        """Regression guard: Shop is a real power register with no appliance
        mapping, so no detector currently covers it. If it ever gets mapped,
        this test should be updated deliberately, not by accident."""
        assert rows["Shop"]["kind"] == "unmapped"
        assert rows["Shop"]["appliances"] == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
