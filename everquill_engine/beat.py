"""Two-phase commit beat (interface decision 2, the engine).

The engine service surface the API wires ``POST /api/action`` and
``POST /api/action/confirm`` to:

- :func:`assess_or_execute` — ONE call per declared action. Computes
  the tier/risk assessment WITHOUT resolving (no dice, no canon). When
  the engine-owned confirmation table
  (:func:`everquill_engine.resolver.confirmation_required`: Dire-and-up
  risk, SEALED, or a law flagged irreversible) says the action needs
  the full ``<<Proceed?>>`` beat, it stores a pending-confirmation row
  (the parsed intent VERBATIM) and returns the assessment. Otherwise it
  auto-commits (ghost-echo): resolves and appends in the same
  transaction, exactly like ``store.execute_command``.

- :func:`confirm` — resolves a pending action under the ORIGINAL
  command_id with the ORIGINAL stored intent. Expiry is world-activity
  based: the pending beat survives strictly less than
  :data:`PENDING_CONFIRMATION_TTL_MINUTES` (10) world-minutes of
  subsequent world activity; at or past that, confirm marks the row
  expired and raises :class:`ConfirmationExpiredError` ("the moment has
  passed") — it NEVER resolves against stale state. A world where
  nothing happens never expires a beat (expiry is diegetic time, not
  wall clock).

The ``pending_confirmation`` table (migration 0006) is OPERATIONAL
state, not canon: no event exists until the player commits, so an
unconfirmed assessment leaves zero trace in the log (nothing happened),
and the table is deliberately NOT a projection — rebuilds ignore it,
``fresh_reset`` clears it.

Dice honesty: the roll happens at confirm time against then-current
counters — "one dialog per commitment, roll resolves inside it"
(roadmap §3.1). The turn ordinal is likewise computed at resolve time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from everquill_engine import crypto
from everquill_engine.claims import ACTIVE_STATUSES
from everquill_engine.folds import FoldState
from everquill_engine.ladder import PlausibilityTier
from everquill_engine.resolver import (
    Resolution,
    TierDecision,
    confirmation_required,
    decide_tier,
    resolve_intent,
)
from everquill_engine.store import (
    AmbientTransactionError,
    AppendResult,
    ConcurrencyError,
    _AbsorbedDuplicate,
    _append_in_cursor,
    _lock_world,
    _validate_command_id,
)
from everquill_engine.views import RefereeState
from everquill_engine.world import WorldContent

__all__ = [
    "PENDING_CONFIRMATION_TTL_MINUTES",
    "Assessment",
    "BeatResult",
    "NoPendingConfirmationError",
    "ConfirmationExpiredError",
    "BeatIntentMismatchError",
    "canonical_intent_hash",
    "assess_or_execute",
    "confirm",
]

#: World-minutes of subsequent world activity a pending beat survives.
PENDING_CONFIRMATION_TTL_MINUTES = 10


class NoPendingConfirmationError(LookupError):
    """confirm() was called for a command with no pending row and no canon."""


class ConfirmationExpiredError(RuntimeError):
    """The moment has passed: >= 10 world-minutes of activity elapsed
    between assessment and confirmation. The action was never resolved."""


class BeatIntentMismatchError(RuntimeError):
    """A re-assessment reused a pending command_id with a
    DIFFERENT intent than the one bound to it. Confirmation resolves the
    STORED intent, so displaying the retry's intent would let a harmless
    redeclaration front a dangerous confirmed action. The pending row's
    stored (canonical) intent rides on the error so the caller can show
    exactly what will resolve; the API maps this to 409."""

    def __init__(self, message: str, *, stored_intent: dict[str, Any]) -> None:
        super().__init__(message)
        self.stored_intent = stored_intent


def canonical_intent_hash(intent: dict[str, Any]) -> str:
    """sha256 of the canonical-JSON parsed intent (the idempotency binding key).

    Deterministic and order-insensitive at the object level (sort_keys):
    the same declared action hashes identically on every retry, a
    different one does not. Computed over the PLAINTEXT intent both at
    assess time (stored) and on each re-assess (compared), so the stored
    ciphertext never has to be decrypted just to check the binding."""
    canonical = json.dumps(intent, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _claim_subjects(state: FoldState, character_id: str) -> frozenset[str]:
    """Dotted subject ids this character holds LIVE claims about — the
    known-Codex reach research addressability grants."""
    return frozenset(
        row["subject_entity_id"]
        for row in state.claims.values()
        if row["believer_id"] == character_id and row["status"] in ACTIVE_STATUSES
    )


def _target_intel(state: FoldState, character_id: str) -> dict[str, frozenset[str]]:
    """Per-subject predicates this character holds LIVE claims about — the
    target-specific intel the resolver's knowledge gate consults (a held
    `weak_point` unlocks a HOPELESS→DESPERATE physical option).
    Dotted subject id -> {predicate, …}."""
    intel: dict[str, set[str]] = {}
    for row in state.claims.values():
        if row["believer_id"] == character_id and row["status"] in ACTIVE_STATUSES:
            intel.setdefault(row["subject_entity_id"], set()).add(row["predicate"])
    return {subject: frozenset(preds) for subject, preds in intel.items()}


@dataclass(frozen=True, slots=True)
class Assessment:
    """The pre-roll System read of one declared action. KNOWN-safe:
    ladder words and risk words only, never numbers or true stats."""

    command_id: str
    character_id: str
    tier: str                      # plausibility tier, lowercase words
    risk_label: str | None         # pre-roll risk word; None for no-roll shapes
    confirmation_required: bool
    world_minutes_cost: int        # duration preview (commit-beat rule, §3.10)
    created_world_time: int | None    # set when a pending row exists
    expires_world_time: int | None    # created + TTL; None when auto-committed
    summary: str                   # the System dialog line


@dataclass(frozen=True, slots=True)
class BeatResult:
    """What one beat call produced.

    ``status``: ``"pending"`` (confirmation stored, nothing resolved),
    ``"resolved"`` (auto-commit or confirm resolved the action), or
    ``"absorbed"`` (duplicate command — canon already holds it).
    """

    status: str
    assessment: Assessment | None
    append_result: AppendResult | None
    resolution: Resolution | None
    #: For a stored/idempotent pending beat, the CANONICAL intent
    #: bound to this command_id (decrypted). The API returns this — never
    #: the retry's redeclaration — so the displayed intent is always the
    #: one confirmation will resolve. None for resolved/absorbed results.
    stored_intent: dict[str, Any] | None = None


def _assessment_summary(decision: TierDecision, needs_beat: bool) -> str:
    tier_word = decision.tier.name
    if decision.tier is PlausibilityTier.SEALED and decision.law is not None:
        head = f"<<Assessment: SEALED, {decision.law.name}."
    elif decision.risk_label is not None:
        head = f"<<Assessment: {tier_word}, {decision.risk_label.name.capitalize()}."
    else:
        head = f"<<Assessment: {tier_word}."
    summary = head + (" Proceed?>>" if needs_beat else ">>")
    if decision.system_note:
        return f"{summary} {decision.system_note}"
    return summary


def _turn_count(cur, character_id: str) -> int:
    cur.execute(
        "SELECT count(*) FROM event WHERE stream_id = %s AND event_type = %s",
        (f"character:{character_id}", "intent_parsed"),
    )
    return cur.fetchone()[0]


def _command_has_events(cur, command_id: str) -> bool:
    cur.execute("SELECT 1 FROM event WHERE command_id = %s LIMIT 1", (command_id,))
    return cur.fetchone() is not None


def _reject_ambient(conn) -> None:
    import psycopg

    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise AmbientTransactionError(
            "the commit beat owns the top-level transaction but this connection "
            "already has one open — commit/rollback pending work first"
        )


def _resolve_and_append(
    cur,
    command_id: str,
    intent: dict[str, Any],
    referee: RefereeState,
    character_id: str,
    turn: int,
) -> tuple[AppendResult, Resolution]:
    state = referee.fold
    actor = state.characters.get(character_id)
    if actor is None or state.world is None:
        raise ValueError(
            f"world/character {character_id!r} missing — genesis must run before beats"
        )
    resolution = resolve_intent(
        intent=intent,
        actor=actor,
        world=referee.world,
        manifest=state.manifest,
        entity_states=state.entities,
        reputation=state.reputation,
        deeds=state.deeds,
        world_time=state.world["world_time"],
        rng_counters=state.world["rng_counters"],
        seed=state.world["seed"],
        turn=turn,
        actor_claim_subjects=_claim_subjects(state, character_id),
        actor_target_intel=_target_intel(state, character_id),
    )
    result = _append_in_cursor(
        cur, command_id, list(resolution.events), state=state, world_locked=True
    )
    return result, resolution


def assess_or_execute(
    conn,
    command_id: str,
    intent: dict[str, Any],
    *,
    world: WorldContent,
    character_id: str = "pc",
) -> BeatResult:
    """Assess one declared action; auto-commit it unless the engine-owned
    table demands the ``<<Proceed?>>`` beat.

    Idempotent per command_id: a repeat while pending returns the stored
    assessment; a repeat after resolution is absorbed; a repeat after
    expiry raises :class:`ConfirmationExpiredError` (the client declares
    again under a fresh command id).
    """
    _validate_command_id(command_id)
    _reject_ambient(conn)

    attempts = 0
    while True:
        attempts += 1
        try:
            return _assess_once(conn, command_id, intent, world, character_id)
        except _AbsorbedDuplicate:
            return BeatResult("absorbed", None, AppendResult(True, ()), None)
        except ConcurrencyError:
            if attempts >= 2:
                raise


def _assess_once(conn, command_id, intent, world, character_id) -> BeatResult:
    with conn.transaction():
        with conn.cursor() as cur:
            _lock_world(cur)
            if _command_has_events(cur, command_id):
                return BeatResult("absorbed", None, AppendResult(True, ()), None)
            cur.execute(
                "SELECT character_id, tier, risk_label, world_minutes_cost,"
                " created_world_time, expires_world_time, status, intent, intent_hash"
                " FROM pending_confirmation WHERE command_id = %s FOR UPDATE",
                (command_id,),
            )
            row = cur.fetchone()
            if row is not None:
                if row[6] == "expired":
                    raise ConfirmationExpiredError(
                        "The moment has passed. Declare the action again."
                    )
                # A pending row binds this command_id to ONE
                # canonical intent. Decrypt the stored intent for the
                # response and compare hashes: a matching redeclaration is
                # idempotent; a DIFFERENT intent under the same id is a
                # mismatch (the confirm would still resolve the stored one).
                account_key = crypto.load_account_key(cur)
                stored_intent = crypto.decrypt_payload(
                    dict(row[7]), account_key[1] if account_key else None
                )
                stored_hash = row[8]
                if stored_hash is not None and stored_hash != canonical_intent_hash(intent):
                    raise BeatIntentMismatchError(
                        "this command_id was already assessed with a different action; "
                        "confirm the standing assessment or declare again under a fresh id",
                        stored_intent=stored_intent,
                    )
                # pending (confirmed-with-events is caught above): return
                # the stored assessment verbatim — idempotent assess.
                return BeatResult(
                    "pending",
                    Assessment(
                        command_id=command_id,
                        character_id=row[0],
                        tier=row[1],
                        risk_label=row[2],
                        confirmation_required=True,
                        world_minutes_cost=row[3],
                        created_world_time=row[4],
                        expires_world_time=row[5],
                        summary="<<Assessment stands. Proceed?>>",
                    ),
                    None,
                    None,
                    stored_intent=stored_intent,
                )

            referee = RefereeState.load(cur, world)
            state = referee.fold
            actor = state.characters.get(character_id)
            if actor is None or state.world is None:
                raise ValueError(
                    f"world/character {character_id!r} missing — genesis must run "
                    "before beats"
                )
            decision = decide_tier(
                intent=intent,
                actor=actor,
                world=world,
                manifest=state.manifest,
                world_time=state.world["world_time"],
                entity_states=state.entities,
                reputation=state.reputation,
                actor_claim_subjects=_claim_subjects(state, character_id),
                actor_target_intel=_target_intel(state, character_id),
            )
            needs_beat = confirmation_required(decision)
            now = state.world["world_time"]

            if not needs_beat:
                turn = _turn_count(cur, character_id) + 1
                result, resolution = _resolve_and_append(
                    cur,
                    command_id,
                    intent,
                    referee,
                    character_id,
                    turn,
                )
                assessment = Assessment(
                    command_id=command_id,
                    character_id=character_id,
                    tier=decision.tier.name.lower(),
                    risk_label=(
                        decision.risk_label.name.lower()
                        if decision.risk_label is not None
                        else None
                    ),
                    confirmation_required=False,
                    world_minutes_cost=decision.time_cost,
                    created_world_time=None,
                    expires_world_time=None,
                    summary=_assessment_summary(decision, needs_beat=False),
                )
                return BeatResult("resolved", assessment, result, resolution)

            expires = now + PENDING_CONFIRMATION_TTL_MINUTES
            # The stored intent is player-authored text at rest —
            # encrypt it exactly like the intent_parsed event payload
            # would be (same key, same field registry). Confirm decrypts.
            key_id, dek = crypto.ensure_account_key(cur)
            stored_intent = crypto.encrypt_payload_fields(
                {"intent": dict(intent)}, "intent_parsed", dek, key_id
            )["intent"]
            cur.execute(
                """
                INSERT INTO pending_confirmation
                    (command_id, character_id, intent, intent_hash, tier, risk_label,
                     world_minutes_cost, created_world_time, expires_world_time,
                     status)
                VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    command_id,
                    character_id,
                    json.dumps(stored_intent),
                    # Bind the id to the plaintext intent's hash.
                    canonical_intent_hash(intent),
                    decision.tier.name.lower(),
                    decision.risk_label.name.lower() if decision.risk_label is not None else None,
                    decision.time_cost,
                    now,
                    expires,
                ),
            )
            assessment = Assessment(
                command_id=command_id,
                character_id=character_id,
                tier=decision.tier.name.lower(),
                risk_label=(
                    decision.risk_label.name.lower() if decision.risk_label is not None else None
                ),
                confirmation_required=True,
                world_minutes_cost=decision.time_cost,
                created_world_time=now,
                expires_world_time=expires,
                summary=_assessment_summary(decision, needs_beat=True),
            )
            return BeatResult("pending", assessment, None, None, stored_intent=dict(intent))


def confirm(conn, command_id: str, *, world: WorldContent) -> BeatResult:
    """Resolve a pending action under its ORIGINAL command_id and intent.

    Raises :class:`NoPendingConfirmationError` when nothing was ever
    assessed under this id, :class:`ConfirmationExpiredError` when 10+
    world-minutes of activity elapsed (the row is marked expired and NO
    resolution happens — never a stale one). A confirm repeated after
    success is absorbed.
    """
    _validate_command_id(command_id)
    _reject_ambient(conn)

    attempts = 0
    while True:
        attempts += 1
        try:
            return _confirm_once(conn, command_id, world)
        except _AbsorbedDuplicate:
            return BeatResult("absorbed", None, AppendResult(True, ()), None)
        except ConcurrencyError:
            if attempts >= 2:
                raise


def _confirm_once(conn, command_id: str, world: WorldContent) -> BeatResult:
    expired_now = False
    with conn.transaction():
        with conn.cursor() as cur:
            _lock_world(cur)
            if _command_has_events(cur, command_id):
                return BeatResult("absorbed", None, AppendResult(True, ()), None)
            cur.execute(
                "SELECT character_id, intent, expires_world_time, status"
                " FROM pending_confirmation WHERE command_id = %s FOR UPDATE",
                (command_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise NoPendingConfirmationError(
                    f"no pending confirmation for command {command_id!r} — "
                    "assess the action first"
                )
            character_id, stored_intent, expires_world_time, status = row
            if status == "expired":
                raise ConfirmationExpiredError(
                    "The moment has passed. Declare the action again."
                )
            # Encrypted player text owner read path: transparently decrypt the stored
            # intent before resolving — resolve gets the same plaintext
            # the player declared.
            account_key = crypto.load_account_key(cur)
            stored_intent = crypto.decrypt_payload(
                stored_intent, account_key[1] if account_key else None
            )

            referee = RefereeState.load(cur, world)
            state = referee.fold
            if state.world is None:
                raise ValueError("no world in the event store")
            now = state.world["world_time"]
            if now >= expires_world_time:
                cur.execute(
                    "UPDATE pending_confirmation SET status = 'expired'"
                    " WHERE command_id = %s",
                    (command_id,),
                )
                expired_now = True
            else:
                turn = _turn_count(cur, character_id) + 1
                result, resolution = _resolve_and_append(
                    cur, command_id, dict(stored_intent), referee, character_id, turn
                )
                outcome_row = result.event_rows[resolution.outcome_event_index]
                cur.execute(
                    "UPDATE pending_confirmation SET status = 'confirmed',"
                    " confirmed_event_id = %s WHERE command_id = %s",
                    (outcome_row["id"], command_id),
                )
                return BeatResult("resolved", None, result, resolution)
    if expired_now:
        raise ConfirmationExpiredError(
            "The moment has passed. Declare the action again."
        )
    raise AssertionError("unreachable")  # pragma: no cover
