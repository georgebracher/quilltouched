"""Fold purity + golden-corpus replay (synthesis §2.6 rule 5, test T1).

The golden corpus freezes one sample event per (event_type,
payload_version) EVER shipped — the authoritative pair list is
everquill_engine.upcasters.SHIPPED_PAYLOAD_VERSIONS; a shipped pair
without a fixture fails the build. Folding the corpus must
produce exactly the frozen projection snapshot; any diff fails the
build unless the snapshot is regenerated IN THE SAME COMMIT with a
documented fold-logic reason:

    EVERQUILL_UPDATE_GOLDEN=1 .venv/bin/python -m pytest tests/test_folds.py

THE VERSION GATE: the snapshot also freezes the corpus hash
and folds.PROJECTOR_VERSIONS. When the corpus is UNCHANGED but a
projection's folded output differs, regeneration is REFUSED unless that
projection's PROJECTOR_VERSIONS entry was bumped in the same commit —
a fold change can never ship as a silent snapshot refresh.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from everquill_engine.events import EventType
from everquill_engine.folds import PROJECTOR_VERSIONS, FoldState, fold_event
from everquill_engine.upcasters import (
    CURRENT_PAYLOAD_VERSIONS,
    SHIPPED_PAYLOAD_VERSIONS,
    UPCASTERS,
)

GOLDEN_DIR = Path(__file__).parent / "golden"
EVENTS_PATH = GOLDEN_DIR / "golden_events.json"
SNAPSHOT_PATH = GOLDEN_DIR / "golden_folds_snapshot.json"

#: snapshot section name -> PROJECTOR_VERSIONS projection name
_SECTION_PROJECTION = {
    "world": "world_state",
    "characters": "character_sheet",
    "entities": "entity_state",
    "claims": "claim",
    "claim_evidence": "claim_evidence",
    "manifest": "scene_manifest",
    "timers": "timer",
    "reputation": "reputation",
    "deeds": "deeds",
}


def _shipped_pairs() -> set[tuple[str, int]]:
    return {
        (event_type, version)
        for event_type, versions in SHIPPED_PAYLOAD_VERSIONS.items()
        for version in versions
    }


def _fold_corpus() -> dict:
    state = FoldState()
    events = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))["events"]
    for event in events:
        fold_event(state, event)
    return {
        "world": state.world,
        "characters": state.characters,
        "entities": state.entities,  # entity_state projection
        "claims": state.claims,
        "claim_evidence": {
            f"{claim_id}::{event_id}": link
            for (claim_id, event_id), link in state.claim_evidence.items()
        },
        "manifest": state.manifest,
        "timers": state.timers,
        "reputation": state.reputation,
        "deeds": state.deeds,
    }


class TestGoldenCorpus:
    def test_corpus_covers_every_shipped_pair_exactly(self):
        """Synthesis §2.6 rule 5 as projector-version demands it: coverage is per
        (event_type, payload_version) PAIR — adding v2 of a type without
        a v2 fixture fails here."""
        events = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))["events"]
        corpus_pairs = {
            (e["event_type"], e.get("payload_version", 1)) for e in events
        }
        assert corpus_pairs == _shipped_pairs()
        # And every shipped type is a real taxonomy member.
        assert set(SHIPPED_PAYLOAD_VERSIONS) <= {t.value for t in EventType}

    def test_shipped_version_registry_is_coherent(self):
        """Versions are 1..current with no gaps; every non-current shipped
        version has a registered upcaster step (the chain is total)."""
        for event_type, versions in SHIPPED_PAYLOAD_VERSIONS.items():
            current = CURRENT_PAYLOAD_VERSIONS[event_type]
            assert versions == tuple(range(1, current + 1)), event_type
            for version in versions[:-1]:
                assert (event_type, version) in UPCASTERS, (
                    f"no upcaster for shipped pair ({event_type}, v{version})"
                )
        assert set(SHIPPED_PAYLOAD_VERSIONS) == set(CURRENT_PAYLOAD_VERSIONS)

    def test_fold_output_matches_frozen_snapshot(self):
        corpus_bytes = EVENTS_PATH.read_bytes()
        folded = {
            "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
            "projector_versions": dict(sorted(PROJECTOR_VERSIONS.items())),
            "projections": json.loads(json.dumps(_fold_corpus(), sort_keys=True)),
        }
        frozen = (
            json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            if SNAPSHOT_PATH.exists()
            else None
        )
        if os.environ.get("EVERQUILL_UPDATE_GOLDEN") == "1":
            self._version_gate(frozen, folded)
            SNAPSHOT_PATH.write_text(
                json.dumps(folded, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            frozen = folded
        assert frozen is not None, (
            "golden snapshot missing — run once with EVERQUILL_UPDATE_GOLDEN=1"
        )
        assert folded == frozen, (
            "fold output diverged from the golden snapshot. If the fold logic "
            "changed ON PURPOSE, bump the affected projection in "
            "folds.PROJECTOR_VERSIONS and regenerate with "
            "EVERQUILL_UPDATE_GOLDEN=1 in the same commit, documenting why."
        )

    @staticmethod
    def _version_gate(frozen: dict | None, folded: dict) -> None:
        """Refuse to regenerate over a fold change without a version bump.
        Only enforceable when the corpus itself is unchanged (a grown
        corpus legitimately changes output for unbumped projections)."""
        if frozen is None or "projections" not in frozen:
            return  # first generation / pre-gate snapshot format
        if frozen.get("corpus_sha256") != folded["corpus_sha256"]:
            return
        stale = [
            (section, projection)
            for section, projection in _SECTION_PROJECTION.items()
            if frozen["projections"].get(section) != folded["projections"].get(section)
            and frozen["projector_versions"].get(projection)
            == folded["projector_versions"].get(projection)
        ]
        assert not stale, (
            "EVERQUILL_UPDATE_GOLDEN refused: fold output changed for "
            f"{[p for _, p in stale]} but folds.PROJECTOR_VERSIONS was not "
            "bumped for them — a fold change must ship with its version bump "
            "(HIGH-3)."
        )

    def test_unknown_event_type_raises(self):
        with pytest.raises(ValueError):
            fold_event(FoldState(), {
                "id": 1, "event_type": "mystery_event", "world_time": 0,
                "payload": {}, "rng": None,
            })

    def test_unknown_delta_type_raises(self):
        state = FoldState()
        state.characters["pc"] = {
            "entity_id": "pc", "hp": 5, "hp_max": 9, "coin": 0, "aptitudes": {},
            "inventory": {}, "flags": {}, "titles": [], "location_id": None,
            "name": "x", "origin": "o", "last_event_id": 0,
        }
        with pytest.raises(ValueError):
            fold_event(state, {
                "id": 2, "event_type": "outcome_resolved", "world_time": 0, "rng": None,
                "payload": {"state_deltas": [{"delta_type": "mana", "entity_id": "pc"}]},
            })


class TestFoldPurity:
    def test_folds_import_no_engine_rules(self):
        """THE hard invariant: folds consume stored deltas only — no
        dice, ladder, resolver, chargen, clock, world (or DB) imports.
        Event sourcing, not command sourcing."""
        source = (
            Path(__file__).parent.parent / "everquill_engine" / "folds.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {
            "everquill_engine.dice", "everquill_engine.ladder",
            "everquill_engine.resolver", "everquill_engine.chargen",
            "everquill_engine.clock", "everquill_engine.world",
            "everquill_engine.db", "everquill_engine.store", "psycopg",
        }
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        # A submodule of a forbidden package (everquill_engine.resolver.tier) counts too.
        imported |= {f for f in forbidden for m in imported if m.startswith(f + ".")}
        assert not (imported & forbidden), f"folds.py imports rules/DB: {imported & forbidden}"

    def test_fold_applies_stored_amounts_blindly(self):
        """A fold must never clamp/derive — the stored amount IS the change."""
        state = FoldState()
        state.characters["pc"] = {
            "entity_id": "pc", "hp": 2, "hp_max": 9, "coin": 0, "aptitudes": {},
            "inventory": {}, "flags": {}, "titles": [], "location_id": None,
            "name": "x", "origin": "o", "last_event_id": 0,
        }
        fold_event(state, {
            "id": 3, "event_type": "outcome_resolved", "world_time": 0, "rng": None,
            "payload": {"state_deltas": [
                {"delta_type": "hp", "entity_id": "pc", "amount": -7, "cause": None}
            ]},
        })
        assert state.characters["pc"]["hp"] == -5  # blind application, no clamp


def _entity_committed(entity_id="npc.dev.hedda", *, hp=9, event_id=1):
    return {
        "id": event_id, "event_type": "entity_committed", "world_time": 0, "rng": None,
        "stream_id": "world",
        "payload": {
            "entity_id": entity_id, "entity_class": "npc", "origin": "authored",
            "name": "X", "location_id": "loc.dev.tavern", "region": "dev",
            "common_knowledge": [], "portrait": None, "hp": hp, "hp_max": hp,
        },
    }


def _outcome(deltas, event_id=2):
    return {
        "id": event_id, "event_type": "outcome_resolved", "world_time": 0, "rng": None,
        "payload": {"state_deltas": deltas},
    }


class TestEntityStateFolds:
    """NPC deltas fold into entity_state; no row -> raise."""

    def test_hp_condition_position_fold_into_entity_state(self):
        state = FoldState()
        fold_event(state, _entity_committed())
        fold_event(state, _outcome([
            {"delta_type": "hp", "entity_id": "npc.dev.hedda", "amount": -3, "cause": None},
            {"delta_type": "condition", "entity_id": "npc.dev.hedda",
             "op": "add", "condition": "winded"},
            {"delta_type": "position", "entity_id": "npc.dev.hedda",
             "from_location_id": "loc.dev.tavern", "to_location_id": "loc.dev.yard"},
        ]))
        row = state.entities["npc.dev.hedda"]
        assert row["hp"] == 6 and row["hp_max"] == 9
        assert row["conditions"] == ["winded"]
        assert row["location_id"] == "loc.dev.yard"
        assert row["updated_from_event_id"] == 2
        # scene manifest follows the position delta, same as characters
        assert state.manifest["npc.dev.hedda"]["location_id"] == "loc.dev.yard"
        fold_event(state, _outcome([
            {"delta_type": "condition", "entity_id": "npc.dev.hedda",
             "op": "remove", "condition": "winded"},
        ], event_id=3))
        assert state.entities["npc.dev.hedda"]["conditions"] == []

    def test_delta_on_entity_without_state_row_raises_not_drops(self):
        state = FoldState()
        with pytest.raises(ValueError, match="no entity_state row"):
            fold_event(state, _outcome([
                {"delta_type": "hp", "entity_id": "npc.dev.ghost", "amount": -3,
                 "cause": None},
            ]))

    def test_non_damageable_commit_seeds_no_state(self):
        state = FoldState()
        event = _entity_committed()
        del event["payload"]["hp"], event["payload"]["hp_max"]
        fold_event(state, event)
        assert state.entities == {}


class TestDomainIdFoldsRaise:
    """Duplicate claim_id / timer_key raise in the SAME fold both
    incremental projection and rebuild use — no silent disagreement."""

    CLAIM = {
        "id": 4, "event_type": "claim_written", "world_time": 0, "rng": None,
        "payload": {
            "claim_id": "claim_dup", "believer_id": "pc",
            "claim": {
                "subject_entity_id": "npc.dev.hedda", "claim_text": "t",
                "value_or_range": None, "layer": "inquiry", "source": "s",
                "observer": None, "method": "witnessed", "world_date": "Day 1, 06:00",
                "scope": "local", "confidence": "consistent",
            },
            "provenance_root_event_id": 1, "hop_count": 0, "journal_flag": False,
        },
    }
    TIMER = {
        "id": 5, "event_type": "timer_started", "world_time": 0, "rng": None,
        "payload": {
            "timer_key": "timer_dup", "kind": "training", "subject_id": "pc",
            "world_due": 480, "due_at": "1970-01-01T08:00:00+00:00",
            "payload": {"aptitude": "will", "owner_id": "pc"},
            "created_event_id": 1,
        },
    }

    def test_duplicate_claim_id_raises(self):
        state = FoldState()
        fold_event(state, dict(self.CLAIM))
        with pytest.raises(ValueError, match="duplicate claim_id"):
            fold_event(state, {**self.CLAIM, "id": 6})

    def test_duplicate_timer_key_raises(self):
        state = FoldState()
        fold_event(state, dict(self.TIMER))
        with pytest.raises(ValueError, match="duplicate timer_key"):
            fold_event(state, {**self.TIMER, "id": 7})

    def test_timer_due_at_fact_folds_verbatim(self):
        """The payload's due_at IS the deadline; the legacy shim
        derives it from the documented epoch mapping only when absent."""
        state = FoldState()
        fold_event(state, dict(self.TIMER))
        assert state.timers["timer_dup"]["due_at"] == "1970-01-01T08:00:00+00:00"
        legacy = {**self.TIMER, "id": 8}
        legacy["payload"] = {k: v for k, v in self.TIMER["payload"].items() if k != "due_at"}
        legacy["payload"]["timer_key"] = "timer_legacy"
        state2 = FoldState()
        fold_event(state2, legacy)
        assert state2.timers["timer_legacy"]["due_at"] == "1970-01-01T08:00:00+00:00"
