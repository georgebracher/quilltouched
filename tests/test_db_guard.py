"""DB suites wipe data, so they refuse a non-local database by default."""

from __future__ import annotations

import pytest

from everquill_engine.db import require_local_test_database


@pytest.mark.parametrize("url", [
    "postgresql://postgres@127.0.0.1:55432/postgres",
    "postgresql://postgres:postgres@localhost:5432/everquill_test",
    "postgresql:///everquill_test",
])
def test_local_urls_pass(url, monkeypatch):
    monkeypatch.delenv("EVERQUILL_ALLOW_REMOTE_TEST_DB", raising=False)
    assert require_local_test_database(url) == url


def test_a_remote_url_is_refused_unless_allowed(monkeypatch):
    url = "postgresql://user:pw@shared.proxy.example.com:5432/railway"
    monkeypatch.delenv("EVERQUILL_ALLOW_REMOTE_TEST_DB", raising=False)
    with pytest.raises(RuntimeError, match="non-local host"):
        require_local_test_database(url)
    monkeypatch.setenv("EVERQUILL_ALLOW_REMOTE_TEST_DB", "1")
    assert require_local_test_database(url) == url
