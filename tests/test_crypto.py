"""Crypto-shredding primitives (pure — DB paths in test_db_crypto).

AES-GCM envelope encryption of player-authored text with deterministic
(SIV-style) nonces so identical (seed, script) replays produce
byte-identical event dumps.
"""

from __future__ import annotations

import pytest

from everquill_engine.crypto import (
    PLAYER_TEXT_PATHS,
    SHREDDED_TEXT,
    ShreddedError,
    decrypt_payload,
    decrypt_text,
    encrypt_payload_fields,
    encrypt_text,
    is_encrypted,
)

DEK = bytes(range(32))
KEY_ID = "dek_test0001"


class TestPrimitives:
    def test_roundtrip(self):
        marker = encrypt_text(DEK, KEY_ID, "sneak past the keeper")
        assert is_encrypted(marker)
        assert marker["$enc"]["key_id"] == KEY_ID
        assert decrypt_text(DEK, marker) == "sneak past the keeper"

    def test_ciphertext_never_contains_plaintext(self):
        marker = encrypt_text(DEK, KEY_ID, "SECRETPHRASE")
        assert "SECRETPHRASE" not in str(marker)

    def test_deterministic_for_identical_inputs(self):
        """Byte-identity determinism: same key + plaintext ⇒ same marker
        (the nonce derives from both — replayed scripts re-encrypt
        identically)."""
        assert encrypt_text(DEK, KEY_ID, "same words") == encrypt_text(
            DEK, KEY_ID, "same words"
        )

    def test_distinct_plaintexts_get_distinct_nonces(self):
        a = encrypt_text(DEK, KEY_ID, "plan A")
        b = encrypt_text(DEK, KEY_ID, "plan B")
        assert a["$enc"]["n"] != b["$enc"]["n"]

    def test_wrong_key_fails_loudly(self):
        from cryptography.exceptions import InvalidTag

        marker = encrypt_text(DEK, KEY_ID, "text")
        with pytest.raises(InvalidTag):
            decrypt_text(bytes(32), marker)


class TestPayloadFields:
    def _payload(self):
        return {
            "character_id": "pc",
            "intent": {
                "action_type": "social",
                "approach": "flatter the keeper outrageously",
                "dialogue": {
                    "addressee_id": "npc_dev_hedda",
                    "quoted_speech": "Finest tavern this side of Dunmere.",
                },
                "target_entity_ids": ["npc_dev_hedda"],
            },
            "source": "parser",
        }

    def test_registered_paths_encrypt_engine_fields_stay_plaintext(self):
        out = encrypt_payload_fields(self._payload(), "intent_parsed", DEK, KEY_ID)
        assert is_encrypted(out["intent"]["approach"])
        assert is_encrypted(out["intent"]["dialogue"]["quoted_speech"])
        # engine-required structure untouched:
        assert out["intent"]["action_type"] == "social"
        assert out["intent"]["dialogue"]["addressee_id"] == "npc_dev_hedda"
        assert out["intent"]["target_entity_ids"] == ["npc_dev_hedda"]

    def test_input_payload_is_not_mutated(self):
        payload = self._payload()
        encrypt_payload_fields(payload, "intent_parsed", DEK, KEY_ID)
        assert payload["intent"]["approach"] == "flatter the keeper outrageously"

    def test_null_dialogue_and_unregistered_types_pass_through(self):
        payload = self._payload()
        payload["intent"]["dialogue"] = None
        out = encrypt_payload_fields(payload, "intent_parsed", DEK, KEY_ID)
        assert out["intent"]["dialogue"] is None
        other = encrypt_payload_fields(self._payload(), "deed_recorded", DEK, KEY_ID)
        assert other["intent"]["approach"] == "flatter the keeper outrageously"

    def test_decrypt_payload_restores_the_owner_view(self):
        out = encrypt_payload_fields(self._payload(), "intent_parsed", DEK, KEY_ID)
        assert decrypt_payload(out, DEK) == self._payload()

    def test_shredded_render_and_strict_mode(self):
        out = encrypt_payload_fields(self._payload(), "intent_parsed", DEK, KEY_ID)
        shredded = decrypt_payload(out, None)
        assert shredded["intent"]["approach"] == SHREDDED_TEXT
        assert shredded["intent"]["dialogue"]["quoted_speech"] == SHREDDED_TEXT
        with pytest.raises(ShreddedError):
            decrypt_payload(out, None, strict=True)

    def test_registry_covers_intent_parsed(self):
        assert ("intent", "approach") in PLAYER_TEXT_PATHS["intent_parsed"]
        assert ("intent", "dialogue", "quoted_speech") in PLAYER_TEXT_PATHS["intent_parsed"]


def test_the_players_duration_words_are_encrypted_closed_fields_are_not():
    """claude-011: duration_hint.text is the player's words; the engine binds
    until / amount / unit, which stay plaintext."""
    payload = {"intent": {"action_type": "rest", "duration_hint": {
        "mode": "until_condition", "text": "until the caravan from Dunmere leaves",
        "until": "dusk", "amount": None, "unit": None,
    }}}
    out = encrypt_payload_fields(payload, "intent_parsed", DEK, KEY_ID)
    hint = out["intent"]["duration_hint"]
    assert is_encrypted(hint["text"])
    assert (hint["mode"], hint["until"]) == ("until_condition", "dusk")
    no_hint = encrypt_payload_fields(
        {"intent": {"duration_hint": None}}, "intent_parsed", DEK, KEY_ID
    )
    assert no_hint["intent"]["duration_hint"] is None
