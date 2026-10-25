"""The Referee: tier decisions, contract conformance, deposit invariants."""

from __future__ import annotations

import jsonschema
import pytest

from everquill_engine.ladder import PlausibilityTier
from everquill_engine.resolver import (
    CONVERSATION_PARTNER_FLAG,
    UNADDRESSABLE_TARGET,
    ResolverError,
    decide_tier,
    outcome_contract,
)
from everquill_engine.views import outcome_public, self_view
from tests.harness import REPO_ROOT, Sim, intent_schema_v11, load_schema, load_script

HARROWDOWN = REPO_ROOT / "content" / "world" / "harrowdown.yaml"
DANGER_WORLD = REPO_ROOT / "tests" / "fixtures" / "danger-world.yaml"


def canned(
    action_type, targets=(), approach="do the thing", stat_hint=None, dialogue=None, **fields
):
    """A full v1.3 intent; ``fields`` sets the closed decision fields."""
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


@pytest.fixture()
def sim():
    return Sim(seed=42)


OUTCOME_SCHEMA = load_schema("outcome.schema.json")
INTENT_SCHEMA = intent_schema_v11()


class TestContracts:
    def test_script_intents_conform_to_intent_schema(self):
        for entry in load_script():
            jsonschema.validate(entry["intent"], INTENT_SCHEMA)

    def test_cli_menu_intents_conform_to_intent_schema(self, sim):
        from everquill_engine.cli import _build_menu

        menu = _build_menu(sim.world, "loc.dev.tavern")
        assert len(menu) >= 15
        for _label, intent in menu:
            jsonschema.validate(intent, INTENT_SCHEMA)

    def test_every_scripted_outcome_conforms_to_outcome_schema(self, sim):
        for entry in load_script():
            _res, outcome_row = sim.run_turn(entry["intent"])
            # outcome.schema.json v1.3 describes the PUBLIC projection
            #; the raw contract keeps exact hp server-side.
            contract = outcome_public(outcome_contract(outcome_row))
            jsonschema.validate(contract, OUTCOME_SCHEMA)
            # Re-check the arithmetic the schema cannot (per its description).
            if contract["dice"] is not None:
                dice = contract["dice"]
                assert dice["total"] == sum(dice["rolls"]) + sum(
                    m["value"] for m in dice["modifiers"]
                )

    def test_contract_ids_are_schema_safe(self, sim):
        _res, row = sim.run_turn(
            canned("physical", ["npc_dev_torvald"], "put his arm to the table", "might")
        )
        contract = outcome_contract(row)
        assert contract["event_id"] == str(row["id"])
        for delta in contract["state_deltas"]:
            for value in delta.values():
                if isinstance(value, str) and value.startswith("npc"):
                    assert "." not in value


class TestTierDecisions:
    def test_meta_and_dialogue_and_untargeted_observation_are_trivial(self, sim):
        for intent in (
            canned("meta"),
            canned("dialogue", ["npc_dev_hedda"], dialogue={
                "addressee_id": "npc_dev_hedda", "quoted_speech": "Evening."
            }),
            canned("observation"),
        ):
            res, row = sim.run_turn(intent)
            assert res.tier is PlausibilityTier.TRIVIAL
            assert row["payload"]["dice"] is None
            assert row["payload"]["outcome_tier"] is None
            assert row["payload"]["risk_label_shown"] is None

    def test_physical_vs_drillmaster_is_hopeless_and_always_miss(self, sim):
        # threat 20 vs any 2..12 chargen might → gap >= 8 → HOPELESS.
        res, row = sim.run_turn(canned("physical", ["npc_dev_torvald"], stat_hint="might"))
        assert res.tier is PlausibilityTier.HOPELESS
        assert row["payload"]["outcome_tier"] == "miss"
        assert row["payload"]["hopeless_flavor"] in ("catastrophic", "punishing", "spared")
        assert row["payload"]["risk_label_shown"] == "suicidal"
        assert row["payload"]["state_deltas"], "hopeless must still deposit"

    def test_hopeless_always_misses_for_all_flavors(self):
        # Sweep seeds until all three flavors observed; every one a miss.
        flavors = set()
        for seed in range(40):
            sim = Sim(seed=seed)
            res, row = sim.run_turn(
                canned("physical", ["npc_dev_torvald"], stat_hint="might")
            )
            assert row["payload"]["outcome_tier"] == "miss"
            flavors.add(row["payload"]["hopeless_flavor"])
        assert flavors == {"catastrophic", "punishing", "spared"}

    def test_every_miss_deposits_at_least_one_delta(self):
        for seed in range(40):
            sim = Sim(seed=seed)
            for entry in load_script():
                _res, row = sim.run_turn(entry["intent"])
                if row["payload"]["outcome_tier"] == "miss":
                    assert row["payload"]["state_deltas"], (
                        f"seed {seed}: miss with no deposit: {row['payload']}"
                    )

    def test_impossible_never_rolls_but_is_a_deed(self, sim):
        res, row = sim.run_turn(
            canned(
                "physical",
                approach="levitate off the floor",
                invoked_law_ids=["law_unwritten_flight"],
            )
        )
        assert res.tier is PlausibilityTier.IMPOSSIBLE
        payload = row["payload"]
        assert payload["dice"] is None and payload["outcome_tier"] is None
        assert payload["law_id"] == "law.unwritten_flight"
        assert any(d["delta_type"] == "deed" for d in payload["state_deltas"])
        assert "impossible_tier_irony_licensed" in payload["narration_constraints"]

    def test_approach_wording_never_invokes_a_law(self, sim):
        # The law's own invoke phrase in the approach decides nothing: only
        # the closed invoked_law_ids field does.
        for approach in ("levitate off the floor", "chase a butterfly across the floor"):
            _res, row = sim.run_turn(canned("physical", approach=approach))
            assert row["payload"].get("law_id") is None, approach

    def test_unknown_invoked_law_id_matches_nothing(self, sim):
        _res, row = sim.run_turn(
            canned("physical", approach="levitate", invoked_law_ids=["law_not_authored"])
        )
        assert row["payload"].get("law_id") is None

    def test_sealed_unmet_fails_forward_without_dice(self, sim):
        res, row = sim.run_turn(
            canned(
                "social",
                approach="swear a binding hearth-oath at the fire",
                invoked_law_ids=["law_hearth_oath"],
            )
        )
        assert res.tier is PlausibilityTier.SEALED
        payload = row["payload"]
        assert payload["dice"] is None
        assert payload["outcome_tier"] == "miss"
        assert payload["law_id"] == "law.hearth_oath"
        kinds = {d["delta_type"] for d in payload["state_deltas"]}
        assert "deed" in kinds and "flag" in kinds and "intel" in kinds

    def test_sealed_with_components_verified_rolls_as_desperate(self, sim):
        sim.pc["flags"]["hearth_token"] = True
        sim.pc["flags"]["witness_blessing"] = True
        res, row = sim.run_turn(
            canned(
                "social",
                approach="swear a binding hearth-oath at the fire",
                invoked_law_ids=["law_hearth_oath"],
            )
        )
        assert res.tier is PlausibilityTier.DESPERATE
        assert row["payload"]["dice"] is not None
        assert row["payload"]["law_notes"] == ["components of law.hearth_oath verified"]

    def test_risk_labels_match_bands(self, sim):
        res, row = sim.run_turn(canned("research", ["npc_dev_sorrel"], stat_hint="lore"))
        # lore 7 vs ambient 5 → gap -2 → ROUTINE → guarded.
        assert res.tier is PlausibilityTier.ROUTINE
        assert row["payload"]["risk_label_shown"] == "guarded"

    def test_train_starts_timer_no_roll(self, sim):
        res, row = sim.run_turn(canned("train", stat_hint="might"))
        assert res.tier is PlausibilityTier.TRIVIAL
        (timer_delta,) = [
            d for d in row["payload"]["state_deltas"] if d["delta_type"] == "timer_started"
        ]
        assert timer_delta["kind"] == "training"
        timer = sim.state.timers[timer_delta["timer_id"]]
        assert timer["status"] == "pending"
        assert timer["created_event_id"] == row["id"]

    def test_unknown_target_is_refused_without_canon(self, sim):
        before = len(sim.rows)
        with pytest.raises(ResolverError):
            sim.run_turn(canned("physical", ["npc_dev_nobody"]))
        assert len(sim.rows) == before


def _decide(sim, intent, claim_subjects=None):
    return decide_tier(
        intent=intent,
        actor=sim.pc,
        world=sim.world,
        manifest=sim.state.manifest,
        world_time=sim.state.world["world_time"],
        entity_states=sim.state.entities,
        actor_claim_subjects=claim_subjects,
    )


def _place_pc(sim, location_id: str) -> None:
    sim.state.characters["pc"]["location_id"] = location_id
    if "pc" in sim.state.manifest:
        sim.state.manifest["pc"]["location_id"] = location_id


def _stored_intent_for(resolution, sim):
    return sim.rows[-len(resolution.events)]["payload"]["intent"]


class TestTargetAddressability:
    """Only co-located + perceptible scene entities, owned items,
    connected locations, and (for research) the actor's known Codex
    subjects are addressable. Unknown and unauthorized targets are refused
    with the SAME string — the boundary is not an existence oracle."""

    def _hw(self):
        # Harrowdown: the PC starts on Market Row (first location).
        return Sim(seed=42, world_path=HARROWDOWN)

    def _tavern(self):
        sim = self._hw()
        _place_pc(sim, "loc.harrowdown.tavern")
        return sim

    def test_remote_entity_attack_is_refused_with_zero_events(self):
        sim = self._hw()
        before = len(sim.rows)
        # Fenn Bracey is in the Guild Hall; the PC is on Market Row.
        with pytest.raises(ResolverError) as exc:
            sim.run_turn(canned("physical", ["npc_harrowdown_fenn_bracey"], "strike him"))
        assert str(exc.value) == UNADDRESSABLE_TARGET
        assert len(sim.rows) == before  # no canon written

    def test_unknown_and_off_scene_reject_identically(self):
        sim = self._hw()
        with pytest.raises(ResolverError) as unknown:
            _decide(sim, canned("physical", ["npc_harrowdown_nobody"]))
        with pytest.raises(ResolverError) as off_scene:
            _decide(sim, canned("physical", ["npc_harrowdown_fenn_bracey"]))
        assert str(unknown.value) == str(off_scene.value) == UNADDRESSABLE_TARGET

    def test_hidden_target_rejected_like_an_unknown_id(self):
        sim = self._hw()
        # Put the PC in the chandlery, CO-LOCATED with the hidden seal.
        sim.state.characters["pc"]["location_id"] = "loc.harrowdown.chandlery"
        with pytest.raises(ResolverError) as hidden:
            _decide(sim, canned("observation", ["item_harrowdown_marriage_seal"], "study it"))
        with pytest.raises(ResolverError) as unknown:
            _decide(sim, canned("observation", ["item_harrowdown_ghost"], "study it"))
        # Byte-identical: co-located-but-hidden is not an existence oracle.
        assert str(hidden.value) == str(unknown.value) == UNADDRESSABLE_TARGET

    def test_discovered_hidden_target_becomes_addressable(self):
        sim = self._hw()
        sim.state.characters["pc"]["location_id"] = "loc.harrowdown.chandlery"
        sim.pc["flags"]["discovered_item_harrowdown_marriage_seal"] = True
        decision = _decide(
            sim, canned("observation", ["item_harrowdown_marriage_seal"], "study it")
        )
        assert decision.targets == ("item.harrowdown.marriage_seal",)

    def test_co_located_entity_is_addressable(self):
        sim = self._hw()
        # Rold Tanner stands on Market Row with the PC.
        decision = _decide(sim, canned("social", ["npc_harrowdown_rold_tanner"], "talk"))
        assert decision.targets == ("npc.harrowdown.rold_tanner",)

    def test_current_location_observation_is_ambient_no_roll(self):
        sim = self._tavern()
        ambient = _decide(sim, canned("observation", approach="look around"))
        decision = _decide(
            sim,
            canned("observation", ["loc_harrowdown_tavern"], "survey the tavern"),
        )

        assert decision.targets == ambient.targets == ()
        assert decision.tier is ambient.tier is PlausibilityTier.TRIVIAL
        assert decision.risk_label is None

        res, row = sim.run_turn(
            canned("observation", ["loc_harrowdown_tavern"], "observe the room")
        )
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["dice"] is None
        assert row["payload"]["outcome_tier"] is None
        assert row["payload"]["risk_label_shown"] is None

    def test_current_location_observation_drops_only_the_location_target(self):
        sim = self._tavern()
        decision = _decide(
            sim,
            canned(
                "observation",
                ["loc_harrowdown_tavern", "npc_harrowdown_maren_ostler"],
                "survey Maren and the tavern",
            ),
        )

        assert decision.targets == ("npc.harrowdown.maren_ostler",)

    def test_co_located_entity_observation_still_targets_the_entity(self):
        sim = self._tavern()
        decision = _decide(
            sim,
            canned("observation", ["npc_harrowdown_maren_ostler"], "watch Maren"),
        )

        assert decision.targets == ("npc.harrowdown.maren_ostler",)

    def test_other_location_observation_is_still_unaddressable(self):
        sim = self._tavern()
        with pytest.raises(ResolverError) as exc:
            _decide(
                sim,
                canned("observation", ["loc_harrowdown_market_row"], "survey outside"),
            )

        assert str(exc.value) == UNADDRESSABLE_TARGET

    def test_research_reaches_known_codex_subjects_off_scene(self):
        sim = self._hw()
        # No claim: an off-scene research subject is refused like anything else.
        with pytest.raises(ResolverError):
            _decide(sim, canned("research", ["npc_harrowdown_fenn_bracey"], "read up"))
        # With a live claim about Fenn, research reaches him.
        decision = _decide(
            sim,
            canned("research", ["npc_harrowdown_fenn_bracey"], "read up"),
            claim_subjects=frozenset({"npc.harrowdown.fenn_bracey"}),
        )
        assert decision.targets == ("npc.harrowdown.fenn_bracey",)

    def test_owned_item_is_addressable_off_scene(self):
        sim = self._hw()  # the seal's manifest is in the chandlery; PC on Market Row
        sim.pc["inventory"]["item_harrowdown_marriage_seal"] = 1
        decision = _decide(
            sim, canned("observation", ["item_harrowdown_marriage_seal"], "turn it over")
        )
        assert decision.targets == ("item.harrowdown.marriage_seal",)


class TestMovementResolution:
    def _tavern(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _place_pc(sim, "loc.harrowdown.tavern")
        return sim

    def test_connected_exit_moves_the_player(self):
        sim = self._tavern()
        res, row = sim.run_turn(
            canned("movement", ["loc_harrowdown_market_row"], "go outside")
        )
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["dice"] is None
        (delta,) = row["payload"]["state_deltas"]
        assert delta["delta_type"] == "position"
        assert delta["to_location_id"] == "loc.harrowdown.market_row"
        assert row["payload"]["movement_blocked"] is False
        assert row["payload"]["system_note"] is None
        assert outcome_contract(row)["movement_blocked"] is False
        assert sim.pc["location_id"] == "loc.harrowdown.market_row"

    def test_in_scene_repositioning_is_narrate_only(self):
        sim = self._tavern()
        res, row = sim.run_turn(
            canned("movement", approach="go to the bar", movement_scope="here")
        )
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["state_deltas"] == []
        assert row["payload"]["movement_blocked"] is False
        assert row["payload"]["system_note"] == "You cross the room."
        assert "You cross the room." in res.summary

    def test_targetless_move_away_is_refused_whatever_the_wording(self):
        # Only movement_scope "here" crosses the room; the approach once
        # decided this, so "go to the bar" was free and "head out" refused.
        for scope in ("away", None):
            sim = self._tavern()
            _res, row = sim.run_turn(
                canned("movement", approach="go to the bar", movement_scope=scope)
            )
            assert row["payload"]["movement_blocked"] is True, scope
            assert row["payload"]["system_note"] != "You cross the room."

    def test_unknown_destination_names_real_exits_without_error(self):
        sim = self._tavern()
        res, row = sim.run_turn(canned("movement", approach="go to the clock tower"))
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["state_deltas"] == []
        assert row["payload"]["movement_blocked"] is True
        assert (
            row["payload"]["system_note"]
            == "You stay where you are. From here you can go to: Market Row."
        )
        assert outcome_contract(row)["movement_blocked"] is True
        assert row["payload"]["system_note"] in res.summary

    def test_unconnected_location_names_real_exits_without_error(self):
        sim = self._tavern()
        res, row = sim.run_turn(
            canned("movement", ["loc_harrowdown_chapel"], "head to the chapel")
        )
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["state_deltas"] == []
        assert row["payload"]["movement_blocked"] is True
        assert (
            row["payload"]["system_note"]
            == "You stay where you are. From here you can go to: Market Row."
        )
        assert outcome_contract(row)["movement_blocked"] is True
        assert row["payload"]["system_note"] in res.summary

    def test_blocked_movement_with_no_exits_says_stayed_put(self):
        sim = Sim(seed=42, world_path=DANGER_WORLD)
        res, row = sim.run_turn(canned("movement", approach="leave the quarry"))
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["state_deltas"] == []
        assert row["payload"]["movement_blocked"] is True
        assert (
            row["payload"]["system_note"]
            == "You stay where you are. There is no way out of here that you can see."
        )
        assert outcome_contract(row)["movement_blocked"] is True
        assert row["payload"]["system_note"] in res.summary

    def test_already_here_is_not_flagged_blocked(self):
        sim = self._tavern()
        res, row = sim.run_turn(
            canned("movement", ["loc_harrowdown_tavern"], "stay in the tavern")
        )
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["state_deltas"] == []
        assert row["payload"]["movement_blocked"] is False
        assert row["payload"]["system_note"] is None


class TestStickyConversationPartner:
    def _tavern(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _place_pc(sim, "loc.harrowdown.tavern")
        return sim

    def _ask(self, target: str, approach="ask about the captain's plate"):
        return canned(
            "dialogue",
            [target],
            approach,
            dialogue={"addressee_id": target, "quoted_speech": None},
            addressee="person",
            speech_act="question",
        )

    def _ambiguous_followup(self):
        intent = canned(
            "dialogue",
            [],
            "ask about his captain's plate",
            dialogue={"addressee_id": None, "quoted_speech": None},
            addressee="person",
            speech_act="question",
        )
        intent["ambiguity_flags"] = ["ambiguous_addressee"]
        return intent

    def _unnamed_quarry_followup(self):
        return canned(
            "dialogue",
            [],
            "and what about the quarry?",
            dialogue={"addressee_id": None, "quoted_speech": None},
            addressee="person",
            speech_act="question",
            topic_ids=["creature_harrowdown_quarryman"],
        )

    def test_ambiguous_followup_sticks_to_current_partner(self):
        sim = self._tavern()
        sim.run_turn(self._ask("npc_harrowdown_jorun_pike"))
        assert sim.pc["flags"][CONVERSATION_PARTNER_FLAG] == "npc.harrowdown.jorun_pike"

        res, _row = sim.run_turn(self._ambiguous_followup())
        stored = _stored_intent_for(res, sim)
        assert stored["target_entity_ids"] == ["npc_harrowdown_jorun_pike"]
        assert stored["dialogue"]["addressee_id"] == "npc_harrowdown_jorun_pike"

    def test_naming_someone_else_switches_partner(self):
        sim = self._tavern()
        sim.run_turn(self._ask("npc_harrowdown_jorun_pike"))
        sim.run_turn(self._ask("npc_harrowdown_maren_ostler", "ask Maren about Pike"))
        assert sim.pc["flags"][CONVERSATION_PARTNER_FLAG] == "npc.harrowdown.maren_ostler"

        res, _row = sim.run_turn(self._ambiguous_followup())
        assert _stored_intent_for(res, sim)["target_entity_ids"] == [
            "npc_harrowdown_maren_ostler"
        ]

    def test_unnamed_followup_without_ambiguity_flag_sticks_to_current_partner(self):
        sim = self._tavern()
        assert sim.state.manifest["npc.harrowdown.jorun_pike"]["location_id"] == (
            "loc.harrowdown.tavern"
        )
        sim.run_turn(self._ask("npc_harrowdown_maren_ostler", "ask Maren what work there is"))

        res, row = sim.run_turn(self._unnamed_quarry_followup())
        stored = _stored_intent_for(res, sim)
        assert stored["target_entity_ids"] == ["npc_harrowdown_maren_ostler"]
        assert stored["dialogue"]["addressee_id"] == "npc_harrowdown_maren_ostler"

        (intel,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "intel"]
        assert intel["claim"]["subject_entity_id"] == "creature.harrowdown.quarryman"
        assert intel["claim"]["source_agent_id"] == "npc.harrowdown.maren_ostler"

    def test_moving_locations_clears_partner(self):
        sim = self._tavern()
        sim.run_turn(self._ask("npc_harrowdown_jorun_pike"))
        _res, row = sim.run_turn(
            canned("movement", ["loc_harrowdown_market_row"], "go outside")
        )
        clear = [
            d for d in row["payload"]["state_deltas"]
            if d.get("flag_key") == CONVERSATION_PARTNER_FLAG
        ]
        assert clear and clear[0]["value"] is None
        assert sim.pc["flags"][CONVERSATION_PARTNER_FLAG] is None

        res, _row = sim.run_turn(self._ambiguous_followup())
        stored = _stored_intent_for(res, sim)
        assert stored["target_entity_ids"] == []
        assert stored["dialogue"]["addressee_id"] is None

    def test_explicit_room_speech_does_not_use_sticky_partner(self):
        sim = self._tavern()
        sim.run_turn(self._ask("npc_harrowdown_jorun_pike"))
        room = canned(
            "dialogue",
            [],
            "say to the room that the road is closed",
            dialogue={"addressee_id": None, "quoted_speech": None},
            addressee="room",
            speech_act="statement",
        )
        res, _row = sim.run_turn(room)
        stored = _stored_intent_for(res, sim)
        assert stored["target_entity_ids"] == []
        assert stored["dialogue"]["addressee_id"] is None


class TestInformationSeekingDialogue:
    def _tavern(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _place_pc(sim, "loc.harrowdown.tavern")
        return sim

    def _ask_maren(self, approach: str, **fields):
        fields.setdefault("speech_act", "question")
        return canned(
            "dialogue",
            ["npc_harrowdown_maren_ostler"],
            approach,
            dialogue={"addressee_id": "npc_harrowdown_maren_ostler", "quoted_speech": None},
            addressee="person",
            **fields,
        )

    def test_asking_present_npc_for_information_writes_common_knowledge_claim(self):
        sim = self._tavern()
        _res, row = sim.run_turn(self._ask_maren("ask Maren what work there is"))

        (intel,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "intel"]
        claim = intel["claim"]
        fact = sim.world.entities["npc.harrowdown.maren_ostler"].common_knowledge[0]
        assert claim["predicate"] == "common_knowledge"
        assert claim["subject_entity_id"] == "npc.harrowdown.maren_ostler"
        assert claim["claim_text"] == fact
        assert claim["source_agent_id"] == "npc.harrowdown.maren_ostler"
        assert any(c["claim_text"] == fact for c in sim.state.claims.values())

    def test_named_subject_ask_uses_source_scope_error_path(self):
        sim = self._tavern()
        _res, row = sim.run_turn(
            self._ask_maren(
                "ask Maren about the quarry", topic_ids=["creature_harrowdown_quarryman"]
            )
        )

        (intel,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "intel"]
        claim = intel["claim"]
        assert claim["subject_entity_id"] == "creature.harrowdown.quarryman"
        assert claim["predicate"] == "common_knowledge"
        assert claim["scope"] == "local_mistaken_for_universal"
        assert "comfort-story" in claim["claim_text"]

    def test_subject_comes_from_topic_ids_not_the_wording(self):
        # The approach names the quarry, but no topic was parsed: Maren answers
        # from her own common knowledge, not about the Quarryman.
        sim = self._tavern()
        _res, row = sim.run_turn(self._ask_maren("ask Maren about the quarry"))
        (intel,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "intel"]
        assert intel["claim"]["subject_entity_id"] == "npc.harrowdown.maren_ostler"

    def test_topic_outside_the_source_scope_falls_back_to_common_knowledge(self):
        sim = self._tavern()
        _res, row = sim.run_turn(
            self._ask_maren("ask Maren about the chalk adder",
                            topic_ids=["creature_harrowdown_chalk_adder"])
        )
        (intel,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "intel"]
        assert intel["claim"]["subject_entity_id"] == "npc.harrowdown.maren_ostler"

    def test_statement_is_not_an_information_ask(self):
        sim = self._tavern()
        _res, row = sim.run_turn(
            self._ask_maren("ask Maren what work there is", speech_act="statement")
        )
        assert not [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "intel"]


class TestCoinTransactions:
    def _tavern(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _place_pc(sim, "loc.harrowdown.tavern")
        return sim

    def _coin_delta(self, row):
        (delta,) = [
            d for d in row["payload"]["state_deltas"] if d["delta_type"] == "coin"
        ]
        return delta

    def _coin_deltas(self, row):
        return [
            d for d in row["payload"]["state_deltas"] if d["delta_type"] == "coin"
        ]

    @staticmethod
    def _buy(price_key, count=1):
        return {"kind": "buy", "price_key": price_key, "count": count}

    def test_ordering_an_ale_deducts_world_price(self):
        sim = self._tavern()
        before = sim.pc["coin"]
        _res, row = sim.run_turn(
            canned(
                "social",
                ["npc_harrowdown_maren_ostler"],
                "order an ale at the bar",
                transaction=self._buy("ale_pint_copper"),
            )
        )
        delta = self._coin_delta(row)
        assert delta == {
            "delta_type": "coin",
            "entity_id": "pc",
            "amount": -sim.world.prices["ale_pint_copper"],
            "reason": "drink",
        }
        assert sim.pc["coin"] == before + delta["amount"]

    def test_giving_a_copper_deducts_one_coin(self):
        sim = self._tavern()
        before = sim.pc["coin"]
        _res, row = sim.run_turn(
            canned(
                "social",
                ["npc_harrowdown_maren_ostler"],
                "give Maren a copper penny",
                transaction={"kind": "give_coin", "price_key": None, "count": 1},
            )
        )
        delta = self._coin_delta(row)
        assert delta["amount"] == -1
        assert delta["reason"] == "coin given"
        assert sim.pc["coin"] == before - 1

    def test_transaction_spend_clamps_at_zero(self):
        sim = self._tavern()
        sim.pc["coin"] = 1
        _res, row = sim.run_turn(
            canned(
                "social",
                ["npc_harrowdown_maren_ostler"],
                "buy two ales from Maren",
                transaction=self._buy("ale_pint_copper", 2),
            )
        )
        assert self._coin_delta(row)["amount"] == -1
        assert sim.pc["coin"] == 0

    def test_targetless_buy_an_ale_deducts_world_price_and_clamps(self):
        sim = self._tavern()
        sim.pc["coin"] = sim.world.prices["ale_pint_copper"]
        _res, row = sim.run_turn(
            canned("social", [], "buy an ale", transaction=self._buy("ale_pint_copper"))
        )

        delta = self._coin_delta(row)
        assert delta == {
            "delta_type": "coin",
            "entity_id": "pc",
            "amount": -sim.world.prices["ale_pint_copper"],
            "reason": "drink",
        }
        assert sim.pc["coin"] == 0

    def test_paying_for_a_room_deducts_the_private_room_price_once(self):
        sim = self._tavern()
        _res, row = sim.run_turn(
            canned(
                "rest",
                ["loc_harrowdown_tavern"],
                "paying Maren for lodging at the Drowned Ram",
                transaction=self._buy("inn_room_night_copper"),
            )
        )

        assert self._coin_deltas(row) == [
            {
                "delta_type": "coin",
                "entity_id": "pc",
                "amount": -sim.world.prices["inn_room_night_copper"],
                "reason": "room",
            }
        ]

    def test_wording_without_a_transaction_spends_nothing(self):
        # Purchase words in the approach decide nothing; only the closed
        # transaction field moves coin.
        sim = self._tavern()
        before = sim.pc["coin"]
        for intent in (
            canned("social", ["npc_harrowdown_maren_ostler"], "buy two ales from Maren"),
            canned(
                "dialogue",
                [],
                "asking about the price of something",
                dialogue={"addressee_id": None, "quoted_speech": None},
            ),
            canned("observation", [], "examining the ale closely"),
        ):
            _res, row = sim.run_turn(intent)
            assert self._coin_deltas(row) == []
        assert sim.pc["coin"] == before

    def test_goods_the_engine_does_not_sell_spend_nothing(self):
        # The knife has a reference price but no vendor stock yet: buying it
        # must not take 60 coppers and hand over nothing.
        sim = self._tavern()
        before = sim.pc["coin"]
        _res, row = sim.run_turn(
            canned("social", [], "buy a knife", transaction=self._buy("knife_copper"))
        )
        assert self._coin_deltas(row) == []
        assert sim.pc["coin"] == before

    def test_transactions_only_move_coin_on_social_and_rest(self):
        sim = self._tavern()
        before = sim.pc["coin"]
        _res, row = sim.run_turn(
            canned("physical", [], "slap a coin down", transaction=self._buy("ale_pint_copper"))
        )
        assert self._coin_deltas(row) == []
        assert sim.pc["coin"] == before


class TestKnownSafety:
    def test_dice_modifiers_never_leak_numbers_beyond_band(self, sim):
        """Modifier labels are aptitude words; values band-derived (-1..+1)."""
        for entry in load_script():
            _res, row = sim.run_turn(entry["intent"])
            dice = row["payload"]["dice"]
            if dice:
                for modifier in dice["modifiers"]:
                    assert modifier["label"] in (
                        "might", "finesse", "wits", "will", "presence", "lore"
                    )
                    assert -1 <= modifier["value"] <= 1

    def test_true_sheets_never_enter_the_log(self, sim):
        """No stored payload may contain an authored aptitude mapping or
        threat band (true sheets are config, not canon — design law)."""
        import json as _json

        for entry in load_script():
            sim.run_turn(entry["intent"])
        blob = _json.dumps([r["payload"] for r in sim.rows if r["stream_id"] != "character:pc"
                            or r["event_type"] != "character_created"])
        assert "threat_band" not in blob
        for entity in sim.world.entities.values():
            # The full aptitude dict of any authored NPC must not appear.
            assert _json.dumps(entity.true_sheet.aptitudes) not in blob


def _wound(sim, entity_id: str, amount: int) -> None:
    """Fold a stored NPC hp delta the way a committed outcome would."""
    from everquill_engine.events import EventSpec, EventType

    sim.apply_specs([
        EventSpec(
            stream_id="character:pc",
            event_type=EventType.OUTCOME_RESOLVED,
            world_time=sim.state.world["world_time"],
            payload={"state_deltas": [{
                "delta_type": "hp", "entity_id": entity_id,
                "amount": -amount, "cause": "test wound",
            }]},
        )
    ])


class TestStatHintIsAdvisory:
    """The LLM's stat_hint may never referee."""

    def test_different_hints_identical_tier_rolls_deltas(self):
        outcomes = []
        for hint in (None, "might", "wits", "presence", "lore"):
            sim = Sim(seed=42)
            _res, row = sim.run_turn(
                canned("physical", ["npc_dev_hedda"], "arm-wrestle", stat_hint=hint)
            )
            p = row["payload"]
            outcomes.append((
                p["tier_resolved"], p["risk_label_shown"], p["outcome_tier"],
                p["dice"], p["state_deltas"],
            ))
        assert all(o == outcomes[0] for o in outcomes)

    def test_hint_survives_in_intent_payload_and_meta_flags_mismatch(self, sim):
        res, _row = sim.run_turn(
            canned("physical", ["npc_dev_hedda"], "arm-wrestle", stat_hint="wits")
        )
        intent_row = sim.rows[-len(res.events)]
        assert intent_row["event_type"] == "intent_parsed"
        assert intent_row["payload"]["intent"]["stat_hint"] == "wits"  # audit record
        meta = res.events[res.outcome_event_index].meta
        assert meta["stat_selected"] == "might"  # engine-owned selection
        assert meta["stat_hint"] == "wits"
        assert meta["stat_hint_mismatch"] is True

    def test_matching_hint_is_not_a_mismatch(self, sim):
        res, _row = sim.run_turn(
            canned("physical", ["npc_dev_hedda"], "arm-wrestle", stat_hint="might")
        )
        meta = res.events[res.outcome_event_index].meta
        assert meta["stat_hint_mismatch"] is False

    def test_train_trains_the_engine_selected_aptitude(self, sim):
        """The trained aptitude is DEFAULT_STAT_FOR_ACTION['train'] (will),
        whatever the hint says — hints select nothing."""
        _res, row = sim.run_turn(canned("train", approach="drill", stat_hint="might"))
        (timer_delta,) = [
            d for d in row["payload"]["state_deltas"] if d["delta_type"] == "timer_started"
        ]
        timer = sim.state.timers[timer_delta["timer_id"]]
        assert timer["payload"]["aptitude"] == "will"


class TestTypedIntentBoundary:
    """The resolver boundary is the closed typed model."""

    def test_unknown_key_rejected_before_any_canon(self, sim):
        before = len(sim.rows)
        with pytest.raises(ResolverError, match="unknown keys"):
            sim.run_turn({**canned("physical", ["npc_dev_hedda"]), "sneaky": 1})
        assert len(sim.rows) == before

    def test_duplicate_targets_rejected(self, sim):
        with pytest.raises(ResolverError, match="duplicate target"):
            sim.run_turn(canned("physical", ["npc_dev_hedda", "npc_dev_hedda"]))

    def test_malformed_dialogue_rejected(self, sim):
        intent = canned("dialogue", ["npc_dev_hedda"])
        intent["dialogue"] = {"addressee_id": "npc_dev_hedda"}  # missing quoted_speech
        with pytest.raises(ResolverError, match="dialogue"):
            sim.run_turn(intent)


def _span(text, amount=None, unit=None):
    return {"mode": "explicit", "text": text, "until": None, "amount": amount, "unit": unit}


def _until(text, until):
    return {"mode": "until_condition", "text": text, "until": until, "amount": None, "unit": None}


class TestDurationBinding:
    """Duration_hint consumed deterministically from its closed fields, or
    rejected."""

    def _train(self, sim, duration_hint):
        intent = canned("train", approach="drill in the yard")
        intent["duration_hint"] = duration_hint
        return sim.run_turn(intent)

    def test_explicit_hours_set_the_block_length(self, sim):
        _res, row = self._train(sim, _span("for three hours", amount=3, unit="hour"))
        (timer_delta,) = [
            d for d in row["payload"]["state_deltas"] if d["delta_type"] == "timer_started"
        ]
        # commit at t=0 costs 5; block = 180 → due 185.
        assert timer_delta["due_world_time"] == "185"

    def test_until_nightfall_binds_to_the_block_table(self, sim):
        _res, row = self._train(sim, _until("until nightfall", "dusk"))
        (timer_delta,) = [
            d for d in row["payload"]["state_deltas"] if d["delta_type"] == "timer_started"
        ]
        # World minute 0 = Day 1 06:00; block starts at 5; next 18:00 is
        # world minute 720 → due 720 (the documented block table).
        assert timer_delta["due_world_time"] == "720"

    def test_no_hint_keeps_the_default_block(self, sim):
        _res, row = self._train(sim, None)
        (timer_delta,) = [
            d for d in row["payload"]["state_deltas"] if d["delta_type"] == "timer_started"
        ]
        assert timer_delta["due_world_time"] == "485"  # 5 + 480 default

    def test_unsupported_condition_rejected_with_clear_error(self, sim):
        before = len(sim.rows)
        with pytest.raises(ResolverError, match="caravan"):
            self._train(sim, _until("until the caravan leaves", None))
        assert len(sim.rows) == before

    def test_unsupported_explicit_form_rejected(self, sim):
        with pytest.raises(ResolverError, match="an amount and a unit"):
            self._train(sim, _span("for a good while"))

    def test_rest_span_prices_the_rest(self, sim):
        intent = canned("rest", approach="doze by the fire")
        intent["duration_hint"] = _span("for two hours", amount=2, unit="hour")
        res, row = sim.run_turn(intent)
        assert row["payload"]["world_time_cost"] == 120
        # Short rest: no inn coin, recovery 1 hp per 2h (here: capped by wounds).
        kinds = {d["delta_type"] for d in row["payload"]["state_deltas"]}
        assert "coin" not in kinds

    def test_occupied_time_floor_for_other_shapes(self, sim):
        intent = canned("observation", ["npc_dev_hedda"], "watch her all evening", "wits")
        intent["duration_hint"] = _span("for two hours", amount=2, unit="hour")
        _res, row = sim.run_turn(intent)
        assert row["payload"]["world_time_cost"] == 120  # max(5, 120)


class TestRollSiteStreams:
    """Per-action-type outcome streams; hopeless flavor is its
    own site. Pin change from the pooled ('character:pc','action') stream
    is documented in tests/golden/roll_sites.json."""

    def test_action_outcomes_draw_from_per_type_streams(self, sim):
        _res, row = sim.run_turn(canned("physical", ["npc_dev_hedda"], "arm-wrestle"))
        assert row["rng"]["stream"] == ["character:pc", "action:physical"]
        _res, row = sim.run_turn(canned("social", ["npc_dev_hedda"], "win her over"))
        assert row["rng"]["stream"] == ["character:pc", "action:social"]

    def test_hopeless_draws_from_the_flavor_site(self, sim):
        res, row = sim.run_turn(canned("physical", ["npc_dev_torvald"], "challenge him"))
        assert res.tier is PlausibilityTier.HOPELESS
        assert row["rng"]["stream"] == ["character:pc", "hopeless_flavor"]

    def test_streams_advance_independently(self, sim):
        sim.run_turn(canned("physical", ["npc_dev_hedda"], "arm-wrestle"))
        sim.run_turn(canned("social", ["npc_dev_hedda"], "win her over"))
        _res, row = sim.run_turn(canned("physical", ["npc_dev_hedda"], "again"))
        assert row["rng"]["index"] == 1  # physical's own counter, untouched by social


class TestDispatchedTargets:
    """Decision-5 cluster: physical vs a dispatched target is a trivial
    no-op with zero deltas and the explicit Chronicle line."""

    def _dispatch(self, sim, entity_id):
        sim.state.entities[entity_id]["hp"] = 0

    def test_physical_vs_dispatched_is_trivial_zero_deltas(self, sim):
        self._dispatch(sim, "npc.dev.torvald")
        res, row = sim.run_turn(
            canned("physical", ["npc_dev_torvald"], "kick the fallen drillmaster")
        )
        assert res.tier is PlausibilityTier.TRIVIAL
        payload = row["payload"]
        assert payload["dice"] is None
        assert payload["state_deltas"] == []  # zero deltas — nothing happened
        assert "[Already dispatched.]" in res.summary

    def test_never_rolls_against_a_corpse_even_for_weak_actors(self, sim):
        # Force the weakest possible actor: without the rule, effective
        # threat 1 vs might could still land ROUTINE and roll dice.
        sim.pc["aptitudes"]["might"] = 2
        self._dispatch(sim, "npc.dev.hedda")
        res, row = sim.run_turn(canned("physical", ["npc_dev_hedda"], "strike her"))
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["dice"] is None
        assert row["payload"]["state_deltas"] == []

    def test_mixed_targets_fight_only_the_living(self, sim):
        self._dispatch(sim, "npc.dev.torvald")
        # Torvald (threat 20) dispatched + Hedda (threat 5) alive → the
        # fight prices off Hedda: ROUTINE, not HOPELESS.
        res, _row = sim.run_turn(
            canned("physical", ["npc_dev_torvald", "npc_dev_hedda"], "wade in")
        )
        assert res.tier is PlausibilityTier.ROUTINE


def _danger_sim(*, seed: int, might: int = 10, hp: int = 14) -> Sim:
    sim = Sim(seed=seed, world_path=DANGER_WORLD)
    sim.pc["aptitudes"]["might"] = might
    sim.pc["hp"] = hp
    sim.pc["hp_max"] = 14
    return sim


def _actor_hp_deltas(row):
    return [
        d for d in row["payload"]["state_deltas"]
        if d["delta_type"] == "hp" and d["entity_id"] == "pc"
    ]


class TestDangerBites:
    def test_desperate_strong_hit_wounds_actor_with_counterattack(self):
        sim = _danger_sim(seed=9)
        res, row = sim.run_turn(
            canned("physical", ["creature_test_wyvern"], "punch the apex wyvern", "might")
        )

        assert res.tier is PlausibilityTier.DESPERATE
        assert row["payload"]["outcome_tier"] == "strong_hit"
        actor_harm = _actor_hp_deltas(row)
        assert actor_harm == [
            {"delta_type": "hp", "entity_id": "pc", "amount": -2,
             "cause": "mauled by Apex Wyvern"}
        ]

        public = outcome_public(outcome_contract(row))
        assert any(
            d == {"delta_type": "wound_transition", "entity_id": "pc", "effect": "wounded"}
            for d in public["state_deltas"]
        )

    def test_desperate_and_hopeless_harm_never_drop_pc_below_one_hp(self):
        desperate = _danger_sim(seed=4, hp=2)
        res, _row = desperate.run_turn(
            canned("physical", ["creature_test_wyvern"], "stand and trade", "might")
        )
        assert res.tier is PlausibilityTier.DESPERATE
        assert desperate.pc["hp"] == 1

        hopeless = _danger_sim(seed=1, hp=2)
        res, _row = hopeless.run_turn(
            canned("physical", ["creature_test_dragon"], "swing anyway", "might")
        )
        assert res.tier is PlausibilityTier.HOPELESS
        assert hopeless.pc["hp"] == 1

    def test_risky_physical_fight_does_not_counterattack(self):
        sim = _danger_sim(seed=1)
        res, row = sim.run_turn(
            canned("physical", ["creature_test_fox"], "drive off the fox", "might")
        )

        assert res.tier is PlausibilityTier.RISKY
        assert row["payload"]["outcome_tier"] == "strong_hit"
        assert not _actor_hp_deltas(row)
        assert not any(
            d.get("delta_type") == "hp" and d.get("cause", "").startswith("mauled by")
            for d in row["payload"]["state_deltas"]
        )

    def test_hopeless_spared_keeps_zero_harm_but_surfaces_a_mark(self):
        sim = _danger_sim(seed=2)
        res, row = sim.run_turn(
            canned("physical", ["creature_test_dragon"], "test the dragon", "might")
        )

        assert res.tier is PlausibilityTier.HOPELESS
        assert row["payload"]["hopeless_flavor"] == "spared"
        assert _actor_hp_deltas(row) == []
        public_flags = [
            d for d in outcome_public(outcome_contract(row))["state_deltas"]
            if d["delta_type"] == "flag"
        ]
        assert public_flags == [
            {"delta_type": "flag", "entity_id": "pc",
             "flag_key": "scar_turn_1", "value": "spared by Elder Dragon"}
        ]
        assert self_view(sim.state, "pc").marks == ("spared by Elder Dragon",)

    def test_hopeless_punishing_and_catastrophic_harm_ladder_is_unchanged(self):
        punishing = _danger_sim(seed=4)
        _res, row = punishing.run_turn(
            canned("physical", ["creature_test_dragon"], "press the dragon", "might")
        )
        assert row["payload"]["hopeless_flavor"] == "punishing"
        assert _actor_hp_deltas(row) == [
            {"delta_type": "hp", "entity_id": "pc", "amount": -3,
             "cause": "mauled by Elder Dragon"}
        ]
        assert not any(
            d.get("delta_type") == "flag" and d.get("flag_key", "").startswith("scar_")
            for d in row["payload"]["state_deltas"]
        )

        catastrophic = _danger_sim(seed=1)
        _res, row = catastrophic.run_turn(
            canned("physical", ["creature_test_dragon"], "press the dragon", "might")
        )
        assert row["payload"]["hopeless_flavor"] == "catastrophic"
        assert _actor_hp_deltas(row) == [
            {"delta_type": "hp", "entity_id": "pc", "amount": -6,
             "cause": "broken against Elder Dragon"}
        ]
        assert self_view(catastrophic.state, "pc").marks == ("marked by Elder Dragon",)

    def test_solo_desperate_and_hopeless_confrontations_write_deeds(self):
        desperate = _danger_sim(seed=9)
        _res, row = desperate.run_turn(
            canned("physical", ["creature_test_wyvern"], "punch the apex wyvern", "might")
        )
        (deed,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "deed"]
        assert deed["witness_ids"] == []
        assert deed["description"] == "the Quill-touched bested Apex Wyvern"

        hopeless = _danger_sim(seed=2)
        _res, row = hopeless.run_turn(
            canned("physical", ["creature_test_dragon"], "challenge the dragon", "might")
        )
        (deed,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "deed"]
        assert deed["witness_ids"] == []
        assert deed["description"] == "the Quill-touched challenged Elder Dragon and was broken"

    def test_low_band_solo_scuffle_still_writes_no_deed(self):
        sim = _danger_sim(seed=1)
        _res, row = sim.run_turn(
            canned("physical", ["creature_test_fox"], "drive off the fox", "might")
        )
        assert not any(d["delta_type"] == "deed" for d in row["payload"]["state_deltas"])

    def test_danger_deltas_are_replay_stable(self):
        first = _danger_sim(seed=9).run_turn(
            canned("physical", ["creature_test_wyvern"], "punch the apex wyvern", "might")
        )[1]["payload"]["state_deltas"]
        second = _danger_sim(seed=9).run_turn(
            canned("physical", ["creature_test_wyvern"], "punch the apex wyvern", "might")
        )[1]["payload"]["state_deltas"]
        assert first == second


class TestWoundedEntityState:
    """Difficulty reads authored truth + CURRENT entity_state."""

    def test_genesis_seeds_entity_state_for_damageable_entities(self, sim):
        assert set(sim.state.entities) == {
            "npc.dev.hedda", "npc.dev.sorrel", "npc.dev.torvald",
        }
        torvald = sim.state.entities["npc.dev.torvald"]
        assert torvald["hp"] == torvald["hp_max"] == 4 + 16  # 4 + might, stored fact
        assert "loc.dev.tavern" == torvald["location_id"]

    def test_npc_damage_persists_and_changes_the_fight(self, sim):
        res, _ = sim.run_turn(canned("physical", ["npc_dev_torvald"], stat_hint="might"))
        assert res.tier is PlausibilityTier.HOPELESS  # threat 20 vs might 5
        _wound(sim, "npc.dev.torvald", 10)
        assert sim.state.entities["npc.dev.torvald"]["hp"] == 10  # persisted
        res2, row2 = sim.run_turn(canned("physical", ["npc_dev_torvald"], stat_hint="might"))
        # effective threat ceil(20 * 10/20) = 10 -> gap 5 -> DESPERATE.
        assert res2.tier is PlausibilityTier.DESPERATE
        assert row2["payload"]["risk_label_shown"] == "dire"

    def test_observation_reads_current_threat_not_authored(self, sim):
        _wound(sim, "npc.dev.torvald", 10)
        _res, row = sim.run_turn(
            canned("observation", ["npc_dev_torvald"], "size him up", stat_hint="wits")
        )
        (claim,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "intel"]
        assert claim["claim"]["value_text"] in ("DESPERATE", "RISKY")  # wounded read
        assert claim["claim"]["value_text"] != "HOPELESS"
        assert claim["claim"]["predicate"] == "threat_assessed"  # claim v2 typed key


class TestDispatchedNpcs:
    """A body is not a person: no answers, no partner, no witness, no deal.
    It can still be looked at (audit 2026-10-24, codex F4)."""

    def _tavern_with_maren_down(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _place_pc(sim, "loc.harrowdown.tavern")
        row = sim.state.entities.setdefault("npc.harrowdown.maren_ostler", {})
        row["hp"] = 0
        row.setdefault("hp_max", 10)
        return sim

    def _ask(self, **fields):
        return canned(
            "dialogue",
            ["npc_harrowdown_maren_ostler"],
            "ask her about the quarry",
            dialogue={"addressee_id": "npc_harrowdown_maren_ostler", "quoted_speech": None},
            addressee="person",
            **fields,
        )

    def test_a_dispatched_npc_answers_nothing_and_is_no_partner(self):
        sim = self._tavern_with_maren_down()
        _res, row = sim.run_turn(
            self._ask(speech_act="question", topic_ids=["creature_harrowdown_quarryman"])
        )
        kinds = [d["delta_type"] for d in row["payload"]["state_deltas"]]
        assert "intel" not in kinds
        assert not sim.pc["flags"].get(CONVERSATION_PARTNER_FLAG)

    def test_no_name_exchange_with_the_dead(self):
        sim = self._tavern_with_maren_down()
        sim.run_turn(self._ask(speech_act="introduction"))
        assert not any(k.startswith("knows_name_") for k in sim.pc["flags"])

    def test_the_dead_witness_nothing(self):
        sim = self._tavern_with_maren_down()
        _res, row = sim.run_turn(canned("physical", ["creature_harrowdown_ditch_slime"], "stomp"))
        deeds = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "deed"]
        assert deeds, "stomping the slime should record a deed"
        for deed in deeds:
            assert "npc.harrowdown.maren_ostler" not in deed["witness_ids"]
            assert "npc.harrowdown.jorun_pike" in deed["witness_ids"]  # the living still see

    def test_social_with_the_dead_is_trivial_and_says_so(self):
        sim = self._tavern_with_maren_down()
        res, row = sim.run_turn(
            canned("social", ["npc_harrowdown_maren_ostler"], "charm her", "presence")
        )
        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["dice"] is None
        assert "No answer. They are past hearing." in res.summary

    def test_a_body_can_still_be_looked_at(self):
        sim = self._tavern_with_maren_down()
        res, _row = sim.run_turn(
            canned("observation", ["npc_harrowdown_maren_ostler"], "look her over", "wits")
        )
        assert res is not None


class TestSellersWhereYouStand:
    """A purchase needs a seller where you stand (audit 2026-10-24, claude #9)."""

    def test_no_pint_on_market_row(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _place_pc(sim, "loc.harrowdown.market_row")
        before = sim.pc["coin"]
        _res, row = sim.run_turn(
            canned(
                "social", [], "buy an ale",
                transaction={"kind": "buy", "price_key": "ale_pint_copper", "count": 1},
            )
        )
        assert not [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "coin"]
        assert sim.pc["coin"] == before

    def test_the_prices_list_offers_only_what_is_sold_here(self):
        from everquill_engine.world import sold_here

        sim = Sim(seed=42, world_path=HARROWDOWN)
        assert "ale_pint_copper" in sold_here(sim.world, "loc.harrowdown.tavern")
        assert sold_here(sim.world, "loc.harrowdown.south_road") == ()
