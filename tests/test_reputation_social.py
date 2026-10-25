"""Social resolution v2.

Reputation you earned EASES the next social contest, and social outcomes MOVE
reputation — the compounding loop that turns "the NPC is a wall" into "the NPC
warms because you earned it". The read side (difficulty easing) is proven pure
and deterministic here; the write side (a social outcome moving disposition,
folded into state) is proven through the Sim, which now threads reputation
exactly as the live beat path does.
"""

from __future__ import annotations

from everquill_engine.ladder import PlausibilityTier
from everquill_engine.resolver import (
    decide_tier,
)
from everquill_engine.resolver.common import (
    _difficulty_for,
    _reputation_delta,
    _settlement_of,
    _social_standing_modifier,
)
from everquill_engine.views import self_view
from tests.harness import Sim

#: bands easy -> hard, for "no harder than" comparisons
_BAND_ORDER = [
    PlausibilityTier.TRIVIAL,
    PlausibilityTier.ROUTINE,
    PlausibilityTier.RISKY,
    PlausibilityTier.DESPERATE,
    PlausibilityTier.HOPELESS,
    PlausibilityTier.SEALED,
    PlausibilityTier.IMPOSSIBLE,
]


def _row(actor: str, scope: str, subject: str, value: int) -> dict:
    return {f"{actor}::{scope}::{subject}": {"value": value}}


def _rep(*rows: dict) -> dict:
    out: dict = {}
    for row in rows:
        out.update(row)
    return out


class _Target:
    """Minimal stand-in for a world entity in _difficulty_for (social reads
    only .id and .true_sheet.aptitudes['will'])."""

    def __init__(self, eid: str, will: int) -> None:
        self.id = eid
        self.true_sheet = type("TS", (), {"aptitudes": {"will": will}})()


def _social_intent(target: str, approach: str) -> dict:
    return {
        "action_type": "social",
        "target_entity_ids": [target],
        "approach": approach,
        "stat_hint": None,
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


class TestSettlementOf:
    def test_strips_sub_location(self):
        assert _settlement_of("loc.harrowdown.tavern") == "loc.harrowdown"

    def test_bare_town_passes_through(self):
        assert _settlement_of("loc.harrowdown") == "loc.harrowdown"

    def test_none_is_empty(self):
        assert _settlement_of(None) == ""


class TestStandingModifier:
    def test_disposition_plus_town_standing(self):
        rep = _rep(_row("pc", "disposition", "npc_j", 2), _row("pc", "standing", "loc.h", 1))
        assert _social_standing_modifier(rep, "pc", ["npc_j"], "loc.h") == 3

    def test_least_warm_target_sets_the_floor(self):
        # The will-max difficulty rule picks the hardest target; disposition
        # must match it — the coldest addressee dominates.
        rep = _rep(_row("pc", "disposition", "warm", 3), _row("pc", "disposition", "cold", -1))
        assert _social_standing_modifier(rep, "pc", ["warm", "cold"], "") == -1

    def test_clamped_to_bound(self):
        rep = _rep(_row("pc", "disposition", "npc_j", 3), _row("pc", "standing", "loc.h", 5))
        assert _social_standing_modifier(rep, "pc", ["npc_j"], "loc.h") == 4  # ±4 bound

    def test_absent_reputation_is_neutral(self):
        assert _social_standing_modifier(None, "pc", ["npc_j"], "loc.h") == 0


class TestReputationEasesDifficulty:
    def test_warm_npc_lowers_the_guard(self):
        tgt = _Target("npc_j", will=9)
        base = _difficulty_for("social", [tgt], None)
        eased = _difficulty_for(
            "social", [tgt], None,
            reputation=_rep(_row("pc", "disposition", "npc_j", 2)),
            actor_id="pc", settlement_id="loc.h",
        )
        assert base == 9
        assert eased == 7  # 9 - 2: reputation you earned changes the odds

    def test_bad_name_stiffens_the_guard(self):
        tgt = _Target("npc_j", will=7)
        stiff = _difficulty_for(
            "social", [tgt], None,
            reputation=_rep(_row("pc", "disposition", "npc_j", -2)),
            actor_id="pc", settlement_id="loc.h",
        )
        assert stiff == 9  # 7 - (-2): a rebuff makes the next ask harder


class TestReputationDeltaClamp:
    def test_moves_toward_the_band(self):
        assert _reputation_delta({}, "pc", "disposition", "npc_j", 2, (-3, 3))["amount"] == 2

    def test_clamps_at_the_ceiling(self):
        rep = _rep(_row("pc", "disposition", "npc_j", 2))
        assert _reputation_delta(rep, "pc", "disposition", "npc_j", 2, (-3, 3))["amount"] == 1

    def test_no_op_at_the_bound_returns_none(self):
        rep = _rep(_row("pc", "disposition", "npc_j", 3))
        assert _reputation_delta(rep, "pc", "disposition", "npc_j", 2, (-3, 3)) is None


class TestSocialLoopThroughTheSim:
    def test_a_social_outcome_moves_and_folds_disposition(self):
        sim = Sim(seed=42)
        _res, row = sim.run_turn(_social_intent("npc_dev_hedda", "win her over"))
        deltas = row["payload"]["state_deltas"]
        disp = [
            d for d in deltas
            if d.get("delta_type") == "reputation" and d["scope"] == "disposition"
        ]
        assert disp, "a social contest must move disposition"
        d = disp[0]
        assert d["subject_id"] == "npc.dev.hedda"
        tier = row["payload"].get("outcome_tier")
        assert (d["amount"] < 0) if tier == "miss" else (d["amount"] > 0)
        # …and it folded into the running projection the next turn will read.
        folded = sim.state.reputation.get("pc::disposition::npc.dev.hedda")
        assert folded is not None and folded["value"] == d["amount"]


class TestTheJorunLoopEndToEnd:
    """The loop that failed the playtest now works and
    compounds — through the real decide_tier, real world content, real fold."""

    def test_a_social_outcome_shows_up_in_the_self_view(self):
        sim = Sim(seed=42)
        sim.run_turn(_social_intent("npc_dev_hedda", "win her over"))
        me = self_view(sim.state, "pc")
        assert me is not None
        hedda = [d for d in me.dispositions if d.subject_id == "npc.dev.hedda"]
        assert hedda, "a social outcome must surface in the Self view's standings"
        assert hedda[0].descriptor  # a legible word, e.g. 'warm to you' / 'wary of you'

    def test_warm_disposition_eases_a_real_contest(self):
        sim = Sim(seed=42)
        intent = _social_intent("npc_dev_hedda", "press her for what she knows")
        common = dict(
            intent=intent, actor=sim.pc, world=sim.world,
            manifest=sim.state.manifest, world_time=sim.state.world["world_time"],
        )
        cold = decide_tier(**common, reputation={})
        warm = decide_tier(**common, reputation={
            "pc::disposition::npc.dev.hedda": {
                "actor_id": "pc", "scope": "disposition",
                "subject_id": "npc.dev.hedda", "value": 3, "last_event_id": 1,
            }
        })
        # Reputation you earned lowers the guard: the warm contest is NEVER
        # harder than the cold one (and strictly easier whenever it crosses a
        # band — the pure difficulty test pins the arithmetic).
        assert _BAND_ORDER.index(warm.tier) <= _BAND_ORDER.index(cold.tier)
