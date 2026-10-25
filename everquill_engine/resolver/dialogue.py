"""Dialogue shapes: information-seeking, name exchange, and matching a
question to the subject a present source can answer."""

from __future__ import annotations

from typing import Any

from everquill_engine.ladder import (
    OutcomeTier,
    PlausibilityTier,
)
from everquill_engine.resolver.common import (
    _is_present_npc,
    contract_id,
    knows_name_flag,
    perceived_entity_label,
)
from everquill_engine.resolver.deltas import (
    _claim,
    _flag,
)

# --- outcome delta rules per action type ---------------------------------------
from everquill_engine.resolver.research import (
    _known_fact,
    _research_in_scope,
    _research_lead,
)
from everquill_engine.world import WorldContent


def _is_information_seek(intent: dict[str, Any]) -> bool:
    """A question (closed ``speech_act``) on a dialogue or social turn."""
    if intent.get("action_type") not in {"dialogue", "social"}:
        return False
    return intent.get("speech_act") == "question"


def _is_name_exchange(intent: dict[str, Any]) -> bool:
    """A deliberate introduction or ask-for-name (closed ``speech_act``)."""
    if intent.get("action_type") not in {"dialogue", "social"}:
        return False
    return intent.get("speech_act") == "introduction"


def _named_scope_subject(topic_ids: list[str], source) -> str | None:
    """The first topic the parser named that this source's scope covers.

    Topics come from the closed ``topic_ids`` field, picked from the Topics
    list or roster in the parse call; the engine only checks them against the
    source's authored scope, in the parser's order (deterministic).
    """
    if source.knowledge_scope is None:
        return None
    for topic in topic_ids:
        for scoped in source.knowledge_scope.subjects:
            if contract_id(scoped.subject) == topic:
                return scoped.subject
    return None


def _addressed_information_source(
    *,
    action: str,
    targets: list[str],
    actor: dict[str, Any],
    world: WorldContent,
    manifest: dict[str, dict[str, Any]],
    entity_states: dict[str, dict[str, Any]] | None = None,
):
    if action not in {"dialogue", "social"}:
        return None
    actor_flags = actor.get("flags") or {}
    npc_targets = [
        target
        for target in targets
        if _is_present_npc(
            target,
            actor_location=actor.get("location_id"),
            actor_flags=actor_flags,
            world=world,
            manifest=manifest,
            entity_states=entity_states,
        )
    ]
    if not npc_targets:
        return None
    return world.entities[npc_targets[0]]


def _authored_information_deltas(
    *,
    intent: dict[str, Any],
    actor: dict[str, Any],
    world: WorldContent,
    targets: list[str],
    time_after: int,
    entity_states: dict[str, dict[str, Any]] | None,
    manifest: dict[str, dict[str, Any]],
    common_index: int = 0,
) -> list[dict[str, Any]]:
    """One authored Inquiry fact for an information-seeking NPC ask.

    Named subjects route through the existing knowledge-scope reveal/error
    helpers. For this minimal dialogue path, a source's authored error is what
    that source tells you casually; otherwise the tier-0 reveal/common fact is
    used. Subjectless asks fall back to one fact from the addressed NPC's own
    ``common_knowledge``.
    """
    if not _is_information_seek(intent):
        return []
    source = _addressed_information_source(
        action=intent["action_type"],
        targets=targets,
        actor=actor,
        world=world,
        manifest=manifest,
        entity_states=entity_states,
    )
    if source is None:
        return []

    subject = _named_scope_subject(list(intent.get("topic_ids") or []), source)
    if subject is not None and source.knowledge_scope is not None:
        scope_subject = source.knowledge_scope.subject(subject)
        subject_entity = world.entities.get(subject)
        subject_name = (
            perceived_entity_label(actor, subject_entity, subject)
            if subject_entity is not None
            else subject
        )
        if scope_subject is not None:
            outcome = (
                OutcomeTier.MISS
                if scope_subject.error is not None
                else None
            )
            return _research_in_scope(
                subject=subject,
                subject_entity=subject_entity,
                subject_name=subject_name,
                actor=actor,
                actor_id=actor["entity_id"],
                source=source,
                scope_subject=scope_subject,
                outcome_tier=outcome,
                time_after=time_after,
                entity_states=entity_states,
            )
        if source.knowledge_scope.lead is not None:
            return _research_lead(actor, source, time_after)

    fact = _known_fact(source, common_index, actor=actor)
    return [
        _claim(
            source.id,
            fact,
            predicate="common_knowledge",
            value_text=fact,
            source=perceived_entity_label(actor, source),
            observer=actor["entity_id"],
            source_agent=source.id,
            method="conversation",
            world_time=time_after,
            scope="local",
            confidence="consistent",
        )
    ]


def _name_exchange_delta(
    *,
    intent: dict[str, Any],
    actor: dict[str, Any],
    world: WorldContent,
    targets: list[str],
    manifest: dict[str, dict[str, Any]],
    tier: PlausibilityTier,
    outcome_tier: OutcomeTier | None,
    entity_states: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Learn an NPC name only from a deliberate, successful name exchange."""
    action = intent.get("action_type")
    if action not in {"dialogue", "social"} or not _is_name_exchange(intent):
        return None
    actor_flags = actor.get("flags") or {}
    npc_targets = [
        target
        for target in targets
        if _is_present_npc(
            target,
            actor_location=actor.get("location_id"),
            actor_flags=actor_flags,
            world=world,
            manifest=manifest,
            entity_states=entity_states,
        )
    ]
    if len(npc_targets) != 1:
        return None
    target = npc_targets[0]
    flag_key = knows_name_flag(target)
    if actor_flags.get(flag_key):
        return None
    target_entity = world.entities[target]
    guarded = "guarded" in target_entity.true_sheet.tags
    if guarded:
        if outcome_tier is not OutcomeTier.STRONG_HIT:
            return None
    elif not (
        outcome_tier in (OutcomeTier.HIT_WITH_COMPLICATION, OutcomeTier.STRONG_HIT)
        or (outcome_tier is None and tier is PlausibilityTier.TRIVIAL)
    ):
        return None
    return _flag(actor["entity_id"], flag_key, True)
