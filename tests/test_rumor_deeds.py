"""Deed-rumor propagation from the projected deed list."""

from __future__ import annotations

from everquill_engine.resolver import resolve_intent
from everquill_engine.rumor import (
    INTRA_HOP_MINUTES,
    RUMOR_LIFESPAN_PER_NOTORIETY,
    reached_deeds,
)
from everquill_engine.world import (
    Connection,
    Location,
    TrueSheet,
    WorldContent,
    WorldEntity,
)


def _world() -> WorldContent:
    return WorldContent(
        source="unit",
        locations={
            "loc.test.origin": Location(
                "loc.test.origin",
                "Origin",
                "road",
                "test",
                (
                    Connection("loc.test.adjacent", 0),
                    Connection("loc.test.direct_far", 1),
                ),
            ),
            "loc.test.adjacent": Location(
                "loc.test.adjacent",
                "Adjacent",
                "road",
                "test",
                (Connection("loc.test.far", 0),),
            ),
            "loc.test.far": Location("loc.test.far", "Far", "road", "test", ()),
            "loc.test.direct_far": Location(
                "loc.test.direct_far", "Direct Far", "road", "test", ()
            ),
        },
        entities={
            "npc.test.target": WorldEntity(
                "npc.test.target",
                "Target",
                "npc",
                "loc.test.adjacent",
                TrueSheet(
                    {
                        "might": 1,
                        "finesse": 1,
                        "wits": 1,
                        "will": 1,
                        "presence": 1,
                        "lore": 1,
                    },
                    1,
                ),
                common_knowledge=("Target keeps to the road.",),
            )
        },
    )


def _deed(
    *,
    world_time=100,
    notoriety=1,
    location="loc.test.origin",
    description="pc did a thing",
):
    return {
        "deed_order": 1,
        "actor_entity_id": "pc",
        "location_id": location,
        "notoriety": notoriety,
        "world_time": world_time,
        "description": description,
        "source_event_id": 9,
    }


def _actor(location="loc.test.adjacent"):
    return {
        "entity_id": "pc",
        "name": "the Quill-touched",
        "origin": "test",
        "aptitudes": {
            "might": 10,
            "finesse": 10,
            "wits": 10,
            "will": 10,
            "presence": 10,
            "lore": 10,
        },
        "hp": 9,
        "hp_max": 9,
        "coin": 0,
        "location_id": location,
        "inventory": {},
        "flags": {},
        "titles": [],
        "last_event_id": 0,
    }


def _manifest(location="loc.test.adjacent"):
    return {
        "pc": {
            "entity_id": "pc",
            "location_id": location,
            "kind": "character",
            "name": "the Quill-touched",
            "region": "test",
            "common_knowledge": [],
            "portrait": None,
            "last_event_id": 0,
        },
        "npc.test.target": {
            "entity_id": "npc.test.target",
            "location_id": "loc.test.adjacent",
            "kind": "npc",
            "name": "Target",
            "region": "test",
            "common_knowledge": ["Target keeps to the road."],
            "portrait": None,
            "last_event_id": 0,
        },
    }


def _intent(action_type, targets=(), approach="look around", stat_hint=None):
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


def _resolve(action_type="observation", *, actor=None, deeds=(), targets=(), turn=1):
    return resolve_intent(
        intent=_intent(
            action_type,
            targets,
            stat_hint="lore" if action_type == "research" else None,
        ),
        actor=actor or _actor(),
        world=_world(),
        manifest=_manifest((actor or _actor())["location_id"]),
        world_time=175 if action_type == "observation" else 120,
        rng_counters={},
        seed=42,
        turn=turn,
        deeds=tuple(deeds),
    )


def _intel_deltas(resolution):
    return [
        delta
        for delta in resolution.events[resolution.outcome_event_index].payload["state_deltas"]
        if delta["delta_type"] == "intel"
    ]


class TestDeedRumorPropagation:
    def test_same_location_never_surfaces_as_gossip(self):
        assert reached_deeds(
            [_deed()],
            world=_world(),
            location_id="loc.test.origin",
            world_time=100 + INTRA_HOP_MINUTES,
        ) == ()

    def test_adjacent_location_waits_for_arrival_delay(self):
        world = _world()
        before = reached_deeds(
            [_deed()],
            world=world,
            location_id="loc.test.adjacent",
            world_time=100 + INTRA_HOP_MINUTES - 1,
        )
        after = reached_deeds(
            [_deed()],
            world=world,
            location_id="loc.test.adjacent",
            world_time=100 + INTRA_HOP_MINUTES,
        )

        assert before == ()
        assert len(after) == 1
        assert after[0]["hop_count"] == 1
        assert after[0]["distance_minutes"] == INTRA_HOP_MINUTES

    def test_far_location_surfaces_later_than_adjacent(self):
        world = _world()
        assert reached_deeds(
            [_deed()],
            world=world,
            location_id="loc.test.far",
            world_time=100 + INTRA_HOP_MINUTES,
        ) == ()

        reached = reached_deeds(
            [_deed()],
            world=world,
            location_id="loc.test.far",
            world_time=100 + (INTRA_HOP_MINUTES * 2),
        )

        assert len(reached) == 1
        assert reached[0]["hop_count"] == 2
        assert reached[0]["distance_minutes"] == INTRA_HOP_MINUTES * 2

    def test_carriage_day_edge_costs_more_than_intra_hop(self):
        reached = reached_deeds(
            [_deed(notoriety=2)],
            world=_world(),
            location_id="loc.test.direct_far",
            world_time=100 + 719,
        )
        assert reached == ()

        reached = reached_deeds(
            [_deed(notoriety=2)],
            world=_world(),
            location_id="loc.test.direct_far",
            world_time=100 + 720,
        )
        assert len(reached) == 1
        assert reached[0]["distance_minutes"] == 1440

    def test_stale_deed_fades_after_lifespan(self):
        assert reached_deeds(
            [_deed(notoriety=1)],
            world=_world(),
            location_id="loc.test.adjacent",
            world_time=100 + RUMOR_LIFESPAN_PER_NOTORIETY + 1,
        ) == ()


class TestDeedRumorSurface:
    def test_ambient_look_surfaces_reached_deed_as_rumor_claim_with_provenance(self):
        deed = _deed(
            world_time=0,
            notoriety=4,
            description="the Quill-touched broke the quarry thing",
            location="loc.test.origin",
        )
        res = _resolve("observation", deeds=[deed])

        (delta,) = _intel_deltas(res)
        claim = delta["claim"]
        assert claim["subject_entity_id"] == "world"
        assert claim["method"] == "rumor"
        assert claim["scope"] == "local_mistaken_for_universal"
        assert claim["claim_text"] == "the Quill-touched broke the quarry thing"
        assert delta["provenance_root_event_id"] == 9
        assert delta["hop_count"] == 1

        claim_event = res.events[res.outcome_event_index + 1]
        assert claim_event.event_type == "claim_written"
        assert claim_event.payload["provenance_root_event_id"] == 9
        assert claim_event.payload["hop_count"] == 1

    def test_same_actor_world_time_turn_replays_same_deed_rumor(self):
        deed = _deed(
            world_time=0,
            notoriety=4,
            description="the same road story",
            location="loc.test.origin",
        )
        first = _resolve("observation", deeds=[deed], turn=3)
        replay = _resolve("observation", deeds=[deed], turn=3)

        assert _intel_deltas(first)[0]["claim"] == _intel_deltas(replay)[0]["claim"]

    def test_own_current_location_deed_does_not_surface_as_gossip(self):
        res = _resolve(
            "observation",
            actor=_actor("loc.test.origin"),
            deeds=[_deed(world_time=0, notoriety=9, location="loc.test.origin")],
        )

        assert _intel_deltas(res) == []

    def test_subjectless_research_uses_reached_deed_pool(self):
        deed = _deed(
            world_time=0,
            notoriety=4,
            description="the quarry road story reached the tavern",
            location="loc.test.origin",
        )
        res = _resolve("research", deeds=[deed])

        (delta,) = _intel_deltas(res)
        assert delta["claim"]["method"] == "rumor"
        assert delta["claim"]["claim_text"] == "the quarry road story reached the tavern"

    def test_non_ambient_actions_do_not_inject_deed_rumors(self):
        deed = _deed(
            world_time=0,
            notoriety=9,
            description="this should not leak into non-ambient actions",
            location="loc.test.origin",
        )

        targeted = _resolve("observation", deeds=[deed], targets=["npc_test_target"])
        movement = _resolve("movement", deeds=[deed], targets=["loc_test_origin"])
        dialogue = _resolve("dialogue", deeds=[deed], targets=["npc_test_target"])
        physical = _resolve("physical", deeds=[deed], targets=["npc_test_target"])

        for resolution in (targeted, movement, dialogue, physical):
            assert all(
                delta["claim"]["claim_text"] != "this should not leak into non-ambient actions"
                for delta in _intel_deltas(resolution)
            )
