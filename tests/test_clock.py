"""World clock v1: costs, display, deterministic timer fires."""

from __future__ import annotations

import pytest

from everquill_engine.clock import (
    ACTION_TIME_COST,
    TRAINING_BLOCK_MINUTES,
    DurationBindingError,
    action_time_cost,
    bind_duration,
    resolve_timer_fire,
    timer_fire_seed,
    world_date,
)
from everquill_engine.resolver import ACTION_TYPES


class TestCosts:
    def test_every_action_type_is_priced(self):
        for action in ACTION_TYPES:
            assert action_time_cost(action) >= 0

    def test_cost_table_matches_docs(self):
        """docs/engine/stats.md table — keep in lockstep."""
        assert ACTION_TIME_COST == {
            "physical": 10, "social": 15, "movement": 15, "observation": 5,
            "research": 60, "craft": 60, "train": 5, "dialogue": 2,
            "meta": 0, "rest": 480,
        }
        assert TRAINING_BLOCK_MINUTES == 480

    def test_unknown_action_raises(self):
        with pytest.raises(ValueError):
            action_time_cost("teleport")


class TestWorldDate:
    def test_epoch_is_day1_0600(self):
        assert world_date(0) == "Day 1, 06:00"

    def test_rollover(self):
        assert world_date(18 * 60) == "Day 2, 00:00"
        assert world_date(1440 + 30) == "Day 2, 06:30"


def _hint(mode, text, until=None, amount=None, unit=None):
    from everquill_engine.intent import DurationHint

    return DurationHint(mode=mode, text=text, until=until, amount=amount, unit=unit)


class TestDurationBinding:
    """Closed fields (mode, until, amount, unit) + world_time -> minutes, or a
    clear rejection. The player's words in ``text`` are never bound."""

    def test_explicit_amount_and_unit(self):
        three = _hint("explicit", "for three hours", amount=3, unit="hour")
        assert bind_duration(three, 0) == 180
        assert bind_duration(_hint("explicit", "an hour", amount=1, unit="hour"), 0) == 60
        assert bind_duration(_hint("explicit", "one day", amount=1, unit="day"), 0) == 1440
        assert bind_duration(_hint("explicit", "45 minutes", amount=45, unit="minute"), 0) == 45

    def test_the_text_never_decides(self):
        # Same closed fields, different words: same minutes.
        a = bind_duration(_hint("explicit", "for the night", amount=8, unit="hour"), 0)
        b = bind_duration(_hint("explicit", "a long while", amount=8, unit="hour"), 0)
        assert a == b == 480
        # "afternoon" used to match "noon" by substring; now only `until` counts.
        afternoon = _hint("until_condition", "until the afternoon", until="dusk")
        assert bind_duration(afternoon, 0) == 720

    def test_until_condition_block_table(self):
        # World minute 0 = Day 1 06:00.
        assert bind_duration(_hint("until_condition", "until nightfall", until="dusk"), 0) == 720
        assert bind_duration(_hint("until_condition", "until dawn", until="dawn"), 0) == 1440
        assert bind_duration(_hint("until_condition", "until noon", until="midday"), 0) == 360
        midnight = _hint("until_condition", "until midnight", until="midnight")
        assert bind_duration(midnight, 0) == 1080
        # From 08:40 (minute 160), dusk is 560 minutes out.
        assert bind_duration(_hint("until_condition", "until nightfall", until="dusk"), 160) == 560

    def test_until_condition_at_the_boundary_rolls_to_tomorrow(self):
        # Exactly at 18:00 (minute 720), "until dusk" = a full day.
        assert bind_duration(_hint("until_condition", "until dusk", until="dusk"), 720) == 1440

    def test_unbindable_forms_rejected_with_the_supported_forms(self):
        with pytest.raises(DurationBindingError, match="dawn, midday, dusk and midnight"):
            bind_duration(_hint("until_condition", "until the caravan leaves"), 0)
        with pytest.raises(DurationBindingError, match="an amount and a unit"):
            bind_duration(_hint("explicit", "a good while"), 0)
        with pytest.raises(DurationBindingError, match="binds spans up to"):
            bind_duration(_hint("explicit", "forty days", amount=40, unit="day"), 0)


class TestTimerFire:
    TIMER = {
        "timer_key": "timer_pc_7",
        "kind": "training",
        "payload": {"aptitude": "might", "owner_id": "pc"},
    }

    def test_seed_is_pure_and_pinned(self):
        seed = timer_fire_seed("timer_pc_7", 31)
        assert seed == timer_fire_seed("timer_pc_7", 31)
        assert seed != timer_fire_seed("timer_pc_7", 32)
        assert seed != timer_fire_seed("timer_pc_8", 31)

    def test_fire_is_deterministic(self):
        a = resolve_timer_fire(dict(self.TIMER), 31)
        b = resolve_timer_fire(dict(self.TIMER), 31)
        assert a == b

    def test_training_gain_is_a_stored_fact(self):
        fire = resolve_timer_fire(dict(self.TIMER), 31)
        (gain, *rest) = fire["gains"]
        assert gain == {
            "delta_type": "aptitude", "entity_id": "pc", "aptitude": "might", "amount": 1,
        }
        assert fire["rng"]["stream"] == ["timerfire", "timer_pc_7"]

    def test_unknown_kind_raises_not_skips(self):
        with pytest.raises(ValueError):
            resolve_timer_fire({**self.TIMER, "kind": "research"}, 31)
