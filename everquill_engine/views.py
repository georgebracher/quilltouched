"""KnownState / RefereeState repository split.

Two named state surfaces, so "which state may the narrator/API see?"
is a TYPE question, not a discipline question:

- :class:`RefereeState` — the resolver's FULL surface: the Tier-1 fold
  image (true character sheets, entity hp, timers, rng counters) plus
  the authored :class:`~everquill_engine.world.WorldContent` (true
  sheets, threat bands, laws). SERVER-SIDE ONLY. ``api/`` and ``llm/``
  modules may never import it — enforced by the static AST lint in
  ``tests/test_known_boundary.py``.

- :class:`KnownState` — the ONLY read surface Teams C (assembler/
  narrator) and F (API) consume. It is built by EXTRACTION: safe fields
  are copied out at construction and nothing else is retained, so there
  is no attribute path from a KnownState to an aptitude, a threat band,
  or a raw hp number. It can produce exactly three things:

  1. **Chronicle facts** (:meth:`KnownState.chronicle_facts`) — exact
     facts of record for a character: coin, inventory, wounds AS WORDS
     (never numbers, roadmap §3.3), named abilities (deed-minted
     titles), public guild rank (None until the guild sprint).
  2. **Inquiry claims** (:meth:`KnownState.inquiry_claims`) — the
     believer's fallible dossier entries with full provenance stamps.
  3. **Perceived scene manifest** (:meth:`KnownState.scene`) — the
     fog-of-warred entity list at the character's location, with
     deterministic anchor-slot assignments (interface decision 5) and
     externally visible conditions only (``dispatched`` for entities at
     0 hp, ``wounded`` for the visibly hurt).

Wound words are a deterministic integer banding of hp/hp_max — the
mapping is the published vocabulary (:data:`WOUND_BANDS`); the numbers
behind it never leave this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from everquill_engine.claims import ACTIVE_STATUSES as ACTIVE_CLAIM_STATUSES
from everquill_engine.clock import world_date
from everquill_engine.folds import FoldState
from everquill_engine.resolver import (
    contract_id,
    is_perceptible,
    knows_name_flag,
    perceived_entity_label,
)
from everquill_engine.slots import Slot, assign_slots, load_slot_maps
from everquill_engine.world import WorldContent

__all__ = [
    "WOUND_BANDS",
    "wound_words",
    "ENTITY_CATEGORIES",
    "entity_category",
    "TimerFact",
    "ChronicleFacts",
    "InquiryClaim",
    "PerceivedEntity",
    "SceneExit",
    "SceneView",
    "TopicView",
    "KnownState",
    "RefereeState",
    "ReputationStanding",
    "SelfFacts",
    "load_known_state",
    "self_view",
    "outcome_public",
    "PUBLIC_FLAG_PREFIXES",
]

#: THE canonical entity-category vocabulary (Hardening Pass 1, audit
#: category-contract). The engine view emits a coarse ``category`` on every
#: perceived entity so downstream (the LLM layer's narration gate, the API's adapter)
#: match ONE vocabulary instead of the fine-grained authored ``kind``. The
#: binding rule: **persons = npc + character** (a player-facing being the
#: narrator may voice / address). The map is APPEND-ONLY, like the predicate
#: registry — add new kinds here, never repurpose. Unmapped kinds default to
#: ``"object"`` (a SAFE non-person default: the gate never invents speech for
#: an unclassified entity).
ENTITY_CATEGORIES: dict[str, str] = {
    "character": "person",
    "npc": "person",
    "creature": "creature",
    "prop": "object",
    "item": "object",
    "location": "place",
}

_DEFAULT_CATEGORY = "object"


def entity_category(kind: str) -> str:
    """Coarse :data:`ENTITY_CATEGORIES` category for an authored entity kind.
    ``person`` = npc + character; unmapped kinds fall back to ``object``."""
    return ENTITY_CATEGORIES.get(kind, _DEFAULT_CATEGORY)

#: Published wound vocabulary, healthiest first. Chronicle-facing wounds
#: are ALWAYS one of these words (roadmap §3.3: wounds are Chronicle
#: facts, but raw hp numbers are true-sheet data — even the player's own
#: stats render as ``???``). Banding is integer arithmetic on
#: (hp, hp_max); see :func:`wound_words`.
WOUND_BANDS: tuple[str, ...] = (
    "unhurt",
    "scuffed",
    "hurting",
    "bloodied",
    "at death's door",
    "dispatched",
)


def wound_words(hp: int, hp_max: int) -> str:
    """Deterministic hp → wound word. Integer arithmetic only."""
    if hp_max <= 0:
        return "dispatched"
    if hp >= hp_max:
        return "unhurt"
    if hp <= 0:
        return "dispatched"
    if hp * 4 >= hp_max * 3:
        return "scuffed"
    if hp * 2 >= hp_max:
        return "hurting"
    if hp * 4 >= hp_max:
        return "bloodied"
    return "at death's door"


@dataclass(frozen=True, slots=True)
class TimerFact:
    """One active (pending) timer on a character — a Chronicle fact for the
    status strip (roadmap §3.8/§3.10). KNOWN-safe: the timer's KIND, its
    world-clock due stamp and the real-world deadline; never the true-sheet
    payload behind it. ``due_world_time`` lets the client show fictional
    progress; ``due_at`` is the offline-completion instant."""

    timer_key: str
    kind: str                    # training | research | travel | craft | recovery | …
    due_world_time: int          # world-clock stamp the timer fires at
    due_at: str                  # real-world ISO deadline (Chronicle-exact)


@dataclass(frozen=True, slots=True)
class ChronicleFacts:
    """Exact, immutable facts of record for one character. The narrator
    cannot contradict anything here; nothing here is a true-sheet value."""

    character_id: str            # contract form
    name: str
    coin: int                    # exact (Chronicle-exact numerals allowed)
    wounds: str                  # WORD from WOUND_BANDS, never a number
    named_abilities: tuple[str, ...]   # deed-minted titles
    public_rank: str | None      # guild rank — None until the guild sprint
    inventory: dict[str, int]    # {contract item id: qty}
    location_id: str | None      # contract form
    world_date: str              # Chronicle rendering of the world clock
    active_timers: tuple[TimerFact, ...] = ()  # pending timers (status strip)


@dataclass(frozen=True, slots=True)
class ReputationStanding:
    """One line of the player's standing (Self view): how a person
    feels about them (disposition) or their regard in a town (standing), with a
    narrative descriptor. The value rides along for the client; the word is the
    legible read."""

    scope: str          # disposition | standing
    subject_id: str     # NPC id (disposition) or settlement id (standing)
    subject_name: str   # resolved display name
    value: int
    descriptor: str


@dataclass(frozen=True, slots=True)
class SelfFacts:
    """Who the player is, as they know themselves (the Self view).
    Unlike an NPC's hidden true sheet, the player KNOWS their own build, so
    aptitudes are shown; reputation is their own EARNED standing. Everything
    here already lives in a client-visible Tier-1 projection."""

    character_id: str
    name: str
    origin: str
    aptitudes: dict[str, int]
    hp: int
    hp_max: int
    wounds: str
    coin: int
    named_abilities: tuple[str, ...]
    marks: tuple[str, ...]
    dispositions: tuple[ReputationStanding, ...]   # per known NPC, warmest first
    standings: tuple[ReputationStanding, ...]      # per town, best-regarded first
    renown: int
    renown_descriptor: str


@dataclass(frozen=True, slots=True)
class InquiryClaim:
    """One fallible dossier entry with its provenance stamp (roadmap §3.3).

    Claim v2 additions ride alongside the original surface —
    existing consumers (api/context.py, llm/assembler.py) keep reading
    the same names. ``value_or_range`` is served from the typed
    ``value_text`` column (the v1 column was migrated into it).
    ``strength`` is the decayed evidence-weight sum in integer basis
    points; ``confidence`` remains the display value. Contested pairs
    surface via ``status``/``contested_by_claim_id`` — narrator gold,
    per the claim-graphs lens."""

    claim_id: str
    subject_entity_id: str       # contract form
    claim_text: str
    value_or_range: str | None   # = value_text (compat name)
    source: str
    observer: str | None         # contract form when an entity id
    method: str
    world_date: str
    scope: str
    confidence: str              # evidence consistency, never truth-probability
    status: str
    journal_flag: bool
    predicate: str
    value_text: str | None
    acquisition_method: str
    strength: int
    hop_count: int
    contested_by_claim_id: str | None
    contradiction_ids: tuple[str, ...]  # ALL live contesters (both ways)


@dataclass(frozen=True, slots=True)
class PerceivedEntity:
    """One entity in the perceived scene. Slot fields are presentation
    hints (decision 5): ``slot_id`` null when no slot map covers the
    location type or the slots ran out — the client renders unslotted."""

    entity_id: str               # contract form (valid intent target)
    name: str
    descriptor: str | None
    kind: str                    # fine-grained authored kind (npc/creature/prop/...)
    category: str                # coarse ENTITY_CATEGORIES vocab (person/creature/object)
    portrait: str | None
    conditions: tuple[str, ...]  # externally visible only (dispatched, wounded, ...)
    slot_id: str | None
    x_pct: float | None
    y_pct: float | None


@dataclass(frozen=True, slots=True)
class SceneExit:
    """One public travel connection from the current location."""

    id: str
    name: str
    carriage_days: int


@dataclass(frozen=True, slots=True)
class SceneView:
    """The perceived scene manifest for one character's location."""

    location_id: str             # contract form
    name: str | None
    location_type: str | None
    region: str | None
    world_date: str
    entities: tuple[PerceivedEntity, ...]
    exits: tuple[SceneExit, ...] = ()


@dataclass(frozen=True, slots=True)
class TopicView:
    """One subject the people here could be asked about (parse-call only)."""

    topic_id: str                # contract form (valid intent topic id)
    label: str                   # perceived label, identity fog applied


class KnownState:
    """The KNOWN-state repository. Constructed only via
    :func:`load_known_state` / :meth:`RefereeState.known_view` — both
    extract safe fields and retain nothing referee-grade."""

    def __init__(
        self,
        *,
        world_date_str: str,
        characters: dict[str, ChronicleFacts],
        claims: tuple[tuple[str, InquiryClaim], ...],  # (believer contract id, claim)
        scenes: dict[str, SceneView],
        topics: dict[str, tuple[TopicView, ...]] | None = None,
        labels: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self._world_date = world_date_str
        self._characters = characters
        self._claims = claims
        self._scenes = scenes
        self._topics = topics or {}
        self._labels = labels or {}

    @property
    def world_date(self) -> str:
        return self._world_date

    def chronicle_facts(self, character_id: str) -> ChronicleFacts:
        """Chronicle facts for one character (contract or dotted id)."""
        key = contract_id(character_id)
        facts = self._characters.get(key)
        if facts is None:
            raise KeyError(f"no character of record: {character_id!r}")
        return facts

    def inquiry_claims(
        self, believer_id: str, subject_id: str | None = None
    ) -> tuple[InquiryClaim, ...]:
        """The believer's Inquiry-layer claims, optionally per subject.
        Ordered by claim_id (deterministic)."""
        believer = contract_id(believer_id)
        wanted = contract_id(subject_id) if subject_id else None
        return tuple(
            claim
            for owner, claim in self._claims
            if owner == believer
            and (wanted is None or claim.subject_entity_id == wanted)
        )

    def scene(self, character_id: str) -> SceneView:
        """The perceived scene at the character's current location."""
        key = contract_id(character_id)
        view = self._scenes.get(key)
        if view is None:
            raise KeyError(f"no scene of record for character {character_id!r}")
        return view

    def labels(self, character_id: str) -> dict[str, str]:
        """{contract id -> the label this character knows it by} for every
        perceptible authored entity and location, and ``you`` for themself.

        An NPC reads as its descriptor until the character learns its name, so
        a surface that renders any id through this map can never spell a name
        the player has not learned (audit 2026-10-24, claude-001). Hidden,
        undiscovered entities are absent."""
        return dict(self._labels.get(contract_id(character_id), {}))

    def topics(self, character_id: str) -> tuple[TopicView, ...]:
        """Subjects the people in the character's scene could be asked about.

        For the parser's Topics list only (the closed ``topic_ids`` field picks
        from it): the API scene, the Codex and the narrator never carry it, so
        it cannot tell the player what anyone knows."""
        return self._topics.get(contract_id(character_id), ())


def _active_timers(fold: FoldState, character_id: str) -> tuple[TimerFact, ...]:
    """Pending timers owned by ``character_id`` for the status strip, sorted
    by world-due then key (deterministic). KNOWN-safe fields only."""
    facts = [
        TimerFact(
            timer_key=row["timer_key"],
            kind=row["kind"],
            due_world_time=row["world_due"],
            due_at=str(row["due_at"]),
        )
        for row in fold.timers.values()
        if row.get("status") == "pending" and row.get("subject_id") == character_id
    ]
    return tuple(sorted(facts, key=lambda t: (t.due_world_time, t.timer_key)))


def _visible_conditions(entity_row: dict[str, Any] | None) -> tuple[str, ...]:
    """Externally visible condition tags from an entity_state row."""
    if entity_row is None:
        return ()
    tags = list(entity_row.get("conditions") or [])
    hp, hp_max = entity_row.get("hp"), entity_row.get("hp_max")
    if hp is not None and hp_max:
        if hp <= 0:
            if "dispatched" not in tags:
                tags.append("dispatched")
        elif hp < hp_max and "wounded" not in tags:
            tags.append("wounded")
    return tuple(tags)


def _generic_fog_label(kind: str) -> str:
    if kind == "npc":
        return "a stranger"
    return "something"


def _perceived_entity_name(
    entity_id: str, row: dict[str, Any], actor_flags: dict[str, Any]
) -> str:
    """Display label for one manifest row from this actor's perspective.

    Identity fog gates only authored NPCs. Non-NPC rows already read as
    descriptors ("a ditch slime", "the guild board") and stay unchanged.
    """
    kind = row.get("kind")
    if kind != "npc":
        return row["name"]
    if actor_flags.get(knows_name_flag(entity_id)):
        return row["name"]
    descriptor = row.get("descriptor")
    if isinstance(descriptor, str) and descriptor.strip():
        return descriptor
    return _generic_fog_label(kind)


def _perceived_labels(
    world: WorldContent, character_key: str, flags: dict[str, Any]
) -> dict[str, str]:
    """{contract id -> perceived label} for one character (see KnownState.labels)."""
    out = {contract_id(loc_id): loc.name for loc_id, loc in world.locations.items()}
    actor = {"flags": flags}
    for entity_id, entity in world.entities.items():
        if is_perceptible(world, entity_id, flags):
            out[contract_id(entity_id)] = perceived_entity_label(actor, entity)
    out[character_key] = "you"
    return out


def _askable_topics(
    world: WorldContent,
    fold: FoldState,
    present: dict[str, dict[str, Any]],
    actor_flags: dict[str, Any],
) -> tuple[TopicView, ...]:
    """Knowledge-scope subjects of the NPCs present, minus anything already on
    the scene roster and anything hidden from this character, in id order.
    Labels obey identity fog and add where the subject is, so the parser can
    match "the quarry" or "the man at the chandlery" to an id."""
    topics: dict[str, TopicView] = {}
    for entity_id in sorted(present):
        entity = world.entities.get(entity_id)
        if entity is None or entity.kind != "npc" or entity.knowledge_scope is None:
            continue
        state = fold.entities.get(entity_id) or {}
        if state.get("hp") is not None and state["hp"] <= 0:
            continue  # a body answers no questions (audit claude-007)
        for scoped in entity.knowledge_scope.subjects:
            subject = scoped.subject
            row = fold.manifest.get(subject)
            if subject in present or subject in topics or row is None:
                continue
            if not is_perceptible(world, subject, actor_flags):
                continue
            label = _perceived_entity_name(subject, row, actor_flags)
            where = world.locations.get(row.get("location_id") or "")
            if where is not None:
                label = f"{label} (at {where.name})"
            topics[subject] = TopicView(topic_id=contract_id(subject), label=label)
    return tuple(topics[s] for s in sorted(topics))


def load_known_state(
    fold: FoldState,
    world: WorldContent,
    slot_maps: dict[str, tuple[Slot, ...]] | None = None,
) -> KnownState:
    """Build the KNOWN surface by extraction from the Tier-1 fold image.

    ``slot_maps`` defaults to ``content/world/slots.yaml`` when present
    (loader tolerates absence — content authors write in parallel; fallback is
    stable ordering with slot_id null).
    """
    if slot_maps is None:
        slot_maps = load_slot_maps()
    now = fold.world["world_time"] if fold.world else 0
    date_str = world_date(now)

    characters: dict[str, ChronicleFacts] = {}
    scenes: dict[str, SceneView] = {}
    topics: dict[str, tuple[TopicView, ...]] = {}
    labels: dict[str, dict[str, str]] = {}
    for character_id, sheet in fold.characters.items():
        key = contract_id(character_id)
        labels[key] = _perceived_labels(world, key, sheet["flags"])
        characters[key] = ChronicleFacts(
            character_id=key,
            name=sheet["name"],
            coin=sheet["coin"],
            wounds=wound_words(sheet["hp"], sheet["hp_max"]),
            named_abilities=tuple(
                t["title"] for t in sheet["titles"] if isinstance(t, dict) and "title" in t
            ),
            public_rank=None,  # guild certification lands with the guild sprint
            inventory={
                contract_id(item): qty for item, qty in sheet["inventory"].items()
            },
            location_id=(
                contract_id(sheet["location_id"]) if sheet["location_id"] else None
            ),
            world_date=date_str,
            active_timers=_active_timers(fold, character_id),
        )

        location_id = sheet["location_id"]
        # THE perceived-manifest choke point. Authored entities
        # tagged `hidden` are engine-only until this character holds their
        # discovery flag — filtered here so the API scene, the parser
        # roster, and the narrator context (all built from this scene) can
        # never surface a secret entity's id, name, or location.
        present = {
            entity_id: row
            for entity_id, row in fold.manifest.items()
            if row.get("location_id") == location_id
            and row.get("kind") != "location"
            and is_perceptible(world, entity_id, sheet["flags"])
        }
        location = world.locations.get(location_id) if location_id else None
        location_row = fold.manifest.get(location_id) if location_id else None
        assignment = assign_slots(
            location.type if location else None, slot_maps, list(present)
        )
        entities = []
        for entity_id in sorted(present):
            row = present[entity_id]
            slot = assignment.get(entity_id)
            entities.append(
                PerceivedEntity(
                    entity_id=contract_id(entity_id),
                    name=_perceived_entity_name(entity_id, row, sheet["flags"]),
                    descriptor=row.get("descriptor"),
                    kind=row["kind"],
                    category=entity_category(row["kind"]),
                    portrait=row.get("portrait"),
                    conditions=_visible_conditions(fold.entities.get(entity_id)),
                    slot_id=slot.slot_id if slot else None,
                    x_pct=slot.x_pct if slot else None,
                    y_pct=slot.y_pct if slot else None,
                )
            )
        exits = []
        if location is not None:
            for connection in location.connections:
                destination = world.locations.get(connection.to)
                if destination is None:
                    continue
                exits.append(
                    SceneExit(
                        id=contract_id(connection.to),
                        name=destination.name,
                        carriage_days=connection.carriage_days,
                    )
                )
        scenes[key] = SceneView(
            location_id=contract_id(location_id) if location_id else "",
            name=(
                location.name
                if location
                else (location_row["name"] if location_row else None)
            ),
            location_type=location.type if location else None,
            region=(
                location.region
                if location
                else (location_row["region"] if location_row else None)
            ),
            world_date=date_str,
            entities=tuple(entities),
            exits=tuple(exits),
        )
        topics[key] = _askable_topics(world, fold, present, sheet["flags"])

    claims = tuple(
        (
            contract_id(row["believer_id"]),
            InquiryClaim(
                claim_id=row["claim_id"],
                subject_entity_id=contract_id(row["subject_entity_id"]),
                claim_text=row["claim_text"],
                value_or_range=row["value_text"],
                source=row["source"],
                observer=contract_id(row["observer"]) if row["observer"] else None,
                method=row["method"],
                world_date=row["world_date"],
                scope=row["scope"],
                confidence=row["confidence"],
                status=row["status"],
                journal_flag=row["journal_flag"],
                predicate=row["predicate"],
                value_text=row["value_text"],
                acquisition_method=row["acquisition_method"],
                strength=row["strength"],
                hop_count=row["hop_count"],
                contested_by_claim_id=row["contested_by_claim_id"],
                contradiction_ids=tuple(row.get("contradiction_ids") or []),
            ),
        )
        for _, row in sorted(fold.claims.items())
        # Live dossier only: superseded/retracted rows stay in the
        # projection for audit/provenance walks but are no longer what
        # the believer believes (claim-graphs lens: the partial indexes
        # drop them for the same reason). Contested claims DO surface —
        # both sides, linked — that's the gameplay.
        if row["layer"] == "inquiry" and row["status"] in ACTIVE_CLAIM_STATUSES
    )

    return KnownState(
        world_date_str=date_str,
        characters=characters,
        claims=claims,
        scenes=scenes,
        topics=topics,
        labels=labels,
    )


# --- outcome redaction -----------------------------------------------

#: Flag-delta key prefixes that are safe to surface in the public/narrator
#: outcome view. Everything else (journal_hook_/humbled_/botched_/attempted_/
#: rapport_/…) is INTERNAL and stripped — the exact-hp path and
#: generic internal flags were the leak. `rapport_` is deliberately NOT yet
#: here (positive-social state the narrator does not consume): add it when a
#: consumer needs it, don't widen the allowlist speculatively.
PUBLIC_FLAG_PREFIXES: tuple[str, ...] = (
    "owes_favor_",
    "rebuffed_",
    "noticed_by_",
    "discovered_",
    "scar_",
    "marked_",
)

MARK_FLAG_PREFIXES: tuple[str, ...] = ("scar_", "marked_")


def outcome_public(
    contract: dict[str, Any], *, wounds_after: dict[str, str] | None = None
) -> dict[str, Any]:
    """Redact a resolver outcome contract for the player + narrator.

    Input is :func:`everquill_engine.resolver.outcome_contract`'s dict (the
    canonical, hp-exact contract). Output is an allowlisted projection:

    - ``hp`` deltas collapse to ``wound_transition`` deltas carrying a
      fiction ``effect`` only (``wounded`` / ``recovered`` / ``dispatched``)
      — NO amount, NO cause. When ``wounds_after`` (contract-entity-id →
      resulting wound WORD, from the post-resolution KnownState) marks the
      target ``dispatched`` the effect is ``dispatched``; otherwise the
      sign of the change decides wounded vs recovered.
    - ``flag`` deltas survive only when their key starts with a
      :data:`PUBLIC_FLAG_PREFIXES` prefix; internal flags are dropped.
    - ``intel`` deltas keep only the claim: provenance root, hop count and
      derivation are store bookkeeping, not part of the public contract.
    - every other delta (deed/coin/inventory/position/timer/…) is already
      KNOWN-safe and passes through unchanged.

    Top-level fields (tier/risk/outcome_tier/dice/constraints/ids) are
    band-derived, KNOWN-safe data and pass through. Pure; the caller keeps
    the canonical contract server-side and serves only this view."""
    after = wounds_after or {}
    public_deltas: list[dict[str, Any]] = []
    for delta in contract.get("state_deltas", []):
        kind = delta.get("delta_type")
        if kind == "hp":
            entity = delta.get("entity_id")
            resulting = after.get(entity)
            if resulting == "dispatched":
                effect = "dispatched"
            else:
                effect = "recovered" if (delta.get("amount") or 0) > 0 else "wounded"
            public_deltas.append(
                {"delta_type": "wound_transition", "entity_id": entity, "effect": effect}
            )
        elif kind == "flag":
            if any(delta.get("flag_key", "").startswith(p) for p in PUBLIC_FLAG_PREFIXES):
                public_deltas.append(delta)
            # else: internal flag — stripped from the public view.
        elif kind == "intel":
            public_deltas.append({"delta_type": "intel", "claim": delta["claim"]})
        else:
            public_deltas.append(delta)
    return {**{k: v for k, v in contract.items() if k != "state_deltas"},
            "state_deltas": public_deltas}


def _disposition_word(value: int) -> str:
    if value >= 3:
        return "trusts you"
    if value == 2:
        return "warm to you"
    if value == 1:
        return "on friendly terms"
    if value == 0:
        return "takes no particular view"
    if value == -1:
        return "wary of you"
    if value == -2:
        return "cold toward you"
    return "wants nothing to do with you"


def _standing_word(value: int) -> str:
    if value >= 3:
        return "esteemed here"
    if value >= 1:
        return "well-regarded here"
    if value == 0:
        return "a stranger here"
    if value >= -2:
        return "distrusted here"
    return "unwelcome here"


def standing_read(scope: str, value: int) -> tuple[int, int]:
    """Where a standing's WORD sits on its scale, and the scale's reach: the
    meter the Self tab draws. The client gets this, never the value, so a town
    standing shows no finer than its words (audit claude #25, George 25 Oct).
    Disposition words are one per value, so there the position is the value."""
    if scope == "disposition":
        return max(-3, min(3, value)), 3
    if value >= 3:
        return 2, 2
    if value >= 1:
        return 1, 2
    if value == 0:
        return 0, 2
    if value >= -2:
        return -1, 2
    return -2, 2


def _renown_word(value: int) -> str:
    if value <= 0:
        return "an unknown"
    if value <= 3:
        return "a local name"
    if value <= 9:
        return "widely spoken of"
    return "renowned"


def _humanize_id(entity_id: str) -> str:
    """Best-effort display name from an id when no manifest name is known:
    'loc.harrowdown' -> 'Harrowdown'; 'npc.dev.hedda' -> 'Hedda'."""
    tail = entity_id.split(".")[-1].replace("_", " ").strip()
    return tail.title() if tail else entity_id


def self_view(fold: FoldState, character_id: str) -> SelfFacts | None:
    """Assemble the player's Self view: their own sheet (they know their build)
    plus their EARNED reputation, resolved to names and narrative descriptors.
    None when the character has no sheet yet. Pure — reads the Tier-1 fold."""
    sheet = fold.characters.get(character_id)
    if sheet is None:
        return None

    def _name(subject_id: str) -> str:
        # Identity fog: a person reads as their descriptor until you learn
        # their name, here as in the scene.
        row = fold.manifest.get(subject_id)
        if not row or not row.get("name"):
            return _humanize_id(subject_id)
        return _perceived_entity_name(subject_id, row, sheet.get("flags") or {})

    def _title(entry: Any) -> str:
        return entry["title"] if isinstance(entry, dict) else entry

    def _marks() -> tuple[str, ...]:
        flags = sheet.get("flags") or {}
        return tuple(
            str(flags[key])
            for key in sorted(flags)
            if any(key.startswith(prefix) for prefix in MARK_FLAG_PREFIXES)
        )

    dispositions: list[ReputationStanding] = []
    standings: list[ReputationStanding] = []
    renown = 0
    prefix = f"{character_id}::"
    for key, row in fold.reputation.items():
        if not key.startswith(prefix):
            continue
        scope, subject_id, value = row["scope"], row["subject_id"], row["value"]
        if scope == "disposition":
            dispositions.append(
                ReputationStanding(
                    scope, subject_id, _name(subject_id), value, _disposition_word(value)
                )
            )
        elif scope == "standing":
            standings.append(
                ReputationStanding(
                    scope, subject_id, _name(subject_id), value, _standing_word(value)
                )
            )
        elif scope == "renown":
            renown = value

    dispositions.sort(key=lambda r: (-r.value, r.subject_name))
    standings.sort(key=lambda r: (-r.value, r.subject_name))
    return SelfFacts(
        character_id=character_id,
        name=sheet["name"],
        origin=sheet["origin"],
        aptitudes=dict(sheet["aptitudes"]),
        hp=sheet["hp"],
        hp_max=sheet["hp_max"],
        wounds=wound_words(sheet["hp"], sheet["hp_max"]),
        coin=sheet["coin"],
        named_abilities=tuple(_title(t) for t in sheet.get("titles", [])),
        marks=_marks(),
        dispositions=tuple(dispositions),
        standings=tuple(standings),
        renown=renown,
        renown_descriptor=_renown_word(renown),
    )


@dataclass(frozen=True, slots=True)
class RefereeState:
    """The resolver's FULL state surface — Tier-1 fold image plus the
    authored world content (true sheets, laws). Never importable from
    ``api/`` or ``llm/`` (static lint). The service layer (beat.py)
    consumes this; everything narrator/API-facing goes through
    :meth:`known_view`."""

    fold: FoldState
    world: WorldContent

    @classmethod
    def load(cls, cur, world: WorldContent) -> RefereeState:
        """Load from an open cursor (caller owns transaction + world lock)."""
        from everquill_engine.store import load_fold_state

        return cls(fold=load_fold_state(cur), world=world)

    def known_view(
        self, slot_maps: dict[str, tuple[Slot, ...]] | None = None
    ) -> KnownState:
        return load_known_state(self.fold, self.world, slot_maps)
