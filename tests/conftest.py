"""Shared fixtures. DB-integration tests skip cleanly when DATABASE_URL
is unavailable (interface decision #4) — resolution order is
env var, then repo-root .env, and EVERQUILL_IGNORE_DOTENV=1 simulates
"unset" so the skip path is provable on machines where .env exists:

    with DB   : .venv/bin/python -m pytest
    without DB: EVERQUILL_IGNORE_DOTENV=1 .venv/bin/python -m pytest
"""

from __future__ import annotations

import pytest

from everquill_engine.db import require_local_test_database, resolve_database_url


@pytest.fixture(scope="session")
def db_url() -> str:
    url = resolve_database_url()
    if not url:
        pytest.skip("DATABASE_URL not set (env or .env) — DB-integration test skipped")
    return require_local_test_database(url)


@pytest.fixture()
def db_conn(db_url):
    from everquill_engine.db import connect
    from everquill_engine.migrate import apply_migrations

    conn = connect(db_url)
    try:
        apply_migrations(conn)
        yield conn
    finally:
        conn.close()
