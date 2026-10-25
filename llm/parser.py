"""Quilltouched intent parser: the parse call shared by the eval harness
(parser_eval.py) and the live gateway (api/llm_gateway.py).

Calls claude-haiku-4-5 with structured output by forcing a single tool
(`emit_intent`) whose input schema IS docs/contracts/intent.schema.json.
No engine imports.

API key: the ANTHROPIC_API_KEY env var, or OPENROUTER_API_KEY to reach the same
models through OpenRouter's Anthropic-compatible endpoint (never printed, never
logged).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "contracts" / "intent.schema.json"
PROMPT_PATH = REPO_ROOT / "llm" / "prompts" / "parser.md"

MODEL = "claude-haiku-4-5"
TOOL_NAME = "emit_intent"

#: Schema keywords strict structured outputs reject. Stripped from the copy
#: sent to the API only; responses are still validated against the FULL
#: contract. The single list for both this harness and api/llm_gateway.py.
STRICT_UNSUPPORTED = (
    "pattern", "minLength", "uniqueItems", "maxLength", "maxItems", "minItems",
    "minimum", "maximum",
)

#: Call settings shared with api/llm_gateway.py.
MAX_TOKENS = 1024
TEMPERATURE = 0.0  # parsing wants determinism, not creativity
#: The SDK (anthropic 1.x) no longer takes sampling arguments, so temperature
#: rides in the request body. That works on API version 2023-06-01 only;
#: anthropic 2.x sends 2026-10-21, which rejects it, so requirements.txt pins
#: anthropic below 2 until the parser moves to default sampling.
SAMPLING_BODY = {"temperature": TEMPERATURE}
TOOL_CHOICE = {"type": "tool", "name": TOOL_NAME, "disable_parallel_tool_use": True}


#: OpenRouter's Anthropic-compatible endpoint: the SDK appends /v1/messages and
#: sends the key as a bearer token. Native tool use, tool_choice and
#: cache_control pass through (checked by a live probe on 25 Oct 2026). The
#: tool's ``strict`` schema is NOT enforced there: about one parse in 75 came
#: back outside the contract (an action_type of "compound_action"), so the API
#: re-asks once before refusing (api/main.py, parse_schema_retry).
OPENROUTER_BASE_URL = "https://openrouter.ai/api"
#: Anthropic model id -> OpenRouter's name for the same model.
OPENROUTER_MODELS = {
    "claude-haiku-4-5": "anthropic/claude-haiku-4.5",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
}


def _via_openrouter() -> bool:
    """An Anthropic key wins; OpenRouter is used only when it is the one set."""
    return not os.environ.get("ANTHROPIC_API_KEY") and bool(os.environ.get("OPENROUTER_API_KEY"))


def served_model(model: str) -> str:
    """The id to send for ``model`` on the provider in use."""
    return OPENROUTER_MODELS.get(model, model) if _via_openrouter() else model


#: OpenRouter spreads a model across hosts (Anthropic, Bedrock, Vertex, Azure);
#: pin Anthropic so every parse, and every eval number, comes from one place.
OPENROUTER_ROUTING = {"provider": {"order": ["anthropic"], "allow_fallbacks": False}}


def routing_body() -> dict:
    """The OpenRouter routing pin alone (the narrator sends no sampling fields)."""
    return dict(OPENROUTER_ROUTING) if _via_openrouter() else {}


def request_body() -> dict:
    """Extra request-body fields for the parse: sampling, plus the routing pin."""
    return {**SAMPLING_BODY, **routing_body()}


def _resolve_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    raise RuntimeError("No model key: set ANTHROPIC_API_KEY or OPENROUTER_API_KEY")


def load_intent_schema() -> dict:
    """Contract schema, adapted for use as a strict tool input schema.

    Strict structured outputs reject the STRICT_UNSUPPORTED keywords, so they
    are stripped from the copy sent to the API. The eval harness still
    validates responses against the FULL contract schema (caps included), so
    nothing is lost.
    """
    schema = json.loads(SCHEMA_PATH.read_text())
    for meta_key in ("$schema", "$id", "$comment"):
        schema.pop(meta_key, None)

    def strip(node):
        if isinstance(node, dict):
            for kw in STRICT_UNSUPPORTED:
                node.pop(kw, None)
            for v in node.values():
                strip(v)
        elif isinstance(node, list):
            for v in node:
                strip(v)

    strip(schema)
    return schema


def load_system_prompt() -> str:
    text = PROMPT_PATH.read_text()
    # Everything below the first horizontal rule is the prompt proper.
    _, _, body = text.partition("\n---\n")
    return body.strip() if body.strip() else text


def build_client() -> anthropic.Anthropic:
    if _via_openrouter():
        return anthropic.Anthropic(
            api_key=None,
            auth_token=os.environ["OPENROUTER_API_KEY"],
            base_url=OPENROUTER_BASE_URL,
            timeout=60.0,
            max_retries=3,
        )
    return anthropic.Anthropic(api_key=_resolve_api_key(), timeout=60.0, max_retries=3)


def parse_tool(schema: dict) -> dict:
    """The strict tool the parser is forced to call."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Emit the single ParsedIntent for the player's utterance. "
            "Every field is required; absence is null or []."
        ),
        "strict": True,
        "input_schema": schema,
    }


#: The optional lists the closed fields pick from (topic_ids, transaction,
#: invoked_law_ids), as (keyword, heading). An empty list is left out.
PARSE_LISTS = (("topics", "Topics"), ("prices", "Prices"), ("laws", "Laws"))


def user_message(roster_text: str, utterance: str, **lists: str) -> str:
    """Player text is DATA: it only ever appears under the '## Utterance'
    heading, after the roster and any non-empty Topics, Prices and Laws lists."""
    unknown = set(lists) - {key for key, _ in PARSE_LISTS}
    if unknown:
        raise ValueError(f"unknown parse lists: {sorted(unknown)}")
    parts = [f"## Scene roster\n{roster_text}"]
    for key, heading in PARSE_LISTS:
        if lists.get(key):
            parts.append(f"## {heading}\n{lists[key]}")
    parts.append(f"## Utterance\n{utterance}")
    return "\n\n".join(parts)


def parse_utterance(
    client: anthropic.Anthropic,
    utterance: str,
    roster_text: str,
    system_prompt: str,
    schema: dict,
    **lists: str,
) -> dict:
    """One utterance -> one ParsedIntent dict (unvalidated; caller validates)."""
    response = client.messages.create(
        model=served_model(MODEL),
        max_tokens=MAX_TOKENS,
        extra_body=request_body(),
        # Cached like production (api/llm_gateway.py), so an eval pays what a turn pays.
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        tools=[parse_tool(schema)],
        tool_choice=TOOL_CHOICE,
        messages=[{"role": "user", "content": user_message(roster_text, utterance, **lists)}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block.input
    raise RuntimeError(
        f"No {TOOL_NAME} tool_use block in response "
        f"(stop_reason={response.stop_reason})"
    )
