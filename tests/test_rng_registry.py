"""Roll-site registry: append-only table, per-site streams."""

from __future__ import annotations

import json
from pathlib import Path

from everquill_engine.rng_registry import (
    ROLL_SITES,
    action_outcome_stream,
    chargen_stream,
    hopeless_flavor_stream,
    timer_fire_stream,
)

FIXTURE_PATH = Path(__file__).parent / "golden" / "roll_sites.json"


class TestAppendOnlyRegistry:
    def test_registered_sites_never_change_or_vanish(self):
        """Every frozen site must exist in the registry with the exact
        frozen spec. Changing a stream template re-keys historical dice;
        that is a replay break, not a refactor."""
        frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["sites"]
        for site_id, spec in frozen.items():
            assert site_id in ROLL_SITES, (
                f"roll site {site_id!r} was REMOVED — the registry is append-only"
            )
            site = ROLL_SITES[site_id]
            assert list(site.stream) == spec["stream"], (
                f"roll site {site_id!r} changed its stream template — that re-keys "
                "historical dice; add a NEW site instead"
            )
            assert site.draws == spec["draws"] and site.owner == spec["owner"], (
                f"roll site {site_id!r} changed its frozen spec"
            )

    def test_new_sites_must_be_appended_to_the_fixture(self):
        frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["sites"]
        unfrozen = set(ROLL_SITES) - set(frozen)
        assert not unfrozen, (
            f"roll sites {sorted(unfrozen)} are not in tests/golden/roll_sites.json — "
            "append them (with a documented reason) in the same commit"
        )

    def test_every_site_has_a_distinct_stream_template(self):
        templates = [site.stream for site in ROLL_SITES.values()]
        assert len(templates) == len(set(templates))


class TestStreamBuilders:
    def test_builders_match_registry_templates(self):
        assert chargen_stream("pc") == ("chargen", "pc")
        assert action_outcome_stream("pc", "physical") == (
            "character:pc", "action:physical",
        )
        assert hopeless_flavor_stream("pc") == ("character:pc", "hopeless_flavor")
        assert timer_fire_stream("timer_pc_7") == ("timerfire", "timer_pc_7")

    def test_every_action_type_has_its_own_stream(self):
        streams = {
            action_outcome_stream("pc", a.split(":", 1)[1])
            for a in ROLL_SITES
            if a.startswith("action:")
        }
        assert len(streams) == sum(1 for a in ROLL_SITES if a.startswith("action:"))

    def test_unregistered_action_type_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            action_outcome_stream("pc", "teleport")

    def test_new_site_draws_never_shift_existing_sites(self):
        """The per-site stream property itself: drawing on one site's stream
        leaves every other registered site's sequence untouched."""
        from everquill_engine.dice import roll_2d6

        seed = 20260713
        physical_before = [
            roll_2d6(seed, action_outcome_stream("pc", "physical"), i) for i in range(5)
        ]
        # Burn draws on every OTHER site.
        for i in range(25):
            roll_2d6(seed, hopeless_flavor_stream("pc"), i)
            roll_2d6(seed, action_outcome_stream("pc", "social"), i)
            roll_2d6(seed, chargen_stream("pc"), i)
            roll_2d6(seed, timer_fire_stream("timer_pc_1"), i)
        physical_after = [
            roll_2d6(seed, action_outcome_stream("pc", "physical"), i) for i in range(5)
        ]
        assert physical_before == physical_after
