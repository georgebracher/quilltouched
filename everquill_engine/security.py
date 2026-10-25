"""Fail-closed production runtime gate (Hardening Pass 1).

Two production-safety controls the audit found failing OPEN:

- **#6 crypto fail-open.** Without ``EVERQUILL_MASTER_KEY`` the account DEK
  is stored raw beside the ciphertext (``wrap_mode='raw'``), so a stolen DB
  backup decrypts every player's text. In production that must be a HARD
  startup failure, not a warning.
- **#7 owner authority.** If the runtime connects as the ``event`` table
  OWNER (or a superuser), the append-only ``REVOKE`` (migrations 0001/0004)
  does not bind it — the web process could rewrite or delete sealed canon.

Both are guarded ONLY when ``EVERQUILL_REQUIRE_SECURE=1`` (the API sets it on
Railway). Dev and the test suites leave it unset and stay lenient — the
engine behaves exactly as before, ``conn`` is never touched. The API calls
:func:`assert_secure_startup` at boot / readiness and fails the readiness
probe (503) if it raises. This module is api/-importable: it carries no
referee state and touches no fold image (the known-boundary lint is
unaffected).
"""

from __future__ import annotations

import os

from everquill_engine import crypto

__all__ = [
    "REQUIRE_SECURE_ENV",
    "InsecureRuntimeError",
    "require_secure",
    "runtime_bypasses_append_only",
    "assert_secure_startup",
]

REQUIRE_SECURE_ENV = "EVERQUILL_REQUIRE_SECURE"


class InsecureRuntimeError(RuntimeError):
    """A production-mode (``EVERQUILL_REQUIRE_SECURE=1``) precondition is
    unmet: the master key is absent/malformed, or the runtime connection can
    bypass the append-only grants (table owner / superuser). Fail closed —
    do not start serving."""


def require_secure(env: os._Environ[str] | dict[str, str] | None = None) -> bool:
    """Whether production fail-closed mode is on (``EVERQUILL_REQUIRE_SECURE=1``)."""
    return (os.environ if env is None else env).get(REQUIRE_SECURE_ENV) == "1"


def runtime_bypasses_append_only(conn) -> tuple[bool, str]:
    """``(bypasses, reason)``. True when the connection's role can defeat the
    append-only ``REVOKE`` on ``event``: it OWNS the table, or it is a
    superuser (owners and superusers ignore table REVOKEs). This is exactly
    the authority the production web process must NOT hold. A
    read-only probe; the caller owns the transaction."""
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('is_superuser') = 'on'")
        is_superuser = bool(cur.fetchone()[0])
        cur.execute(
            "SELECT tableowner = current_user FROM pg_tables"
            " WHERE tablename = 'event'"
            " ORDER BY (schemaname = current_schema()) DESC NULLS LAST"
            " LIMIT 1"
        )
        row = cur.fetchone()
        is_owner = bool(row[0]) if row is not None else False
    if is_superuser:
        return True, "authenticates as a superuser"
    if is_owner:
        return True, "owns the append-only `event` table"
    return False, ""


def assert_secure_startup(
    conn, *, env: os._Environ[str] | dict[str, str] | None = None
) -> None:
    """THE fail-closed production gate. A no-op unless
    ``EVERQUILL_REQUIRE_SECURE=1``. In that mode it RAISES
    :class:`InsecureRuntimeError` when ``EVERQUILL_MASTER_KEY`` is
    absent/malformed, or when ``conn`` can bypass the append-only grants.
    Dev (unset) stays lenient and never touches ``conn``."""
    if not require_secure(env):
        return
    try:
        configured = crypto.master_key_configured(env)
    except ValueError as exc:
        # A malformed key is a configuration error, not a transient one:
        # readiness must say so instead of passing while every player-text
        # append fails (audit 2026-10-24, claude P3 #21).
        raise InsecureRuntimeError(f"{crypto.MASTER_KEY_ENV} is malformed: {exc}") from exc
    if not configured:
        raise InsecureRuntimeError(
            f"{REQUIRE_SECURE_ENV}=1 but {crypto.MASTER_KEY_ENV} is absent — "
            "refusing to run with fail-open raw DEK storage (audit #6). Set the "
            "64-hex master key, or unset the secure requirement in dev."
        )
    bypasses, reason = runtime_bypasses_append_only(conn)
    if bypasses:
        raise InsecureRuntimeError(
            f"{REQUIRE_SECURE_ENV}=1 but the runtime connection {reason} — the "
            "append-only REVOKE on `event` cannot bind it (audit #7). Connect as "
            "the non-owner app_role (APP_DATABASE_URL), never the table owner."
        )
