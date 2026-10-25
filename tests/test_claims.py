"""Claim schema v2 vocabulary + lifecycle rules (pure tests).

The closed predicate registry, the parser-boundary enforcement hook,
the strength model (per-method base weights, integer decay), and the
deterministic write-time revision rule. DB integration (probe + events)
lives in tests/test_db_claims.py.
"""

from __future__ import annotations

import pytest

from everquill_engine.claims import (
    ACQUISITION_FOR_METHOD,
    ACQUISITION_METHODS,
    ACTIVE_STATUSES,
    BASE_EVIDENCE_WEIGHT,
    CLAIM_STATUSES,
    PREDICATES,
    STRENGTH_HALF_LIFE_MINUTES,
    SUPERSEDED_REASONS,
    PredicateError,
    acquisition_for_method,
    corroboration_status,
    decayed_weight,
    enforce_predicate,
    evidence_strength,
    revise,
)


class TestRegistry:
    def test_five_lifecycle_states(self):
        assert CLAIM_STATUSES == (
            "asserted", "corroborated", "contested", "superseded", "retracted"
        )
        assert set(ACTIVE_STATUSES) == {"asserted", "corroborated", "contested"}

    def test_base_weight_ordering_is_binding(self):
        """observed > told > rumor > inherited_journal > overheard —
        the original ticket's evidence hierarchy, exactly."""
        assert ACQUISITION_METHODS == (
            "observed", "told", "rumor", "inherited_journal", "overheard"
        )
        weights = [BASE_EVIDENCE_WEIGHT[m] for m in ACQUISITION_METHODS]
        assert weights == sorted(weights, reverse=True)
        assert len(set(weights)) == len(weights)  # strict ordering

    def test_superseded_reasons_closed(self):
        assert SUPERSEDED_REASONS == (
            "better_evidence", "direct_observation", "source_recanted", "canon_sealed"
        )

    def test_every_v1_method_maps_into_the_closed_vocabulary(self):
        for method, acquisition in ACQUISITION_FOR_METHOD.items():
            assert acquisition in BASE_EVIDENCE_WEIGHT, method
        assert acquisition_for_method("witnessed") == "observed"
        assert acquisition_for_method("conversation") == "told"
        assert acquisition_for_method("never_seen_before") == "told"  # conservative middle

    def test_exclusive_predicates_require_their_value(self):
        for spec in PREDICATES.values():
            if spec.exclusive:
                assert spec.value_required, (
                    f"{spec.predicate}: exclusivity contradicts an optional value — "
                    "the value IS the thing contradicted"
                )


class TestEnforcePredicate:
    """THE parser-boundary hook (exported for llm/)."""

    def test_unknown_predicate_rejected(self):
        with pytest.raises(PredicateError, match="closed"):
            enforce_predicate("vibes_about")

    def test_wrong_value_column_rejected(self):
        with pytest.raises(PredicateError, match="value_type"):
            enforce_predicate("threat_assessed", value_num=3)

    def test_required_value_missing_rejected(self):
        with pytest.raises(PredicateError, match="requires"):
            enforce_predicate("threat_assessed")

    def test_optional_value_predicates_accept_absence(self):
        assert enforce_predicate("observed_statement").predicate == "observed_statement"
        assert enforce_predicate("personal_lesson", value_text="x").value_type == "text"

    def test_world_valid_only_on_ranged_predicates(self):
        enforce_predicate("whereabouts", value_text="loc.dev.tavern", world_valid=[0, 100])
        with pytest.raises(PredicateError, match="world_valid"):
            enforce_predicate("threat_assessed", value_text="RISKY", world_valid=[0, 100])

    def test_integer_only_values(self):
        with pytest.raises(PredicateError, match="int"):
            enforce_predicate(  # Floats never enter folded domains
                "whereabouts", value_text="loc.a", world_valid=[0.5, 2]
            )


def _link(root, base=100, world_time=0):
    return {"root_event_id": root, "base_weight": base, "world_time": world_time}


class TestStrengthModel:
    def test_decay_halves_per_half_life_floor_one(self):
        assert decayed_weight(100, 0) == 100
        assert decayed_weight(100, STRENGTH_HALF_LIFE_MINUTES - 1) == 100
        assert decayed_weight(100, STRENGTH_HALF_LIFE_MINUTES) == 50
        assert decayed_weight(100, STRENGTH_HALF_LIFE_MINUTES * 2) == 25
        assert decayed_weight(100, STRENGTH_HALF_LIFE_MINUTES * 40) == 1  # floor

    def test_evidence_strength_is_the_decayed_sum(self):
        links = [_link(1, 100, 0), _link(2, 60, STRENGTH_HALF_LIFE_MINUTES)]
        # at now = one half-life: 100>>1=50 for the old, 60>>0=60 for the fresh
        assert evidence_strength(links, STRENGTH_HALF_LIFE_MINUTES) == 50 + 60

    def test_corroboration_needs_distinct_roots(self):
        """THE echo-chamber rule: one root, however many retellings,
        never corroborates."""
        assert corroboration_status([_link(7), _link(7), _link(7)]) == "asserted"
        assert corroboration_status([_link(7), _link(8)]) == "corroborated"


def _claim(claim_id, predicate="threat_assessed", value_text="RISKY",
           method="observed", text="t"):
    return {
        "claim_id": claim_id,
        "predicate": predicate,
        "value_text": value_text,
        "value_num": None,
        "value_range": None,
        "world_valid": None,
        "claim_text": text,
        "acquisition_method": method,
        "believer_id": "pc",
        "subject_entity_id": "npc.x",
        "status": "asserted",
        "strength": BASE_EVIDENCE_WEIGHT[method],
    }


class TestRevisionRule:
    def test_equal_value_corroborates_the_oldest_match(self):
        actions = revise(
            new_claim=_claim("c9"),
            new_strength=100,
            existing=[_claim("c1"), _claim("c2")],
            existing_strength={"c1": 100, "c2": 100},
        )
        assert [a.kind for a in actions] == ["corroborate"]
        assert actions[0].claim_id == "c1"

    def test_no_value_predicates_fall_back_to_claim_text_equality(self):
        existing = [_claim("c1", "personal_lesson", None, "observed", "lesson A")]
        same = revise(
            new_claim=_claim("c9", "personal_lesson", None, "observed", "lesson A"),
            new_strength=100, existing=existing, existing_strength={"c1": 100},
        )
        assert [a.kind for a in same] == ["corroborate"]
        different = revise(
            new_claim=_claim("c9", "personal_lesson", None, "observed", "lesson B"),
            new_strength=100, existing=existing, existing_strength={"c1": 100},
        )
        assert [a.kind for a in different] == ["insert"]

    def test_non_exclusive_different_values_coexist(self):
        actions = revise(
            new_claim=_claim("c9", "common_knowledge", "fact B"),
            new_strength=60,
            existing=[_claim("c1", "common_knowledge", "fact A")],
            existing_strength={"c1": 60},
        )
        assert [a.kind for a in actions] == ["insert"]

    def test_exclusive_conflict_weaker_new_contests_both_ways(self):
        actions = revise(
            new_claim=_claim("c9", value_text="DESPERATE", method="told"),
            new_strength=60,
            existing=[_claim("c1", value_text="RISKY", method="observed")],
            existing_strength={"c1": 100},
        )
        assert [a.kind for a in actions] == ["insert", "contest", "contest"]
        assert {(a.claim_id, a.other_claim_id) for a in actions[1:]} == {
            ("c1", "c9"), ("c9", "c1"),
        }

    def test_exclusive_conflict_stronger_new_supersedes(self):
        actions = revise(
            new_claim=_claim("c9", value_text="DESPERATE", method="observed"),
            new_strength=100,
            existing=[_claim("c1", value_text="RISKY", method="told")],
            existing_strength={"c1": 60},
        )
        assert [a.kind for a in actions] == ["insert", "supersede"]
        assert actions[1].claim_id == "c1"
        assert actions[1].other_claim_id == "c9"
        assert actions[1].reason == "direct_observation"

    def test_fresh_observation_wins_strength_ties(self):
        """A new direct observation supersedes an equal-strength stale one
        (lens: superseded_reason 'direct_observation')."""
        actions = revise(
            new_claim=_claim("c9", value_text="DESPERATE", method="observed"),
            new_strength=100,
            existing=[_claim("c1", value_text="RISKY", method="observed")],
            existing_strength={"c1": 100},
        )
        assert [a.kind for a in actions] == ["insert", "supersede"]
        assert actions[1].reason == "direct_observation"

    def test_non_observed_ties_contest(self):
        actions = revise(
            new_claim=_claim("c9", value_text="DESPERATE", method="told"),
            new_strength=60,
            existing=[_claim("c1", value_text="RISKY", method="told")],
            existing_strength={"c1": 60},
        )
        assert [a.kind for a in actions] == ["insert", "contest", "contest"]

    def test_non_overlapping_world_valid_does_not_conflict(self):
        old = _claim("c1", "whereabouts", "loc.a")
        old["world_valid"] = [0, 100]
        new = _claim("c9", "whereabouts", "loc.b")
        new["world_valid"] = [200, 300]
        actions = revise(
            new_claim=new, new_strength=100, existing=[old],
            existing_strength={"c1": 100},
        )
        assert [a.kind for a in actions] == ["insert"]
