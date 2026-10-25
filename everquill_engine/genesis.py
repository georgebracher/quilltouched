"""Genesis spec builder — ONE authority for what world commit writes.

Shared by the CLI and the test harness (the API's api/bootstrap.py
should migrate to it too) so the genesis shape can never fork between
callers. Pure: builds EventSpecs from loaded world content, no DB.

Sprint-1 review fixes carried here:

- Content drift: genesis includes a ``content_manifest`` event carrying the
  sha256 of the world YAML's raw bytes plus the loader version. On
  world open, the CLI recomputes the hash and hard-refuses on mismatch
  (EVERQUILL_ALLOW_CONTENT_DRIFT=1 bypasses with a loud warning) —
  editing authored truth under the same filename is no longer silent.
- hp-persistence: every damageable entity (kind npc|creature) commits with
  seed ``hp``/``hp_max`` facts in its entity_committed payload, from
  the same rule chargen uses (4 + might, computed HERE at command
  time). Folds seed the entity_state projection from those stored
  facts — never from engine rules or true sheets.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from everquill_engine.events import EventSpec, EventType
from everquill_engine.world import LOADER_VERSION, WorldContent, WorldEntity

__all__ = ["DAMAGEABLE_KINDS", "content_sha256", "entity_seed_hp", "genesis_specs"]

#: Entity kinds that get a mutable entity_state row at world commit.
#: Items/props keep authored true sheets but no mutable hp in v1 — a
#: delta targeting one raises at fold time (reject, never drop).
DAMAGEABLE_KINDS = frozenset({"npc", "creature"})


def content_sha256(source: str | Path) -> str:
    """sha256 hex digest of the world YAML's raw bytes (the canon form)."""
    return hashlib.sha256(Path(source).read_bytes()).hexdigest()


def entity_seed_hp(entity: WorldEntity) -> int:
    """Seed hp/hp_max for a damageable entity: 4 + might (chargen's rule).

    Computed at genesis command time and STORED in the entity_committed
    payload; folds apply the stored value blindly. Server-side only —
    the log never reaches the client.
    """
    return 4 + entity.true_sheet.aptitudes["might"]


def genesis_specs(world: WorldContent, seed: int) -> list[EventSpec]:
    """The complete genesis command: world_created, content_manifest,
    then every location + entity in file order (deterministic)."""
    source_name = Path(world.source).name
    specs: list[EventSpec] = [
        EventSpec(
            stream_id="world",
            event_type=EventType.WORLD_CREATED,
            world_time=0,
            payload={"seed": seed, "content_source": source_name},
        ),
        EventSpec(
            stream_id="world",
            event_type=EventType.CONTENT_MANIFEST,
            world_time=0,
            payload={
                "content_source": source_name,
                "sha256": content_sha256(world.source),
                "loader_version": LOADER_VERSION,
            },
        ),
    ]
    for location in world.locations.values():  # file order (dict preserves insertion)
        specs.append(
            EventSpec(
                stream_id="world",
                event_type=EventType.ENTITY_COMMITTED,
                world_time=0,
                location_id=location.id,
                payload={
                    "entity_id": location.id,
                    "entity_class": "location",
                    "origin": "authored",
                    "name": location.name,
                    "location_id": None,
                    "region": location.region,
                    "common_knowledge": [],
                    "portrait": None,
                },
            )
        )
    for entity in world.entities.values():
        payload = {
            "entity_id": entity.id,
            "entity_class": entity.kind,
            "origin": "authored",
            "name": entity.name,
            "location_id": entity.location,
            "region": world.locations[entity.location].region,
            "descriptor": entity.descriptor,
            "common_knowledge": list(entity.common_knowledge),
            "portrait": entity.portrait,
        }
        if entity.kind in DAMAGEABLE_KINDS:
            hp = entity_seed_hp(entity)
            payload["hp"] = hp
            payload["hp_max"] = hp
        specs.append(
            EventSpec(
                stream_id="world",
                event_type=EventType.ENTITY_COMMITTED,
                world_time=0,
                location_id=entity.location,
                payload=payload,
            )
        )
    return specs
