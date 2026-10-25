"""KnownState / RefereeState split: the safe read surface."""

from __future__ import annotations

import dataclasses
import json

import pytest

from everquill_engine.folds import fold_event
from everquill_engine.slots import Slot
from everquill_engine.views import (
    WOUND_BANDS,
    KnownState,
    RefereeState,
    entity_category,
    load_known_state,
    outcome_public,
    wound_words,
)
from tests.harness import REPO_ROOT, Sim


def _claim_written(claim_id, *, root, event_id, subject="npc.dev.hedda"):
    """A v1-shaped inquiry claim_written (upcasts to observed_statement)."""
    return {
        "id": event_id, "event_type": "claim_written", "world_time": 0, "rng": None,
        "payload_version": 1,
        "payload": {
            "claim_id": claim_id, "believer_id": "pc",
            "claim": {
                "subject_entity_id": subject, "claim_text": f"about {claim_id}",
                "value_or_range": None, "layer": "inquiry", "source": "s",
                "observer": "pc", "method": "witnessed", "world_date": "Day 1, 06:00",
                "scope": "local", "confidence": "consistent",
            },
            "provenance_root_event_id": root, "hop_count": 0, "journal_flag": False,
        },
    }


def _claim_contested(claim_id, contested_by, *, event_id):
    return {
        "id": event_id, "event_type": "claim_contested", "world_time": 0, "rng": None,
        "payload_version": 1,
        "payload": {"claim_id": claim_id, "contested_by_claim_id": contested_by},
    }

HARROWDOWN = REPO_ROOT / "content" / "world" / "harrowdown.yaml"


def canned(action_type, targets=(), approach="do the thing", stat_hint=None):
    return {
        "action_type": action_type,
        "target_entity_ids": list(targets),
        "approach": approach,
        "stat_hint": stat_hint,
        "dialogue": None,
        "plausibility_hint": "plausible",
        "duration_hint": None,
        "ambiguity_flags": [],
        "addressee": None,
        "speech_act": None,
        "topic_ids": [],
        "transaction": None,
        "invoked_law_ids": [],
        "movement_scope": None,
    }


TAVERN_SLOTS = {
    "tavern": (
        Slot("tavern_bar", 64, 72),
        Slot("tavern_center", 52, 81),
        Slot("tavern_left", 37, 88),
        Slot("tavern_right", 66, 90),
    )
}


@pytest.fixture()
def sim():
    return Sim(seed=42)


def known(sim, slot_maps=TAVERN_SLOTS) -> KnownState:
    return load_known_state(sim.state, sim.world, slot_maps)


def _known_blob(state: KnownState, sim) -> str:
    """Serialize EVERYTHING a KnownState can produce."""
    payload = {
        "world_date": state.world_date,
        "facts": dataclasses.asdict(state.chronicle_facts("pc")),
        "claims": [dataclasses.asdict(c) for c in state.inquiry_claims("pc")],
        "scene": dataclasses.asdict(state.scene("pc")),
    }
    return json.dumps(payload, sort_keys=True)


class TestWoundWords:
    def test_bands_are_words_and_deterministic(self):
        assert wound_words(9, 9) == "unhurt"
        assert wound_words(7, 9) == "scuffed"
        assert wound_words(5, 9) == "hurting"
        assert wound_words(3, 9) == "bloodied"
        assert wound_words(1, 9) == "at death's door"
        assert wound_words(0, 9) == "dispatched"
        for hp in range(-2, 12):
            assert wound_words(hp, 9) in WOUND_BANDS


class TestChronicleFacts:
    def test_exposes_chronicle_facts_only(self, sim):
        facts = known(sim).chronicle_facts("pc")
        assert facts.coin == 30  # exact — Chronicle numerals allowed
        assert facts.wounds == "unhurt"  # a WORD, never a number
        assert facts.named_abilities == ()
        assert facts.public_rank is None
        assert facts.location_id == "loc_dev_tavern"  # contract form
        as_dict = dataclasses.asdict(facts)
        assert "hp" not in as_dict and "hp_max" not in as_dict
        assert "aptitudes" not in as_dict

    def test_wounds_word_tracks_state(self, sim):
        sim.pc["hp"] = 3
        assert known(sim).chronicle_facts("pc").wounds == "bloodied"

    def test_unknown_character_raises(self, sim):
        with pytest.raises(KeyError):
            known(sim).chronicle_facts("nobody")


class TestInquiryClaims:
    def test_claims_carry_provenance_never_truth(self, sim):
        sim.run_turn(canned("observation", ["npc_dev_hedda"], "size her up", "wits"))
        claims = known(sim).inquiry_claims("pc", subject_id="npc_dev_hedda")
        assert claims, "observation should have written a claim"
        claim = claims[0]
        assert claim.subject_entity_id == "npc_dev_hedda"
        assert claim.method and claim.source and claim.scope
        assert claim.confidence in ("uncorroborated", "consistent", "strongly_corroborated")
        # value_or_range is band WORDS (the threat read), never a number.
        if claim.value_or_range is not None:
            assert not claim.value_or_range.isdigit()
        # claim v2 surface: typed key + evidence strength ride along.
        assert claim.predicate == "threat_assessed"
        assert claim.value_text == claim.value_or_range
        assert claim.acquisition_method == "observed"
        assert claim.strength > 0

    def test_dead_claims_leave_the_dossier(self, sim):
        """Superseded/retracted rows stay in the projection for audit but
        are no longer what the believer believes — inquiry_claims serves
        live statuses only (contested INCLUDED: both sides surface)."""
        from everquill_engine.folds import fold_event

        sim.run_turn(canned("observation", ["npc_dev_hedda"], "size her up", "wits"))
        (claim,) = known(sim).inquiry_claims("pc", subject_id="npc_dev_hedda")
        sim.next_id += 1
        fold_event(sim.state, {
            "id": sim.next_id, "event_type": "claim_retracted", "world_time": 100,
            "rng": None, "payload_version": 1,
            "payload": {"claim_id": claim.claim_id, "reason": "canon_sealed"},
        })
        assert known(sim).inquiry_claims("pc", subject_id="npc_dev_hedda") == ()
        assert sim.state.claims[claim.claim_id]["status"] == "retracted"  # audit row stays


class TestContradictionIds:
    """Audit #2: the contested link surfaces BOTH ways and does not lose
    edges when a claim is contested by several others (the single
    contested_by_claim_id column was lossy — contradiction_ids is the fix)."""

    def _inject(self, sim, events):
        for event in events:
            fold_event(sim.state, event)

    def test_two_conflicting_claims_report_the_link_both_ways(self, sim):
        self._inject(sim, [
            _claim_written("cx_a", root=1, event_id=1001),
            _claim_written("cx_b", root=2, event_id=1002),
            _claim_contested("cx_a", "cx_b", event_id=1003),
            _claim_contested("cx_b", "cx_a", event_id=1004),
        ])
        claims = {
            c.claim_id: c
            for c in known(sim).inquiry_claims("pc", subject_id="npc_dev_hedda")
        }
        assert claims["cx_a"].contradiction_ids == ("cx_b",)
        assert claims["cx_b"].contradiction_ids == ("cx_a",)
        # the single-column compat name still points the latest way each
        assert claims["cx_a"].contested_by_claim_id == "cx_b"
        assert claims["cx_b"].contested_by_claim_id == "cx_a"

    def test_multi_edge_contradiction_keeps_every_contester(self, sim):
        """cx_a contested by cx_b THEN cx_c: contested_by_claim_id would
        forget cx_b (last wins), contradiction_ids remembers both."""
        self._inject(sim, [
            _claim_written("cx_a", root=1, event_id=2001),
            _claim_written("cx_b", root=2, event_id=2002),
            _claim_written("cx_c", root=3, event_id=2003),
            _claim_contested("cx_a", "cx_b", event_id=2004),
            _claim_contested("cx_a", "cx_c", event_id=2005),
        ])
        (a,) = [
            c for c in known(sim).inquiry_claims("pc", subject_id="npc_dev_hedda")
            if c.claim_id == "cx_a"
        ]
        assert a.contradiction_ids == ("cx_b", "cx_c")  # sorted, both kept
        assert a.contested_by_claim_id == "cx_c"          # single column: last only

    def test_uncontested_claim_has_empty_contradiction_ids(self, sim):
        self._inject(sim, [_claim_written("cx_solo", root=1, event_id=3001)])
        (solo,) = known(sim).inquiry_claims("pc", subject_id="npc_dev_hedda")
        assert solo.contradiction_ids == ()


class TestEntityCategory:
    """Audit category-contract: the engine view emits ONE coarse category
    vocabulary — persons = npc + character — so the narration gate and the
    API adapter stop matching the fine-grained authored kind."""

    def test_person_is_npc_plus_character(self):
        assert entity_category("npc") == "person"
        assert entity_category("character") == "person"
        assert entity_category("creature") == "creature"
        assert entity_category("prop") == "object"
        assert entity_category("item") == "object"
        assert entity_category("location") == "place"
        # unmapped kinds fall back to the safe non-person default
        assert entity_category("eldritch_horror") == "object"

    def test_scene_entities_carry_the_category(self, sim):
        scene = known(sim).scene("pc")
        by_id = {e.entity_id: e for e in scene.entities}
        # the PC (kind 'character') and the tavern NPCs are all persons
        assert by_id["pc"].category == "person"
        assert by_id["pc"].kind == "character"
        assert by_id["npc_dev_hedda"].category == "person"
        assert by_id["npc_dev_hedda"].kind == "npc"


class TestSceneView:
    def test_scene_lists_perceived_entities_with_slots(self, sim):
        scene = known(sim).scene("pc")
        assert scene.location_id == "loc_dev_tavern"
        assert scene.location_type == "tavern"
        ids = [e.entity_id for e in scene.entities]
        assert ids == sorted(ids)  # stable ordering
        assert {"npc_dev_hedda", "npc_dev_sorrel", "npc_dev_torvald", "pc"} <= set(ids)
        slotted = [e for e in scene.entities if e.slot_id is not None]
        assert len(slotted) == 4  # four slots, four entities
        assert all(
            e.x_pct is not None and e.y_pct is not None for e in slotted
        )
        # Same scene → same arrangement.
        again = known(sim).scene("pc")
        assert again == scene

    def test_absent_slot_map_falls_back_to_null_slots(self, sim):
        scene = load_known_state(sim.state, sim.world, {}).scene("pc")
        assert all(e.slot_id is None and e.x_pct is None for e in scene.entities)
        ids = [e.entity_id for e in scene.entities]
        assert ids == sorted(ids)  # stable ordering survives the fallback

    def test_dispatched_condition_surfaced_at_zero_hp(self, sim):
        sim.state.entities["npc.dev.hedda"]["hp"] = 0
        scene = known(sim).scene("pc")
        (hedda,) = [e for e in scene.entities if e.entity_id == "npc_dev_hedda"]
        assert "dispatched" in hedda.conditions

    def test_wounded_condition_surfaced_when_visibly_hurt(self, sim):
        sim.state.entities["npc.dev.hedda"]["hp"] = 4
        scene = known(sim).scene("pc")
        (hedda,) = [e for e in scene.entities if e.entity_id == "npc_dev_hedda"]
        assert "wounded" in hedda.conditions and "dispatched" not in hedda.conditions

    def test_scene_lists_public_exits(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        sim.state.characters["pc"]["location_id"] = "loc.harrowdown.tavern"
        if "pc" in sim.state.manifest:
            sim.state.manifest["pc"]["location_id"] = "loc.harrowdown.tavern"
        scene = load_known_state(sim.state, sim.world, {}).scene("pc")
        assert [(e.id, e.name, e.carriage_days) for e in scene.exits] == [
            ("loc_harrowdown_market_row", "Market Row", 0),
        ]


class TestNoTrueSheetLeak:
    def test_known_state_serialization_contains_no_referee_data(self, sim):
        """The FULL KnownState surface, serialized, must contain no
        authored aptitude mapping, no threat band, no raw hp keys."""
        for entry in [
            canned("observation", ["npc_dev_torvald"], "size him up", "wits"),
            canned("physical", ["npc_dev_hedda"], "arm-wrestle", "might"),
            canned("research", ["npc_dev_sorrel"], "ask around", "lore"),
        ]:
            sim.run_turn(entry)
        blob = _known_blob(known(sim), sim)
        assert "threat_band" not in blob
        assert "aptitudes" not in blob
        assert '"hp"' not in blob and '"hp_max"' not in blob
        for entity in sim.world.entities.values():
            assert json.dumps(entity.true_sheet.aptitudes) not in blob
        for word in ("might", "finesse", "wits", "will", "presence", "lore"):
            assert f'"{word}":' not in blob  # no aptitude-keyed mappings at all


class TestHiddenEntityVisibility:
    """A `hidden`-tagged entity is absent from the perceived
    scene until a committed discovery fact makes it known. The parser
    roster and narrator context are built from this same scene, so the
    single choke point covers all three surfaces."""

    def _chandlery_sim(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        # Stand the PC in Ferrier's Chandlery, co-located with the seal.
        sim.state.characters["pc"]["location_id"] = "loc.harrowdown.chandlery"
        return sim

    def test_hidden_seal_absent_before_discovery(self):
        sim = self._chandlery_sim()
        scene = load_known_state(sim.state, sim.world, {}).scene("pc")
        ids = {e.entity_id for e in scene.entities}
        assert "item_harrowdown_marriage_seal" not in ids
        # Filtering is selective, never a blanket empty: Elam is still here.
        assert "npc_harrowdown_elam_ferrier" in ids

    def test_hidden_seal_present_after_discovery(self):
        sim = self._chandlery_sim()
        sim.pc["flags"]["discovered_item_harrowdown_marriage_seal"] = True
        scene = load_known_state(sim.state, sim.world, {}).scene("pc")
        assert "item_harrowdown_marriage_seal" in {e.entity_id for e in scene.entities}

    def test_only_the_seal_carries_the_hidden_tag(self):
        # Scan asserted: the marriage seal is the ONLY hidden entity in
        # harrowdown.yaml (Elam's secrets are true-sheet-only, never tagged).
        sim = Sim(seed=42, world_path=HARROWDOWN)
        hidden = [
            e.id for e in sim.world.entities.values() if "hidden" in e.true_sheet.tags
        ]
        assert hidden == ["item.harrowdown.marriage_seal"]


class TestOutcomePublicRedaction:
    """Exact hp and internal flags never reach the public view."""

    def _contract(self, deltas):
        return {
            "event_id": "7",
            "event_ulid": None,
            "tier_resolved": "routine",
            "risk_label_shown": "guarded",
            "outcome_tier": "hit_with_complication",
            "dice": {"rolls": [3, 4], "modifiers": [{"label": "might", "value": 1}], "total": 8},
            "state_deltas": deltas,
            "narration_constraints": [],
        }

    def test_dispatched_npc_hp_never_leaks_the_number(self):
        raw = self._contract([
            {"delta_type": "hp", "entity_id": "npc_dev_hedda", "amount": -1,
             "cause": "dispatched without ceremony"},
        ])
        public = outcome_public(raw)
        assert "-1" not in json.dumps(public)
        assert not any(d["delta_type"] == "hp" for d in public["state_deltas"])
        (wt,) = [d for d in public["state_deltas"] if d["delta_type"] == "wound_transition"]
        assert wt == {
            "delta_type": "wound_transition", "entity_id": "npc_dev_hedda", "effect": "wounded",
        }
        # With the post-resolution wound word, a kill reads as dispatched.
        dispatched = outcome_public(raw, wounds_after={"npc_dev_hedda": "dispatched"})
        (wt2,) = [d for d in dispatched["state_deltas"] if d["delta_type"] == "wound_transition"]
        assert wt2["effect"] == "dispatched"

    def test_player_near_death_shows_words_not_numbers(self):
        raw = self._contract([
            {"delta_type": "hp", "entity_id": "pc", "amount": -6,
             "cause": "broken against the drillmaster"},
        ])
        public = outcome_public(raw)
        assert "-6" not in json.dumps(public["state_deltas"])
        assert not any(d.get("cause") for d in public["state_deltas"])
        (wt,) = [d for d in public["state_deltas"] if d["delta_type"] == "wound_transition"]
        assert wt["effect"] == "wounded"

    def test_internal_flags_stripped_public_flags_kept(self):
        raw = self._contract([
            {"delta_type": "flag", "entity_id": "pc", "flag_key": "scar_turn_3", "value": "x"},
            {"delta_type": "flag", "entity_id": "pc",
             "flag_key": "owes_favor_npc_dev_hedda", "value": True},
            {"delta_type": "flag", "entity_id": "pc",
             "flag_key": "discovered_item_harrowdown_marriage_seal", "value": True},
            {"delta_type": "flag", "entity_id": "pc",
             "flag_key": "rapport_npc_dev_hedda", "value": True},
        ])
        keys = {
            d["flag_key"] for d in outcome_public(raw)["state_deltas"]
            if d["delta_type"] == "flag"
        }
        assert keys == {
            "scar_turn_3",
            "owes_favor_npc_dev_hedda",
            "discovered_item_harrowdown_marriage_seal",
        }

    def test_safe_deltas_and_band_data_pass_through(self):
        deltas = [
            {"delta_type": "coin", "entity_id": "pc", "amount": -5, "reason": "the inn"},
            {"delta_type": "deed", "actor_entity_id": "pc", "description": "x",
             "location_id": "loc_dev_tavern", "witness_ids": [], "notoriety": 1,
             "world_date": "Day 1"},
        ]
        raw = self._contract(deltas)
        public = outcome_public(raw)
        assert public["state_deltas"] == deltas  # KNOWN-safe deltas untouched
        assert public["dice"] == raw["dice"]  # band-derived, unchanged


class TestRefereeState:
    def test_referee_state_wraps_full_surface_and_derives_known(self, sim):
        referee = RefereeState(fold=sim.state, world=sim.world)
        # Full surface: true sheets reachable (this is the point — server-side).
        assert referee.fold.characters["pc"]["aptitudes"]
        assert referee.world.entities["npc.dev.torvald"].true_sheet.threat_band == 20
        view = referee.known_view(TAVERN_SLOTS)
        assert view.chronicle_facts("pc").wounds in WOUND_BANDS


class TestAskableTopics:
    """The parser's Topics list: what the people here could be asked about."""

    def _tavern(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        sim.state.characters["pc"]["location_id"] = "loc.harrowdown.tavern"
        sim.state.manifest["pc"]["location_id"] = "loc.harrowdown.tavern"
        return sim

    def test_scope_subjects_of_present_npcs_minus_the_roster(self):
        sim = self._tavern()
        known = load_known_state(sim.state, sim.world, {})
        topics = {t.topic_id: t.label for t in known.topics("pc")}
        present = {e.entity_id for e in known.scene("pc").entities}
        # Maren's road talk covers the Quarryman, the wight and the wolves.
        assert topics["creature_harrowdown_quarryman"] == "the Quarryman (at The Quarry Track)"
        assert "creature_harrowdown_barrow_wight" in topics
        # Jorun is in the room, so he is on the roster, not the Topics list.
        assert "npc_harrowdown_jorun_pike" in present
        assert not present & set(topics)

    def test_unlearned_names_stay_fogged(self):
        sim = self._tavern()
        known = load_known_state(sim.state, sim.world, {})
        labels = " ".join(t.label for t in known.topics("pc"))
        assert "Rold Tanner" not in labels
        tanner = sim.world.entities["npc.harrowdown.rold_tanner"]
        assert tanner.descriptor in labels

    def test_topics_never_reach_the_scene_surface(self):
        sim = self._tavern()
        known = load_known_state(sim.state, sim.world, {})
        blob = json.dumps(dataclasses.asdict(known.scene("pc")), sort_keys=True)
        assert "creature_harrowdown_quarryman" not in blob
