"""Property tests for the context assembler. NO API CALLS.

Run: .venv/bin/python -m pytest llm/test_assembler.py -q
  1. schema validity (narration_context.schema.json v1.1)
  2. determinism: same view -> byte-identical envelope + hash (in-process x2
     AND a fresh subprocess)
  3. irrelevance injection: +100 unrelated claims -> envelope byte-identical
  4. floor satisfaction + caps under a 500-claim flood (pinned survive,
     per-subject cap holds, totals bounded, other sections untouched)
  5. total tiebreak order: equal salience resolves by category rank, then
     world_timestamp DESC (hours_ago ASC), then claim_id ASC
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assembler import (  # noqa: E402
    PER_SUBJECT_CAP,
    SECTION_CAPS,
    SECTION_FLOORS,
    TOTAL_CAP,
    assemble,
    atmosphere_from_world,
    canonical_entity_id,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((REPO_ROOT / "docs/contracts/narration_context.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def _claim(cid: str, subject: str, text: str, *, method="rumor", hours=24,
           conf="uncorroborated", contradiction_ids=(), source="Maren Ostler",
           scope="harrowdown", **meta):
    return {
        "claim": {
            "claim_id": cid, "subject_entity_id": subject, "claim_text": text,
            "value_or_range": None, "source": source, "observer": None,
            "method": method, "world_date": "Y1-Q2-D14", "scope": scope,
            "confidence": conf, "corroboration_ids": [],
            "contradiction_ids": list(contradiction_ids),
            "inheritance_status": "original",
        },
        "meta": {"world_hours_ago": hours, "half_life_class": "gossip", **meta},
    }


def base_view() -> dict:
    return {
        "scene": {
            "location_id": "loc_harrowdown_tavern",
            "label_known": "The Drowned Ram",
            "world_time": "Year 1, Quarterday Eve, evening bell",
            "entities": [
                {"entity_id": "npc_harrowdown_maren_ostler", "label_known": "Maren Ostler",
                 "category": "person", "position": {"x": 0.3, "y": 0.7}, "state_tags": []},
                {"entity_id": "npc_harrowdown_jorun_pike", "label_known": "Jorun Pike",
                 "category": "person", "position": {"x": 0.62, "y": 0.7},
                 "state_tags": ["ruined_arm"]},
                {"entity_id": "item_harrowdown_guild_board", "label_known": "the guild board",
                 "category": "feature", "position": None, "state_tags": []},
            ],
        },
        "known_sheets": [
            {"entity_id": "pc_quilltouched", "facts": [
                {"field": "coin_pennies", "value": 184},
                {"field": "wound_left_shoulder", "value": "bandaged, three days old"},
                {"field": "title", "value": "none yet earned"},
            ]},
            {"entity_id": "npc_harrowdown_jorun_pike", "facts": [
                {"field": "plate_rank_public", "value": "C"},
                {"field": "arm", "value": "left arm ruined at Redcliff quarry"},
            ]},
        ],
        "claims": [
            _claim("c_aaa01", "npc_harrowdown_jorun_pike",
                   "Jorun answers wyvern questions once per asker, then never again.",
                   method="witnessed", hours=12),
            _claim("c_aaa02", "npc_harrowdown_maren_ostler",
                   "Maren pays a penny for road news worth hearing.",
                   method="rumor", hours=40),
            _claim("c_aaa03", "creature_harrowdown_barrow_wight",
                   "Something walks the cairns after dark; the drovers won't camp there.",
                   method="rumor", hours=60, one_hop=True),
            _claim("c_pin01", "pc_quilltouched",
                   "OATH: you swore to Sister Odile to carry no blade into the chapel.",
                   method="witnessed", hours=100, constraint_class=True),
        ],
        "active_clocks": [
            {"clock_id": "clk_quarterday_eve", "label": "Quarterday appraisal eve",
             "due_world_time": "Quarterday, first bell", "progress_text": "candles being set",
             "due_world_hours": 10,
             "refs": ["npc_harrowdown_sister_odile", "loc_harrowdown_chapel"]},
        ],
        "canon_excerpts": [
            {"source_ref": "precedent:redcliff_quarry_deaths", "mode": "summary",
             "text": "Six went up the Redcliff track nine years back; "
                     "two came down. Jorun was one."},
        ],
        "atmosphere": [
            "Rushlight and tallow smoke; the fire is banked low to save wood.",
            "The floorboards nearest the door are still swollen from the spring flood.",
        ],
        "recent_subjects": {"npc_harrowdown_jorun_pike": 1},
        "last_resolution": {
            "event_id": "evt_000412", "action_summary": "asked Jorun about the wyvern",
            "tier_resolved": "risky", "outcome_tier": "hit_with_complication",
            "dice_total": 8,
        },
    }


def test_schema_valid():
    out = assemble(base_view())
    errs = list(VALIDATOR.iter_errors(out.envelope))
    assert not errs, [e.message for e in errs]


def test_deterministic_byte_identical():
    v = base_view()
    a = assemble(copy.deepcopy(v))
    b = assemble(copy.deepcopy(v))
    assert a.canonical == b.canonical
    assert a.content_hash == b.content_hash
    # and across a fresh interpreter (rules out set/hash-seed order leaks)
    code = (
        "import json,sys; sys.path.insert(0,'llm');"
        "from assembler import assemble;"
        "v=json.load(open(sys.argv[1]));print(assemble(v).content_hash)"
    )
    tmp = REPO_ROOT / ".pytest_cache" / "assembler_view.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(v))
    got = subprocess.run([sys.executable, "-c", code, str(tmp)], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert got == a.content_hash


def test_irrelevance_injection_leaves_envelope_unchanged():
    v = base_view()
    baseline = assemble(copy.deepcopy(v))
    noisy = copy.deepcopy(v)
    for i in range(100):
        noisy["claims"].append(_claim(
            f"c_noise{i:03d}", f"npc_severwick_stranger_{i:03d}",
            f"A stranger in Severwick owes someone {i} pennies.",
            method="rumor", hours=5))  # recent but structurally irrelevant
    flooded = assemble(noisy)
    assert flooded.canonical == baseline.canonical
    assert flooded.content_hash == baseline.content_hash
    reasons = {r["reason"] for r in flooded.receipt["claims"] if not r["accepted"]}
    assert "no_structural_relevance" in reasons


def test_floor_satisfaction_and_caps_under_claim_flood():
    v = base_view()
    baseline = assemble(copy.deepcopy(v))
    flood = copy.deepcopy(v)
    subjects = [e["entity_id"] for e in v["scene"]["entities"]]
    for i in range(500):
        flood["claims"].append(_claim(
            f"c_flood{i:03d}", subjects[i % len(subjects)],
            f"Bar-room assertion number {i} about this very scene, sworn on someone's mother.",
            method="rumor", hours=1 + i))
    out = assemble(flood)
    errs = list(VALIDATOR.iter_errors(out.envelope))
    assert not errs, [e.message for e in errs]

    st = out.receipt["section_tokens"]
    # total bounded
    assert out.receipt["total_tokens"] <= TOTAL_CAP
    # claims flex-capped, and the floor is actually reached under a flood
    assert st["salient_claims"] <= out.receipt["claims_budget"]
    assert st["salient_claims"] >= SECTION_FLOORS["salient_claims"]
    # fixed sections keep their caps
    for s in ("canon_excerpts", "known_sheet_slices", "active_clocks", "assembly"):
        assert st[s] <= SECTION_CAPS[s], s
    # pinned constraint-class claim survives the flood
    packed_ids = {c["claim_id"] for c in out.envelope["salient_claims"]}
    assert "c_pin01" in packed_ids
    # per-subject cap holds for ranked claims (pinned exempt)
    per_subject: dict = {}
    for c in out.envelope["salient_claims"]:
        if c["claim_id"] == "c_pin01":
            continue
        per_subject[c["subject_entity_id"]] = per_subject.get(c["subject_entity_id"], 0) + 1
    assert all(n <= PER_SUBJECT_CAP for n in per_subject.values()), per_subject
    # the flood cannot move the other sections at all
    for section in ("scene_manifest", "known_sheet_slices", "active_clocks", "canon_excerpts"):
        assert out.envelope[section] == baseline.envelope[section], section
    # trace still present
    assert out.envelope["assembly"]["last_resolution"]["event_id"] == "evt_000412"


def test_tiebreak_chain_total_order():
    v = base_view()
    v["claims"] = [
        # identical salience inputs except the tiebreak axes
        _claim("c_tie_b", "npc_harrowdown_jorun_pike", "tie text one", method="rumor", hours=24),
        _claim("c_tie_a", "npc_harrowdown_jorun_pike", "tie text two", method="rumor", hours=24),
        _claim("c_tie_c", "npc_harrowdown_jorun_pike", "newer rumor", method="rumor", hours=6),
        _claim("c_tie_d", "npc_harrowdown_jorun_pike", "witnessed same salience?",
               method="witnessed", hours=24),
    ]
    out = assemble(v)
    order = [c["claim_id"] for c in out.envelope["salient_claims"]
             if c["claim_id"].startswith("c_tie")]
    # hours=6 wins on recency (higher salience). Among hours=24: witnessed
    # (category rank 0) precedes rumor (rank 3); rumor ties resolve by id ASC
    # — so c_tie_a packs and c_tie_b is the one squeezed out by the
    # per-subject cap of 3 (proving id ASC decided the tie).
    assert order == ["c_tie_c", "c_tie_d", "c_tie_a"]
    excluded = {r["claim_id"]: r["reason"] for r in out.receipt["claims"] if not r["accepted"]}
    assert excluded.get("c_tie_b") == "per_subject_cap"


def test_entity_id_canonicalization_and_atmosphere_loader():
    assert canonical_entity_id("loc.harrowdown.tavern") == "loc_harrowdown_tavern"
    world = {"locations": [
        {"id": "loc.harrowdown.tavern", "atmosphere": ["banked fire", "wet boards"]},
        {"id": "loc.harrowdown.chapel"},
    ]}
    assert atmosphere_from_world(world, "loc_harrowdown_tavern") == ["banked fire", "wet boards"]
    assert atmosphere_from_world(world, "loc.harrowdown.chapel") == []
    assert atmosphere_from_world({}, "loc_harrowdown_tavern") == []


def _contested_view() -> dict:
    """A scene subject carrying a contested pair plus filler claims that would
    normally starve one side of the pair out of the per-subject cap."""
    v = base_view()
    v["claims"] = []  # drop the pin so this test isolates cap/co-surface behaviour
    subj = "npc_harrowdown_jorun_pike"  # present in the scene -> V=100 for all
    v["claims"] = [
        _claim("c_ballad", subj, "The ballads say the wyvern's throat is bare to a spear.",
               method="rumor", hours=6, contradiction_ids=["c_archive"],
               source="Ballad of Red Vermithrax"),
        _claim("c_archive", subj, "The archivist holds the throat-scale is the thickest of all.",
               method="archive_research", hours=200, contradiction_ids=["c_ballad"],
               source="Dunmere archive"),
        _claim("c_fill1", subj, "Filler claim one about Jorun.", method="rumor", hours=20),
        _claim("c_fill2", subj, "Filler claim two about Jorun.", method="rumor", hours=30),
        _claim("c_fill3", subj, "Filler claim three about Jorun.", method="rumor", hours=40),
    ]
    return v


def test_contested_pair_cosurfaced_past_per_subject_cap():
    """Both halves of a contradiction reach the narrator even when the low-
    ranking side would otherwise be squeezed out by the per-subject cap."""
    out = assemble(_contested_view())
    assert not list(VALIDATOR.iter_errors(out.envelope))
    packed = {c["claim_id"] for c in out.envelope["salient_claims"]}
    # The recent ballad ranks; the stale archive rebuttal would lose the cap
    # race, but co-surfaces as the ballad's contradiction partner.
    assert {"c_ballad", "c_archive"} <= packed, packed
    reasons = {r["claim_id"]: r["reason"] for r in out.receipt["claims"]}
    assert reasons["c_archive"] == "contested_partner", reasons
    # cap still bites the non-contested filler that lost the race
    assert reasons.get("c_fill3") == "per_subject_cap", reasons
    # and the contradiction links still point at each other in the envelope
    by_id = {c["claim_id"]: c for c in out.envelope["salient_claims"]}
    assert by_id["c_ballad"]["contradiction_ids"] == ["c_archive"]
    assert by_id["c_archive"]["contradiction_ids"] == ["c_ballad"]


def test_contested_cosurfacing_is_deterministic():
    v = _contested_view()
    a = assemble(copy.deepcopy(v))
    b = assemble(copy.deepcopy(v))
    assert a.canonical == b.canonical
    assert a.content_hash == b.content_hash


def test_dangling_contradiction_id_is_ignored():
    """A contradiction_id with no matching claim in the view never crashes and
    never invents a partner."""
    v = base_view()
    v["claims"] = [
        _claim("c_solo", "npc_harrowdown_jorun_pike", "A lone contested claim with a dead link.",
               method="rumor", hours=5, contradiction_ids=["c_missing"]),
    ]
    out = assemble(v)
    assert not list(VALIDATOR.iter_errors(out.envelope))
    packed = {c["claim_id"] for c in out.envelope["salient_claims"]}
    assert packed == {"c_solo"}


def test_source_lead_is_never_surfaced_ambiently():
    """Turn-53 fabrication fix: a source's `lead` pointer (scope='lead') must
    NOT reach the narrator just because the source is present, EVEN when
    salience meta (one_hop / region) would otherwise rank it. A lead is
    delivered only on the research turn, via the outcome."""
    for meta in ({}, {"one_hop": True}, {"scope_class": "region"}):
        v = base_view()
        v["claims"] = [_claim(
            "c_lead_severwick", "loc_severwick_monastery",
            "Nothing here on that - the burned province keeps the deep dragon-lore.",
            method="source_records", scope="lead", hours=1, **meta)]
        out = assemble(v)
        assert not list(VALIDATOR.iter_errors(out.envelope))
        packed = {c["claim_id"] for c in out.envelope["salient_claims"]}
        assert "c_lead_severwick" not in packed, (meta, packed)
        reasons = {r["claim_id"]: r["reason"] for r in out.receipt["claims"]}
        assert reasons["c_lead_severwick"] == "source_lead_not_ambient", reasons


def test_offscene_source_records_finding_is_not_promoted_ambiently():
    """A `source_records` research finding about an OFF-SCENE subject cannot be
    promoted into ambient prose by a one_hop link back to the co-located source;
    the same finding about a PRESENT subject stays eligible."""
    present = "npc_harrowdown_jorun_pike"  # in base_view scene
    v = base_view()
    v["claims"] = [
        _claim("c_offscene", "creature_severwick_wyrm",
               "Severwick's rolls call the wyrm half-grown.", method="source_records",
               scope="appraisal_tier_1", hours=2, one_hop=True),
        _claim("c_present", present, "The archive takes his measure: dire.",
               method="source_records", scope="appraisal_tier_1", hours=2),
    ]
    out = assemble(v)
    packed = {c["claim_id"] for c in out.envelope["salient_claims"]}
    reasons = {r["claim_id"]: r["reason"] for r in out.receipt["claims"]}
    assert "c_offscene" not in packed
    assert reasons["c_offscene"] == "offscene_source_lore_not_ambient", reasons
    assert "c_present" in packed  # in-scene source knowledge is still eligible


def test_source_lead_suppression_is_deterministic():
    v = base_view()
    v["claims"] = [_claim("c_lead", "loc_severwick_monastery", "a lead.",
                          method="source_records", scope="lead", hours=1, one_hop=True)]
    a = assemble(copy.deepcopy(v))
    b = assemble(copy.deepcopy(v))
    assert a.canonical == b.canonical and a.content_hash == b.content_hash


def test_trace_none_at_world_start_is_schema_legal():
    v = base_view()
    v["last_resolution"] = None
    out = assemble(v)
    assert not list(VALIDATOR.iter_errors(out.envelope))
    assert out.envelope["assembly"]["last_resolution"] is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
