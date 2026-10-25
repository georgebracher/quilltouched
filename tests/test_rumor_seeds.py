"""Authored rumor seeds surfacing through ambient Inquiry claims."""

from __future__ import annotations

from everquill_engine.claims import BASE_EVIDENCE_WEIGHT
from everquill_engine.ladder import OutcomeTier, PlausibilityTier
from everquill_engine.resolver.research import _pick_rumor_seed, _research_ambient
from everquill_engine.world import RumorSeed
from tests.harness import REPO_ROOT, Sim

HARROWDOWN = REPO_ROOT / "content" / "world" / "harrowdown.yaml"
SCOPE_WORLD = REPO_ROOT / "tests" / "fixtures" / "scope-world.yaml"


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


def _intel_claim(row):
    claims = [
        delta["claim"]
        for delta in row["payload"]["state_deltas"]
        if delta["delta_type"] == "intel"
    ]
    assert len(claims) == 1
    return claims[0]


def _rumor_claims(row):
    return [
        delta["claim"]
        for delta in row["payload"]["state_deltas"]
        if delta["delta_type"] == "intel"
        and delta["claim"]["subject_entity_id"] == "world"
        and delta["claim"]["method"] == "rumor"
    ]


def _seed_deeds(sim: Sim) -> set[str]:
    return {seed.deed for seed in sim.world.rumor_seeds}


class TestRumorSeedSurface:
    def test_untargeted_ambient_observation_surfaces_one_harrowdown_seed(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        res, row = sim.run_turn(canned("observation", approach="look around"))

        assert res.tier is PlausibilityTier.TRIVIAL
        assert row["payload"]["dice"] is None
        assert row["payload"]["outcome_tier"] is None
        assert [delta["delta_type"] for delta in row["payload"]["state_deltas"]] == ["intel"]

        (claim,) = _rumor_claims(row)
        assert claim["subject_entity_id"] == "world"
        assert claim["predicate"] == "common_knowledge"
        assert claim["claim_text"] in _seed_deeds(sim)
        assert claim["value_text"] == claim["claim_text"]
        assert claim["source"] == "taproom consensus"
        assert claim["method"] == "rumor"
        assert claim["acquisition_method"] == "rumor"
        assert BASE_EVIDENCE_WEIGHT[claim["acquisition_method"]] == 35
        assert claim["scope"] == "local_mistaken_for_universal"

    def test_successive_ambient_observations_pick_the_turn_seed_replay_stably(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _res_1, row_1 = sim.run_turn(canned("observation", approach="look around"))
        _res_2, row_2 = sim.run_turn(canned("observation", approach="observe the room"))

        (claim_1,) = _rumor_claims(row_1)
        (claim_2,) = _rumor_claims(row_2)
        expected_1 = _pick_rumor_seed(
            sim.world.rumor_seeds,
            actor_id="pc",
            world_time=row_1["world_time"],
            turn=1,
        )
        expected_2 = _pick_rumor_seed(
            sim.world.rumor_seeds,
            actor_id="pc",
            world_time=row_2["world_time"],
            turn=2,
        )
        assert expected_1 is not None
        assert expected_2 is not None
        assert claim_1["claim_text"] == expected_1.deed
        assert claim_2["claim_text"] == expected_2.deed
        assert claim_1["claim_text"] != claim_2["claim_text"]

        replay = Sim(seed=42, world_path=HARROWDOWN)
        _replay_res, replay_row = replay.run_turn(canned("observation", approach="look around"))
        (replay_claim,) = _rumor_claims(replay_row)
        assert replay_claim["claim_text"] == claim_1["claim_text"]

    def test_no_seed_world_untargeted_observation_has_no_rumor_claim(self):
        sim = Sim(seed=42, world_path=SCOPE_WORLD)
        assert sim.world.rumor_seeds == ()

        _res, row = sim.run_turn(canned("observation", approach="look around"))

        assert row["payload"]["state_deltas"] == []
        assert _rumor_claims(row) == []

    def test_targeted_observation_does_not_inject_seed_rumor(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _res, row = sim.run_turn(
            canned("observation", ["npc_harrowdown_rold_tanner"], "watch Rold")
        )

        assert _rumor_claims(row) == []
        assert all(
            delta["claim"]["claim_text"] not in _seed_deeds(sim)
            for delta in row["payload"]["state_deltas"]
            if delta["delta_type"] == "intel"
        )

    def test_subjectless_ambient_research_surfaces_one_harrowdown_seed(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        _res, row = sim.run_turn(
            canned("research", approach="listen for the town gossip", stat_hint="lore")
        )

        claim = _intel_claim(row)
        assert claim["subject_entity_id"] == "world"
        assert claim["predicate"] == "common_knowledge"
        assert claim["claim_text"] in _seed_deeds(sim)
        assert claim["value_text"] == claim["claim_text"]
        assert claim["source"] == "taproom consensus"
        assert claim["method"] == "rumor"
        assert claim["acquisition_method"] == "rumor"
        assert BASE_EVIDENCE_WEIGHT[claim["acquisition_method"]] == 35
        assert claim["scope"] == "local_mistaken_for_universal"

    def test_same_actor_world_time_turn_picks_same_seed_on_replay(self):
        a = Sim(seed=42, world_path=HARROWDOWN)
        b = Sim(seed=42, world_path=HARROWDOWN)

        _res_a, row_a = a.run_turn(
            canned("research", approach="listen for the town gossip", stat_hint="lore")
        )
        _res_b, row_b = b.run_turn(
            canned("research", approach="listen for the town gossip", stat_hint="lore")
        )

        claim_a = _intel_claim(row_a)
        claim_b = _intel_claim(row_b)
        assert claim_a["claim_text"] == claim_b["claim_text"]
        expected = _pick_rumor_seed(
            a.world.rumor_seeds,
            actor_id="pc",
            world_time=row_a["world_time"],
            turn=1,
        )
        assert expected is not None
        assert claim_a["claim_text"] == expected.deed

    def test_notoriety_weights_pick_distribution_deterministically(self):
        seeds = (
            RumorSeed("quiet", 1),
            RumorSeed("loud", 8),
        )
        counts = {"quiet": 0, "loud": 0}

        for turn in range(1, 1001):
            picked = _pick_rumor_seed(
                seeds, actor_id="pc", world_time=60 + turn, turn=turn
            )
            assert picked is not None
            counts[picked.deed] += 1

        assert counts["loud"] >= counts["quiet"]

    def test_no_seed_world_keeps_subjectless_filler_unchanged(self):
        sim = Sim(seed=42, world_path=SCOPE_WORLD)
        assert sim.world.rumor_seeds == ()

        (hit_delta,) = _research_ambient(
            None,
            None,
            "pc",
            OutcomeTier.HIT_WITH_COMPLICATION,
            60,
            rumor_seeds=sim.world.rumor_seeds,
            turn=1,
        )
        hit_claim = hit_delta["claim"]
        assert hit_claim["claim_text"] == "You piece together the shape of local talk."
        assert hit_claim["method"] == "archive_research"
        assert hit_claim["source"] == "patient questions"
        assert hit_claim["scope"] == "local"

        (miss_delta,) = _research_ambient(
            None,
            None,
            "pc",
            OutcomeTier.MISS,
            60,
            rumor_seeds=sim.world.rumor_seeds,
            turn=1,
        )
        miss_claim = miss_delta["claim"]
        assert miss_claim["claim_text"] == "The stories agree on more than they should."
        assert miss_claim["method"] == "rumor"
        assert miss_claim["source"] == "taproom consensus"
        assert miss_claim["scope"] == "local_mistaken_for_universal"

    def test_subject_entity_ambient_research_ignores_world_seeds(self):
        sim = Sim(seed=42)
        subject = sim.world.entities["npc.dev.sorrel"]
        fake_seeds = (RumorSeed("a loud unrelated rumor", 999),)

        (delta,) = _research_ambient(
            subject.id,
            subject,
            "pc",
            OutcomeTier.STRONG_HIT,
            60,
            rumor_seeds=fake_seeds,
            turn=1,
        )

        claim = delta["claim"]
        assert claim["subject_entity_id"] == "npc.dev.sorrel"
        assert claim["claim_text"] == subject.common_knowledge[0]
        assert claim["method"] == "archive_research"
        assert claim["source"] == "patient questions"

    def test_authored_source_research_path_still_wins(self):
        sim = Sim(seed=42, world_path=SCOPE_WORLD)
        _res, row = sim.run_turn(
            canned("research", ["creature_test_wyrm"], "study it", stat_hint="lore")
        )

        claim = _intel_claim(row)
        assert claim["subject_entity_id"] == "creature.test.wyrm"
        assert claim["source_agent_id"] == "npc.test.archivist"
        assert claim["source"] == "the archivist"
        assert claim["method"] == "source_records"


class TestAuthoredRumorRoot:
    """Hearing one authored rumor twice is one source, not corroboration."""

    def test_every_hearing_of_a_seed_shares_one_negative_root(self):
        from everquill_engine.resolver.research import (
            _ambient_rumor_candidates,
            authored_rumor_root,
        )

        seeds = (RumorSeed(deed="a stranger asked after the wyvern", notoriety=2),
                 RumorSeed(deed="the miller's dam leaks", notoriety=1))
        first = _ambient_rumor_candidates(
            rumor_seeds=seeds, deeds=(), world=None, location_id=None, time_after=0
        )
        later = _ambient_rumor_candidates(
            rumor_seeds=seeds, deeds=(), world=None, location_id=None, time_after=9999
        )
        roots = [c.provenance_root_event_id for c in first]
        assert roots == [c.provenance_root_event_id for c in later]
        assert roots[0] == authored_rumor_root(seeds[0].deed)
        assert all(r is not None and r < 0 for r in roots)
        assert roots[0] != roots[1]

    def test_the_delta_carries_the_authored_root(self):
        sim = Sim(seed=42, world_path=HARROWDOWN)
        from everquill_engine.resolver.research import authored_rumor_root

        roots = set()
        for _ in range(4):
            _res, row = sim.run_turn(canned("observation", approach="take in the room"))
            for delta in row["payload"]["state_deltas"]:
                if delta["delta_type"] == "intel" and delta["claim"]["method"] == "rumor":
                    roots.add(delta["provenance_root_event_id"])
                    assert delta["provenance_root_event_id"] == authored_rumor_root(
                        delta["claim"]["claim_text"]
                    )
        assert roots, "no authored rumor surfaced in four looks"


class TestSourceAgentRoot:
    """One NPC asked twice is one source, not corroboration (audit codex-001)."""

    MAREN = "npc_harrowdown_maren_ostler"

    def _ask_about_the_quarry(self, sim):
        intent = dict(
            canned("dialogue", [self.MAREN], approach="ask about the quarry"),
            dialogue={"addressee_id": self.MAREN, "quoted_speech": None},
            speech_act="question",
            topic_ids=["creature_harrowdown_quarryman"],
        )
        resolution, _row = sim.run_turn(intent)
        return [
            spec.payload for spec in resolution.events
            if spec.event_type == "claim_written"
        ]

    def test_two_answers_from_one_npc_share_its_root(self):
        from everquill_engine.resolver.research import source_agent_root

        sim = Sim(seed=42, world_path=HARROWDOWN)
        sim.state.characters["pc"]["location_id"] = "loc.harrowdown.tavern"
        sim.state.manifest["pc"]["location_id"] = "loc.harrowdown.tavern"
        first, second = self._ask_about_the_quarry(sim), self._ask_about_the_quarry(sim)
        assert first and second, "the barkeep gave no account of the quarry"
        roots = {c["provenance_root_event_id"] for c in first + second}
        agents = {c["claim"]["source_agent_id"] for c in first + second}
        assert len(agents) == 1
        assert roots == {source_agent_root(agents.pop())}

    def test_sources_and_rumors_never_share_a_root(self):
        from everquill_engine.resolver.research import authored_rumor_root, source_agent_root

        assert source_agent_root("npc.harrowdown.maren_ostler") < 0
        assert source_agent_root("npc.harrowdown.maren_ostler") != source_agent_root(
            "npc.harrowdown.jorun_pike"
        )
        assert source_agent_root("x") != authored_rumor_root("x")


class TestDeadSourcesTellNothing:
    """A dispatched NPC is no research source and holds no askable topics
    (audit claude-007, codex-007)."""

    def test_a_dead_barkeep_neither_answers_nor_lists_topics(self):
        from everquill_engine.resolver.research import _governing_source
        from everquill_engine.views import load_known_state

        sim = Sim(seed=42, world_path=HARROWDOWN)
        sim.state.characters["pc"]["location_id"] = "loc.harrowdown.tavern"
        sim.state.manifest["pc"]["location_id"] = "loc.harrowdown.tavern"
        alive = load_known_state(sim.state, sim.world, {}).topics("pc")
        mode, source, _ = _governing_source(
            sim.world, sim.pc, "creature.harrowdown.quarryman", sim.state.entities
        )
        assert alive and source is not None and mode == "in_scope"

        sim.state.entities["npc.harrowdown.maren_ostler"]["hp"] = 0
        mode, source, _ = _governing_source(
            sim.world, sim.pc, "creature.harrowdown.quarryman", sim.state.entities
        )
        assert source is None or source.id != "npc.harrowdown.maren_ostler"
        dead = load_known_state(sim.state, sim.world, {}).topics("pc")
        assert "creature_harrowdown_quarryman" not in {t.topic_id for t in dead}
