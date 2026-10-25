"""Crypto-shredding for player-authored text (synthesis §2.1).

Player free text is personal data. It is envelope-encrypted at append
time and decrypted transparently on the owner's read path; deleting the
account's data-encryption key (DEK) is the erasure — ciphertext in the
log, dumps, and backups becomes permanently unreadable while every
event still folds (engine-required structured enums stay plaintext and
no projection ever depends on the encrypted values).

Scheme (AES-256-GCM via the ``cryptography`` package — engine extra
``crypto``):

- **One DEK per account world.** Worlds and accounts are 1:1 (Sprint-2
  decision 1: each account owns its own world schema), so the key lives
  in the world schema's ``account_key`` singleton row (migration 0009).
  It is generated lazily at the first append that needs it;
  :func:`ensure_account_key` is also exported so the API can mint it
  eagerly at invite-code claim time.
- **Envelope wrap:** when ``EVERQUILL_MASTER_KEY`` (64 hex chars) is set,
  the stored DEK is wrapped with AES-GCM under that KEK
  (``wrap_mode='kek-v1'``); without it the DEK is stored raw
  (``wrap_mode='raw'``, dev/test only — production sets the master key
  so a DB backup alone can never decrypt).
- **Deterministic (SIV-style) nonces:** the nonce is derived as
  ``sha256(domain || dek || key_id || plaintext)[:12]``. Identical
  (key, plaintext) pairs produce identical ciphertext — an equality
  leak we accept deliberately so the byte-identity determinism suite
  (same seed + script ⇒ identical event dumps) holds; distinct
  plaintexts can never collide a (key, nonce) pair.
- **Shred:** delete the ``account_key`` row (owner/operator connection —
  app_role holds no DELETE). Reads then render ``[shredded]``; folds
  and rebuilds are unaffected.

What gets encrypted is registered per event type in
:data:`PLAYER_TEXT_PATHS` — the store applies it to the INSERTED row
only; the rows handed back to the caller (the owner's own turn) keep
plaintext. ``fresh_reset`` deliberately does NOT clear ``account_key``:
the key belongs to the account, not to world canon, and identical
replays must re-encrypt identically.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Any

__all__ = [
    "MASTER_KEY_ENV",
    "SHREDDED_TEXT",
    "PLAYER_TEXT_PATHS",
    "EncryptionUnavailableError",
    "ShreddedError",
    "is_encrypted",
    "encrypt_text",
    "decrypt_text",
    "encrypt_payload_fields",
    "decrypt_payload",
    "ensure_account_key",
    "load_account_key",
    "shred_account_key",
    "master_key_configured",
]

MASTER_KEY_ENV = "EVERQUILL_MASTER_KEY"

#: What owners see where a shredded (key-deleted) value used to be.
SHREDDED_TEXT = "[shredded]"

#: Player-authored free-text fields, per event type: the ONLY payload
#: paths the store encrypts. Everything else in a payload is
#: engine-required structure and stays plaintext (folds, contracts and
#: audits read it). Registry is append-only — journal free text joins
#: here when journaling events ship.
PLAYER_TEXT_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "intent_parsed": (
        ("intent", "approach"),
        ("intent", "dialogue", "quoted_speech"),
        # The player's own words for a span ("until the caravan leaves"); the
        # engine binds the closed until/amount/unit fields instead (claude-011).
        ("intent", "duration_hint", "text"),
    ),
}

_NONCE_DOMAIN = b"everquill.enc.nonce.v1"


class EncryptionUnavailableError(RuntimeError):
    """The ``cryptography`` package is not installed but an append needs
    to encrypt player text. Install the engine's ``crypto`` extra
    (``pip install cryptography>=42``); the API deploy needs it in root
    requirements.txt."""


class ShreddedError(LookupError):
    """A strict decrypt met ciphertext whose key has been deleted."""


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise EncryptionUnavailableError(
            "player-text encryption needs the 'cryptography' package "
            "(engine extra: everquill-engine[crypto]); refusing to store "
            "player-authored text in plaintext (HIGH-8)"
        ) from exc
    return AESGCM(key)


def _master_key(env: os._Environ[str] | dict[str, str] | None = None) -> bytes | None:
    raw = (os.environ if env is None else env).get(MASTER_KEY_ENV)
    if not raw:
        return None
    key = bytes.fromhex(raw.strip())
    if len(key) != 32:
        raise ValueError(f"{MASTER_KEY_ENV} must be 64 hex chars (256-bit)")
    return key


def master_key_configured(env: os._Environ[str] | dict[str, str] | None = None) -> bool:
    """True iff EVERQUILL_MASTER_KEY is present AND well-formed. Raises
    ValueError on a present-but-malformed key — a bad key must fail LOUD,
    never fall back to fail-open raw DEK storage (the fail-closed gate in
    everquill_engine.security consumes this)."""
    return _master_key(env) is not None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def is_encrypted(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == {"$enc"}


def encrypt_text(dek: bytes, key_id: str, plaintext: str) -> dict[str, Any]:
    """One string → one ``{"$enc": …}`` marker. Deterministic per
    (dek, key_id, plaintext) — see the module docstring."""
    nonce = hashlib.sha256(
        _NONCE_DOMAIN + dek + key_id.encode("utf-8") + plaintext.encode("utf-8")
    ).digest()[:12]
    ciphertext = _aesgcm(dek).encrypt(
        nonce, plaintext.encode("utf-8"), key_id.encode("utf-8")
    )
    return {
        "$enc": {"v": 1, "key_id": key_id, "n": _b64(nonce), "ct": _b64(ciphertext)}
    }


def decrypt_text(dek: bytes, marker: dict[str, Any]) -> str:
    body = marker["$enc"]
    plaintext = _aesgcm(dek).decrypt(
        _unb64(body["n"]), _unb64(body["ct"]), body["key_id"].encode("utf-8")
    )
    return plaintext.decode("utf-8")


def encrypt_payload_fields(
    payload: dict[str, Any],
    event_type: str,
    dek: bytes,
    key_id: str,
) -> dict[str, Any]:
    """Encrypt the registered player-text paths of one payload. Returns a
    new dict; the input is never mutated. Absent/null/already-encrypted
    values pass through."""
    paths = PLAYER_TEXT_PATHS.get(event_type)
    if not paths:
        return payload
    out = dict(payload)
    for path in paths:
        _encrypt_at_path(out, path, dek, key_id)
    return out


def _encrypt_at_path(container: dict[str, Any], path: tuple[str, ...], dek, key_id) -> None:
    node = container
    for step in path[:-1]:
        child = node.get(step)
        if not isinstance(child, dict) or is_encrypted(child):
            return
        child = dict(child)
        node[step] = child
        node = child
    leaf = path[-1]
    value = node.get(leaf)
    if isinstance(value, str) and value:
        node[leaf] = encrypt_text(dek, key_id, value)


def decrypt_payload(value: Any, dek: bytes | None, *, strict: bool = False) -> Any:
    """Recursively resolve every ``{"$enc": …}`` marker in a JSON value.

    ``dek=None`` means the key is gone (shredded) or unavailable: markers
    render as :data:`SHREDDED_TEXT` — or raise :class:`ShreddedError`
    when ``strict``. Non-marker values pass through untouched."""
    if is_encrypted(value):
        if dek is None:
            if strict:
                raise ShreddedError("encrypted value's key has been deleted (shredded)")
            return SHREDDED_TEXT
        return decrypt_text(dek, value)
    if isinstance(value, dict):
        return {k: decrypt_payload(v, dek, strict=strict) for k, v in value.items()}
    if isinstance(value, list):
        return [decrypt_payload(v, dek, strict=strict) for v in value]
    return value


# --- key storage (account_key singleton, migration 0009) --------------------------


def _wrap_dek(dek: bytes, key_id: str) -> tuple[bytes, str]:
    kek = _master_key()
    if kek is None:
        return dek, "raw"
    nonce = secrets.token_bytes(12)
    wrapped = _aesgcm(kek).encrypt(nonce, dek, key_id.encode("utf-8"))
    return nonce + wrapped, "kek-v1"


def _unwrap_dek(stored: bytes, wrap_mode: str, key_id: str) -> bytes:
    if wrap_mode == "raw":
        return bytes(stored)
    if wrap_mode == "kek-v1":
        kek = _master_key()
        if kek is None:
            raise RuntimeError(
                f"account key {key_id!r} is KEK-wrapped but {MASTER_KEY_ENV} is unset"
            )
        stored = bytes(stored)
        return _aesgcm(kek).decrypt(stored[:12], stored[12:], key_id.encode("utf-8"))
    raise ValueError(f"unknown wrap_mode {wrap_mode!r}")


def load_account_key(cur) -> tuple[str, bytes] | None:
    """The world's (key_id, DEK), or None when absent/shredded."""
    cur.execute("SELECT key_id, dek, wrap_mode FROM account_key")
    row = cur.fetchone()
    if row is None:
        return None
    key_id, stored, wrap_mode = row
    return key_id, _unwrap_dek(stored, wrap_mode, key_id)


def ensure_account_key(cur) -> tuple[str, bytes]:
    """The world's (key_id, DEK), generating and storing it on first use.

    Safe under the store's world lock (one writer per world). Exported
    for the API to call at invite-code claim time too — generation is
    idempotent either way. NOTE: once a key has been SHREDDED this mints
    a fresh key; pre-shred ciphertext stays unreadable forever.
    """
    existing = load_account_key(cur)
    if existing is not None:
        return existing
    dek = secrets.token_bytes(32)
    key_id = "dek_" + secrets.token_hex(8)
    stored, wrap_mode = _wrap_dek(dek, key_id)
    cur.execute(
        "INSERT INTO account_key (singleton, key_id, dek, wrap_mode)"
        " VALUES (true, %s, %s, %s) ON CONFLICT (singleton) DO NOTHING",
        (key_id, stored, wrap_mode),
    )
    after = load_account_key(cur)
    if after is None:  # pragma: no cover - only under exotic isolation
        raise RuntimeError("account_key insert raced and vanished")
    return after


def shred_account_key(cur, world_id: str | None = None) -> bool:
    """THE erasure: delete the world's DEK row. Owner/operator connections
    only (app_role holds no DELETE on account_key). Returns whether a key
    existed. Every ciphertext written under it is unreadable from this
    commit on — including in dumps and backups of the event log.

    Pass the world id to erase that world's plaintext test capture too
    (public.test_turn_capture, written only for accounts an owner flagged):
    it sits outside the encrypted log, so deleting the key alone would leave
    it readable (audit 2026-10-24, k3 F3)."""
    cur.execute("DELETE FROM account_key")
    existed = cur.rowcount > 0
    if world_id is not None:
        cur.execute("SELECT to_regclass('public.test_turn_capture') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("DELETE FROM public.test_turn_capture WHERE world_id = %s", (world_id,))
    return existed
