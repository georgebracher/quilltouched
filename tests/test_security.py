"""Fail-closed production gate (Hardening Pass 1).

Under EVERQUILL_REQUIRE_SECURE=1 the engine refuses to run with a missing
master key (fail-open raw DEK storage) or an owner/superuser runtime
connection (append-only REVOKE would not bind). Dev (unset) stays lenient.
The conn-free cases run without a database; the owner/non-owner cases skip
cleanly when DATABASE_URL is unavailable.
"""

from __future__ import annotations

import pytest

from everquill_engine import crypto
from everquill_engine.security import (
    REQUIRE_SECURE_ENV,
    InsecureRuntimeError,
    assert_secure_startup,
    require_secure,
    runtime_bypasses_append_only,
)

VALID_KEY = "a1" * 32  # 64 hex chars → a well-formed 256-bit master key


class _UntouchableConn:
    """A conn that FAILS if any code path touches it — proves the lenient
    and short-circuit paths never reach the database."""

    def cursor(self, *args, **kwargs):
        raise AssertionError("connection must not be touched on this path")


class TestRequireSecureFlag:
    def test_flag_reads_the_env(self):
        assert require_secure({REQUIRE_SECURE_ENV: "1"}) is True
        assert require_secure({REQUIRE_SECURE_ENV: "0"}) is False
        assert require_secure({}) is False


class TestFailClosedNoDB:
    def test_dev_lenient_is_noop_and_never_touches_conn(self):
        assert assert_secure_startup(_UntouchableConn(), env={}) is None

    def test_missing_master_key_raises_before_touching_conn(self):
        with pytest.raises(InsecureRuntimeError, match=crypto.MASTER_KEY_ENV):
            assert_secure_startup(_UntouchableConn(), env={REQUIRE_SECURE_ENV: "1"})

    def test_malformed_master_key_fails_loud_not_open(self):
        # An InsecureRuntimeError, so readiness reports it instead of treating
        # it as a transient error and passing.
        with pytest.raises(InsecureRuntimeError, match="malformed"):
            assert_secure_startup(
                _UntouchableConn(),
                env={REQUIRE_SECURE_ENV: "1", crypto.MASTER_KEY_ENV: "nothexatall"},
            )

    def test_secure_with_key_reaches_the_owner_check(self):
        """Key present → the gate proceeds to the connection check (and so
        DOES touch conn — the opposite of the short-circuit cases)."""
        with pytest.raises(AssertionError, match="must not be touched"):
            assert_secure_startup(
                _UntouchableConn(),
                env={REQUIRE_SECURE_ENV: "1", crypto.MASTER_KEY_ENV: VALID_KEY},
            )


class TestFailClosedRuntime:
    """Owner/superuser vs non-owner against a real connection."""

    def test_owner_or_superuser_connection_is_refused(self, db_conn):
        bypasses, reason = runtime_bypasses_append_only(db_conn)
        db_conn.rollback()
        assert bypasses, "scratch/dev connection should be owner or superuser"
        assert reason
        with pytest.raises(InsecureRuntimeError, match="append-only"):
            assert_secure_startup(
                db_conn,
                env={REQUIRE_SECURE_ENV: "1", crypto.MASTER_KEY_ENV: VALID_KEY},
            )
        db_conn.rollback()

    def test_non_owner_app_role_passes(self, db_conn):
        """app_role (migration 0004) is non-owner + non-superuser — exactly
        the runtime the gate must ALLOW. SET ROLE assumes its identity."""
        with db_conn.cursor() as cur:
            cur.execute("SET ROLE app_role")
        try:
            bypasses, _reason = runtime_bypasses_append_only(db_conn)
            assert not bypasses
            # passes cleanly with the master key set (no raise)
            assert (
                assert_secure_startup(
                    db_conn,
                    env={REQUIRE_SECURE_ENV: "1", crypto.MASTER_KEY_ENV: VALID_KEY},
                )
                is None
            )
        finally:
            with db_conn.cursor() as cur:
                cur.execute("RESET ROLE")
            db_conn.rollback()

    def test_require_secure_unset_allows_the_owner_connection(self, db_conn):
        assert assert_secure_startup(db_conn, env={}) is None
        db_conn.rollback()
