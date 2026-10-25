"""LLM gateway: parser + narrator wired for production.

Wraps the LLM layer's offline modules (llm/parser.py, llm/narrator.py) with the
API-side concerns they deliberately leave to the API:

- prompt-cache breakpoints (``cache_control``) on BOTH stable prefixes: the
  parser's tool schema + system prompt and the narrator's system prompt.
  Render order is tools -> system -> messages, so the system-block breakpoint
  caches the whole stable prefix; the parser also carries one on the tool for
  explicitness. C measured ~5k stable input tokens per parser call — caching
  is the difference between ~$0.024 and ~$0.008 per turn.
- per-stage usage capture (input/output/cache read/cache write tokens +
  latency) for telemetry JSON lines and the public.llm_usage ledger.

Model decisions are LOAD-BEARING and imported from C's modules, never
restated: parser = claude-haiku-4-5, temperature 0, strict tool (p9);
narrator = claude-sonnet-5, max_tokens 400, thinking EXPLICITLY DISABLED
(adaptive thinking would spend the 400-token cap), temperature NOT SENT
(non-default sampling params are rejected on sonnet-5; prose wants variance).

Narration failure NEVER blocks the outcome (locked decision 3: canon never
waits) — ``narrate_outcome`` returns text None on any LLM error and the
caller ships the committed outcome with ``narration: null``.

Hardening:
- GLOBAL LLM concurrency semaphore, size EVERQUILL_LLM_MAX_CONCURRENCY
  (default 4). The endpoints are sync ``def`` routes running in the
  threadpool, so this is a threading semaphore — same intent as the
  review's asyncio semaphore, correct for this execution model.
- Retry budget: at most ONE SDK retry per LLM call per turn
  (``max_retries=1`` on both stages; the parser was 2).
- Defensive rendered-input cap: parse calls estimating > 8k input tokens
  (chars/4 heuristic over system + tool schema + user message) raise
  :class:`ParseInputTooLarge` before any network call; narrate calls over
  the same estimate return an error tuple (canon never waits).
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from llm import narrator as narrator_mod
from llm import parser as parser_mod

_CACHE = {"type": "ephemeral"}

#: Estimated-input-token ceiling per rendered model call. The fixed parser
#: prompt plus the v1.3 contract is ~8k by this estimate on its own, so the
#: ceiling leaves room for a roster, the pick-lists and a 2,000-char utterance;
#: api/tests/test_parser_gateway_parity.py keeps that headroom from shrinking.
MAX_ESTIMATED_INPUT_TOKENS = 12_000

_lock = threading.Lock()
_client = None
_parser_schema: dict | None = None
_parser_system: str | None = None
_narrator_system: str | None = None

# One process-global gate in front of EVERY paid model call.
_llm_semaphore = threading.BoundedSemaphore(
    max(1, int(os.environ.get("EVERQUILL_LLM_MAX_CONCURRENCY", "4")))
)
_SEMAPHORE_WAIT_S = 30.0


class _SemaphoreBusy(Exception):
    """Could not obtain an LLM concurrency slot within the wait budget."""


class _semaphore_slot:
    """``with _semaphore_slot():`` — bounded-wait acquire, always released."""

    def __enter__(self):
        if not _llm_semaphore.acquire(timeout=_SEMAPHORE_WAIT_S):
            raise _SemaphoreBusy(
                f"no LLM concurrency slot within {_SEMAPHORE_WAIT_S:.0f}s"
            )
        return self

    def __exit__(self, *exc_info):
        _llm_semaphore.release()
        return False


def _estimated_tokens(*texts: str) -> int:
    """Cheap chars/4 heuristic — deliberately provider-free and deterministic."""
    return sum(len(t) for t in texts) // 4


def _get_client():
    global _client
    with _lock:
        if _client is None:
            _client = parser_mod.build_client()  # ANTHROPIC_API_KEY env
        return _client


def _parser_assets() -> tuple[dict, str]:
    global _parser_schema, _parser_system
    with _lock:
        if _parser_schema is None:
            # Strict-unsupported keywords stripped; api.main still validates
            # the response against the FULL contract.
            _parser_schema = parser_mod.load_intent_schema()
            _parser_system = parser_mod.load_system_prompt()
        return _parser_schema, _parser_system  # type: ignore[return-value]


def _narrator_system_prompt() -> str:
    global _narrator_system
    with _lock:
        if _narrator_system is None:
            _narrator_system = narrator_mod.load_system_prompt()
        return _narrator_system


@dataclass(frozen=True, slots=True)
class StageUsage:
    stage: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    latency_ms: int

    def as_fields(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "latency_ms": self.latency_ms,
        }


def _usage(stage: str, model: str, response, latency_ms: int) -> StageUsage:
    u = response.usage
    return StageUsage(
        stage=stage,
        model=model,
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        latency_ms=latency_ms,
    )


class ParseFailure(Exception):
    """The parser call failed or returned no tool_use block."""


class ParseInputTooLarge(ParseFailure):
    """The rendered parse input exceeds MAX_ESTIMATED_INPUT_TOKENS.
    Never a player fault at the 2000-char text cap — a tripped cap means a
    bloated roster/prompt and must fail loudly before spending tokens."""


def parse_free_text(
    text: str,
    roster_text: str,
    lists: dict[str, str] | None = None,
    correction: str | None = None,
) -> tuple[dict, StageUsage]:
    """One player utterance -> ParsedIntent dict (unvalidated; caller validates).

    The production form of llm/parser.py::parse_utterance: same tool, user
    message, model and settings (imported, not copied), plus cache_control on
    the tool schema AND the system prompt, and usage returned for cost
    telemetry. Player text is DATA (locked decision 4).
    """
    schema, system_prompt = _parser_assets()
    user_message = parser_mod.user_message(roster_text, text, **(lists or {}))
    if correction:
        # Engine-written, after the utterance: at temperature 0 an identical
        # request returns the identical out-of-contract answer.
        user_message += f"\n\n## Correction\n{correction}"
    estimated = _estimated_tokens(system_prompt, json.dumps(schema), user_message)
    if estimated > MAX_ESTIMATED_INPUT_TOKENS:
        raise ParseInputTooLarge(
            f"rendered parse input ~{estimated} tokens > "
            f"{MAX_ESTIMATED_INPUT_TOKENS} cap"
        )
    tool = {**parser_mod.parse_tool(schema), "cache_control": _CACHE}
    started = time.perf_counter()
    try:
        # Inside the try: a missing key is a parse failure (a System line and
        # a 502), not an unhandled 500 (audit 2026-10-24, claude P3 #16).
        # Retry budget: at most 1 SDK retry per LLM call per turn.
        client = _get_client().with_options(timeout=30.0, max_retries=1)
        with _semaphore_slot():
            response = client.messages.create(
                model=parser_mod.served_model(parser_mod.MODEL),
                max_tokens=parser_mod.MAX_TOKENS,
                extra_body=parser_mod.request_body(),
                system=[{"type": "text", "text": system_prompt, "cache_control": _CACHE}],
                tools=[tool],
                tool_choice=parser_mod.TOOL_CHOICE,
                messages=[{"role": "user", "content": user_message}],
            )
    except Exception as exc:
        raise ParseFailure(f"parser call failed: {type(exc).__name__}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    for block in response.content:
        if block.type == "tool_use" and block.name == parser_mod.TOOL_NAME:
            return dict(block.input), _usage("parse", parser_mod.MODEL, response, latency_ms)
    raise ParseFailure(f"no {parser_mod.TOOL_NAME} tool_use block (stop_reason="
                       f"{response.stop_reason})")


def narrate_outcome(
    envelope: dict, outcome: dict, action: dict, corrective: str | None = None
) -> tuple[str | None, StageUsage | None, str | None]:
    """Narrate a committed outcome. Returns (prose|None, usage|None, error|None).

    NEVER raises: any failure returns (None, None, error) so the caller can
    return the outcome contract immediately (canon never waits, decision 3).
    The user message is C's deterministic U-shaped rendering — player text
    rides inside JSON string literals only.

    ``corrective``: the narration gate's correction for the single
    re-narrate attempt, appended to the END of the user message. It quotes the
    rejected prose, so it never enters a system block; the cached system
    prefix stays byte-identical.
    """
    started = time.perf_counter()
    try:
        user_message = narrator_mod.render_user_message(envelope, outcome, action)
        if corrective:
            user_message += "\n\n" + corrective
        system_prompt = _narrator_system_prompt()
        estimated = _estimated_tokens(system_prompt, user_message)
        if estimated > MAX_ESTIMATED_INPUT_TOKENS:
            return None, None, (
                f"rendered narrate input ~{estimated} tokens > "
                f"{MAX_ESTIMATED_INPUT_TOKENS} cap"
            )
        system: list[dict] = [
            {"type": "text", "text": system_prompt, "cache_control": _CACHE}
        ]
        client = _get_client().with_options(timeout=45.0, max_retries=1)
        with _semaphore_slot():
            response = client.messages.create(
                model=parser_mod.served_model(narrator_mod.MODEL),
                max_tokens=narrator_mod.MAX_TOKENS,
                thinking={"type": "disabled"},  # cap starvation — see llm/narrator.py
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = _usage("narrate", narrator_mod.MODEL, response, latency_ms)
        if not text:
            return None, usage, f"empty narration (stop_reason={response.stop_reason})"
        return text, usage, None
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}"


def record_usage(conn, usage: StageUsage, *, account_id: str | None,
                 world_id: str | None, command_id: str | None) -> None:
    """Append one row to the public.llm_usage ledger. Never raises."""
    try:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO public.llm_usage
                    (account_id, world_id, command_id, stage, model, input_tokens,
                     output_tokens, cache_read_input_tokens,
                     cache_creation_input_tokens, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    account_id, world_id, command_id, usage.stage, usage.model,
                    usage.input_tokens, usage.output_tokens,
                    usage.cache_read_input_tokens,
                    usage.cache_creation_input_tokens, usage.latency_ms,
                ),
            )
    except Exception:  # ledger writes never block a turn
        from api import budget, telemetry

        telemetry.emit("llm_usage_write_failed", stage=usage.stage)
        budget.note_ledger_failure()  # the breaker holds paid layers until writes recover
