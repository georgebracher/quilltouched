"""Two-phase commit beat, pure half: the engine-owned confirmation table
and assess/resolve tier agreement (interface decision 2)."""

from __future__ import annotations

import pytest

from everquill_engine.beat import PENDING_CONFIRMATION_TTL_MINUTES, canonical_intent_hash
from everquill_engine.intent import parse_intent
from everquill_engine.ladder import PlausibilityTier, RiskLabel
from everquill_engine.resolver import (
    CONFIRMATION_REQUIRED_FOR_RISK,
    TierDecision,
    confirmation_required,
    decide_tier,
)
from everquill_engine.world import Law
from tests.harness import Sim, load_script


def canned(action_type, targets=(), approach="do the thing", stat_hint=None, **fields):
    intent = {
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
    intent.update(fields)
    return intent


def _decision(sim, intent) -> TierDecision:
    return decide_tier(
        intent=intent,
        actor=sim.pc,
        world=sim.world,
        manifest=sim.state.manifest,
        world_time=sim.state.world["world_time"],
        entity_states=sim.state.entities,
    )


def _fake_decision(tier, risk, law=None) -> TierDecision:
    return TierDecision(
        intent=parse_intent(canned("physical")),
        action="physical",
        targets=(),
        law=law,
        law_notes=(),
        stat_name="might",
        tier=tier,
        risk_label=risk,
        time_cost=10,
        block_minutes=None,
        move_to=None,
        already_dispatched=False,
    )


class TestConfirmationTable:
    def test_ttl_is_ten_world_minutes(self):
        assert PENDING_CONFIRMATION_TTL_MINUTES == 10

    def test_risk_table_is_dire_and_up(self):
        assert CONFIRMATION_REQUIRED_FOR_RISK == {
            RiskLabel.GUARDED: False,
            RiskLabel.PERILOUS: False,
            RiskLabel.DIRE: True,
            RiskLabel.DESPERATE: True,
            RiskLabel.SUICIDAL: True,
        }

    @pytest.mark.parametrize("tier,risk,expected", [
        (PlausibilityTier.TRIVIAL, None, False),
        (PlausibilityTier.ROUTINE, RiskLabel.GUARDED, False),
        (PlausibilityTier.RISKY, RiskLabel.PERILOUS, False),
        (PlausibilityTier.DESPERATE, RiskLabel.DIRE, True),
        (PlausibilityTier.HOPELESS, RiskLabel.SUICIDAL, True),
        (PlausibilityTier.SEALED, None, True),
        (PlausibilityTier.IMPOSSIBLE, None, False),
    ])
    def test_tier_to_confirmation(self, tier, risk, expected):
        assert confirmation_required(_fake_decision(tier, risk)) is expected

    def test_irreversible_law_forces_the_beat(self):
        law = Law(
            law_id="law.burn_it", name="Burn It", tier="impossible",
            invoke_phrases=("burn",), irreversible=True,
        )
        decision = _fake_decision(PlausibilityTier.IMPOSSIBLE, None, law=law)
        assert confirmation_required(decision) is True

    def test_engine_decisions_from_real_state(self):
        sim = Sim(seed=42)
        # ROUTINE vs Hedda (threat 5, might 5) → auto-commit.
        assert confirmation_required(
            _decision(sim, canned("physical", ["npc_dev_hedda"]))
        ) is False
        # HOPELESS vs Torvald (threat 20) → Suicidal → beat.
        assert confirmation_required(
            _decision(sim, canned("physical", ["npc_dev_torvald"]))
        ) is True
        # Sealed unmet → beat.
        assert confirmation_required(
            _decision(sim, canned(
                "social",
                approach="swear a binding hearth-oath",
                invoked_law_ids=["law_hearth_oath"],
            ))
        ) is True
        # Sealed with components met resolves DESPERATE → Dire → still a beat.
        sim.pc["flags"]["hearth_token"] = True
        sim.pc["flags"]["witness_blessing"] = True
        met = _decision(sim, canned(
                "social",
                approach="swear a binding hearth-oath",
                invoked_law_ids=["law_hearth_oath"],
            ))
        assert met.tier is PlausibilityTier.DESPERATE
        assert confirmation_required(met) is True
        # Impossible → auto (the world reacts to the attempt).
        assert confirmation_required(
            _decision(
                sim,
                canned(
                    "physical",
                    approach="levitate off the floor",
                    invoked_law_ids=["law_unwritten_flight"],
                ),
            )
        ) is False


class TestAssessResolveAgreement:
    def test_decide_tier_matches_resolution_for_the_whole_script(self):
        """assess and resolve are the same decision — for every scripted
        intent, decide_tier's tier/risk equal what resolve_intent then
        commits (they share the TierDecision code path; this pins it)."""
        sim = Sim(seed=42)
        for entry in load_script():
            decision = _decision(sim, entry["intent"])
            resolution, row = sim.run_turn(entry["intent"])
            assert resolution.tier is decision.tier
            payload = row["payload"]
            if payload["dice"] is not None:
                assert payload["risk_label_shown"] == decision.risk_label.name.lower()

    def test_assess_never_rolls_dice(self):
        sim = Sim(seed=42)
        before = dict(sim.state.world["rng_counters"])
        _decision(sim, canned("physical", ["npc_dev_torvald"]))
        _decision(sim, canned("physical", ["npc_dev_hedda"]))
        assert sim.state.world["rng_counters"] == before


class TestCanonicalIntentHash:
    """The binding key is a canonical hash of the parsed intent."""

    def test_same_intent_hashes_identically_regardless_of_key_order(self):
        a = canned("physical", ["npc_dev_hedda"], "arm-wrestle")
        b = {k: a[k] for k in reversed(list(a))}  # same content, reversed key order
        assert canonical_intent_hash(a) == canonical_intent_hash(b)

    def test_different_intent_hashes_differently(self):
        a = canned("physical", ["npc_dev_hedda"], "arm-wrestle")
        b = canned("social", ["npc_dev_hedda"], "sweet-talk")
        assert canonical_intent_hash(a) != canonical_intent_hash(b)
