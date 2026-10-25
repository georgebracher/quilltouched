"""Event envelope + event taxonomy for the append-only canon log.

APPEND-ONLY SEMANTICS (binding — roadmap §4 State Architecture):

- The event log is the single source of truth. Events are NEVER
  updated, rewritten, or deleted once written. A correction is a new
  event (e.g. a ``claim_contradicted`` following a ``claim_written``),
  never an edit — this is what makes canon savescum-proof and every
  death auditable.
- Everything else (sheets, known/true projections, rumor states, scene
  manifests, the Chronicle) is a projection rebuilt from this log. A
  bad projection is a bug, never a loss.
- ``stream_version`` is the per-stream monotonic sequence number
  (1, 2, 3… with no gaps within a stream); appends assert the expected
  next version (optimistic concurrency). Enforcement lives in the
  persistence layer — the engine only defines the shape.
- Payloads are VERSIONED (``payload_version``) so old events can be
  upcast when a payload schema evolves; the stored event is still
  never mutated.

Full taxonomy with payload sketches and consuming projections:
``docs/engine/events.md`` (ticket A0.2).
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

__all__ = ["EventType", "Event", "EventSpec", "event_ref", "narration_spec"]


class EventType(enum.StrEnum):
    """Every event type the canon log may contain (taxonomy).

    Values are the wire/storage names. New types may be ADDED in later
    sprints; existing names and meanings are never repurposed.
    """

    # The core loop
    ACTION_DECLARED = "action_declared"      # player committed an action (post commit-beat)
    INTENT_PARSED = "intent_parsed"          # structured intent recorded for audit/replay
    OUTCOME_RESOLVED = "outcome_resolved"    # engine verdict: band, dice, tier, state deltas

    # Knowledge (Chronicle / Inquiry)
    CLAIM_WRITTEN = "claim_written"          # a KNOWN-sheet claim (with provenance) recorded
    CLAIM_CONTRADICTED = "claim_contradicted"  # Sprint-0 name, NEVER shipped (no fold, no
    #                                          writer). Kept because the vocabulary is
    #                                          append-only; the shipped contradiction
    #                                          grammar is claim_contested below (§2.3).

    # Deeds, titles, world memory
    DEED_RECORDED = "deed_recorded"          # significant outcome became a witnessed deed
    TITLE_MINTED = "title_minted"            # deed thresholds minted a System title

    # World clock
    TIMER_STARTED = "timer_started"          # a timed block began (training/research/travel…)
    TIMER_COMPLETED = "timer_completed"      # timer ran to term; results land
    TIMER_ABORTED = "timer_aborted"          # timer interrupted; pro-rated gains recorded

    # Death & legacy
    DEATH_SEALED = "death_sealed"            # full death record — written BEFORE narration
    HEIR_CREATED = "heir_created"            # heir enters the same world; thin inheritance

    # Canon growth
    ENTITY_COMMITTED = "entity_committed"    # generated entity validated + committed forever

    # Sprint-1 additions (vocabulary is append-only; docs/engine/events.md
    # "Sprint 1 additions" section documents payloads + consumers).
    WORLD_CREATED = "world_created"          # genesis: world seed committed (server-side only)
    CHARACTER_CREATED = "character_created"  # chargen: aptitude rolls resolved into a character
    TIME_ADVANCED = "time_advanced"          # world clock advanced without an action (sweeper)

    # Sprint-1 review fixes: genesis pins the authored content.
    CONTENT_MANIFEST = "content_manifest"    # sha256 of the world YAML bytes + loader version

    # Claim-lifecycle additions (§2.3:
    # transitions are EVENTS so the claim table stays a rebuildable
    # projection. Payload shapes in docs/engine/events.md.)
    CLAIM_CORROBORATED = "claim_corroborated"  # an evidence link attached; strength/status stamped
    CLAIM_CONTESTED = "claim_contested"        # live conflicting claim linked; both stay active
    CLAIM_SUPERSEDED = "claim_superseded"      # outweighed (reason enum); row never deleted
    CLAIM_RETRACTED = "claim_retracted"        # terminal: origin evidence itself invalidated

    # Narration is canon BOUND to its outcome event —
    # the API logs assembler_version + content_hash + the prose (closes
    # The API's decision-3 TODO). Audit-only fold, no projection table.
    NARRATION_GENERATED = "narration_generated"


@dataclass(frozen=True, slots=True)
class Event:
    """The immutable envelope every canon-log event is wrapped in.

    Fields:
        event_id:        globally unique id (opaque to the engine;
                         assigned at append time by persistence).
        stream_id:       the aggregate stream this event belongs to,
                         e.g. ``"character:<id>"``, ``"region:<id>"``,
                         ``"world"``.
        stream_version:  1-based monotonic position within the stream;
                         gap-free per stream (optimistic concurrency).
        world_time:      world-clock timestamp of the event, in canonical
                         world ticks (unit fixed with the Sprint-1 world
                         clock; opaque monotonic int until then).
        event_type:      one of :class:`EventType`.
        payload_version: schema version of ``payload`` for this
                         event_type, starting at 1. Readers upcast old
                         versions; writers always write the current one.
        payload:         the event body (shape sketched per type in
                         docs/engine/events.md; frozen JSON-safe mapping).

    The envelope is frozen and the payload is wrapped in a read-only
    mapping view at construction. Treat the whole event as immutable:
    once appended it is canon, forever.
    """

    event_id: str
    stream_id: str
    stream_version: int
    world_time: int
    event_type: EventType
    payload_version: int
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.stream_version < 1:
            raise ValueError(f"stream_version is 1-based, got {self.stream_version}")
        if self.payload_version < 1:
            raise ValueError(f"payload_version is 1-based, got {self.payload_version}")
        # Shallow-freeze the payload so envelope holders cannot mutate
        # canon in place (object.__setattr__ is the sanctioned frozen-
        # dataclass init-time write).
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def event_ref(index: int) -> dict[str, int]:
    """Placeholder for 'the DB id of event #index in this same command'.

    Multi-event commands sometimes need later events to reference earlier
    ones (a claim's provenance_root_event_id is the outcome event that
    caused it), but DB ids only exist at insert time. Rules code embeds
    ``event_ref(i)`` in a payload; the store substitutes the real bigint
    id while inserting, in order, inside the one command transaction.
    """
    if index < 0:
        raise ValueError(f"event ref index must be >= 0, got {index}")
    return {"$event_ref": index}


def narration_spec(
    *,
    character_id: str,
    outcome_event_id: int,
    outcome_event_ulid: str,
    world_time: int,
    prose: str,
    assembler_version: str,
    content_hash: str,
    location_id: str | None = None,
    model: str | None = None,
    turn_command_id: str | None = None,
    public_outcome: Mapping[str, Any] | None = None,
) -> EventSpec:
    """Build the ``narration_generated`` event binding prose to its
    committed outcome (decision 3; closes the API's TODO).

    Append it as its OWN command (idempotency key convention:
    ``narrate:<outcome_event_ulid>``) AFTER the outcome's command has
    committed — the outcome ids must already be canon. The fold is
    audit-only (no projection table): the log itself is the canon record
    that THIS prose, assembled by THIS assembler version over THIS
    content hash, narrated THAT outcome. Prose is model output, not
    player-authored text — it is not encrypted.

    THE CANONICAL PUBLIC-TURN RECORD (Hardening Pass 1). When the
    API also supplies ``turn_command_id`` (the ORIGINAL turn command's id,
    what the client retries with) and ``public_outcome`` (the redacted
    :func:`everquill_engine.views.outcome_public` contract), this one event
    becomes the complete player-visible turn record: redacted outcome +
    prose + assembler meta, keyed by the turn command_id. Idempotent on the
    ``narrate:<ulid>`` command, so it survives response loss — a retry is
    absorbed and :func:`everquill_engine.store.public_turn` serves the SAME
    record, never a re-resolved outcome. Both are optional (audit-only
    narration still works without them).
    """
    if not prose:
        raise ValueError("narration_generated needs the prose it canonizes")
    if not content_hash or not assembler_version:
        raise ValueError("narration_generated needs assembler_version + content_hash")
    return EventSpec(
        stream_id=f"character:{character_id}",
        event_type=EventType.NARRATION_GENERATED,
        world_time=world_time,
        location_id=location_id,
        payload={
            "character_id": character_id,
            "outcome_event_id": outcome_event_id,
            "outcome_event_ulid": outcome_event_ulid,
            "turn_command_id": turn_command_id,
            "prose": prose,
            "assembler_version": assembler_version,
            "content_hash": content_hash,
            "model": model,
            "public_outcome": dict(public_outcome) if public_outcome is not None else None,
        },
    )


@dataclass(frozen=True, slots=True)
class EventSpec:
    """An event as produced by rules code, before persistence.

    The store (everquill_engine.store.append_command) assigns id,
    stream_version, command_id and base meta at append time; rules code
    provides everything canon. ``payload`` may contain
    :func:`event_ref` placeholders (see above). ``rng`` is the honest
    dice record for the event ({stream: [...], index, rolls: [...]})
    or None when no dice were drawn. ``meta`` is OPTIONAL telemetry the
    rules code wants merged into the store's meta column (engine/ruleset
    versions land there automatically) — e.g. the
    stat_hint-mismatch audit fields. Meta is deterministic forensics,
    never a fold input.
    """

    stream_id: str
    event_type: EventType
    world_time: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    location_id: str | None = None
    rng: Mapping[str, Any] | None = None
    payload_version: int = 1
    meta: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.world_time < 0:
            raise ValueError(f"world_time must be >= 0, got {self.world_time}")
        if self.payload_version < 1:
            raise ValueError(f"payload_version is 1-based, got {self.payload_version}")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        if self.rng is not None:
            object.__setattr__(self, "rng", MappingProxyType(dict(self.rng)))
        if self.meta is not None:
            object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))
