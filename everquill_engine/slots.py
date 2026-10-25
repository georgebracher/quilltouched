"""Anchor-slot maps + deterministic entity→slot assignment (decision 5).

content authors write ``content/world/slots.yaml`` with the LOCKED format::

    <location_type>:
      slots:
        - {slot_id: tavern_bar, x_pct: 64, y_pct: 72}
        ...

``x_pct``/``y_pct`` are percent of the scene canvas (0..100), the
sprite's bottom-center anchor. Slot ids are snake_case and unique per
location type (content authors keep them globally unique by prefixing the type;
this loader enforces per-type uniqueness only).

The loader TOLERATES the file being absent (content authors write in parallel)
— :func:`load_slot_maps` returns ``{}`` and :func:`assign_slots` falls
back to stable ordering with ``slot_id`` null, so nothing downstream
blocks on content.

Assignment (deterministic, presentation-only — never canon):
entities are taken in sorted id order; each hashes over the CURRENTLY
FREE slots (``sha256('everquill.slots.v1|' + entity_id)`` modulo the
free count). Same scene composition → same arrangement, on any machine.
Entities beyond the slot count get ``None`` (the client renders unslotted).
Coordinates are floats by design: presentation coordinates are the one
sanctioned float domain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from everquill_engine.db import REPO_ROOT

__all__ = [
    "SLOTS_PATH",
    "SlotContentError",
    "Slot",
    "load_slot_maps",
    "assign_slots",
]

SLOTS_PATH = REPO_ROOT / "content" / "world" / "slots.yaml"

_HASH_SCHEME = b"everquill.slots.v1"


class SlotContentError(ValueError):
    """slots.yaml failed validation. Message names the offending key."""


@dataclass(frozen=True, slots=True)
class Slot:
    slot_id: str
    x_pct: float
    y_pct: float


def _need_pct(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SlotContentError(f"{what} must be a number (percent of canvas)")
    if not 0 <= value <= 100:
        raise SlotContentError(f"{what} must be within 0..100, got {value}")
    return float(value)


def load_slot_maps(path: str | Path | None = None) -> dict[str, tuple[Slot, ...]]:
    """Parse slots.yaml → {location_type: (Slot, ...)}. ``{}`` when absent."""
    file_path = Path(path) if path is not None else SLOTS_PATH
    if not file_path.exists():
        return {}
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SlotContentError(f"{file_path}: not valid YAML: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SlotContentError(f"{file_path}: top level must map location types to slot maps")

    maps: dict[str, tuple[Slot, ...]] = {}
    for location_type, body in raw.items():
        where = f"{file_path}: [{location_type}]"
        if not isinstance(location_type, str) or not location_type:
            raise SlotContentError(f"{file_path}: location-type keys must be strings")
        if not isinstance(body, dict) or set(body) != {"slots"}:
            raise SlotContentError(
                f"{where} must be a mapping with exactly one key: 'slots'"
            )
        entries = body["slots"]
        if not isinstance(entries, list) or not entries:
            raise SlotContentError(f"{where} slots must be a non-empty list")
        slots: list[Slot] = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"slot_id", "x_pct", "y_pct"}:
                raise SlotContentError(
                    f"{where} each slot needs exactly slot_id, x_pct, y_pct"
                )
            slot_id = entry["slot_id"]
            if not isinstance(slot_id, str) or not slot_id.replace("_", "a").isalnum() \
                    or not slot_id[0].isalpha() or slot_id != slot_id.lower():
                raise SlotContentError(f"{where} slot_id {slot_id!r} must be snake_case")
            if any(existing.slot_id == slot_id for existing in slots):
                raise SlotContentError(f"{where} duplicate slot_id {slot_id!r}")
            slots.append(
                Slot(
                    slot_id=slot_id,
                    x_pct=_need_pct(entry["x_pct"], f"{where}.{slot_id}.x_pct"),
                    y_pct=_need_pct(entry["y_pct"], f"{where}.{slot_id}.y_pct"),
                )
            )
        maps[location_type] = tuple(slots)
    return maps


def _slot_hash(entity_id: str) -> int:
    digest = hashlib.sha256(_HASH_SCHEME + b"|" + entity_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def assign_slots(
    location_type: str | None,
    slot_maps: dict[str, tuple[Slot, ...]],
    entity_ids: list[str] | tuple[str, ...],
) -> dict[str, Slot | None]:
    """Deterministic entity→slot assignment for one scene.

    Entities are processed in sorted-id order (stable ordering is the
    contract with the client); each takes ``hash(entity_id) % len(free)``
    from the remaining free slots. Missing slot map (file absent, type
    unmapped) or exhausted slots → ``None``.
    """
    ordered = sorted(entity_ids)
    slots = slot_maps.get(location_type or "", ())
    free = list(slots)
    assignment: dict[str, Slot | None] = {}
    for entity_id in ordered:
        if not free:
            assignment[entity_id] = None
            continue
        index = _slot_hash(entity_id) % len(free)
        assignment[entity_id] = free.pop(index)
    return assignment
