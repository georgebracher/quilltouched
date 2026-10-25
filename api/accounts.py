"""Accounts v1: invite codes, device tokens, per-account worlds (decision 1).

- POST /api/claim exchanges a valid invite code for a random 256-bit device
  token. Only sha256(token) is stored (migration 0007). One account per code.
- Invite codes are HASH-ONLY rows in ``public.invite`` (migration 0010):
  claiming is one atomic ``UPDATE .. WHERE claimed_at IS NULL
  RETURNING`` and unknown/used codes are indistinguishable (uniform
  InviteCodeError -> 403 — no validity-state oracle). Codes in the legacy
  EVERQUILL_INVITE_CODES env var keep working: their hashes are seeded into
  the table at startup (api.main bootstrap) and lazily at claim time.
- Every game request authenticates with ``Authorization: Bearer <token>``.
- Each account owns its OWN Harrowdown: ``world_id = "harrowdown--<prefix>"``
  (prefix = first 8 hex of the account id), stored in Postgres schema
  ``world_<prefix>``. The schema is created, migrated (same plain-SQL files,
  applied with search_path set so every world gets identical tables) and
  bootstrapped (genesis + chargen from the SAME shared content YAML, so the
  content manifest hash matches across accounts) idempotently on the first
  authenticated call. The genesis seed is derived deterministically from the
  account id, so each account's dice history is its own but reproducible.

Security note: schema names are derived only from hex we generated; the
identifier is still regex-validated before interpolation into DDL.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
from dataclasses import dataclass

from api import telemetry
from api.bootstrap import bootstrap, bootstrap_genesis
from everquill_engine.db import connect
from everquill_engine.store import migrate_and_rebuild
from everquill_engine.world import WorldContent

WORLD_ID_BASE = "harrowdown"
AUTO_CHARGEN_MODE = "auto"
GUIDED_CHARGEN_MODE = "guided"
CHARGEN_MODES = frozenset({AUTO_CHARGEN_MODE, GUIDED_CHARGEN_MODE})
_PREFIX_RE = re.compile(r"^[0-9a-f]{8}$")

_ready_lock = threading.Lock()
_ready_worlds: set[str] = set()  # account ids whose schema is bootstrapped


class InviteCodeError(Exception):
    """Invite code not accepted. DELIBERATELY UNIFORM across unknown and
    already-claimed codes (a distinct used-code error was a
    validity oracle for guessing attacks)."""


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    chargen_mode: str = AUTO_CHARGEN_MODE
    test_capture: bool = False

    @property
    def prefix(self) -> str:
        return self.account_id[:8]

    @property
    def world_id(self) -> str:
        return f"{WORLD_ID_BASE}--{self.prefix}"

    @property
    def schema(self) -> str:
        if not _PREFIX_RE.match(self.prefix):  # defense in depth before DDL
            raise ValueError(f"malformed account prefix {self.prefix!r}")
        return f"world_{self.prefix}"


def invite_codes() -> tuple[str, ...]:
    raw = os.environ.get("EVERQUILL_INVITE_CODES", "")
    return tuple(code.strip() for code in raw.split(",") if code.strip())


def token_hash(device_token: str) -> str:
    return hashlib.sha256(device_token.encode("utf-8")).hexdigest()


def invite_code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def seed_env_invites(conn, codes: tuple[str, ...] | None = None) -> int:
    """Insert sha256 hashes of the env invite codes into public.invite
    (idempotent). Keeps the legacy EVERQUILL_INVITE_CODES list claimable
    without a migration carrying raw codes. Returns rows inserted."""
    codes = invite_codes() if codes is None else codes
    if not codes:
        return 0
    inserted = 0
    with conn.transaction():
        with conn.cursor() as cur:
            for code in codes:
                cur.execute(
                    "INSERT INTO public.invite (code_hash) VALUES (%s)"
                    " ON CONFLICT (code_hash) DO NOTHING",
                    (invite_code_hash(code),),
                )
                inserted += cur.rowcount
    return inserted


def account_seed(account_id: str) -> int:
    """A fresh 63-bit genesis seed for ``account_id``'s new world (each world
    rolls its own dice). Genesis stores it in ``world_state``, so replays stay
    exact, and a re-bootstrap is absorbed and keeps the first one. It is not
    derived from the account id: that id reaches the client, and a public
    derivation of a 32-bit seed let a player recover it from the dice shown
    and predict every later roll (audit 2026-10-24, claude #23)."""
    return secrets.randbits(63)


def claim(
    conn,
    invite_code: str,
    *,
    chargen_mode: str = AUTO_CHARGEN_MODE,
) -> tuple[Account, str]:
    """Claim an invite code: atomically burn the invite row, insert the
    account, return (account, raw token).

    Raises InviteCodeError for unknown AND already-claimed codes (uniform, so
    a used code is indistinguishable). The caller owns the connection (runtime role: INSERT+SELECT
    on public.accounts, SELECT/INSERT/UPDATE on public.invite).
    """
    import psycopg.errors

    code = (invite_code or "").strip()
    if not code:
        raise InviteCodeError("invite code not recognized")
    if chargen_mode not in CHARGEN_MODES:
        raise ValueError(f"chargen_mode must be one of {sorted(CHARGEN_MODES)}")
    code_hash = invite_code_hash(code)

    # Lazy env seeding: a code still living only in EVERQUILL_INVITE_CODES
    # gets its hash row created here, so legacy codes keep working even if
    # the env changed after startup seeding. Constant-time membership.
    if any(hmac.compare_digest(invite_code_hash(known), code_hash) for known in invite_codes()):
        seed_env_invites(conn, (code,))

    device_token = secrets.token_hex(32)  # 256-bit
    hashed = token_hash(device_token)

    for _ in range(3):  # re-roll on the (unlikely) prefix collision
        account_id = secrets.token_hex(16)
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    # Atomic burn: one UPDATE, no read-then-write window.
                    # 0 rows = unknown OR used — deliberately the same error.
                    cur.execute(
                        """
                        UPDATE public.invite
                        SET claimed_at = now(), claimed_by = %s
                        WHERE code_hash = %s AND claimed_at IS NULL
                        RETURNING code_hash
                        """,
                        (account_id, code_hash),
                    )
                    if cur.fetchone() is None:
                        raise InviteCodeError("invite code not accepted")
                    cur.execute(
                        """
                        INSERT INTO public.accounts
                            (account_id, prefix, invite_code_used, device_token_hash,
                             chargen_mode)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (account_id, account_id[:8], code, hashed, chargen_mode),
                    )
        except psycopg.errors.UniqueViolation as exc:
            constraint = exc.diag.constraint_name or ""
            if constraint == "accounts_prefix_key":
                continue  # 32-bit prefix collision — the DB caught it; new id
            # invite_code_used / anything else: treat as not-accepted (uniform).
            raise InviteCodeError("invite code not accepted") from None
        account = Account(account_id=account_id, chargen_mode=chargen_mode)
        telemetry.emit("account_claimed", account_id=account_id, world_id=account.world_id)
        return account, device_token
    raise RuntimeError("could not allocate an account id")  # pragma: no cover


def authenticate(conn, bearer_token: str) -> Account | None:
    """Resolve a raw device token to an Account (constant-time via hash lookup)."""
    if not bearer_token:
        return None
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'accounts'
                      AND column_name = 'test_capture'
                )
                """
            )
            has_test_capture = bool(cur.fetchone()[0])
            test_capture_sql = (
                "COALESCE(test_capture, false)" if has_test_capture else "false"
            )
            cur.execute(
                f"""
                SELECT account_id, COALESCE(chargen_mode, %s), {test_capture_sql}
                FROM public.accounts
                WHERE device_token_hash = %s
                """,
                (AUTO_CHARGEN_MODE, token_hash(bearer_token)),
            )
            row = cur.fetchone()
    return (
        Account(account_id=row[0], chargen_mode=row[1], test_capture=bool(row[2]))
        if row else None
    )


def _bootstrap_account_world(conn, account: Account, world: WorldContent, seed: int) -> dict:
    if account.chargen_mode == GUIDED_CHARGEN_MODE:
        return bootstrap_genesis(conn, world, seed)
    return bootstrap(conn, world, seed)


def set_search_path(conn, schema: str) -> None:
    """Pin the session's search_path to one world schema (validated name)."""
    if not re.match(r"^world_[0-9a-f]{8}$", schema):
        raise ValueError(f"refusing search_path for {schema!r}")
    conn.execute(f'SET search_path TO "{schema}"')
    conn.commit()


def ensure_world_ready(account: Account, world: WorldContent, admin_url: str) -> dict:
    """Create + migrate + bootstrap the account's world schema, idempotently.

    Runs on the OWNER connection (DDL + migrations). Cached per process on
    success. Returns the bootstrap summary (content_drift is the caller's
    503 signal). A world cached as ready is not re-checked for drift: content
    is loaded once per process, so new drift can only appear after a restart.
    """
    with _ready_lock:
        if account.account_id in _ready_worlds:
            return {"content_drift": None, "cached": True}
        conn = connect(admin_url)
        try:
            with conn.transaction():
                conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{account.schema}"')
            set_search_path(conn, account.schema)
            applied = migrate_and_rebuild(conn)
            # Migrations grant per-table rights inside the schema (unqualified
            # names resolve through search_path); the schema itself and its
            # sequences still need explicit grants for the runtime role.
            with conn.transaction():
                conn.execute(f'GRANT USAGE ON SCHEMA "{account.schema}" TO app_role')
                conn.execute(
                    f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{account.schema}"'
                    " TO app_role"
                )
            summary = _bootstrap_account_world(
                conn, account, world, account_seed(account.account_id)
            )
        finally:
            conn.close()
        summary["migrations_applied"] = applied
        telemetry.emit(
            "world_bootstrap",
            account_id=account.account_id,
            world_id=account.world_id,
            schema=account.schema,
            **{k: v for k, v in summary.items() if k != "cached"},
        )
        if summary["content_drift"] is None:
            _ready_worlds.add(account.account_id)
        return summary


def reset_ready_cache() -> None:
    """Test hook: forget which schemas were bootstrapped this process."""
    with _ready_lock:
        _ready_worlds.clear()
