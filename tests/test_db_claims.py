"""Claim lifecycle v2 against the real store (claim lifecycle; skips without DB).

The write-time probe runs inside the append transaction and stamps its
verdicts as EVENTS; the claim table stays a rebuildable projection.
Covers: corroboration with distinct provenance roots, THE echo-chamber
rule (one root retold three times must NOT corroborate), write-time
contradiction (contest + supersede), lifecycle-event replay equivalence,
and the migrated-v1-claim path.
"""

from __future__ import annotations

import pytest

from everquill_engine.events import EventSpec, EventType
from everquill_engine.store import (
    append_command,
    canonical_projection_dump,
    fresh_reset,
    rebuild_projections,
)


def _anchor(n=1):
    return EventSpec(
        stream_id="character:pc",
        event_type=EventType.INTENT_PARSED,
        world_time=0,
        payload_version=2,
        payload={"character_id": "pc", "intent": {"approach": f"anchor {n}"},
                 "source": "test"},
    )


def _claim_spec(
    claim_id: str,
    *,
    predicate: str = "common_knowledge",
    value_text: str | None = "the keeper forgets no tab",
    method: str = "conversation",
    acquisition: str = "told",
    root: int = 1,
    strength: int = 60,
    text: str | None = None,
    world_time: int = 0,
) -> EventSpec:
    return EventSpec(
        stream_id="character:pc",
        event_type=EventType.CLAIM_WRITTEN,
        world_time=world_time,
        payload_version=2,
        payload={
            "claim_id": claim_id,
            "believer_id": "pc",
            "claim": {
                "subject_entity_id": "npc.dev.hedda",
                "predicate": predicate,
                "value_text": value_text,
                "value_num": None,
                "value_range": None,
                "world_valid": None,
                "claim_text": text or value_text or "t",
                "layer": "inquiry",
                "source": "s",
                "observer": "pc",
                "method": method,
                "acquisition_method": acquisition,
                "source_agent_id": None,
                "world_date": "Day 1, 06:00",
                "scope": "local",
                "confidence": "uncorroborated",
            },
            "provenance_root_event_id": root,
            "derived_from_claim_id": None,
            "hop_count": 1 if acquisition in ("told", "rumor", "overheard") else 0,
            "journal_flag": False,
            "strength": strength,
        },
    )


def _claim_row(conn, claim_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, strength, contested_by_claim_id, superseded_by_claim_id,"
            " superseded_reason FROM claim WHERE claim_id = %s",
            (claim_id,),
        )
        row = cur.fetchone()
    conn.rollback()
    return None if row is None else {
        "status": row[0], "strength": row[1], "contested_by": row[2],
        "superseded_by": row[3], "reason": row[4],
    }


def _evidence_roots(conn, claim_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT root_event_id FROM claim_evidence WHERE claim_id = %s ORDER BY event_id",
            (claim_id,),
        )
        roots = [r[0] for r in cur.fetchall()]
    conn.rollback()
    return roots


def _event_types(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT event_type FROM event ORDER BY id")
        types = [r[0] for r in cur.fetchall()]
    conn.rollback()
    return types


@pytest.fixture()
def clean_conn(db_conn):
    fresh_reset(db_conn)
    append_command(db_conn, "seed", [_anchor()])
    return db_conn


class TestEchoChamber:
    def test_one_root_retold_three_times_never_corroborates(self, clean_conn):
        """THE echo-chamber rule (synthesis pitfall 5): retellings of one
        provenance root raise strength only. Corroboration demands a
        SECOND root."""
        append_command(clean_conn, "c1", [_claim_spec("c1", root=1)])
        append_command(clean_conn, "c2", [_claim_spec("c2", root=1)])
        append_command(clean_conn, "c3", [_claim_spec("c3", root=1)])
        row = _claim_row(clean_conn, "c1")
        assert row["status"] == "asserted"  # NOT corroborated
        assert row["strength"] == 180       # 3 x told(60), undecayed
        assert _evidence_roots(clean_conn, "c1") == [1, 1, 1]
        # the retellings became evidence, never rows of their own
        assert _claim_row(clean_conn, "c2") is None
        assert _claim_row(clean_conn, "c3") is None
        types = _event_types(clean_conn)
        assert types.count("claim_written") == 1
        assert types.count("claim_corroborated") == 2

        # A DISTINCT root flips it.
        append_command(clean_conn, "c4", [_claim_spec("c4", root=999)])
        row = _claim_row(clean_conn, "c1")
        assert row["status"] == "corroborated"
        assert row["strength"] == 240
        assert set(_evidence_roots(clean_conn, "c1")) == {1, 999}

    def test_an_authored_rumor_heard_twice_stays_one_source(self, clean_conn):
        """Authored rumor seeds root at a negative id derived from their text
        (research.authored_rumor_root), so two hearings share a root."""
        from everquill_engine.resolver.research import authored_rumor_root

        root = authored_rumor_root("Dunmere posted rat bounties again")
        append_command(clean_conn, "r1", [_claim_spec("r1", acquisition="rumor", root=root)])
        append_command(clean_conn, "r2", [_claim_spec("r2", acquisition="rumor", root=root)])
        assert _claim_row(clean_conn, "r1")["status"] == "asserted"
        assert _evidence_roots(clean_conn, "r1") == [root, root]


class TestWriteTimeContradiction:
    def test_stronger_observation_supersedes_the_rumor(self, clean_conn):
        append_command(clean_conn, "t1", [_claim_spec(
            "t1", predicate="threat_assessed", value_text="RISKY",
            method="rumor", acquisition="rumor", strength=35, root=1,
        )])
        append_command(clean_conn, "t2", [_claim_spec(
            "t2", predicate="threat_assessed", value_text="DESPERATE",
            method="witnessed", acquisition="observed", strength=100, root=2,
        )])
        old = _claim_row(clean_conn, "t1")
        assert old["status"] == "superseded"
        assert old["superseded_by"] == "t2"
        assert old["reason"] == "direct_observation"
        assert _claim_row(clean_conn, "t2")["status"] == "asserted"
        assert "claim_superseded" in _event_types(clean_conn)

    def test_weaker_challenger_contests_both_ways_both_stay_active(self, clean_conn):
        append_command(clean_conn, "t1", [_claim_spec(
            "t1", predicate="threat_assessed", value_text="DESPERATE",
            method="witnessed", acquisition="observed", strength=100, root=1,
        )])
        append_command(clean_conn, "t2", [_claim_spec(
            "t2", predicate="threat_assessed", value_text="RISKY",
            method="rumor", acquisition="rumor", strength=35, root=2,
        )])
        first, second = _claim_row(clean_conn, "t1"), _claim_row(clean_conn, "t2")
        assert first["status"] == "contested" and first["contested_by"] == "t2"
        assert second["status"] == "contested" and second["contested_by"] == "t1"
        assert _event_types(clean_conn).count("claim_contested") == 2

    def test_non_exclusive_predicates_accumulate_without_conflict(self, clean_conn):
        append_command(clean_conn, "k1", [_claim_spec("k1", value_text="fact A")])
        append_command(clean_conn, "k2", [_claim_spec("k2", value_text="fact B")])
        assert _claim_row(clean_conn, "k1")["status"] == "asserted"
        assert _claim_row(clean_conn, "k2")["status"] == "asserted"
        assert "claim_contested" not in _event_types(clean_conn)


class TestLifecycleReplay:
    def test_rebuild_reproduces_lifecycle_projections_exactly(self, clean_conn):
        """Transitions are events; truncate-and-replay through the folds
        (incl. upcasters) must land on the identical claim image."""
        append_command(clean_conn, "c1", [_claim_spec("c1", root=1)])
        append_command(clean_conn, "c2", [_claim_spec("c2", root=1)])
        append_command(clean_conn, "c3", [_claim_spec("c3", root=999)])
        append_command(clean_conn, "t1", [_claim_spec(
            "t1", predicate="threat_assessed", value_text="RISKY",
            method="rumor", acquisition="rumor", strength=35, root=1,
        )])
        append_command(clean_conn, "t2", [_claim_spec(
            "t2", predicate="threat_assessed", value_text="DESPERATE",
            method="witnessed", acquisition="observed", strength=100, root=2,
        )])
        live = canonical_projection_dump(clean_conn)
        rebuild_projections(clean_conn)
        assert canonical_projection_dump(clean_conn) == live

    def test_migrated_v1_claims_join_the_same_lifecycle(self, clean_conn):
        """A v1-shaped claim (legacy writer) upcasts to observed_statement;
        an identical v1 retelling corroborates it through the same probe."""
        v1_payload = {
            "claim_id": "old1", "believer_id": "pc",
            "claim": {
                "subject_entity_id": "npc.dev.hedda", "claim_text": "legacy text",
                "value_or_range": None, "layer": "inquiry", "source": "s",
                "observer": "pc", "method": "witnessed",
                "world_date": "Day 1, 06:00", "scope": "local",
                "confidence": "consistent",
            },
            "provenance_root_event_id": 1, "hop_count": 0, "journal_flag": False,
        }
        spec = EventSpec(
            stream_id="character:pc", event_type=EventType.CLAIM_WRITTEN,
            world_time=0, payload=v1_payload,  # payload_version defaults to 1
        )
        append_command(clean_conn, "old1", [spec])
        with clean_conn.cursor() as cur:
            cur.execute(
                "SELECT predicate, acquisition_method, strength FROM claim"
                " WHERE claim_id = 'old1'"
            )
            assert cur.fetchone() == ("observed_statement", "observed", 100)
        clean_conn.rollback()
        # identical retelling from a distinct root corroborates the v1 row
        retell = EventSpec(
            stream_id="character:pc", event_type=EventType.CLAIM_WRITTEN,
            world_time=0,
            payload={**v1_payload, "claim_id": "old2", "provenance_root_event_id": 998},
        )
        append_command(clean_conn, "old2", [retell])
        assert _claim_row(clean_conn, "old1")["status"] == "corroborated"
        live = canonical_projection_dump(clean_conn)
        rebuild_projections(clean_conn)
        assert canonical_projection_dump(clean_conn) == live
