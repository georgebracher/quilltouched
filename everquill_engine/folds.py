"""Pure Tier-1 projection folds.

THE HARD INVARIANT (synthesis §2.6 rule 1, roadmap State architecture):
folds consume STORED DELTAS and never recompute from engine rules —
event sourcing, not command sourcing. A fold that "just quickly"
re-derives damage from a stored roll would silently rewrite sealed
history at the next balance patch. Therefore:

- This module imports NOTHING from dice/ladder/resolver/chargen/clock/
  world (enforced by tests/test_folds.py::test_folds_import_purity).
- Every mutation applies a stored amount/value verbatim. Bounds (hp
  clamps, coin floors) are the RESOLVER's job at command time — the
  engine emits the delta already clamped, the fold applies it blindly.
- Unknown delta/event types raise: silence would let a new event type
  ship without a fold and quietly desynchronize projections.

Double-write rules (documented once, here, because they are easy to get
wrong): ``outcome_resolved.state_deltas`` is the complete audit record
of a turn, but three delta kinds are ALSO fanned out as their own
events in the same command (claim_written / deed_recorded /
timer_started per the docs/engine/events.md taxonomy). Folds therefore
IGNORE ``intel``, ``deed`` and ``timer_started`` deltas inside
``outcome_resolved`` and fold them from their dedicated events instead
— exactly one writer per projection row.

Used identically by the same-transaction Tier-1 projector and by
truncate-and-replay rebuilds (tests prove hash-equality of the two).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from everquill_engine.upcasters import upcast

__all__ = ["PROJECTOR_VERSIONS", "FoldState", "fold_event", "stream_counter_key"]

#: The fold-logic version of every projection this module can
#: build. BUMP the affected projection's number IN THE SAME COMMIT as
#: any fold change that alters its output for existing events; the
#: golden-snapshot gate (tests/test_folds.py) fails otherwise, and the
#: store refuses to append against a database whose persisted
#: projection_checkpoint.projector_version disagrees with this table
#: until a rebuild has run.
PROJECTOR_VERSIONS: dict[str, int] = {
    "world_state": 1,
    "character_sheet": 1,
    "entity_state": 1,
    "claim": 3,            # v3: multi-edge contradiction_ids (Hardening Pass 1)
    "claim_evidence": 1,
    "scene_manifest": 2,  # v2: optional NPC descriptor for identity fog labels
    "timer": 1,
    "reputation": 1,       # The world's memory of the player
    "deeds": 1,            # Witnessed deeds as rumor substrate
}


@dataclass
class FoldState:
    """In-memory image of every Tier-1 projection table.

    Row dicts mirror the migration columns exactly (minus DB-generated
    ids). ``dirty`` records (table, key) pairs touched since load so the
    DB projector writes back only what changed. ``claim_evidence`` is
    keyed ``(claim_id, event_id)``; its dirty keys are the same pair
    joined with ``"::"`` (both components are id-safe).
    """

    world: dict[str, Any] | None = None
    characters: dict[str, dict[str, Any]] = field(default_factory=dict)
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)  # entity_state rows
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    claim_evidence: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    manifest: dict[str, dict[str, Any]] = field(default_factory=dict)
    timers: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: reputation rows keyed "actor::scope::subject" (subject '' = global renown)
    reputation: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: deed rows in append order; source_event_id is the deed_recorded event id.
    deeds: list[dict[str, Any]] = field(default_factory=list)
    dirty: set[tuple[str, str]] = field(default_factory=set)

    def touch(self, table: str, key: str) -> None:
        self.dirty.add((table, key))


def stream_counter_key(stream: list[str] | tuple[str, ...]) -> str:
    """Canonical JSON key for a dice stream tuple in world_state.rng_counters."""
    return json.dumps(list(stream), separators=(",", ":"))


# --- shared delta application -------------------------------------------------


def _apply_entity_delta(state: FoldState, delta: dict[str, Any], event_id: int) -> None:
    """Apply one stored delta to a non-character entity's entity_state row.

    Hp / condition / position deltas targeting committed
    damageable entities fold into the mutable entity_state projection.
    An entity with NO state row RAISES — a silent drop is exactly how
    'the log says the wyvern bled, the state says it didn't' happened.
    """
    delta_type = delta["delta_type"]
    entity_id = delta["entity_id"]
    row = state.entities.get(entity_id)
    if row is None:
        raise ValueError(
            f"delta {delta_type!r} targets {entity_id!r} which has no entity_state row "
            f"(event {event_id}) — only committed damageable entities hold mutable state"
        )
    if delta_type == "hp":
        row["hp"] = row["hp"] + delta["amount"]
    elif delta_type == "condition":
        conditions = list(row["conditions"])
        if delta["op"] == "add":
            if delta["condition"] not in conditions:
                conditions.append(delta["condition"])
        elif delta["op"] == "remove":
            conditions = [c for c in conditions if c != delta["condition"]]
        else:
            raise ValueError(
                f"condition delta op must be add|remove, got {delta['op']!r} (event {event_id})"
            )
        row["conditions"] = conditions
    elif delta_type == "position":
        row["location_id"] = delta["to_location_id"]
        manifest_row = state.manifest.get(entity_id)
        if manifest_row is not None:
            manifest_row["location_id"] = delta["to_location_id"]
            manifest_row["last_event_id"] = event_id
            state.touch("scene_manifest", entity_id)
    else:
        raise ValueError(
            f"fold has no entity_state rule for delta_type {delta_type!r} "
            f"targeting {entity_id!r} (event {event_id})"
        )
    row["updated_from_event_id"] = event_id
    state.touch("entity_state", entity_id)


def _apply_sheet_delta(state: FoldState, delta: dict[str, Any], event_id: int) -> None:
    """Apply one stored character-sheet delta verbatim."""
    delta_type = delta["delta_type"]
    if delta_type in ("intel", "deed", "timer_started"):
        return  # folded from their dedicated events — see module docstring
    if delta_type == "clock":
        return  # world time folds from the event envelope's world_time
    if delta_type == "reputation":
        _apply_reputation_delta(state, delta, event_id)
        return  # separate projection, not a character_sheet row

    entity_id = delta["entity_id"]
    sheet = state.characters.get(entity_id)
    if sheet is None:
        # Non-character target: folds into entity_state (raises when the
        # entity holds no mutable state — reject, never drop).
        _apply_entity_delta(state, delta, event_id)
        return

    if delta_type == "hp":
        sheet["hp"] = sheet["hp"] + delta["amount"]
    elif delta_type == "coin":
        sheet["coin"] = sheet["coin"] + delta["amount"]
    elif delta_type == "inventory":
        inventory = dict(sheet["inventory"])
        qty = inventory.get(delta["item_id"], 0)
        qty = qty + delta["quantity"] if delta["op"] == "add" else qty - delta["quantity"]
        if qty > 0:
            inventory[delta["item_id"]] = qty
        else:
            inventory.pop(delta["item_id"], None)
        sheet["inventory"] = inventory
    elif delta_type == "flag":
        flags = dict(sheet["flags"])
        flags[delta["flag_key"]] = delta["value"]
        sheet["flags"] = flags
    elif delta_type == "position":
        sheet["location_id"] = delta["to_location_id"]
        row = state.manifest.get(entity_id)
        if row is not None:
            row["location_id"] = delta["to_location_id"]
            row["last_event_id"] = event_id
            state.touch("scene_manifest", entity_id)
    elif delta_type == "title":
        sheet["titles"] = list(sheet["titles"]) + [
            {"title": delta["title"], "deed_ref": delta["deed_ref"]}
        ]
    elif delta_type == "aptitude":
        # Stored training gain: {delta_type: aptitude, entity_id, aptitude, amount}
        aptitudes = dict(sheet["aptitudes"])
        aptitudes[delta["aptitude"]] = aptitudes[delta["aptitude"]] + delta["amount"]
        sheet["aptitudes"] = aptitudes
    else:
        raise ValueError(f"fold has no rule for delta_type {delta_type!r} (event {event_id})")

    sheet["last_event_id"] = event_id
    state.touch("character_sheet", entity_id)


def _apply_reputation_delta(state: FoldState, delta: dict[str, Any], event_id: int) -> None:
    """Fold one reputation delta verbatim into the reputation projection.

    ``scope`` ∈ {disposition, standing, renown}; ``subject_id`` is the NPC id
    (disposition), the settlement id (standing), or '' (global renown). The
    stored ``amount`` is applied as-is: the resolver clamped it to the design
    band at command time, so the fold neither bounds nor re-derives (event
    sourcing, module docstring rule 1). One writer per row — a reputation row
    only ever changes through this delta.
    """
    actor_id = delta["entity_id"]
    scope = delta["scope"]
    subject_id = delta.get("subject_id") or ""
    key = f"{actor_id}::{scope}::{subject_id}"
    row = state.reputation.get(key)
    if row is None:
        row = {
            "actor_id": actor_id,
            "scope": scope,
            "subject_id": subject_id,
            "value": 0,
            "last_event_id": event_id,
        }
        state.reputation[key] = row
    row["value"] = row["value"] + delta["amount"]
    row["last_event_id"] = event_id
    state.touch("reputation", key)


# --- per-event folds -----------------------------------------------------------


def _fold_world_created(state: FoldState, event: dict[str, Any]) -> None:
    state.world = {
        "seed": event["payload"]["seed"],
        "world_time": event["world_time"],
        "rng_counters": {},
        "last_event_id": event["id"],
    }
    state.touch("world_state", "world")


def _fold_entity_committed(state: FoldState, event: dict[str, Any]) -> None:
    payload = event["payload"]
    state.manifest[payload["entity_id"]] = {
        "entity_id": payload["entity_id"],
        "location_id": payload["location_id"],
        "kind": payload["entity_class"],
        "name": payload["name"],
        "region": payload.get("region"),
        "descriptor": payload.get("descriptor"),
        "common_knowledge": list(payload.get("common_knowledge", [])),
        "portrait": payload.get("portrait"),
        "last_event_id": event["id"],
    }
    state.touch("scene_manifest", payload["entity_id"])
    # Damageable entities commit with stored hp/hp_max seed
    # facts → mutable entity_state row. Entities committed without them
    # (locations, items, pre-fix rows) hold no mutable state; a delta
    # targeting one raises in _apply_entity_delta.
    if "hp" in payload:
        state.entities[payload["entity_id"]] = {
            "entity_id": payload["entity_id"],
            "world_id": event["stream_id"],
            "hp": payload["hp"],
            "hp_max": payload["hp_max"],
            "conditions": [],
            "location_id": payload["location_id"],
            "updated_from_event_id": event["id"],
        }
        state.touch("entity_state", payload["entity_id"])


def _fold_character_created(state: FoldState, event: dict[str, Any]) -> None:
    payload = event["payload"]
    character_id = payload["character_id"]
    state.characters[character_id] = {
        "entity_id": character_id,
        "name": payload["name"],
        "origin": payload["origin"],
        "aptitudes": dict(payload["aptitudes"]),
        "hp": payload["hp"],
        "hp_max": payload["hp_max"],
        "coin": payload["coin"],
        "location_id": payload["location_id"],
        "inventory": {},
        "flags": {},
        "titles": [],
        "last_event_id": event["id"],
    }
    state.touch("character_sheet", character_id)
    state.manifest[character_id] = {
        "entity_id": character_id,
        "location_id": payload["location_id"],
        "kind": "character",
        "name": payload["name"],
        "region": payload.get("region"),
        "common_knowledge": [],
        "portrait": None,
        "last_event_id": event["id"],
    }
    state.touch("scene_manifest", character_id)


def _fold_outcome_resolved(state: FoldState, event: dict[str, Any]) -> None:
    for delta in event["payload"]["state_deltas"]:
        _apply_sheet_delta(state, delta, event["id"])


def _fold_claim_written(state: FoldState, event: dict[str, Any]) -> None:
    # Payloads arrive UPCAST to v2 (fold_event upcasts first): typed
    # predicate + value columns + strength, per synthesis §2.3. The fold
    # applies the stored facts verbatim — strength was computed at write
    # time and stamped; it is never re-derived here.
    payload = event["payload"]
    claim = payload["claim"]
    claim_id = payload["claim_id"]
    if claim_id in state.claims:
        # Domain-id uniqueness is canonical. Raising here (both
        # incremental and rebuild use this fold) means live projection
        # and replay can never disagree silently about which claim won.
        raise ValueError(
            f"duplicate claim_id {claim_id!r} (event {event['id']}) — "
            "claim ids are canonical domain ids and may appear once, ever"
        )
    state.claims[claim_id] = {
        "claim_id": claim_id,
        "believer_id": payload["believer_id"],
        "subject_entity_id": claim["subject_entity_id"],
        "predicate": claim["predicate"],
        "value_text": claim.get("value_text"),
        "value_num": claim.get("value_num"),
        "value_range": _range_or_none(claim.get("value_range")),
        "world_valid": _range_or_none(claim.get("world_valid")),
        "claim_text": claim["claim_text"],
        "layer": claim["layer"],
        "source": claim["source"],
        "observer": claim["observer"],
        "method": claim["method"],
        "acquisition_method": claim["acquisition_method"],
        "world_date": claim["world_date"],
        "scope": claim["scope"],
        "confidence": claim["confidence"],
        "status": "asserted",
        "strength": payload["strength"],
        "provenance_root_event_id": payload["provenance_root_event_id"],
        "source_agent_id": claim.get("source_agent_id"),
        "derived_from_claim_id": payload.get("derived_from_claim_id"),
        "hop_count": payload.get("hop_count", 0),
        "journal_flag": payload.get("journal_flag", False),
        "world_time_acquired": event["world_time"],
        "origin_event_id": event["id"],
        "contested_by_claim_id": None,
        "contradiction_ids": [],
        "superseded_by_claim_id": None,
        "superseded_reason": None,
    }
    state.touch("claim", claim_id)
    # The founding evidence link: the claim's own source event, at its
    # undecayed base weight (= the stamped strength of a fresh claim).
    evidence_world_time = payload.get("evidence_world_time")
    if evidence_world_time is None:
        evidence_world_time = event["world_time"]
    _add_evidence(
        state,
        claim_id=claim_id,
        event_id=event["id"],
        root_event_id=payload["provenance_root_event_id"],
        acquisition_method=claim["acquisition_method"],
        base_weight=payload["strength"],
        world_time=evidence_world_time,
        source_event_id=event["id"],
    )


def _range_or_none(value: Any) -> list[int] | None:
    """Canonical [lo, hi] inclusive int pair (payload lists/tuples), or None."""
    if value is None:
        return None
    lo, hi = value
    return [int(lo), int(hi)]


def _add_evidence(
    state: FoldState,
    *,
    claim_id: str,
    event_id: int,
    root_event_id: int,
    acquisition_method: str,
    base_weight: int,
    world_time: int,
    source_event_id: int,
) -> None:
    key = (claim_id, event_id)
    if key in state.claim_evidence:
        raise ValueError(
            f"duplicate evidence link {key!r} (event {source_event_id}) — "
            "one event contributes evidence to a claim at most once"
        )
    state.claim_evidence[key] = {
        "claim_id": claim_id,
        "event_id": event_id,
        "root_event_id": root_event_id,
        "acquisition_method": acquisition_method,
        "base_weight": base_weight,
        "world_time": world_time,
    }
    state.touch("claim_evidence", f"{claim_id}::{event_id}")


def _require_claim(state: FoldState, claim_id: str, event: dict[str, Any]) -> dict[str, Any]:
    row = state.claims.get(claim_id)
    if row is None:
        raise ValueError(
            f"lifecycle event {event['event_type']!r} targets unknown claim "
            f"{claim_id!r} (event {event['id']}) — transitions require the claim row"
        )
    return row


def _fold_claim_corroborated(state: FoldState, event: dict[str, Any]) -> None:
    """An evidence link attached to an existing claim. The RESULTING
    strength and status were decided at write time (distinct-provenance-
    roots rule, everquill_engine.claims) and stored as facts; the fold
    applies them blindly. Retellings of one root arrive with
    status='asserted' — they can never flip corroboration."""
    payload = event["payload"]
    claim_id = payload["claim_id"]
    row = _require_claim(state, claim_id, event)
    evidence = payload["evidence"]
    # evidence.event_id null = "this event's own id" — the corroborating
    # event IS the evidence (stored ids are canon, identical on rebuild).
    evidence_event_id = evidence["event_id"]
    if evidence_event_id is None:
        evidence_event_id = event["id"]
    _add_evidence(
        state,
        claim_id=claim_id,
        event_id=evidence_event_id,
        root_event_id=evidence["root_event_id"],
        acquisition_method=evidence["acquisition_method"],
        base_weight=evidence["base_weight"],
        world_time=evidence["world_time"],
        source_event_id=event["id"],
    )
    row["strength"] = payload["strength"]
    row["status"] = payload["status"]
    state.touch("claim", claim_id)


def _fold_claim_contested(state: FoldState, event: dict[str, Any]) -> None:
    payload = event["payload"]
    row = _require_claim(state, payload["claim_id"], event)
    contester = payload["contested_by_claim_id"]
    row["status"] = "contested"
    row["contested_by_claim_id"] = contester  # latest single (compat name)
    # Multi-edge: a claim contested by SEVERAL others must
    # remember them all — the single column above forgot everything but the
    # last. Sorted + deduped so the projection dump is deterministic and the
    # live incremental image equals a truncate-and-replay rebuild.
    ids = set(row.get("contradiction_ids") or [])
    if contester is not None:
        ids.add(contester)
    row["contradiction_ids"] = sorted(ids)
    state.touch("claim", payload["claim_id"])


def _fold_claim_superseded(state: FoldState, event: dict[str, Any]) -> None:
    payload = event["payload"]
    row = _require_claim(state, payload["claim_id"], event)
    row["status"] = "superseded"
    row["superseded_by_claim_id"] = payload["superseded_by_claim_id"]
    row["superseded_reason"] = payload["superseded_reason"]
    state.touch("claim", payload["claim_id"])


def _fold_claim_retracted(state: FoldState, event: dict[str, Any]) -> None:
    payload = event["payload"]
    row = _require_claim(state, payload["claim_id"], event)
    row["status"] = "retracted"
    state.touch("claim", payload["claim_id"])


def _fold_timer_started(state: FoldState, event: dict[str, Any]) -> None:
    payload = event["payload"]
    if payload["timer_key"] in state.timers:
        # Same canonical-uniqueness rule as claim ids.
        raise ValueError(
            f"duplicate timer_key {payload['timer_key']!r} (event {event['id']}) — "
            "timer keys are canonical domain ids and may appear once, ever"
        )
    due_at = payload.get("due_at")
    if due_at is None:
        # Legacy shim for rows written before timer fire order landed: derive the
        # real deadline from the SAME documented world-epoch mapping the
        # creator would have used (clock.WORLD_EPOCH_UTC: world minute 0 =
        # 1970-01-01T00:00:00Z, 1 world minute = 1 real minute). This is a
        # pure data upcast of a missing stored fact, not an engine rule;
        # new events always carry due_at and fold it verbatim.
        due_at = (
            datetime(1970, 1, 1, tzinfo=UTC) + timedelta(minutes=payload["world_due"])
        ).isoformat()
    state.timers[payload["timer_key"]] = {
        "timer_key": payload["timer_key"],
        "kind": payload["kind"],
        "subject_id": payload["subject_id"],
        "due_at": due_at,
        "world_due": payload["world_due"],
        "payload": dict(payload.get("payload", {})),
        "status": "pending",
        "created_event_id": payload["created_event_id"],
        "fired_event_id": None,
        "attempts": 0,
    }
    state.touch("timer", payload["timer_key"])


def _fold_timer_completed(state: FoldState, event: dict[str, Any]) -> None:
    payload = event["payload"]
    timer = state.timers.get(payload["timer_key"])
    if timer is not None:
        timer["status"] = "fired"
        timer["fired_event_id"] = event["id"]
        state.touch("timer", payload["timer_key"])
    for delta in payload["gains"]:
        _apply_sheet_delta(state, delta, event["id"])


def _fold_deed_recorded(state: FoldState, event: dict[str, Any]) -> None:
    deed = event["payload"]["deed"]
    record = {
        "deed_order": len(state.deeds) + 1,
        "actor_entity_id": deed["actor_entity_id"],
        "location_id": deed["location_id"],
        "notoriety": int(deed["notoriety"]),
        "world_time": event["world_time"],
        "description": deed["description"],
        "source_event_id": event["id"],
    }
    state.deeds.append(record)
    state.touch("deeds", str(event["id"]))


def _fold_intent_parsed(state: FoldState, event: dict[str, Any]) -> None:
    # Audit-only in Sprint 1: consumed by replay/eval tooling, no table.
    return


def _fold_time_advanced(state: FoldState, event: dict[str, Any]) -> None:
    # World time itself folds from the envelope, below, for every event.
    return


def _fold_content_manifest(state: FoldState, event: dict[str, Any]) -> None:
    # Audit-only: world open verifies the hash by reading the
    # event directly; no projection table materializes it.
    return


def _fold_narration_generated(state: FoldState, event: dict[str, Any]) -> None:
    # Audit-only: the log IS the canon record binding
    # prose + assembler_version + content_hash to the outcome event id.
    # No projection table; readers query the log directly.
    return


_FOLDS = {
    "world_created": _fold_world_created,
    "entity_committed": _fold_entity_committed,
    "character_created": _fold_character_created,
    "intent_parsed": _fold_intent_parsed,
    "outcome_resolved": _fold_outcome_resolved,
    "claim_written": _fold_claim_written,
    "claim_corroborated": _fold_claim_corroborated,
    "claim_contested": _fold_claim_contested,
    "claim_superseded": _fold_claim_superseded,
    "claim_retracted": _fold_claim_retracted,
    "deed_recorded": _fold_deed_recorded,
    "timer_started": _fold_timer_started,
    "timer_completed": _fold_timer_completed,
    "time_advanced": _fold_time_advanced,
    "content_manifest": _fold_content_manifest,
    "narration_generated": _fold_narration_generated,
}


def fold_event(state: FoldState, event: dict[str, Any]) -> None:
    """Fold one stored event row into the projection state. Pure.

    ``event`` is the stored row as a plain dict: id, stream_id,
    stream_version, world_time, event_type, location_id, command_id,
    rng, payload, payload_version. Old payload versions are UPCAST first
    (pure chained upcasters) — the stored row is never mutated.
    Raises on unknown event types.
    """
    fold = _FOLDS.get(event["event_type"])
    if fold is None:
        raise ValueError(f"fold has no rule for event_type {event['event_type']!r}")
    event = upcast(event)
    fold(state, event)

    if state.world is not None and event["event_type"] != "world_created":
        changed = False
        if event["world_time"] > state.world["world_time"]:
            state.world["world_time"] = event["world_time"]
            changed = True
        rng = event.get("rng")
        if rng:
            key = stream_counter_key(rng["stream"])
            counters = state.world["rng_counters"]
            next_index = rng["index"] + 1
            if next_index > counters.get(key, 0):
                counters[key] = next_index
                changed = True
        if event["id"] > state.world["last_event_id"]:
            state.world["last_event_id"] = event["id"]
            changed = True
        if changed:
            state.touch("world_state", "world")
