"""Unit tests for the Codex-facing formatting helpers.

Pure — NO API calls, NO DB, NO engine import. Run:
  .venv/bin/python -m pytest llm/test_codex.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex import (  # noqa: E402
    CONFIDENCE_WORDS,
    confidence_word,
    evaluate_hypothesis,
    fact_card,
    fact_cards,
)


def _claim(cid, subject, text, *, source="the Dunmere archive",
           when="Y1-Q2-D14", confidence="uncorroborated", contradiction_ids=()):
    """Read-time InquiryClaim shape (narration_context #/$defs/claim subset)."""
    return {
        "claim_id": cid, "subject_entity_id": subject, "claim_text": text,
        "value_or_range": None, "source": source, "observer": None,
        "method": "archive_research", "world_date": when, "scope": "harrowdown",
        "confidence": confidence, "corroboration_ids": [],
        "contradiction_ids": list(contradiction_ids), "inheritance_status": "original",
    }


# ---- fact_card -------------------------------------------------------------

def test_fact_card_shape_and_fields():
    card = fact_card(_claim(
        "c1", "crt_dragon_vermithrax", "The throat is bare to a spear.",
        source="Ballad of Red Vermithrax", when="Y1-Q3-D02", confidence="consistent"))
    assert set(card) == {"text", "source", "when", "confidence_word", "contested"}
    assert card["text"] == "The throat is bare to a spear."
    assert card["source"] == "Ballad of Red Vermithrax"
    assert card["when"] == "Y1-Q3-D02"
    assert card["confidence_word"] == "consistent"
    assert card["contested"] is False


def test_fact_card_contested_flag():
    plain = fact_card(_claim("c1", "s", "x"))
    contested = fact_card(_claim("c2", "s", "y", contradiction_ids=["c1"]))
    assert plain["contested"] is False
    assert contested["contested"] is True


def test_confidence_word_mapping_and_default():
    assert confidence_word("uncorroborated") == "unconfirmed"
    assert confidence_word("consistent") == "consistent"
    assert confidence_word("strongly_corroborated") == "well-attested"
    # unknown / missing never reads as strong
    assert confidence_word("banana") == "unconfirmed"
    assert confidence_word(None) == "unconfirmed"
    assert set(CONFIDENCE_WORDS) == {"uncorroborated", "consistent", "strongly_corroborated"}


def test_fact_card_defensive_on_missing_keys():
    card = fact_card({})
    assert card == {"text": "", "source": "", "when": "",
                    "confidence_word": "unconfirmed", "contested": False}


def test_fact_cards_preserves_order():
    claims = [_claim("c3", "s", "third"), _claim("c1", "s", "first"), _claim("c2", "s", "second")]
    texts = [c["text"] for c in fact_cards(claims)]
    assert texts == ["third", "first", "second"]


# ---- evaluate_hypothesis ---------------------------------------------------

def test_hypothesis_picks_shared_subject_as_research_target():
    pinned = [
        _claim("c1", "crt_dragon_vermithrax", "throat is bare", contradiction_ids=["c2"]),
        _claim("c2", "crt_dragon_vermithrax", "throat is thickest", contradiction_ids=["c1"]),
        _claim("c3", "crt_ash_wolf", "hunts alone"),
    ]
    out = evaluate_hypothesis(pinned)
    assert out["research_target"] == "crt_dragon_vermithrax"  # 2 pins vs 1
    assert out["subjects"] == ["crt_dragon_vermithrax", "crt_ash_wolf"]
    assert out["resolves"] == ["c1", "c2"]
    assert out["contested"] is True
    assert out["suggested_prompt"] == \
        "Search the archive and ask around about crt_dragon_vermithrax."


def test_hypothesis_uses_label_map_for_prompt():
    pinned = [_claim("c1", "crt_dragon_vermithrax", "x")]
    out = evaluate_hypothesis(pinned, labels={"crt_dragon_vermithrax": "Vermithrax"})
    assert out["suggested_prompt"] == "Search the archive and ask around about Vermithrax."
    assert out["research_target"] == "crt_dragon_vermithrax"  # target stays the id


def test_hypothesis_tiebreak_is_lexicographic_and_deterministic():
    # one pin each on two subjects -> smallest id wins, stably
    pinned = [_claim("c1", "npc_z", "a"), _claim("c2", "npc_a", "b")]
    a = evaluate_hypothesis(pinned)
    b = evaluate_hypothesis(list(reversed(pinned)))
    assert a["research_target"] == "npc_a"
    assert a == b  # order of pinning must not change the suggestion
    assert a["subjects"] == ["npc_a", "npc_z"]


def test_hypothesis_contested_false_when_no_links():
    out = evaluate_hypothesis([_claim("c1", "s", "x"), _claim("c2", "s", "y")])
    assert out["contested"] is False
    assert out["research_target"] == "s"
    assert out["resolves"] == ["c1", "c2"]


def test_hypothesis_empty_input():
    out = evaluate_hypothesis([])
    assert out == {"research_target": None, "subjects": [], "contested": False,
                   "resolves": [], "suggested_prompt": None}


def test_hypothesis_defensive_on_missing_subject():
    out = evaluate_hypothesis([{"claim_id": "c1", "claim_text": "no subject here"}])
    assert out["research_target"] is None
    assert out["subjects"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
