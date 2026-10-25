"""The knowledge system (engine half).

Research resolves against a source's ``knowledge_scope``: success reveals
appraisal FIELDS (never numbers), a bad roll writes the source's confidently
WRONG answer at HIGH strength, an out-of-scope subject yields a LEAD. A known
``weak_point`` claim is a target-specific modifier that turns a HOPELESS
physical fight into a DESPERATE option. Plus the status-strip active-timers
surface. DB half (narrate_outcome) skips cleanly without DATABASE_URL.
"""

from __future__ import annotations

import types

import pytest

from everquill_engine.claims import BASE_EVIDENCE_WEIGHT
from everquill_engine.ladder import OutcomeTier, PlausibilityTier
from everquill_engine.resolver import (
    UNADDRESSABLE_TARGET,
    WEAK_POINT_ROLL_BONUS,
    ResolverError,
    decide_tier,
    resolve_intent,
)
from everquill_engine.resolver.research import _governing_source, _research_in_scope, _research_lead
from everquill_engine.views import load_known_state
from everquill_engine.world import (
    KnowledgeScope,
    ScopeReveal,
    ScopeSubject,
    WorldContentError,
    load_world,
)
from tests.harness import REPO_ROOT, Sim

SCOPE_WORLD = REPO_ROOT / "tests" / "fixtures" / "scope-world.yaml"
WYRM = "creature.test.wyrm"


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


def _actor(location_id, *, might=5, flags=None):
    return {
        "entity_id": "pc",
        "location_id": location_id,
        "flags": flags or {},
        "aptitudes": {"might": might},
    }


# --------------------------------------------------------------------------- #
# Loader: the knowledge_scope field shape (what content authors write to)             #
# --------------------------------------------------------------------------- #


class TestScopeLoader:
    def test_scope_parses_into_the_documented_shape(self):
        world = load_world(SCOPE_WORLD)
        archivist = world.entities["npc.test.archivist"]
        scope = archivist.knowledge_scope
        assert scope is not None
        assert scope.max_appraisal_tier == 2
        subject = scope.subject(WYRM)
        assert subject is not None
        assert [r.tier for r in subject.reveals] == [0, 1, 2]
        assert subject.reveals[2].predicate == "weak_point"
        assert subject.error.distortion == "ballad_inflation"
        assert scope.lead.to == "loc.test.far_province"
        assert [s.id for s in world.sources_at("loc.test.archive")] == ["npc.test.archivist"]

    def test_world_without_scope_loads_with_none(self):
        # dev-fixture authors no scopes: absence is tolerated (every entity None).
        world = load_world(REPO_ROOT / "content" / "world" / "dev-fixture.yaml")
        assert all(e.knowledge_scope is None for e in world.entities.values())

    def test_harrowdown_has_inlined_knowledge_scopes(self):
        # The authored scopes were inlined into harrowdown.yaml (the
        # sidecar is gone). The seed region must load with real sources.
        world = load_world(REPO_ROOT / "content" / "world" / "harrowdown.yaml")
        sources = [e for e in world.entities.values() if e.knowledge_scope is not None]
        assert len(sources) >= 4  # guild board, Maren, Sister Odile, Toller
        assert all(s.knowledge_scope.subjects for s in sources)

    def test_reveal_with_unknown_predicate_is_rejected_with_file_line(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "locations:\n"
            "  - {id: loc.test.a, name: A, type: guild_hall, region: test}\n"
            "entities:\n"
            "  - id: npc.test.s\n"
            "    name: S\n"
            "    kind: npc\n"
            "    location: loc.test.a\n"
            "    true_sheet:\n"
            "      aptitudes: {might: 3, finesse: 3, wits: 3, will: 3, presence: 3, lore: 3}\n"
            "      threat_band: 1\n"
            "    knowledge_scope:\n"
            "      subjects:\n"
            "        - subject: creature.test.x\n"
            "          reveals:\n"
            "            - {tier: 0, predicate: vibes, value_text: v, claim_text: c}\n",
            encoding="utf-8",
        )
        with pytest.raises(WorldContentError) as exc:
            load_world(bad)
        assert "not a closed claim predicate" in str(exc.value)
        assert str(bad) in str(exc.value)


# --------------------------------------------------------------------------- #
# Source selection (roadmap §3.6)                                             #
# --------------------------------------------------------------------------- #


class TestGoverningSource:
    def _world(self):
        return load_world(SCOPE_WORLD)

    def test_in_scope_subject_selects_the_covering_source(self):
        world = self._world()
        mode, source, subject = _governing_source(
            world, _actor("loc.test.archive"), WYRM
        )
        assert mode == "in_scope"
        assert source.id == "npc.test.archivist"
        assert subject.subject == WYRM

    def test_out_of_scope_subject_falls_to_a_lead(self):
        world = self._world()
        mode, source, subject = _governing_source(
            world, _actor("loc.test.archive"), "creature.test.unheard_of"
        )
        assert mode == "lead"
        assert source.id == "npc.test.archivist"
        assert subject is None

    def test_no_co_located_source_is_ambient(self):
        world = self._world()
        # At the scar there is no source entity — ambient rumor default.
        mode, source, _ = _governing_source(world, _actor("loc.test.scar"), WYRM)
        assert mode is None and source is None


# --------------------------------------------------------------------------- #
# Research resolution: accurate on success, confidently wrong on a bad roll    #
# --------------------------------------------------------------------------- #


class TestResearchInScope:
    def _args(self, world, outcome_tier):
        return dict(
            subject=WYRM,
            subject_entity=world.entities[WYRM],
            subject_name=world.entities[WYRM].name,
            actor=_actor("loc.test.archive"),
            actor_id="pc",
            source=world.entities["npc.test.archivist"],
            scope_subject=world.entities["npc.test.archivist"].knowledge_scope.subject(WYRM),
            outcome_tier=outcome_tier,
            time_after=0,
            entity_states=None,
        )

    def test_bad_roll_writes_the_confident_wrong_answer_at_high_strength(self):
        world = load_world(SCOPE_WORLD)
        (delta,) = _research_in_scope(**self._args(world, OutcomeTier.MISS))
        claim = delta["claim"]
        # The authored error profile, verbatim — the ballads lie.
        assert claim["predicate"] == "threat_assessed"
        assert claim["value_text"] == "RISKY"
        assert claim["scope"] == "ballad_inflation"
        assert claim["source_agent_id"] == "npc.test.archivist"
        # HIGH strength: a source told you authoritatively (told=60), far above
        # ambient rumor (35). This is what a later observation can supersede.
        assert claim["acquisition_method"] == "told"
        assert BASE_EVIDENCE_WEIGHT[claim["acquisition_method"]] == 60

    def test_bad_roll_is_deterministic(self):
        world = load_world(SCOPE_WORLD)
        a = _research_in_scope(**self._args(world, OutcomeTier.MISS))
        b = _research_in_scope(**self._args(world, OutcomeTier.MISS))
        assert a == b  # never random — same source, same subject, same wrong claim

    def test_strong_hit_reaches_the_deepest_authored_field(self):
        world = load_world(SCOPE_WORLD)
        (delta,) = _research_in_scope(**self._args(world, OutcomeTier.STRONG_HIT))
        claim = delta["claim"]
        # Tier-2 source, strong hit → the weak_point reveal (a FIELD, not a #).
        assert claim["predicate"] == "weak_point"
        assert claim["value_text"] == "the old wound under its left wing"
        assert claim["scope"] == "appraisal_tier_2"
        assert claim["value_num"] is None  # never an exact number to KnownState

    def test_complicated_hit_reads_a_shallower_field(self):
        world = load_world(SCOPE_WORLD)
        (delta,) = _research_in_scope(**self._args(world, OutcomeTier.HIT_WITH_COMPLICATION))
        claim = delta["claim"]
        assert claim["predicate"] == "threat_assessed"  # tier-1 band, not the weak point
        assert claim["scope"] == "appraisal_tier_1"


class TestAppraisalTierCap:
    """Research depth reveals FIELDS, capped by the SOURCE's max tier (Kumo)."""

    def test_shallow_source_cannot_surface_a_deep_field_on_a_strong_hit(self):
        reveals = (
            ScopeReveal(0, "common_knowledge", "surface", "a surface note"),
            ScopeReveal(1, "threat_assessed", "DESPERATE", "a band read"),
            ScopeReveal(2, "weak_point", "the soft place", "the deep truth"),
        )
        subject = ScopeSubject(subject=WYRM, reveals=reveals, error=None)
        shallow = types.SimpleNamespace(
            id="npc.test.clerk",
            name="the clerk",
            knowledge_scope=KnowledgeScope(max_appraisal_tier=1, subjects=(subject,)),
        )
        (delta,) = _research_in_scope(
            subject=WYRM, subject_entity=None, subject_name="the wyrm",
            actor=_actor("loc.test.archive"), actor_id="pc", source=shallow,
            scope_subject=subject, outcome_tier=OutcomeTier.STRONG_HIT,
            time_after=0, entity_states=None,
        )
        # A strong hit at a tier-1 source reaches tier 1, never the tier-2 weak
        # point — the source's depth caps what any roll can read.
        assert delta["claim"]["predicate"] == "threat_assessed"
        assert delta["claim"]["scope"] == "appraisal_tier_1"


class TestResearchLead:
    def test_lead_points_at_a_better_source(self):
        world = load_world(SCOPE_WORLD)
        (delta,) = _research_lead("pc", world.entities["npc.test.archivist"], 0)
        claim = delta["claim"]
        assert claim["subject_entity_id"] == "loc.test.far_province"
        assert claim["scope"] == "lead"
        assert "burned province" in claim["claim_text"]


# --------------------------------------------------------------------------- #
# Research addressability (a present source opens its catalogue)              #
# --------------------------------------------------------------------------- #


class TestResearchAddressability:
    def _decide(self, sim, intent, claim_subjects=None):
        return decide_tier(
            intent=intent, actor=sim.pc, world=sim.world, manifest=sim.state.manifest,
            world_time=sim.state.world["world_time"], entity_states=sim.state.entities,
            actor_claim_subjects=claim_subjects,
        )

    def test_catalogued_off_scene_subject_is_addressable(self):
        sim = Sim(seed=42, world_path=SCOPE_WORLD)
        # The wyrm is at the scar (off-scene), but the co-located archive
        # catalogues it — research reaches it with NO prior claim.
        decision = self._decide(sim, canned("research", ["creature_test_wyrm"], "study it"))
        assert decision.targets == (WYRM,)

    def test_uncatalogued_off_scene_subject_is_refused(self):
        sim = Sim(seed=42, world_path=SCOPE_WORLD)
        with pytest.raises(ResolverError) as exc:
            self._decide(sim, canned("research", ["creature_test_ghost"], "study it"))
        assert str(exc.value) == UNADDRESSABLE_TARGET


class TestResearchIntegration:
    """End to end through resolve_intent: the source path fires, not ambient."""

    def test_research_at_a_source_writes_a_source_stamped_claim(self):
        sim = Sim(seed=42, world_path=SCOPE_WORLD)
        _res, row = sim.run_turn(canned("research", ["creature_test_wyrm"], stat_hint="lore"))
        (intel,) = [d for d in row["payload"]["state_deltas"] if d["delta_type"] == "intel"]
        claim = intel["claim"]
        # Provenance proves the archive governed it (ambient would be
        # "taproom consensus"/rumor); strength is the high source weight.
        assert claim["subject_entity_id"] == "creature.test.wyrm"
        assert claim["source_agent_id"] == "npc.test.archivist"
        assert claim["source"] == "the archivist"
        assert claim["acquisition_method"] == "told"

    def test_research_outcome_is_deterministic(self):
        a = Sim(seed=7, world_path=SCOPE_WORLD).run_turn(
            canned("research", ["creature_test_wyrm"], stat_hint="lore")
        )[1]["payload"]["state_deltas"]
        b = Sim(seed=7, world_path=SCOPE_WORLD).run_turn(
            canned("research", ["creature_test_wyrm"], stat_hint="lore")
        )[1]["payload"]["state_deltas"]
        assert a == b


# --------------------------------------------------------------------------- #
# Knowledge-gated actions                                         #
# --------------------------------------------------------------------------- #


class TestKnowledgeGate:
    def _decide(self, sim, intent, intel=None):
        return decide_tier(
            intent=intent, actor=sim.pc, world=sim.world, manifest=sim.state.manifest,
            world_time=sim.state.world["world_time"], entity_states=sim.state.entities,
            actor_target_intel=intel,
        )

    def test_hopeless_fight_stays_hopeless_without_intel(self):
        sim = Sim(seed=42)  # dev-fixture; PC in the tavern with Torvald (threat 20)
        decision = self._decide(sim, canned("physical", ["npc_dev_torvald"], stat_hint="might"))
        assert decision.tier is PlausibilityTier.HOPELESS
        assert decision.weak_point_target is None

    def test_known_weak_point_unlocks_the_desperate_option(self):
        sim = Sim(seed=42)
        decision = self._decide(
            sim,
            canned("physical", ["npc_dev_torvald"], stat_hint="might"),
            intel={"npc.dev.torvald": frozenset({"weak_point"})},
        )
        assert decision.tier is PlausibilityTier.DESPERATE
        assert decision.weak_point_target == "npc.dev.torvald"
        assert any("weak_point known" in n for n in decision.law_notes)

    def test_threat_assessment_alone_does_not_downgrade(self):
        sim = Sim(seed=42)
        decision = self._decide(
            sim,
            canned("physical", ["npc_dev_torvald"], stat_hint="might"),
            intel={"npc.dev.torvald": frozenset({"threat_assessed"})},
        )
        assert decision.tier is PlausibilityTier.HOPELESS  # knowing it is deadly ≠ softer
        assert decision.weak_point_target is None

    def test_weak_point_adds_a_named_roll_modifier(self):
        sim = Sim(seed=42)
        res = resolve_intent(
            intent=canned("physical", ["npc_dev_torvald"], stat_hint="might"),
            actor=sim.pc, world=sim.world, manifest=sim.state.manifest,
            entity_states=sim.state.entities, world_time=sim.state.world["world_time"],
            rng_counters=sim.state.world["rng_counters"], seed=sim.seed, turn=1,
            actor_target_intel={"npc.dev.torvald": frozenset({"weak_point"})},
        )
        assert res.tier is PlausibilityTier.DESPERATE
        outcome = res.events[res.outcome_event_index]
        mods = {m["label"]: m["value"] for m in outcome.payload["dice"]["modifiers"]}
        assert mods["weak_point"] == WEAK_POINT_ROLL_BONUS


# --------------------------------------------------------------------------- #
# Status strip: coin + active timers on ChronicleFacts (5a)                    #
# --------------------------------------------------------------------------- #


class TestStatusStrip:
    def test_active_timers_surface_on_chronicle_facts(self):
        sim = Sim(seed=42)
        sim.run_turn(canned("train", stat_hint="might"))  # starts a training timer
        facts = load_known_state(sim.state, sim.world).chronicle_facts("pc")
        assert facts.coin == sim.pc["coin"]  # coin already exact-known
        assert len(facts.active_timers) == 1
        timer = facts.active_timers[0]
        assert timer.kind == "training"
        assert timer.due_world_time > 0
        assert isinstance(timer.due_at, str)

    def test_no_timers_means_empty_tuple(self):
        sim = Sim(seed=42)
        assert load_known_state(sim.state, sim.world).chronicle_facts("pc").active_timers == ()


# --------------------------------------------------------------------------- #
# narration-as-canon store entry point (5b) — DB half                         #
# --------------------------------------------------------------------------- #


class TestNarrateOutcome:
    def _world_conn(self, db_conn):
        from everquill_engine.chargen import chargen_events, roll_character
        from everquill_engine.genesis import genesis_specs
        from everquill_engine.store import execute_command, fresh_reset
        from tests.harness import FIXTURE_WORLD

        world = load_world(FIXTURE_WORLD)
        fresh_reset(db_conn)
        execute_command(db_conn, "genesis", lambda _s: genesis_specs(world, 42))
        specs = chargen_events(
            roll_character(42, "pc", name="q"), location_id="loc.dev.tavern",
            region="dev", world_time=0,
        )
        execute_command(db_conn, "chargen:pc", lambda _s: specs)
        return db_conn, world

    def test_narration_binds_to_the_outcome_and_is_idempotent(self, db_conn):
        from everquill_engine.beat import assess_or_execute
        from everquill_engine.store import narrate_outcome

        conn, world = self._world_conn(db_conn)
        result = assess_or_execute(
            conn, "turn:1",
            canned("research", ["npc_dev_sorrel"], stat_hint="lore"),
            world=world, character_id="pc",
        )
        outcome = result.append_result.event_rows[result.resolution.outcome_event_index]

        appended = narrate_outcome(
            conn, character_id="pc", outcome_event_id=outcome["id"],
            outcome_event_ulid=outcome["event_ulid"], world_time=outcome["world_time"],
            prose="The archivist's records blur, and so do you.",
            assembler_version="test.v1", content_hash="deadbeef",
        )
        assert not appended.absorbed
        (narr,) = appended.event_rows
        assert narr["event_type"] == "narration_generated"
        assert narr["payload"]["outcome_event_id"] == outcome["id"]
        assert narr["payload"]["content_hash"] == "deadbeef"
        assert narr["command_id"] == f"narrate:{outcome['event_ulid']}"

        # Re-narrating the same outcome is absorbed — prose never forks.
        again = narrate_outcome(
            conn, character_id="pc", outcome_event_id=outcome["id"],
            outcome_event_ulid=outcome["event_ulid"], world_time=outcome["world_time"],
            prose="a different take", assembler_version="test.v2", content_hash="other",
        )
        assert again.absorbed
