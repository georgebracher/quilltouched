"""Outcome deltas per action type, plus the deposit rule that every miss
leaves something behind."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from everquill_engine.clock import (
    world_date,
)
from everquill_engine.ladder import (
    OutcomeTier,
    PlausibilityTier,
    band_for_gap,
)
from everquill_engine.resolver.common import (
    _DISPOSITION_BAND,
    _STANDING_BAND,
    DEFAULT_STAT_FOR_ACTION,
    _effective_threat,
    _reputation_delta,
    _settlement_of,
    contract_id,
    perceived_entity_label,
)
from everquill_engine.resolver.deltas import (
    _claim,
    _clamped_self_harm,
    _desperate_counterattack_harm,
    _flag,
    _hp,
)
from everquill_engine.resolver.dialogue import (
    _authored_information_deltas,
    _name_exchange_delta,
)

# --- outcome delta rules per action type ---------------------------------------
from everquill_engine.resolver.research import (
    _band_word,
    _known_fact,
    _research_deltas,
)
from everquill_engine.world import WorldContent


@dataclass(frozen=True)
class _OutcomeContext:
    """Everything one outcome's delta rules read, plus the shared ``deltas``
    list they append to and the helpers that close over it."""

    intent: Any
    actor: Any
    world: Any
    targets: Any
    band: Any
    outcome: Any
    turn: Any
    time_after: Any
    witnesses: Any
    entity_states: Any
    reputation: Any
    deeds: Any
    manifest: Any
    action: Any
    actor_id: Any
    deltas: Any
    primary: Any
    primary_entity: Any
    primary_name: Any
    primary_label: Any
    tier: Any
    flavor: Any
    append_self_harm: Any
    threat_gap_for_primary: Any
    append_desperate_counterattack: Any
    should_record_physical_deed: Any
    deed: Any


def _outcome_context(
    *,
    intent: dict[str, Any],
    actor: dict[str, Any],
    world: WorldContent,
    targets: list[str],
    band: PlausibilityTier,
    outcome,
    turn: int,
    time_after: int,
    witnesses: list[str],
    entity_states: dict[str, dict[str, Any]] | None = None,
    reputation: dict[str, dict[str, Any]] | None = None,
    deeds: tuple[dict[str, Any], ...] = (),
    manifest: dict[str, dict[str, Any]] | None = None,
) -> _OutcomeContext:
    action = intent["action_type"]
    actor_id = actor["entity_id"]
    deltas: list[dict[str, Any]] = []
    primary = targets[0] if targets else None
    primary_entity = world.entities.get(primary) if primary else None
    primary_label = perceived_entity_label(actor, primary_entity, primary or "the room")
    # Deeds and harm causes are public text: name the target as the actor knows
    # them, so a fight never reveals a name the actor has not learned.
    primary_name = primary_label
    tier = outcome.tier if outcome else None
    flavor = outcome.hopeless_flavor.value if outcome and outcome.hopeless_flavor else None

    def append_self_harm(amount: int, cause: str) -> None:
        pending_hp = actor["hp"] + sum(
            d["amount"]
            for d in deltas
            if d.get("delta_type") == "hp" and d.get("entity_id") == actor_id
        )
        harm = _clamped_self_harm({**actor, "hp": pending_hp}, amount)
        if harm:
            deltas.append(_hp(actor_id, harm, cause))

    def threat_gap_for_primary() -> int | None:
        if primary_entity is None:
            return None
        stat = DEFAULT_STAT_FOR_ACTION["physical"]
        return _effective_threat(primary_entity, entity_states) - actor["aptitudes"][stat]

    def append_desperate_counterattack() -> None:
        if band is not PlausibilityTier.DESPERATE or primary_entity is None:
            return
        gap = threat_gap_for_primary()
        if gap is None:
            return
        append_self_harm(
            _desperate_counterattack_harm(gap),
            f"mauled by {primary_name}",
        )

    def should_record_physical_deed() -> bool:
        return bool(witnesses) or band in (
            PlausibilityTier.DESPERATE,
            PlausibilityTier.HOPELESS,
        )

    def deed(description: str, notoriety: int) -> dict[str, Any]:
        return {
            "delta_type": "deed",
            "actor_entity_id": actor_id,
            "description": description,
            "location_id": actor["location_id"],
            "witness_ids": witnesses,
            "notoriety": notoriety,
            "world_date": world_date(time_after),
        }

    return _OutcomeContext(
        intent=intent,
        actor=actor,
        world=world,
        targets=targets,
        band=band,
        outcome=outcome,
        turn=turn,
        time_after=time_after,
        witnesses=witnesses,
        entity_states=entity_states,
        reputation=reputation,
        deeds=deeds,
        manifest=manifest,
        action=action,
        actor_id=actor_id,
        deltas=deltas,
        primary=primary,
        primary_entity=primary_entity,
        primary_name=primary_name,
        primary_label=primary_label,
        tier=tier,
        flavor=flavor,
        append_self_harm=append_self_harm,
        threat_gap_for_primary=threat_gap_for_primary,
        append_desperate_counterattack=append_desperate_counterattack,
        should_record_physical_deed=should_record_physical_deed,
        deed=deed,
    )


def _hopeless_deltas(c: _OutcomeContext) -> list[dict[str, Any]]:
    """HOPELESS: failure flavor only, never a roll's worth of outcome."""
    actor = c.actor
    band = c.band
    turn = c.turn
    time_after = c.time_after
    action = c.action
    actor_id = c.actor_id
    deltas = c.deltas
    primary = c.primary
    primary_name = c.primary_name
    primary_label = c.primary_label
    flavor = c.flavor
    append_self_harm = c.append_self_harm
    should_record_physical_deed = c.should_record_physical_deed
    deed = c.deed
    # Failure flavor only — the deposit rules of roadmap §3.1.
    # Physical harm belongs to physical confrontation; a hopeless
    # read/charm/inquiry costs face and truth, never hit points.
    if action == "physical":
        if flavor == "catastrophic":
            append_self_harm(6, f"broken against {primary_name}")
            deltas.append(_flag(actor_id, f"scar_turn_{turn}", f"marked by {primary_name}"))
        elif flavor == "punishing":
            append_self_harm(3, f"mauled by {primary_name}")
        else:  # spared
            deltas.append(_flag(actor_id, f"scar_turn_{turn}", f"spared by {primary_name}"))
            deltas.append(
                _flag(actor_id, f"journal_hook_turn_{turn}", f"spared by {primary_name}")
            )
        if should_record_physical_deed():
            deltas.append(
                deed(f"{actor['name']} challenged {primary_name} and was broken", 4)
            )
    else:
        if flavor == "catastrophic":
            deltas.append(
                _flag(actor_id, f"humbled_turn_{turn}", f"outclassed by {primary_name}")
            )
        elif flavor == "spared":
            deltas.append(
                _flag(actor_id, f"journal_hook_turn_{turn}", f"spared by {primary_name}")
            )
    if primary:
        deltas.append(
            _claim(
                primary,
                f"{primary_label} is far beyond you.",
                predicate="threat_assessed",
                value_text=_band_word(band),
                source="your own survival",
                observer=actor_id,
                method="survived_attempt",
                world_time=time_after,
                scope="firsthand",
                confidence="consistent",
            )
        )
    return deltas


def _physical_deltas(c: _OutcomeContext) -> None:
    """Physical confrontation: harm both ways, deeds when witnessed or desperate."""
    actor = c.actor
    time_after = c.time_after
    actor_id = c.actor_id
    deltas = c.deltas
    primary = c.primary
    primary_name = c.primary_name
    primary_label = c.primary_label
    tier = c.tier
    append_self_harm = c.append_self_harm
    append_desperate_counterattack = c.append_desperate_counterattack
    should_record_physical_deed = c.should_record_physical_deed
    deed = c.deed
    if tier is OutcomeTier.STRONG_HIT:
        if primary:
            deltas.append(_hp(primary, -3, f"struck by {actor['name']}"))
        append_desperate_counterattack()
        if should_record_physical_deed():
            deltas.append(deed(f"{actor['name']} bested {primary_name}", 3))
    elif tier is OutcomeTier.HIT_WITH_COMPLICATION:
        if primary:
            deltas.append(_hp(primary, -2, f"struck by {actor['name']}"))
        append_self_harm(1, f"caught by {primary_name}")
        append_desperate_counterattack()
        if should_record_physical_deed():
            deltas.append(deed(f"{actor['name']} traded blows with {primary_name}", 2))
    else:  # miss
        append_self_harm(2, f"outmatched by {primary_name}")
        append_desperate_counterattack()
        if primary:
            deltas.append(
                _claim(
                    primary,
                    f"{primary_label} reads you before you move.",
                    predicate="personal_lesson",
                    source="a hard lesson",
                    observer=actor_id,
                    method="hard_lesson",
                    world_time=time_after,
                    scope="firsthand",
                    confidence="uncorroborated",
                )
            )


def _social_deltas(c: _OutcomeContext) -> None:
    """Social actions: standing, reputation and what the other party now thinks."""
    intent = c.intent
    actor = c.actor
    world = c.world
    targets = c.targets
    time_after = c.time_after
    witnesses = c.witnesses
    entity_states = c.entity_states
    reputation = c.reputation
    manifest = c.manifest
    actor_id = c.actor_id
    deltas = c.deltas
    primary = c.primary
    primary_entity = c.primary_entity
    primary_label = c.primary_label
    tier = c.tier
    if tier is OutcomeTier.STRONG_HIT and primary:
        disp_delta = _reputation_delta(
            reputation, actor_id, "disposition", primary, 2, _DISPOSITION_BAND
        )
        if disp_delta:
            deltas.append(disp_delta)
        if witnesses:  # a win others saw lifts your regard in the town
            stand_delta = _reputation_delta(
                reputation, actor_id, "standing",
                _settlement_of(actor["location_id"]), 1, _STANDING_BAND,
            )
            if stand_delta:
                deltas.append(stand_delta)
        info = _authored_information_deltas(
            intent=intent,
            actor=actor,
            world=world,
            targets=targets,
            time_after=time_after,
            entity_states=entity_states,
            manifest=manifest or {},
            common_index=0,
        )
        if info:
            deltas.extend(info)
        else:
            fact = _known_fact(primary_entity, 0, actor=actor)
            deltas.append(
                _claim(
                    primary,
                    fact,
                    predicate="common_knowledge",
                    value_text=fact,
                    source=primary_label,
                    observer=actor_id,
                    source_agent=primary,
                    method="conversation",
                    world_time=time_after,
                    scope="local",
                    confidence="consistent",
                )
            )
    elif tier is OutcomeTier.HIT_WITH_COMPLICATION and primary:
        disp_delta = _reputation_delta(
            reputation, actor_id, "disposition", primary, 1, _DISPOSITION_BAND
        )
        if disp_delta:
            deltas.append(disp_delta)
        info = _authored_information_deltas(
            intent=intent,
            actor=actor,
            world=world,
            targets=targets,
            time_after=time_after,
            entity_states=entity_states,
            manifest=manifest or {},
            common_index=1,
        )
        if info:
            deltas.extend(info)
        else:
            fact = _known_fact(primary_entity, 1, actor=actor)
            deltas.append(
                _claim(
                    primary,
                    fact,
                    predicate="common_knowledge",
                    value_text=fact,
                    source=primary_label,
                    observer=actor_id,
                    source_agent=primary,
                    method="conversation",
                    world_time=time_after,
                    scope="local",
                    confidence="uncorroborated",
                )
            )
    elif tier is OutcomeTier.MISS and primary:
        disp_delta = _reputation_delta(
            reputation, actor_id, "disposition", primary, -1, _DISPOSITION_BAND
        )
        if disp_delta:
            deltas.append(disp_delta)
        deltas.append(
            _claim(
                primary,
                f"{primary_label} wants nothing to do with you today.",
                predicate="disposition_toward",
                value_text="rebuffed",
                source="the exchange itself",
                observer=actor_id,
                source_agent=primary,
                method="conversation",
                world_time=time_after,
                scope="firsthand",
                confidence="uncorroborated",
            )
        )
        deltas.extend(
            _authored_information_deltas(
                intent=intent,
                actor=actor,
                world=world,
                targets=targets,
                time_after=time_after,
                entity_states=entity_states,
                manifest=manifest or {},
                common_index=0,
            )
        )


def _observation_deltas(c: _OutcomeContext) -> None:
    """Observation: what the actor notices, at the depth the outcome reached."""
    actor = c.actor
    band = c.band
    time_after = c.time_after
    entity_states = c.entity_states
    actor_id = c.actor_id
    deltas = c.deltas
    primary = c.primary
    primary_entity = c.primary_entity
    primary_label = c.primary_label
    tier = c.tier
    if primary:
        # The appraisal reports the target's THREAT read: the band a
        # physical confrontation would resolve at for this actor now
        # (the re-tier toast surface, roadmap §3.3). Never a number.
        # Reads CURRENT threat (wounds included) — same source the
        # referee would fight from.
        if primary_entity is not None:
            true_read = band_for_gap(
                _effective_threat(primary_entity, entity_states)
                - actor["aptitudes"]["might"]
            )
        else:
            true_read = band
        if tier is OutcomeTier.MISS:
            # Wrong intel is CAUSAL, never random: a failed glance
            # reads one band too kindly, every time.
            softer = PlausibilityTier(
                max(true_read.value - 1, PlausibilityTier.TRIVIAL.value)
            )
            deltas.append(
                _claim(
                    primary,
                    f"At a glance, {primary_label} seems manageable.",
                    predicate="threat_assessed",
                    value_text=_band_word(softer),
                    source="your own eyes",
                    observer=actor_id,
                    method="misjudged_glance",
                    world_time=time_after,
                    scope="firsthand",
                    confidence="uncorroborated",
                )
            )
        else:
            deltas.append(
                _claim(
                    primary,
                    f"You take {primary_label}'s measure.",
                    predicate="threat_assessed",
                    value_text=_band_word(true_read),
                    source="your own eyes",
                    observer=actor_id,
                    method="witnessed",
                    world_time=time_after,
                    scope="firsthand",
                    confidence="consistent",
                )
            )
            if tier is OutcomeTier.HIT_WITH_COMPLICATION:
                deltas.append(_flag(actor_id, f"noticed_by_{contract_id(primary)}", True))


def _research_outcome_deltas(c: _OutcomeContext) -> None:
    """Research against a present source's knowledge scope."""
    actor = c.actor
    world = c.world
    turn = c.turn
    time_after = c.time_after
    entity_states = c.entity_states
    deeds = c.deeds
    actor_id = c.actor_id
    deltas = c.deltas
    primary = c.primary
    primary_entity = c.primary_entity
    primary_label = c.primary_label
    tier = c.tier
    # Resolve against THIS source's scope (roadmap §3.3/§3.6): an in-scope
    # source reveals appraisal FIELDS on success and its confidently-wrong
    # answer on a bad roll; an out-of-scope source gives a LEAD; with no
    # authored source it falls back to ambient rumor. `tier` here is the
    # OUTCOME tier (MISS/HIT/STRONG_HIT).
    deltas.extend(
        _research_deltas(
            subject=primary,
            subject_entity=primary_entity,
            subject_name=primary_label,
            actor=actor,
            actor_id=actor_id,
            world=world,
            outcome_tier=tier,
            time_after=time_after,
            turn=turn,
            entity_states=entity_states,
            deeds=deeds,
        )
    )


def _craft_deltas(c: _OutcomeContext) -> None:
    """Crafting: the made thing, or what the attempt cost."""
    turn = c.turn
    time_after = c.time_after
    actor_id = c.actor_id
    deltas = c.deltas
    tier = c.tier
    if tier is OutcomeTier.STRONG_HIT:
        deltas.append(
            {
                "delta_type": "inventory",
                "entity_id": actor_id,
                "item_id": f"crafted_trinket_{turn}",
                "op": "add",
                "quantity": 1,
            }
        )
    elif tier is OutcomeTier.HIT_WITH_COMPLICATION:
        deltas.append(
            {
                "delta_type": "inventory",
                "entity_id": actor_id,
                "item_id": f"crafted_trinket_{turn}",
                "op": "add",
                "quantity": 1,
            }
        )
        deltas.append(
            {
                "delta_type": "coin",
                "entity_id": actor_id,
                "amount": -2,
                "reason": "spoiled materials",
            }
        )
    else:
        deltas.append(_flag(actor_id, f"botched_craft_turn_{turn}", True))
        deltas.append(
            _claim(
                actor_id,
                "Your hands know less than your eyes claimed.",
                predicate="personal_lesson",
                source="the ruined piece",
                observer=actor_id,
                method="hard_lesson",
                world_time=time_after,
                scope="firsthand",
                confidence="uncorroborated",
            )
        )


_ACTION_DELTAS = {
    "physical": _physical_deltas,
    "social": _social_deltas,
    "observation": _observation_deltas,
    "research": _research_outcome_deltas,
    "craft": _craft_deltas,
}


def _deltas_for_outcome(
    *,
    intent: dict[str, Any],
    actor: dict[str, Any],
    world: WorldContent,
    targets: list[str],
    band: PlausibilityTier,
    outcome,
    turn: int,
    time_after: int,
    witnesses: list[str],
    entity_states: dict[str, dict[str, Any]] | None = None,
    reputation: dict[str, dict[str, Any]] | None = None,
    deeds: tuple[dict[str, Any], ...] = (),
    manifest: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    c = _outcome_context(
        intent=intent,
        actor=actor,
        world=world,
        targets=targets,
        band=band,
        outcome=outcome,
        turn=turn,
        time_after=time_after,
        witnesses=witnesses,
        entity_states=entity_states,
        reputation=reputation,
        deeds=deeds,
        manifest=manifest,
    )
    if band is PlausibilityTier.HOPELESS:
        return _hopeless_deltas(c)
    rule = _ACTION_DELTAS.get(c.action)
    if rule is not None:
        rule(c)
    deltas = c.deltas
    tier = c.tier
    name_delta = _name_exchange_delta(
        intent=intent,
        actor=actor,
        world=world,
        targets=targets,
        manifest=manifest or {},
        tier=band,
        outcome_tier=tier,
        entity_states=c.entity_states,
    )
    if name_delta is not None:
        deltas.append(name_delta)
    return deltas


def _ensure_deposit(
    deltas: list[dict[str, Any]],
    *,
    actor: dict[str, Any],
    intent: dict[str, Any],
    turn: int,
    time_after: int,
) -> None:
    """Every miss deposits at least one delta (roadmap §2). Structural backstop.

    The lesson text deliberately does NOT quote the player's approach:
    raw player text lives (encrypted) in intent_parsed only — derived
    canon never embeds it, so crypto-shredding never has to
    chase claim rows.
    """
    if deltas:
        return
    deltas.append(
        _claim(
            actor["entity_id"],
            "Nothing came of it but the lesson.",
            predicate="personal_lesson",
            source="your own journal hand",
            observer=actor["entity_id"],
            method="hard_lesson",
            world_time=time_after,
            scope="firsthand",
            confidence="uncorroborated",
        )
    )
