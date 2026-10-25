"""Crypto-shredding end to end (encrypted player text; skips without DB).

Player-authored text (intent approach + quoted speech) is encrypted at
append under the world's account key; the owner's turn response and the
owner read path see plaintext; DELETING the key is the erasure — dumps
hold no plaintext, decryption renders [shredded], and every event still
folds/rebuilds (engine-required enums stay plaintext).
"""

from __future__ import annotations

import pytest

from everquill_engine.crypto import (
    SHREDDED_TEXT,
    ensure_account_key,
    is_encrypted,
    load_account_key,
    shred_account_key,
)
from everquill_engine.events import EventSpec, EventType
from everquill_engine.store import (
    append_command,
    canonical_event_dump,
    canonical_projection_dump,
    decrypt_event_payload,
    fresh_reset,
    rebuild_projections,
)

APPROACH = "SECRET_APPROACH bribe the gatekeeper with my last sovereign"
SPEECH = "SECRET_SPEECH the password is thistledown"


def _intent_spec():
    return EventSpec(
        stream_id="character:pc",
        event_type=EventType.INTENT_PARSED,
        world_time=0,
        payload_version=2,
        payload={
            "character_id": "pc",
            "intent": {
                "action_type": "social",
                "target_entity_ids": ["npc_dev_hedda"],
                "approach": APPROACH,
                "stat_hint": None,
                "dialogue": {"addressee_id": "npc_dev_hedda", "quoted_speech": SPEECH},
                "plausibility_hint": "plausible",
                "duration_hint": None,
                "ambiguity_flags": [],
                "addressee": None,
                "speech_act": None,
                "topic_ids": [],
                "transaction": None,
                "invoked_law_ids": [],
                "movement_scope": None,
            },
            "source": "parser",
        },
    )


def _shred(conn) -> bool:
    with conn.transaction():
        with conn.cursor() as cur:
            return shred_account_key(cur)


@pytest.fixture()
def clean_conn(db_conn):
    fresh_reset(db_conn)
    _shred(db_conn)  # each test mints (and owns) a fresh key
    return db_conn


class TestEncryptionAtAppend:
    def test_stored_log_holds_ciphertext_owner_rows_hold_plaintext(self, clean_conn):
        result = append_command(clean_conn, "turn1", [_intent_spec()])
        # The owner's own turn (the AppendResult) is plaintext …
        intent = result.event_rows[0]["payload"]["intent"]
        assert intent["approach"] == APPROACH
        assert intent["dialogue"]["quoted_speech"] == SPEECH
        # … the LOG is not: no raw utterance anywhere in the dump.
        dump = canonical_event_dump(clean_conn)
        assert APPROACH not in dump and SPEECH not in dump
        assert "SECRET_" not in dump
        # engine-required structure stays plaintext for audits
        assert '"action_type": "social"'.replace(" ", "") in dump.replace(" ", "")

    def test_owner_read_path_decrypts_transparently(self, clean_conn):
        append_command(clean_conn, "turn1", [_intent_spec()])
        with clean_conn.cursor() as cur:
            cur.execute("SELECT payload FROM event WHERE command_id = 'turn1'")
            stored = cur.fetchone()[0]
            assert is_encrypted(stored["intent"]["approach"])
            readable = decrypt_event_payload(cur, stored)
        clean_conn.rollback()
        assert readable["intent"]["approach"] == APPROACH
        assert readable["intent"]["dialogue"]["quoted_speech"] == SPEECH

    def test_replays_encrypt_byte_identically(self, clean_conn):
        """Determinism suite compatibility: the key survives fresh_reset
        and nonces derive from (key, plaintext), so identical scripts
        produce identical dumps."""
        append_command(clean_conn, "turn1", [_intent_spec()])
        first = canonical_event_dump(clean_conn)
        fresh_reset(clean_conn)
        append_command(clean_conn, "turn1", [_intent_spec()])
        assert canonical_event_dump(clean_conn) == first

    def test_key_is_minted_lazily_once(self, clean_conn):
        with clean_conn.cursor() as cur:
            assert load_account_key(cur) is None
        clean_conn.rollback()
        append_command(clean_conn, "turn1", [_intent_spec()])
        with clean_conn.cursor() as cur:
            key_id_1, _ = load_account_key(cur)
            key_id_2, _ = ensure_account_key(cur)  # F's claim-time hook: idempotent
        clean_conn.rollback()
        assert key_id_1 == key_id_2


class TestShred:
    def test_key_deletion_is_erasure_and_events_still_fold(self, clean_conn):
        append_command(clean_conn, "turn1", [_intent_spec()])
        assert _shred(clean_conn)
        # 1. no plaintext anywhere, before or after the shred
        dump = canonical_event_dump(clean_conn)
        assert "SECRET_" not in dump
        # 2. the owner read path now renders the tombstone, never ciphertext-errors
        with clean_conn.cursor() as cur:
            cur.execute("SELECT payload FROM event WHERE command_id = 'turn1'")
            readable = decrypt_event_payload(cur, cur.fetchone()[0])
        clean_conn.rollback()
        assert readable["intent"]["approach"] == SHREDDED_TEXT
        assert readable["intent"]["dialogue"]["quoted_speech"] == SHREDDED_TEXT
        assert readable["intent"]["action_type"] == "social"  # enums intact
        # 3. the log still folds: full rebuild over the ciphertext rows
        live = canonical_projection_dump(clean_conn)
        assert rebuild_projections(clean_conn) == 1
        assert canonical_projection_dump(clean_conn) == live

    def test_shred_with_a_world_id_erases_its_plaintext_test_capture(self, clean_conn):
        with clean_conn.transaction():
            for world in ("harrowdown--shred-me", "harrowdown--keep-me"):
                clean_conn.execute(
                    "INSERT INTO public.test_turn_capture (world_id, kind, utterance)"
                    " VALUES (%s, 'action', 'I whisper my real name')",
                    (world,),
                )
        with clean_conn.transaction():
            with clean_conn.cursor() as cur:
                shred_account_key(cur, world_id="harrowdown--shred-me")
        with clean_conn.cursor() as cur:
            cur.execute(
                "SELECT world_id FROM public.test_turn_capture"
                " WHERE world_id LIKE 'harrowdown--%-me'"
            )
            left = [r[0] for r in cur.fetchall()]
        with clean_conn.transaction():
            clean_conn.execute(
                "DELETE FROM public.test_turn_capture WHERE world_id LIKE 'harrowdown--%-me'"
            )
        assert left == ["harrowdown--keep-me"]

    def test_post_shred_appends_mint_a_fresh_key(self, clean_conn):
        append_command(clean_conn, "turn1", [_intent_spec()])
        with clean_conn.cursor() as cur:
            old_key_id, _ = load_account_key(cur)
        clean_conn.rollback()
        _shred(clean_conn)
        append_command(clean_conn, "turn2", [_intent_spec()])
        with clean_conn.cursor() as cur:
            new_key_id, _ = load_account_key(cur)
        clean_conn.rollback()
        assert new_key_id != old_key_id
