"""Typed intent model — the closed validation boundary for ParsedIntent.

Typed-intent boundary: every intent entering the resolver is
validated into this closed typed model first. The rules mirror
``docs/contracts/intent.schema.json`` v1.3 exactly:

- ``additionalProperties: false`` at every level — unknown keys are
  violations, not passengers (envelope discipline, contracts README).
- All fourteen declared fields are required; absence is ``None`` or ``[]``,
  never a missing key.
- ``target_entity_ids``: snake_case pattern, ``uniqueItems`` (duplicate
  targets rejected HERE; *unknown* targets are rejected by the resolver
  against the scene roster, which the schema cannot see).
- Enum vocabularies (action_type, stat_hint, plausibility_hint,
  duration_hint.mode) are the LOCKED v1.1 sets; v1.3 adds the closed decision
  fields (addressee, speech_act, topic_ids, transaction, invoked_law_ids,
  movement_scope) the resolver reads instead of the free-text ``approach``.

``tests/test_intent.py`` proves acceptance-equivalence against the JSON
Schema file itself (jsonschema validates X ⟺ ``parse_intent`` accepts X)
and that the vocabularies here match the schema's enums, so this module
cannot drift from the contract silently.

This module is pure (no persistence, no I/O beyond none). The resolver
wraps :class:`IntentValidationError` in ``ResolverError`` at its
boundary so callers keep one rejection type.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from everquill_engine.world import APTITUDES

__all__ = [
    "INTENT_SCHEMA_VERSION",
    "ACTION_TYPES",
    "PLAUSIBILITY_HINTS",
    "DURATION_MODES",
    "DURATION_UNTILS",
    "DURATION_UNITS",
    "ADDRESSEES",
    "SPEECH_ACTS",
    "MOVEMENT_SCOPES",
    "TRANSACTION_KINDS",
    "TRANSACTION_MAX_COUNT",
    "IntentValidationError",
    "DurationHint",
    "Dialogue",
    "Transaction",
    "ParsedIntent",
    "parse_intent",
]

#: The contract version this model mirrors (docs/contracts/intent.schema.json).
INTENT_SCHEMA_VERSION = "1.3"

#: intent.schema.json v1.1 action_type enum (locked).
ACTION_TYPES = frozenset(
    {
        "physical",
        "social",
        "movement",
        "observation",
        "research",
        "craft",
        "train",
        "dialogue",
        "rest",
        "meta",
    }
)

PLAUSIBILITY_HINTS = frozenset({"plausible", "dubious", "impossible_in_fiction"})
DURATION_MODES = frozenset({"until_condition", "explicit"})
#: v1.3 closed duration fields: the engine binds these, never the text.
DURATION_UNTILS = frozenset({"dawn", "midday", "dusk", "midnight"})
DURATION_UNITS = frozenset({"minute", "hour", "day"})
DURATION_AMOUNT_MAX = 999

#: v1.3 closed decision fields (null is the absent value for each enum).
ADDRESSEES = frozenset({"room", "person"})
SPEECH_ACTS = frozenset({"question", "introduction", "statement"})
MOVEMENT_SCOPES = frozenset({"here", "away"})
TRANSACTION_KINDS = frozenset({"buy", "give_coin"})
TRANSACTION_MAX_COUNT = 20
_TOPIC_MAX = 3
_LAW_MAX = 2

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_INTENT_KEYS = frozenset(
    {
        "action_type",
        "target_entity_ids",
        "approach",
        "stat_hint",
        "dialogue",
        "plausibility_hint",
        "duration_hint",
        "ambiguity_flags",
        "addressee",
        "speech_act",
        "topic_ids",
        "transaction",
        "invoked_law_ids",
        "movement_scope",
    }
)
_DIALOGUE_KEYS = frozenset({"addressee_id", "quoted_speech"})
_DURATION_KEYS = frozenset({"mode", "text", "until", "amount", "unit"})
_TRANSACTION_KEYS = frozenset({"kind", "price_key", "count"})


class IntentValidationError(ValueError):
    """The raw intent violates intent.schema.json v1.3 (closed model)."""


@dataclass(frozen=True, slots=True)
class DurationHint:
    mode: str  # until_condition | explicit
    text: str  # the player's words, for the narrator; never bound
    until: str | None  # dawn | midday | dusk | midnight (until_condition)
    amount: int | None  # explicit span length
    unit: str | None  # minute | hour | day (explicit)


@dataclass(frozen=True, slots=True)
class Dialogue:
    addressee_id: str | None
    quoted_speech: str | None


@dataclass(frozen=True, slots=True)
class Transaction:
    kind: str  # buy | give_coin
    price_key: str | None  # a world price key for buy; None for give_coin
    count: int  # 1..TRANSACTION_MAX_COUNT


@dataclass(frozen=True, slots=True)
class ParsedIntent:
    """One validated intent. Frozen — the resolver reads, never edits."""

    action_type: str
    target_entity_ids: tuple[str, ...]
    approach: str
    stat_hint: str | None
    dialogue: Dialogue | None
    plausibility_hint: str
    duration_hint: DurationHint | None
    ambiguity_flags: tuple[str, ...]
    addressee: str | None
    speech_act: str | None
    topic_ids: tuple[str, ...]
    transaction: Transaction | None
    invoked_law_ids: tuple[str, ...]
    movement_scope: str | None


def _require_str(value: Any, what: str, *, min_length: int = 1) -> str:
    if not isinstance(value, str) or isinstance(value, bool):
        raise IntentValidationError(f"{what} must be a string")
    if len(value) < min_length:
        raise IntentValidationError(f"{what} must not be empty")
    return value


def _require_id(value: Any, what: str) -> str:
    text = _require_str(value, what)
    if not _ID_RE.match(text):
        raise IntentValidationError(
            f"{what} {text!r} must match ^[a-z][a-z0-9_]*$ (lowercase snake_case)"
        )
    return text


def _parse_dialogue(raw: Any) -> Dialogue | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise IntentValidationError("dialogue must be null or an object")
    unknown = set(raw) - _DIALOGUE_KEYS
    if unknown:
        raise IntentValidationError(
            f"dialogue has unknown keys: {', '.join(sorted(unknown))} "
            "(additionalProperties is false)"
        )
    missing = _DIALOGUE_KEYS - set(raw)
    if missing:
        raise IntentValidationError(
            f"dialogue missing required keys: {', '.join(sorted(missing))}"
        )
    addressee = raw["addressee_id"]
    if addressee is not None:
        addressee = _require_id(addressee, "dialogue.addressee_id")
    speech = raw["quoted_speech"]
    if speech is not None:
        speech = _require_str(speech, "dialogue.quoted_speech")
    return Dialogue(addressee_id=addressee, quoted_speech=speech)


def _parse_duration(raw: Any) -> DurationHint | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise IntentValidationError("duration_hint must be null or an object")
    unknown = set(raw) - _DURATION_KEYS
    if unknown:
        raise IntentValidationError(
            f"duration_hint has unknown keys: {', '.join(sorted(unknown))} "
            "(additionalProperties is false)"
        )
    missing = _DURATION_KEYS - set(raw)
    if missing:
        raise IntentValidationError(
            f"duration_hint missing required keys: {', '.join(sorted(missing))}"
        )
    mode = raw["mode"]
    if mode not in DURATION_MODES:
        raise IntentValidationError(
            f"duration_hint.mode {mode!r} not one of: {', '.join(sorted(DURATION_MODES))}"
        )
    text = _require_str(raw["text"], "duration_hint.text")
    until = _parse_enum_or_null(raw["until"], "duration_hint.until", DURATION_UNTILS)
    unit = _parse_enum_or_null(raw["unit"], "duration_hint.unit", DURATION_UNITS)
    amount = raw["amount"]
    if amount is not None:
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise IntentValidationError("duration_hint.amount must be an integer or null")
        if not 1 <= amount <= DURATION_AMOUNT_MAX:
            raise IntentValidationError(
                f"duration_hint.amount {amount} must be between 1 and {DURATION_AMOUNT_MAX}"
            )
    return DurationHint(mode=mode, text=text, until=until, amount=amount, unit=unit)


def _parse_transaction(raw: Any) -> Transaction | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise IntentValidationError("transaction must be null or an object")
    unknown = set(raw) - _TRANSACTION_KEYS
    if unknown:
        raise IntentValidationError(
            f"transaction has unknown keys: {', '.join(sorted(unknown))} "
            "(additionalProperties is false)"
        )
    missing = _TRANSACTION_KEYS - set(raw)
    if missing:
        raise IntentValidationError(
            f"transaction missing required keys: {', '.join(sorted(missing))}"
        )
    kind = raw["kind"]
    if kind not in TRANSACTION_KINDS:
        raise IntentValidationError(
            f"transaction.kind {kind!r} not one of: {', '.join(sorted(TRANSACTION_KINDS))}"
        )
    price_key = raw["price_key"]
    if price_key is not None:
        price_key = _require_id(price_key, "transaction.price_key")
    count = raw["count"]
    if not isinstance(count, int) or isinstance(count, bool):
        raise IntentValidationError("transaction.count must be an integer")
    if not 1 <= count <= TRANSACTION_MAX_COUNT:
        raise IntentValidationError(
            f"transaction.count {count} must be between 1 and {TRANSACTION_MAX_COUNT}"
        )
    return Transaction(kind=kind, price_key=price_key, count=count)


def _parse_id_list(raw: Any, what: str, max_items: int) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        raise IntentValidationError(f"{what} must be a list")
    if len(raw) > max_items:
        raise IntentValidationError(f"{what} has more than {max_items} entries")
    ids: list[str] = []
    for item in raw:
        value = _require_id(item, f"{what} entry")
        if value in ids:
            raise IntentValidationError(f"duplicate {what} entry {value!r} (uniqueItems)")
        ids.append(value)
    return tuple(ids)


def _parse_enum_or_null(raw: Any, what: str, vocabulary: frozenset[str]) -> str | None:
    if raw is None:
        return None
    if raw not in vocabulary:
        raise IntentValidationError(
            f"{what} {raw!r} not one of: {', '.join(sorted(vocabulary))} or null"
        )
    return raw


def parse_intent(raw: Any) -> ParsedIntent:
    """Validate one raw intent dict into the closed typed model.

    Raises :class:`IntentValidationError` with a precise message on ANY
    deviation from intent.schema.json v1.3 — unknown keys, missing keys,
    wrong types, out-of-vocabulary enums, duplicate targets, malformed
    ids, empty strings.
    """
    if not isinstance(raw, Mapping):
        raise IntentValidationError("intent must be an object")

    unknown = set(raw) - _INTENT_KEYS
    if unknown:
        raise IntentValidationError(
            f"intent has unknown keys: {', '.join(sorted(unknown))} "
            "(additionalProperties is false)"
        )
    missing = _INTENT_KEYS - set(raw)
    if missing:
        raise IntentValidationError(
            f"intent missing required fields: {', '.join(sorted(missing))}"
        )

    action_type = raw["action_type"]
    if action_type not in ACTION_TYPES:
        raise IntentValidationError(
            f"unknown action_type {action_type!r} (locked v1.1 vocabulary)"
        )

    raw_targets = raw["target_entity_ids"]
    if not isinstance(raw_targets, (list, tuple)):
        raise IntentValidationError("target_entity_ids must be a list")
    targets: list[str] = []
    for item in raw_targets:
        target = _require_id(item, "target_entity_ids entry")
        if target in targets:
            raise IntentValidationError(
                f"duplicate target entity id {target!r} (uniqueItems is required)"
            )
        targets.append(target)

    approach = _require_str(raw["approach"], "approach")

    stat_hint = raw["stat_hint"]
    if stat_hint is not None and stat_hint not in APTITUDES:
        raise IntentValidationError(
            f"stat_hint {stat_hint!r} is not in the locked aptitude vocabulary"
        )

    plausibility = raw["plausibility_hint"]
    if plausibility not in PLAUSIBILITY_HINTS:
        raise IntentValidationError(
            f"plausibility_hint {plausibility!r} not one of: "
            f"{', '.join(sorted(PLAUSIBILITY_HINTS))}"
        )

    raw_flags = raw["ambiguity_flags"]
    if not isinstance(raw_flags, (list, tuple)):
        raise IntentValidationError("ambiguity_flags must be a list")
    flags: list[str] = []
    for item in raw_flags:
        flag = _require_id(item, "ambiguity_flags entry")
        if flag in flags:
            raise IntentValidationError(
                f"duplicate ambiguity flag {flag!r} (uniqueItems is required)"
            )
        flags.append(flag)

    return ParsedIntent(
        action_type=action_type,
        target_entity_ids=tuple(targets),
        approach=approach,
        stat_hint=stat_hint,
        dialogue=_parse_dialogue(raw["dialogue"]),
        plausibility_hint=plausibility,
        duration_hint=_parse_duration(raw["duration_hint"]),
        ambiguity_flags=tuple(flags),
        addressee=_parse_enum_or_null(raw["addressee"], "addressee", ADDRESSEES),
        speech_act=_parse_enum_or_null(raw["speech_act"], "speech_act", SPEECH_ACTS),
        topic_ids=_parse_id_list(raw["topic_ids"], "topic_ids", _TOPIC_MAX),
        transaction=_parse_transaction(raw["transaction"]),
        invoked_law_ids=_parse_id_list(raw["invoked_law_ids"], "invoked_law_ids", _LAW_MAX),
        movement_scope=_parse_enum_or_null(
            raw["movement_scope"], "movement_scope", MOVEMENT_SCOPES
        ),
    )
