"""Typed intent model: closed validation, schema equivalence.

The typed model in ``everquill_engine/intent.py`` must accept EXACTLY
what docs/contracts/intent.schema.json v1.1 accepts. The battery below
runs every case through BOTH validators and asserts they agree, so the
hand-rolled model cannot drift from the contract file silently.
"""

from __future__ import annotations

import jsonschema
import pytest

from everquill_engine.intent import (
    ACTION_TYPES,
    ADDRESSEES,
    MOVEMENT_SCOPES,
    PLAUSIBILITY_HINTS,
    SPEECH_ACTS,
    TRANSACTION_KINDS,
    IntentValidationError,
    parse_intent,
)
from everquill_engine.world import APTITUDES
from tests.harness import intent_schema_v11, load_script

SCHEMA = intent_schema_v11()
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def valid_intent(**overrides):
    intent = {
        "action_type": "physical",
        "target_entity_ids": ["npc_dev_hedda"],
        "approach": "arm-wrestle the barkeep",
        "stat_hint": "might",
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
    intent.update(overrides)
    return intent


#: (label, intent) — every case is judged by BOTH validators.
CASES = [
    ("baseline valid", valid_intent()),
    ("valid with dialogue", valid_intent(
        action_type="dialogue",
        dialogue={"addressee_id": "npc_dev_hedda", "quoted_speech": "Evening."},
    )),
    ("valid dialogue to the room", valid_intent(
        action_type="dialogue", dialogue={"addressee_id": None, "quoted_speech": None},
    )),
    ("valid explicit duration", valid_intent(
        action_type="train",
        duration_hint={"mode": "explicit", "text": "for three hours",
                       "until": None, "amount": 3, "unit": "hour"},
    )),
    ("valid until-condition duration", valid_intent(
        action_type="train",
        duration_hint={"mode": "until_condition", "text": "until nightfall",
                       "until": "dusk", "amount": None, "unit": None},
    )),
    ("valid world-event condition the engine will refuse", valid_intent(
        action_type="rest",
        duration_hint={"mode": "until_condition", "text": "until the caravan leaves",
                       "until": None, "amount": None, "unit": None},
    )),
    ("duration missing the closed fields", valid_intent(
        action_type="train", duration_hint={"mode": "explicit", "text": "for three hours"},
    )),
    ("duration bad until", valid_intent(duration_hint={
        "mode": "until_condition", "text": "till teatime", "until": "teatime",
        "amount": None, "unit": None,
    })),
    ("duration bad unit", valid_intent(duration_hint={
        "mode": "explicit", "text": "a fortnight", "until": None, "amount": 2, "unit": "week",
    })),
    ("duration amount zero", valid_intent(duration_hint={
        "mode": "explicit", "text": "no time", "until": None, "amount": 0, "unit": "hour",
    })),
    ("duration amount not an integer", valid_intent(duration_hint={
        "mode": "explicit", "text": "an hour and a half", "until": None, "amount": 1.5,
        "unit": "hour",
    })),
    ("valid null stat_hint + empty targets", valid_intent(
        target_entity_ids=[], stat_hint=None,
    )),
    ("unknown top-level key", valid_intent(sneaky="yes")),
    ("missing required key", {
        k: v for k, v in valid_intent().items() if k != "duration_hint"
    }),
    ("unknown action_type", valid_intent(action_type="teleport")),
    ("duplicate targets", valid_intent(
        target_entity_ids=["npc_dev_hedda", "npc_dev_hedda"],
    )),
    ("bad target pattern", valid_intent(target_entity_ids=["Npc.Dev.Hedda"])),
    ("targets not a list", valid_intent(target_entity_ids="npc_dev_hedda")),
    ("empty approach", valid_intent(approach="")),
    ("approach wrong type", valid_intent(approach=7)),
    ("bad stat_hint", valid_intent(stat_hint="charisma")),
    ("bad plausibility_hint", valid_intent(plausibility_hint="unlikely")),
    ("dialogue extra key", valid_intent(dialogue={
        "addressee_id": None, "quoted_speech": None, "tone": "wry",
    })),
    ("dialogue missing key", valid_intent(dialogue={"addressee_id": None})),
    ("dialogue empty speech", valid_intent(dialogue={
        "addressee_id": None, "quoted_speech": "",
    })),
    ("dialogue bad addressee pattern", valid_intent(dialogue={
        "addressee_id": "Hedda!", "quoted_speech": None,
    })),
    ("duration bad mode", valid_intent(duration_hint={
        "mode": "roughly", "text": "an hour", "until": None, "amount": 1, "unit": "hour",
    })),
    ("duration empty text", valid_intent(duration_hint={
        "mode": "explicit", "text": "", "until": None, "amount": 1, "unit": "hour",
    })),
    ("duration extra key", valid_intent(duration_hint={
        "mode": "explicit", "text": "an hour", "until": None, "amount": 1, "unit": "hour",
        "minutes": 60,
    })),
    ("duration not an object", valid_intent(duration_hint="an hour")),
    ("ambiguity flags duplicate", valid_intent(
        ambiguity_flags=["compound_action", "compound_action"],
    )),
    ("ambiguity flags bad pattern", valid_intent(ambiguity_flags=["Compound-Action"])),
    ("ambiguity flags not a list", valid_intent(ambiguity_flags="compound_action")),
    ("boolean where string expected", valid_intent(approach=True)),
    # v1.3 closed decision fields
    ("valid spoken question with a topic", valid_intent(
        action_type="dialogue", addressee="person", speech_act="question",
        topic_ids=["creature_dev_wyvern"],
    )),
    ("valid room proclamation", valid_intent(
        action_type="social", addressee="room", speech_act="statement",
    )),
    ("valid purchase", valid_intent(
        action_type="social", transaction={"kind": "buy", "price_key": "ale_copper", "count": 2},
    )),
    ("valid coin hand-over", valid_intent(
        action_type="social", transaction={"kind": "give_coin", "price_key": None, "count": 20},
    )),
    ("valid invoked law", valid_intent(invoked_law_ids=["law_hearth_oath"])),
    ("valid in-room move", valid_intent(action_type="movement", movement_scope="here")),
    ("bad addressee", valid_intent(addressee="crowd")),
    ("bad speech_act", valid_intent(speech_act="rhetorical")),
    ("bad movement_scope", valid_intent(movement_scope="elsewhere")),
    ("topic_ids not a list", valid_intent(topic_ids="creature_dev_wyvern")),
    ("topic_ids duplicate", valid_intent(topic_ids=["a_b", "a_b"])),
    ("topic_ids bad pattern", valid_intent(topic_ids=["The Wyvern"])),
    ("topic_ids over the cap", valid_intent(topic_ids=["a", "b", "c", "d"])),
    ("invoked_law_ids over the cap", valid_intent(invoked_law_ids=["a", "b", "c"])),
    ("invoked_law_ids bad pattern", valid_intent(invoked_law_ids=["law.hearth_oath"])),
    ("transaction bad kind", valid_intent(
        transaction={"kind": "steal", "price_key": None, "count": 1},
    )),
    ("transaction missing key", valid_intent(transaction={"kind": "buy", "count": 1})),
    ("transaction extra key", valid_intent(
        transaction={"kind": "buy", "price_key": "ale_copper", "count": 1, "haggle": True},
    )),
    ("transaction count zero", valid_intent(
        transaction={"kind": "give_coin", "price_key": None, "count": 0},
    )),
    ("transaction count over the cap", valid_intent(
        transaction={"kind": "give_coin", "price_key": None, "count": 21},
    )),
    ("transaction count not an integer", valid_intent(
        transaction={"kind": "give_coin", "price_key": None, "count": 1.5},
    )),
    ("transaction count boolean", valid_intent(
        transaction={"kind": "give_coin", "price_key": None, "count": True},
    )),
    ("transaction bad price_key", valid_intent(
        transaction={"kind": "buy", "price_key": "Ale Pint", "count": 1},
    )),
    ("transaction not an object", valid_intent(transaction="buy ale")),
]


class TestSchemaEquivalence:
    @pytest.mark.parametrize("label,intent", CASES, ids=[c[0] for c in CASES])
    def test_typed_model_agrees_with_json_schema(self, label, intent):
        schema_ok = VALIDATOR.is_valid(intent)
        try:
            parse_intent(intent)
            typed_ok = True
        except IntentValidationError:
            typed_ok = False
        assert typed_ok == schema_ok, (
            f"{label}: typed model {'accepted' if typed_ok else 'rejected'} what the "
            f"JSON schema {'accepts' if schema_ok else 'rejects'}"
        )

    def test_script_and_menu_intents_all_parse(self):
        from everquill_engine.cli import _build_menu
        from tests.harness import Sim

        for entry in load_script():
            parse_intent(entry["intent"])
        sim = Sim(seed=42)
        for _label, intent in _build_menu(sim.world, "loc.dev.tavern"):
            parse_intent(intent)


class TestVocabularyLockstep:
    """The typed model's enums ARE the schema's enums — drift is a failure."""

    def test_action_types_match_schema(self):
        assert set(SCHEMA["properties"]["action_type"]["enum"]) == ACTION_TYPES

    def test_stat_hint_vocabulary_matches_schema(self):
        schema_enum = set(SCHEMA["properties"]["stat_hint"]["enum"])
        assert schema_enum == set(APTITUDES) | {None}

    def test_plausibility_hints_match_schema(self):
        assert set(SCHEMA["properties"]["plausibility_hint"]["enum"]) == PLAUSIBILITY_HINTS

    def test_closed_decision_vocabularies_match_schema(self):
        props = SCHEMA["properties"]
        assert set(props["addressee"]["enum"]) == ADDRESSEES | {None}
        assert set(props["speech_act"]["enum"]) == SPEECH_ACTS | {None}
        assert set(props["movement_scope"]["enum"]) == MOVEMENT_SCOPES | {None}
        kinds = SCHEMA["$defs"]["transaction"]["properties"]["kind"]["enum"]
        assert set(kinds) == TRANSACTION_KINDS


class TestTypedShape:
    def test_parse_returns_frozen_tuples(self):
        typed = parse_intent(valid_intent(ambiguity_flags=["compound_action"]))
        assert typed.target_entity_ids == ("npc_dev_hedda",)
        assert typed.ambiguity_flags == ("compound_action",)
        with pytest.raises(AttributeError):
            typed.approach = "changed"

    def test_error_messages_name_the_violation(self):
        with pytest.raises(IntentValidationError, match="unknown keys: sneaky"):
            parse_intent(valid_intent(sneaky=1))
        with pytest.raises(IntentValidationError, match="duplicate target"):
            parse_intent(valid_intent(target_entity_ids=["a_b", "a_b"]))
