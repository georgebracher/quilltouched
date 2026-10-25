"""TEST-ONLY plaintext turn capture gate.

These tests are privacy guards first: an unflagged account must never write a
capture row, and the only enabling path here is the owner-side accounts flag.
"""

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


def _parse_usage() -> StageUsage:
    return StageUsage(
        stage="parse",
        model="claude-haiku-4-5",
        input_tokens=500,
        output_tokens=40,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        latency_ms=50,
    )


def _clear_capture(db_url: str) -> None:
    from everquill_engine.db import connect

    with connect(db_url) as conn:
        conn.execute("DELETE FROM public.test_turn_capture")
        conn.commit()


def _capture_count(db_url: str) -> int:
    from everquill_engine.db import connect

    with connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.test_turn_capture")
        return cur.fetchone()[0]


def _capture_rows(db_url: str, world_id: str) -> list[dict]:
    from everquill_engine.db import connect

    with connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, world_id, command_id, world_time, utterance, action_type,
                   target_entity_ids, approach, pending_confirmation, tier_resolved,
                   outcome_tier, state_deltas, narration, system_note
            FROM public.test_turn_capture
            WHERE world_id = %s
            ORDER BY id
            """,
            (world_id,),
        )
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def _enable_test_capture(db_url: str, account_id: str) -> None:
    from everquill_engine.db import connect

    with connect(db_url) as conn:
        conn.execute(
            "UPDATE public.accounts SET test_capture = true WHERE account_id = %s",
            (account_id,),
        )
        conn.commit()


@pytest.fixture()
def player(app_client, invite_code, monkeypatch):
    """Seed 42 keeps the Quarryman attack hopeless, forcing a confirm beat."""
    import api.accounts as accounts_mod

    monkeypatch.setattr(accounts_mod, "account_seed", lambda account_id: 42)
    client, main_mod = app_client
    claimed = client.post("/api/claim", json={"invite_code": invite_code}).json()
    headers = {"authorization": f"Bearer {claimed['device_token']}"}
    return client, headers, claimed, main_mod


def _walk_to_the_quarry(client, headers) -> None:
    for i, loc in enumerate(
        (
            "loc_harrowdown_market_row",
            "loc_harrowdown_drove_road",
            "loc_harrowdown_quarry_track",
        )
    ):
        r = client.post(
            "/api/action",
            json={"command_id": f"capture-walk-{i}", "intent": _move(loc)},
            headers=headers,
        )
        assert r.status_code == 200, r.text


def test_unflagged_account_captures_nothing(player, db_url):
    _clear_capture(db_url)
    client, headers, _claimed, _main_mod = player

    r = client.post(
        "/api/action",
        json={"command_id": "capture-guard-normal", "intent": LOOK},
        headers=headers,
    )

    assert r.status_code == 200, r.text
    assert _capture_count(db_url) == 0


def test_flagged_account_captures_action_and_confirm_rows(player, db_url, monkeypatch):
    _clear_capture(db_url)
    client, headers, claimed, main_mod = player
    _walk_to_the_quarry(client, headers)
    _enable_test_capture(db_url, claimed["account_id"])

    import api.llm_gateway as gateway

    def fake_parse(text, roster_text, lists=None):
        assert text == "I study the quarry before risking it"
        assert "creature_harrowdown_quarryman" in roster_text
        return {**LOOK, "approach": "study the quarry before risking it"}, _parse_usage()

    def fake_narrate(conn, account, world_content, contract, intent, command_id):
        return f"Narration for {command_id}: {contract['tier_resolved']}.", {
            "gate": "pass"
        }

    monkeypatch.setattr(gateway, "parse_free_text", fake_parse)
    monkeypatch.setattr(main_mod, "_narrate_turn", fake_narrate)

    action = client.post(
        "/api/action",
        json={
            "command_id": "capture-action-1",
            "text": "I study the quarry before risking it",
        },
        headers=headers,
    )
    assert action.status_code == 200, action.text
    action_body = action.json()
    rows = _capture_rows(db_url, claimed["world_id"])
    assert len(rows) == 1
    action_row = rows[0]
    assert action_row["kind"] == "action"
    assert action_row["utterance"] == "I study the quarry before risking it"
    assert action_row["action_type"] == "observation"
    assert action_row["target_entity_ids"] == []
    assert action_row["approach"] == "study the quarry before risking it"
    assert action_row["tier_resolved"] == action_body["outcome"]["tier_resolved"]
    assert action_row["narration"] == action_body["narration"]
    assert action_row["state_deltas"] == action_body["outcome"]["state_deltas"]
    assert action_row["pending_confirmation"] is False

    pending = client.post(
        "/api/action",
        json={"command_id": "capture-confirm-1", "intent": ATTACK_QUARRYMAN},
        headers=headers,
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["pending_confirmation"] is True
    assert len(_capture_rows(db_url, claimed["world_id"])) == 1

    confirmed = client.post(
        "/api/action/confirm",
        json={"command_id": "capture-confirm-1"},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()
    rows = _capture_rows(db_url, claimed["world_id"])
    assert len(rows) == 2
    confirm_row = rows[1]
    assert confirm_row["kind"] == "confirm"
    assert confirm_row["utterance"] is None
    assert confirm_row["action_type"] == "physical"
    assert confirm_row["target_entity_ids"] == ["creature_harrowdown_quarryman"]
    assert confirm_row["tier_resolved"] == "hopeless"
    assert confirm_row["outcome_tier"] == "miss"
    assert confirm_row["state_deltas"] == confirmed_body["outcome"]["state_deltas"]
    assert confirm_row["narration"] == confirmed_body["narration"]
    assert not any(d.get("delta_type") == "hp" for d in confirm_row["state_deltas"])


def test_capture_insert_failure_does_not_break_turn(player, db_url, monkeypatch):
    _clear_capture(db_url)
    client, headers, claimed, main_mod = player
    _enable_test_capture(db_url, claimed["account_id"])

    def broken_insert(*args, **kwargs):
        raise RuntimeError("simulated capture table failure")

    monkeypatch.setattr(main_mod, "_insert_test_turn_capture", broken_insert)
    r = client.post(
        "/api/action",
        json={"command_id": "capture-insert-fails", "intent": LOOK},
        headers=headers,
    )

    assert r.status_code == 200, r.text
    assert r.json()["outcome"]["event_id"]
    assert _capture_count(db_url) == 0
