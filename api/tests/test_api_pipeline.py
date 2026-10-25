"""The turn pipeline: intent -> (parse) -> beat -> resolve -> narrate."""

from __future__ import annotations

import pytest

from api.llm_gateway import StageUsage

LOOK = {
    "action_type": "observation",
    "target_entity_ids": [],
    "approach": "take in the room",
    "stat_hint": None,
    "dialogue": None,
    "plausibility_hint": "plausible",
    "duration_hint": None,
    "ambiguity_flags": [],
    "addressee": None,
    "speech_act": None,
    "topic_ids": [],
    "transaction": None,
    "invoked_law_ids": [],
    "movement_scope": None,
}


def _move(where: str) -> dict:
    return {
        "action_type": "movement",
        "target_entity_ids": [where],
        "approach": "walk there",
        "stat_hint": None,
        "dialogue": None,
        "plausibility_hint": "plausible",
        "duration_hint": None,
        "ambiguity_flags": [],
        "addressee": None,
        "speech_act": None,
        "topic_ids": [],
        "transaction": None,
        "invoked_law_ids": [],
        "movement_scope": None,
    }


def _dialogue(targets=(), *, addressee=None, approach="ask a question", flags=()):
    return {
        "action_type": "dialogue",
        "target_entity_ids": list(targets),
        "approach": approach,
        "stat_hint": None,
        "dialogue": {"addressee_id": addressee, "quoted_speech": None},
        "plausibility_hint": "plausible",
        "duration_hint": None,
        "ambiguity_flags": list(flags),
        "addressee": None,
        "speech_act": None,
        "topic_ids": [],
        "transaction": None,
        "invoked_law_ids": [],
        "movement_scope": None,
    }


def _alias(roster_text: str, label: str) -> str:
    """The id the parser roster gives the person shown by ``label``."""
    for line in roster_text.splitlines():
        if f": {label}" in line:
            return line.removeprefix("- ").split(":")[0]
    raise AssertionError(f"{label!r} not in roster:\n{roster_text}")


ATTACK_QUARRYMAN = {
    "action_type": "physical",
    "target_entity_ids": ["creature_harrowdown_quarryman"],
    "approach": "a straight charge with a knife",
    "stat_hint": "might",
    "dialogue": None,
    "plausibility_hint": "plausible",
    "duration_hint": None,
    "ambiguity_flags": [],
    "addressee": None,
    "speech_act": None,
    "topic_ids": [],
    "transaction": None,
    "invoked_law_ids": [],
    "movement_scope": None,
}


@pytest.fixture()
def player(app_client, invite_code, monkeypatch):
    """A claimed account with a DETERMINISTIC world seed (42: might 5 — the
    Quarryman at threat 14 tiers HOPELESS (gap 9) -> Suicidal -> <<Proceed?>>)."""
    import api.accounts as accounts_mod

    monkeypatch.setattr(accounts_mod, "account_seed", lambda account_id: 42)
    client, main_mod = app_client
    claimed = client.post("/api/claim", json={"invite_code": invite_code}).json()
    headers = {"authorization": f"Bearer {claimed['device_token']}"}
    return client, headers, claimed


class TestStructuredIntent:
    def test_trivial_action_resolves_with_outcome_contract(self, player):
        client, headers, _ = player
        r = client.post(
            "/api/action", json={"command_id": "look-1", "intent": LOOK}, headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pending_confirmation"] is False
        assert body["absorbed"] is False
        assert body["outcome"]["tier_resolved"] == "trivial"
        assert body["assessment"]["confirmation_required"] is False
        # Narrator is stubbed off in tests: outcome ships anyway (decision 3).
        assert body["narration"] is None

    def test_duplicate_command_is_absorbed_with_stored_outcome(self, player):
        client, headers, _ = player
        first = client.post(
            "/api/action", json={"command_id": "dup-1", "intent": LOOK}, headers=headers
        ).json()
        second = client.post(
            "/api/action", json={"command_id": "dup-1", "intent": LOOK}, headers=headers
        ).json()
        assert second["absorbed"] is True
        assert second["outcome"]["event_id"] == first["outcome"]["event_id"]
        assert second["narration"] is None  # duplicates never re-narrate

    def test_intent_schema_violations_are_422(self, player):
        client, headers, _ = player
        r = client.post(
            "/api/action",
            json={"command_id": "bad-1", "intent": {"action_type": "dance"}},
            headers=headers,
        )
        assert r.status_code == 422
        assert "intent_schema_violations" in r.text

    def test_exactly_one_of_intent_or_text(self, player):
        client, headers, _ = player
        r = client.post("/api/action", json={"command_id": "x"}, headers=headers)
        assert r.status_code == 422
        r = client.post(
            "/api/action",
            json={"command_id": "x", "intent": LOOK, "text": "look"},
            headers=headers,
        )
        assert r.status_code == 422


class TestCommitBeat:
    def _walk_to_the_quarry(self, client, headers):
        walk = ["loc_harrowdown_market_row", "loc_harrowdown_drove_road",
                "loc_harrowdown_quarry_track"]
        for i, loc in enumerate(walk):
            r = client.post(
                "/api/action",
                json={"command_id": f"walk-{i}", "intent": _move(loc)},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["pending_confirmation"] is False  # movement auto-commits

    def test_dire_plus_returns_pending_then_confirm_resolves(self, player):
        client, headers, _ = player
        self._walk_to_the_quarry(client, headers)

        r = client.post(
            "/api/action",
            json={"command_id": "quarryman-1", "intent": ATTACK_QUARRYMAN},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pending_confirmation"] is True
        assert body["assessment"]["confirmation_required"] is True
        assert body["assessment"]["tier"] == "hopeless"
        assert "Proceed?" in body["assessment"]["summary"]
        assert "outcome" not in body  # NOTHING resolved yet — no dice, no canon

        # Re-declaring while pending is idempotent (assessment stands).
        again = client.post(
            "/api/action",
            json={"command_id": "quarryman-1", "intent": ATTACK_QUARRYMAN},
            headers=headers,
        ).json()
        assert again["pending_confirmation"] is True

        confirmed = client.post(
            "/api/action/confirm", json={"command_id": "quarryman-1"}, headers=headers
        )
        assert confirmed.status_code == 200, confirmed.text
        outcome = confirmed.json()["outcome"]
        assert outcome["tier_resolved"] == "hopeless"
        assert outcome["outcome_tier"] == "miss"  # hopeless always misses

        # A repeated confirm is absorbed against the stored contract.
        dup = client.post(
            "/api/action/confirm", json={"command_id": "quarryman-1"}, headers=headers
        ).json()
        assert dup["absorbed"] is True
        assert dup["outcome"]["event_id"] == outcome["event_id"]

    def test_confirm_without_pending_is_404(self, player):
        client, headers, _ = player
        r = client.post(
            "/api/action/confirm", json={"command_id": "never-declared"}, headers=headers
        )
        assert r.status_code == 404


class TestFreeTextParse:
    @staticmethod
    def _parse_usage() -> StageUsage:
        return StageUsage(
            stage="parse", model="claude-haiku-4-5", input_tokens=500,
            output_tokens=40, cache_read_input_tokens=0,
            cache_creation_input_tokens=0, latency_ms=50,
        )

    def test_text_goes_through_the_parser_and_usage_is_ledgered(
        self, player, monkeypatch, db_url
    ):
        client, headers, claimed = player
        import api.llm_gateway as gateway

        seen = {}

        def fake_parse(text, roster_text, lists=None):
            seen["text"] = text
            seen["roster"] = roster_text
            usage = StageUsage(
                stage="parse", model="claude-haiku-4-5", input_tokens=5000,
                output_tokens=80, cache_read_input_tokens=4600,
                cache_creation_input_tokens=0, latency_ms=900,
            )
            return dict(LOOK), usage

        monkeypatch.setattr(gateway, "parse_free_text", fake_parse)
        r = client.post(
            "/api/action",
            json={"command_id": "ft-1", "text": "I look around the room"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert seen["text"] == "I look around the room"
        # The scene roster is supplied, unlearned people by alias only (identity fog).
        assert _alias(seen["roster"], "the barkeep").startswith("person_")
        assert "npc_harrowdown_maren_ostler" not in seen["roster"]
        assert r.json()["intent"]["action_type"] == "observation"

        from everquill_engine.db import connect

        with connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT stage, model, input_tokens, cache_read_input_tokens "
                "FROM public.llm_usage WHERE command_id = %s", ("ft-1",),
            )
            rows = cur.fetchall()
        assert ("parse", "claude-haiku-4-5", 5000, 4600) in rows

    def test_blocked_movement_returns_exit_note_without_narration(
        self, player, monkeypatch
    ):
        client, headers, _claimed = player
        import api.llm_gateway as gateway
        import api.main as main_mod

        def fake_parse(text, roster_text, lists=None):
            assert text == "go to the drove road"
            assert "loc_harrowdown_market_row" in roster_text
            return _move("loc_harrowdown_drove_road"), self._parse_usage()

        narrated = {"count": 0}

        def spy_narrate(*args, **kwargs):
            narrated["count"] += 1
            raise AssertionError("blocked movement must not call the narrator")

        monkeypatch.setattr(gateway, "parse_free_text", fake_parse)
        monkeypatch.setattr(main_mod, "_narrate_turn", spy_narrate)

        before = client.get("/api/scene", headers=headers).json()["location"]["id"]
        r = client.post(
            "/api/action",
            json={"command_id": "blocked-drove-road", "text": "go to the drove road"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pending_confirmation"] is False
        assert body["intent"]["action_type"] == "movement"
        assert body["intent"]["target_entity_ids"] == ["loc_harrowdown_drove_road"]
        assert body["outcome"]["movement_blocked"] is True
        assert body["outcome"]["state_deltas"] == []
        assert body["narration"] is None
        assert body["narration_meta"]["gate"] == "movement_blocked"
        assert (
            body["system_note"]
            == "You stay where you are. From here you can go to: Market Row."
        )
        assert "You stay where you are." in body["system_note"]
        assert "From here you can go to: Market Row." in body["system_note"]
        assert "Drove Road" not in body["system_note"]
        assert narrated["count"] == 0

        after = client.get("/api/scene", headers=headers).json()["location"]["id"]
        assert after == before == "loc_harrowdown_tavern"

    @pytest.mark.parametrize(
        "utterance",
        ("look around the tavern", "observe the room", "survey the tavern"),
    )
    def test_current_location_observation_target_is_ambient(
        self, player, monkeypatch, utterance
    ):
        client, headers, _claimed = player
        import api.llm_gateway as gateway

        def fake_parse(text, roster_text, lists=None):
            assert text == utterance
            assert "loc_harrowdown_tavern" in roster_text
            usage = StageUsage(
                stage="parse", model="claude-haiku-4-5", input_tokens=500,
                output_tokens=40, cache_read_input_tokens=0,
                cache_creation_input_tokens=0, latency_ms=50,
            )
            return dict(
                LOOK,
                target_entity_ids=["loc_harrowdown_tavern"],
                approach=utterance,
            ), usage

        monkeypatch.setattr(gateway, "parse_free_text", fake_parse)
        command_id = "ambient-loc-" + utterance.replace(" ", "-")
        r = client.post(
            "/api/action",
            json={"command_id": command_id, "text": utterance},
            headers=headers,
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pending_confirmation"] is False
        assert body["outcome"]["tier_resolved"] == "trivial"
        assert body["outcome"]["risk_label_shown"] is None
        assert body["outcome"]["dice"] is None
        assert body["outcome"]["outcome_tier"] is None

    def test_an_out_of_contract_parse_is_asked_once_more(self, player, monkeypatch):
        """OpenRouter does not enforce the strict tool schema: a parse once came
        back as action_type "compound_action" and the player got a 422. One
        re-ask now comes first (25 Oct 2026)."""
        client, headers, _claimed = player
        import api.llm_gateway as gateway

        replies = [dict(LOOK, action_type="compound_action"), dict(LOOK)]
        corrections = []

        def fake_parse(text, roster_text, lists=None, correction=None):
            corrections.append(correction)
            return replies.pop(0), self._parse_usage()

        monkeypatch.setattr(gateway, "parse_free_text", fake_parse)
        r = client.post(
            "/api/action",
            json={"command_id": "reask-1", "text": "look around and take it all in"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["intent"]["action_type"] == "observation"
        assert replies == []
        assert corrections[0] is None and "compound_action" in corrections[1]

    def test_parser_failure_is_502_and_blocks_nothing_else(self, player, monkeypatch):
        client, headers, _ = player
        import api.llm_gateway as gateway

        def broken(text, roster_text, lists=None):
            raise gateway.ParseFailure("no tool_use block")

        monkeypatch.setattr(gateway, "parse_free_text", broken)
        r = client.post(
            "/api/action", json={"command_id": "ft-2", "text": "hello"}, headers=headers
        )
        assert r.status_code == 502
        # Structured intents still work fine afterwards.
        ok = client.post(
            "/api/action", json={"command_id": "ft-3", "intent": LOOK}, headers=headers
        )
        assert ok.status_code == 200

    def test_ambiguous_followup_uses_sticky_conversation_partner(
        self, player, monkeypatch
    ):
        client, headers, _claimed = player
        import api.llm_gateway as gateway

        def usage():
            return StageUsage(
                stage="parse", model="claude-haiku-4-5", input_tokens=500,
                output_tokens=40, cache_read_input_tokens=0,
                cache_creation_input_tokens=0, latency_ms=50,
            )

        def fake_parse(text, roster_text, lists=None):
            assert "npc_harrowdown_jorun_pike" not in roster_text
            assert _alias(roster_text, "the barkeep").startswith("person_")
            if "Jorun" in text:
                # The player names him; the model only has the alias to pick.
                wary_man = _alias(roster_text, "a wary man")
                return _dialogue(
                    [wary_man],
                    addressee=wary_man,
                    approach="ask Jorun about his captain's plate",
                ), usage()
            return _dialogue(
                [],
                addressee=None,
                approach="ask about his captain's plate",
                flags=["ambiguous_addressee"],
            ), usage()

        monkeypatch.setattr(gateway, "parse_free_text", fake_parse)
        first = client.post(
            "/api/action",
            json={"command_id": "sticky-1", "text": "Ask Jorun about his plate"},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["intent"]["target_entity_ids"] == [
            "npc_harrowdown_jorun_pike"
        ]

        followup = client.post(
            "/api/action",
            json={"command_id": "sticky-2", "text": "ask about his captain's plate"},
            headers=headers,
        )
        assert followup.status_code == 200, followup.text
        intent = followup.json()["intent"]
        assert intent["target_entity_ids"] == ["npc_harrowdown_jorun_pike"]
        assert intent["dialogue"]["addressee_id"] == "npc_harrowdown_jorun_pike"

    def test_free_text_purchase_prices_from_the_parsed_transaction(
        self, player, monkeypatch
    ):
        client, headers, _claimed = player
        import api.llm_gateway as gateway

        def fake_parse(text, roster_text, lists=None):
            assert text == "buy an ale"
            barkeep = _alias(roster_text, "the barkeep")
            # The closed fields pick from these lists: goods the engine sells,
            # and what Maren (present) could be asked about.
            assert "- ale_pint_copper: 1 copper" in lists["prices"]
            assert "knife_copper" not in lists["prices"]
            assert "creature_harrowdown_quarryman" in lists["topics"]
            usage = StageUsage(
                stage="parse", model="claude-haiku-4-5", input_tokens=500,
                output_tokens=40, cache_read_input_tokens=0,
                cache_creation_input_tokens=0, latency_ms=50,
            )
            return {
                "action_type": "social",
                "target_entity_ids": [barkeep],
                "approach": "casual purchase at the bar",
                "stat_hint": None,
                "dialogue": None,
                "plausibility_hint": "plausible",
                "duration_hint": None,
                "ambiguity_flags": [],
                "addressee": "person",
                "speech_act": "statement",
                "topic_ids": [],
                "transaction": {"kind": "buy", "price_key": "ale_pint_copper", "count": 1},
                "invoked_law_ids": [],
                "movement_scope": None,
            }, usage

        monkeypatch.setattr(gateway, "parse_free_text", fake_parse)
        r = client.post(
            "/api/action",
            json={"command_id": "buy-ale-1", "text": "buy an ale"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        deltas = r.json()["outcome"]["state_deltas"]
        assert any(
            d["delta_type"] == "coin" and d["amount"] == -1 and d["reason"] == "drink"
            for d in deltas
        )


class TestNarration:
    def test_valid_adjacent_movement_is_still_narrated(self, player, monkeypatch):
        client, headers, _claimed = player
        import api.main as main_mod

        calls = {"count": 0}

        def fake_narrate(conn, account, world_content, contract, intent, command_id):
            calls["count"] += 1
            assert contract["movement_blocked"] is False
            assert any(d["delta_type"] == "position" for d in contract["state_deltas"])
            assert intent["action_type"] == "movement"
            return "Bran steps out into Market Row.", {"gate": "pass"}

        monkeypatch.setattr(main_mod, "_narrate_turn", fake_narrate)
        r = client.post(
            "/api/action",
            json={
                "command_id": "move-market-narrates",
                "intent": _move("loc_harrowdown_market_row"),
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["narration"] == "Bran steps out into Market Row."
        assert body["system_note"] is None
        assert calls["count"] == 1
        assert any(
            d["delta_type"] == "position"
            and d["to_location_id"] == "loc_harrowdown_market_row"
            for d in body["outcome"]["state_deltas"]
        )

    def test_narration_is_returned_with_the_outcome_and_ledgered(
        self, player, monkeypatch, db_url
    ):
        client, headers, claimed = player
        import api.llm_gateway as gateway

        captured = {}

        def fake_narrate(envelope, outcome, action):
            captured["envelope"] = envelope
            captured["outcome"] = outcome
            captured["action"] = action
            usage = StageUsage(
                stage="narrate", model="claude-sonnet-5", input_tokens=2600,
                output_tokens=180, cache_read_input_tokens=2300,
                cache_creation_input_tokens=0, latency_ms=2400,
            )
            return "The room answers you with woodsmoke and low voices.", usage, None

        monkeypatch.setattr(gateway, "narrate_outcome", fake_narrate)
        r = client.post(
            "/api/action", json={"command_id": "nar-1", "intent": LOOK}, headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["narration"].startswith("The room answers")
        assert body["narration_meta"]["content_hash"]
        assert body["narration_meta"]["assembler_version"]

        # The envelope the narrator saw is the assembler's contract shape,
        # built from the KnownState surface only.
        env = captured["envelope"]
        assert set(env) == {
            "scene_manifest", "known_sheet_slices", "salient_claims",
            "active_clocks", "canon_excerpts", "token_budget", "assembly",
        }
        assert env["scene_manifest"]["location_id"] == "loc_harrowdown_tavern"
        atmo = [c for c in env["canon_excerpts"] if c["source_ref"].startswith("atmosphere:")]
        assert atmo, "Team B's atmosphere should reach the narrator context"
        assert captured["action"]["action_type"] == "observation"
        assert captured["outcome"]["event_id"] == body["outcome"]["event_id"]

        from everquill_engine.db import connect

        with connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT stage, model FROM public.llm_usage WHERE command_id = %s",
                ("nar-1",),
            )
            assert ("narrate", "claude-sonnet-5") in cur.fetchall()

    def test_narration_failure_never_blocks_the_outcome(self, player):
        # conftest stubs narrate_outcome to (None, None, error): decision 3.
        client, headers, _ = player
        r = client.post(
            "/api/action", json={"command_id": "nf-1", "intent": LOOK}, headers=headers
        )
        assert r.status_code == 200
        body = r.json()
        assert body["outcome"]["event_id"]
        assert body["narration"] is None


class TestOpsUsage:
    def test_requires_the_ops_token(self, player, monkeypatch):
        client, headers, _ = player
        monkeypatch.delenv("EVERQUILL_OPS_TOKEN", raising=False)
        assert client.get("/api/ops/usage").status_code == 503
        monkeypatch.setenv("EVERQUILL_OPS_TOKEN", "ops-secret")
        assert client.get("/api/ops/usage").status_code == 401
        assert (
            client.get(
                "/api/ops/usage", headers={"authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        r = client.get("/api/ops/usage", headers={"authorization": "Bearer ops-secret"})
        assert r.status_code == 200
        assert "rollup" in r.json()

    def test_rollup_reports_ledgered_stages(self, player, monkeypatch, db_url):
        client, headers, _ = player
        import api.llm_gateway as gateway

        def fake_narrate(envelope, outcome, action):
            usage = StageUsage(
                stage="narrate", model="claude-sonnet-5", input_tokens=1000,
                output_tokens=100, cache_read_input_tokens=0,
                cache_creation_input_tokens=0, latency_ms=1000,
            )
            return "Prose.", usage, None

        monkeypatch.setattr(gateway, "narrate_outcome", fake_narrate)
        client.post(
            "/api/action", json={"command_id": "roll-1", "intent": LOOK}, headers=headers
        )
        monkeypatch.setenv("EVERQUILL_OPS_TOKEN", "ops-secret")
        r = client.get("/api/ops/usage", headers={"authorization": "Bearer ops-secret"})
        rows = r.json()["rollup"]
        narrate_rows = [x for x in rows if x["stage"] == "narrate"]
        assert narrate_rows and narrate_rows[0]["estimated_cost_usd"] is not None
