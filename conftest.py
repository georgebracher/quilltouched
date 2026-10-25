"""Repo-root fixtures shared across suites.

Lives here, not under api/, because the KNOWN-state boundary lint
(tests/test_known_boundary.py) forbids api/ and llm/ from importing the
referee surface, test files included. Resetting the world is referee-grade
plumbing, so it stays outside the linted tree.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def clean_legacy_world(db_url):
    """Empty the public-schema world so the app bootstraps the configured
    world on startup. The engine suite seeds its own fixture world into
    public; without this, running both suites in one process trips the
    content-drift guard and the legacy world 503s. Request it BEFORE
    app_client so the reset lands before the app starts."""
    from everquill_engine.db import connect
    from everquill_engine.store import fresh_reset

    with connect(db_url) as conn:
        migrated = conn.execute("SELECT to_regclass('public.event')").fetchone()[0]
        if migrated:
            fresh_reset(conn)
