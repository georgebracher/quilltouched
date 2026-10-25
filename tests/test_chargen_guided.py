"""Guided-dice character creation.

The seed still owns the numbers (honest dice); the player owns the placement.
Roll a pool of six base values plus one spare, assign six of them to aptitudes,
optionally swap a base value for the spare. Pure and replayable: same seed +
same assignment => same character, forever.
"""

from __future__ import annotations

import pytest

from everquill_engine.chargen import (
    MAX_REROLLS,
    build_character,
    chargen_events,
    roll_character,
    roll_pool,
)
from everquill_engine.world import APTITUDES

SEED = 42
CID = "pc"


def _identity_assignment() -> dict[str, int]:
    return {aptitude: index for index, aptitude in enumerate(APTITUDES)}


class TestPool:
    def test_pool_is_six_plus_spares_and_deterministic(self):
        pool = roll_pool(SEED, CID)
        assert [p.index for p in pool] == list(range(len(APTITUDES) + MAX_REROLLS))
        assert roll_pool(SEED, CID) == pool  # pure: same (seed, id) => same pool
        for p in pool:
            assert p.total == p.die_one + p.die_two
            assert 2 <= p.total <= 12

    def test_pool_varies_by_character(self):
        assert roll_pool(SEED, "pc") != roll_pool(SEED, "heir")


class TestBuildMatchesAuto:
    def test_identity_assignment_equals_roll_character(self):
        # The auto path is exactly guided-dice with the identity placement, so
        # it must produce the same aptitudes and audit rolls.
        auto = roll_character(SEED, CID, name="Ash")
        guided = build_character(SEED, CID, name="Ash", assignment=_identity_assignment())
        assert guided.aptitudes == auto.aptitudes
        assert guided.rolls == auto.rolls
        assert guided.hp_max == auto.hp_max


class TestPlacement:
    def test_player_places_the_best_roll_where_they_want(self):
        pool = roll_pool(SEED, CID)
        best = max(pool, key=lambda p: p.total)
        # Put the best roll on presence; fill the rest with the remaining base
        # indexes (skip the chosen one, ignore the spare).
        rest = [p.index for p in pool if p.index != best.index]
        assignment = {"presence": best.index}
        for aptitude in APTITUDES:
            if aptitude != "presence":
                assignment[aptitude] = rest.pop(0)
        char = build_character(SEED, CID, name="Ash", assignment=assignment)
        assert char.aptitudes["presence"] == best.total
        assert char.aptitudes["presence"] == max(char.aptitudes.values())

    def test_reroll_swaps_a_base_value_for_the_spare(self):
        pool = roll_pool(SEED, CID)
        spare = pool[-1]  # index 6, the reroll spare
        # Use the spare for lore, drop base index 0.
        assignment = {aptitude: index for index, aptitude in enumerate(APTITUDES)}
        assignment["lore"] = spare.index  # was index 5; now the spare
        # index 5 is now free but index 0 is still used — that's fine, distinct.
        char = build_character(SEED, CID, name="Ash", assignment=assignment)
        assert char.aptitudes["lore"] == spare.total

    def test_deterministic_replay(self):
        a = build_character(SEED, CID, name="Ash", assignment=_identity_assignment())
        b = build_character(SEED, CID, name="Ash", assignment=_identity_assignment())
        assert a == b


class TestValidation:
    def test_missing_aptitude_rejected(self):
        bad = _identity_assignment()
        del bad["lore"]
        with pytest.raises(ValueError, match="six aptitudes"):
            build_character(SEED, CID, name="Ash", assignment=bad)

    def test_duplicate_index_rejected(self):
        bad = _identity_assignment()
        bad["lore"] = bad["might"]  # two aptitudes claim one value
        with pytest.raises(ValueError, match="only one aptitude"):
            build_character(SEED, CID, name="Ash", assignment=bad)

    def test_out_of_range_index_rejected(self):
        bad = _identity_assignment()
        bad["might"] = 99
        with pytest.raises(ValueError, match="out of range"):
            build_character(SEED, CID, name="Ash", assignment=bad)


class TestEvents:
    def test_guided_event_records_the_assignment(self):
        char = build_character(SEED, CID, name="Ash", assignment=_identity_assignment())
        [spec] = chargen_events(
            char, location_id="loc.harrowdown.tavern", region="lundmarch", world_time=0
        )
        assert spec.payload["chargen_mode"] == "guided"
        assert spec.payload["assignment"] == _identity_assignment()
        assert spec.rng["index"] == len(APTITUDES) + MAX_REROLLS - 1  # pool of 7 -> index 6

    def test_auto_event_is_unchanged(self):
        char = roll_character(SEED, CID, name="Ash")
        [spec] = chargen_events(
            char, location_id="loc.harrowdown.tavern", region="lundmarch", world_time=0
        )
        assert "assignment" not in spec.payload  # auto path payload untouched
        assert "chargen_mode" not in spec.payload
        assert spec.rng["index"] == len(APTITUDES) - 1
