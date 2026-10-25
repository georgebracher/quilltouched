"""Narration runtime gate — pure unit tests, no DB, no LLM.

Fixture narrations cover: admissible prose, System-markup violation,
success-framing on a committed miss, invented entities, mechanics
vocabulary, and the length cap; plus the deterministic fallback prose,
which must itself pass the gate for every delta shape it can emit.
"""

from __future__ import annotations

from llm import narration_gate

ENVELOPE = {
    "scene_manifest": {
        "location_id": "loc_harrowdown_tavern",
        "label_known": "The Wet Ledger",
        "entities": [
            {"entity_id": "npc_harrowdown_maren_ostler", "label_known": "Maren Ostler"},
            {"entity_id": "npc_harrowdown_elam_ferrier", "label_known": "Elam Ferrier"},
        ],
    },
    "known_sheet_slices": [{"entity_id": "pc", "facts": [{"field": "name", "value": "Bram"}]}],
    "salient_claims": [],
    "active_clocks": [],
    "canon_excerpts": [],
}

ACTION = {
    "action_type": "physical",
    "approach": "a straight lunge across the taproom",
    "target_entity_ids": ["npc_harrowdown_elam_ferrier"],
    "dialogue": None,
}

MISS_OUTCOME = {
    "event_id": "41",
    "tier_resolved": "hopeless",
    "risk_label_shown": "suicidal",
    "outcome_tier": "miss",
    "dice": {"rolls": [2, 3], "modifiers": [], "total": 5},
    "state_deltas": [
        {"delta_type": "hp", "entity_id": "pc", "amount": -2, "cause": "counterblow"}
    ],
    "narration_constraints": ["no_success_framing"],
}

STRONG_HIT_OUTCOME = {
    "event_id": "42",
    "tier_resolved": "routine",
    "risk_label_shown": "guarded",
    "outcome_tier": "strong_hit",
    "dice": {"rolls": [6, 5], "modifiers": [], "total": 11},
    "state_deltas": [],
    "narration_constraints": [],
}


def check(text, outcome=MISS_OUTCOME):
    return narration_gate.check_narration(
        text, outcome=outcome, envelope=ENVELOPE, action=ACTION
    )


class TestGateChecks:
    def test_admissible_narration_passes(self):
        text = (
            "Elam Ferrier steps aside and your lunge finds only the taproom air. "
            "Maren Ostler does not look up from the ledger. Your ribs catch the "
            "edge of the counter on the way past, and it hurts."
        )
        assert check(text) == ()

    def test_markup_violation(self):
        text = "You lunge. [The counter takes the rest.] <<Assessment stands.>>"
        violations = check(text)
        assert any(v.startswith("G1") for v in violations)

    def test_mechanics_vocabulary_violation(self):
        text = "You lunge, but the dice were never with you and the roll comes up 5."
        violations = check(text)
        assert any(v.startswith("G2") for v in violations)

    def test_success_framing_on_a_miss(self):
        text = "A flawless strike — you succeed where lesser hands would falter."
        violations = check(text)
        assert any(v.startswith("G3") for v in violations)

    def test_negated_success_words_are_allowed_on_a_miss(self):
        text = "You do not succeed. The floorboards take your dignity quietly."
        assert not any(v.startswith("G3") for v in check(text))

    def test_failure_framing_on_a_strong_hit(self):
        text = "You fail to see how cleanly it lands until Elam Ferrier drops."
        violations = check(text, outcome=STRONG_HIT_OUTCOME)
        assert any(v.startswith("G3") for v in violations)

    def test_invented_entity_violation(self):
        text = "You lunge at Elam Ferrier, but Duke Malverin's chair blocks the way."
        violations = check(text)
        assert any(v.startswith("G4") and "Malverin" in v for v in violations)

    def test_context_entities_are_not_flagged(self):
        text = "Maren Ostler watches Elam Ferrier from behind the ledger in Harrowdown."
        assert not any(v.startswith("G4") for v in check(text))

    def test_length_cap(self):
        text = "The counter holds its ground. " + ("It holds and holds again. " * 90)
        violations = check(text)
        assert any(v.startswith("G5") for v in violations)


OBSERVATION_ACTION = {
    "action_type": "observation",
    "approach": "investigating the moving thing low to the ground",
    "target_entity_ids": ["creature_harrowdown_ditch_slime"],
    "dialogue": None,
}

OBSERVATION_OUTCOME = {
    "event_id": "53",
    "tier_resolved": "routine",
    "risk_label_shown": "guarded",
    "outcome_tier": "strong_hit",
    "dice": {"rolls": [5, 4], "modifiers": [], "total": 9},
    "state_deltas": [
        {"delta_type": "intel", "claim": {
            "subject_entity_id": "creature_harrowdown_ditch_slime",
            "claim_text": "The ditch slime recoils from lamplight.",
            "value_or_range": None, "layer": "inquiry", "source": "own attempt",
            "observer": None, "method": "witnessed", "world_date": "Y1-Q2-D14",
            "scope": "harrowdown", "confidence": "uncorroborated"}}
    ],
    "narration_constraints": ["entity_facts_only", "no_chronicle_contradiction"],
}

SLIME_ENVELOPE = {
    "scene_manifest": {
        "location_id": "loc_harrowdown_ditch", "label_known": "Harrowdown Ditch",
        "entities": [
            {"entity_id": "creature_harrowdown_ditch_slime", "label_known": "a ditch slime",
             "category": "creature"},
            {"entity_id": "npc_harrowdown_maren_ostler", "label_known": "Maren Ostler",
             "category": "person"},
        ],
    },
    "known_sheet_slices": [], "salient_claims": [], "active_clocks": [], "canon_excerpts": [],
}


class TestUnsupportedNpcSpeech:
    """G6 — the turn-53 fabrication class."""

    def _check(self, text, *, action=OBSERVATION_ACTION, outcome=OBSERVATION_OUTCOME):
        return narration_gate.check_narration(
            text, outcome=outcome, envelope=SLIME_ENVELOPE, action=action
        )

    def test_observation_gets_description_not_a_monologue(self):
        # correct: the slime is described, no one volunteers anything.
        text = (
            "The moving thing low to the ground is a ditch slime, a translucent "
            "sac hauling itself over the wet stones. It shrinks from your lamp."
        )
        assert not any(v.startswith("G6") for v in self._check(text))

    def test_turn53_fabricated_monologue_is_flagged(self):
        text = (
            "The moving thing is a ditch slime, low and pale over the stones. "
            "Maren Ostler leans over from the bar. \"You want dragon-lore, you're "
            "in the wrong room — Severwick keeps the deep of it, and the wyverns "
            "roll through four days south of here when the season turns.\""
        )
        violations = self._check(text)
        assert any(v.startswith("G6") for v in violations), violations

    def test_npc_speech_is_fine_on_a_dialogue_turn(self):
        dialogue_action = {
            "action_type": "dialogue",
            "approach": "ask Maren what she knows of dragons",
            "target_entity_ids": ["npc_harrowdown_maren_ostler"],
            "dialogue": {"addressee_id": "npc_harrowdown_maren_ostler",
                         "quoted_speech": "What do you know of dragons?"},
        }
        text = (
            "Maren Ostler wipes the counter. \"You want dragon-lore, you're in the "
            "wrong room — Severwick keeps the deep of it, four days south.\""
        )
        assert not any(v.startswith("G6") for v in self._check(text, action=dialogue_action))

    def test_short_reaction_is_not_a_monologue(self):
        # a curt caught-in-the-act line is a supported reaction, not volunteered lore.
        text = "The slime recoils from your lamp. Maren Ostler barks \"Out.\" and turns away."
        assert not any(v.startswith("G6") for v in self._check(text))

    def test_targeted_npc_may_react_in_speech(self):
        # the NPC the player acted ON this turn may react — bound to what the
        # player just did to them, not volunteered bystander lore (the nf-09
        # rescued-drover false positive the first eval run surfaced).
        rescue_action = {
            "action_type": "physical",
            "approach": "wade in on the rope and pull Wat clear of the flood",
            "target_entity_ids": ["npc_harrowdown_wat_drover"],
            "dialogue": None,
        }
        envelope = {
            "scene_manifest": {
                "location_id": "loc_harrowdown_cairn_road",
                "entities": [{"entity_id": "npc_harrowdown_wat_drover",
                              "label_known": "Wat the drover", "category": "person"}],
            },
            "known_sheet_slices": [], "salient_claims": [], "active_clocks": [],
            "canon_excerpts": [],
        }
        outcome = {"event_id": "9", "outcome_tier": "strong_hit", "state_deltas": [],
                   "narration_constraints": []}
        text = ("You haul Wat clear of the ford. \"Didn't think that stone would take "
                "my weight,\" he says, sitting up soaked through.")
        v = narration_gate.check_narration(
            text, outcome=outcome, envelope=envelope, action=rescue_action)
        assert not any(x.startswith("G6") for x in v), v


class TestCorrectiveLine:
    def test_carries_violations_and_instructions(self):
        line = narration_gate.corrective_line(("G1 System markup ([ ] or << >>) in prose",))
        assert "G1 System markup" in line
        assert "Re-narrate the SAME committed outcome" in line


class TestFallbackProse:
    def all_delta_outcome(self):
        return {
            "event_id": "43",
            "tier_resolved": "risky",
            "risk_label_shown": "perilous",
            "outcome_tier": "hit_with_complication",
            "dice": {"rolls": [4, 4], "modifiers": [], "total": 8},
            "state_deltas": [
                {"delta_type": "hp", "entity_id": "pc", "amount": -1, "cause": None},
                {"delta_type": "hp", "entity_id": "npc_harrowdown_elam_ferrier",
                 "amount": -3, "cause": None},
                {"delta_type": "coin", "entity_id": "pc", "amount": -5, "reason": None},
                {"delta_type": "inventory", "entity_id": "pc", "item_id": "itm_rope",
                 "op": "add", "quantity": 1},
                {"delta_type": "deed", "actor_entity_id": "pc", "description": "x",
                 "location_id": "loc_harrowdown_tavern", "witness_ids": [],
                 "notoriety": 1, "world_date": "d"},
            ],
            "narration_constraints": [],
        }

    def test_fallback_is_plain_register_and_bound_to_the_outcome(self):
        prose = narration_gate.fallback_prose(MISS_OUTCOME, pc_id="pc")
        assert prose.startswith("It does not go your way.")
        assert "hurt" in prose  # the pc hp delta is summarized

    def test_fallback_passes_its_own_gate(self):
        for outcome in (MISS_OUTCOME, STRONG_HIT_OUTCOME, self.all_delta_outcome()):
            prose = narration_gate.fallback_prose(outcome, pc_id="pc")
            violations = narration_gate.check_narration(
                prose, outcome=outcome, envelope=ENVELOPE, action=ACTION
            )
            assert violations == (), (outcome["event_id"], violations, prose)

    def test_no_roll_tiers_get_their_own_register(self):
        trivial = {
            "event_id": "44", "tier_resolved": "trivial", "risk_label_shown": None,
            "outcome_tier": None, "dice": None, "state_deltas": [],
            "narration_constraints": [],
        }
        assert narration_gate.fallback_prose(trivial) == "It is done without ceremony."


# --- G3(b) semantic clause-level agreement ------------------------------
#
# PRODUCTION-category scene (entities carry the engine `kind` vocabulary: npc /
# character / creature), not the legacy fixture label `person`.
PROD_SCENE = {
    "scene_manifest": {
        "location_id": "loc_harrowdown_cairn_road", "label_known": "The Cairn Road",
        "entities": [
            {"entity_id": "npc_harrowdown_rold_tanner", "label_known": "Rold Tanner",
             "category": "npc"},
        ],
    },
    "known_sheet_slices": [], "salient_claims": [], "active_clocks": [], "canon_excerpts": [],
}
PROD_ACTION = {
    "action_type": "physical", "approach": "drive the staff at Rold's head",
    "target_entity_ids": ["npc_harrowdown_rold_tanner"], "dialogue": None,
}
# A committed MISS whose only delta wounded the PC — no dispatched / death_record,
# so a KILL of the target is NOT licensed.
KILL_ON_MISS_OUTCOME = {
    "event_id": "601", "tier_resolved": "desperate", "risk_label_shown": "dire",
    "outcome_tier": "miss", "dice": {"rolls": [2, 3], "modifiers": [], "total": 5},
    "state_deltas": [
        {"delta_type": "wound_transition", "entity_id": "pc", "effect": "wounded"},
    ],
    "narration_constraints": ["no_success_framing"],
}
# The SAME action resolved as a real kill — dispatched delta licenses the death.
KILL_COMMITTED_OUTCOME = {
    "event_id": "602", "tier_resolved": "desperate", "risk_label_shown": "dire",
    "outcome_tier": "strong_hit", "dice": {"rolls": [6, 5], "modifiers": [], "total": 11},
    "state_deltas": [
        {"delta_type": "wound_transition", "entity_id": "npc_harrowdown_rold_tanner",
         "effect": "dispatched"},
    ],
    "narration_constraints": [],
}
KILL_NARRATION = (
    "Your staff finds the gap in Rold Tanner's guard and drives home. He drops "
    "to the mud, dead before he lands, and the cairn road goes quiet around you."
)

# A committed outcome with NO inventory delta — an item taken is NOT licensed.
NO_INVENTORY_OUTCOME = {
    "event_id": "603", "tier_resolved": "routine", "risk_label_shown": "guarded",
    "outcome_tier": "strong_hit", "dice": {"rolls": [5, 4], "modifiers": [], "total": 9},
    "state_deltas": [
        {"delta_type": "flag", "entity_id": "pc",
         "flag_key": "noticed_by_rold", "value": True},
    ],
    "narration_constraints": [],
}
INVENTORY_COMMITTED_OUTCOME = {
    "event_id": "604", "tier_resolved": "routine", "risk_label_shown": "guarded",
    "outcome_tier": "strong_hit", "dice": {"rolls": [5, 4], "modifiers": [], "total": 9},
    "state_deltas": [
        {"delta_type": "inventory", "entity_id": "pc", "item_id": "item_brass_key",
         "op": "add", "quantity": 1},
    ],
    "narration_constraints": [],
}
INVENTORY_NARRATION = (
    "You search the coat and lift a heavy brass key from the inner pocket, "
    "tucking it into your own belt pouch."
)


class TestSemanticG3AllowedFacts:
    """allowed_facts() derives the typed licence set from committed deltas."""

    def test_dispatched_licenses_kill_and_damage(self):
        assert narration_gate.allowed_facts(KILL_COMMITTED_OUTCOME) == {"kill", "damage"}

    def test_wounded_licenses_damage_not_kill(self):
        assert narration_gate.allowed_facts(KILL_ON_MISS_OUTCOME) == {"damage"}

    def test_inventory_add_licenses_item_gain(self):
        assert narration_gate.allowed_facts(INVENTORY_COMMITTED_OUTCOME) == {"item_gain"}

    def test_no_deltas_license_nothing(self):
        assert narration_gate.allowed_facts(STRONG_HIT_OUTCOME) == set()


WOUNDED_ONLY_OUTCOME = {
    "event_id": "606",
    "tier_resolved": "routine",
    "risk_label_shown": "guarded",
    "outcome_tier": "strong_hit",
    "dice": {"rolls": [5, 5], "modifiers": [], "total": 10},
    "state_deltas": [
        {
            "delta_type": "wound_transition",
            "entity_id": "npc_harrowdown_jorun_pike",
            "effect": "wounded",
        },
    ],
    "narration_constraints": [],
}
WOUNDED_SCENE = {
    "scene_manifest": {
        "location_id": "loc_harrowdown_tavern",
        "label_known": "The Drowned Ram",
        "entities": [
            {
                "entity_id": "npc_harrowdown_jorun_pike",
                "label_known": "Jorun Pike",
                "category": "npc",
                "state_tags": ["wounded"],
            },
        ],
    },
    "known_sheet_slices": [],
    "salient_claims": [],
    "active_clocks": [],
    "canon_excerpts": [],
}
WOUND_ACTION = {
    "action_type": "physical",
    "approach": "punch Jorun once",
    "target_entity_ids": ["npc_harrowdown_jorun_pike"],
    "dialogue": None,
}


class TestSemanticG3SpecificInjuries:
    """Generic wound deltas do not license new body-part state."""

    def test_generic_wound_word_is_admitted(self):
        text = "Jorun Pike comes away wounded and gives ground by the bar."
        v = narration_gate.check_narration(
            text, outcome=WOUNDED_ONLY_OUTCOME, envelope=WOUNDED_SCENE,
            action=WOUND_ACTION,
        )
        assert not any("specific injury" in x for x in v), v

    def test_split_lip_is_rejected_without_support(self):
        text = "Jorun Pike wipes at a split lip and gives ground by the bar."
        v = narration_gate.check_narration(
            text, outcome=WOUNDED_ONLY_OUTCOME, envelope=WOUNDED_SCENE,
            action=WOUND_ACTION,
        )
        assert any(x.startswith("G3") and "specific injury location" in x for x in v), v

    def test_wounded_arm_is_rejected_without_support(self):
        text = "Jorun Pike keeps his wounded arm close and gives ground by the bar."
        v = narration_gate.check_narration(
            text, outcome=WOUNDED_ONLY_OUTCOME, envelope=WOUNDED_SCENE,
            action=WOUND_ACTION,
        )
        assert any("wounded arm" in x for x in v), v

    def test_existing_specific_context_allows_restating_it(self):
        scene = dict(WOUNDED_SCENE)
        scene["scene_manifest"] = dict(WOUNDED_SCENE["scene_manifest"])
        scene["scene_manifest"]["entities"] = [
            {
                "entity_id": "npc_harrowdown_jorun_pike",
                "label_known": "Jorun Pike",
                "category": "npc",
                "state_tags": ["wounded", "split_lip"],
            },
        ]
        text = "Jorun Pike wipes at a split lip and gives ground by the bar."
        v = narration_gate.check_narration(
            text, outcome=WOUNDED_ONLY_OUTCOME, envelope=scene, action=WOUND_ACTION,
        )
        assert not any("specific injury location" in x for x in v), v

    def test_body_part_named_by_damaging_action_is_supported(self):
        action = dict(WOUND_ACTION)
        action["approach"] = "punch Jorun in the arm"
        text = "Jorun Pike keeps his wounded arm close and gives ground by the bar."
        v = narration_gate.check_narration(
            text, outcome=WOUNDED_ONLY_OUTCOME, envelope=WOUNDED_SCENE, action=action,
        )
        assert not any("specific injury location" in x for x in v), v


class TestSemanticG3KillOnMiss:
    """The Codex-reproduced kill-on-miss: narration claims a kill the
    committed deltas never recorded. The OLD lexical gate admitted it."""

    def test_kill_on_miss_is_rejected(self):
        v = narration_gate.check_narration(
            KILL_NARRATION, outcome=KILL_ON_MISS_OUTCOME,
            envelope=PROD_SCENE, action=PROD_ACTION)
        # exactly the semantic-G3 kill flag — nothing else fires, which proves the
        # OLD gate (no semantic layer, and no lexical success word here) returned ().
        assert v == (
            'G3 asserts a kill / a death the committed outcome did not license: '
            '"drops to the mud, dead"',
        ), v

    def test_lexical_g3_alone_would_miss_it(self):
        # the narration carries no success/failure lexicon, so the pre-audit gate
        # would not have flagged G3 — the kill class is only caught semantically.
        assert not narration_gate.SUCCESS_WORDS.search(KILL_NARRATION)
        assert not any(v == "G3 success-framing on a committed miss"
                       for v in narration_gate.check_narration(
                           KILL_NARRATION, outcome=KILL_ON_MISS_OUTCOME,
                           envelope=PROD_SCENE, action=PROD_ACTION))

    def test_same_kill_narration_admitted_when_dispatched(self):
        # delta-bound, not a blanket ban: the identical prose passes when the
        # outcome committed a dispatched wound_transition.
        v = narration_gate.check_narration(
            KILL_NARRATION, outcome=KILL_COMMITTED_OUTCOME,
            envelope=PROD_SCENE, action=PROD_ACTION)
        assert not any(x.startswith("G3") for x in v), v

    def test_death_record_also_licenses_a_kill(self):
        outcome = dict(KILL_ON_MISS_OUTCOME)
        outcome["state_deltas"] = [
            {"delta_type": "death_record", "entity_id": "npc_harrowdown_rold_tanner",
             "cause": "staff", "location_id": "loc_harrowdown_cairn_road",
             "witness_ids": [], "body_disposition": None, "journal_disposition": None,
             "rumor_seeds": [], "world_date": "Y1-Q2-D14"},
        ]
        v = narration_gate.check_narration(
            KILL_NARRATION, outcome=outcome, envelope=PROD_SCENE, action=PROD_ACTION)
        assert not any(x.startswith("G3") for x in v), v

    def test_pre_existing_corpse_is_not_a_fresh_kill(self):
        # "already dead" is a scene fact, not a kill the narrator committed.
        text = "The rat is already dead. Your boot presses it flatter into the mud."
        outcome = {"event_id": "44", "tier_resolved": "trivial", "outcome_tier": None,
                   "state_deltas": [], "narration_constraints": []}
        v = narration_gate.check_narration(text, outcome=outcome, envelope=PROD_SCENE,
                                           action=PROD_ACTION)
        assert not any(x.startswith("G3") for x in v), v


class TestSemanticG3InventedInventory:
    """Narration adds an item with no inventory delta. OLD gate passed."""

    def test_invented_inventory_is_rejected(self):
        v = narration_gate.check_narration(
            INVENTORY_NARRATION, outcome=NO_INVENTORY_OUTCOME,
            envelope=PROD_SCENE, action=PROD_ACTION)
        assert any(x.startswith("G3") and "item taken into inventory" in x for x in v), v

    def test_same_item_narration_admitted_when_inventory_add(self):
        v = narration_gate.check_narration(
            INVENTORY_NARRATION, outcome=INVENTORY_COMMITTED_OUTCOME,
            envelope=PROD_SCENE, action=PROD_ACTION)
        assert not any(x.startswith("G3") for x in v), v

    def test_npc_pocketing_own_coin_is_not_player_item_gain(self):
        # an NPC pocketing their own payment is not the PLAYER acquiring an item.
        text = "Rold finishes the sale, pockets his cut, and glances over at the well step."
        v = narration_gate.check_narration(
            text, outcome=NO_INVENTORY_OUTCOME, envelope=PROD_SCENE, action=PROD_ACTION)
        assert not any(x.startswith("G3") for x in v), v


class TestSemanticG3Movement:
    """Invented door/movement actions require a committed position delta."""

    POSITION_OUTCOME = {
        "event_id": "605", "tier_resolved": "risky", "risk_label_shown": "perilous",
        "outcome_tier": "strong_hit", "dice": {"rolls": [5, 5], "modifiers": [], "total": 10},
        "state_deltas": [
            {"delta_type": "position", "entity_id": "pc",
             "from_location_id": "loc_harrowdown_cairn_road",
             "to_location_id": "loc_harrowdown_tavern", "transit_hint": "walked"},
        ],
        "narration_constraints": [],
    }
    DOOR_NARRATION = "You push through the door into the tavern and let it swing shut behind you."

    def test_invented_door_action_rejected_without_position_delta(self):
        v = narration_gate.check_narration(
            self.DOOR_NARRATION, outcome=NO_INVENTORY_OUTCOME,
            envelope=PROD_SCENE, action=PROD_ACTION)
        assert any(x.startswith("G3") and "moving to a new place" in x for x in v), v

    def test_door_action_admitted_with_position_delta(self):
        v = narration_gate.check_narration(
            self.DOOR_NARRATION, outcome=self.POSITION_OUTCOME,
            envelope=PROD_SCENE, action=PROD_ACTION)
        assert not any(x.startswith("G3") for x in v), v

    def test_looking_through_a_doorway_is_not_movement(self):
        # a line of sight through a doorway is not the character passing through it.
        text = "Through the doorway Jorun sits with his cup, and does not look up from it once."
        v = narration_gate.check_narration(
            text, outcome=NO_INVENTORY_OUTCOME, envelope=PROD_SCENE, action=PROD_ACTION)
        assert not any(x.startswith("G3") for x in v), v


class TestProductionNpcCategoryG6:
    """The npc/person fix: production emits `npc`, the old gate matched
    only `person`, so G6 was inert. persons = npc + character now."""

    NPC_SCENE = {
        "scene_manifest": {
            "location_id": "loc_harrowdown_ditch", "label_known": "Harrowdown Ditch",
            "entities": [
                {"entity_id": "creature_harrowdown_ditch_slime", "label_known": "a ditch slime",
                 "category": "creature"},
                {"entity_id": "npc_harrowdown_maren_ostler", "label_known": "Maren Ostler",
                 "category": "npc"},  # production category
            ],
        },
        "known_sheet_slices": [], "salient_claims": [], "active_clocks": [], "canon_excerpts": [],
    }
    OBS_ACTION = {"action_type": "observation", "approach": "investigate the moving thing",
                  "target_entity_ids": ["creature_harrowdown_ditch_slime"], "dialogue": None}
    OBS_OUTCOME = {"event_id": "53", "outcome_tier": "strong_hit", "state_deltas": [],
                   "narration_constraints": []}
    MONOLOGUE = (
        "The moving thing is a ditch slime, low over the stones. Maren Ostler leans "
        "over from the bar. \"You want that lore, you're in the wrong room entirely, "
        "and the road you want runs four days south when the season finally turns.\""
    )

    def test_npc_category_person_is_detected(self):
        persons = narration_gate._scene_persons(self.NPC_SCENE)
        assert [p["entity_id"] for p in persons] == ["npc_harrowdown_maren_ostler"]

    def test_g6_fires_on_production_npc_category(self):
        v = narration_gate.check_narration(
            self.MONOLOGUE, outcome=self.OBS_OUTCOME,
            envelope=self.NPC_SCENE, action=self.OBS_ACTION)
        assert any(x.startswith("G6") for x in v), v

    def test_character_category_also_counts_as_person(self):
        assert "character" in narration_gate.PERSON_CATEGORIES
        assert "npc" in narration_gate.PERSON_CATEGORIES
