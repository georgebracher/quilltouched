"""Identity fog: NPC labels stay descriptive until the actor learns a name."""

from __future__ import annotations

import dataclasses
import json

from everquill_engine.folds import FoldState, fold_event
from everquill_engine.resolver import knows_name_flag
from everquill_engine.views import load_known_state
from tests.harness import REPO_ROOT, Sim

FOG_WORLD = REPO_ROOT / "tests" / "fixtures" / "identity-fog-world.yaml"


def canned(
    action_type, targets=(), approach="do the thing", stat_hint=None, dialogue=None, **fields
):
    intent = {
        "action_type": action_type,
        "target_entity_ids": list(targets),
        "approach": approach,
        "stat_hint": stat_hint,
        "dialogue": dialogue,
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
    intent.update(fields)
    return intent


def dialogue(target: str, approach: str, speech_act: str):
    return canned(
        "dialogue",
        [target],
        approach,
        dialogue={"addressee_id": target, "quoted_speech": None},
        addressee="person",
        speech_act=speech_act,
    )


def scene(sim):
    return load_known_state(sim.state, sim.world, {}).scene("pc")


def by_id(sim):
    return {entity.entity_id: entity for entity in scene(sim).entities}


def test_unknown_npc_scene_uses_descriptor_and_omits_true_name():
    sim = Sim(seed=42, world_path=FOG_WORLD)

    view = scene(sim)
    entities = by_id(sim)
    blob = json.dumps(dataclasses.asdict(view), sort_keys=True)

    assert entities["npc_fog_greeter"].name == "a wary man watching the door"
    assert entities["npc_fog_greeter"].descriptor == "a wary man watching the door"
    assert "Arel Voss" not in blob
    assert "Jorun Pike" not in blob


def test_creatures_and_props_are_not_fogged():
    sim = Sim(seed=42, world_path=FOG_WORLD)

    entities = by_id(sim)

    assert entities["creature_fog_slime"].name == "a ditch slime"
    assert entities["prop_fog_board"].name == "the guild board"


def test_name_exchange_success_sets_flag_and_replay_shows_true_name():
    sim = Sim(seed=42, world_path=FOG_WORLD)

    _res, row = sim.run_turn(
        dialogue("npc_fog_greeter", "introduce myself and ask your name", "introduction")
    )

    flag_key = knows_name_flag("npc.fog.greeter")
    assert any(
        delta == {
            "delta_type": "flag",
            "entity_id": "pc",
            "flag_key": flag_key,
            "value": True,
        }
        for delta in row["payload"]["state_deltas"]
    )
    assert sim.pc["flags"][flag_key] is True
    assert by_id(sim)["npc_fog_greeter"].name == "Arel Voss"

    replayed = FoldState()
    for event in sim.rows:
        fold_event(replayed, event)
    replay_scene = load_known_state(replayed, sim.world, {}).scene("pc")
    replay_entities = {entity.entity_id: entity for entity in replay_scene.entities}
    assert replayed.characters["pc"]["flags"][flag_key] is True
    assert replay_entities["npc_fog_greeter"].name == "Arel Voss"


def test_guarded_npc_requires_strong_hit_to_reveal_name():
    hit = Sim(seed=5, world_path=FOG_WORLD)
    _res, hit_row = hit.run_turn(
        canned(
            "social",
            ["npc_fog_keeper"],
            "introduce myself and ask your name",
            "presence",
            addressee="person",
            speech_act="introduction",
        )
    )
    flag_key = knows_name_flag("npc.fog.keeper")
    assert hit_row["payload"]["outcome_tier"] == "hit_with_complication"
    assert flag_key not in hit.pc["flags"]
    assert by_id(hit)["npc_fog_keeper"].name == "a hard-eyed guard by the stairs"

    strong = Sim(seed=12, world_path=FOG_WORLD)
    _res, strong_row = strong.run_turn(
        canned(
            "social",
            ["npc_fog_keeper"],
            "introduce myself and ask your name",
            "presence",
            addressee="person",
            speech_act="introduction",
        )
    )
    assert strong_row["payload"]["outcome_tier"] == "strong_hit"
    assert strong.pc["flags"][flag_key] is True
    assert by_id(strong)["npc_fog_keeper"].name == "Jorun Pike"


def test_non_name_exchange_and_ambiguous_exchange_do_not_reveal_names():
    ordinary = Sim(seed=12, world_path=FOG_WORLD)
    ordinary.run_turn(
        canned(
            "social",
            ["npc_fog_greeter"],
            "share a drink and talk weather",
            "presence",
            addressee="person",
            speech_act="statement",
        )
    )
    assert knows_name_flag("npc.fog.greeter") not in ordinary.pc["flags"]

    ambiguous = Sim(seed=12, world_path=FOG_WORLD)
    ambiguous.run_turn(
        canned(
            "social",
            ["npc_fog_greeter", "npc_fog_keeper"],
            "introduce myself and ask your name",
            "presence",
            addressee="person",
            speech_act="introduction",
        )
    )
    assert knows_name_flag("npc.fog.greeter") not in ambiguous.pc["flags"]
    assert knows_name_flag("npc.fog.keeper") not in ambiguous.pc["flags"]


def test_earned_common_fact_and_threat_read_use_descriptor_until_name_known():
    fact_sim = Sim(seed=42, world_path=FOG_WORLD)
    _res, fact_row = fact_sim.run_turn(
        dialogue("npc_fog_greeter", "ask what you know about this place", "question")
    )
    fact_claims = [
        delta["claim"]
        for delta in fact_row["payload"]["state_deltas"]
        if delta["delta_type"] == "intel"
    ]
    assert fact_claims
    fact_blob = json.dumps(fact_claims, sort_keys=True)
    assert "The wary man watching the door keeps a room upstairs" in fact_blob
    assert "Arel Voss" not in fact_blob

    threat_sim = Sim(seed=1, world_path=FOG_WORLD)
    _res, threat_row = threat_sim.run_turn(
        canned("observation", ["npc_fog_keeper"], "size up the guard", "wits")
    )
    threat_claims = [
        delta["claim"]
        for delta in threat_row["payload"]["state_deltas"]
        if delta["delta_type"] == "intel"
    ]
    assert threat_claims
    threat_blob = json.dumps(threat_claims, sort_keys=True)
    assert "the hard-eyed guard by the stairs" in threat_blob
    assert "Jorun Pike" not in threat_blob
