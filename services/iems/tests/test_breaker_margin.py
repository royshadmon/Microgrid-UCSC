#!/usr/bin/env python3
"""Unit tests for the Phase 4 breaker-margin detector.

All offline: no AnyLog, no network, no parquet. Every test drives the state
machine with synthetic samples so the failure modes that matter for a safety
detector are pinned down explicitly.

Run:
    .venv-training/bin/python -m pytest services/iems/tests/test_breaker_margin.py -v
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, "services")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detect"))

from iems.detect.breaker_margin import (  # noqa: E402
    Group, evaluate, group_current, load_groups,
)

T0 = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


TWO_LEG = ["I11", "I12"]


def mk(rating=30.0, **kw) -> Group:
    # Default to ONE leg so state-machine tests are not perturbed by
    # leg_dropout events. Tests about leg coverage pass legs=TWO_LEG.
    base = dict(
        key="p1", label="Panel1", legs=["I11"], amps_rating=rating,
        per_leg=True, margin_frac=0.80, clear_frac=0.70,
        sustain_seconds=900, min_samples=3, cooldown_seconds=43200,
    )
    base.update(kw)
    return Group(**base)


def series(**legs) -> dict:
    """series(I11=[1,2,3]) -> {"I11": [{"w": 1}, {"w": 2}, {"w": 3}]}"""
    return {k: [{"w": v} for v in vals] for k, vals in legs.items()}


# ── group_current ─────────────────────────────────────────────────────────────

class TestGroupCurrent:
    def test_takes_worst_leg_not_sum(self):
        """A 240V circuit with imbalanced legs: the hot leg is the constraint.

        Summing would report 30 A on a 30 A breaker and cry overload when each
        pole is only at 25 A / 5 A. Max is correct; sum is the classic bug.
        """
        g = mk(legs=TWO_LEG)
        amps, leg, n, _ = group_current(g, series(I11=[25, 25, 25], I12=[5, 5, 5]))
        assert amps == 25
        assert leg == "I11"
        assert n == 6

    def test_uses_median_not_max(self):
        """Inrush is a spike, not a sustained overload. Median rejects it."""
        g = mk()
        amps, _, _, _ = group_current(g, series(I11=[10, 10, 10, 10, 99]))
        assert amps == 10

    def test_absolute_value_applied(self):
        """eGauge reports panel channels negative; amps must not go negative."""
        g = mk()
        amps, _, _, _ = group_current(g, series(I11=[-22, -22, -22]))
        assert amps == 22

    def test_tolerates_malformed_rows(self):
        g = mk()
        s = {"I11": [{"w": "12"}, {"w": None}, {"nope": 1}, {"w": "abc"}, {"w": "12"}]}
        amps, _, n, _ = group_current(g, s)
        assert amps == 12
        assert n == 2

    def test_missing_legs_yield_zero_and_are_reported(self):
        g = mk(legs=TWO_LEG)
        assert group_current(g, {}) == (0.0, "", 0, ["I11", "I12"])

    def test_partial_leg_loss_is_reported(self):
        """Live regression: I12 and I22 stopped reporting while I11/I21 kept
        going. The surviving leg must not make the group look fully covered."""
        g = mk(legs=TWO_LEG)
        amps, leg, n, missing = group_current(g, series(I11=[10, 10, 10]))
        assert amps == 10
        assert missing == ["I12"]


class TestLegDropout:
    def test_dropout_emitted_even_when_unarmed(self):
        """A dead channel needs no rating to detect, and the shipped config is
        unarmed -- so gating this behind `armed` would silence it exactly when
        it is most needed."""
        g = mk(rating=None, legs=TWO_LEG)
        ev = evaluate([g], series(I11=[10] * 10), now=T0)
        assert len(ev) == 1
        assert ev[0]["type"] == "leg_dropout"
        assert ev[0]["severity"] == "warning"
        assert ev[0]["missing_legs"] == ["I12"]
        assert ev[0]["monitored_legs"] == ["I11"]

    def test_no_dropout_when_all_legs_report(self):
        g = mk(legs=TWO_LEG)
        ev = evaluate([g], series(I11=[10] * 5, I12=[10] * 5), now=T0)
        assert ev == []

    def test_dropout_respects_cooldown(self):
        g = mk(legs=TWO_LEG)
        assert len(evaluate([g], series(I11=[10] * 10), now=T0)) == 1
        for i in range(1, 5):
            assert evaluate([g], series(I11=[10] * 10),
                            now=T0 + timedelta(minutes=10 * i)) == []

    def test_dropout_repeats_after_cooldown(self):
        g = mk(cooldown_seconds=60, legs=TWO_LEG)
        assert len(evaluate([g], series(I11=[10] * 10), now=T0)) == 1
        ev = evaluate([g], series(I11=[10] * 10), now=T0 + timedelta(seconds=120))
        assert len(ev) == 1

    def test_dropout_does_not_block_breach_alert(self):
        """Half-covered is still monitored: the surviving leg must still alert."""
        g = mk(legs=TWO_LEG)
        evaluate([g], series(I11=[25] * 10), now=T0)          # dropout + timer
        ev = evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=900))
        assert [e["type"] for e in ev] == ["breaker_margin"]


# ── state machine ─────────────────────────────────────────────────────────────

class TestStateMachine:
    def test_unarmed_group_never_alerts(self):
        """No rating means no threshold. It must stay silent, not guess."""
        g = mk(rating=None)
        ev = evaluate([g], series(I11=[999] * 10), now=T0)
        assert ev == []
        assert not g.in_breach

    def test_below_margin_is_silent(self):
        g = mk()  # margin = 24 A
        assert evaluate([g], series(I11=[20] * 10), now=T0) == []
        assert g.breach_since is None

    def test_breach_requires_sustain(self):
        g = mk()
        assert evaluate([g], series(I11=[25] * 10), now=T0) == []
        assert g.breach_since == T0          # timer started
        assert not g.in_breach               # but not alerting yet

    def test_alerts_after_sustain(self):
        g = mk()
        evaluate([g], series(I11=[25] * 10), now=T0)
        ev = evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=900))
        assert len(ev) == 1
        assert ev[0]["type"] == "breaker_margin"
        assert ev[0]["severity"] == "critical"
        assert ev[0]["pct_of_rating"] == pytest.approx(83.3, abs=0.1)
        assert g.in_breach

    def test_no_duplicate_alerts_while_in_breach(self):
        g = mk()
        evaluate([g], series(I11=[25] * 10), now=T0)
        evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=900))
        for i in range(1, 6):
            extra = evaluate([g], series(I11=[25] * 10),
                             now=T0 + timedelta(seconds=900 + 60 * i))
            assert extra == []

    def test_hysteresis_band_holds_state(self):
        """22 A is below margin (24) but above clear (21): must NOT clear."""
        g = mk()
        evaluate([g], series(I11=[25] * 10), now=T0)
        evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=900))
        assert g.in_breach
        ev = evaluate([g], series(I11=[22] * 10), now=T0 + timedelta(seconds=1200))
        assert ev == []
        assert g.in_breach

    def test_clears_below_clear_frac(self):
        g = mk()
        evaluate([g], series(I11=[25] * 10), now=T0)
        evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=900))
        ev = evaluate([g], series(I11=[10] * 10), now=T0 + timedelta(seconds=1800))
        assert len(ev) == 1
        assert ev[0]["type"] == "breaker_margin_clear"
        assert ev[0]["severity"] == "info"
        assert not g.in_breach
        assert g.breach_since is None

    def test_dip_below_clear_resets_sustain_timer(self):
        """A brief drop must restart the dwell, not bank partial credit."""
        g = mk()
        evaluate([g], series(I11=[25] * 10), now=T0)
        evaluate([g], series(I11=[10] * 10), now=T0 + timedelta(seconds=600))
        assert g.breach_since is None
        ev = evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=700))
        assert ev == []
        assert g.breach_since == T0 + timedelta(seconds=700)

    def test_cooldown_suppresses_realert(self):
        g = mk()
        evaluate([g], series(I11=[25] * 10), now=T0)
        evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=900))
        evaluate([g], series(I11=[10] * 10), now=T0 + timedelta(seconds=1000))
        t = T0 + timedelta(seconds=2000)
        evaluate([g], series(I11=[25] * 10), now=t)
        ev = evaluate([g], series(I11=[25] * 10), now=t + timedelta(seconds=900))
        assert ev == [], "re-alerted inside the 12h cooldown"

    def test_realerts_after_cooldown(self):
        g = mk(cooldown_seconds=60)
        evaluate([g], series(I11=[25] * 10), now=T0)
        evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=900))
        evaluate([g], series(I11=[10] * 10), now=T0 + timedelta(seconds=1000))
        t = T0 + timedelta(seconds=5000)
        evaluate([g], series(I11=[25] * 10), now=t)
        ev = evaluate([g], series(I11=[25] * 10), now=t + timedelta(seconds=900))
        assert len(ev) == 1

    def test_min_samples_gate(self):
        """A thin window is a data dropout, not evidence of an overload."""
        g = mk(min_samples=20)
        ev = evaluate([g], series(I11=[25, 25]), now=T0)
        assert ev == []
        assert g.breach_since is None

    def test_exactly_at_margin_counts_as_breach(self):
        g = mk()  # margin exactly 24.0
        evaluate([g], series(I11=[24] * 10), now=T0)
        assert g.breach_since == T0

    def test_multiple_groups_independent(self):
        a = mk(key="a", legs=["I11"])
        b = mk(key="b", legs=["I21"], rating=60.0)
        evaluate([a, b], series(I11=[25] * 10, I21=[10] * 10), now=T0)
        ev = evaluate([a, b], series(I11=[25] * 10, I21=[10] * 10),
                      now=T0 + timedelta(seconds=900))
        assert len(ev) == 1
        assert ev[0]["group"] == "a"

    def test_alert_payload_is_complete(self):
        g = mk()
        evaluate([g], series(I11=[25] * 10), now=T0)
        e = evaluate([g], series(I11=[25] * 10), now=T0 + timedelta(seconds=900))[0]
        for k in ("ts", "type", "severity", "group", "label", "leg", "amps",
                  "rating_amps", "pct_of_rating", "sustained_seconds",
                  "message", "action"):
            assert k in e, f"missing {k}"
        assert "30" in e["message"] and "25" in e["message"]


# ── config loading ────────────────────────────────────────────────────────────

class TestConfig:
    def test_shipped_config_parses_and_is_unarmed(self):
        """The shipped config must never arrive armed."""
        cfg = Path("services/iems/detect/breaker_ratings.yaml")
        groups = load_groups(cfg)
        assert len(groups) == 4
        assert all(not g.armed for g in groups), "shipped config must be UNARMED"

    def test_shipped_config_leg_mapping(self):
        groups = {g.key: g for g in
                  load_groups(Path("services/iems/detect/breaker_ratings.yaml"))}
        assert groups["panel1_hvac"].legs == ["I11", "I12"]
        assert groups["panel2_h2o"].legs == ["I21", "I22"]
        assert groups["panel3_kitchen"].legs == ["I31", "I32"]
        assert groups["main_service"].legs == ["Current on Utility Tie"]

    def test_defaults_applied(self):
        groups = load_groups(Path("services/iems/detect/breaker_ratings.yaml"))
        g = groups[0]
        assert g.margin_frac == 0.80
        assert g.clear_frac == 0.70
        assert g.sustain_seconds == 900

    def test_clear_below_margin_invariant(self):
        """clear_frac < margin_frac, or the hysteresis band inverts and flaps."""
        for g in load_groups(Path("services/iems/detect/breaker_ratings.yaml")):
            assert g.clear_frac < g.margin_frac


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
