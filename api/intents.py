"""Intent and command plumbing: schema validation, byte caps, parser clamps,
command-id rules, and probing what a command already did."""

from __future__ import annotations

import json
from typing import Any

import jsonschema
from fastapi import HTTPException

from api import telemetry
from everquill_engine.db import REPO_ROOT
from everquill_engine.store import (
    decrypt_event_payload,
)

COMMAND_ID_MAX_LEN = 128


_COMMAND_ID_ALPHABET = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_.-"
)


#: Canonical-intent byte cap (checked BEFORE schema validation) and
#: request-body byte cap (ASGI middleware, checked before FastAPI parses).
INTENT_MAX_BYTES = 4096


_CONTRACTS_DIR = REPO_ROOT / "docs" / "contracts"


_INTENT_VALIDATOR = jsonschema.Draft202012Validator(
    json.loads((_CONTRACTS_DIR / "intent.schema.json").read_text(encoding="utf-8"))
)


_OUTCOME_VALIDATOR = jsonschema.Draft202012Validator(
    json.loads((_CONTRACTS_DIR / "outcome.schema.json").read_text(encoding="utf-8"))
)


def _intent_errors(intent: Any) -> list[str]:
    errors = sorted(_INTENT_VALIDATOR.iter_errors(intent), key=lambda e: list(e.path))
    out = []
    for err in errors[:5]:
        where = "$" + "".join(f".{p}" if isinstance(p, str) else f"[{p}]" for p in err.path)
        out.append(f"{where}: {err.message}")
    if len(errors) > 5:
        out.append(f"... and {len(errors) - 5} more")
    return out


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _stored_outcome_row(conn, command_id: str) -> dict[str, Any] | None:
    """The committed outcome_resolved row of an absorbed duplicate command
    (event_ulid included so replays serve the same stable external id)."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, payload, event_ulid FROM event
                WHERE event_type = 'outcome_resolved'
                  AND (command_id = %s OR command_id LIKE %s)
                ORDER BY id
                LIMIT 1
                """,
                (command_id, _escape_like(command_id) + "#%"),
            )
            row = cur.fetchone()
    return {"id": row[0], "payload": row[1], "event_ulid": row[2]} if row else None


def _stored_intent(conn, store_command_id: str) -> dict | None:
    """The committed intent_parsed payload of a duplicate command, decrypted
    through the owner read path (encrypted player text markers resolve; plain rows pass
    through). Duplicates answer with the STORED parsed intent."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT payload FROM event
                WHERE event_type = 'intent_parsed'
                  AND (command_id = %s OR command_id LIKE %s)
                ORDER BY id
                LIMIT 1
                """,
                (store_command_id, _escape_like(store_command_id) + "#%"),
            )
            row = cur.fetchone()
            if row is None:
                return None
            payload = decrypt_event_payload(cur, dict(row[0]))
    intent = payload.get("intent")
    return dict(intent) if isinstance(intent, dict) else None


def _probe_command_state(conn, store_command_id: str) -> tuple[str | None, dict | None]:
    """Command state BEFORE any paid parser call: a replayed
    command_id must never buy another parse. Returns one of
    ("committed", None) — canon already holds this command;
    ("pending", row)  — an unexpired <<Proceed?>> beat is stored (row carries
                        the DECRYPTED stored intent + assessment columns);
    ("expired", None) — the pending beat expired (the caller 410s, like beat);
    (None, None)      — fresh command, pay the pipeline."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM event WHERE command_id = %s LIMIT 1",
                (store_command_id,),
            )
            if cur.fetchone() is not None:
                return "committed", None
            cur.execute(
                "SELECT character_id, intent, tier, risk_label, world_minutes_cost,"
                " created_world_time, expires_world_time, status"
                " FROM pending_confirmation WHERE command_id = %s",
                (store_command_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None, None
            if row[7] == "expired":
                return "expired", None
            stored = decrypt_event_payload(cur, {"intent": row[1]})["intent"]
            return "pending", {
                "character_id": row[0],
                "intent": dict(stored) if isinstance(stored, dict) else stored,
                "tier": row[2],
                "risk_label": row[3],
                "world_minutes_cost": row[4],
                "created_world_time": row[5],
                "expires_world_time": row[6],
            }


def _check_intent_bytes(intent: Any) -> None:
    """Small canonical-byte ceiling BEFORE schema validation, so a
    pathological intent never reaches uniqueItems/regex validation work."""
    try:
        size = len(
            json.dumps(intent, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422, detail="intent must be a JSON-serializable object"
        ) from None
    if size > INTENT_MAX_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"intent too large ({size} bytes > {INTENT_MAX_BYTES}-byte "
            "canonical cap)",
        )


def _clamp_parsed_intent(intent: Any, command_id: str, world_id: str) -> Any:
    """Clamp PARSER-produced free-text fields to the schema v1.2 caps. The
    player's own typed turn must not 422 because OUR parser got verbose;
    direct structured intents skip this and get the strict 422 instead."""
    if not isinstance(intent, dict):
        return intent
    clamped: list[str] = []
    approach = intent.get("approach")
    if isinstance(approach, str) and len(approach) > 500:
        intent["approach"] = approach[:500]
        clamped.append("approach")
    dialogue = intent.get("dialogue")
    if isinstance(dialogue, dict):
        quoted = dialogue.get("quoted_speech")
        if isinstance(quoted, str) and len(quoted) > 500:
            dialogue["quoted_speech"] = quoted[:500]
            clamped.append("dialogue.quoted_speech")
    duration = intent.get("duration_hint")
    if isinstance(duration, dict):
        text = duration.get("text")
        if isinstance(text, str) and len(text) > 200:
            duration["text"] = text[:200]
            clamped.append("duration_hint.text")
    if clamped:
        telemetry.emit(
            "parse_clamped", command_id=command_id, world_id=world_id, fields=clamped
        )
    return intent


def _validate_command_id(command_id: Any) -> str:
    if (
        not isinstance(command_id, str)
        or not 1 <= len(command_id) <= COMMAND_ID_MAX_LEN
        or not set(command_id) <= _COMMAND_ID_ALPHABET
    ):
        raise HTTPException(
            status_code=422,
            detail="command_id must be 1-128 chars of [A-Za-z0-9:_.-] and "
            "client-deterministic per action (retries reuse it)",
        )
    return command_id


def _validated_contract(conn, contract: dict[str, Any], command_id: str) -> dict[str, Any]:
    violations = sorted(_OUTCOME_VALIDATOR.iter_errors(contract), key=lambda e: list(e.path))
    if violations:
        telemetry.emit(
            "contract_violation",
            command_id=command_id,
            event_id=contract.get("event_id"),
            errors=[e.message for e in violations[:5]],
        )
        raise HTTPException(
            status_code=500,
            detail="engine outcome failed outcome.schema.json validation — "
            "refusing to serve a non-contract response",
        )
    return contract


def _committed_intent(event_rows, fallback: dict | None) -> dict | None:
    for row in event_rows:
        if row["event_type"] == "intent_parsed":
            return dict(row["payload"].get("intent") or {})
    return fallback
