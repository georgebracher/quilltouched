"""Claim schema v2 vocabulary + lifecycle rules (synthesis §2.3).

PURE module — no persistence, no engine-rules imports. Three things live
here, all deterministic:

1. **The closed predicate vocabulary** (:data:`PREDICATES`). Claims carry
   a typed ``predicate`` from this registry, never free text, so
   contradiction stays a SQL equality-and-overlap problem — never
   NLI/LLM checking (claim-graphs lens §2, binding). The registry is
   APPEND-ONLY: predicates are never renamed or repurposed; retiring one
   means marking it here with a comment and ceasing to write it.
   :func:`enforce_predicate` is THE parser-boundary hook — ``llm/``
   modules call it when mapping player free text to predicates, so an
   out-of-vocabulary predicate is rejected before it can reach the
   engine (synthesis §2.3: "closed predicate vocabulary enforced at the
   intent-parser boundary").

2. **The strength model**: per-acquisition-method base evidence weights
   (observed > told > rumor > inherited_journal > overheard), integer
   basis points, decayed by world-time age with an integer halving
   schedule (:func:`decayed_weight`). ``claim.strength`` is the cached
   decayed sum of a claim's evidence links, recomputed and stored as a
   FACT whenever a lifecycle event touches the claim — folds apply the
   stored value verbatim (event sourcing, never command sourcing).

3. **The write-time revision rule** (:func:`revise`): given one incoming
   claim and the believer's live claims on the same
   ``(believer, subject, predicate)`` key, decide deterministically
   whether the write is a fresh assertion, corroborating evidence for an
   existing claim, or a contradiction (contest / supersede). The store
   runs this inside the append transaction (one indexed probe per
   insert) and emits the resulting lifecycle EVENTS in the same command;
   the claim table stays a rebuildable projection.

The echo-chamber rule (synthesis pitfall 5): corroboration requires
>= 2 evidence links with DISTINCT ``provenance_root_event_id``. One deed
retold three times raises strength only — it can NEVER flip a claim to
``corroborated``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "CLAIM_STATUSES",
    "ACTIVE_STATUSES",
    "ACQUISITION_METHODS",
    "ACQUISITION_FOR_METHOD",
    "BASE_EVIDENCE_WEIGHT",
    "STRENGTH_HALF_LIFE_MINUTES",
    "SUPERSEDED_REASONS",
    "PredicateSpec",
    "PREDICATES",
    "PredicateError",
    "enforce_predicate",
    "acquisition_for_method",
    "decayed_weight",
    "evidence_strength",
    "corroboration_status",
    "RevisionAction",
    "revise",
]

#: The five lifecycle states (synthesis §2.3). Transitions are EVENTS.
CLAIM_STATUSES = ("asserted", "corroborated", "contested", "superseded", "retracted")

#: Statuses a claim is "live" in — the partial-index filter and the
#: revision rule's probe set.
ACTIVE_STATUSES = ("asserted", "corroborated", "contested")

#: Closed acquisition-method vocabulary with base evidence weights in
#: integer basis points. Ordering is BINDING:
#: observed > told > rumor > inherited_journal > overheard.
BASE_EVIDENCE_WEIGHT: dict[str, int] = {
    "observed": 100,
    "told": 60,
    "rumor": 35,
    "inherited_journal": 20,
    "overheard": 10,
}

ACQUISITION_METHODS = tuple(BASE_EVIDENCE_WEIGHT)

#: Evidence weight halves per this many world-minutes of age (30 world
#: days). Integer arithmetic only: ``weight >> (age // half_life)``,
#: floored at 1 — old evidence fades but never vanishes.
STRENGTH_HALF_LIFE_MINUTES = 30 * 24 * 60

#: Closed supersede-reason vocabulary (Wikidata deprecation rationale —
#: superseded rows are never deleted, the reason says why they lost).
SUPERSEDED_REASONS = (
    "better_evidence",
    "direct_observation",
    "source_recanted",
    "canon_sealed",
)

#: v1 free-text ``method`` values → closed acquisition_method. Used by
#: the claim_written v1→v2 upcaster AND the resolver's claim sites; kept
#: here so the mapping can never fork. Unknown v1 methods map to
#: "told" (a person said it) — the conservative middle weight.
ACQUISITION_FOR_METHOD: dict[str, str] = {
    "witnessed": "observed",
    "misjudged_glance": "observed",
    "survived_attempt": "observed",
    "hard_lesson": "observed",
    "conversation": "told",
    "archive_research": "rumor",
    "rumor": "rumor",
    "appraisal_ii": "observed",
    "source_records": "told",
    "inherited_journal": "inherited_journal",
    "overheard": "overheard",
}

_DEFAULT_ACQUISITION = "told"


def acquisition_for_method(method: str) -> str:
    """Closed acquisition_method for a v1/free-text method label."""
    return ACQUISITION_FOR_METHOD.get(method, _DEFAULT_ACQUISITION)


@dataclass(frozen=True, slots=True)
class PredicateSpec:
    """One registered predicate.

    ``value_type``: which typed value column carries the claim's value —
    ``"none"`` (the predicate itself is the statement), ``"text"``
    (value_text), ``"int"`` (value_num), ``"int_range"`` (value_range).

    ``value_required``: whether a claim of this predicate must carry the
    value (exclusive predicates always do — their value IS the thing
    contradicted); optional-value predicates fall back to ``claim_text``
    for the corroboration-equality check.

    ``exclusive``: one live value per (believer, subject) — a differing
    value on the same key is a CONTRADICTION (write-time probe applies).
    Non-exclusive predicates accumulate (a subject has many facts).

    ``world_valid``: whether claims of this predicate may carry a
    world-time validity range (whereabouts-class; gist-indexed).
    """

    predicate: str
    value_type: str
    value_required: bool
    exclusive: bool
    world_valid: bool
    description: str


def _spec(
    predicate, value_type, value_required, exclusive, world_valid, description
) -> PredicateSpec:
    return PredicateSpec(
        predicate, value_type, value_required, exclusive, world_valid, description
    )


#: THE closed predicate vocabulary (append-only). Contradiction scope is
#: per-spec: exclusive predicates contest/supersede on differing values;
#: non-exclusive predicates coexist and only corroborate on equal values.
PREDICATES: dict[str, PredicateSpec] = {
    "observed_statement": _spec(
        "observed_statement", "text", False, False, False,
        "Generic recorded statement about the subject (claim_text carries the "
        "prose; value_text an optional short form). The v1 free-text migration "
        "target — every pre-v2 claim upcasts to this predicate.",
    ),
    "threat_assessed": _spec(
        "threat_assessed", "text", True, True, False,
        "The believer's read of the subject's threat, as a plausibility band "
        "word (TRIVIAL..HOPELESS). Exclusive: a new read contradicts an old one.",
    ),
    "common_knowledge": _spec(
        "common_knowledge", "text", True, False, False,
        "A piece of the subject's common knowledge learned in play "
        "(conversation, research; value_text = the fact). Accumulative — many "
        "facts coexist; equal facts corroborate.",
    ),
    "disposition_toward": _spec(
        "disposition_toward", "text", True, True, False,
        "How the subject currently stands toward the believer "
        "(value_text: rapport|owes_favor|rebuffed|hostile|neutral). Exclusive.",
    ),
    "personal_lesson": _spec(
        "personal_lesson", "text", False, False, False,
        "A lesson the believer recorded about the subject (or themselves). "
        "Accumulative journal-fodder.",
    ),
    "whereabouts": _spec(
        "whereabouts", "text", True, True, True,
        "Where the subject is believed to be (value_text: location id). "
        "Exclusive, world_valid-ranged — the gist-index predicate class. "
        "Registered ahead of the rumor-propagation sprint; no writer yet.",
    ),
    "weak_point": _spec(
        "weak_point", "text", True, False, False,
        "A specific known vulnerability of the subject (value_text: the "
        "weak point, e.g. 'the bare patch on its left breast'). Accumulative "
        "— a subject may have several; equal ones corroborate. Holding one is "
        "knowledge that changes the ACTION SPACE (roadmap §3.3): the resolver "
        "consults it as a target-specific modifier, turning a HOPELESS "
        "physical confrontation into a DESPERATE option. Written by deep "
        "appraisal tiers (a source's knowledge_scope reveal); never by a bare "
        "glance.",
    ),
}


class PredicateError(ValueError):
    """A claim violates the closed predicate vocabulary."""


def enforce_predicate(
    predicate: str,
    *,
    value_text: str | None = None,
    value_num: int | None = None,
    value_range: tuple[int, int] | list[int] | None = None,
    world_valid: tuple[int, int] | list[int] | None = None,
) -> PredicateSpec:
    """THE parser-boundary enforcement hook (exported for ``llm/``).

    Validates a predicate + typed value shape against the registry and
    returns the spec. Raises :class:`PredicateError` on any deviation:
    unknown predicate, value in the wrong column, missing required
    value, floats where integers are demanded, world_valid on a
    predicate that doesn't range.
    """
    spec = PREDICATES.get(predicate)
    if spec is None:
        raise PredicateError(
            f"unknown predicate {predicate!r} — the vocabulary is closed "
            f"(registered: {', '.join(sorted(PREDICATES))})"
        )
    populated = {
        "text": value_text is not None,
        "int": value_num is not None,
        "int_range": value_range is not None,
    }
    expected = spec.value_type
    for column, present in populated.items():
        if present and column != expected:
            raise PredicateError(
                f"predicate {predicate!r} carries value_type {expected!r}; "
                f"a {column!r} value is a vocabulary violation"
            )
    if spec.value_required and not populated.get(expected, False):
        raise PredicateError(
            f"predicate {predicate!r} requires a {expected!r} value"
        )
    if value_num is not None and (isinstance(value_num, bool) or not isinstance(value_num, int)):
        raise PredicateError("value_num must be an integer (integer-only domains, LOW-1)")
    if value_range is not None:
        if (
            len(value_range) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in value_range)
        ):
            raise PredicateError("value_range must be [int, int]")
    if world_valid is not None:
        if not spec.world_valid:
            raise PredicateError(
                f"predicate {predicate!r} does not carry world_valid ranges"
            )
        if (
            len(world_valid) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in world_valid)
        ):
            raise PredicateError("world_valid must be [int, int] (world minutes)")
    return spec


# --- strength model -------------------------------------------------------------


def decayed_weight(base_weight: int, age_minutes: int) -> int:
    """Integer decay: halve per elapsed half-life, floor 1. Pure."""
    if age_minutes < 0:
        raise ValueError(f"evidence from the future: age {age_minutes}")
    halvings = age_minutes // STRENGTH_HALF_LIFE_MINUTES
    return max(1, base_weight >> min(halvings, 30))


def evidence_strength(evidence: list[dict[str, Any]], now_world_time: int) -> int:
    """Cached ``claim.strength``: decayed sum of evidence link weights.

    Each link dict carries ``base_weight`` and ``world_time`` (facts
    stored on the link when it was written). Deterministic for a given
    (links, now) pair — lifecycle events stamp the result.
    """
    return sum(
        decayed_weight(link["base_weight"], now_world_time - link["world_time"])
        for link in evidence
    )


def corroboration_status(evidence: list[dict[str, Any]]) -> str:
    """'corroborated' iff >= 2 evidence links with DISTINCT provenance
    roots — the echo-chamber rule. Retellings of one root never flip
    status; they only raise strength."""
    roots = {link["root_event_id"] for link in evidence}
    return "corroborated" if len(roots) >= 2 else "asserted"


# --- write-time revision rule -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class RevisionAction:
    """One deterministic consequence of a claim write.

    kind:
      - ``insert``      — write the new claim row (claim_written stands).
      - ``corroborate`` — the write matched an existing live claim's value;
                          drop the new row, attach evidence to ``claim_id``.
      - ``contest``     — mark ``claim_id`` contested by ``other_claim_id``.
      - ``supersede``   — mark ``claim_id`` superseded by ``other_claim_id``
                          for ``reason``.
    """

    kind: str
    claim_id: str | None = None
    other_claim_id: str | None = None
    reason: str | None = None


def _values_equal(new_claim: dict[str, Any], row: dict[str, Any]) -> bool:
    """Same-claim test for corroboration. Typed value columns first; when
    NEITHER side carries a value (optional-value predicates), fall back
    to claim_text equality so two different statements never merge."""
    fields = ("value_text", "value_num", "value_range")
    if any(new_claim.get(f) is not None or row.get(f) is not None for f in fields):
        return all(new_claim.get(f) == row.get(f) for f in fields)
    return new_claim.get("claim_text") == row.get("claim_text")


def _ranges_overlap(a, b) -> bool:
    if a is None or b is None:
        return True  # an unranged claim overlaps everything on the key
    return a[0] <= b[1] and b[0] <= a[1]


def revise(
    *,
    new_claim: dict[str, Any],
    new_strength: int,
    existing: list[dict[str, Any]],
    existing_strength: dict[str, int],
) -> list[RevisionAction]:
    """The deterministic write-time revision rule (one believer's mind).

    ``new_claim``: the incoming claim's typed fields (predicate,
    value_text/num/range, world_valid). ``existing``: the believer's
    LIVE claims on the same (believer, subject, predicate) key, oldest
    first (claim_id order). ``existing_strength``: claim_id → current
    decayed strength.

    Rules, in order:
    1. Equal value on any live claim → corroborate that claim (oldest
       match wins; the new row is dropped in favor of an evidence link).
    2. Differing value on an exclusive predicate with overlapping
       world_valid → contradiction: if the new claim outweighs a live
       claim — strictly stronger, or equal-strength with fresh DIRECT
       OBSERVATION (your own eyes beat a stale read of the same weight)
       — that claim is SUPERSEDED (reason: direct_observation when the
       new evidence is 'observed', else better_evidence); otherwise both
       are marked contested, challenger links both ways, both stay
       active (Talk-of-the-Town candidate beliefs — narrator gold).
    3. Otherwise → plain insert (non-exclusive predicates accumulate).
    """
    spec = PREDICATES[new_claim["predicate"]]
    for row in existing:
        if _values_equal(new_claim, row):
            return [RevisionAction(kind="corroborate", claim_id=row["claim_id"])]

    if not spec.exclusive:
        return [RevisionAction(kind="insert")]

    actions: list[RevisionAction] = [RevisionAction(kind="insert")]
    new_id = new_claim["claim_id"]
    new_method = new_claim["acquisition_method"]
    for row in existing:
        if not _ranges_overlap(new_claim.get("world_valid"), row.get("world_valid")):
            continue
        old_strength = existing_strength[row["claim_id"]]
        outweighs = new_strength > old_strength or (
            new_strength == old_strength and new_method == "observed"
        )
        if outweighs:
            reason = "direct_observation" if new_method == "observed" else "better_evidence"
            actions.append(
                RevisionAction(
                    kind="supersede",
                    claim_id=row["claim_id"],
                    other_claim_id=new_id,
                    reason=reason,
                )
            )
        else:
            actions.append(
                RevisionAction(kind="contest", claim_id=row["claim_id"], other_claim_id=new_id)
            )
            actions.append(
                RevisionAction(kind="contest", claim_id=new_id, other_claim_id=row["claim_id"])
            )
    return actions
