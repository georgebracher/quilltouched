"""World clock v1. Pure module — no persistence.

- ``world_time`` is an integer count of world MINUTES since the world
  was created. Epoch display convention: minute 0 = Day 1, 06:00 (dawn
  of the awakening day). Both the unit and the epoch are documented in
  docs/engine/stats.md; the intent-schema's delta_clock note ("unit
  definition belongs to the engine's world-clock spec") resolves to this.
- Every resolved action advances the clock by a fixed cost per action
  type (table below). Movement between locations costs carriage_days
  from the world content instead.
- Timed blocks (training, v1) run on the timer table; the sweeper is a
  manual CLI command (`python -m everquill_engine.cli clock-advance`),
  no daemon (ticket #5). Timer outcomes resolve deterministically AT
  FIRE TIME with seed = hash(timer_id, created_event_id) — canon never
  waits for anything (synthesis §2.5/D5).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from everquill_engine.dice import roll_2d6
from everquill_engine.rng_registry import timer_fire_stream

__all__ = [
    "MINUTES_PER_DAY",
    "ACTION_TIME_COST",
    "TRAINING_BLOCK_MINUTES",
    "WORLD_EPOCH_UTC",
    "DURATION_MAX_MINUTES",
    "UNTIL_CLOCKS",
    "DurationBindingError",
    "bind_duration",
    "action_time_cost",
    "world_date",
    "real_due_at",
    "timer_fire_seed",
    "resolve_timer_fire",
]

MINUTES_PER_DAY = 1440

#: THE world-epoch mapping (documented here and in migration
#: 0005): world minute 0 maps to the Unix epoch, 1970-01-01T00:00:00Z,
#: and one world minute is one real minute. This is a deliberate
#: Sprint-1 placeholder — there is no real-time pacing yet — chosen so
#: the mapping is a pure constant and byte-identical across runs
#: (determinism test 1). When real pacing lands, only THIS mapping and
#: the creation-time computation change: because every timer records
#: its real ``due_at`` as a payload FACT at creation (folded verbatim,
#: never recomputed), a later mapping change can never rewrite the
#: deadline of any existing timer.
WORLD_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)

#: World-minutes each resolved action advances the clock (documented in
#: docs/engine/stats.md — keep the table there in lockstep). ``movement``
#: is the same-location/short-hop cost; cross-location movement prices
#: carriage_days x 1440 from the world content instead. ``rest`` is the
#: intent schema v1.1 addition (the LLM layer owns the schema edit; the engine
#: accepts it now so the vocabularies land in lockstep). ``train`` is
#: the cost of committing to the block — the block itself runs on a
#: timer (TRAINING_BLOCK_MINUTES).
ACTION_TIME_COST: dict[str, int] = {
    "physical": 10,
    "social": 15,
    "movement": 15,
    "observation": 5,
    "research": 60,
    "craft": 60,
    "train": 5,
    "dialogue": 2,
    "meta": 0,
    "rest": 480,
}

#: One committed training block (world minutes). Flat v1 value; rising
#: per-gain cost curves are the Sprint-2+ progression ticket.
TRAINING_BLOCK_MINUTES = 480


def action_time_cost(action_type: str) -> int:
    """World-minute cost for an action type. Raises on unknown types."""
    try:
        return ACTION_TIME_COST[action_type]
    except KeyError:
        raise ValueError(f"no time cost defined for action_type {action_type!r}") from None


# --- duration_hint binding --------------------------------------------
#
# The intent schema says duration_hint "carries the player's words -- the
# engine maps conditions to world clocks and prices actual duration".
# Sprint 1 silently ignored it; these tables are the deterministic
# binding. Consumption per action shape is the resolver's job
# (docs/engine/stats.md "Duration binding" — keep in lockstep); this
# module only turns the closed fields (mode, until, amount, unit) and
# world_time into world minutes or a clear rejection.

#: Hard cap on any bound span. Beyond this the engine refuses rather
#: than committing a season to a typo.
DURATION_MAX_MINUTES = 30 * MINUTES_PER_DAY

#: Time of day each closed ``until`` value ends at (minutes since midnight).
#: The span runs to the NEXT occurrence (strictly in the future: "until dusk"
#: at dusk means tomorrow's).
UNTIL_CLOCKS: dict[str, int] = {
    "dawn": 6 * 60,
    "midday": 12 * 60,
    "dusk": 18 * 60,
    "midnight": 0,
}

_UNIT_MINUTES: dict[str, int] = {"minute": 1, "hour": 60, "day": 1440}


class DurationBindingError(ValueError):
    """A duration_hint could not be bound deterministically. The message
    names the supported forms so the rejection is actionable."""


def bind_duration(hint: Any, world_time: int) -> int:
    """Bind one duration_hint to world minutes, deterministically. Pure.

    Reads only the closed fields (``mode``, ``until``, ``amount``, ``unit``),
    never the player's words in ``text``: the parser's choice of words cannot
    change a time cost (audit 2026-10-24). ``world_time`` is the world minute
    the span starts at (only until-conditions read it). Returns minutes >= 1
    or raises :class:`DurationBindingError`, never a silent default.
    """
    if hint.mode == "until_condition":
        if hint.until is None:
            raise DurationBindingError(
                f"cannot bind {hint.text!r} to a world clock: the engine binds dawn, "
                "midday, dusk and midnight (world-event conditions land with a later sprint)"
            )
        minute_of_day = (world_time + 6 * 60) % MINUTES_PER_DAY
        delta = (UNTIL_CLOCKS[hint.until] - minute_of_day) % MINUTES_PER_DAY
        return delta if delta > 0 else MINUTES_PER_DAY
    if hint.mode == "explicit":
        if hint.amount is None or hint.unit is None:
            raise DurationBindingError(
                f"cannot bind explicit span {hint.text!r}: it needs an amount and a unit "
                "(minute, hour or day)"
            )
        minutes = hint.amount * _UNIT_MINUTES[hint.unit]
        if minutes > DURATION_MAX_MINUTES:
            raise DurationBindingError(
                f"explicit span {hint.text!r} binds to {minutes} world-minutes; the engine "
                f"binds spans up to {DURATION_MAX_MINUTES // MINUTES_PER_DAY} days"
            )
        return minutes
    raise DurationBindingError(f"unknown duration mode {hint.mode!r}")


def world_date(world_time: int) -> str:
    """Human/Chronicle rendering: minute 0 → 'Day 1, 06:00'."""
    if world_time < 0:
        raise ValueError(f"world_time must be >= 0, got {world_time}")
    total = world_time + 6 * 60  # epoch offset: day starts at 06:00
    day = 1 + total // MINUTES_PER_DAY
    minutes_of_day = total % MINUTES_PER_DAY
    return f"Day {day}, {minutes_of_day // 60:02d}:{minutes_of_day % 60:02d}"


def real_due_at(world_due: int) -> str:
    """World-minute deadline → real-timestamp fact (ISO 8601, UTC).

    Computed ONCE at timer creation against :data:`WORLD_EPOCH_UTC` and
    stored in the timer_started payload; folds apply it verbatim.
    Never call this from a fold or a sweeper — the stored
    fact is the deadline.
    """
    if world_due < 0:
        raise ValueError(f"world_due must be >= 0, got {world_due}")
    return (WORLD_EPOCH_UTC + timedelta(minutes=world_due)).isoformat()


def timer_fire_seed(timer_key: str, created_event_id: int) -> int:
    """Deterministic fire-time seed = hash(timer_id, created_event_id).

    (Synthesis §2.5.) Stable across machines and engine versions: the
    preimage is versioned and the inputs are canon (the timer's domain
    key and the DB id of the event that created it).
    """
    preimage = f"everquill.timerfire.v1|{timer_key}|{created_event_id}".encode()
    return int.from_bytes(hashlib.sha256(preimage).digest()[:8], "big")


def resolve_timer_fire(timer_row: dict[str, Any], created_event_id: int) -> dict[str, Any]:
    """Resolve a due timer's outcome deterministically. Pure.

    Returns the timer_completed payload fields that carry facts:
    ``gains`` (stored deltas, folded blindly later) and the audit
    ``rng`` record (or None). v1 fires only ``training`` timers; other
    kinds exist in the table structure (per §2.5) but have no fire rule
    yet — reaching one is a bug, not a silent skip.
    """
    kind = timer_row["kind"]
    if kind != "training":
        raise ValueError(f"no fire rule for timer kind {kind!r} yet (Sprint-1 fires training)")

    seed = timer_fire_seed(timer_row["timer_key"], created_event_id)
    roll = roll_2d6(seed, timer_fire_stream(timer_row["timer_key"]), 0)
    payload = timer_row["payload"]
    aptitude = payload["aptitude"]
    owner_id = payload["owner_id"]
    # v1 training rule, resolved HERE at fire time (never in a fold):
    # a block always grinds +1; a 10+ on the block's own dice marks a
    # breakthrough flag (narrator hook), not extra stats.
    gains: list[dict[str, Any]] = [
        {
            "delta_type": "aptitude",
            "entity_id": owner_id,
            "aptitude": aptitude,
            "amount": 1,
        }
    ]
    if roll.total >= 10:
        gains.append(
            {
                "delta_type": "flag",
                "entity_id": owner_id,
                "flag_key": f"breakthrough_{aptitude}",
                "value": True,
            }
        )
    return {
        "gains": gains,
        "rng": {
            "stream": ["timerfire", timer_row["timer_key"]],
            "index": 0,
            "rolls": [roll.die_one, roll.die_two],
        },
    }
