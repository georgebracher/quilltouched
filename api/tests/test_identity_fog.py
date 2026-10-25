"""Identity fog reaches API scene, parser roster, and narrator context."""

from __future__ import annotations

import json

from api import context
from api import main as api_main
from everquill_engine.views import load_known_state
from tests.harness import REPO_ROOT, Sim

FOG_WORLD = REPO_ROOT / "tests" / "fixtures" / "identity-fog-world.yaml"


def test_scene_api_roster_and_narrator_context_use_fogged_label():
    sim = Sim(seed=42, world_path=FOG_WORLD)
    known = load_known_state(sim.state, sim.world, {})

    response = api_main._scene_response(known, "fog")
    greeter = next(entity for entity in response["entities"] if entity["id"] == "npc_fog_greeter")
    assert greeter["name"] == "a wary man watching the door"

    scene_dict = context._scene_dict(known)
    label = next(
        entity["label_known"]
        for entity in scene_dict["entities"]
        if entity["entity_id"] == "npc_fog_greeter"
    )
    assert label == "a wary man watching the door"

    roster = context.roster_text(known)
    assert "- npc_fog_greeter: a wary man watching the door (npc)" in roster

    combined = (
        json.dumps(response, sort_keys=True)
        + json.dumps(scene_dict, sort_keys=True)
        + roster
    )
    assert "Arel Voss" not in combined
