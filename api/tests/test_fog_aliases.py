"""Identity fog on the model-facing side: a contract id spells the true name
(npc_harrowdown_jorun_pike), so the parser and narrator see unlearned people by
an opaque alias, and the gate rejects a true name the player has not learned
(audit 2026-10-24, claude #2). Pure: no database."""

from __future__ import annotations

from api import context as context_mod
from everquill_engine.views import load_known_state
from llm import narration_gate
from tests.harness import REPO_ROOT, Sim

HARROWDOWN = REPO_ROOT / "content" / "world" / "harrowdown.yaml"
JORUN = "npc_harrowdown_jorun_pike"
MAREN = "npc_harrowdown_maren_ostler"


def _tavern(**flags):
    sim = Sim(seed=42, world_path=HARROWDOWN)
    sim.state.characters["pc"]["location_id"] = "loc.harrowdown.tavern"
    sim.state.manifest["pc"]["location_id"] = "loc.harrowdown.tavern"
    sim.state.characters["pc"]["flags"].update(flags)
    return sim, load_known_state(sim.state, sim.world, {})


def test_unlearned_people_reach_the_parser_by_alias_only():
    sim, known = _tavern()
    aliases = context_mod.fogged_aliases(known, sim.world)
    roster = context_mod.roster_text(known, sim.world, aliases)
    lists = context_mod.parse_lists(known, sim.world, aliases)
    text = (roster + "\n" + "\n".join(lists.values())).lower()
    assert aliases[JORUN].startswith("person_")
    for true_name in ("jorun", "pike", "maren", "ostler", "rold", "tanner"):
        assert true_name not in text, true_name
    assert f"- {aliases[JORUN]}: a wary man" in roster


def test_a_learned_name_keeps_its_real_id_and_nobody_else_is_renumbered():
    sim, before = _tavern()
    sim, known = _tavern(knows_name_npc_harrowdown_jorun_pike=True)
    aliases = context_mod.fogged_aliases(known, sim.world)
    assert JORUN not in aliases
    assert aliases[MAREN] == context_mod.fogged_aliases(before, sim.world)[MAREN]
    assert f"- {JORUN}: Jorun Pike" in context_mod.roster_text(known, sim.world, aliases)


def test_the_parse_maps_aliases_back():
    sim, known = _tavern()
    aliases = context_mod.fogged_aliases(known, sim.world)
    alias = aliases[JORUN]
    parsed = {
        "target_entity_ids": [alias],
        "topic_ids": [alias],
        "dialogue": {"addressee_id": alias, "quoted_speech": None},
    }
    back = context_mod.unalias_intent(parsed, aliases)
    assert back["target_entity_ids"] == [JORUN]
    assert back["topic_ids"] == [JORUN]
    assert back["dialogue"]["addressee_id"] == JORUN


def test_the_gate_rejects_a_true_name_the_player_has_not_learned():
    sim, known = _tavern()
    aliases = context_mod.fogged_aliases(known, sim.world)
    envelope = {"scene": {"entities": [{"entity_id": JORUN, "label_known": "a wary man"}]}}
    outcome = {"tier_resolved": "trivial", "outcome_tier": None, "state_deltas": []}
    prose = "The wary man shifts his ruined arm, and Jorun says nothing."
    leaked = narration_gate.check_narration(prose, outcome=outcome, envelope=envelope)
    fogged = narration_gate.check_narration(
        prose, outcome=outcome, envelope=context_mod.alias_payload(envelope, aliases)
    )
    assert not any("G4" in v for v in leaked)  # the old hole: the id taught the gate the name
    assert any("G4" in v and "Jorun" in v for v in fogged)


TRUE_NAMES = ("Maren", "Ostler", "Jorun", "Pike", "Rold", "Tanner", "Odile", "Toller", "Whin",
              "Elam", "Ferrier", "Fenn", "Bracey")


def test_the_scene_labels_every_id_without_an_unlearned_name():
    """The client renders every id (marks, workings, Codex) through these
    labels, so they must hold a descriptor for anyone not yet named, here and
    off-scene (audit 2026-10-24, claude-001)."""
    import json

    from api.presenters import _scene_response, _subject_labels

    sim, known = _tavern()
    response = _scene_response(known, "w")
    labels = response["labels"]
    assert labels[JORUN] == "the wary man"
    assert labels["npc_harrowdown_rold_tanner"] == "the hard-faced man working the row"  # off-scene
    assert labels["pc"] == "you"
    assert _subject_labels(known)["npc_harrowdown_rold_tanner"] == labels[
        "npc_harrowdown_rold_tanner"
    ]
    # People only: a shop sign ("Ferrier's Chandlery") or a headstone may carry
    # a surname; that is the world being legible, not the fog failing.
    people = {k: v for k, v in labels.items() if k.startswith("npc_")}
    blob = json.dumps([people, response["entities"]])
    assert len(people) == 7
    assert not [n for n in TRUE_NAMES if n in blob]


def test_a_learned_name_is_served_as_the_name():
    from api.presenters import _scene_response

    sim, known = _tavern(knows_name_npc_harrowdown_jorun_pike=True)
    assert _scene_response(known, "w")["labels"][JORUN] == "Jorun Pike"


def test_deeds_name_the_target_as_the_actor_knows_them():
    """The trivial-victory deed used the authored name (audit codex-008)."""
    sim, _known = _tavern()
    descriptions = []
    for _ in range(3):
        _res, row = sim.run_turn({
            "action_type": "physical", "target_entity_ids": [MAREN],
            "approach": "a shove across the bar", "stat_hint": "might", "dialogue": None,
            "plausibility_hint": "plausible", "duration_hint": None, "ambiguity_flags": [],
            "addressee": None, "speech_act": None, "topic_ids": [], "transaction": None,
            "invoked_law_ids": [], "movement_scope": None,
        })
        descriptions += [
            d["description"] for d in row["payload"]["state_deltas"] if d["delta_type"] == "deed"
        ]
    assert not [n for n in TRUE_NAMES if any(n in text for text in descriptions)]


def test_the_self_payload_carries_the_word_not_the_value():
    from api.presenters import _standing_json
    from everquill_engine.views import ReputationStanding

    town = _standing_json(ReputationStanding("standing", "loc_x", "Harrowdown", 4, "esteemed here"))
    assert "value" not in town and (town["read"], town["read_max"]) == (2, 2)
    person = _standing_json(ReputationStanding("disposition", MAREN, "the barkeep", -2, "cold"))
    assert (person["read"], person["read_max"]) == (-2, 3)


def test_the_fog_eval_context_is_what_production_sends():
    """evals/fog-utterances.jsonl runs against parser_eval's FOG_ROSTER and
    FOG_LISTS; they must stay byte-equal to the live tavern roster (audit F4:
    the eval measured a roster production no longer sent)."""
    from llm import parser_eval

    sim, known = _tavern()
    aliases = context_mod.fogged_aliases(known, sim.world)
    assert parser_eval.FOG_ROSTER == context_mod.roster_text(known, sim.world, aliases)
    assert parser_eval.FOG_LISTS == context_mod.parse_lists(known, sim.world, aliases)


def test_the_gate_catches_an_alias_echo_and_a_sentence_initial_name():
    """claude-010: G4 skipped sentence starts and could not see ids."""
    sim, known = _tavern()
    aliases = context_mod.fogged_aliases(known, sim.world)
    unlearned = context_mod.unlearned_names(sim.world, aliases)
    assert "Jorun" in unlearned and "Pike" in unlearned
    assert "Ferrier" not in unlearned  # on the chandlery's sign
    outcome = {"tier_resolved": "trivial", "outcome_tier": None, "state_deltas": []}
    for prose, expected in (
        ("Jorun says nothing. The room is quiet.", "has not learned"),
        ("The room is quiet, and person_3 says nothing.", "internal alias"),
    ):
        violations = narration_gate.check_narration(
            prose, outcome=outcome, envelope={}, unlearned_names=unlearned
        )
        assert any(expected in v for v in violations), (prose, violations)
