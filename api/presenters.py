"""Read-side response builders for the scene, Codex and Self views. Pure
shaping over KnownState; no writes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from api.bootstrap import PC_ID
from everquill_engine.clock import world_date
from everquill_engine.resolver import contract_id
from everquill_engine.views import standing_read
from everquill_engine.world import WorldContent


def _status_facts(known) -> dict[str, Any] | None:
    """Chronicle-exact status facts for D's status strip (roadmap §3.8 zone 1):
    coin (Chronicle-exact numerals, never a true-sheet number) + the PC's active
    timers, read straight off ChronicleFacts (docs/engine/known-state.md).
    `due_world_date` is the Chronicle rendering of the timer's world_due
    (`clock.world_date`) — the client shows "Day N, HH:MM", never a raw minute.
    `label` is the authored fictional-progress phrase — null until authored.
    Returns None only if the PC has no Chronicle record (the strip shows date
    only and invents nothing)."""
    try:
        facts = known.chronicle_facts(PC_ID)
    except KeyError:
        return None
    return {
        "coin": facts.coin,
        "active_timers": [
            {
                "timer_id": t.timer_key,
                "kind": t.kind,
                "label": None,
                "due_world_date": world_date(t.due_world_time),
            }
            for t in facts.active_timers
        ],
    }


def _scene_response(known, world_id: str) -> dict[str, Any]:
    try:
        scene = known.scene(PC_ID)
    except KeyError:
        raise HTTPException(status_code=503, detail="world not initialized (no PC yet)") from None
    return {
        "world": world_id,
        "world_date": scene.world_date,
        "location": {
            "id": scene.location_id,
            "name": scene.name,
            "type": scene.location_type,
            "region": scene.region,
        },
        "entities": [
            {
                "id": e.entity_id,
                "name": e.name,
                "kind": e.kind,
                "conditions": list(e.conditions),
                "portrait": e.portrait,
                "slot": (
                    {"slot_id": e.slot_id, "x_pct": e.x_pct, "y_pct": e.y_pct}
                    if e.slot_id is not None
                    else None
                ),
            }
            for e in scene.entities
        ],
        "exits": [
            {"id": e.id, "name": e.name, "carriage_days": e.carriage_days}
            for e in scene.exits
        ],
        # Coin + active timers for the status strip
        # (StatusFacts in client/src/api.ts). Absent-safe: null renders date only.
        "facts": _status_facts(known),
        # How the player knows every id the client may render (marks, workings,
        # Codex): descriptors until a name is learned, never a raw id.
        "labels": known.labels(PC_ID),
    }


def _subject_labels(known) -> dict[str, str]:
    """{contract subject id -> the label the player knows it by}: descriptors
    until a name is learned, on-scene or off (KnownState.labels), plus the
    PC's own Chronicle name. Off-scene subjects used to fall back to a
    client-prettified id, which spelled the true name (audit claude-001)."""
    labels = known.labels(PC_ID)
    try:
        pc = known.chronicle_facts(PC_ID)
        labels[pc.character_id] = pc.name
    except KeyError:
        pass
    return labels


def _known_locations(conn, world_content: WorldContent, known) -> list[dict[str, Any]]:
    """Places the player has SEEN (map-in-Codex v0): the current scene location
    plus every location the PC has ACTED at or TRAVELLED to. Fog-of-war holds —
    genesis seeds entities world-wide on the ``world`` stream, which is NOT
    "seen"; only the PC's OWN character stream (`character:<pc>`) counts, so a
    fresh world shows just the starting location and everything past the ridge
    stays blank. Names/regions come from authored world content (already public
    via /api/scene); an id with no authored location is dropped, never guessed."""
    loc_by_contract = {
        contract_id(loc.id): loc for loc in world_content.locations.values()
    }
    seen: dict[str, dict[str, Any]] = {}

    def _add(cid: str | None) -> None:
        if not cid:
            return
        cid = contract_id(cid)
        if cid in seen:
            return
        loc = loc_by_contract.get(cid)
        if loc is None:
            return
        seen[cid] = {"location_id": cid, "name": loc.name, "region": loc.region}

    try:
        _add(known.scene(PC_ID).location_id)
    except KeyError:
        pass
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT location_id, payload FROM event WHERE stream_id LIKE %s",
                ("character:%",),
            )
            rows = cur.fetchall()
    for loc_id, payload in rows:
        _add(loc_id)
        # travel destination lands immediately (a movement outcome may stamp the
        # origin as its event location_id); position deltas ride outcome payloads
        # (plaintext — intent payloads are encrypted but carry no state_deltas).
        deltas = payload.get("state_deltas", []) if isinstance(payload, dict) else []
        for delta in deltas:
            if isinstance(delta, dict) and delta.get("delta_type") == "position":
                _add(delta.get("to_location_id"))
    return sorted(seen.values(), key=lambda d: d["location_id"])


def _codex_claim(claim, labels: dict[str, str]) -> dict[str, Any]:
    """One KnownState InquiryClaim -> the CodexClaim shape (client/src/api.ts).

    `confidence` is served RAW (the evidence-consistency enum word, e.g.
    `strongly_corroborated`): the client's own `confidenceWord()` pretty-prints
    it (`.replace(/_/g,' ')`), so serving the enum is what lets D wire with no
    changes. NO true-sheet value ever reaches here — the source is KnownState.
    `contested_by_claim_id`/`status` are engine-marked; both sides of a contested
    pair carry each other's id, so the badge lights up both ways with no client
    inference."""
    return {
        "claim_id": claim.claim_id,
        "subject_entity_id": claim.subject_entity_id,
        "subject_label": labels.get(claim.subject_entity_id),
        "claim_text": claim.claim_text,
        "value_or_range": claim.value_or_range,
        "source": claim.source,
        "observer": claim.observer,
        "method": claim.method,
        "world_date": claim.world_date,
        "scope": claim.scope,
        "confidence": claim.confidence,
        "status": claim.status,
        "journal_flag": claim.journal_flag,
        "predicate": claim.predicate,
        "hop_count": claim.hop_count,
        "contested_by_claim_id": claim.contested_by_claim_id,
    }


def _standing_json(s) -> dict[str, Any]:
    read, read_max = standing_read(s.scope, s.value)
    return {
        "scope": s.scope,
        "subject_id": s.subject_id,
        "subject_name": s.subject_name,
        # The word's place on its scale for the meter; never the raw value.
        "read": read,
        "read_max": read_max,
        "descriptor": s.descriptor,
    }


def _self_response(me, world_id: str) -> dict[str, Any]:
    return {
        "world": world_id,
        "character_id": me.character_id,
        "name": me.name,
        "origin": me.origin,
        "aptitudes": me.aptitudes,
        "hp": me.hp,
        "hp_max": me.hp_max,
        "wounds": me.wounds,
        "coin": me.coin,
        "named_abilities": list(me.named_abilities),
        "marks": list(me.marks),
        "dispositions": [_standing_json(s) for s in me.dispositions],
        "standings": [_standing_json(s) for s in me.standings],
        "renown": me.renown,
        "renown_descriptor": me.renown_descriptor,
    }
