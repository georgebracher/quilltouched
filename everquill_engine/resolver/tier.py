"""Tier decision, shared by resolve and the commit-beat assess path. Pure,
no dice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from everquill_engine.clock import (
    TRAINING_BLOCK_MINUTES,
    DurationBindingError,
    action_time_cost,
    bind_duration,
)
from everquill_engine.intent import (
    ParsedIntent,
)
from everquill_engine.ladder import (
    PlausibilityTier,
    RiskLabel,
    band_for_gap,
)
from everquill_engine.resolver.common import (
    _RISK_FOR_BAND,
    CONFIRMATION_REQUIRED_FOR_RISK,
    DEFAULT_STAT_FOR_ACTION,
    ResolverError,
    _difficulty_for,
    _is_dispatched,
    _matching_law,
    _roster,
    _settlement_of,
    _typed_intent,
    _with_conversation_partner,
    contract_id,
    is_perceptible,
)
from everquill_engine.world import Law, WorldContent

# --- tier decision (shared by resolve and the commit-beat assess path) ---------


@dataclass(frozen=True, slots=True)
class TierDecision:
    """Everything the tier decision produces, WITHOUT resolving.

    Pure and dice-free — this is the assess half of the two-phase commit
    beat (interface decision 2). :func:`resolve_intent` builds
    on exactly this object, so assess and resolve can never disagree
    about tier, risk, or pricing.
    """

    intent: ParsedIntent
    action: str
    targets: tuple[str, ...]           # dotted world ids
    law: Law | None
    law_notes: tuple[str, ...]
    stat_name: str
    tier: PlausibilityTier
    risk_label: RiskLabel | None       # pre-roll label; None for no-roll shapes
    time_cost: int                     # world-minutes the action itself costs
    block_minutes: int | None          # train only: committed block length
    move_to: str | None
    already_dispatched: bool           # physical aimed only at dispatched targets
    system_note: str | None = None      # System-facing note for trivial no-op turns
    movement_blocked: bool = False      # true only when declared travel cannot use an exit
    #: Knowledge-gated action space: the dotted target id for which
    #: the actor holds a `weak_point` claim (physical only). Non-None means a
    #: known vulnerability altered the action — a HOPELESS confrontation
    #: became a DESPERATE option (band already reflects it) and the resolver
    #: applies the intel roll modifier. None = no target-specific intel.
    weak_point_target: str | None = None


#: The SINGLE rejection returned for ANY target the actor cannot
#: act on from its current scene — an unknown id and a real-but-off-scene
#: (or undiscovered, or unowned) id are refused with the SAME string, so the
#: contract boundary is not an existence oracle. It names no id and reveals
#: no existence (tests assert byte-equality across the two cases).
UNADDRESSABLE_TARGET = "that is not something you can act on from where you stand"


def _target_addressable(
    action: str,
    dotted: str,
    *,
    actor_location: str,
    actor_flags: dict[str, Any],
    actor_inventory: dict[str, Any],
    world: WorldContent,
    manifest: dict[str, dict[str, Any]],
    claim_subjects: frozenset[str],
    research_catalog: frozenset[str],
) -> bool:
    """Can the actor address ``dotted`` for ``action`` right now?

    Engine-owned capability check, run BEFORE tiering. Membership in the
    authored world is NOT authorization: a physical/social/observation/
    dialogue target must be a co-located, PERCEPTIBLE scene entity; an
    inventory target must be owned; research additionally reaches the
    subjects of the actor's existing claims AND the subjects catalogued by a
    co-located source's knowledge_scope (a present archive/sage
    opens its catalogue to your research action space, roadmap §3.6).
    Everything else is refused."""
    owned = contract_id(dotted) in actor_inventory
    if action == "rest" and dotted in world.locations:
        return dotted == actor_location
    row = manifest.get(dotted)
    co_located = (
        row is not None
        and row.get("location_id") == actor_location
        and is_perceptible(world, dotted, actor_flags)
    )
    if action == "research":
        return co_located or owned or dotted in claim_subjects or dotted in research_catalog
    return co_located or owned


def _research_catalog(
    world: WorldContent,
    location_id: str,
    actor_flags: dict[str, Any],
    entity_states: dict[str, dict[str, Any]] | None = None,
) -> frozenset[str]:
    """Dotted subject ids catalogued by co-located PERCEPTIBLE, living sources:
    the research reach a present archive/sage opens (roadmap §3.6)."""
    catalog: set[str] = set()
    for src in world.sources_at(location_id):
        if is_perceptible(world, src.id, actor_flags) and not _is_dispatched(
            src.id, entity_states
        ):
            for subject in src.knowledge_scope.subjects:
                catalog.add(subject.subject)
    return frozenset(catalog)


def decide_tier(
    *,
    intent: dict[str, Any],
    actor: dict[str, Any],
    world: WorldContent,
    manifest: dict[str, dict[str, Any]],
    world_time: int,
    entity_states: dict[str, dict[str, Any]] | None = None,
    actor_claim_subjects: frozenset[str] | None = None,
    actor_target_intel: dict[str, frozenset[str]] | None = None,
    reputation: dict[str, dict[str, Any]] | None = None,
) -> TierDecision:
    """Validate + tier one intent against projected state. Pure, NO dice.

    Order of authority: typed-intent validation → target
    ADDRESSABILITY (co-located + perceptible scene entity,
    owned inventory item, direct travel connection, or — for research —
    a subject of the actor's existing claims OR a subject catalogued by a
    co-located source; unknown and unauthorized targets refused
    IDENTICALLY) → authored law override (sealed components verified here —
    deterministic flag reads) → no-roll action shapes → dispatched-target
    rule → gap arithmetic → KNOWLEDGE GATE (a known weak point
    turns a HOPELESS physical fight into a DESPERATE option). Duration hints
    are bound here too (clock.bind_duration) so the commit beat can preview
    real pricing. ``actor_claim_subjects`` is the set of dotted subject ids
    the actor holds live claims about; ``actor_target_intel`` maps a dotted
    subject id to the set of claim predicates the actor holds about it
    (``weak_point``/``threat_assessed`` — the target-specific intel the
    resolver consults). Both come from the fold image (None = empty)."""
    typed = _typed_intent(intent)
    action = typed.action_type
    location_id = actor["location_id"]
    actor_flags = actor.get("flags") or {}
    actor_inventory = actor.get("inventory") or {}
    claim_subjects = actor_claim_subjects or frozenset()
    target_intel = actor_target_intel or {}
    research_catalog = (
        _research_catalog(world, location_id, actor_flags, entity_states)
        if action == "research"
        else frozenset()
    )

    typed = _with_conversation_partner(
        typed, actor=actor, world=world, manifest=manifest, entity_states=entity_states
    )

    roster = _roster(world, manifest)
    movement_note: str | None = None
    movement_blocked = False
    targets: list[str] = []
    for raw in typed.target_entity_ids:
        dotted = roster.get(raw)
        if action == "observation" and dotted == location_id:
            # Observing the room/place you are already in is an ambient scene
            # read, not a contested target. Other locations still fail below.
            continue
        # Movement targets are locations, addressed by the travel-network
        # check below; every other shape must pass the engine-owned
        # capability check. Unknown ids (roster miss) and unauthorized ids
        # are refused with the SAME string — no existence oracle.
        addressable = dotted is not None and (
            action == "movement"
            or _target_addressable(
                action,
                dotted,
                actor_location=location_id,
                actor_flags=actor_flags,
                actor_inventory=actor_inventory,
                world=world,
                manifest=manifest,
                claim_subjects=claim_subjects,
                research_catalog=research_catalog,
            )
        )
        if not addressable:
            if action == "movement":
                continue
            raise ResolverError(UNADDRESSABLE_TARGET)
        targets.append(dotted)

    time_cost = action_time_cost(action)

    # Movement re-prices from the travel network.
    move_to: str | None = None
    if action == "movement":
        here = world.locations.get(location_id)
        if here is None:
            raise ResolverError(f"actor location {location_id!r} is not in this world file")
        exit_names = [
            world.locations[c.to].name
            for c in here.connections
            if c.to in world.locations
        ]
        exit_line = (
            "You stay where you are. From here you can go to: "
            f"{', '.join(exit_names)}."
            if exit_names
            else "You stay where you are. There is no way out of here that you can see."
        )
        if not targets or targets[0] not in world.locations:
            move_to = None
            if typed.movement_scope == "here":
                movement_note = "You cross the room."
            else:
                movement_note = exit_line
                movement_blocked = True
        else:
            move_to = targets[0]
            if move_to == location_id:
                move_to = None  # already here → trivial narrate-only
            else:
                connection = next((c for c in here.connections if c.to == move_to), None)
                if connection is None:
                    move_to = None
                    movement_note = exit_line
                    movement_blocked = True
                else:
                    time_cost = max(connection.carriage_days * 1440, time_cost)

    # Duration binding: consumed deterministically or rejected.
    # Consumption table (docs/engine/stats.md "Duration binding"):
    #   train → the committed block length (block starts after the commit
    #           cost, so until-conditions bind from world_time + cost);
    #   rest  → the rest span itself (replaces the flat 480);
    #   else  → an occupied-time floor: the action takes at least the
    #           declared span (never less than its base/travel price).
    block_minutes: int | None = None
    try:
        if action == "train":
            if typed.duration_hint is not None:
                block_minutes = bind_duration(typed.duration_hint, world_time + time_cost)
            else:
                block_minutes = TRAINING_BLOCK_MINUTES
        elif typed.duration_hint is not None:
            bound = bind_duration(typed.duration_hint, world_time)
            time_cost = bound if action == "rest" else max(time_cost, bound)
    except DurationBindingError as exc:
        raise ResolverError(str(exc)) from exc

    # --- tier decision ---------------------------------------------------------
    law = _matching_law(world, typed, targets)
    # The engine-owned table is the SOLE aptitude selector.
    # The parser's stat_hint is retained in the stored intent payload
    # (audit) and surfaced as mismatch telemetry in the outcome event's
    # meta — it never touches resolution.
    stat_name = DEFAULT_STAT_FOR_ACTION.get(action, "wits")
    no_roll_shapes = {"meta", "dialogue", "rest", "train", "movement"}

    law_notes: list[str] = []
    already_dispatched = False
    living = [t for t in targets if not _is_dispatched(t, entity_states)]

    if law is not None and law.tier == "impossible":
        tier = PlausibilityTier.IMPOSSIBLE
    elif law is not None and law.tier == "sealed":
        verified = all(bool(actor["flags"].get(component)) for component in law.components)
        if verified:
            # Components met: resolves as the band the components unlock
            # (v1: DESPERATE — a sealed feat is never routine).
            tier = PlausibilityTier.DESPERATE
            law_notes.append(f"components of {law.law_id} verified")
        else:
            tier = PlausibilityTier.SEALED
    elif action in no_roll_shapes or (action == "observation" and not targets):
        tier = PlausibilityTier.TRIVIAL
    elif action == "physical" and targets and not living:
        # Every target is already at 0 hp: nothing to fight. Trivial,
        # zero deltas — the resolver narrates "[Already dispatched.]".
        tier = PlausibilityTier.TRIVIAL
        already_dispatched = True
    elif action == "social" and targets and not living:
        # Pressing, charming or bargaining with the dead: nothing to move.
        # Trivial, no roll against a body; the presence checks give it no
        # partner, source or name exchange either.
        tier = PlausibilityTier.TRIVIAL
        movement_note = movement_note or "No answer. They are past hearing."
    else:
        # Dispatched targets contribute nothing to physical difficulty;
        # other shapes read true sheets as before.
        difficulty_targets = living if action == "physical" else targets
        target_entities = [
            world.entities[t] for t in difficulty_targets if t in world.entities
        ]
        difficulty = _difficulty_for(
            action, target_entities, entity_states,
            reputation=reputation, actor_id=actor["entity_id"],
            settlement_id=_settlement_of(actor["location_id"]),
        )
        gap = difficulty - actor["aptitudes"][stat_name]
        tier = band_for_gap(gap)
        # A trivial physical action dispatches its target without a roll. Only a
        # creature may die that way: harming a person always takes dice
        # (George, 25 Oct 2026, after "buy an ale" misread as physical killed
        # the barkeep).
        if (
            action == "physical"
            and tier is PlausibilityTier.TRIVIAL
            and any(
                t in world.entities and world.entities[t].kind == "npc" for t in living
            )
        ):
            tier = PlausibilityTier.ROUTINE
            law_notes.append("a person is never harmed without a roll")

    # Knowledge gate: a KNOWN weak point on the primary living
    # physical target is target-specific intel the resolver consults. It
    # converts a HOPELESS confrontation into a DESPERATE option (the intel,
    # not the stats, changes the action space — roadmap §3.3) and rides on
    # the decision so the roll picks up the intel modifier. A bare
    # threat_assessed read is surfaced via target_intel but never downgrades
    # the band by itself (knowing a foe is deadly does not make it softer).
    weak_point_target: str | None = None
    if action == "physical" and living:
        primary_living = living[0]
        if "weak_point" in target_intel.get(primary_living, frozenset()):
            weak_point_target = primary_living
            if tier is PlausibilityTier.HOPELESS:
                tier = PlausibilityTier.DESPERATE
                law_notes.append(
                    f"weak_point known: {primary_living} — HOPELESS unlocked to DESPERATE"
                )

    return TierDecision(
        intent=typed,
        action=action,
        targets=tuple(targets),
        law=law,
        law_notes=tuple(law_notes),
        stat_name=stat_name,
        tier=tier,
        risk_label=_RISK_FOR_BAND.get(tier),
        time_cost=time_cost,
        block_minutes=block_minutes,
        move_to=move_to,
        already_dispatched=already_dispatched,
        system_note=movement_note,
        movement_blocked=movement_blocked,
        weak_point_target=weak_point_target,
    )


def confirmation_required(decision: TierDecision) -> bool:
    """Does this decision demand the full ``<<Proceed?>>`` beat?

    Engine-owned (interface decision 2): Dire-and-up risk, SEALED, or a
    law flagged irreversible. Everything else auto-commits.
    """
    if decision.law is not None and decision.law.irreversible:
        return True
    if decision.tier is PlausibilityTier.SEALED:
        return True
    if decision.risk_label is None:
        return False
    return CONFIRMATION_REQUIRED_FOR_RISK[decision.risk_label]
