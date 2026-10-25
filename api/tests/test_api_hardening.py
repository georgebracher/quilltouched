"""API hardening: input caps, degrade-not-block, fail-closed readiness,
probe-before-parse, narration gate wiring, invite and prefix hardening.

Covers: input caps (schema 422, canonical-byte 422, body 413, parser clamp),
rate/daily/spend 429s with Retry-After, one-in-flight-turn 429, probe-before-
parse (a duplicate free-text command never buys a second parse), narration-
gate fallback/regeneration wiring, invite claim atomicity + throttles, and
prefix-collision retry."""

from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest

from api import messages
from api.llm_gateway import StageUsage
from api.tests.conftest import track_invite_code
from api.tests.test_api_pipeline import ATTACK_QUARRYMAN, LOOK, _move
from everquill_engine.db import connect
from llm import narration_gate


@pytest.fixture()
def player(app_client, invite_code, monkeypatch):
    """A claimed account with the deterministic dev seed (42) — same shape as
    the pipeline tests' fixture, plus the reloaded main module for constants."""
    import api.accounts as accounts_mod

    monkeypatch.setattr(accounts_mod, "account_seed", lambda account_id: 42)
    client, main_mod = app_client
    claimed = client.post("/api/claim", json={"invite_code": invite_code}).json()
    headers = {"authorization": f"Bearer {claimed['device_token']}"}
    return client, headers, claimed, main_mod


def _fake_usage(stage: str, model: str) -> StageUsage:
    return StageUsage(
        stage=stage, model=model, input_tokens=100, output_tokens=10,
        cache_read_input_tokens=0, cache_creation_input_tokens=0, latency_ms=5,
    )


# --- input caps -----------------------------------------------------------


class TestInputCaps:
    def test_oversized_approach_is_a_schema_422(self, player):
        client, headers, _, _ = player
        intent = dict(LOOK, approach="x" * 501)
        r = client.post(
            "/api/action", json={"command_id": "cap-1", "intent": intent}, headers=headers
        )
        assert r.status_code == 422
        assert "intent_schema_violations" in r.text

    def test_too_many_targets_is_a_schema_422(self, player):
        client, headers, _, _ = player
        intent = dict(LOOK, target_entity_ids=[f"npc_extra_{i}" for i in range(6)])
        r = client.post(
            "/api/action", json={"command_id": "cap-2", "intent": intent}, headers=headers
        )
        assert r.status_code == 422
        assert "intent_schema_violations" in r.text

    def test_intent_over_the_canonical_byte_cap_is_422_before_schema_work(self, player):
        client, headers, _, _ = player
        intent = dict(LOOK, approach="x" * 5000)  # > 4096 canonical bytes
        r = client.post(
            "/api/action", json={"command_id": "cap-3", "intent": intent}, headers=headers
        )
        assert r.status_code == 422
        assert "canonical cap" in r.text
        assert "intent_schema_violations" not in r.text  # byte cap fired first

    def test_body_over_16kb_is_413(self, player):
        client, headers, _, _ = player
        r = client.post(
            "/api/action",
            json={"command_id": "cap-4", "text": "x" * 20000},
            headers=headers,
        )
        assert r.status_code == 413
        assert "too large" in r.text

    def test_parser_verbosity_is_clamped_not_422(self, player, monkeypatch):
        """The caps must never 422 a player's own typed turn because OUR
        parser got verbose — parser output is clamped to the schema caps."""
        client, headers, _, _ = player
        import api.llm_gateway as gateway

        def verbose_parse(text, roster_text, lists=None):
            return dict(LOOK, approach="y" * 800), _fake_usage("parse", "claude-haiku-4-5")

        monkeypatch.setattr(gateway, "parse_free_text", verbose_parse)
        r = client.post(
            "/api/action", json={"command_id": "cap-5", "text": "look"}, headers=headers
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["intent"]["approach"]) == 500


# --- DEGRADE-NOT-BLOCK — never meter the deterministic engine ------------


def _good_narrate(envelope, outcome, action, corrective=None):
    """A clean narration that passes the deterministic gate (for the tests that
    exercise the PAID narrator degrading)."""
    return (
        "The room answers you with woodsmoke and low voices.",
        _fake_usage("narrate", "claude-sonnet-5"),
        None,
    )


class TestDegradeNotBlock:
    """The deterministic engine turn (structured intent -> beat -> resolve ->
    commit) is NEVER blocked by the daily turn cap or the spend breaker; only
    the PAID LLM layers degrade ('never meter the conversation')."""

    def test_structured_turn_over_daily_cap_still_resolves_without_narration(
        self, player, monkeypatch
    ):
        client, headers, _, main_mod = player
        import api.llm_gateway as gateway

        narrated = {"n": 0}

        def spy_narrate(*a, **k):
            narrated["n"] += 1
            return _good_narrate(*a, **k)

        monkeypatch.setattr(gateway, "narrate_outcome", spy_narrate)
        monkeypatch.setenv("EVERQUILL_DAILY_TURN_CAP", "0")
        r = client.post(
            "/api/action", json={"command_id": "deg-1", "intent": LOOK}, headers=headers
        )
        assert r.status_code == 200, r.text  # engine NOT blocked
        body = r.json()
        assert body["outcome"]["event_id"]            # the deed is canon
        assert body["narration"] is None              # paid layer degraded
        assert body["system_note"] == messages.NARRATION_RESTING
        assert body["narration_meta"]["gate"] == "degraded"
        assert narrated["n"] == 0                      # narrator was never paid

    def test_structured_turn_over_spend_cap_still_resolves(
        self, player, monkeypatch, db_url
    ):
        client, headers, _, main_mod = player
        monkeypatch.setenv("EVERQUILL_DAILY_SPEND_CAP_USD", "20")
        with connect(db_url) as conn:
            conn.execute(
                "INSERT INTO public.llm_usage (command_id, stage, model, input_tokens)"
                " VALUES ('spend-sentinel', 'narrate', 'claude-sonnet-5', 2000000000)"
            )
            conn.commit()
        try:
            r = client.post(
                "/api/action", json={"command_id": "deg-2", "intent": LOOK},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["outcome"]["event_id"]
            assert body["narration"] is None
            assert body["system_note"] == messages.NARRATION_RESTING
        finally:
            with connect(db_url) as conn:
                conn.execute(
                    "DELETE FROM public.llm_usage WHERE command_id = 'spend-sentinel'"
                )
                conn.commit()

    def test_free_text_degrades_to_429_requiring_a_tapped_action(
        self, player, monkeypatch
    ):
        """Free text needs the PAID parser — when the budget is spent it 429s to
        require a structured (tapped) action, but the engine stays open."""
        client, headers, _, main_mod = player
        monkeypatch.setenv("EVERQUILL_DAILY_TURN_CAP", "0")
        r = client.post(
            "/api/action", json={"command_id": "deg-ft-1", "text": "look around"},
            headers=headers,
        )
        assert r.status_code == 429
        assert messages.TURN_DAILY_DONE in r.text
        assert int(r.headers["retry-after"]) >= 1
        # ...and a STRUCTURED intent still resolves (engine never metered).
        ok = client.post(
            "/api/action", json={"command_id": "deg-ft-2", "intent": LOOK},
            headers=headers,
        )
        assert ok.status_code == 200, ok.text

    def test_per_minute_flood_guards_free_text_only(self, player, monkeypatch):
        """The per-minute rate is a transient flood guard on the paid parser —
        it 429s free text but NEVER a structured engine turn."""
        client, headers, _, main_mod = player
        monkeypatch.setenv("EVERQUILL_TURN_RATE_PER_MIN", "0")
        typed = client.post(
            "/api/action", json={"command_id": "flood-1", "text": "look"},
            headers=headers,
        )
        assert typed.status_code == 429
        assert messages.TURN_TOO_FAST in typed.text
        assert 1 <= int(typed.headers["retry-after"]) <= 60
        # A structured intent is NOT gated by the per-minute flood guard.
        structured = client.post(
            "/api/action", json={"command_id": "flood-2", "intent": LOOK},
            headers=headers,
        )
        assert structured.status_code == 200, structured.text

    def test_committed_duplicates_stay_free_under_a_spent_budget(
        self, player, monkeypatch
    ):
        client, headers, _, _ = player
        first = client.post(
            "/api/action", json={"command_id": "day-1", "intent": LOOK}, headers=headers
        )
        assert first.status_code == 200
        monkeypatch.setenv("EVERQUILL_DAILY_TURN_CAP", "0")
        # A replay of the committed command answers from storage — no budget.
        dup = client.post(
            "/api/action", json={"command_id": "day-1", "intent": LOOK}, headers=headers
        )
        assert dup.status_code == 200
        assert dup.json()["absorbed"] is True

    @pytest.mark.parametrize(
        "intent",
        [
            dict(
                LOOK, action_type="physical", stat_hint="might",
                target_entity_ids=["creature_harrowdown_ditch_slime"],
                approach="boot heel, quick, before it reaches the casks",
            ),
            _move("loc_harrowdown_drove_road"),  # blocked: not adjacent to the tavern
        ],
        ids=["stomp", "blocked-move"],
    )
    def test_a_non_narrated_retry_serves_the_same_turn(self, player, monkeypatch, intent):
        """No prose on record, so the retry rebuilds the public outcome; it must
        match the first response, kill and movement note included (claude #17)."""
        client, headers, _, _ = player
        monkeypatch.setenv("EVERQUILL_DAILY_TURN_CAP", "0")
        body = {"command_id": "nn-1", "intent": intent}
        first = client.post("/api/action", json=body, headers=headers).json()
        dup = client.post("/api/action", json=body, headers=headers).json()
        assert first["narration"] is None and dup["absorbed"] is True
        assert dup["outcome"] == first["outcome"]
        if first["outcome"].get("movement_blocked"):
            assert dup["system_note"] == first["system_note"]
        else:
            effects = [d.get("effect") for d in first["outcome"]["state_deltas"]]
            assert "dispatched" in effects  # the stomp kills, so the old retry said "wounded"

    def test_a_retried_kill_still_reads_as_a_kill_after_a_move(self, player, monkeypatch):
        """The rebuild read the current scene, so once the player had left the
        room a retried kill came back "wounded" (claude-013)."""
        client, headers, _, _ = player
        monkeypatch.setenv("EVERQUILL_DAILY_TURN_CAP", "0")
        stomp = {"command_id": "nn-kill", "intent": dict(
            LOOK, action_type="physical", stat_hint="might",
            target_entity_ids=["creature_harrowdown_ditch_slime"],
            approach="boot heel, quick, before it reaches the casks",
        )}
        first = client.post("/api/action", json=stomp, headers=headers).json()
        moved = client.post(
            "/api/action",
            json={"command_id": "nn-move", "intent": _move("loc_harrowdown_market_row")},
            headers=headers,
        )
        assert moved.status_code == 200 and not moved.json()["outcome"].get("movement_blocked")
        dup = client.post("/api/action", json=stomp, headers=headers).json()
        assert dup["absorbed"] is True and dup["outcome"] == first["outcome"]


class TestConfirmBudgetOnce:
    """Budget is reserved ONCE per command — the confirm continuation
    must not re-charge the daily turn cap (the double-count fix)."""

    def _turnday_count(self, db_url, main_mod, account_id):
        from api import ratelimit
        with connect(db_url) as conn:
            return ratelimit.peek(conn, f"turnday:{account_id}", window_seconds=86400)

    def test_confirm_does_not_recharge_the_daily_turn_cap(self, player, db_url):
        client, headers, claimed, main_mod = player
        account_id = claimed["account_id"]
        # walk to the quarry (3 structured turns), then declare the dire attack
        for i, loc in enumerate(
            ["loc_harrowdown_market_row", "loc_harrowdown_drove_road",
             "loc_harrowdown_quarry_track"]
        ):
            assert client.post(
                "/api/action", json={"command_id": f"cwalk-{i}", "intent": _move(loc)},
                headers=headers,
            ).status_code == 200
        pend = client.post(
            "/api/action",
            json={"command_id": "cbud-1", "intent": ATTACK_QUARRYMAN},
            headers=headers,
        )
        assert pend.json()["pending_confirmation"] is True
        after_declare = self._turnday_count(db_url, main_mod, account_id)

        confirmed = client.post(
            "/api/action/confirm", json={"command_id": "cbud-1"}, headers=headers
        )
        assert confirmed.status_code == 200, confirmed.text
        after_confirm = self._turnday_count(db_url, main_mod, account_id)
        # the ORIGINAL command already reserved the slot; confirm adds nothing.
        assert after_confirm == after_declare


class TestCanonicalRecordServed:
    """A narrated turn's duplicate/retry returns the canonical
    public-turn record WITH its prose (not narration:null), and GET /api/turns
    rebuilds the Chronicle."""

    def test_duplicate_returns_the_record_with_narration(self, player, monkeypatch):
        client, headers, _, _ = player
        import api.llm_gateway as gateway

        monkeypatch.setattr(gateway, "narrate_outcome", _good_narrate)
        first = client.post(
            "/api/action", json={"command_id": "canon-1", "intent": LOOK}, headers=headers
        )
        assert first.status_code == 200, first.text
        fb = first.json()
        assert fb["narration"].startswith("The room answers")

        dup = client.post(
            "/api/action", json={"command_id": "canon-1", "intent": LOOK}, headers=headers
        )
        assert dup.status_code == 200
        db = dup.json()
        assert db["absorbed"] is True
        # the SAME prose is served from canon — NOT narration:null
        assert db["narration"] == fb["narration"]
        assert db["outcome"]["event_id"] == fb["outcome"]["event_id"]
        assert db["narration_meta"]["gate"] == "canonical_record"

    def test_api_turns_rebuilds_the_chronicle(self, player, monkeypatch):
        client, headers, _, _ = player
        import api.llm_gateway as gateway

        monkeypatch.setattr(gateway, "narrate_outcome", _good_narrate)
        for i in range(3):
            assert client.post(
                "/api/action", json={"command_id": f"thist-{i}", "intent": LOOK},
                headers=headers,
            ).status_code == 200

        r = client.get("/api/turns", headers=headers)
        assert r.status_code == 200, r.text
        turns = r.json()["turns"]
        assert [t["command_id"] for t in turns] == ["thist-0", "thist-1", "thist-2"]
        assert all(t["narration"].startswith("The room answers") for t in turns)
        assert all(t["outcome"]["event_id"] for t in turns)

        # ?since=<watermark> returns only newer turns (incremental catch-up).
        watermark = turns[0]["narration_event_id"]
        newer = client.get(f"/api/turns?since={watermark}", headers=headers).json()["turns"]
        assert [t["command_id"] for t in newer] == ["thist-1", "thist-2"]

    def test_api_turns_requires_auth(self, player):
        client, _headers, _, _ = player
        assert client.get("/api/turns").status_code == 401


class TestFailClosedReadiness:
    """Under EVERQUILL_REQUIRE_SECURE=1 the runtime must fail
    readiness (503) rather than fail open — /healthz liveness stays up, but
    /readyz and every game endpoint refuse to serve."""

    def test_require_secure_without_master_key_fails_readiness(
        self, db_url, monkeypatch
    ):
        import importlib

        from fastapi.testclient import TestClient

        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.delenv("APP_DATABASE_URL", raising=False)
        monkeypatch.delenv("EVERQUILL_MASTER_KEY", raising=False)
        monkeypatch.setenv("EVERQUILL_REQUIRE_SECURE", "1")

        import api.main as main_mod

        importlib.reload(main_mod)
        try:
            with TestClient(main_mod.app) as client:
                # liveness stays up so the platform does not kill the container
                assert client.get("/healthz").status_code == 200
                # readiness fails closed (missing master key -> raw-DEK fail-open)
                ready = client.get("/readyz")
                assert ready.status_code == 503
                assert "MASTER_KEY" in ready.text
                # and no play on an insecure runtime
                assert client.get("/api/scene?world=harrowdown").status_code == 503
        finally:
            monkeypatch.delenv("EVERQUILL_REQUIRE_SECURE", raising=False)
            importlib.reload(main_mod)

    def test_readyz_is_200_in_dev_lenient_mode(self, app_client):
        client, _main = app_client
        r = client.get("/readyz")
        assert r.status_code == 200
        assert "ready" in r.text


class TestContextIntegrity:
    """The prior action's `approach` is PLAYER TEXT (encrypted at
    rest); it must be DECRYPTED before it reaches the assembler, not passed
    through as a {"$enc": ...} marker."""

    def test_prior_player_text_is_decrypted_before_the_assembler(
        self, player, monkeypatch
    ):
        client, headers, _, _ = player
        import api.llm_gateway as gateway

        captured = {}

        def capture_narrate(envelope, outcome, action, corrective=None):
            captured["envelope"] = envelope
            return _good_narrate(envelope, outcome, action, corrective)

        monkeypatch.setattr(gateway, "narrate_outcome", capture_narrate)
        # turn 1 — a recognisable approach, stored ENCRYPTED (intent.approach)
        first = client.post(
            "/api/action",
            json={"command_id": "dec-1",
                  "intent": dict(LOOK, approach="peer behind the ale casks")},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        # turn 2 — the assembler pins turn 1 as last_resolution
        second = client.post(
            "/api/action", json={"command_id": "dec-2", "intent": LOOK}, headers=headers
        )
        assert second.status_code == 200, second.text

        trace = captured["envelope"]["assembly"]["last_resolution"]
        assert trace is not None
        # decrypted plaintext reaches the narrator — NOT the encryption marker
        assert trace["action_summary"] == "peer behind the ale casks"
        assert "$enc" not in str(trace)


class TestInFlightLock:
    def test_second_turn_while_one_is_in_flight_is_429(self, player, db_url):
        client, headers, claimed, main_mod = player
        key = main_mod._turn_lock_key(claimed["account_id"])
        holder = connect(db_url)
        try:
            with holder.transaction():
                with holder.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
                    assert cur.fetchone()[0] is True
            r = client.post(
                "/api/action",
                json={"command_id": "lock-1", "intent": LOOK},
                headers=headers,
            )
            assert r.status_code == 429
            assert messages.TURN_IN_FLIGHT in r.text
            assert int(r.headers["retry-after"]) >= 1
        finally:
            holder.close()  # session close releases the advisory lock
        ok = client.post(
            "/api/action", json={"command_id": "lock-2", "intent": LOOK}, headers=headers
        )
        assert ok.status_code == 200, ok.text


# --- probe before parse ---------------------------------------------------


class TestProbeBeforeParse:
    def test_duplicate_free_text_never_buys_a_second_parse(self, player, monkeypatch):
        client, headers, _, _ = player
        import api.llm_gateway as gateway

        calls = {"n": 0}

        def counting_parse(text, roster_text, lists=None):
            calls["n"] += 1
            return dict(LOOK), _fake_usage("parse", "claude-haiku-4-5")

        monkeypatch.setattr(gateway, "parse_free_text", counting_parse)
        first = client.post(
            "/api/action",
            json={"command_id": "probe-1", "text": "look around"},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        assert calls["n"] == 1

        second = client.post(
            "/api/action",
            json={"command_id": "probe-1", "text": "look around"},
            headers=headers,
        )
        assert second.status_code == 200
        body = second.json()
        assert body["absorbed"] is True
        assert calls["n"] == 1  # the replay paid for NO parse
        # ... and answers with the STORED parsed intent, decrypted.
        assert body["intent"]["action_type"] == "observation"
        assert body["intent"]["approach"] == LOOK["approach"]
        assert body["outcome"]["event_id"] == first.json()["outcome"]["event_id"]

    def test_pending_beat_replay_returns_stored_intent_without_a_parse(
        self, player, monkeypatch
    ):
        client, headers, _, _ = player
        import api.llm_gateway as gateway

        for i, loc in enumerate(
            ["loc_harrowdown_market_row", "loc_harrowdown_drove_road",
             "loc_harrowdown_quarry_track"]
        ):
            r = client.post(
                "/api/action",
                json={"command_id": f"probe-walk-{i}", "intent": _move(loc)},
                headers=headers,
            )
            assert r.status_code == 200, r.text

        calls = {"n": 0}

        def counting_parse(text, roster_text, lists=None):
            calls["n"] += 1
            return dict(ATTACK_QUARRYMAN), _fake_usage("parse", "claude-haiku-4-5")

        monkeypatch.setattr(gateway, "parse_free_text", counting_parse)
        first = client.post(
            "/api/action",
            json={"command_id": "probe-pend-1", "text": "charge the quarryman"},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["pending_confirmation"] is True
        assert calls["n"] == 1

        again = client.post(
            "/api/action",
            json={"command_id": "probe-pend-1", "text": "charge the quarryman"},
            headers=headers,
        )
        assert again.status_code == 200
        body = again.json()
        assert body["pending_confirmation"] is True
        assert calls["n"] == 1  # answered from the stored row, parser untouched
        assert body["intent"]["approach"] == ATTACK_QUARRYMAN["approach"]
        assert body["assessment"]["summary"] == "<<Assessment stands. Proceed?>>"
        assert body["assessment"]["tier"] == "hopeless"


# --- narration gate wiring ------------------------------------------------


class TestNarrationGateWiring:
    def test_persistent_gate_failure_ships_deterministic_fallback(
        self, player, monkeypatch, db_url
    ):
        client, headers, _, _ = player
        import api.llm_gateway as gateway

        correctives = []

        def bad_narrate(envelope, outcome, action, corrective=None):
            correctives.append(corrective)
            return (
                "[You roll the dice] <<System: a strong hit>>",
                _fake_usage("narrate", "claude-sonnet-5"),
                None,
            )

        monkeypatch.setattr(gateway, "narrate_outcome", bad_narrate)
        # Unique per run: llm_usage is a GLOBAL append-only ledger on the
        # shared test DB, so a fixed id would accumulate rows across runs.
        command_id = f"gate-fb-{secrets.token_hex(4)}"
        r = client.post(
            "/api/action", json={"command_id": command_id, "intent": LOOK}, headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # exactly ONE re-narrate attempt, with the violations as a corrective line
        assert len(correctives) == 2
        assert correctives[0] is None
        assert "G1" in correctives[1] and "Re-narrate" in correctives[1]
        # deterministic fallback prose, bound to the committed outcome
        assert body["narration"] == narration_gate.fallback_prose(
            body["outcome"], pc_id="pc"
        )
        assert "[" not in body["narration"] and "<<" not in body["narration"]
        assert body["narration_meta"]["gate"] == "fallback"
        assert body["narration_meta"]["gate_violations"]
        # both paid attempts hit the ledger
        with connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM public.llm_usage"
                " WHERE command_id = %s AND stage = 'narrate'",
                (command_id,),
            )
            assert cur.fetchone()[0] == 2

    def test_gate_failure_then_clean_retry_is_served(self, player, monkeypatch):
        client, headers, _, _ = player
        import api.llm_gateway as gateway

        texts = iter([
            "<<A strong hit — the System approves.>>",
            "The room answers you with woodsmoke and low voices.",
        ])

        def flaky_narrate(envelope, outcome, action, corrective=None):
            return next(texts), _fake_usage("narrate", "claude-sonnet-5"), None

        monkeypatch.setattr(gateway, "narrate_outcome", flaky_narrate)
        r = client.post(
            "/api/action", json={"command_id": "gate-rg-1", "intent": LOOK}, headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["narration"].startswith("The room answers")
        assert body["narration_meta"]["gate"] == "regenerated"


# --- invite + prefix hardening ---------------------------------


class TestInviteHardening:
    def test_claim_per_ip_throttle_is_429(self, app_client, monkeypatch):
        client, main_mod = app_client
        monkeypatch.setenv("EVERQUILL_CLAIM_RATE_PER_MIN", "0")
        r = client.post("/api/claim", json={"invite_code": "whatever"})
        assert r.status_code == 429
        assert messages.CLAIM_THROTTLED in r.text
        assert int(r.headers["retry-after"]) >= 1

    def test_claim_global_throttle_is_429(self, app_client, monkeypatch):
        client, main_mod = app_client
        monkeypatch.setenv("EVERQUILL_CLAIM_RATE_GLOBAL_PER_MIN", "0")
        r = client.post("/api/claim", json={"invite_code": "whatever"})
        assert r.status_code == 429
        assert messages.CLAIM_THROTTLED in r.text

    def test_concurrent_claims_of_one_code_have_exactly_one_winner(
        self, app_client, db_url
    ):
        """Atomicity: the single UPDATE .. WHERE claimed_at IS NULL
        RETURNING admits exactly one of N racing claims; losers get the
        uniform rejection."""
        import api.accounts as accounts_mod

        code = track_invite_code(f"test-{secrets.token_hex(4)}")
        with connect(db_url) as conn:
            accounts_mod.seed_env_invites(conn, (code,))

        def one_claim(_):
            with connect(db_url) as conn:
                try:
                    account, _token = accounts_mod.claim(conn, code)
                    return account.account_id
                except accounts_mod.InviteCodeError:
                    return None

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(one_claim, range(6)))
        winners = [r for r in results if r is not None]
        assert len(winners) == 1
        assert results.count(None) == 5
        with connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT claimed_by FROM public.invite WHERE code_hash = %s",
                (accounts_mod.invite_code_hash(code),),
            )
            assert cur.fetchone()[0] == winners[0]

    def test_prefix_collision_retries_with_a_fresh_account_id(
        self, app_client, db_url, monkeypatch
    ):
        """The accounts.prefix UNIQUE index catches a 32-bit prefix
        collision and the claim path re-rolls the account id."""
        import api.accounts as accounts_mod

        code = track_invite_code(f"test-{secrets.token_hex(4)}")
        squatter_id = "deadbeef" + "0" * 24
        with connect(db_url) as conn:
            accounts_mod.seed_env_invites(conn, (code,))
            conn.execute(
                "INSERT INTO public.accounts"
                " (account_id, prefix, invite_code_used, device_token_hash)"
                " VALUES (%s, %s, %s, %s)",
                (squatter_id, "deadbeef", f"test-squat-{secrets.token_hex(3)}",
                 secrets.token_hex(32)),
            )
            conn.commit()

        colliding = "deadbeef" + secrets.token_hex(12)
        fresh = secrets.token_hex(16)
        scripted_ids = [colliding, fresh]
        real_token_hex = secrets.token_hex

        def scripted(n=32):
            if n == 16 and scripted_ids:
                return scripted_ids.pop(0)
            return real_token_hex(n)

        monkeypatch.setattr(accounts_mod.secrets, "token_hex", scripted)
        with connect(db_url) as conn:
            account, _token = accounts_mod.claim(conn, code)
        assert account.account_id == fresh  # retried past the collision
        with connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT claimed_by, claimed_at FROM public.invite WHERE code_hash = %s",
                (accounts_mod.invite_code_hash(code),),
            )
            claimed_by, claimed_at = cur.fetchone()
            assert claimed_by == fresh  # burned once, by the surviving id
            assert claimed_at is not None
