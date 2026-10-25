"""Upcaster registry: (event_type, payload_version) → pure chained upcasters.

projector-version fix (the engine), per synthesis §2.6:

- Rule 1: upcasters are PURE functions with **no engine imports** —
  enforced by the same AST lint pattern as folds
  (``tests/test_upcasters.py``). They transform a stored event row's
  payload from one structural version to the next; they never touch
  dice, rules, clocks, or the DB, and they NEVER mutate the stored row
  (the log is append-only; upcasting happens at read/fold time).
- Rule 3: a structural payload break bumps the type's payload_version
  and registers a chained upcaster here. Rule 4: a MEANING change is a
  new event type name, never a version bump.
- Rule 5: the golden corpus (``tests/golden/golden_events.json``) must
  carry a fixture for every (event_type, payload_version) pair in
  :data:`SHIPPED_PAYLOAD_VERSIONS` — a missing fixture fails the build.

Version history (append-only; document every bump here):

- ``claim_written`` v2: the inner ``claim``
  gains the typed v2 fields — closed ``predicate``, ``value_text`` /
  ``value_num`` / ``value_range``, ``world_valid``,
  ``acquisition_method`` — and the payload gains ``source_agent_id``,
  ``derived_from_claim_id``, ``strength``, ``evidence_world_time``.
  v1 free text maps to the ``observed_statement`` predicate with
  provenance preserved (the original ticket's migration rule).
- ``outcome_resolved`` v2: embedded ``intel`` claim
  dicts carry the same v2 typed fields; ``position`` deltas gain the
  required ``transit_hint`` (v1 rows upcast to ``"unknown"``).
- ``intent_parsed`` v2: the player-authored
  ``intent.approach`` and ``intent.dialogue.quoted_speech`` values may
  be envelope-encrypted (``{"$enc": …}`` markers, see
  ``everquill_engine.crypto``). Structurally a superset of v1 — the
  upcaster is the identity — but readers of v2 must be prepared to
  meet ciphertext where v1 guaranteed plaintext.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CURRENT_PAYLOAD_VERSIONS",
    "SHIPPED_PAYLOAD_VERSIONS",
    "UPCASTERS",
    "UpcastError",
    "upcast",
    "upcast_claim_fields_v1_to_v2",
    "upcast_intel_delta_claim",
    "upcast_position_delta",
]


class UpcastError(ValueError):
    """No registered upcast path from a stored payload_version to current."""


#: v1 free-text ``method`` → closed acquisition_method. This table is a
#: FROZEN COPY of the mapping in ``everquill_engine.claims`` (upcasters
#: may not import engine modules; ``tests/test_upcasters.py`` asserts the
#: two never drift). It is part of shipped history: append, never edit.
_ACQUISITION_FOR_METHOD: dict[str, str] = {
    "witnessed": "observed",
    "misjudged_glance": "observed",
    "survived_attempt": "observed",
    "hard_lesson": "observed",
    "conversation": "told",
    "archive_research": "rumor",
    "rumor": "rumor",
    "appraisal_ii": "observed",
    "source_records": "told",
    "inherited_journal": "inherited_journal",
    "overheard": "overheard",
}

#: Frozen copy of claims.BASE_EVIDENCE_WEIGHT at the v2 bump (same
#: no-engine-imports rule; drift-checked by tests). Used to backfill the
#: cached ``strength`` of upcast v1 claims: one evidence link at its
#: undecayed base weight, exactly what migration 0008 backfills.
_BASE_EVIDENCE_WEIGHT: dict[str, int] = {
    "observed": 100,
    "told": 60,
    "rumor": 35,
    "inherited_journal": 20,
    "overheard": 10,
}

_DEFAULT_ACQUISITION = "told"


def upcast_claim_fields_v1_to_v2(claim: dict[str, Any]) -> dict[str, Any]:
    """v1 free-text claim dict → v2 typed shape (pure, shared by the
    claim_written and outcome_resolved upcasters and mirrored by the
    0008 SQL backfill). Free text maps to ``observed_statement``;
    ``value_or_range`` becomes ``value_text``; provenance fields are
    untouched."""
    if "predicate" in claim:
        return dict(claim)  # already v2 (idempotent — contract normalizers reuse this)
    out = dict(claim)
    out["predicate"] = "observed_statement"
    out["value_text"] = claim.get("value_or_range")
    out["value_num"] = None
    out["value_range"] = None
    out["world_valid"] = None
    out["acquisition_method"] = _ACQUISITION_FOR_METHOD.get(
        claim.get("method", ""), _DEFAULT_ACQUISITION
    )
    out["source_agent_id"] = None
    out.pop("value_or_range", None)
    return out


def upcast_intel_delta_claim(delta: dict[str, Any]) -> dict[str, Any]:
    if delta.get("delta_type") != "intel":
        return delta
    out = dict(delta)
    out["claim"] = upcast_claim_fields_v1_to_v2(dict(delta["claim"]))
    return out


def upcast_position_delta(delta: dict[str, Any]) -> dict[str, Any]:
    if delta.get("delta_type") != "position" or "transit_hint" in delta:
        return delta
    out = dict(delta)
    out["transit_hint"] = "unknown"
    return out


def _claim_written_1_to_2(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["claim"] = upcast_claim_fields_v1_to_v2(dict(payload["claim"]))
    out.setdefault("derived_from_claim_id", None)
    method = out["claim"]["acquisition_method"]
    out.setdefault("strength", _BASE_EVIDENCE_WEIGHT[method])
    return out


def _outcome_resolved_1_to_2(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["state_deltas"] = [
        upcast_position_delta(upcast_intel_delta_claim(dict(d)))
        for d in payload.get("state_deltas", [])
    ]
    return out


def _intent_parsed_1_to_2(payload: dict[str, Any]) -> dict[str, Any]:
    # Structural superset: v1 plaintext is valid v2 (encryption markers
    # are optional). Identity by design — see the module docstring.
    return dict(payload)


#: THE registry: (event_type, from_version) → pure payload transform to
#: from_version + 1. Chains apply until CURRENT_PAYLOAD_VERSIONS is hit.
UPCASTERS: dict[tuple[str, int], Any] = {
    ("claim_written", 1): _claim_written_1_to_2,
    ("outcome_resolved", 1): _outcome_resolved_1_to_2,
    ("intent_parsed", 1): _intent_parsed_1_to_2,
}

#: The payload version every WRITER emits today, per event type.
CURRENT_PAYLOAD_VERSIONS: dict[str, int] = {
    "world_created": 1,
    "entity_committed": 1,
    "character_created": 1,
    "intent_parsed": 2,
    "outcome_resolved": 2,
    "claim_written": 2,
    "claim_corroborated": 1,
    "claim_contested": 1,
    "claim_superseded": 1,
    "claim_retracted": 1,
    "deed_recorded": 1,
    "timer_started": 1,
    "timer_completed": 1,
    "time_advanced": 1,
    "content_manifest": 1,
    "narration_generated": 1,
}

#: Every (event_type, payload_version) pair EVER shipped — the golden
#: corpus must hold a fixture for each (synthesis §2.6 rule 5). Append
#: only; a version is "shipped" the moment a writer can emit it.
SHIPPED_PAYLOAD_VERSIONS: dict[str, tuple[int, ...]] = {
    "world_created": (1,),
    "entity_committed": (1,),
    "character_created": (1,),
    "intent_parsed": (1, 2),
    "outcome_resolved": (1, 2),
    "claim_written": (1, 2),
    "claim_corroborated": (1,),
    "claim_contested": (1,),
    "claim_superseded": (1,),
    "claim_retracted": (1,),
    "deed_recorded": (1,),
    "timer_started": (1,),
    "timer_completed": (1,),
    "time_advanced": (1,),
    "content_manifest": (1,),
    "narration_generated": (1,),
}


def upcast(event_row: dict[str, Any]) -> dict[str, Any]:
    """Upcast one stored event row's payload to the current version.

    Pure; never mutates the input. Rows already at the current version
    pass through unchanged (same object — folds may rely on cheapness).
    Raises :class:`UpcastError` when the chain has a hole.
    """
    event_type = event_row["event_type"]
    current = CURRENT_PAYLOAD_VERSIONS.get(event_type)
    if current is None:
        # Unknown types fall through to fold_event's own unknown-type error.
        return event_row
    version = event_row.get("payload_version", 1)
    if version == current:
        return event_row
    if version > current:
        raise UpcastError(
            f"{event_type} payload_version {version} is NEWER than this engine's "
            f"current {current} — engine too old for this log"
        )
    payload = dict(event_row["payload"])
    while version < current:
        step = UPCASTERS.get((event_type, version))
        if step is None:
            raise UpcastError(
                f"no upcaster registered for ({event_type}, v{version}) — "
                f"cannot reach current v{current}"
            )
        payload = step(payload)
        version += 1
    out = dict(event_row)
    out["payload"] = payload
    out["payload_version"] = version
    return out
