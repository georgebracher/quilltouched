"""Ratchet on the parser's free text reaching engine decisions.

``approach`` (the parser's paraphrase of HOW the player acts),
``dialogue.quoted_speech`` and ``duration_hint.text`` (the player's words as the
parser copied them) exist for the narrator; the design law says the LLM never
decides an outcome. Any engine code that branches on their wording lets the
parser's word choice steer the result, so every read is listed here, frozen,
exact-match.

A NEW read fails the build. Removing one (by moving that decision onto a typed
intent field) fails until the entry is deleted here too, so the list only
shrinks. Plumbing reads (validation, conversion, the dev CLI) are listed
separately and are not decision paths.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "everquill_engine"

#: Engine functions whose OUTCOMES depend on free-text wording. EMPTY since
#: 2026-10-24: the last decisions (room-directed speech, information-seeking,
#: name exchange and scope subject; authored law matching; purchases; the
#: in-room move; time spans) read the closed intent fields from schema v1.3
#: instead. The mechanism stays: a new read fails the build.
DECISION_READS: set[tuple[str, str]] = set()

#: Reads that carry the field without deciding anything from its wording.
PLUMBING_READS: set[tuple[str, str]] = {
    ("intent.py", "parse_intent"),
    ("intent.py", "_parse_dialogue"),  # validates quoted_speech
    ("intent.py", "_parse_duration"),  # validates the duration's text
    ("resolver/common.py", "_intent_from_typed"),
    ("resolver/common.py", "_with_conversation_partner"),  # carries quoted_speech over
    ("clock.py", "bind_duration"),  # quotes the player's words in a refusal; binds closed fields
    ("cli.py", "_canned_intent"),
    ("cli.py", "_build_menu"),  # writes canned intents
    ("cli.py", "cmd_play"),
}


#: The parser's free-text fields. ``approach`` and ``quoted_speech`` by name;
#: the duration's ``text`` as ``<...duration_hint|hint>.text`` or a ``"text"``
#: key inside a duration function.
_FREE_TEXT_NAMES = frozenset({"approach", "quoted_speech"})


def _reads_free_text(fn: ast.AST) -> bool:
    in_duration_fn = "duration" in getattr(fn, "name", "")
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and node.attr in _FREE_TEXT_NAMES:
            return True
        if isinstance(node, ast.Constant) and node.value in _FREE_TEXT_NAMES:
            return True
        if isinstance(node, ast.Attribute) and node.attr == "text":
            owner = ast.unparse(node.value)
            if owner.endswith("duration_hint") or owner == "hint":
                return True
        if in_duration_fn and isinstance(node, ast.Constant) and node.value == "text":
            return True
    return False


def _approach_reads() -> set[tuple[str, str]]:
    found = set()
    for path in sorted(ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _reads_free_text(fn):
                found.add((str(path.relative_to(ENGINE)), fn.name))
    return found


def test_approach_reads_match_the_frozen_lists_exactly():
    found = _approach_reads()
    new = found - DECISION_READS - PLUMBING_READS
    assert not new, (
        f"new engine read(s) of the parser's free-text approach: {sorted(new)}. "
        "Decide on a typed intent field instead, or argue the case and list it."
    )
    gone = (DECISION_READS | PLUMBING_READS) - found
    assert not gone, f"read(s) removed, shrink the frozen lists: {sorted(gone)}"


def test_the_scan_sees_real_reads():
    """Guard the guard: an empty scan would pass vacuously."""
    assert ("intent.py", "parse_intent") in _approach_reads()
