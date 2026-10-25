"""KnownState -> assembler-view adapter.

The thin function llm/assembler.py's ADAPTER CONTRACT asks for: map the engine's
KnownState surface (docs/engine/known-state.md) onto the plain-dict view the
assembler consumes. Mapping notes applied verbatim from the contract:

- SceneView -> view["scene"]: name -> label_known, kind -> category,
  x_pct/y_pct (0..100) -> position {x, y} (0..1), conditions -> state_tags.
- ChronicleFacts -> known_sheets (one slice for the PC; values str|num|bool).
- InquiryClaim -> claims[].claim, with the adapter adding
  corroboration_ids: [], contradiction_ids: [], and inheritance_status from
  journal_flag. Salience meta defaults are safe ({}).
- atmosphere: the authored harrowdown-narrator.yaml, reshaped so C's
  atmosphere_from_world handles the id matching.
- active_clocks: [] until A-team exposes a KNOWN clock surface (the
  assembler tolerates the empty section).
- last_resolution: previous committed outcome_resolved trace read from the
  event log (outcome payloads are contract-safe player-visible data).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from api import telemetry
from everquill_engine.resolver import contract_id
from everquill_engine.store import decrypt_event_payload
from everquill_engine.views import KnownState
from everquill_engine.world import WorldContent, sold_here
from llm.assembler import (
    AssembledContext,
    assemble,
    atmosphere_from_world,
    canonical_entity_id,
    estimate_tokens,
)

PC_ID = "pc"

_narrator_content_cache: dict[str, dict] = {}


def narrator_content(world_path: Path) -> dict:
    """The authored narrator sidecar (<world>-narrator.yaml), reshaped for
    llm.assembler.atmosphere_from_world: {"locations": [{"id", "atmosphere"}]}.
    Tolerates absence (dev fixtures have none)."""
    key = str(world_path)
    if key not in _narrator_content_cache:
        sidecar = world_path.with_name(world_path.stem + "-narrator.yaml")
        locations: list[dict] = []
        if sidecar.exists():
            data = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
            for loc_id, lines in (data.get("atmosphere") or {}).items():
                locations.append({"id": loc_id, "atmosphere": list(lines or [])})
        _narrator_content_cache[key] = {"locations": locations}
    return _narrator_content_cache[key]


def _scene_dict(known: KnownState) -> dict:
    scene = known.scene(PC_ID)
    entities = []
    for e in scene.entities:
        position = None
        if e.slot_id is not None and e.x_pct is not None and e.y_pct is not None:
            position = {"x": round(e.x_pct / 100.0, 4), "y": round(e.y_pct / 100.0, 4)}
        entities.append({
            "entity_id": e.entity_id,
            "label_known": e.name,
            # Category contract: the assembler/gate match the COARSE
            # ENTITY_CATEGORIES vocab (person/creature/object/place), not the
            # fine-grained authored `kind` — persons resolve as npc + character.
            "category": e.category,
            "position": position,
            "state_tags": sorted({canonical_entity_id(c) for c in e.conditions if c}),
        })
    return {
        "location_id": scene.location_id,
        "label_known": scene.name,
        "world_time": scene.world_date,
        "entities": entities,
        "exits": [
            {"id": e.id, "name": e.name, "carriage_days": e.carriage_days}
            for e in (getattr(scene, "exits", ()) or ())
        ],
    }


def _known_sheets(known: KnownState) -> list[dict]:
    facts = known.chronicle_facts(PC_ID)
    rows: list[dict] = [
        {"field": "name", "value": facts.name},
        {"field": "coin", "value": facts.coin},
        {"field": "wounds", "value": facts.wounds},
    ]
    for title in facts.named_abilities:
        rows.append({"field": "named_ability", "value": title})
    if facts.public_rank:
        rows.append({"field": "public_rank", "value": facts.public_rank})
    for item, qty in sorted(facts.inventory.items()):
        rows.append({"field": f"item:{item}", "value": qty})
    return [{"entity_id": facts.character_id, "facts": rows}]


def _claims(known: KnownState) -> list[dict]:
    out = []
    for c in known.inquiry_claims(PC_ID):
        out.append({
            "claim": {
                "claim_id": c.claim_id,
                "subject_entity_id": c.subject_entity_id,
                "claim_text": c.claim_text,
                "value_or_range": c.value_or_range,
                "source": c.source,
                "observer": c.observer,
                "method": c.method,
                "world_date": c.world_date,
                "scope": c.scope,
                "confidence": c.confidence,
                "corroboration_ids": [],
                # Pass A's REAL contested links through so the
                # assembler co-surfaces both halves of a contradiction to the
                # narrator (was hardcoded [] — the contested feature was inert).
                "contradiction_ids": list(c.contradiction_ids),
                "inheritance_status": "inherited" if c.journal_flag else "original",
            },
            "meta": {},  # salience meta defaults are safe (assembler contract)
        })
    return out


def last_resolution_trace(conn, before_event_id: int) -> dict | None:
    """The PREVIOUS committed resolution (already narrated — the assembler
    pins it so the narrator never re-narrates it). Outcome + intent payloads
    are contract-safe, player-visible data."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, payload FROM event
                WHERE event_type = 'outcome_resolved' AND id < %s
                ORDER BY id DESC LIMIT 1
                """,
                (before_event_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            event_id, payload = row[0], dict(row[1])
            summary = None
            intent_ref = payload.get("intent_event")
            if isinstance(intent_ref, int):
                cur.execute("SELECT payload FROM event WHERE id = %s", (intent_ref,))
                intent_row = cur.fetchone()
                if intent_row:
                    # The prior action's `approach` is PLAYER TEXT and
                    # is stored encrypted ({"$enc": ...}); decrypt it on the
                    # owner read path so a plaintext summary — never an
                    # encryption marker — reaches the assembler.
                    intent_payload = decrypt_event_payload(cur, dict(intent_row[0]))
                    summary = (intent_payload.get("intent") or {}).get("approach")
    dice = payload.get("dice")
    return {
        "event_id": str(event_id),
        "action_summary": summary or "an earlier action",
        "tier_resolved": payload["tier_resolved"],
        "outcome_tier": payload["outcome_tier"],
        "dice_total": dice["total"] if dice else None,
    }


def build_view(
    known: KnownState, *, world_path: Path, last_resolution: dict | None
) -> dict[str, Any]:
    """The assembler's KnownStateView dict for this turn."""
    scene = _scene_dict(known)
    return {
        "scene": scene,
        "known_sheets": _known_sheets(known),
        "claims": _claims(known),
        "active_clocks": [],  # no KNOWN clock surface yet (A-team follow-on)
        "canon_excerpts": [],
        "atmosphere": atmosphere_from_world(
            narrator_content(world_path), scene["location_id"]
        ),
        "recent_subjects": {},  # transcript stickiness lands with the client
        "last_resolution": last_resolution,
    }


def assemble_within_cap(view: dict[str, Any]) -> AssembledContext:
    """Assemble the narrator context and ENFORCE the declared final token cap
    AFTER pinned claims.

    The assembler admits pinned constraint-class claims unconditionally — they
    bypass the packer's per-section budget, so a large enough set could push the
    rendered envelope past its own declared ``token_budget.max_tokens``. This is
    the adapter's hard post-condition: if the assembled context exceeds the cap,
    drop the largest pinned claim (deterministic tiebreak: claim_id ASC) and
    re-assemble until it fits or no pinned claim remains. In production the
    adapter marks no claim ``constraint_class`` yet, so this is a no-op today
    and a guardrail for when it does — but the cap is now genuinely enforced,
    not merely declared. Returns the in-cap :class:`AssembledContext`."""
    assembled = assemble(view)
    cap = assembled.envelope["token_budget"]["max_tokens"]
    if assembled.receipt["total_tokens"] <= cap:
        return assembled

    view = dict(view)
    claims = list(view.get("claims", []))
    # largest pinned first; break ties by claim_id so the trim is byte-stable
    pinned_by_cost = sorted(
        (c for c in claims if (c.get("meta") or {}).get("constraint_class")),
        key=lambda c: (-estimate_tokens(c["claim"]), c["claim"]["claim_id"]),
    )
    for victim in pinned_by_cost:
        claims = [c for c in claims if c is not victim]
        view["claims"] = claims
        assembled = assemble(view)
        telemetry.emit(
            "assemble_cap_enforced",
            dropped_claim_id=victim["claim"]["claim_id"],
            total_tokens=assembled.receipt["total_tokens"],
            cap=cap,
        )
        if assembled.receipt["total_tokens"] <= cap:
            break
    return assembled


def fogged_aliases(known: KnownState, world: WorldContent | None) -> dict[str, str]:
    """Opaque model-facing ids for the people whose names the player has not
    learned: contract AND dotted id -> ``person_N``.

    A contract id spells the true name (``npc_harrowdown_jorun_pike``), so
    sending it to the parser or narrator would hand the model a name the
    player does not know (audit 2026-10-24, claude #2). Every authored NPC is
    aliased unless this turn's KNOWN view shows its true name: on the scene,
    or at the head of a topic label. Numbered over every authored NPC by contract
    id, so an alias never shifts when another name is learned.
    """
    if world is None:
        return {}
    known_names: set[str] = set()
    try:
        scene_entities = known.scene(PC_ID).entities
    except KeyError:
        scene_entities = ()
    for entity in world.entities.values():
        cid = contract_id(entity.id)
        if entity.kind != "npc":
            continue
        if any(e.entity_id == cid and e.name == entity.name for e in scene_entities) or any(
            t.topic_id == cid and t.label.startswith(entity.name) for t in known.topics(PC_ID)
        ):
            known_names.add(entity.id)
    people = sorted((e.id for e in world.entities.values() if e.kind == "npc"), key=contract_id)
    aliases: dict[str, str] = {}
    for i, dotted in enumerate(people, start=1):
        if dotted not in known_names:
            aliases[contract_id(dotted)] = aliases[dotted] = f"person_{i}"
    return aliases


def unlearned_names(world: WorldContent | None, aliases: dict[str, str]) -> tuple[str, ...]:
    """Every word of the true names behind ``aliases`` (first names and
    surnames: "Jorun", "Pike"), for the narration gate to reject in prose."""
    if world is None:
        return ()
    out: set[str] = set()
    for dotted, entity in world.entities.items():
        if dotted in aliases:
            out.update(w for w in entity.name.split() if len(w) > 2 and w[0].isupper())
    # A surname on a sign or a grave ("Ferrier's Chandlery") is the world being
    # legible, and the narrator may say it.
    public = " ".join(
        [loc.name for loc in world.locations.values()]
        + [e.name for e in world.entities.values() if e.kind != "npc"]
    )
    return tuple(sorted(w for w in out if w not in public))


def alias_payload(payload: Any, aliases: dict[str, str]) -> Any:
    """``payload`` with every string that IS an aliased id replaced (deep).
    Prose and labels are untouched: only exact id values change."""
    if not aliases:
        return payload
    if isinstance(payload, str):
        return aliases.get(payload, payload)
    if isinstance(payload, list):
        return [alias_payload(v, aliases) for v in payload]
    if isinstance(payload, tuple):
        return tuple(alias_payload(v, aliases) for v in payload)
    if isinstance(payload, dict):
        return {k: alias_payload(v, aliases) for k, v in payload.items()}
    return payload


def unalias_intent(intent: Any, aliases: dict[str, str]) -> Any:
    """Map a parsed intent's ids back from ``person_N`` to contract ids."""
    if not aliases or not isinstance(intent, dict):
        return intent
    back = {alias: cid for cid, alias in aliases.items() if "." not in cid}
    out = dict(intent)
    for key in ("target_entity_ids", "topic_ids"):
        if isinstance(out.get(key), list):
            out[key] = [back.get(v, v) for v in out[key]]
    dialogue = out.get("dialogue")
    if isinstance(dialogue, dict) and dialogue.get("addressee_id") in back:
        out["dialogue"] = {**dialogue, "addressee_id": back[dialogue["addressee_id"]]}
    return out


def roster_text(
    known: KnownState,
    world: WorldContent | None = None,
    aliases: dict[str, str] | None = None,
) -> str:
    """The parser's scene roster: entity ids that exist right now, one line
    each (same shape as the eval harness fixture roster). Includes the
    location's travel connections so typed movement can resolve a
    destination id — the parser never invents ids that are not listed.
    People whose names the player has not learned appear under their alias."""
    aliases = aliases or {}
    scene = known.scene(PC_ID)
    facts = known.chronicle_facts(PC_ID)
    lines = [f"- {scene.location_id}: {scene.name or 'the current location'} "
             "(the place you are standing in)"]
    for e in scene.entities:
        if e.entity_id == PC_ID:
            # The player's character is "you" to the parser: their chosen name
            # is player text and never sits in the roster (claude #5).
            lines.append(f"- {e.entity_id}: you (the player's own character)")
            continue
        detail = e.kind
        if e.conditions:
            detail += ", " + ", ".join(e.conditions)
        lines.append(f"- {aliases.get(e.entity_id, e.entity_id)}: {e.name} ({detail})")
    exits = tuple(getattr(scene, "exits", ()) or ())
    if exits:
        for exit_ in exits:
            lines.append(f"- {exit_.id}: {exit_.name} (a road leads there)")
    elif world is not None:
        here = next(
            (loc for loc in world.locations.values()
             if contract_id(loc.id) == scene.location_id),
            None,
        )
        if here is not None:
            for conn in here.connections:
                dest = world.locations.get(conn.to)
                label = dest.name if dest is not None else conn.to
                lines.append(f"- {contract_id(conn.to)}: {label} (a road leads there)")
    for item, qty in sorted(facts.inventory.items()):
        note = f"x{qty} " if qty != 1 else ""
        lines.append(f"- {item}: {note}in your pack")
    return "\n".join(lines)


def parse_lists(
    known: KnownState,
    world: WorldContent | None = None,
    aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    """The lists the parser's closed fields pick from, one line each: subjects
    the people here could be asked about (``topic_ids``), goods the engine sells
    (``transaction``), and authored laws (``invoked_law_ids``). Topics come from
    the KNOWN view, so hidden subjects and unlearned names never appear, and
    unlearned people carry their alias."""
    aliases = aliases or {}
    topics = "\n".join(
        f"- {aliases.get(t.topic_id, t.topic_id)}: {t.label}" for t in known.topics(PC_ID)
    )
    prices = laws = ""
    if world is not None:
        here = None
        try:
            location_id = known.chronicle_facts(PC_ID).location_id
        except KeyError:
            location_id = None
        if location_id is not None:
            here = next(
                (loc_id for loc_id in world.locations if contract_id(loc_id) == location_id),
                None,
            )
        prices = "\n".join(
            f"- {key}: {world.prices[key]} copper" for key in sold_here(world, here)
        )
        laws = "\n".join(
            f"- {contract_id(law.law_id)}: {law.name}"
            + (f" ({', '.join(law.invoke_phrases)})" if law.invoke_phrases else "")
            for law in world.laws
        )
    return {"topics": topics, "prices": prices, "laws": laws}


def action_slice(intent: dict) -> dict:
    """The parsed-intent slice narrate() takes as its 4th argument."""
    return {
        "action_type": intent.get("action_type"),
        "approach": intent.get("approach"),
        "target_entity_ids": intent.get("target_entity_ids", []),
        "dialogue": intent.get("dialogue"),
    }
