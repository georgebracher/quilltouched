"""Event store + Tier-1 projector. psycopg3 only.

THE orchestration entry point is :func:`execute_command`: one command →
ONE top-level transaction that (a) locks the world_state row FOR
UPDATE, (b) loads the Tier-1 projection state under that lock, (c)
calls the caller's pure ``resolve_fn(state)`` for the EventSpecs, (d)
appends them with client-computed stream versions (optimistic
concurrency via UNIQUE(stream_id, stream_version)) plus every Tier-1
projection update, and commits. On :class:`ConcurrencyError` it reloads
and re-resolves ONCE under the same command_id. It refuses to run
inside an ambient transaction (no savepoint surprises — ambient-transaction).

:func:`append_command` is the lower-level append for callers that
already hold resolved specs (genesis builders, timer fires, tests). It
still takes the world lock before its fold-state load so Tier-1 world
writes are serialized, but freshness of the specs themselves
is the caller's problem — resolution-bearing paths must use
:func:`execute_command`.

Command identity: every event of a command stores the RAW
command_id plus its 0-based ``event_ordinal``; UNIQUE(command_id,
event_ordinal) replaces the old '<command_id>#<n>' suffix aliasing.
'#' is rejected in command ids so legacy suffixed rows can never
collide with new appends. Command ids stay client-deterministic
(replayable scripts); the CLI namespaces turn ids by world seed
(its world-generation component) and ``fresh_reset`` clears the
namespace with the log — see cli.py.

Idempotency: a duplicate command (retry, replayed script) is detected
by one probe on command_id and absorbed silently — the caller gets
``AppendResult(absorbed=True)`` and no state changes. A concurrent
duplicate loses the UNIQUE race and is also absorbed.

Domain-id uniqueness: duplicate claim_ids / timer_keys are
rejected at append time (pre-commit probe inside the transaction) and
the folds themselves raise on duplicates, so live projection and
rebuild can never disagree silently.

Rebuild (:func:`rebuild_projections`): SHADOW rebuild — fold
every event in id order into ``<table>__shadow`` copies, diff canonical
dumps against live, atomically swap, restore grants/FKs, stamp
``projection_checkpoint.projector_version``. Never truncate-in-place
over a live read model. Every append verifies persisted projector
versions against ``folds.PROJECTOR_VERSIONS`` first.

Claim lifecycle: the append transaction runs the write-time
corroboration/contradiction probe (see :func:`_claim_lifecycle_pass`)
and stamps its verdicts as claim_* events in the same command.

Crypto-shredding: player-authored payload fields are encrypted
on the INSERTED rows (``everquill_engine.crypto``); AppendResult rows
keep plaintext for the owner's own turn. Owner reads of stored payloads
go through :func:`decrypt_event_payload`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from everquill_engine import __version__ as ENGINE_VERSION
from everquill_engine import claims as claims_mod
from everquill_engine import crypto
from everquill_engine.events import EventSpec, EventType, narration_spec
from everquill_engine.folds import PROJECTOR_VERSIONS, FoldState, fold_event
from everquill_engine.upcasters import upcast_claim_fields_v1_to_v2

__all__ = [
    "AppendResult",
    "ConcurrencyError",
    "AmbientTransactionError",
    "DuplicateDomainIdError",
    "ProjectorVersionError",
    "execute_command",
    "append_command",
    "narrate_outcome",
    "public_turn",
    "recent_public_turns",
    "load_fold_state",
    "rebuild_projections",
    "due_timers",
    "stored_content_manifest",
    "canonical_event_dump",
    "canonical_projection_dump",
    "decrypt_event_payload",
    "event_ulid",
    "fresh_reset",
    "PROJECTION_TABLES",
]

PROJECTION_TABLES = (
    "world_state",
    "character_sheet",
    "entity_state",
    "claim",
    "claim_evidence",
    "scene_manifest",
    "timer",
    "reputation",
    "deeds",
)

#: Stamped on every event, so a log shows which rules wrote it (audit claude-012).
#: sprint1.v1: July 2026, the engine still read some decisions from free text.
#: 2026-10-25.closed-fields: every decision from a closed intent field (schema v1.3).
RULESET_VERSION = "2026-10-25.closed-fields"

_EVENT_COLUMNS = (
    "id, stream_id, stream_version, world_time, event_type, "
    "location_id, command_id, event_ordinal, rng, payload, payload_version, meta, "
    "event_ulid, stream_type"
)

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


def event_ulid(world_time: int, stream_id: str, stream_version: int) -> str:
    """The stable EXTERNAL event id, derived DETERMINISTICALLY:
    Crockford base32 of 48 bits of world-time milliseconds || 80 bits of
    md5 over the unique (stream_id, stream_version) pair. Identical
    (seed, script) runs therefore produce byte-identical logs while
    UNIQUE(stream_id, stream_version) + the event_ulid unique index
    guarantee uniqueness. MUST stay in lockstep with the plpgsql
    backfill in migrations/0009 (tests assert agreement)."""
    time_ms = (world_time * 60000) % (1 << 48)
    digest = hashlib.md5(
        f"everquill.event_ulid.{stream_id}:{stream_version}".encode()
    ).digest()[:10]
    n = (time_ms << 80) | int.from_bytes(digest, "big")
    chars = []
    for _ in range(26):
        chars.append(_ULID_ALPHABET[n & 31])
        n >>= 5
    return "".join(reversed(chars))


def _stream_type(stream_id: str) -> str:
    return stream_id.split(":", 1)[0]


class ConcurrencyError(RuntimeError):
    """A concurrent writer advanced a stream first; retry against new state."""


class AmbientTransactionError(RuntimeError):
    """execute_command was called with a transaction already open on the
    connection — it would silently become a savepoint. Commit/rollback
    reads first."""


class DuplicateDomainIdError(ValueError):
    """A claim_id / timer_key in this command already exists. Domain ids
    are canonical and unique forever."""


class ProjectorVersionError(RuntimeError):
    """The database's persisted projector_version disagrees with this
    engine's fold logic (folds.PROJECTOR_VERSIONS). Appending would mix
    two fold generations in one projection — run rebuild_projections()."""


@dataclass(frozen=True, slots=True)
class AppendResult:
    absorbed: bool
    event_rows: tuple[dict[str, Any], ...]  # stored rows (plain dicts), empty when absorbed


def _row_to_dict(row: tuple) -> dict[str, Any]:
    keys = [k.strip() for k in _EVENT_COLUMNS.split(",")]
    return dict(zip(keys, row, strict=True))


def _substitute_event_refs(value: Any, inserted_ids: list[int]) -> Any:
    """Replace event_ref placeholders with the real ids of earlier inserts."""
    if isinstance(value, dict):
        if set(value.keys()) == {"$event_ref"}:
            index = value["$event_ref"]
            if index >= len(inserted_ids):
                raise ValueError(
                    f"event_ref({index}) points at an event not yet inserted "
                    f"({len(inserted_ids)} inserted) — order specs so refs point backwards"
                )
            return inserted_ids[index]
        return {k: _substitute_event_refs(v, inserted_ids) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_event_refs(v, inserted_ids) for v in value]
    return value


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _validate_command_id(command_id: str) -> None:
    if not command_id or not isinstance(command_id, str):
        raise ValueError("command_id must be a non-empty string")
    if "#" in command_id:
        raise ValueError(
            f"command_id {command_id!r} contains '#' — reserved by the retired "
            "sibling-suffix encoding (MEDIUM-2); event_ordinal is a real column now"
        )


def _lock_world(cur) -> None:
    """Serialize Tier-1 world writes: take the world_state row lock BEFORE
    reading fold state. RNG counters and the world clock then
    advance under the lock — folds merge against a fresh image, so the
    write-back can never clobber a concurrent writer's advance. Genesis
    (no row yet) locks nothing; concurrent geneses are settled by the
    UNIQUE command_id on 'genesis'."""
    cur.execute("SELECT singleton FROM world_state FOR UPDATE")


def execute_command(conn, command_id: str, resolve_fn):
    """THE orchestration path: lock → load → resolve → append → commit.

    ``resolve_fn(state)`` receives the freshly-loaded :class:`FoldState`
    (read under the world lock) and returns the command's EventSpecs.
    On ConcurrencyError the whole transaction rolls back and resolve_fn
    is re-run ONCE against reloaded state under the SAME command_id.
    Raises :class:`AmbientTransactionError` when the connection already
    has a transaction open (detected via connection.info
    .transaction_status) — the top-level transaction must be ours.
    """
    import psycopg

    _validate_command_id(command_id)
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise AmbientTransactionError(
            "execute_command owns the top-level transaction but this connection "
            "already has one open — commit/rollback pending work first"
        )

    attempts = 0
    while True:
        attempts += 1
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    _lock_world(cur)
                    cur.execute(
                        "SELECT 1 FROM event WHERE command_id = %s LIMIT 1", (command_id,)
                    )
                    if cur.fetchone() is not None:
                        return AppendResult(absorbed=True, event_rows=())
                    state = load_fold_state(cur)
                    specs = list(resolve_fn(state))
                    if not specs:
                        raise ValueError("resolve_fn must return at least one EventSpec")
                    return _append_in_cursor(
                        cur, command_id, specs, state=state, world_locked=True
                    )
        except _AbsorbedDuplicate:
            return AppendResult(absorbed=True, event_rows=())
        except ConcurrencyError:
            if attempts >= 2:
                raise


def append_command(conn, command_id: str, specs: list[EventSpec] | tuple[EventSpec, ...]):
    """Append one command's PRE-RESOLVED events + Tier-1 projections in
    ONE transaction (still takes the world lock before folding).

    Duplicate command_ids (sequential or concurrent) are absorbed: the
    transaction rolls back cleanly and ``AppendResult(absorbed=True)``
    comes back with no state change.

    Use :func:`execute_command` for anything that resolves against
    state — this function cannot know the specs are fresh. NOTE: unlike
    execute_command this does not reject ambient transactions (the API's
    API bootstrap still reads-then-appends on one connection); inside
    one, its transaction degrades to a savepoint.
    """
    _validate_command_id(command_id)
    if not specs:
        raise ValueError("a command must append at least one event")
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                return _append_in_cursor(cur, command_id, list(specs))
    except _AbsorbedDuplicate:
        return AppendResult(absorbed=True, event_rows=())


def _check_domain_ids(cur, specs: list[EventSpec]) -> None:
    """Pre-commit probe: duplicate claim_id / timer_key — in this
    batch or already projected — rejects the whole command."""
    claim_ids = [
        spec.payload["claim_id"] for spec in specs if str(spec.event_type) == "claim_written"
    ]
    timer_keys = [
        spec.payload["timer_key"] for spec in specs if str(spec.event_type) == "timer_started"
    ]
    if len(claim_ids) != len(set(claim_ids)):
        raise DuplicateDomainIdError(f"command repeats claim_id(s) within itself: {claim_ids}")
    if len(timer_keys) != len(set(timer_keys)):
        raise DuplicateDomainIdError(f"command repeats timer_key(s) within itself: {timer_keys}")
    if claim_ids:
        cur.execute("SELECT claim_id FROM claim WHERE claim_id = ANY(%s)", (claim_ids,))
        clashes = [r[0] for r in cur.fetchall()]
        if clashes:
            raise DuplicateDomainIdError(f"claim_id(s) already exist: {clashes}")
    if timer_keys:
        cur.execute("SELECT timer_key FROM timer WHERE timer_key = ANY(%s)", (timer_keys,))
        clashes = [r[0] for r in cur.fetchall()]
        if clashes:
            raise DuplicateDomainIdError(f"timer_key(s) already exist: {clashes}")


def _verify_projector_versions(cur) -> None:
    """Gate: the persisted projector_version of every projection
    must equal this engine's fold logic before we write another row."""
    cur.execute("SELECT projection_name, projector_version FROM projection_checkpoint")
    stored = dict(cur.fetchall())
    mismatched = {
        name: (stored.get(name), version)
        for name, version in PROJECTOR_VERSIONS.items()
        if stored.get(name) != version
    }
    if mismatched:
        raise ProjectorVersionError(
            "projection_checkpoint disagrees with folds.PROJECTOR_VERSIONS "
            f"({{name: (db, code)}} = {mismatched}) — run "
            "everquill_engine.store.rebuild_projections() before appending"
        )


def _claim_lifecycle_pass(
    state: FoldState, specs: list[EventSpec]
) -> list[EventSpec]:
    """The write-time contradiction/corroboration probe (synthesis §2.3),
    run inside the append transaction against the preloaded claim image
    (the believer+subject+predicate key the claim_active_key index
    serves). Deterministic; the decisions are stamped into lifecycle
    EVENTS so folds — live and rebuild — just apply facts.

    - A claim matching an existing live claim's value becomes a
      claim_corroborated event IN PLACE of its claim_written (evidence
      link attached to the existing claim; new row dropped). Status
      flips to corroborated only when the evidence now spans >= 2
      DISTINCT provenance roots — one deed retold three times raises
      strength, never corroboration (the echo-chamber rule).
    - A conflicting value on an exclusive predicate emits
      claim_contested / claim_superseded events after the new
      claim_written (both-active contest, or outweighed supersede).
    """
    live_evidence: dict[str, list[dict[str, Any]]] = {}
    for (claim_id, _), link in state.claim_evidence.items():
        live_evidence.setdefault(claim_id, []).append(link)

    # In-batch image: claims this command has already decided to insert
    # (their founding evidence links included, event_ref roots made
    # comparable), so two claims in one command see each other.
    batch_claims: list[dict[str, Any]] = []
    out: list[EventSpec] = []
    for spec in specs:
        if str(spec.event_type) != "claim_written":
            out.append(spec)
            continue
        payload = dict(spec.payload)
        # v1-shaped specs (legacy writers, replayed scripts) probe through
        # the same v1→v2 view the fold-time upcaster applies; the stored
        # event keeps its own version.
        claim = upcast_claim_fields_v1_to_v2(dict(payload["claim"]))
        if "strength" not in payload:
            payload["strength"] = claims_mod.BASE_EVIDENCE_WEIGHT[
                claim["acquisition_method"]
            ]
        key = (payload["believer_id"], claim["subject_entity_id"], claim["predicate"])
        new_fields = {
            "claim_id": payload["claim_id"],
            "predicate": claim["predicate"],
            "value_text": claim.get("value_text"),
            "value_num": claim.get("value_num"),
            "value_range": claim.get("value_range"),
            "world_valid": claim.get("world_valid"),
            "claim_text": claim["claim_text"],
            "acquisition_method": claim["acquisition_method"],
        }
        existing = sorted(
            (
                row
                for row in list(state.claims.values()) + batch_claims
                if (row["believer_id"], row["subject_entity_id"], row["predicate"]) == key
                and row["status"] in claims_mod.ACTIVE_STATUSES
            ),
            key=lambda row: row["claim_id"],
        )
        strengths = {
            row["claim_id"]: claims_mod.evidence_strength(
                live_evidence.get(row["claim_id"], []), spec.world_time
            )
            or row["strength"]
            for row in existing
        }
        actions = claims_mod.revise(
            new_claim=new_fields,
            new_strength=payload["strength"],
            existing=existing,
            existing_strength=strengths,
        )

        corroborate = next((a for a in actions if a.kind == "corroborate"), None)
        if corroborate is not None:
            target = corroborate.claim_id
            links = live_evidence.get(target, [])
            new_link = {
                "root_event_id": payload["provenance_root_event_id"],
                "base_weight": payload["strength"],
                "world_time": spec.world_time,
            }
            target_row = state.claims.get(target) or next(
                row for row in batch_claims if row["claim_id"] == target
            )
            status = claims_mod.corroboration_status(
                links + [_comparable_link(new_link)]
            )
            if target_row["status"] == "contested":
                status = "contested"  # evidence raises strength, not verdicts
            strength = claims_mod.evidence_strength(links, spec.world_time) + payload[
                "strength"
            ]
            out.append(
                EventSpec(
                    stream_id=spec.stream_id,
                    event_type=EventType.CLAIM_CORROBORATED,
                    world_time=spec.world_time,
                    location_id=spec.location_id,
                    payload={
                        "claim_id": target,
                        "believer_id": payload["believer_id"],
                        "evidence": {
                            # event_id null = "this event's own id" (the
                            # fold substitutes the envelope id).
                            "event_id": None,
                            "root_event_id": payload["provenance_root_event_id"],
                            "acquisition_method": claim["acquisition_method"],
                            "base_weight": payload["strength"],
                            "world_time": spec.world_time,
                        },
                        "strength": strength,
                        "status": status,
                    },
                )
            )
            continue

        out.append(spec)  # the insert stands
        batch_claims.append(
            {
                **new_fields,
                "believer_id": payload["believer_id"],
                "subject_entity_id": claim["subject_entity_id"],
                "status": "asserted",
                "strength": payload["strength"],
            }
        )
        live_evidence.setdefault(payload["claim_id"], []).append(
            _comparable_link(
                {
                    "root_event_id": payload["provenance_root_event_id"],
                    "base_weight": payload["strength"],
                    "world_time": spec.world_time,
                }
            )
        )
        for action in actions:
            if action.kind == "insert":
                continue
            if action.kind == "supersede":
                out.append(
                    EventSpec(
                        stream_id=spec.stream_id,
                        event_type=EventType.CLAIM_SUPERSEDED,
                        world_time=spec.world_time,
                        location_id=spec.location_id,
                        payload={
                            "claim_id": action.claim_id,
                            "superseded_by_claim_id": action.other_claim_id,
                            "superseded_reason": action.reason,
                        },
                    )
                )
            elif action.kind == "contest":
                out.append(
                    EventSpec(
                        stream_id=spec.stream_id,
                        event_type=EventType.CLAIM_CONTESTED,
                        world_time=spec.world_time,
                        location_id=spec.location_id,
                        payload={
                            "claim_id": action.claim_id,
                            "contested_by_claim_id": action.other_claim_id,
                        },
                    )
                )
    return out


def _comparable_link(link: dict[str, Any]) -> dict[str, Any]:
    """An unresolved event_ref root is a NEW event by construction —
    representable as a root no stored link can equal."""
    root = link["root_event_id"]
    if isinstance(root, dict):  # {"$event_ref": n} — resolves to a fresh id
        return {**link, "root_event_id": ("$new", json.dumps(root, sort_keys=True))}
    return link


def _append_in_cursor(
    cur,
    command_id: str,
    specs: list[EventSpec],
    *,
    state: FoldState | None = None,
    world_locked: bool = False,
):
    """Insert one command's events + fold Tier-1 projections. Runs inside
    the caller's transaction; raises to roll the whole command back."""
    import psycopg

    if not world_locked:
        _lock_world(cur)

    # Idempotency probe (duplicate absorbed, no writes).
    cur.execute("SELECT 1 FROM event WHERE command_id = %s LIMIT 1", (command_id,))
    if cur.fetchone() is not None:
        return AppendResult(absorbed=True, event_rows=())

    _verify_projector_versions(cur)

    # Tier-1 fold base, read under the world lock BEFORE any insert. The
    # claim-lifecycle pass consults it; folding after insert uses it too.
    if state is None:
        state = load_fold_state(cur)

    specs = _claim_lifecycle_pass(state, specs)
    _check_domain_ids(cur, specs)

    # Player-authored text is encrypted at append. The key is
    # ensured lazily (one singleton row per account world); the INSERTED
    # payload carries ciphertext while the rows handed back to the caller
    # (the owner's own turn) keep plaintext.
    account_key: tuple[str, bytes] | None = None
    if any(str(spec.event_type) in crypto.PLAYER_TEXT_PATHS for spec in specs):
        account_key = crypto.ensure_account_key(cur)

    # Client-side next stream versions for optimistic concurrency.
    streams = sorted({spec.stream_id for spec in specs})
    next_version: dict[str, int] = {}
    for stream_id in streams:
        cur.execute(
            "SELECT coalesce(max(stream_version), 0) FROM event WHERE stream_id = %s",
            (stream_id,),
        )
        next_version[stream_id] = cur.fetchone()[0] + 1

    base_meta = {"engine_version": ENGINE_VERSION, "ruleset_version": RULESET_VERSION}
    inserted_ids: list[int] = []
    rows: list[dict[str, Any]] = []
    try:
        for ordinal, spec in enumerate(specs):
            payload = _substitute_event_refs(
                json.loads(json.dumps(dict(spec.payload))), inserted_ids
            )
            event_type = str(spec.event_type)
            stored_payload = payload
            if account_key is not None and event_type in crypto.PLAYER_TEXT_PATHS:
                key_id, dek = account_key
                stored_payload = crypto.encrypt_payload_fields(
                    payload, event_type, dek, key_id
                )
            version = next_version[spec.stream_id]
            next_version[spec.stream_id] = version + 1
            ulid = event_ulid(spec.world_time, spec.stream_id, version)
            meta = dict(base_meta)
            if spec.meta:
                meta.update(dict(spec.meta))
            cur.execute(
                """
                INSERT INTO event
                    (stream_id, stream_version, world_time, event_type,
                     location_id, command_id, event_ordinal, rng, payload,
                     payload_version, meta, event_ulid, stream_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    spec.stream_id,
                    version,
                    spec.world_time,
                    event_type,
                    spec.location_id,
                    command_id,
                    ordinal,
                    _jsonb(dict(spec.rng)) if spec.rng is not None else None,
                    _jsonb(stored_payload),
                    spec.payload_version,
                    _jsonb(meta),
                    ulid,
                    _stream_type(spec.stream_id),
                ),
            )
            event_id = cur.fetchone()[0]
            inserted_ids.append(event_id)
            rows.append(
                {
                    "id": event_id,
                    "stream_id": spec.stream_id,
                    "stream_version": version,
                    "world_time": spec.world_time,
                    "event_type": event_type,
                    "location_id": spec.location_id,
                    "command_id": command_id,
                    "event_ordinal": ordinal,
                    "rng": dict(spec.rng) if spec.rng is not None else None,
                    "payload": payload,
                    "payload_version": spec.payload_version,
                    "meta": meta,
                    "event_ulid": ulid,
                    "stream_type": _stream_type(spec.stream_id),
                }
            )
    except psycopg.errors.UniqueViolation as exc:
        constraint = exc.diag.constraint_name or ""
        if "command_id" in constraint:
            # Concurrent duplicate: absorbed (transaction rolls back).
            raise _AbsorbedDuplicate() from exc
        if "rng" in constraint:
            # Canonical uniqueness: a (stream, index) draw was
            # committed twice — a stale retry reusing a counter. This is
            # a caller bug, never a retryable race.
            raise ValueError(
                "duplicate rng draw: this command re-commits a (stream, index) "
                "pair already in the log — stale resolution must be re-run "
                "against fresh counters (event_rng_stream_index_key)"
            ) from exc
        raise ConcurrencyError(
            "another writer advanced a stream in this command; retry"
        ) from exc

    # Tier-1 projections, same transaction, same folds as rebuild. Folds
    # run over the PLAINTEXT rows (identical projections either way — no
    # projection reads an encrypted field; the rebuild path folds the
    # stored ciphertext rows and the equivalence tests prove it).
    for row in rows:
        fold_event(state, row)
    _write_dirty(cur, state)

    return AppendResult(absorbed=False, event_rows=tuple(rows))


def narrate_outcome(
    conn,
    *,
    character_id: str,
    outcome_event_id: int,
    outcome_event_ulid: str,
    world_time: int,
    prose: str,
    assembler_version: str,
    content_hash: str,
    location_id: str | None = None,
    model: str | None = None,
    turn_command_id: str | None = None,
    public_outcome: dict[str, Any] | None = None,
) -> AppendResult:
    """Append the ``narration_generated`` event binding THIS prose to
    its committed outcome (closes the API decision-3). THE store entry point
    the API calls AFTER an outcome command commits — the outcome id/ulid must
    already be canon.

    Idempotent by command_id ``narrate:<outcome_event_ulid>`` (the ulid is the
    stable external id, byte-identical on replay): a re-narration of the same
    outcome is absorbed, so a retrying API is safe and prose can never fork on
    one outcome. The fold is audit-only (no projection) — the log itself is the
    canon record that this assembler_version over this content_hash narrated
    that outcome. Prose is model output, NOT player text, so it is not
    encrypted. Returns the AppendResult (``absorbed=True`` if already narrated).

    CANONICAL PUBLIC-TURN RECORD (Hardening Pass 1): pass
    ``turn_command_id`` (the original turn command's id) + ``public_outcome``
    (the redacted :func:`everquill_engine.views.outcome_public` contract) and
    this event becomes the ONE authoritative player-visible record for the
    turn — read it back with :func:`public_turn` / :func:`recent_public_turns`.
    Because the narrate command is idempotent, the record survives response
    loss: a retry after prose was committed returns the SAME record.
    """
    spec = narration_spec(
        character_id=character_id,
        outcome_event_id=outcome_event_id,
        outcome_event_ulid=outcome_event_ulid,
        world_time=world_time,
        prose=prose,
        assembler_version=assembler_version,
        content_hash=content_hash,
        location_id=location_id,
        model=model,
        turn_command_id=turn_command_id,
        public_outcome=public_outcome,
    )
    return append_command(conn, f"narrate:{outcome_event_ulid}", [spec])


def _public_turn_record(row: tuple) -> dict[str, Any]:
    """Assemble ONE canonical public-turn record from a stored
    ``narration_generated`` row (id, world_time, payload)."""
    narration_id, world_time, payload = row
    payload = dict(payload)
    return {
        "turn_command_id": payload.get("turn_command_id"),
        "character_id": payload.get("character_id"),
        "outcome_event_id": payload.get("outcome_event_id"),
        "outcome_event_ulid": payload.get("outcome_event_ulid"),
        "world_time": world_time,
        "public_outcome": payload.get("public_outcome"),
        "prose": payload.get("prose"),
        "assembler_version": payload.get("assembler_version"),
        "content_hash": payload.get("content_hash"),
        "model": payload.get("model"),
        "narration_event_id": narration_id,
    }


def public_turn(conn, command_id: str) -> dict[str, Any] | None:
    """THE canonical player-visible record for a turn, keyed by the TURN's
    command_id. Persisted at narration commit as the
    ``narration_generated`` payload — redacted public outcome + prose +
    assembler meta — this serves it verbatim for the first response, a
    duplicate/retry (identical record, NEVER a re-resolved outcome), and a
    Chronicle rebuild. ``None`` until the turn has been narrated. Reads
    canon; a projection rebuild does not change what it returns."""
    # A transaction block, not a bare cursor: an implicit transaction left
    # open here would make the caller's next execute_command refuse.
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT id, world_time, payload FROM event"
            " WHERE event_type = 'narration_generated'"
            "   AND payload->>'turn_command_id' = %s"
            " ORDER BY id LIMIT 1",
            (command_id,),
        )
        row = cur.fetchone()
    return _public_turn_record(row) if row is not None else None


def recent_public_turns(
    conn, character_id: str, n: int, since: int | None = None
) -> list[dict[str, Any]]:
    """The character's public-turn records for a Chronicle reconnect/rebuild
    (public-turn record client half; backs the API's GET /api/turns), at most
    ``n``, oldest first so the client renders top-to-bottom without re-sorting.

    Without ``since``: the newest ``n``. With ``since`` (a narration event id
    watermark): the OLDEST ``n`` strictly after it, so a caller pages forward
    until a short page. Filtering after the limit would drop every turn
    between the watermark and the newest ``n`` (audit 2026-10-24, k3 F1)."""
    if n <= 0:
        return []
    stream_id = f"character:{character_id}"
    with conn.transaction(), conn.cursor() as cur:
        if since is None:
            cur.execute(
                "SELECT id, world_time, payload FROM event"
                " WHERE event_type = 'narration_generated' AND stream_id = %s"
                " ORDER BY id DESC LIMIT %s",
                (stream_id, n),
            )
            rows = list(reversed(cur.fetchall()))
        else:
            cur.execute(
                "SELECT id, world_time, payload FROM event"
                " WHERE event_type = 'narration_generated' AND stream_id = %s AND id > %s"
                " ORDER BY id ASC LIMIT %s",
                (stream_id, since, n),
            )
            rows = cur.fetchall()
    return [_public_turn_record(r) for r in rows]


class _AbsorbedDuplicate(Exception):
    pass


# --- fold-state load/save -------------------------------------------------------


def _range_to_list(value) -> list[int] | None:
    """int8range (postgres-canonical [lo, hi)) → inclusive [lo, hi] list."""
    if value is None:
        return None
    return [value.lower, value.upper - 1]


def _list_to_range(value):
    """Inclusive [lo, hi] list → psycopg int8range value."""
    if value is None:
        return None
    from psycopg.types.range import Range

    return Range(value[0], value[1], "[]")


def load_fold_state(cur) -> FoldState:
    """Load the full Tier-1 projection image (small at alpha scale).

    Claims + evidence links ARE preloaded since claim v2: the write-time
    lifecycle probe and the lifecycle folds (status/strength updates)
    read them, and the KnownState surface serves Inquiry claims from
    this image. If claim volume ever outgrows the full-image load, move
    to per-(believer, subject, predicate) lazy loads against
    claim_active_key — the index already exists.
    """
    state = FoldState()
    cur.execute("SELECT seed, world_time, rng_counters, last_event_id FROM world_state")
    row = cur.fetchone()
    if row is not None:
        state.world = {
            "seed": row[0],
            "world_time": row[1],
            "rng_counters": dict(row[2]),
            "last_event_id": row[3],
        }
    cur.execute(
        "SELECT entity_id, name, origin, aptitudes, hp, hp_max, coin, location_id,"
        " inventory, flags, titles, last_event_id FROM character_sheet"
    )
    for r in cur.fetchall():
        state.characters[r[0]] = {
            "entity_id": r[0],
            "name": r[1],
            "origin": r[2],
            "aptitudes": dict(r[3]),
            "hp": r[4],
            "hp_max": r[5],
            "coin": r[6],
            "location_id": r[7],
            "inventory": dict(r[8]),
            "flags": dict(r[9]),
            "titles": list(r[10]),
            "last_event_id": r[11],
        }
    cur.execute(
        "SELECT entity_id, world_id, hp, hp_max, conditions, location_id,"
        " updated_from_event_id FROM entity_state"
    )
    for r in cur.fetchall():
        state.entities[r[0]] = {
            "entity_id": r[0],
            "world_id": r[1],
            "hp": r[2],
            "hp_max": r[3],
            "conditions": list(r[4]),
            "location_id": r[5],
            "updated_from_event_id": r[6],
        }
    cur.execute(
        "SELECT entity_id, location_id, kind, name, region, descriptor,"
        " common_knowledge, portrait, last_event_id FROM scene_manifest"
    )
    for r in cur.fetchall():
        state.manifest[r[0]] = {
            "entity_id": r[0],
            "location_id": r[1],
            "kind": r[2],
            "name": r[3],
            "region": r[4],
            "descriptor": r[5],
            "common_knowledge": list(r[6]),
            "portrait": r[7],
            "last_event_id": r[8],
        }
    cur.execute(
        "SELECT timer_key, kind, subject_id, due_at, world_due, payload, status,"
        " created_event_id, fired_event_id, attempts FROM timer"
    )
    for r in cur.fetchall():
        state.timers[r[0]] = {
            "timer_key": r[0],
            "kind": r[1],
            "subject_id": r[2],
            "due_at": r[3],
            "world_due": r[4],
            "payload": dict(r[5]),
            "status": r[6],
            "created_event_id": r[7],
            "fired_event_id": r[8],
            "attempts": r[9],
        }
    cur.execute(
        "SELECT claim_id, believer_id, subject_entity_id, predicate, value_text,"
        " value_num, value_range, world_valid, claim_text, layer, source, observer,"
        " method, acquisition_method, world_date, scope, confidence, status, strength,"
        " provenance_root_event_id, source_agent_id, derived_from_claim_id, hop_count,"
        " journal_flag, world_time_acquired, origin_event_id, contested_by_claim_id,"
        " superseded_by_claim_id, superseded_reason, contradiction_ids FROM claim"
    )
    for r in cur.fetchall():
        state.claims[r[0]] = {
            "claim_id": r[0],
            "believer_id": r[1],
            "subject_entity_id": r[2],
            "predicate": r[3],
            "value_text": r[4],
            "value_num": r[5],
            "value_range": _range_to_list(r[6]),
            "world_valid": _range_to_list(r[7]),
            "claim_text": r[8],
            "layer": r[9],
            "source": r[10],
            "observer": r[11],
            "method": r[12],
            "acquisition_method": r[13],
            "world_date": r[14],
            "scope": r[15],
            "confidence": r[16],
            "status": r[17],
            "strength": r[18],
            "provenance_root_event_id": r[19],
            "source_agent_id": r[20],
            "derived_from_claim_id": r[21],
            "hop_count": r[22],
            "journal_flag": r[23],
            "world_time_acquired": r[24],
            "origin_event_id": r[25],
            "contested_by_claim_id": r[26],
            "superseded_by_claim_id": r[27],
            "superseded_reason": r[28],
            "contradiction_ids": list(r[29] or []),
        }
    cur.execute(
        "SELECT claim_id, event_id, root_event_id, acquisition_method, base_weight,"
        " world_time FROM claim_evidence"
    )
    for r in cur.fetchall():
        state.claim_evidence[(r[0], r[1])] = {
            "claim_id": r[0],
            "event_id": r[1],
            "root_event_id": r[2],
            "acquisition_method": r[3],
            "base_weight": r[4],
            "world_time": r[5],
        }
    cur.execute("SELECT actor_id, scope, subject_id, value, last_event_id FROM reputation")
    for r in cur.fetchall():
        state.reputation[f"{r[0]}::{r[1]}::{r[2]}"] = {
            "actor_id": r[0],
            "scope": r[1],
            "subject_id": r[2],
            "value": r[3],
            "last_event_id": r[4],
        }
    cur.execute(
        "SELECT deed_order, actor_id, location_id, notoriety, world_time,"
        " description, source_event_id FROM deeds ORDER BY deed_order, source_event_id"
    )
    for r in cur.fetchall():
        state.deeds.append(
            {
                "deed_order": r[0],
                "actor_entity_id": r[1],
                "location_id": r[2],
                "notoriety": r[3],
                "world_time": r[4],
                "description": r[5],
                "source_event_id": r[6],
            }
        )
    return state


def _write_dirty(cur, state: FoldState, *, suffix: str = "") -> None:
    """Write back every dirty projection row. ``suffix`` redirects writes
    to shadow tables (``<table><suffix>``) during a rebuild — table names
    are engine constants, never caller input."""
    for table, key in sorted(state.dirty):
        target = table + suffix
        if table == "world_state":
            w = state.world
            # Written ONLY under the world row lock taken before the fold
            # base was read (_lock_world) — the fold's max-merge of
            # world_time / rng counters / last_event_id against that fresh
            # image IS the merge; no blind overwrite of concurrent work is
            # possible.
            cur.execute(
                f"""
                INSERT INTO {target} (singleton, seed, world_time, rng_counters, last_event_id)
                VALUES (true, %s, %s, %s, %s)
                ON CONFLICT (singleton) DO UPDATE SET
                    seed = EXCLUDED.seed, world_time = EXCLUDED.world_time,
                    rng_counters = EXCLUDED.rng_counters,
                    last_event_id = EXCLUDED.last_event_id
                """,
                (w["seed"], w["world_time"], _jsonb(w["rng_counters"]), w["last_event_id"]),
            )
        elif table == "character_sheet":
            c = state.characters[key]
            cur.execute(
                f"""
                INSERT INTO {target}
                    (entity_id, name, origin, aptitudes, hp, hp_max, coin, location_id,
                     inventory, flags, titles, last_event_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id) DO UPDATE SET
                    name = EXCLUDED.name, origin = EXCLUDED.origin,
                    aptitudes = EXCLUDED.aptitudes, hp = EXCLUDED.hp,
                    hp_max = EXCLUDED.hp_max, coin = EXCLUDED.coin,
                    location_id = EXCLUDED.location_id, inventory = EXCLUDED.inventory,
                    flags = EXCLUDED.flags, titles = EXCLUDED.titles,
                    last_event_id = EXCLUDED.last_event_id
                """,
                (
                    c["entity_id"], c["name"], c["origin"], _jsonb(c["aptitudes"]),
                    c["hp"], c["hp_max"], c["coin"], c["location_id"],
                    _jsonb(c["inventory"]), _jsonb(c["flags"]), _jsonb(c["titles"]),
                    c["last_event_id"],
                ),
            )
        elif table == "entity_state":
            e = state.entities[key]
            cur.execute(
                f"""
                INSERT INTO {target}
                    (entity_id, world_id, hp, hp_max, conditions, location_id,
                     updated_from_event_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id) DO UPDATE SET
                    world_id = EXCLUDED.world_id, hp = EXCLUDED.hp,
                    hp_max = EXCLUDED.hp_max, conditions = EXCLUDED.conditions,
                    location_id = EXCLUDED.location_id,
                    updated_from_event_id = EXCLUDED.updated_from_event_id
                """,
                (
                    e["entity_id"], e["world_id"], e["hp"], e["hp_max"],
                    _jsonb(e["conditions"]), e["location_id"], e["updated_from_event_id"],
                ),
            )
        elif table == "claim":
            cl = state.claims[key]
            # Upsert: the INSERT arm is the claim_written fold (duplicates
            # were rejected LOUDLY before this point — duplicate domain-id); the UPDATE
            # arm carries lifecycle transitions (status, strength, links).
            cur.execute(
                f"""
                INSERT INTO {target}
                    (claim_id, believer_id, subject_entity_id, predicate, value_text,
                     value_num, value_range, world_valid, claim_text, layer, source,
                     observer, method, acquisition_method, world_date, scope, confidence,
                     status, strength, provenance_root_event_id, source_agent_id,
                     derived_from_claim_id, hop_count, journal_flag, world_time_acquired,
                     origin_event_id, contested_by_claim_id, superseded_by_claim_id,
                     superseded_reason, contradiction_ids)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (claim_id) DO UPDATE SET
                    status = EXCLUDED.status, strength = EXCLUDED.strength,
                    contested_by_claim_id = EXCLUDED.contested_by_claim_id,
                    contradiction_ids = EXCLUDED.contradiction_ids,
                    superseded_by_claim_id = EXCLUDED.superseded_by_claim_id,
                    superseded_reason = EXCLUDED.superseded_reason,
                    journal_flag = EXCLUDED.journal_flag
                """,
                (
                    cl["claim_id"], cl["believer_id"], cl["subject_entity_id"],
                    cl["predicate"], cl["value_text"], cl["value_num"],
                    _list_to_range(cl["value_range"]), _list_to_range(cl["world_valid"]),
                    cl["claim_text"], cl["layer"], cl["source"], cl["observer"],
                    cl["method"], cl["acquisition_method"], cl["world_date"], cl["scope"],
                    cl["confidence"], cl["status"], cl["strength"],
                    cl["provenance_root_event_id"], cl["source_agent_id"],
                    cl["derived_from_claim_id"], cl["hop_count"], cl["journal_flag"],
                    cl["world_time_acquired"], cl["origin_event_id"],
                    cl["contested_by_claim_id"], cl["superseded_by_claim_id"],
                    cl["superseded_reason"], _jsonb(cl.get("contradiction_ids") or []),
                ),
            )
        elif table == "claim_evidence":
            claim_id, _, event_id = key.rpartition("::")
            link = state.claim_evidence[(claim_id, int(event_id))]
            # Evidence links are written once, ever (folds raise on
            # duplicates) — a violation here must be LOUD.
            cur.execute(
                f"""
                INSERT INTO {target}
                    (claim_id, event_id, root_event_id, acquisition_method,
                     base_weight, world_time)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    link["claim_id"], link["event_id"], link["root_event_id"],
                    link["acquisition_method"], link["base_weight"], link["world_time"],
                ),
            )
        elif table == "scene_manifest":
            m = state.manifest[key]
            cur.execute(
                f"""
                INSERT INTO {target}
                    (entity_id, location_id, kind, name, region, descriptor,
                     common_knowledge, portrait, last_event_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id) DO UPDATE SET
                    location_id = EXCLUDED.location_id, kind = EXCLUDED.kind,
                    name = EXCLUDED.name, region = EXCLUDED.region,
                    descriptor = EXCLUDED.descriptor,
                    common_knowledge = EXCLUDED.common_knowledge,
                    portrait = EXCLUDED.portrait, last_event_id = EXCLUDED.last_event_id
                """,
                (
                    m["entity_id"], m["location_id"], m["kind"], m["name"], m["region"],
                    m.get("descriptor"), _jsonb(m["common_knowledge"]),
                    m["portrait"], m["last_event_id"],
                ),
            )
        elif table == "timer":
            t = state.timers[key]
            # due_at is the folded FACT from the timer_started payload
            # — never recomputed here. The ON CONFLICT update
            # touches lifecycle fields only; a second timer_started for the
            # same key can never reach this (fold raises).
            cur.execute(
                f"""
                INSERT INTO {target}
                    (timer_key, kind, subject_id, due_at, world_due, payload, status,
                     created_event_id, fired_event_id, attempts)
                VALUES (%s, %s, %s, %s::timestamptz, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (timer_key) DO UPDATE SET
                    status = EXCLUDED.status, fired_event_id = EXCLUDED.fired_event_id,
                    attempts = EXCLUDED.attempts
                """,
                (
                    t["timer_key"], t["kind"], t["subject_id"], t["due_at"],
                    t["world_due"], _jsonb(t["payload"]), t["status"],
                    t["created_event_id"], t["fired_event_id"], t["attempts"],
                ),
            )
        elif table == "reputation":
            rep = state.reputation[key]
            # value is the folded running total (amounts applied verbatim); the
            # resolver clamped at command time. Composite key = actor+scope+subject.
            cur.execute(
                f"""
                INSERT INTO {target}
                    (actor_id, scope, subject_id, value, last_event_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (actor_id, scope, subject_id) DO UPDATE SET
                    value = EXCLUDED.value, last_event_id = EXCLUDED.last_event_id
                """,
                (
                    rep["actor_id"], rep["scope"], rep["subject_id"],
                    rep["value"], rep["last_event_id"],
                ),
            )
        elif table == "deeds":
            source_event_id = int(key)
            deed = next(
                d for d in state.deeds if d["source_event_id"] == source_event_id
            )
            cur.execute(
                f"""
                INSERT INTO {target}
                    (deed_order, actor_id, location_id, notoriety, world_time,
                     description, source_event_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_event_id) DO UPDATE SET
                    deed_order = EXCLUDED.deed_order,
                    actor_id = EXCLUDED.actor_id,
                    location_id = EXCLUDED.location_id,
                    notoriety = EXCLUDED.notoriety,
                    world_time = EXCLUDED.world_time,
                    description = EXCLUDED.description
                """,
                (
                    deed["deed_order"], deed["actor_entity_id"], deed["location_id"],
                    deed["notoriety"], deed["world_time"], deed["description"],
                    deed["source_event_id"],
                ),
            )
    state.dirty.clear()


# --- rebuild ----------------------------------------------------------------------

#: DDL re-applied to the fresh live tables after a shadow swap. CREATE
#: TABLE (LIKE …) copies neither grants nor foreign keys, so the swap
#: restores them explicitly — keep in lockstep with migrations 0003/0004/
#: 0005/0008 (tests assert privileges survive a rebuild).
_POST_SWAP_DDL = tuple(
    f"GRANT SELECT, INSERT, UPDATE ON {table} TO app_role"
    for table in PROJECTION_TABLES
) + (
    "ALTER TABLE timer ADD FOREIGN KEY (created_event_id) REFERENCES event (id)",
    "ALTER TABLE timer ADD FOREIGN KEY (fired_event_id) REFERENCES event (id)",
)

_SHADOW_SUFFIX = "__shadow"


def migrate_and_rebuild(conn) -> list[str]:
    """Apply pending migrations, then rebuild every projection from the log if
    any landed on a world that already has events, or if any projection's
    stored version disagrees with the fold code.

    A migration that adds or reshapes a projection (0016 added ``deeds``)
    creates it empty, so an existing world would read an empty projection
    while a replay sees its history (audit 2026-10-24, codex F5). Projections
    are rebuildable by design, so the rebuild is the backfill. The version
    check makes it resumable (codex-003): a run killed between the migration
    and the rebuild, or a migration applied with the CLI, leaves the versions
    disagreeing, and the next start finishes the job. So a migration that adds
    a projection should leave its checkpoint row out (a missing row is stale),
    never stamp it current. Owner connections only (DDL). Returns the
    migrations applied."""
    from everquill_engine.migrate import apply_migrations

    applied = apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM event)")
        has_events = bool(cur.fetchone()[0])
        stale = _projector_versions_stale(cur)
    conn.commit()
    if (applied and has_events) or stale:
        rebuild_projections(conn)
    return applied


def _projector_versions_stale(cur) -> bool:
    """Whether any projection's stored version differs from the fold code's."""
    cur.execute("SELECT projection_name, projector_version FROM projection_checkpoint")
    stored = dict(cur.fetchall())
    return any(stored.get(name) != version for name, version in PROJECTOR_VERSIONS.items())


def rebuild_projections(conn) -> int:
    """Rebuild every projection: fold the log into SHADOW tables, diff
    against the live image, atomically swap, stamp projector versions
    (projector-version — replaces truncate-in-place; live tables are replaced only
    by a complete, verified image, in one transaction). Owner/migration
    connections only (DDL). Returns events folded."""
    with conn.transaction():
        with conn.cursor() as cur:
            _lock_world(cur)
            # 1. Shadow tables: full structural copies (constraints,
            #    indexes, defaults, identity) minus grants/FKs.
            for table in PROJECTION_TABLES:
                cur.execute(f"DROP TABLE IF EXISTS {table}{_SHADOW_SUFFIX}")
                cur.execute(
                    f"CREATE TABLE {table}{_SHADOW_SUFFIX}"
                    f" (LIKE {table} INCLUDING ALL)"
                )
            # 2. Fold the whole log into the shadows.
            cur.execute(f"SELECT {_EVENT_COLUMNS} FROM event ORDER BY id")
            state = FoldState()
            count = 0
            for raw in cur.fetchall():
                fold_event(state, _row_to_dict(raw))
                count += 1
            if state.world is not None:
                state.touch("world_state", "world")
            for key in state.characters:
                state.touch("character_sheet", key)
            for key in state.entities:
                state.touch("entity_state", key)
            for key in state.claims:
                state.touch("claim", key)
            for claim_id, event_id in state.claim_evidence:
                state.touch("claim_evidence", f"{claim_id}::{event_id}")
            for key in state.manifest:
                state.touch("scene_manifest", key)
            for key in state.timers:
                state.touch("timer", key)
            for deed in state.deeds:
                state.touch("deeds", str(deed["source_event_id"]))
            _write_dirty(cur, state, suffix=_SHADOW_SUFFIX)
            # 3. Diff live vs shadow (canonical dumps — volatile identity
            #    columns excluded by construction). A diff is expected
            #    exactly when fold logic changed; it is surfaced, never
            #    silently overwritten.
            live = canonical_projection_dump(conn, cur=cur)
            shadow = canonical_projection_dump(conn, cur=cur, suffix=_SHADOW_SUFFIX)
            if live != shadow:
                _emit_rebuild_diff(live, shadow)
            # 4. Atomic swap (same transaction: readers see old or new,
            #    never partial).
            for table in PROJECTION_TABLES:
                cur.execute(f"ALTER TABLE {table} RENAME TO {table}__old")
                cur.execute(f"ALTER TABLE {table}{_SHADOW_SUFFIX} RENAME TO {table}")
                cur.execute(f"DROP TABLE {table}__old CASCADE")
            for statement in _POST_SWAP_DDL:
                cur.execute(statement)
            # 5. Stamp the fold-logic versions this image was built by.
            for name, version in PROJECTOR_VERSIONS.items():
                cur.execute(
                    """
                    INSERT INTO projection_checkpoint
                        (projection_name, projector_version, last_event_id, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (projection_name) DO UPDATE SET
                        projector_version = EXCLUDED.projector_version,
                        last_event_id = EXCLUDED.last_event_id,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (name, version, state.world["last_event_id"] if state.world else None),
                )
    return count


def _emit_rebuild_diff(live: str, shadow: str) -> None:
    """Surface which projection chunks changed (stderr — rebuilds are
    operator actions). The swap proceeds: the shadow IS the truth of the
    current fold logic over the log; the diff is the changelog."""
    import sys

    labels = list(PROJECTION_TABLES)
    live_chunks = live.split("\n")
    shadow_chunks = shadow.split("\n")
    for label, a, b in zip(labels, live_chunks, shadow_chunks, strict=False):
        if a != b:
            print(f"[rebuild] projection {label!r} changed", file=sys.stderr)


# --- timers ------------------------------------------------------------------------


def due_timers(conn, world_time: int) -> list[dict[str, Any]]:
    """Pending timers due at or before world_time, in deterministic fire order.

    Tie order is (world_due, created_event_id): created_event_id is
    CANON (the event that started the timer), identical live and after
    a rebuild — unlike the projection's own insertion-ordered id, which
    a rebuild reassigns.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT timer_key, kind, subject_id, due_at, world_due, payload, status,
                   created_event_id, fired_event_id, attempts
            FROM timer
            WHERE status = 'pending' AND world_due <= %s
            ORDER BY world_due, created_event_id
            """,
            (world_time,),
        )
        return [
            {
                "timer_key": r[0], "kind": r[1], "subject_id": r[2], "due_at": r[3],
                "world_due": r[4], "payload": dict(r[5]), "status": r[6],
                "created_event_id": r[7], "fired_event_id": r[8], "attempts": r[9],
            }
            for r in cur.fetchall()
        ]


# --- content manifest -----------------------------------------------------


def stored_content_manifest(cur) -> dict[str, Any] | None:
    """The genesis content_manifest payload ({content_source, sha256,
    loader_version}), or None for worlds committed before content-drift."""
    cur.execute(
        "SELECT payload FROM event WHERE event_type = 'content_manifest' ORDER BY id LIMIT 1"
    )
    row = cur.fetchone()
    return dict(row[0]) if row else None


# --- test/dev helpers ----------------------------------------------------------------


def canonical_event_dump(conn) -> str:
    """Deterministic textual dump of the event table for byte-identity tests.

    Excludes exactly two columns: transaction_id (xid8) and recorded_at
    (wall clock) — both are infra forensics, never canon inputs
    (synthesis §2.1 rules). Everything else must be byte-identical for
    identical (seed, script) runs.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_EVENT_COLUMNS} FROM event ORDER BY id"
        )
        lines = []
        for raw in cur.fetchall():
            row = _row_to_dict(raw)
            lines.append(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))
    return "\n".join(lines)


#: Canonical dump queries, one per projection, in PROJECTION_TABLES
#: order ({t} = physical table name). Volatile DB-generated identities
#: (timer.id) are deliberately excluded; range columns dump as text.
_DUMP_QUERIES = {
    "world_state": "SELECT seed, world_time, rng_counters, last_event_id FROM {t}",
    "character_sheet": (
        "SELECT entity_id, name, origin, aptitudes, hp, hp_max, coin, location_id,"
        " inventory, flags, titles, last_event_id FROM {t} ORDER BY entity_id"
    ),
    "entity_state": (
        "SELECT entity_id, world_id, hp, hp_max, conditions, location_id,"
        " updated_from_event_id FROM {t} ORDER BY entity_id"
    ),
    "claim": (
        "SELECT claim_id, believer_id, subject_entity_id, predicate, value_text,"
        " value_num, value_range::text, world_valid::text, claim_text, layer, source,"
        " observer, method, acquisition_method, world_date, scope, confidence, status,"
        " strength, provenance_root_event_id, source_agent_id, derived_from_claim_id,"
        " hop_count, journal_flag, world_time_acquired, origin_event_id,"
        " contested_by_claim_id, superseded_by_claim_id, superseded_reason,"
        " contradiction_ids"
        " FROM {t} ORDER BY claim_id"
    ),
    "claim_evidence": (
        "SELECT claim_id, event_id, root_event_id, acquisition_method, base_weight,"
        " world_time FROM {t} ORDER BY claim_id, event_id"
    ),
    "scene_manifest": (
        "SELECT entity_id, location_id, kind, name, region, descriptor,"
        " common_knowledge, portrait, last_event_id FROM {t} ORDER BY entity_id"
    ),
    "timer": (
        "SELECT timer_key, kind, subject_id, due_at, world_due, payload, status,"
        " created_event_id, fired_event_id, attempts FROM {t} ORDER BY timer_key"
    ),
    "reputation": (
        "SELECT actor_id, scope, subject_id, value, last_event_id FROM {t}"
        " ORDER BY actor_id, scope, subject_id"
    ),
    "deeds": (
        "SELECT deed_order, actor_id, location_id, notoriety, world_time,"
        " description, source_event_id FROM {t} ORDER BY deed_order, source_event_id"
    ),
}


def canonical_projection_dump(conn, *, cur=None, suffix: str = "") -> str:
    """Deterministic dump of every projection table (rebuild-equivalence
    tests and the shadow-rebuild diff). One line per projection, in
    PROJECTION_TABLES order; ``suffix`` dumps the shadow set."""

    def _dump(cursor) -> str:
        chunks: list[str] = []
        for table in PROJECTION_TABLES:
            cursor.execute(_DUMP_QUERIES[table].format(t=table + suffix))
            rows = [_json_row(r) for r in cursor.fetchall()]
            if table == "world_state":
                rows = sorted(rows)
            chunks.append(json.dumps(rows, default=str))
        return "\n".join(chunks)

    if cur is not None:
        return _dump(cur)
    with conn.cursor() as own_cur:
        return _dump(own_cur)


def _json_row(row: tuple) -> list:
    return [json.loads(json.dumps(v, default=str)) for v in row]


def fresh_reset(conn) -> None:
    """DEV ONLY: wipe the log + projections (event ids restart at 1).

    Exists for the determinism harness and `cli play --fresh`. Never a
    production operation — production corrections are compensating
    events; worlds get wiped whole during alpha, exactly like this.
    This is also the sanctioned way replayed scripts get a clean
    command-id namespace (ambient-transaction note in the module docstring).

    Deliberately NOT cleared: projection_checkpoint (fold-logic versions
    are meta, not world state) and account_key (the key belongs to the
    account, not to canon — identical replays must re-encrypt
    identically; erasure is crypto.shred_account_key, never a reset).
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE event, world_state, character_sheet, entity_state, claim,"
                " claim_evidence, scene_manifest, timer, reputation, deeds,"
                " pending_confirmation"
                " RESTART IDENTITY CASCADE"
            )


def decrypt_event_payload(cur, payload: Any) -> Any:
    """Owner read path for stored event payloads (encrypted player text contract for
    the API): resolve every ``{"$enc": …}`` marker using the world's
    account key. After a shred the markers render ``[shredded]``.
    Plain payloads pass through untouched, so this is safe to apply
    unconditionally when serving stored events to their owner."""
    key = crypto.load_account_key(cur)
    return crypto.decrypt_payload(payload, key[1] if key else None)
