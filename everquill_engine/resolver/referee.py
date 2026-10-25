"""The referee: resolve one intent against projected state, roll, and
build the events to append."""

from __future__ import annotations

from typing import Any

from everquill_engine.claims import BASE_EVIDENCE_WEIGHT
from everquill_engine.clock import (
    TRAINING_BLOCK_MINUTES,
    real_due_at,
    world_date,
)
from everquill_engine.dice import roll_2d6
from everquill_engine.events import EventSpec, EventType, event_ref
from everquill_engine.folds import stream_counter_key
from everquill_engine.ladder import (
    OutcomeTier,
    PlausibilityTier,
    RiskLabel,
    outcome_for_roll,
)
from everquill_engine.resolver.common import (
    _BAND_MODIFIER,
    WEAK_POINT_ROLL_BONUS,
    Resolution,
    _intent_from_typed,
    _is_dispatched,
    _renown_delta_for_deeds,
    contract_id,
    perceived_entity_label,
)
from everquill_engine.resolver.deltas import (
    _claim,
    _coin_delta,
    _conversation_partner_delta,
    _flag,
    _hp,
    _transaction_coin_delta,
)
from everquill_engine.resolver.dialogue import (
    _authored_information_deltas,
    _name_exchange_delta,
)
from everquill_engine.resolver.outcomes import (
    _deltas_for_outcome,
    _ensure_deposit,
)
from everquill_engine.resolver.research import (
    _ambient_seed_rumor,
    _research_deltas,
    source_agent_root,
)
from everquill_engine.resolver.tier import (
    TierDecision,
    decide_tier,
)
from everquill_engine.rng_registry import action_outcome_stream, hopeless_flavor_stream
from everquill_engine.world import APTITUDES, Law, WorldContent

# --- the referee ---------------------------------------------------------------


def _impossible_outcome(
    *,
    actor: dict[str, Any],
    actor_id: str,
    constraints: list[str],
    deltas: list[dict[str, Any]],
    law: Law | None,
    location_id: str,
    outcome_obj: Any,
    summary: list[str],
    tier: PlausibilityTier,
    time_after: int,
    witnesses: list[str],
) -> Any:
    """IMPOSSIBLE: no roll; the attempt is a deed and the law says why."""
    if tier is PlausibilityTier.IMPOSSIBLE:
        # Never rolls; fiction reacts to the attempt — still a deed. The
        # description names the LAW, never the player's own words: raw
        # player text stays out of derived canon (encrypted player text — the utterance
        # lives, encrypted, in intent_parsed).
        constraints.append("impossible_tier_irony_licensed")
        deltas.append(
            {
                "delta_type": "deed",
                "actor_entity_id": actor_id,
                "description": f"{actor['name']} attempted the impossible: {law.name}",
                "location_id": location_id,
                "witness_ids": witnesses,
                "notoriety": 2,
                "world_date": world_date(time_after),
            }
        )
        summary.append(f"<<Assessment: IMPOSSIBLE, {law.name}.>>")
        summary.append("No roll. The world reacts to the attempt itself.")
    elif tier is PlausibilityTier.SEALED:
        # Components unmet (decide_tier verified them — met components
        # arrive here already upgraded to DESPERATE with a law note).
        # Fail forward: no dice, miss, deed logged, something noticed.
        outcome_obj = None
        missing = [c for c in law.components if not actor["flags"].get(c)]
        deltas.append(
            {
                "delta_type": "deed",
                "actor_entity_id": actor_id,
                "description": (
                    f"{actor['name']} attempted {law.name} with the components unmet"
                ),
                "location_id": location_id,
                "witness_ids": witnesses,
                "notoriety": 3,
                "world_date": world_date(time_after),
            }
        )
        deltas.append(_flag(actor_id, f"attempted_{law.law_id.replace('.', '_')}", True))
        deltas.append(
            _claim(
                actor_id,
                f"{law.name} demands more than you brought: {', '.join(missing)}.",
                predicate="personal_lesson",
                source="the attempt itself",
                observer=actor_id,
                method="hard_lesson",
                world_time=time_after,
                scope="firsthand",
                confidence="consistent",
            )
        )
        constraints.append("no_success_framing")
        summary.append(f"<<Assessment: SEALED, {law.name}. Components unmet.>>")
        summary.append("It fails forward. The attempt is a deed; something noticed.")
    return outcome_obj


def _rolled_or_free_outcome(
    *,
    action: str,
    actor: dict[str, Any],
    actor_id: str,
    constraints: list[str],
    decision: TierDecision,
    deltas: list[dict[str, Any]],
    dice_record: dict[str, Any] | None,
    entity_states: dict[str, dict[str, Any]] | None,
    intent: dict[str, Any],
    location_id: str,
    manifest: dict[str, dict[str, Any]],
    move_to: str | None,
    outcome_obj: Any,
    projected_deeds: tuple[dict[str, Any], ...],
    reputation: dict[str, dict[str, Any]] | None,
    resolved_intent: dict[str, Any],
    risk_label: RiskLabel | None,
    rng_counters: dict[str, int],
    rng_field: dict[str, Any] | None,
    seed: int,
    stat_name: str | None,
    summary: list[str],
    targets: list[str],
    tier: PlausibilityTier,
    time_after: int,
    time_cost: int,
    transaction_delta: dict[str, Any] | None,
    turn: int,
    witnesses: list[str],
    world: WorldContent,
) -> tuple[dict[str, Any] | None, Any, dict[str, Any] | None, dict[str, Any] | None]:
    """Every other tier: roll where the ladder calls for it, else narrate-only."""
    if tier in (
        PlausibilityTier.ROUTINE,
        PlausibilityTier.RISKY,
        PlausibilityTier.DESPERATE,
        PlausibilityTier.HOPELESS,
    ):
        # Every roll site draws from its own registered stream —
        # per-action-type outcome streams; HOPELESS flavor is its own site
        # (the draw picks HOW you fail, never an outcome tier).
        if tier is PlausibilityTier.HOPELESS:
            stream = list(hopeless_flavor_stream(actor_id))
        else:
            stream = list(action_outcome_stream(actor_id, action))
        index = rng_counters.get(stream_counter_key(stream), 0)
        roll = roll_2d6(seed, tuple(stream), index)
        modifiers = [{"label": stat_name, "value": _BAND_MODIFIER[tier]}]
        # Target-specific intel modifier — a held weak_point on
        # this physical target adds a KNOWN-safe bonus (you strike soft).
        if action == "physical" and decision.weak_point_target is not None:
            modifiers.append({"label": "weak_point", "value": WEAK_POINT_ROLL_BONUS})
        total = roll.total + sum(m["value"] for m in modifiers)
        effective = min(12, max(2, total))
        outcome_obj = outcome_for_roll(tier, effective)
        dice_record = {
            "rolls": [roll.die_one, roll.die_two],
            "modifiers": modifiers,
            "total": total,
        }
        rng_field = {"stream": stream, "index": index, "rolls": [roll.die_one, roll.die_two]}
        summary.append(
            f"<<Assessment: {tier.name}, {risk_label.name.capitalize()}.>>"
        )
        summary.append(
            f"[2d6] {roll.die_one} + {roll.die_two} = {roll.total}  |  "
            + "  ".join(f"{m['label']} {m['value']:+d}" for m in modifiers)
            + f"  ->  {total}"
        )
        if outcome_obj.hopeless_flavor:
            summary.append(
                f"MISS ({outcome_obj.hopeless_flavor.value}): the roll picked how you fail."
            )
        else:
            summary.append(f"Outcome: {outcome_obj.tier.value.upper()}")
        if outcome_obj.tier is OutcomeTier.MISS:
            constraints.append("no_success_framing")
        deltas.extend(
            _deltas_for_outcome(
                intent=resolved_intent,
                actor=actor,
                world=world,
                targets=targets,
                band=tier,
                outcome=outcome_obj,
                turn=turn,
                time_after=time_after,
                witnesses=witnesses,
                entity_states=entity_states,
                reputation=reputation,
                deeds=projected_deeds,
                manifest=manifest,
            )
        )
        if outcome_obj.tier is OutcomeTier.MISS:
            _ensure_deposit(
                deltas, actor=actor, intent=intent, turn=turn, time_after=time_after
            )
    elif tier is PlausibilityTier.TRIVIAL:
        summary.append("<<Assessment: TRIVIAL.>> No roll; narrated only.")
        if decision.system_note:
            summary.append(decision.system_note)
        if decision.already_dispatched:
            # Physical action aimed only at targets already at 0 hp:
            # nothing happens, nothing rolls, ZERO deltas — but the
            # Chronicle says so explicitly (ticket, decision 5
            # cluster). The outcome event still commits (the attempt is
            # auditable), it just changes nothing.
            summary.append("[Already dispatched.]")
        elif action == "physical" and targets:
            # TRIVIAL means guaranteed success, never a no-op: a target the
            # actor trivially outclasses is dispatched without ceremony —
            # no dice, full consequence (found by George stomping the slime
            # and watching nothing happen).
            for target_id in targets:
                state = (entity_states or {}).get(target_id)
                if state is None or state.get("hp") is None:
                    continue
                remaining = int(state["hp"])
                if remaining <= 0:
                    continue
                deltas.append(_hp(target_id, -remaining, "dispatched without ceremony"))
                target_entity = world.entities.get(target_id)
                # As the actor knows them: a deed is public text, and the authored
                # name may be one the actor never learned (audit codex-008).
                target_name = perceived_entity_label(actor, target_entity, target_id)
                deltas.append(
                    {
                        "delta_type": "deed",
                        "actor_entity_id": actor_id,
                        "description": f"{actor['name']} dispatched {target_name} without ceremony",
                        "location_id": location_id,
                        "witness_ids": witnesses,
                        "notoriety": 1,
                        "world_date": world_date(time_after),
                    }
                )
            if any(d["delta_type"] == "hp" for d in deltas):
                summary.append("Beneath your notice. It is done.")
        elif action == "research" or (action == "observation" and targets):
            # TRIVIAL research/appraisal still DEPOSITS a finding: a subject far
            # beneath the researcher's depth is grasped at the surface without a
            # roll (found by George — a high-lore PC trivialised all research and
            # the Codex stayed empty). Same principle as the physical case above:
            # trivial success is success, never a no-op. Deep tiers still need a
            # roll. Untargeted observation ("look around") has its own ambient
            # seed-rumor hook below.
            r_subject = targets[0] if targets else None
            r_entity = world.entities.get(r_subject) if r_subject else None
            r_name = perceived_entity_label(actor, r_entity, r_subject or "the room")
            deltas.extend(
                _research_deltas(
                    subject=r_subject,
                    subject_entity=r_entity,
                    subject_name=r_name,
                    actor=actor,
                    actor_id=actor_id,
                    world=world,
                    outcome_tier=None,
                    time_after=time_after,
                    turn=turn,
                    entity_states=entity_states,
                    deeds=projected_deeds,
                )
            )
            if any(d["delta_type"] == "intel" for d in deltas):
                summary.append("You take its measure at a glance.")
        elif action == "observation":
            deltas.extend(
                _ambient_seed_rumor(
                    actor_id=actor_id,
                    time_after=time_after,
                    rumor_seeds=world.rumor_seeds,
                    turn=turn,
                    outcome_tier=None,
                    deeds=projected_deeds,
                    world=world,
                    location_id=location_id,
                )
            )
        elif action == "dialogue":
            deltas.extend(
                _authored_information_deltas(
                    intent=resolved_intent,
                    actor=actor,
                    world=world,
                    targets=targets,
                    time_after=time_after,
                    entity_states=entity_states,
                    manifest=manifest,
                    common_index=0,
                )
            )
        name_delta = _name_exchange_delta(
            intent=resolved_intent,
            actor=actor,
            world=world,
            targets=targets,
            manifest=manifest,
            tier=tier,
            outcome_tier=None,
            entity_states=entity_states,
        )
        if name_delta is not None:
            deltas.append(name_delta)
        if action == "rest":
            # Duration-aware rest: the bound span IS the rest.
            # A full night (>= 480 min) buys the inn room and the full
            # recovery; shorter rests are free and recover 1 hp per two
            # hours (deterministic, documented in docs/engine/stats.md).
            transaction_delta = _transaction_coin_delta(
                intent=resolved_intent,
                actor=actor,
                world=world,
            )
            span = time_cost
            missing = actor["hp_max"] - actor["hp"]
            if span >= 480 and transaction_delta is None:
                price = world.prices.get("inn_night_copper", 5)
                default_inn_delta = _coin_delta(actor, price, "a night at the inn")
                if default_inn_delta is not None:
                    deltas.append(default_inn_delta)
                recovery = min(4, missing)
            else:
                recovery = min(span // 120, missing, 4)
            if recovery > 0:
                cause = "a night's rest" if span >= 480 else "a short rest"
                deltas.append(_hp(actor_id, recovery, cause))
        elif action == "train":
            timer_key = f"timer_{contract_id(actor_id)}_{turn}"
            block = decision.block_minutes or TRAINING_BLOCK_MINUTES
            deltas.append(
                {
                    "delta_type": "timer_started",
                    "timer_id": timer_key,
                    "kind": "training",
                    "due_world_time": str(time_after + block),
                }
            )
        elif action == "movement" and move_to is not None:
            deltas.append(
                {
                    "delta_type": "position",
                    "entity_id": actor_id,
                    "from_location_id": location_id,
                    "to_location_id": move_to,
                    # The LLM layer's finding: position deltas say HOW. Declared
                    # travel is walked; other movers (throws, routs,
                    # carries) set their own hint when those rules land.
                    "transit_hint": "walked",
                }
            )
    return dice_record, outcome_obj, rng_field, transaction_delta


def _fan_out_events(
    *,
    actor_id: str,
    claim_seq: int,
    deltas: list[dict[str, Any]],
    events: list[EventSpec],
    location_id: str,
    outcome_event_index: int,
    stat_name: str | None,
    time_after: int,
    turn: int,
    world: WorldContent,
) -> None:
    """Fan-out events (claims, deeds, timers) for the same command; folds read only these."""
    for delta in deltas:
        if delta["delta_type"] == "intel":
            claim_seq += 1
            claim_body = delta["claim"]
            # Explicit roots (rumors, deeds) win; a source's answer roots at the
            # source; anything else (first-hand) at this turn's outcome event.
            provenance_root_event_id = delta.get("provenance_root_event_id")
            if provenance_root_event_id is None:
                agent = claim_body.get("source_agent_id")
                provenance_root_event_id = (
                    source_agent_root(agent) if agent else event_ref(outcome_event_index)
                )
            events.append(
                EventSpec(
                    stream_id=f"character:{actor_id}",
                    event_type=EventType.CLAIM_WRITTEN,
                    world_time=time_after,
                    location_id=location_id,
                    payload_version=2,
                    payload={
                        "claim_id": f"claim_{actor_id}_{turn}_{claim_seq}",
                        "believer_id": actor_id,
                        "claim": claim_body,
                        "provenance_root_event_id": provenance_root_event_id,
                        "derived_from_claim_id": delta.get("derived_from_claim_id"),
                        "hop_count": int(delta.get("hop_count", 0)),
                        "journal_flag": False,
                        # Cached decayed evidence-weight sum; a fresh claim's
                        # single founding link at its undecayed base weight.
                        "strength": BASE_EVIDENCE_WEIGHT[claim_body["acquisition_method"]],
                    },
                )
            )
        elif delta["delta_type"] == "deed":
            region = None
            location = world.locations.get(location_id)
            region = location.region if location else "unknown"
            events.append(
                EventSpec(
                    stream_id=f"region:{region}",
                    event_type=EventType.DEED_RECORDED,
                    world_time=time_after,
                    location_id=location_id,
                    payload={
                        "deed": {k: v for k, v in delta.items() if k != "delta_type"},
                        "caused_by": event_ref(outcome_event_index),
                    },
                )
            )
        elif delta["delta_type"] == "timer_started":
            events.append(
                EventSpec(
                    stream_id=f"character:{actor_id}",
                    event_type=EventType.TIMER_STARTED,
                    world_time=time_after,
                    location_id=location_id,
                    payload={
                        "timer_key": delta["timer_id"],
                        "kind": delta["kind"],
                        "subject_id": actor_id,
                        "world_due": int(delta["due_world_time"]),
                        # The real deadline is a FACT recorded at
                        # creation from the documented world-epoch mapping
                        # (clock.WORLD_EPOCH_UTC); folds apply it verbatim.
                        "due_at": real_due_at(int(delta["due_world_time"])),
                        "payload": {
                            "aptitude": stat_name if stat_name in APTITUDES else "will",
                            "owner_id": actor_id,
                        },
                        "created_event_id": event_ref(outcome_event_index),
                    },
                )
            )


def resolve_intent(
    *,
    intent: dict[str, Any],
    actor: dict[str, Any],
    world: WorldContent,
    manifest: dict[str, dict[str, Any]],
    world_time: int,
    rng_counters: dict[str, int],
    seed: int,
    turn: int,
    entity_states: dict[str, dict[str, Any]] | None = None,
    actor_claim_subjects: frozenset[str] | None = None,
    actor_target_intel: dict[str, frozenset[str]] | None = None,
    reputation: dict[str, dict[str, Any]] | None = None,
    deeds: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> Resolution:
    """Resolve one canned intent against projected state. Pure.

    ``actor`` is the character_sheet projection row; ``manifest`` the
    scene_manifest rows keyed by entity id; ``entity_states`` the
    entity_state projection rows keyed by entity id (current NPC/
    creature hp — hp-persistence: difficulty reads authored truth PLUS
    current wounds; pass it whenever it exists); ``rng_counters`` the
    world_state counters ({json stream key: next index}); ``turn`` the
    1-based turn ordinal (= the command sequence for this actor, used
    for deterministic claim/timer/flag keys).
    """
    decision = decide_tier(
        intent=intent,
        actor=actor,
        world=world,
        manifest=manifest,
        world_time=world_time,
        entity_states=entity_states,
        actor_claim_subjects=actor_claim_subjects,
        actor_target_intel=actor_target_intel,
        reputation=reputation,
    )
    resolved_intent = _intent_from_typed(decision.intent)
    action = decision.action
    actor_id = actor["entity_id"]
    location_id = actor["location_id"]
    projected_deeds = tuple(deeds or ())
    targets = list(decision.targets)
    law = decision.law
    stat_name = decision.stat_name
    tier = decision.tier
    time_cost = decision.time_cost
    move_to = decision.move_to

    witnesses = sorted(
        entity_id
        for entity_id, row in manifest.items()
        if row.get("location_id") == location_id
        and entity_id != actor_id
        and row.get("kind") in ("npc", "character")
        and not _is_dispatched(entity_id, entity_states)  # the dead see nothing
    )

    summary: list[str] = []
    events: list[EventSpec] = []
    stat_hint = decision.intent.stat_hint
    stat_meta = {
        "stat_selected": stat_name,
        "stat_hint": stat_hint,
        "stat_hint_mismatch": bool(stat_hint) and stat_hint != stat_name,
    }

    time_after = world_time + time_cost
    risk_label = decision.risk_label
    intent_spec = EventSpec(
        stream_id=f"character:{actor_id}",
        event_type=EventType.INTENT_PARSED,
        world_time=world_time,
        location_id=location_id,
        # v2: approach/quoted_speech may be envelope-encrypted at append
        # (encrypted player text; the store owns the transform — this payload is plaintext).
        payload_version=2,
        payload={"character_id": actor_id, "intent": resolved_intent, "source": "canned"},
    )
    events.append(intent_spec)

    outcome_obj = None
    dice_record: dict[str, Any] | None = None
    rng_field: dict[str, Any] | None = None
    deltas: list[dict[str, Any]] = []
    transaction_delta: dict[str, Any] | None = None
    constraints = ["entity_facts_only", "no_chronicle_contradiction", "no_npc_awe_unearned"]
    law_notes: list[str] = list(decision.law_notes)

    outcome_obj = _impossible_outcome(
        actor=actor,
        actor_id=actor_id,
        constraints=constraints,
        deltas=deltas,
        law=law,
        location_id=location_id,
        outcome_obj=outcome_obj,
        summary=summary,
        tier=tier,
        time_after=time_after,
        witnesses=witnesses,
    )

    (
        dice_record,
        outcome_obj,
        rng_field,
        transaction_delta,
    ) = _rolled_or_free_outcome(
        action=action,
        actor=actor,
        actor_id=actor_id,
        constraints=constraints,
        decision=decision,
        deltas=deltas,
        dice_record=dice_record,
        entity_states=entity_states,
        intent=intent,
        location_id=location_id,
        manifest=manifest,
        move_to=move_to,
        outcome_obj=outcome_obj,
        projected_deeds=projected_deeds,
        reputation=reputation,
        resolved_intent=resolved_intent,
        risk_label=risk_label,
        rng_counters=rng_counters,
        rng_field=rng_field,
        seed=seed,
        stat_name=stat_name,
        summary=summary,
        targets=targets,
        tier=tier,
        time_after=time_after,
        time_cost=time_cost,
        transaction_delta=transaction_delta,
        turn=turn,
        witnesses=witnesses,
        world=world,
    )

    if action in {"social", "rest"}:
        coin_delta = transaction_delta or _transaction_coin_delta(
            intent=resolved_intent,
            actor=actor,
            world=world,
        )
        if coin_delta is not None:
            deltas.append(coin_delta)

    partner_delta = _conversation_partner_delta(
        actor=actor,
        action=action,
        targets=targets,
        move_to=move_to,
        world=world,
        manifest=manifest,
        entity_states=entity_states,
    )
    if partner_delta is not None:
        deltas.append(partner_delta)

    renown_delta = _renown_delta_for_deeds(
        deltas, reputation=reputation, actor_id=actor_id
    )
    if renown_delta is not None:
        deltas.append(renown_delta)

    if witnesses and any(d["delta_type"] == "deed" for d in deltas):
        constraints.append("no_invented_witnesses")

    outcome_event_index = len(events)
    outcome_spec = EventSpec(
        stream_id=f"character:{actor_id}",
        event_type=EventType.OUTCOME_RESOLVED,
        world_time=time_after,
        location_id=location_id,
        rng=rng_field,
        meta=stat_meta,  # Advisory stat_hint telemetry: hint vs engine selection
        # v2: intel deltas carry typed v2 claims; position deltas carry
        # transit_hint (upcasters map stored v1 rows forward).
        payload_version=2,
        payload={
            "character_id": actor_id,
            "intent_event": event_ref(0),
            "tier_resolved": tier.name.lower(),
            "risk_label_shown": risk_label.name.lower() if dice_record else None,
            "outcome_tier": outcome_obj.tier.value if outcome_obj else (
                "miss" if tier is PlausibilityTier.SEALED else None
            ),
            "hopeless_flavor": (
                outcome_obj.hopeless_flavor.value
                if outcome_obj and outcome_obj.hopeless_flavor
                else None
            ),
            "dice": dice_record,
            "state_deltas": deltas,
            "narration_constraints": constraints,
            "system_note": decision.system_note,
            "movement_blocked": decision.movement_blocked,
            "law_id": law.law_id if law else None,
            "law_notes": law_notes,
            "world_time_cost": time_cost,
        },
    )
    events.append(outcome_spec)

    # Fan-out events (claims / deeds / timers) — same command, same
    # transaction; folds read ONLY these for their tables.
    claim_seq = 0
    _fan_out_events(
        actor_id=actor_id,
        claim_seq=claim_seq,
        deltas=deltas,
        events=events,
        location_id=location_id,
        outcome_event_index=outcome_event_index,
        stat_name=stat_name,
        time_after=time_after,
        turn=turn,
        world=world,
    )

    for delta in deltas:
        summary.append("  Δ " + _describe_delta(delta, world))
    summary.append(f"[Time: {world_date(world_time)} -> {world_date(time_after)}]")

    return Resolution(
        events=tuple(events),
        outcome_event_index=outcome_event_index,
        tier=tier,
        risk_label=risk_label if dice_record else None,
        outcome_tier=outcome_obj.tier if outcome_obj else None,
        hopeless_flavor=(
            outcome_obj.hopeless_flavor.value
            if outcome_obj and outcome_obj.hopeless_flavor
            else None
        ),
        dice=dice_record,
        world_time_after=time_after,
        summary=tuple(summary),
    )


def _describe_delta(delta: dict[str, Any], world: WorldContent) -> str:
    kind = delta["delta_type"]
    if kind == "hp":
        return f"hp {delta['entity_id']} {delta['amount']:+d} ({delta['cause']})"
    if kind == "coin":
        return f"coin {delta['entity_id']} {delta['amount']:+d} ({delta['reason']})"
    if kind == "inventory":
        return (
            f"inventory {delta['entity_id']} {delta['op']} "
            f"{delta['item_id']} x{delta['quantity']}"
        )
    if kind == "flag":
        return f"flag {delta['entity_id']} {delta['flag_key']} = {delta['value']}"
    if kind == "position":
        return f"position {delta['entity_id']} -> {delta['to_location_id']}"
    if kind == "intel":
        claim = delta["claim"]
        return f"claim: \"{claim['claim_text']}\" ({claim['method']}, {claim['confidence']})"
    if kind == "deed":
        return f"deed: {delta['description']} (notoriety {delta['notoriety']})"
    if kind == "timer_started":
        return (
            f"timer {delta['timer_id']} ({delta['kind']}) "
            f"due at world minute {delta['due_world_time']}"
        )
    if kind == "title":
        return f"title {delta['entity_id']}: {delta['title']}"
    return str(delta)
