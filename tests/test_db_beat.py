"""Two-phase commit beat, DB half (skips cleanly without DATABASE_URL).

Covers: assess-without-resolving (pending row, zero canon, zero dice),
confirm under the ORIGINAL command_id with the ORIGINAL stored intent,
world-activity expiry ("the moment has passed", never a stale
resolution), idempotency in every direction, the not-a-projection rule,
and the 0006 rng-uniqueness constraint.
"""

from __future__ import annotations

import pytest

from everquill_engine import crypto
from everquill_engine.beat import (
    BeatIntentMismatchError,
    ConfirmationExpiredError,
    NoPendingConfirmationError,
    assess_or_execute,
    confirm,
)
from everquill_engine.chargen import chargen_events, roll_character
from everquill_engine.events import EventSpec, EventType
from everquill_engine.genesis import genesis_specs
from everquill_engine.store import (
    append_command,
    decrypt_event_payload,
    execute_command,
    fresh_reset,
    load_fold_state,
    rebuild_projections,
)
from everquill_engine.world import load_world
from tests.harness import FIXTURE_WORLD

WORLD = load_world(FIXTURE_WORLD)
SEED = 42

ROUTINE_INTENT = {
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
DIRE_INTENT = {
    "action_type": "physical",
    "target_entity_ids": ["npc_dev_torvald"],
    "approach": "challenge the drillmaster to real steel",
    "stat_hint": "might",
    "dialogue": None,
    "plausibility_hint": "dubious",
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
    fresh_reset(db_conn)
    execute_command(db_conn, "genesis", lambda _s: genesis_specs(WORLD, SEED))
    rolled = roll_character(SEED, "pc", name="the Quill-touched")
    specs = chargen_events(rolled, location_id="loc.dev.tavern", region="dev", world_time=0)
    execute_command(db_conn, "chargen:pc", lambda _s: specs)
    return db_conn


def _events_for(conn, command_id):
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_type, payload FROM event WHERE command_id = %s ORDER BY id",
                (command_id,),
            )
            return cur.fetchall()


def _pending_row(conn, command_id):
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, character_id, intent, created_world_time,"
                " expires_world_time, confirmed_event_id"
                " FROM pending_confirmation WHERE command_id = %s",
                (command_id,),
            )
            return cur.fetchone()


def _world_state(conn):
    with conn.transaction():
        with conn.cursor() as cur:
            return load_fold_state(cur)


class TestAutoCommit:
    def test_guarded_intent_resolves_inline_no_pending_row(self, world_conn):
        result = assess_or_execute(world_conn, "beat_auto_1", ROUTINE_INTENT, world=WORLD)
        assert result.status == "resolved"
        assert result.assessment.confirmation_required is False
        assert result.assessment.risk_label == "guarded"
        assert result.resolution is not None and result.append_result.event_rows
        assert _events_for(world_conn, "beat_auto_1")
        assert _pending_row(world_conn, "beat_auto_1") is None

    def test_duplicate_auto_commit_absorbed(self, world_conn):
        assess_or_execute(world_conn, "beat_auto_1", ROUTINE_INTENT, world=WORLD)
        again = assess_or_execute(world_conn, "beat_auto_1", ROUTINE_INTENT, world=WORLD)
        assert again.status == "absorbed"


class TestAssessWithoutResolving:
    def test_dire_returns_assessment_zero_canon_zero_dice(self, world_conn):
        before = _world_state(world_conn)
        result = assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)
        assert result.status == "pending"
        a = result.assessment
        assert a.confirmation_required is True
        assert a.tier == "hopeless" and a.risk_label == "suicidal"
        assert a.expires_world_time == a.created_world_time + 10
        assert "Proceed?" in a.summary
        # WITHOUT resolving: no events, no dice drawn, no world time spent.
        assert _events_for(world_conn, "beat_dire_1") == []
        after = _world_state(world_conn)
        assert after.world["rng_counters"] == before.world["rng_counters"]
        assert after.world["world_time"] == before.world["world_time"]
        row = _pending_row(world_conn, "beat_dire_1")
        assert row is not None and row[0] == "pending"
        # Intent stored verbatim in STRUCTURE; the player-authored approach
        # is envelope-encrypted at rest and decrypts back exactly.
        stored_intent = dict(row[2])
        assert crypto.is_encrypted(stored_intent["approach"])
        with world_conn.cursor() as cur:
            _key_id, dek = crypto.load_account_key(cur)
        world_conn.rollback()
        assert crypto.decrypt_payload(stored_intent, dek) == DIRE_INTENT

    def test_repeat_assess_is_idempotent(self, world_conn):
        first = assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)
        second = assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)
        assert second.status == "pending"
        assert second.assessment.created_world_time == first.assessment.created_world_time
        assert second.assessment.expires_world_time == first.assessment.expires_world_time
        # Still exactly one pending row, still zero canon.
        assert _events_for(world_conn, "beat_dire_1") == []

    def test_pending_row_is_not_a_projection(self, world_conn):
        """Rebuild (truncate + replay) must leave the pending beat alone —
        no event exists for it, and it must survive a rebuild intact."""
        assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)
        rebuild_projections(world_conn)
        row = _pending_row(world_conn, "beat_dire_1")
        assert row is not None and row[0] == "pending"


class TestConfirm:
    def test_confirm_resolves_under_original_command_and_intent(self, world_conn):
        assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)
        result = confirm(world_conn, "beat_dire_1", world=WORLD)
        assert result.status == "resolved"
        events = _events_for(world_conn, "beat_dire_1")
        types = [e[0] for e in events]
        assert "intent_parsed" in types and "outcome_resolved" in types
        (intent_payload,) = [p for t, p in events if t == "intent_parsed"]
        # ORIGINAL intent, verbatim — through the owner read path (the
        # stored approach is ciphertext at rest).
        assert crypto.is_encrypted(intent_payload["intent"]["approach"])
        with world_conn.cursor() as cur:
            readable = decrypt_event_payload(cur, intent_payload)
        world_conn.rollback()
        assert readable["intent"] == DIRE_INTENT
        (outcome_payload,) = [p for t, p in events if t == "outcome_resolved"]
        assert outcome_payload["tier_resolved"] == "hopeless"
        assert outcome_payload["outcome_tier"] == "miss"
        row = _pending_row(world_conn, "beat_dire_1")
        assert row[0] == "confirmed" and row[5] is not None  # confirmed_event_id set

    def test_duplicate_confirm_absorbed(self, world_conn):
        assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)
        confirm(world_conn, "beat_dire_1", world=WORLD)
        before = _events_for(world_conn, "beat_dire_1")
        again = confirm(world_conn, "beat_dire_1", world=WORLD)
        assert again.status == "absorbed"
        assert _events_for(world_conn, "beat_dire_1") == before

    def test_confirm_without_assess_raises(self, world_conn):
        with pytest.raises(NoPendingConfirmationError):
            confirm(world_conn, "beat_never_assessed", world=WORLD)


class TestExpiry:
    def _advance_world(self, conn, minutes=10):
        """Subsequent world activity: auto-commit actions until the clock
        has moved >= minutes (physical costs 10)."""
        start = _world_state(conn).world["world_time"]
        n = 0
        while _world_state(conn).world["world_time"] - start < minutes:
            n += 1
            assess_or_execute(conn, f"beat_filler_{n}", ROUTINE_INTENT, world=WORLD)
            assert n < 10, "world clock is not advancing"

    def test_confirm_after_expiry_is_a_clean_error_never_stale(self, world_conn):
        assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)
        self._advance_world(world_conn, 10)
        with pytest.raises(ConfirmationExpiredError, match="moment has passed"):
            confirm(world_conn, "beat_dire_1", world=WORLD)
        # No stale resolution: zero canon under the original command id.
        assert _events_for(world_conn, "beat_dire_1") == []
        assert _pending_row(world_conn, "beat_dire_1")[0] == "expired"
        # And the error is stable on retry.
        with pytest.raises(ConfirmationExpiredError):
            confirm(world_conn, "beat_dire_1", world=WORLD)
        # Re-assessing a burned command id is also refused (fresh id, fresh beat).
        with pytest.raises(ConfirmationExpiredError):
            assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)

    def test_confirm_just_before_expiry_still_resolves(self, world_conn):
        assess_or_execute(world_conn, "beat_dire_1", DIRE_INTENT, world=WORLD)
        # 5 minutes of activity (observation costs 5): still inside the window.
        assess_or_execute(
            world_conn,
            "beat_filler_obs",
            {**ROUTINE_INTENT, "action_type": "observation",
             "approach": "watch the room"},
            world=WORLD,
        )
        result = confirm(world_conn, "beat_dire_1", world=WORLD)
        assert result.status == "resolved"


class TestIntentBinding:
    """A pending command_id is bound to ONE canonical intent.

    A→B-retry surfaces the STORED A and a mismatch; confirm still resolves
    A; A→A is idempotent and returns the stored intent."""

    def test_reassess_with_different_intent_is_a_mismatch_showing_stored(self, world_conn):
        assess_or_execute(world_conn, "beat_bind_1", DIRE_INTENT, world=WORLD)
        with pytest.raises(BeatIntentMismatchError) as exc:
            # A harmless routine redeclaration under the SAME command id.
            assess_or_execute(world_conn, "beat_bind_1", ROUTINE_INTENT, world=WORLD)
        # The STORED (dire) intent rides on the error — never the retry's B.
        assert exc.value.stored_intent == DIRE_INTENT
        # Confirm still resolves the ORIGINAL A (the dire one).
        result = confirm(world_conn, "beat_bind_1", world=WORLD)
        assert result.status == "resolved"
        (outcome_payload,) = [
            p for t, p in _events_for(world_conn, "beat_bind_1") if t == "outcome_resolved"
        ]
        assert outcome_payload["tier_resolved"] == "hopeless"

    def test_reassess_with_same_intent_is_idempotent_and_returns_stored(self, world_conn):
        first = assess_or_execute(world_conn, "beat_bind_2", DIRE_INTENT, world=WORLD)
        again = assess_or_execute(world_conn, "beat_bind_2", DIRE_INTENT, world=WORLD)
        assert again.status == "pending"
        assert again.stored_intent == DIRE_INTENT
        assert again.assessment.created_world_time == first.assessment.created_world_time
        # Still exactly one pending row, still zero canon.
        assert _events_for(world_conn, "beat_bind_2") == []


class TestRngUniqueness:
    """The 0006 unique index makes a re-committed (stream,
    index) draw a loud failure, never a silent double-spend."""

    def test_duplicate_draw_rejected(self, world_conn):
        def spec(command_suffix):
            return EventSpec(
                stream_id="character:pc",
                event_type=EventType.INTENT_PARSED,
                world_time=0,
                rng={"stream": ["character:pc", "action:physical"], "index": 77,
                     "rolls": [3, 4]},
                payload={"probe": command_suffix},
            )

        append_command(world_conn, "rng_dup_1", [spec(1)])
        with pytest.raises(ValueError, match="duplicate rng draw"):
            append_command(world_conn, "rng_dup_2", [spec(2)])
