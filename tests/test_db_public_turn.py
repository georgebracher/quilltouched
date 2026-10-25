"""Canonical public-turn record (Hardening Pass 1; skips no-DB).

Persist the COMPLETE player-visible turn — redacted public outcome + prose
+ assembler meta — as ONE canon record keyed by the turn command_id, so a
retry after response loss returns the SAME record (never a re-resolved
outcome) and a client can rebuild its Chronicle on reconnect.
"""

from __future__ import annotations

import pytest

from everquill_engine.store import (
    public_turn,
    rebuild_projections,
    recent_public_turns,
)
from everquill_engine.views import outcome_public
from tests.harness import FIXTURE_WORLD


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


@pytest.fixture()
def world_conn(db_conn):
    from everquill_engine.chargen import chargen_events, roll_character
    from everquill_engine.genesis import genesis_specs
    from everquill_engine.store import execute_command, fresh_reset
    from everquill_engine.world import load_world

    world = load_world(FIXTURE_WORLD)
    fresh_reset(db_conn)
    execute_command(db_conn, "genesis", lambda _s: genesis_specs(world, 42))
    specs = chargen_events(
        roll_character(42, "pc", name="q"), location_id="loc.dev.tavern",
        region="dev", world_time=0,
    )
    execute_command(db_conn, "chargen:pc", lambda _s: specs)
    return db_conn, world


def _resolve_turn(conn, world, command_id, intent):
    """Resolve an engine turn and canonize its public-turn record."""
    from everquill_engine.beat import assess_or_execute
    from everquill_engine.store import narrate_outcome

    result = assess_or_execute(
        conn, command_id, intent, world=world, character_id="pc",
    )
    outcome = result.append_result.event_rows[result.resolution.outcome_event_index]
    redacted = outcome_public(outcome["payload"])
    narrate_outcome(
        conn, character_id="pc", outcome_event_id=outcome["id"],
        outcome_event_ulid=outcome["event_ulid"], world_time=outcome["world_time"],
        prose=f"Prose for {command_id}.", assembler_version="asm.v1",
        content_hash=f"hash-{command_id}", turn_command_id=command_id,
        public_outcome=redacted,
    )
    return outcome, redacted


def _read(conn, command_id):
    rec = public_turn(conn, command_id)
    conn.rollback()
    return rec


class TestPublicTurnRecord:
    def test_record_holds_redacted_outcome_prose_and_meta(self, world_conn):
        conn, world = world_conn
        outcome, redacted = _resolve_turn(
            conn, world, "turn:1", canned("research", ["npc_dev_sorrel"], stat_hint="lore"),
        )
        rec = _read(conn, "turn:1")
        assert rec is not None
        assert rec["turn_command_id"] == "turn:1"
        assert rec["character_id"] == "pc"
        assert rec["outcome_event_id"] == outcome["id"]
        assert rec["outcome_event_ulid"] == outcome["event_ulid"]
        assert rec["prose"] == "Prose for turn:1."
        assert rec["assembler_version"] == "asm.v1"
        assert rec["content_hash"] == "hash-turn:1"
        assert rec["public_outcome"] == redacted

    def test_response_loss_retry_returns_the_identical_record(self, world_conn):
        """Prose committed, HTTP lost, client retries: the turn command is
        absorbed and re-narration is absorbed, so public_turn returns the
        SAME record — never a re-resolved outcome or forked prose."""
        from everquill_engine.beat import assess_or_execute
        from everquill_engine.store import narrate_outcome

        conn, world = world_conn
        outcome, _ = _resolve_turn(
            conn, world, "turn:1", canned("research", ["npc_dev_sorrel"], stat_hint="lore"),
        )
        before = _read(conn, "turn:1")

        # Retry: re-POST the turn (absorbed — the command already committed)...
        retry = assess_or_execute(
            conn, "turn:1", canned("research", ["npc_dev_sorrel"], stat_hint="lore"),
            world=world, character_id="pc",
        )
        assert retry.status == "absorbed"
        # ...and a re-narration with DIFFERENT prose is absorbed, not forked.
        again = narrate_outcome(
            conn, character_id="pc", outcome_event_id=outcome["id"],
            outcome_event_ulid=outcome["event_ulid"], world_time=outcome["world_time"],
            prose="a totally different take", assembler_version="asm.v2",
            content_hash="other", turn_command_id="turn:1", public_outcome={"x": 1},
        )
        assert again.absorbed

        after = _read(conn, "turn:1")
        assert after == before  # byte-identical record; original prose kept
        assert after["prose"] == "Prose for turn:1."

    def test_record_survives_a_projection_rebuild(self, world_conn):
        """The record is canon in the append-only log — a Tier-1 rebuild
        does not alter what public_turn serves."""
        conn, world = world_conn
        _resolve_turn(
            conn, world, "turn:1", canned("research", ["npc_dev_sorrel"], stat_hint="lore"),
        )
        before = _read(conn, "turn:1")
        rebuild_projections(conn)
        conn.rollback()
        assert _read(conn, "turn:1") == before

    def test_unknown_command_returns_none(self, world_conn):
        conn, _world = world_conn
        assert _read(conn, "turn:never") is None


class TestRecentPublicTurns:
    def test_chronicle_rebuild_returns_turns_oldest_first(self, world_conn):
        conn, world = world_conn
        for i in (1, 2, 3):
            _resolve_turn(
                conn, world, f"turn:{i}",
                canned("research", ["npc_dev_sorrel"], stat_hint="lore"),
            )
            conn.rollback()
        turns = recent_public_turns(conn, "pc", 10)
        conn.rollback()
        assert [t["turn_command_id"] for t in turns] == ["turn:1", "turn:2", "turn:3"]
        assert [t["prose"] for t in turns] == [
            "Prose for turn:1.", "Prose for turn:2.", "Prose for turn:3.",
        ]

    def test_limit_returns_the_newest_n_in_order(self, world_conn):
        conn, world = world_conn
        for i in (1, 2, 3):
            _resolve_turn(
                conn, world, f"turn:{i}",
                canned("research", ["npc_dev_sorrel"], stat_hint="lore"),
            )
            conn.rollback()
        turns = recent_public_turns(conn, "pc", 2)
        conn.rollback()
        assert [t["turn_command_id"] for t in turns] == ["turn:2", "turn:3"]

    def test_since_pages_forward_from_the_watermark(self, world_conn):
        conn, world = world_conn
        for i in (1, 2, 3, 4):
            _resolve_turn(
                conn, world, f"turn:{i}",
                canned("research", ["npc_dev_sorrel"], stat_hint="lore"),
            )
            conn.rollback()
        everything = recent_public_turns(conn, "pc", 10)
        first = everything[0]["narration_event_id"]
        # The two turns right after the watermark, not the newest two.
        page = recent_public_turns(conn, "pc", 2, since=first)
        assert [t["turn_command_id"] for t in page] == ["turn:2", "turn:3"]
        rest = recent_public_turns(conn, "pc", 2, since=page[-1]["narration_event_id"])
        conn.rollback()
        assert [t["turn_command_id"] for t in rest] == ["turn:4"]

    def test_non_positive_n_is_empty(self, world_conn):
        conn, _world = world_conn
        assert recent_public_turns(conn, "pc", 0) == []
