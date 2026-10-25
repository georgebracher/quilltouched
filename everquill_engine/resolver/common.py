"""Shared resolver vocabulary: errors, result types, constants and the
helpers every later stage reads (perception, typed intent, law matching)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from everquill_engine.events import EventSpec
from everquill_engine.intent import (
    Dialogue,
    IntentValidationError,
    ParsedIntent,
    parse_intent,
)
from everquill_engine.ladder import (
    OutcomeTier,
    PlausibilityTier,
    RiskLabel,
)
from everquill_engine.world import Law, WorldContent

#: THE acting-aptitude selector: engine-owned, keyed by
#: action type. The intent's stat_hint is ADVISORY ONLY — it is stored
#: for parse audit and mismatch telemetry (event meta) and NEVER read
#: for resolution, so parser variance can never change difficulty,
#: rolls, or state. Later sprints select aptitudes through engine-owned
#: techniques/action metadata; this table is the v1 form of that.
DEFAULT_STAT_FOR_ACTION: dict[str, str] = {
    "physical": "might",
    "social": "presence",
    "observation": "wits",
    "research": "lore",
    "craft": "finesse",
    "movement": "finesse",
    "train": "will",
}

#: Difficulty for rollable actions with no resolvable target (an
#: ambient task, nobody's true sheet in play). Sits at the low end of a
#: commoner aptitude (2d6 mean 7) so fresh characters see ROUTINE.
UNTARGETED_DIFFICULTY = 5

#: Private character-sheet flag holding the current conversation partner's
#: dotted NPC id. The resolver owns set/reset logic and folds apply the stored
#: flag deltas verbatim; outcome_public strips this key from player/narrator
#: contracts because it is not in PUBLIC_FLAG_PREFIXES.
CONVERSATION_PARTNER_FLAG = "conversation_partner_id"

#: Pre-roll risk label per band. DESPERATE (the stakes word) is reserved
#: for lethal-stakes escalation, which lands with the danger sprint —
#: documented in docs/engine/stats.md.
_RISK_FOR_BAND: dict[PlausibilityTier, RiskLabel] = {
    PlausibilityTier.ROUTINE: RiskLabel.GUARDED,
    PlausibilityTier.RISKY: RiskLabel.PERILOUS,
    PlausibilityTier.DESPERATE: RiskLabel.DIRE,
    PlausibilityTier.HOPELESS: RiskLabel.SUICIDAL,
}

#: KNOWN-safe flat modifier per band. The band is already shown to the
#: player pre-roll as the risk label, so a band-derived modifier leaks
#: nothing the risk label didn't; raw stat gaps would.
_BAND_MODIFIER: dict[PlausibilityTier, int] = {
    PlausibilityTier.ROUTINE: 1,
    PlausibilityTier.RISKY: 0,
    PlausibilityTier.DESPERATE: -1,
    PlausibilityTier.HOPELESS: 0,
}

#: The KNOWN-safe roll bonus a held weak_point claim grants on a
#: physical action against that target — you strike where it is soft. It is
#: derived from a claim the player already holds, so it leaks nothing new;
#: the Chronicle shows it as a named modifier (the dice are the trust
#: surface).
WEAK_POINT_ROLL_BONUS = 2

#: TUNABLE (George feel): DESPERATE-band physical counterattack harm is
#: ``max(1, threat_gap // DESPERATE_COUNTERATTACK_GAP_DIVISOR)``. Gap 4 -> 2,
#: gap 7 -> 3. The actual hp delta still runs through `_clamped_self_harm`,
#: so Slice 3 danger bites without producing death.
DESPERATE_COUNTERATTACK_GAP_DIVISOR = 2

#: THE tier→confirmation-required table (interface decision 2,
#: engine-owned). Keyed on the PRE-roll risk label: Dire-and-up demands
#: the full <<Proceed?>> beat; Guarded/Perilous auto-commit (ghost-echo).
#: SEALED always confirms (with or without components met — met sealed
#: resolves at DESPERATE→Dire anyway); laws flagged ``irreversible``
#: force the beat regardless of tier. TRIVIAL and IMPOSSIBLE never
#: confirm (no stakes to misparse into; impossible is the world reacting
#: to the attempt itself).
CONFIRMATION_REQUIRED_FOR_RISK: dict[RiskLabel, bool] = {
    RiskLabel.GUARDED: False,
    RiskLabel.PERILOUS: False,
    RiskLabel.DIRE: True,
    RiskLabel.DESPERATE: True,
    RiskLabel.SUICIDAL: True,
}


class ResolverError(ValueError):
    """The intent cannot be resolved against current state (no canon written)."""


def _effective_threat(entity, entity_states: dict[str, dict[str, Any]] | None) -> int:
    """Current combat threat: authored threat_band scaled by remaining hp.

    Difficulty reads the authored TRUE sheet plus the
    entity's CURRENT entity_state — a wounded wyvern is a different
    fight. Rule (engine-owned, deterministic, integer): the effective
    threat is ceil(threat_band * hp / hp_max), floored at 1. Full
    health = the authored band; a nearly-dead foe reads (and fights)
    near-TRIVIAL. Entities without a state row (no mutable hp) keep the
    authored band unchanged.
    """
    band = entity.true_sheet.threat_band
    row = (entity_states or {}).get(entity.id)
    if row is None:
        return band
    hp, hp_max = row["hp"], row["hp_max"]
    if hp_max <= 0 or hp >= hp_max:
        return band
    if hp <= 0:
        return 1  # helpless but alive — death is a later sprint
    return max(1, -(-band * hp // hp_max))  # ceil(band * hp / hp_max)


#: Reputation shifts a social contest but never owns it: the standing
#: modifier (disposition + town standing) is clamped to ±this, and each
#: outcome's disposition/standing total is bounded (The Self & The
#: Social). A warm friend eases a hard guard; a bad name stiffens an easy one.
_SOCIAL_REP_MODIFIER_BOUND = 4
_DISPOSITION_BAND = (-3, 3)
_STANDING_BAND = (-5, 5)
_RENOWN_BAND = (0, 99)


def _settlement_of(location_id: str | None) -> str:
    """The town a location belongs to — the 'standing' reputation subject.
    'loc.harrowdown.tavern' -> 'loc.harrowdown'; a bare town id passes
    through. '' when there is no location (no town to hold standing in)."""
    if not location_id:
        return ""
    parts = location_id.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else location_id


def _rep_value(
    reputation: dict[str, dict[str, Any]] | None,
    actor_id: str | None,
    scope: str,
    subject_id: str | None,
) -> int:
    """Current reputation total for one (actor, scope, subject), else 0."""
    if not reputation or actor_id is None:
        return 0
    row = reputation.get(f"{actor_id}::{scope}::{subject_id or ''}")
    return row["value"] if row else 0


def _social_standing_modifier(
    reputation: dict[str, dict[str, Any]] | None,
    actor_id: str | None,
    target_ids: list[str],
    settlement_id: str | None,
) -> int:
    """How much the actor's standing eases (+) or stiffens (-) a social ask:
    the LEAST-warm addressed NPC's disposition (the hardest target sets the
    floor, matching the will max) plus the actor's regard in this town.
    Clamped to ±_SOCIAL_REP_MODIFIER_BOUND so reputation shifts the odds
    without trivialising a hard guard or sealing off a warm one."""
    if not reputation or actor_id is None or not target_ids:
        return 0
    disposition = min(
        _rep_value(reputation, actor_id, "disposition", tid) for tid in target_ids
    )
    standing = _rep_value(reputation, actor_id, "standing", settlement_id)
    total = disposition + standing
    return max(-_SOCIAL_REP_MODIFIER_BOUND, min(_SOCIAL_REP_MODIFIER_BOUND, total))


def _reputation_delta(
    reputation: dict[str, dict[str, Any]] | None,
    actor_id: str,
    scope: str,
    subject_id: str,
    want: int,
    band: tuple[int, int],
) -> dict[str, Any] | None:
    """A reputation delta that moves the running total by ``want`` toward the
    outcome but keeps it inside ``band`` — the RESOLVER clamps here so the
    fold applies the stored amount verbatim (event sourcing, folds.py rule 1).
    None when the total already sits at the bound (no no-op delta emitted)."""
    current = _rep_value(reputation, actor_id, scope, subject_id)
    lo, hi = band
    target = max(lo, min(hi, current + want))
    amount = target - current
    if amount == 0:
        return None
    return {
        "delta_type": "reputation", "entity_id": actor_id,
        "scope": scope, "subject_id": subject_id, "amount": amount,
    }


def _renown_amount_for_deed(notoriety: int) -> int:
    """V1 deed→renown scale: modest, immediate, and zero for notoriety-1."""
    return max(0, int(notoriety) // 2)


def _renown_delta_for_deeds(
    deltas: list[dict[str, Any]],
    *,
    reputation: dict[str, dict[str, Any]] | None,
    actor_id: str,
) -> dict[str, Any] | None:
    amount = sum(
        _renown_amount_for_deed(delta["notoriety"])
        for delta in deltas
        if delta["delta_type"] == "deed"
    )
    if amount <= 0:
        return None
    return _reputation_delta(reputation, actor_id, "renown", "", amount, _RENOWN_BAND)


def _difficulty_for(
    action: str,
    target_entities: list,
    entity_states: dict[str, dict[str, Any]] | None,
    *,
    reputation: dict[str, dict[str, Any]] | None = None,
    actor_id: str | None = None,
    settlement_id: str | None = None,
) -> int:
    """Difficulty demanded of a rollable action (docs/engine/stats.md).

    threat_band is a COMBAT number, so only physical opposition reads
    it (scaled by current wounds — see :func:`_effective_threat`);
    social and observation contest the target's defending aptitude
    (will / wits); research and craft are tests of your own craft
    against an ambient bar. Multi-target: the hardest target sets it.

    A social guard is EASED by the actor's standing — the
    addressed NPC's disposition plus the actor's regard in this town
    (:func:`_social_standing_modifier`) subtract from the will the actor
    must beat, so reputation you earned changes the odds.
    """
    if not target_entities:
        return UNTARGETED_DIFFICULTY
    if action == "physical":
        return max(_effective_threat(e, entity_states) for e in target_entities)
    if action == "social":
        base = max(e.true_sheet.aptitudes["will"] for e in target_entities)
        return base - _social_standing_modifier(
            reputation, actor_id, [e.id for e in target_entities], settlement_id
        )
    if action == "observation":
        return max(e.true_sheet.aptitudes["wits"] for e in target_entities)
    return UNTARGETED_DIFFICULTY


@dataclass(frozen=True, slots=True)
class Resolution:
    """Everything one resolved turn hands back to the store/CLI."""

    events: tuple[EventSpec, ...]
    outcome_event_index: int          # index into events of the outcome_resolved spec
    tier: PlausibilityTier
    risk_label: RiskLabel | None
    outcome_tier: OutcomeTier | None
    hopeless_flavor: str | None
    dice: dict[str, Any] | None
    world_time_after: int
    summary: tuple[str, ...] = field(default=())  # Chronicle lines for the CLI


def contract_id(entity_id: str) -> str:
    """Dotted world id → schema-safe contract id ('npc.dev.mara' → 'npc_dev_mara')."""
    return entity_id.replace(".", "_")


#: An authored entity carrying this true-sheet tag is engine-only.
#: It is absent from every perceived surface (KnownState scene, parser
#: roster, narrator context) and unaddressable as an intent target UNTIL a
#: committed discovery fact makes it known to the perceiving character.
HIDDEN_TAG = "hidden"

#: The discovery fact is an ordinary ``flag`` delta any outcome may carry —
#: ``discovered_<contract_id>`` on the discovering character's sheet. No new
#: fold or delta type: the existing flag rule folds it and
#: ``views.outcome_public`` allowlists this prefix.
DISCOVERY_FLAG_PREFIX = "discovered_"

#: Per-actor identity knowledge fact. A flag delta on the actor sheet with
#: this key means that actor may see the target NPC's true name.
KNOWS_NAME_PREFIX = "knows_name_"


def discovery_flag(entity_id: str) -> str:
    """The character-sheet flag key that marks ``entity_id`` discovered.

    Emitting ``{delta_type: flag, entity_id: <discoverer>, flag_key:
    discovery_flag(target), value: true}`` from any outcome is the whole
    discovery mechanism — the flag fold applies it and
    :func:`is_perceptible` reads it."""
    return f"{DISCOVERY_FLAG_PREFIX}{contract_id(entity_id)}"


def knows_name_flag(entity_id: str) -> str:
    """The character-sheet flag key marking that ``entity_id``'s name is known."""
    return f"{KNOWS_NAME_PREFIX}{contract_id(entity_id)}"


def entity_hidden(world: WorldContent, entity_id: str) -> bool:
    """Is ``entity_id`` an authored engine-only (``hidden``) entity?"""
    entity = world.entities.get(entity_id)
    return entity is not None and HIDDEN_TAG in entity.true_sheet.tags


def is_perceptible(
    world: WorldContent, entity_id: str, actor_flags: dict[str, Any]
) -> bool:
    """Whether ``entity_id`` is perceptible to a character with ``actor_flags``.

    Non-hidden entities are always perceptible; a ``hidden`` entity is
    perceptible only once that character holds its discovery flag. Shared
    by the perceived-manifest choke point (:func:`views.load_known_state`)
    and the target-addressability check below, so scene, roster, narrator,
    and the resolver can never disagree about what exists."""
    if not entity_hidden(world, entity_id):
        return True
    return bool(actor_flags.get(discovery_flag(entity_id)))


def _generic_fog_label(kind: str) -> str:
    if kind == "npc":
        return "a stranger"
    return "something"


def perceived_entity_label(actor: dict[str, Any], entity, fallback: str | None = None) -> str:
    """Actor-perceived label for player-facing derived text.

    NPC names are gated by the actor's ``knows_name_*`` flag; all non-NPC
    entities keep their authored names because those names are already
    descriptive labels in the current content contract.
    """
    if entity is None:
        return fallback or "the subject"
    kind = getattr(entity, "kind", None)
    if kind != "npc":
        return entity.name
    flags = actor.get("flags") or {}
    if flags.get(knows_name_flag(entity.id)):
        return entity.name
    descriptor = getattr(entity, "descriptor", None)
    if descriptor:
        return short_descriptor(descriptor)
    return _generic_fog_label(kind)


def short_descriptor(descriptor: str) -> str:
    """A descriptor cut to the phrase a sentence can carry: "a wary man with a
    ruined left arm, his back to the wall..." -> "the wary man". Derived text
    puts the label mid-sentence ("You take the wary man's measure"); the scene
    keeps the full descriptor. Mirrors client/src/render.ts shortLabel."""
    text = descriptor.split(",")[0].strip()
    with_at = text.find(" with ")
    if with_at > 0:
        text = text[:with_at]
    for article in ("a ", "an ", "A ", "An "):
        if text.startswith(article):
            return "the " + text[len(article):]
    return text


def _fog_known_fact_for_actor(text: str, actor: dict[str, Any], entity) -> str:
    if entity is None or entity.kind != "npc":
        return text
    label = perceived_entity_label(actor, entity)
    if label == entity.name:
        return text
    fogged = text.replace(entity.name, label)
    if fogged.startswith(label):  # "Jorun keeps..." -> "The wary man keeps..."
        fogged = fogged[:1].upper() + fogged[1:]
    return fogged


def _roster(world: WorldContent, manifest: dict[str, dict[str, Any]]) -> dict[str, str]:
    """contract id → dotted id for everything addressable, rejecting collisions."""
    mapping: dict[str, str] = {}
    ids = set(world.entities) | set(world.locations) | set(manifest)
    for dotted in sorted(ids):
        contract = contract_id(dotted)
        clash = mapping.get(contract)
        if clash is not None and clash != dotted:
            raise ResolverError(
                f"contract id collision: {clash!r} and {dotted!r} both map to {contract!r} "
                "— rename one in the world content"
            )
        mapping[contract] = dotted
    return mapping


def _is_dispatched(entity_id: str, entity_states: dict[str, dict[str, Any]] | None) -> bool:
    """Whether the entity is at 0 hp: a body, not a person you can deal with."""
    row = (entity_states or {}).get(entity_id)
    return row is not None and row.get("hp") is not None and row["hp"] <= 0


def _is_present_npc(
    entity_id: str,
    *,
    actor_location: str | None,
    actor_flags: dict[str, Any],
    world: WorldContent,
    manifest: dict[str, dict[str, Any]],
    entity_states: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Whether ``entity_id`` is a co-located, perceptible, living NPC.

    Conversation stickiness is deliberately narrower than general target
    addressability: items do not become conversation partners, and the PC never
    becomes their own partner. Hidden entities obey the same perceptibility
    rule as the parser roster and resolver target check. A dispatched NPC is
    no longer someone you can talk to, learn from or be seen by; it can still
    be looked at.
    """
    if not entity_id or entity_id not in world.entities:
        return False
    if _is_dispatched(entity_id, entity_states):
        return False
    row = manifest.get(entity_id)
    return bool(
        row is not None
        and row.get("kind") == "npc"
        and row.get("location_id") == actor_location
        and is_perceptible(world, entity_id, actor_flags)
    )


def _explicit_room_directed(typed: ParsedIntent) -> bool:
    """Whether the speech is aimed at everyone present (closed ``addressee``)."""
    return typed.addressee == "room"


def _conversation_partner_target(
    typed: ParsedIntent,
    *,
    actor: dict[str, Any],
    world: WorldContent,
    manifest: dict[str, dict[str, Any]],
    entity_states: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Sticky addressee rule.

    The parser still owns names and ambiguity detection. The engine only steps
    in for dialogue/social utterances with no resolved addressee or target: if
    the actor has a current partner and that NPC is still present, the follow-up
    is addressed to them. Named addressees and explicit room speech stay as the
    parser resolved them.
    """
    if typed.action_type not in {"dialogue", "social"}:
        return None
    if typed.target_entity_ids:
        return None
    if typed.dialogue is not None and typed.dialogue.addressee_id is not None:
        return None
    if _explicit_room_directed(typed):
        return None
    partner = (actor.get("flags") or {}).get(CONVERSATION_PARTNER_FLAG)
    if not isinstance(partner, str):
        return None
    actor_flags = actor.get("flags") or {}
    if not _is_present_npc(
        partner,
        actor_location=actor.get("location_id"),
        actor_flags=actor_flags,
        world=world,
        manifest=manifest,
        entity_states=entity_states,
    ):
        return None
    return partner


def _with_conversation_partner(
    typed: ParsedIntent,
    *,
    actor: dict[str, Any],
    world: WorldContent,
    manifest: dict[str, dict[str, Any]],
    entity_states: dict[str, dict[str, Any]] | None = None,
) -> ParsedIntent:
    partner = _conversation_partner_target(
        typed, actor=actor, world=world, manifest=manifest, entity_states=entity_states
    )
    if partner is None:
        return typed
    contract = contract_id(partner)
    dialogue = typed.dialogue
    if dialogue is not None and dialogue.addressee_id is None:
        dialogue = Dialogue(
            addressee_id=contract,
            quoted_speech=dialogue.quoted_speech,
        )
    return replace(typed, target_entity_ids=(contract,), dialogue=dialogue)


def _intent_from_typed(typed: ParsedIntent) -> dict[str, Any]:
    """Render the resolver's normalized typed intent back to the wire shape."""
    return {
        "action_type": typed.action_type,
        "target_entity_ids": list(typed.target_entity_ids),
        "approach": typed.approach,
        "stat_hint": typed.stat_hint,
        "dialogue": (
            None
            if typed.dialogue is None
            else {
                "addressee_id": typed.dialogue.addressee_id,
                "quoted_speech": typed.dialogue.quoted_speech,
            }
        ),
        "plausibility_hint": typed.plausibility_hint,
        "duration_hint": (
            None
            if typed.duration_hint is None
            else {
                "mode": typed.duration_hint.mode,
                "text": typed.duration_hint.text,
                "until": typed.duration_hint.until,
                "amount": typed.duration_hint.amount,
                "unit": typed.duration_hint.unit,
            }
        ),
        "ambiguity_flags": list(typed.ambiguity_flags),
        "addressee": typed.addressee,
        "speech_act": typed.speech_act,
        "topic_ids": list(typed.topic_ids),
        "transaction": (
            None
            if typed.transaction is None
            else {
                "kind": typed.transaction.kind,
                "price_key": typed.transaction.price_key,
                "count": typed.transaction.count,
            }
        ),
        "invoked_law_ids": list(typed.invoked_law_ids),
        "movement_scope": typed.movement_scope,
    }


def _typed_intent(intent: dict[str, Any]) -> ParsedIntent:
    """The closed typed boundary. Every deviation from
    intent.schema.json v1.3 (unknown keys, duplicate targets, malformed
    dialogue/duration, out-of-vocabulary enums) is a ResolverError
    BEFORE any state is touched."""
    try:
        return parse_intent(intent)
    except IntentValidationError as exc:
        raise ResolverError(str(exc)) from exc


def _matching_law(
    world: WorldContent, intent: ParsedIntent, target_ids: list[str]
) -> Law | None:
    """First matching authored override, in file order (deterministic).

    A law with target tags or invoke phrases applies only when a resolved
    target carries one of its tags or the parser named it in the closed
    ``invoked_law_ids`` field (chosen from the Laws list in the parse call).
    The tag hit is the engine's own ruling; the parser's id can only add a
    law (see world.Law for the rule).
    """
    invoked = set(intent.invoked_law_ids)
    for law in world.laws:
        if law.action_types and intent.action_type not in law.action_types:
            continue
        tag_hit = False
        if law.target_tags:
            for target in target_ids:
                entity = world.entities.get(target)
                if entity and any(tag in entity.true_sheet.tags for tag in law.target_tags):
                    tag_hit = True
                    break
        invoked_hit = contract_id(law.law_id) in invoked
        if law.target_tags or law.invoke_phrases:
            if not (tag_hit or invoked_hit):
                continue
        yield_law = law
        return yield_law
    return None
