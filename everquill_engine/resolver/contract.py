"""Outcome contract rendering: the narrator-facing dict, read back FROM the
committed event row."""

from __future__ import annotations

from typing import Any

from everquill_engine.resolver.common import (
    contract_id,
)
from everquill_engine.upcasters import upcast_intel_delta_claim, upcast_position_delta

# --- outcome contract rendering -------------------------------------------------

_ID_FIELDS: dict[str, tuple[str, ...]] = {
    "hp": ("entity_id",),
    "coin": ("entity_id",),
    "inventory": ("entity_id", "item_id"),
    "flag": ("entity_id",),
    "position": ("entity_id", "from_location_id", "to_location_id"),
    "title": ("entity_id",),
    "clock": ("clock_id",),
    "timer_started": (),
    "death_record": ("entity_id", "location_id"),
}


def _contract_delta(delta: dict[str, Any]) -> dict[str, Any]:
    out = dict(delta)
    kind = out["delta_type"]
    for field_name in _ID_FIELDS.get(kind, ()):
        value = out.get(field_name)
        if isinstance(value, str):
            out[field_name] = contract_id(value)
    if kind == "intel":
        claim = dict(out["claim"])
        claim["subject_entity_id"] = contract_id(claim["subject_entity_id"])
        out["claim"] = claim
    if kind == "deed":
        out["actor_entity_id"] = contract_id(out["actor_entity_id"])
        out["location_id"] = contract_id(out["location_id"])
        out["witness_ids"] = [contract_id(w) for w in out["witness_ids"]]
    if kind == "flag":
        # flag keys embed contract ids already; ensure snake pattern
        out["flag_key"] = out["flag_key"].replace(".", "_")
    return out


def outcome_contract(event_row: dict[str, Any]) -> dict[str, Any]:
    """Render the committed outcome_resolved row as a ResolvedOutcome dict.

    Conforms to docs/contracts/outcome.schema.json v1.2. Always derived
    FROM the stored event — narration can never see an outcome the log
    doesn't already hold. ``event_ulid`` is the STABLE EXTERNAL id;
    ``event_id`` remains the bigint's string form for
    internal correlation (existing consumers parse it as an int). Rows
    fetched through reads that predate the ulid column render
    ``event_ulid: null`` — extend the SELECT to serve it.

    Deltas stored at payload v1 are normalized through the pure v1→v2
    upcasters (typed intel claims, transit_hint) so every served
    contract has one shape regardless of the stored generation.
    """
    payload = event_row["payload"]
    return {
        "event_id": str(event_row["id"]),
        "event_ulid": event_row.get("event_ulid"),
        "tier_resolved": payload["tier_resolved"],
        "risk_label_shown": payload["risk_label_shown"],
        "outcome_tier": payload["outcome_tier"],
        "dice": payload["dice"],
        "state_deltas": [
            _contract_delta(upcast_position_delta(upcast_intel_delta_claim(dict(d))))
            for d in payload["state_deltas"]
        ],
        "narration_constraints": payload["narration_constraints"],
        "system_note": payload.get("system_note"),
        "movement_blocked": bool(payload.get("movement_blocked", False)),
    }
