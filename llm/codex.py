"""Codex-facing formatting helpers. PURE, OFFLINE, STDLIB.

The read-side logic behind the Codex screen (roadmap 3.8) and the hypothesis
pinboard. This module is deliberately dependency-free: NO engine import, NO
network, NO SDK. Every function takes plain dicts (the KnownState-serialised
InquiryClaim shape) and returns plain dicts, so the API layer can call
it directly without dragging a referee-state boundary across the seam.

The claim dicts consumed here are the read-time claim shape defined in
`docs/contracts/narration_context.schema.json#/$defs/claim` (equivalently
`everquill_engine.views.InquiryClaim` serialised): fields used are
`claim_id`, `subject_entity_id`, `claim_text`, `source`, `world_date`,
`confidence`, and `contradiction_ids`. Only KnownState fields are ever touched
— no true value ever reaches this module.

WHAT TEAM F CALLS
-----------------
GET /api/codex  -> for each player InquiryClaim card:
    codex.fact_card(claim_dict) -> {
        "text": str,               # the claim as the player reads it
        "source": str,             # named provenance ("the Dunmere archive")
        "when": str,               # world-date of acquisition
        "confidence_word": str,    # evidence-consistency label, NOT a truth %
        "contested": bool,         # True iff another live claim contradicts it
    }
    # or codex.fact_cards(claims) for the whole list, order preserved.

POST /api/hypothesis (pin >=2 claim ids + optional note) -> research suggestion:
    codex.evaluate_hypothesis(pinned_claim_dicts, labels=<{id: display}>) -> {
        "research_target": str | None,   # the subject id to research to resolve
        "subjects": [str, ...],          # all pinned subjects, most-pinned first
        "contested": bool,               # any pinned card is contested
        "resolves": [str, ...],          # pinned claim_ids the target bears on
        "suggested_prompt": str | None,  # composer pre-seed text (research chip)
    }
    `labels` is an optional {entity_id: display_name} map so the suggested
    prompt reads with a real name; absent it, the entity id is used verbatim.

Both functions are pure and deterministic: same input -> same output, no clock,
no RNG, no ordering that depends on dict insertion beyond what is explicitly
sorted. Safe to unit-test without any fixture DB (see llm/test_codex.py).
"""

from __future__ import annotations

from collections import Counter

__all__ = ["CONFIDENCE_WORDS", "confidence_word", "fact_card", "fact_cards",
           "evaluate_hypothesis"]

# Evidence-CONSISTENCY labels (playbook 3: provenance, never truth-probability).
# The Codex shows where a belief came from and how well corroborated it is — it
# never shows "70% likely true". Keep this the single mapping the UI reads.
CONFIDENCE_WORDS = {
    "uncorroborated": "unconfirmed",
    "consistent": "consistent",
    "strongly_corroborated": "well-attested",
}
_DEFAULT_CONFIDENCE_WORD = "unconfirmed"


def confidence_word(confidence) -> str:
    """Map a claim `confidence` enum to its display word (conservative default
    for anything unrecognised — an unknown confidence never reads as strong)."""
    return CONFIDENCE_WORDS.get(confidence, _DEFAULT_CONFIDENCE_WORD)


def fact_card(claim: dict) -> dict:
    """One InquiryClaim dict -> the flat fact-card shape the Codex renders.

    Defensive against missing keys (the API may hand a partially-populated read
    row); `contested` is True iff the claim carries any live contradiction link.
    """
    contradiction_ids = claim.get("contradiction_ids") or []
    return {
        "text": claim.get("claim_text", ""),
        "source": claim.get("source", ""),
        "when": claim.get("world_date", ""),
        "confidence_word": confidence_word(claim.get("confidence")),
        "contested": bool(contradiction_ids),
    }


def fact_cards(claims: list[dict]) -> list[dict]:
    """fact_card over a list, order preserved (the caller owns sort/filter)."""
    return [fact_card(c) for c in claims]


def evaluate_hypothesis(pinned_claims: list[dict], *, labels: dict | None = None) -> dict:
    """Given the claim cards a player pinned into a hypothesis, work out which
    research target/subject would confirm or deny them.

    The resolving target is the subject the pinned cards most agree on (a
    hypothesis is normally several readings of one thing). Ties break on the
    lexicographically smallest entity id so the suggestion is deterministic.
    `resolves` lists the pinned claim_ids that share that subject — the cards a
    fresh Inquiry against the target would actually corroborate or contest.
    """
    labels = labels or {}

    subjects = [c.get("subject_entity_id") for c in pinned_claims
                if c.get("subject_entity_id")]
    contested = any((c.get("contradiction_ids") or []) for c in pinned_claims)

    if not subjects:
        return {"research_target": None, "subjects": [], "contested": contested,
                "resolves": [], "suggested_prompt": None}

    counts = Counter(subjects)
    # rank subjects by pin-count desc, then id asc (total, deterministic order)
    ordered = sorted(counts, key=lambda s: (-counts[s], s))
    research_target = ordered[0]

    resolves = sorted(c.get("claim_id") for c in pinned_claims
                      if c.get("subject_entity_id") == research_target
                      and c.get("claim_id"))

    display = labels.get(research_target, research_target)
    suggested_prompt = f"Search the archive and ask around about {display}."

    return {
        "research_target": research_target,
        "subjects": ordered,
        "contested": contested,
        "resolves": resolves,
        "suggested_prompt": suggested_prompt,
    }
