"""Upcaster registry: purity lint, chain totality, v1→v2 shapes.

Golden-corpus coverage per (event_type, payload_version) pair is
enforced in tests/test_folds.py; this file proves the upcasters
themselves.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from everquill_engine import claims
from everquill_engine import upcasters as upcasters_mod
from everquill_engine.upcasters import (
    CURRENT_PAYLOAD_VERSIONS,
    SHIPPED_PAYLOAD_VERSIONS,
    UPCASTERS,
    UpcastError,
    upcast,
)


class TestPurity:
    def test_upcasters_import_no_engine_rules(self):
        """Synthesis §2.6 rule 1: upcasters are pure functions with NO
        engine imports — the same AST lint pattern as folds. A rules or
        persistence import here would let a balance patch silently
        rewrite history at upcast time."""
        source = (
            Path(__file__).parent.parent / "everquill_engine" / "upcasters.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {
            "everquill_engine.dice", "everquill_engine.ladder",
            "everquill_engine.resolver", "everquill_engine.chargen",
            "everquill_engine.clock", "everquill_engine.world",
            "everquill_engine.db", "everquill_engine.store",
            "everquill_engine.folds", "everquill_engine.claims",
            "everquill_engine.crypto", "psycopg",
        }
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        # A submodule of a forbidden package (everquill_engine.resolver.tier) counts too.
        imported |= {f for f in forbidden for m in imported if m.startswith(f + ".")}
        assert not (imported & forbidden), (
            f"upcasters.py imports engine modules: {imported & forbidden}"
        )

    def test_frozen_copies_have_not_drifted_from_the_registry(self):
        """upcasters.py may not import claims.py (purity), so it carries
        frozen copies of the v1-method map and base weights. Drift here
        means an upcast claim and a freshly-written claim would disagree."""
        assert upcasters_mod._ACQUISITION_FOR_METHOD == claims.ACQUISITION_FOR_METHOD
        assert upcasters_mod._BASE_EVIDENCE_WEIGHT == claims.BASE_EVIDENCE_WEIGHT


def _v1_claim_payload():
    return {
        "claim_id": "claim_pc_1_1",
        "believer_id": "pc",
        "claim": {
            "subject_entity_id": "npc.dev.hedda",
            "claim_text": "Hedda favors her left arm.",
            "value_or_range": "RISKY",
            "layer": "inquiry",
            "source": "the bout itself",
            "observer": "pc",
            "method": "witnessed",
            "world_date": "Day 1, 06:10",
            "scope": "firsthand",
            "confidence": "consistent",
        },
        "provenance_root_event_id": 5,
        "hop_count": 0,
        "journal_flag": False,
    }


def _row(event_type, payload, version=1):
    return {
        "id": 6, "event_type": event_type, "world_time": 10, "rng": None,
        "payload": payload, "payload_version": version,
    }


class TestClaimWrittenChain:
    def test_v1_maps_to_observed_statement_with_provenance_preserved(self):
        out = upcast(_row("claim_written", _v1_claim_payload()))
        assert out["payload_version"] == 2
        claim = out["payload"]["claim"]
        assert claim["predicate"] == "observed_statement"
        assert claim["value_text"] == "RISKY"
        assert "value_or_range" not in claim
        assert claim["acquisition_method"] == "observed"  # witnessed
        assert claim["source_agent_id"] is None
        assert claim["claim_text"] == "Hedda favors her left arm."
        assert out["payload"]["provenance_root_event_id"] == 5
        assert out["payload"]["strength"] == claims.BASE_EVIDENCE_WEIGHT["observed"]
        assert out["payload"]["derived_from_claim_id"] is None

    def test_input_row_is_never_mutated(self):
        payload = _v1_claim_payload()
        row = _row("claim_written", payload)
        upcast(row)
        assert row["payload_version"] == 1
        assert "predicate" not in payload["claim"]


class TestOutcomeResolvedChain:
    def test_v1_deltas_gain_typed_claims_and_transit_hints(self):
        payload = {
            "state_deltas": [
                {"delta_type": "intel", "claim": _v1_claim_payload()["claim"]},
                {"delta_type": "position", "entity_id": "pc",
                 "from_location_id": "loc.a", "to_location_id": "loc.b"},
                {"delta_type": "hp", "entity_id": "pc", "amount": -1, "cause": None},
            ]
        }
        out = upcast(_row("outcome_resolved", payload))
        intel, position, hp = out["payload"]["state_deltas"]
        assert intel["claim"]["predicate"] == "observed_statement"
        assert position["transit_hint"] == "unknown"
        assert hp == payload["state_deltas"][2]

    def test_v2_shapes_pass_through_unchanged(self):
        v2_claim = upcast(_row("claim_written", _v1_claim_payload()))["payload"]["claim"]
        payload = {
            "state_deltas": [
                {"delta_type": "intel", "claim": v2_claim},
                {"delta_type": "position", "entity_id": "pc",
                 "from_location_id": "loc.a", "to_location_id": "loc.b",
                 "transit_hint": "walked"},
            ]
        }
        out = upcast(_row("outcome_resolved", dict(payload), version=2))
        assert out["payload"]["state_deltas"][0]["claim"]["predicate"] == "observed_statement"
        assert out["payload"]["state_deltas"][1]["transit_hint"] == "walked"


class TestChainMechanics:
    def test_current_version_rows_pass_through_as_the_same_object(self):
        row = _row("deed_recorded", {"deed": {}}, version=1)
        assert upcast(row) is row

    def test_intent_parsed_v1_upcasts_to_identical_v2(self):
        payload = {"character_id": "pc", "intent": {"approach": "x"}, "source": "canned"}
        out = upcast(_row("intent_parsed", payload))
        assert out["payload_version"] == 2
        assert out["payload"] == payload

    def test_unknown_event_types_pass_through_for_folds_own_error(self):
        row = _row("mystery_event", {})
        assert upcast(row) is row

    def test_future_versions_are_refused(self):
        with pytest.raises(UpcastError, match="NEWER"):
            upcast(_row("claim_written", {}, version=99))

    def test_missing_chain_step_is_loud(self):
        # claim_written currently chains 1→2; a fabricated v0 has no path.
        with pytest.raises(UpcastError, match="no upcaster"):
            upcast(_row("claim_written", {}, version=0))

    def test_every_shipped_pair_reaches_current(self):
        for event_type, versions in SHIPPED_PAYLOAD_VERSIONS.items():
            current = CURRENT_PAYLOAD_VERSIONS[event_type]
            for version in versions[:-1]:
                walk = version
                while walk < current:
                    assert (event_type, walk) in UPCASTERS
                    walk += 1
