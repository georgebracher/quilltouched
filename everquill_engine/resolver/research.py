"""Research against a source's knowledge scope, and the rumor picks it feeds:
who governs a question, what they know, where to look next."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from everquill_engine.ladder import (
    OutcomeTier,
    PlausibilityTier,
    band_for_gap,
)
from everquill_engine.resolver.common import (
    _effective_threat,
    _fog_known_fact_for_actor,
    _is_dispatched,
    is_perceptible,
    perceived_entity_label,
)
from everquill_engine.resolver.deltas import (
    _claim,
)
from everquill_engine.rumor import reached_deeds
from everquill_engine.world import RumorSeed, WorldContent

# --- outcome delta rules per action type ---------------------------------------


def _band_word(band: PlausibilityTier) -> str:
    return band.name


# --- research resolution against a source's knowledge_scope (research) ------

#: Success outcome tier → the appraisal depth it reaches, before the source's
#: own ``max_appraisal_tier`` cap. STRONG_HIT reads deep (ranged estimate +
#: provenance / weak point); a complicated hit reads a category/band.
_RESEARCH_DEPTH_FOR_OUTCOME: dict[OutcomeTier, int] = {
    OutcomeTier.STRONG_HIT: 2,
    OutcomeTier.HIT_WITH_COMPLICATION: 1,
}

_RUMOR_PICK_SCHEME = b"everquill.rumor_seed.v1"
_RUMOR_WEIGHT_SCALE = 1000
_RUMOR_ROOT_SCHEME = b"everquill.rumor_seed_root.v1"


def authored_rumor_root(text: str) -> int:
    """The provenance root every retelling of one authored rumor seed shares.

    An authored seed has no founding event in the log, and rooting it at each
    hearing's own outcome event made the same rumor heard twice count as two
    independent sources (corroborated). A pure function of the seed's text
    gives every hearing one root. Negative, so it can never equal a real
    event id (bigserial, positive).
    """
    digest = hashlib.sha256(_RUMOR_ROOT_SCHEME + b"\x00" + text.encode("utf-8")).digest()
    return -(int.from_bytes(digest[:7], "big") + 1)


_SOURCE_ROOT_SCHEME = b"everquill.source_agent_root.v1"


def source_agent_root(agent_id: str) -> int:
    """The provenance root of everything one authored source tells you.

    A source's answer has no founding event in the log either, and rooting it
    at each hearing's outcome event let one NPC asked twice corroborate itself
    (audit 2026-10-24, codex-001). One root per source agent means a source can
    never confirm its own word, while two different sources telling the same
    thing still corroborate. Negative, like :func:`authored_rumor_root`, and in
    its own hash domain so the two can never collide in practice.
    """
    digest = hashlib.sha256(_SOURCE_ROOT_SCHEME + b"\x00" + agent_id.encode("utf-8")).digest()
    return -(int.from_bytes(digest[:7], "big") + 1)


@dataclass(frozen=True, slots=True)
class _RumorCandidate:
    text: str
    notoriety: float
    hop_count: int = 0
    provenance_root_event_id: int | None = None


def _rumor_seed_weight(seed: RumorSeed) -> int:
    if seed.notoriety <= 0:
        return 0
    return max(1, int(seed.notoriety * _RUMOR_WEIGHT_SCALE))


def _rumor_candidate_weight(candidate: _RumorCandidate) -> int:
    if candidate.notoriety <= 0:
        return 0
    return max(1, int(candidate.notoriety * _RUMOR_WEIGHT_SCALE))


def _rumor_pick_hash(actor_id: str, world_time: int, turn: int) -> int:
    preimage = b"|".join(
        (
            _RUMOR_PICK_SCHEME,
            actor_id.encode("utf-8"),
            str(world_time).encode("ascii"),
            str(turn).encode("ascii"),
        )
    )
    return int.from_bytes(hashlib.sha256(preimage).digest()[:8], "big")


def _pick_rumor_seed(
    seeds: tuple[RumorSeed, ...], *, actor_id: str, world_time: int, turn: int
) -> RumorSeed | None:
    """Weighted deterministic pick for authored ambient rumor seeds.

    This is not a dice roll and does not advance RNG counters. It follows the
    engine's existing SHA-256 seed discipline: stable canon inputs in, one
    replay-safe integer out. Notoriety is only the weight for Slice 1.
    """
    if not seeds:
        return None
    weights = [_rumor_seed_weight(seed) for seed in seeds]
    if sum(weights) <= 0:
        weights = [1 for _seed in seeds]
    ticket = _rumor_pick_hash(actor_id, world_time, turn) % sum(weights)
    seen = 0
    for seed, weight in zip(seeds, weights, strict=True):
        seen += weight
        if ticket < seen:
            return seed
    return seeds[-1]


def _pick_ambient_rumor(
    candidates: tuple[_RumorCandidate, ...],
    *,
    actor_id: str,
    world_time: int,
    turn: int,
) -> _RumorCandidate | None:
    """Weighted deterministic pick for the merged seed+deed rumor pool."""
    if not candidates:
        return None
    weights = [_rumor_candidate_weight(candidate) for candidate in candidates]
    if sum(weights) <= 0:
        weights = [1 for _candidate in candidates]
    ticket = _rumor_pick_hash(actor_id, world_time, turn) % sum(weights)
    seen = 0
    for candidate, weight in zip(candidates, weights, strict=True):
        seen += weight
        if ticket < seen:
            return candidate
    return candidates[-1]


def _ambient_rumor_candidates(
    *,
    rumor_seeds: tuple[RumorSeed, ...],
    deeds: tuple[dict[str, Any], ...],
    world: WorldContent | None,
    location_id: str | None,
    time_after: int,
) -> tuple[_RumorCandidate, ...]:
    candidates = [
        _RumorCandidate(
            text=seed.deed,
            notoriety=seed.notoriety,
            provenance_root_event_id=authored_rumor_root(seed.deed),
        )
        for seed in rumor_seeds
    ]
    if world is not None and location_id is not None and deeds:
        for deed in reached_deeds(
            deeds, world=world, location_id=location_id, world_time=time_after
        ):
            candidates.append(
                _RumorCandidate(
                    text=deed["description"],
                    notoriety=float(deed["notoriety"]),
                    hop_count=int(deed["hop_count"]),
                    provenance_root_event_id=int(deed["source_event_id"]),
                )
            )
    return tuple(candidates)


def _known_fact(entity, index: int, *, actor: dict[str, Any] | None = None) -> str:
    """Deterministic pick from an entity's common knowledge."""
    if entity is None or not entity.common_knowledge:
        return "There is less to learn here than the asking cost."
    fact = entity.common_knowledge[index % len(entity.common_knowledge)]
    if actor is None:
        return fact
    return _fog_known_fact_for_actor(fact, actor, entity)


def _governing_source(
    world: WorldContent,
    actor: dict[str, Any],
    subject: str | None,
    entity_states: dict[str, dict[str, Any]] | None = None,
):
    """The co-located, perceptible knowledge source that governs research on
    ``subject`` (roadmap §3.6). Deterministic (sources sorted by id): a source
    whose scope COVERS the subject wins ('in_scope'); else a source that can
    give a LEAD ('lead'); else None (ambient research — the safe default when
    content authors have written no scope). Returns (mode, source, scope_subject)."""
    if not subject:
        return (None, None, None)
    actor_flags = actor.get("flags") or {}
    sources = [
        s
        for s in world.sources_at(actor["location_id"])
        if s.id != subject
        and is_perceptible(world, s.id, actor_flags)
        and not _is_dispatched(s.id, entity_states)  # the dead tell nothing
    ]
    for src in sources:
        scope_subject = src.knowledge_scope.subject(subject)
        if scope_subject is not None:
            return ("in_scope", src, scope_subject)
    for src in sources:
        if src.knowledge_scope.lead is not None:
            return ("lead", src, None)
    return (None, None, None)


def _research_in_scope(
    *, subject, subject_entity, subject_name, actor, actor_id, source,
    scope_subject, outcome_tier, time_after, entity_states,
) -> list[dict[str, Any]]:
    """A source that HOLDS this subject: success reveals a FIELD up to the
    achieved appraisal tier (never a number); a bad roll writes the source's
    confidently-WRONG answer at HIGH strength (told-weight) — the ballads lie
    (roadmap §3.3), authored-flavored and deterministic."""
    name = perceived_entity_label(actor, source)
    if outcome_tier is OutcomeTier.MISS:
        error = scope_subject.error
        if error is not None:
            return [_claim(
                subject, error.claim_text,
                predicate=error.predicate, value_text=error.value_text,
                source=name, observer=actor_id, source_agent=source.id,
                method="source_records", world_time=time_after,
                scope=error.distortion, confidence="consistent",
            )]
        # No authored error: the records mislead by one band, too kindly —
        # deterministic (same source, same subject, same wrong answer).
        if subject_entity is not None:
            true_read = band_for_gap(
                _effective_threat(subject_entity, entity_states)
                - actor["aptitudes"]["might"]
            )
            softer = PlausibilityTier(
                max(true_read.value - 1, PlausibilityTier.TRIVIAL.value)
            )
            return [_claim(
                subject, f"{name}'s records make {subject_name} sound manageable.",
                predicate="threat_assessed", value_text=_band_word(softer),
                source=name, observer=actor_id, source_agent=source.id,
                method="source_records", world_time=time_after,
                scope="insufficient_appraisal_tier", confidence="consistent",
            )]
        return [_claim(
            subject or "world", f"{name} is confident, and confidently wrong.",
            predicate="common_knowledge", value_text=f"{name} misremembers this",
            source=name, observer=actor_id, source_agent=source.id,
            method="source_records", world_time=time_after,
            scope="local_mistaken_for_universal", confidence="consistent",
        )]

    # outcome_tier None = a TRIVIAL research success (no roll — the subject is
    # so far beneath the researcher's depth the surface is simply grasped):
    # reveal the tier-0 field, accurately. Deep tiers still require the roll.
    achieved = min(
        _RESEARCH_DEPTH_FOR_OUTCOME.get(outcome_tier, 0),
        source.knowledge_scope.max_appraisal_tier,
    )
    confidence = (
        "consistent" if outcome_tier in (OutcomeTier.STRONG_HIT, None) else "uncorroborated"
    )
    reveal = scope_subject.reveal_at(achieved)
    if reveal is not None:
        return [_claim(
            subject, reveal.claim_text,
            predicate=reveal.predicate, value_text=reveal.value_text,
            source=name, observer=actor_id, source_agent=source.id,
            method="source_records", world_time=time_after,
            scope=f"appraisal_tier_{reveal.tier}", confidence=confidence,
        )]
    # No authored reveal at this depth: the engine reveals the threat FIELD as
    # a band WORD (tier >= 1) or a surface descriptor (tier 0). Never a number.
    if achieved >= 1 and subject_entity is not None:
        true_read = band_for_gap(
            _effective_threat(subject_entity, entity_states)
            - actor["aptitudes"]["might"]
        )
        return [_claim(
            subject, f"You take {subject_name}'s measure in {name}'s records.",
            predicate="threat_assessed", value_text=_band_word(true_read),
            source=name, observer=actor_id, source_agent=source.id,
            method="source_records", world_time=time_after,
            scope=f"appraisal_tier_{achieved}", confidence=confidence,
        )]
    fact = _known_fact(subject_entity, 0, actor=actor)
    return [_claim(
        subject or "world", fact,
        predicate="common_knowledge", value_text=fact,
        source=name, observer=actor_id, source_agent=source.id,
        method="source_records", world_time=time_after,
        scope="appraisal_tier_0", confidence=confidence,
    )]


def _research_lead(actor: dict[str, Any] | str, source, time_after: int) -> list[dict[str, Any]]:
    """A source that does NOT hold this subject: 'nothing here — but a lead'
    (roadmap §3.6). One pointer claim ABOUT the better source/location, scoped
    ``lead`` so the LLM layer and client can render it as a research-target chip."""
    if isinstance(actor, dict):
        actor_id = actor["entity_id"]
        source_label = perceived_entity_label(actor, source)
    else:
        actor_id = actor
        source_label = source.name
    lead = source.knowledge_scope.lead
    return [_claim(
        lead.to, lead.claim_text,
        predicate="common_knowledge", value_text=lead.claim_text,
        source=source_label, observer=actor_id, source_agent=source.id,
        method="source_records", world_time=time_after,
        scope="lead", confidence="uncorroborated",
    )]


def _ambient_seed_rumor(
    *,
    actor_id: str,
    time_after: int,
    rumor_seeds: tuple[RumorSeed, ...],
    turn: int,
    outcome_tier: OutcomeTier | None,
    deeds: tuple[dict[str, Any], ...] = (),
    world: WorldContent | None = None,
    location_id: str | None = None,
) -> list[dict[str, Any]]:
    candidate = _pick_ambient_rumor(
        _ambient_rumor_candidates(
            rumor_seeds=rumor_seeds,
            deeds=deeds,
            world=world,
            location_id=location_id,
            time_after=time_after,
        ),
        actor_id=actor_id,
        world_time=time_after,
        turn=turn,
    )
    if candidate is None:
        return []
    confidence = (
        "consistent"
        if outcome_tier in (OutcomeTier.MISS, OutcomeTier.STRONG_HIT)
        else "uncorroborated"
    )
    delta = _claim(
        "world", candidate.text,
        predicate="common_knowledge", value_text=candidate.text,
        source="taproom consensus", observer=actor_id,
        method="rumor", world_time=time_after,
        scope="local_mistaken_for_universal", confidence=confidence,
    )
    if candidate.provenance_root_event_id is not None:
        delta["provenance_root_event_id"] = candidate.provenance_root_event_id
        delta["hop_count"] = candidate.hop_count
        delta["derived_from_claim_id"] = None
    return [delta]


def _research_ambient(
    subject,
    subject_entity,
    actor,
    outcome_tier,
    time_after,
    *,
    rumor_seeds: tuple[RumorSeed, ...],
    turn: int,
    deeds: tuple[dict[str, Any], ...] = (),
    world: WorldContent | None = None,
    location_id: str | None = None,
) -> list[dict[str, Any]]:
    """Safe default when no authored source governs: local rumor / patient
    questions — LOW-strength (rumor). Seeded worlds and reached deeds surface
    one subjectless rumor here; empty pools keep the Sprint-2 filler."""
    if isinstance(actor, dict):
        actor_id = actor["entity_id"]
        fact_actor = actor
    else:
        actor_id = actor
        fact_actor = None
    if subject is None and subject_entity is None:
        deltas = _ambient_seed_rumor(
            actor_id=actor_id,
            time_after=time_after,
            rumor_seeds=rumor_seeds,
            turn=turn,
            outcome_tier=outcome_tier,
            deeds=deeds,
            world=world,
            location_id=location_id,
        )
        if deltas:
            return deltas

    if outcome_tier is OutcomeTier.MISS:
        fact = (
            f"The stories agree: {_known_fact(subject_entity, 0, actor=fact_actor)}"
            if subject_entity
            else "The stories agree on more than they should."
        )
        return [_claim(
            subject or "world", fact,
            predicate="common_knowledge", value_text=fact,
            source="taproom consensus", observer=actor_id,
            method="rumor", world_time=time_after,
            scope="local_mistaken_for_universal", confidence="consistent",
        )]
    confidence = "consistent" if outcome_tier is OutcomeTier.STRONG_HIT else "uncorroborated"
    fact = (
        _known_fact(subject_entity, 0, actor=fact_actor)
        if subject_entity
        else "You piece together the shape of local talk."
    )
    return [_claim(
        subject or "world", fact,
        predicate="common_knowledge", value_text=fact,
        source="patient questions", observer=actor_id,
        method="archive_research", world_time=time_after,
        scope="local", confidence=confidence,
    )]


def _research_deltas(
    *, subject, subject_entity, subject_name, actor, actor_id, world,
    outcome_tier, time_after, turn, entity_states, deeds,
) -> list[dict[str, Any]]:
    """Route a research outcome through the governing source's scope (or the
    ambient default). ONE claim delta out."""
    mode, source, scope_subject = _governing_source(world, actor, subject, entity_states)
    if mode == "in_scope":
        return _research_in_scope(
            subject=subject, subject_entity=subject_entity, subject_name=subject_name,
            actor=actor, actor_id=actor_id, source=source, scope_subject=scope_subject,
            outcome_tier=outcome_tier, time_after=time_after, entity_states=entity_states,
        )
    if mode == "lead":
        return _research_lead(actor, source, time_after)
    return _research_ambient(
        subject, subject_entity, actor, outcome_tier, time_after,
        rumor_seeds=world.rumor_seeds, turn=turn, deeds=deeds, world=world,
        location_id=actor["location_id"],
    )
