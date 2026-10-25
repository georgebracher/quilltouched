"""Chargen: locked vocabulary, deterministic rolls, derived facts stored."""

from __future__ import annotations

from everquill_engine.chargen import STARTING_COIN, chargen_events, roll_character
from everquill_engine.world import APTITUDES


class TestVocabulary:
    def test_locked_aptitude_vocabulary_and_order(self):
        assert APTITUDES == ("might", "finesse", "wits", "will", "presence", "lore")

    def test_rolls_cover_exactly_the_vocabulary(self):
        rolled = roll_character(7, "pc", name="x")
        assert tuple(rolled.aptitudes) == APTITUDES
        assert tuple(rolled.rolls) == APTITUDES


class TestDeterminism:
    def test_same_seed_same_character(self):
        a = roll_character(42, "pc", name="x")
        b = roll_character(42, "pc", name="x")
        assert a.aptitudes == b.aptitudes and a.rolls == b.rolls

    def test_seed_and_character_id_both_matter(self):
        base = roll_character(42, "pc", name="x")
        assert roll_character(43, "pc", name="x").aptitudes != base.aptitudes
        assert roll_character(42, "heir", name="x").aptitudes != base.aptitudes

    def test_pinned_seed_42(self):
        """Frozen: the dev-fixture demo character. If the roll scheme
        changes this pin must be updated WITH a documented reason (it
        invalidates every existing dev world)."""
        rolled = roll_character(42, "pc", name="the Quill-touched")
        assert rolled.aptitudes == {
            "might": 5, "finesse": 7, "wits": 10, "will": 7, "presence": 4, "lore": 7,
        }
        assert rolled.hp_max == 9  # 4 + might


class TestRangesAndFacts:
    def test_ranges_2_to_12(self):
        for seed in range(30):
            rolled = roll_character(seed, "pc", name="x")
            assert all(2 <= v <= 12 for v in rolled.aptitudes.values())
            assert all(
                v == sum(rolled.rolls[k]) for k, v in rolled.aptitudes.items()
            )

    def test_event_stores_facts_not_rules(self):
        """The payload carries resolved hp/coin so folds never derive them."""
        rolled = roll_character(1, "pc", name="x")
        (spec,) = chargen_events(rolled, location_id="loc.d.t", region="d", world_time=0)
        payload = dict(spec.payload)
        assert payload["hp"] == payload["hp_max"] == 4 + rolled.aptitudes["might"]
        assert payload["coin"] == STARTING_COIN
        assert spec.rng is not None and len(spec.rng["rolls"]) == 12
        assert spec.rng["stream"] == ["chargen", "pc"]
