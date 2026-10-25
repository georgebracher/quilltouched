"""API test fixtures.

DB-backed tests hit the SAME dev/test database the engine tests use
(repo .env -> everquill_test) and skip cleanly when none is configured —
CI provides an ephemeral Postgres and separately fails the build if any
DB-marked test skipped.

Every test gets a FRESH app module (importlib.reload) so module-level
engine state never leaks between tests, and per-account world schemas
created by a test are dropped afterwards.
"""

from __future__ import annotations

import hashlib
import importlib
import secrets

import pytest

from everquill_engine.db import require_local_test_database, resolve_database_url

# sha256 hex of invite codes minted by tests this session — app_client's
# teardown deletes their public.invite rows (codes are random per test, so
# leftovers would only be inert junk, but keep the shared test DB tidy).
_test_invite_hashes: list[str] = []


def track_invite_code(code: str) -> str:
    _test_invite_hashes.append(hashlib.sha256(code.encode()).hexdigest())
    return code


@pytest.fixture(scope="session")
def db_url() -> str:
    url = resolve_database_url()
    if not url:
        pytest.skip("DATABASE_URL not set (env or .env) — DB-integration test skipped")
    return require_local_test_database(url)


@pytest.fixture()
def invite_code(monkeypatch) -> str:
    code = track_invite_code(f"test-{secrets.token_hex(4)}")
    spare = track_invite_code(f"spare-{secrets.token_hex(3)}")
    monkeypatch.setenv("EVERQUILL_INVITE_CODES", f"{code}, {spare}")
    return code


@pytest.fixture()
def app_client(db_url, monkeypatch):
    """TestClient over a freshly-reloaded api.main, with LLM calls forbidden
    by default (tests monkeypatch the gateway explicitly when needed)."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    # Rate/spend gates default to effectively-off in tests;
    # the hardening tests set tight values per-test (env is read per request).
    monkeypatch.setenv("EVERQUILL_TURN_RATE_PER_MIN", "100000")
    monkeypatch.setenv("EVERQUILL_DAILY_TURN_CAP", "100000")
    monkeypatch.setenv("EVERQUILL_DAILY_SPEND_CAP_USD", "1000000")
    monkeypatch.setenv("EVERQUILL_CLAIM_RATE_PER_MIN", "100000")
    monkeypatch.setenv("EVERQUILL_CLAIM_RATE_GLOBAL_PER_MIN", "100000")

    import api.accounts as accounts_mod
    import api.llm_gateway as gateway
    import api.main as main_mod

    importlib.reload(main_mod)
    accounts_mod.reset_ready_cache()

    def _no_llm(*args, **kwargs):  # pragma: no cover - guard rail
        raise AssertionError("unexpected real LLM call in tests — monkeypatch the gateway")

    monkeypatch.setattr(gateway, "parse_free_text", _no_llm)
    monkeypatch.setattr(
        gateway, "narrate_outcome", lambda *a, **k: (None, None, "llm disabled in tests")
    )

    created_schemas: list[str] = []
    original_ensure = accounts_mod.ensure_world_ready

    def tracking_ensure(account, world, admin_url):
        if account.schema not in created_schemas:
            created_schemas.append(account.schema)
        return original_ensure(account, world, admin_url)

    monkeypatch.setattr(accounts_mod, "ensure_world_ready", tracking_ensure)
    # api.main binds the module object, so the attribute patch above is seen.

    with TestClient(main_mod.app) as client:
        yield client, main_mod

    # Cleanup: drop world schemas + test accounts (owner connection).
    from everquill_engine.db import connect

    with connect(db_url) as conn:
        for schema in created_schemas:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.execute("DELETE FROM public.test_turn_capture WHERE world_id LIKE 'harrowdown--%'")
        conn.execute("DELETE FROM accounts WHERE invite_code_used LIKE 'test-%'")
        conn.execute("DELETE FROM accounts WHERE invite_code_used LIKE 'spare-%'")
        if _test_invite_hashes:
            conn.execute(
                "DELETE FROM public.invite WHERE code_hash = ANY(%s)",
                (list(_test_invite_hashes),),
            )
        conn.execute(
            "DELETE FROM public.rate_limit WHERE bucket_key LIKE 'claim:%' "
            "OR bucket_key LIKE 'turn:%' OR bucket_key LIKE 'turnday:%'"
        )
        conn.commit()
    _test_invite_hashes.clear()
    accounts_mod.reset_ready_cache()
