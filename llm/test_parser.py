"""The parse call's user message: roster, the optional pick-lists, then the
player's words last, so player text is only ever data under '## Utterance'."""

from __future__ import annotations

import pytest

from llm.parser import load_intent_schema, user_message


def test_lists_sit_between_roster_and_utterance_in_a_fixed_order():
    msg = user_message(
        "- npc_a: A", "buy an ale", laws="- law_x: X", prices="- ale: 1 copper", topics="- t: T"
    )
    assert msg == (
        "## Scene roster\n- npc_a: A\n\n"
        "## Topics\n- t: T\n\n"
        "## Prices\n- ale: 1 copper\n\n"
        "## Laws\n- law_x: X\n\n"
        "## Utterance\nbuy an ale"
    )


def test_empty_lists_are_left_out():
    assert user_message("- npc_a: A", "wave", topics="", prices="", laws="") == (
        "## Scene roster\n- npc_a: A\n\n## Utterance\nwave"
    )


def test_unknown_list_is_refused():
    with pytest.raises(ValueError):
        user_message("- npc_a: A", "wave", secrets="- x")


def test_strict_copy_drops_the_numeric_caps_the_api_rejects():
    count = load_intent_schema()["$defs"]["transaction"]["properties"]["count"]
    assert count == {"description": count["description"], "type": "integer"}


def test_an_openrouter_key_routes_through_openrouter(monkeypatch):
    from llm import parser

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    client = parser.build_client()
    assert str(client.base_url).startswith(parser.OPENROUTER_BASE_URL)
    assert client.auth_token == "or-test" and client.api_key is None
    assert parser.served_model("claude-haiku-4-5") == "anthropic/claude-haiku-4.5"


def test_an_anthropic_key_wins(monkeypatch):
    from llm import parser

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    client = parser.build_client()
    assert "openrouter" not in str(client.base_url)
    assert parser.served_model("claude-haiku-4-5") == "claude-haiku-4-5"
