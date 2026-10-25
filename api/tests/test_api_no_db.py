"""No-database mode: the app boots, /healthz stays 200, game endpoints 503,
and the auth layer answers before any DB work (unauthed action -> 410)."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def no_db_client(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    monkeypatch.setenv("EVERQUILL_IGNORE_DOTENV", "1")

    import api.main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        yield client
    # Leave a clean module for the next test session user.
    monkeypatch.delenv("EVERQUILL_IGNORE_DOTENV", raising=False)
    importlib.reload(main_mod)


class TestNoDatabaseMode:
    def test_healthz_and_hello_stay_up(self, no_db_client):
        assert no_db_client.get("/healthz").status_code == 200
        assert no_db_client.get("/api/hello").status_code == 200

    def test_scene_degrades_to_503(self, no_db_client):
        assert no_db_client.get("/api/scene?world=harrowdown").status_code == 503

    def test_unauthed_action_is_410_before_db(self, no_db_client):
        r = no_db_client.post("/api/action", json={"command_id": "x", "intent": {}})
        assert r.status_code == 410

    def test_authed_action_degrades_to_503(self, no_db_client):
        r = no_db_client.post(
            "/api/action",
            json={"command_id": "x", "intent": {}},
            headers={"authorization": "Bearer " + "0" * 64},
        )
        assert r.status_code == 503

    def test_claim_degrades_to_503(self, no_db_client):
        r = no_db_client.post("/api/claim", json={"invite_code": "whatever"})
        assert r.status_code == 503


class TestClaimThrottleAddress:
    """The per-IP claim throttle keys on the address the trusted proxy appended,
    not the left end of X-Forwarded-For, which the client writes (audit claude #22)."""

    @staticmethod
    def _request(forwarded: str | None, host: str = "10.0.0.9"):
        from starlette.requests import Request

        headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
        return Request({"type": "http", "headers": headers, "client": (host, 4000)})

    def test_a_spoofed_left_entry_is_ignored(self, monkeypatch):
        from api.main import _client_ip

        monkeypatch.delenv("EVERQUILL_TRUSTED_PROXY_HOPS", raising=False)
        assert _client_ip(self._request("6.6.6.6, 203.0.113.7")) == "203.0.113.7"
        assert _client_ip(self._request("203.0.113.7")) == "203.0.113.7"

    def test_no_header_or_zero_hops_uses_the_socket(self, monkeypatch):
        from api.main import _client_ip

        assert _client_ip(self._request(None)) == "10.0.0.9"
        monkeypatch.setenv("EVERQUILL_TRUSTED_PROXY_HOPS", "0")
        assert _client_ip(self._request("6.6.6.6")) == "10.0.0.9"

    def test_two_hops_reads_second_from_the_right(self, monkeypatch):
        from api.main import _client_ip

        monkeypatch.setenv("EVERQUILL_TRUSTED_PROXY_HOPS", "2")
        assert _client_ip(self._request("6.6.6.6, 203.0.113.7, 10.1.1.1")) == "203.0.113.7"

    def test_a_malformed_hop_count_falls_back_to_one(self, monkeypatch):
        from api.main import _client_ip

        monkeypatch.setenv("EVERQUILL_TRUSTED_PROXY_HOPS", "one")
        assert _client_ip(self._request("6.6.6.6, 203.0.113.7")) == "203.0.113.7"


def test_a_failed_usage_write_holds_the_paid_layers(monkeypatch):
    """k3-005: the spend breaker read a falsely low total while ledger writes
    failed; now it reads as tripped until writes recover."""
    from api import budget

    clock = {"t": 1000.0}
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(budget, "_ledger_failed_at", None)
    assert not budget.ledger_failing()
    budget.note_ledger_failure()
    assert budget.ledger_failing()
    clock["t"] += budget.LEDGER_FAILURE_HOLD_S + 1
    assert not budget.ledger_failing()


def test_a_failed_bootstrap_waits_before_trying_again(monkeypatch):
    """k3-006: every request and /readyz poll re-ran the whole migration while
    the database was down."""
    import api.main as main_mod

    engine = main_mod._EngineState()
    engine.world = object()
    monkeypatch.setattr(engine, "admin_url", lambda: "postgresql://nowhere")
    attempts = []

    def down(url):
        attempts.append(url)
        raise OSError("connection refused")

    monkeypatch.setattr(main_mod, "connect", down)
    with pytest.raises(OSError):
        engine.ensure_bootstrap()
    with pytest.raises(RuntimeError, match="moments ago"):
        engine.ensure_bootstrap()
    assert len(attempts) == 1


def test_the_clients_fallback_lines_are_the_servers():
    """k3-008: the client's copies of the 429 lines had drifted from the
    server's; it shows them only when a response carries no line."""
    import re

    from api import messages
    from tests.harness import REPO_ROOT

    app = (REPO_ROOT / "client" / "src" / "App.tsx").read_text()
    block = app[app.index("const DEGRADE_CODE_LINES"):]
    block = block[: block.index("\n}\n")]
    client = dict(re.findall(r"(\w+):\s*['\"](.+?)['\"],", block, flags=re.S))
    server = {code: line for line, code in messages.CODE_FOR_429_LINE.items()}
    assert client == server
