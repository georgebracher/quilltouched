"""Chargen: aptitude rolls via named dice streams → character + event (pure).

Locked vocabulary (interface decision #1): might, finesse,
wits, will, presence, lore. Roll method, ranges and band interaction
are published in docs/engine/stats.md — that document and this module
must move together.

No class picker (roadmap §2): aptitudes + origin only. Two build paths,
both drawing from the dedicated stream ``("chargen", character_id)`` so
chargen can never perturb any action stream (stream independence,
dice.py design goal 2):

- ``roll_character`` — auto: aptitude i takes the value at index i
  (the Sprint-1 path; unchanged).
- ``roll_pool`` + ``build_character`` — GUIDED DICE (George's
  chargen decision): roll a pool of six base values plus one spare
  (indexes 0..6), then the PLAYER assigns six of them to aptitudes and
  may swap a base value for the spare ("reroll"). Nothing is re-rolled —
  the pool is a pure function of (seed, character_id); the player's
  choice lives in the event, so it replays identically.
"""

from __future__ import annotations

from dataclasses import dataclass

from everquill_engine.dice import roll_2d6
from everquill_engine.events import EventSpec, EventType
from everquill_engine.rng_registry import chargen_stream
from everquill_engine.world import APTITUDES

__all__ = [
    "STARTING_COIN",
    "MAX_REROLLS",
    "CharacterRolls",
    "PoolRoll",
    "roll_character",
    "roll_pool",
    "build_character",
    "chargen_events",
]

#: Starting purse in copper. Flat v1 value; origin-based purses are a
#: later content decision.
STARTING_COIN = 30

#: Guided-dice spares (George, 2026-07-14): the pool holds six base values
#: plus this many extra, and the player assigns six of the pool to aptitudes —
#: so one base value can be swapped for the spare. The honest-dice ethos holds:
#: the seed owns the numbers, the player owns the placement.
MAX_REROLLS = 1


@dataclass(frozen=True, slots=True)
class CharacterRolls:
    """Resolved chargen: the facts that go into the character_created payload."""

    character_id: str
    name: str
    origin: str
    aptitudes: dict[str, int]
    rolls: dict[str, tuple[int, int]]  # aptitude -> (die_one, die_two), audit record
    hp_max: int
    coin: int
    #: Guided-dice: aptitude -> chosen pool index. None for the auto-rolled
    #: path (roll_character), which keeps the identity assignment.
    assignment: dict[str, int] | None = None
    #: Number of 2d6 values drawn from the chargen stream (the pool size).
    pool_size: int = len(APTITUDES)


@dataclass(frozen=True, slots=True)
class PoolRoll:
    """One assignable value in the guided-dice pool."""

    index: int
    die_one: int
    die_two: int
    total: int


def roll_character(
    seed: int,
    character_id: str,
    *,
    name: str,
    origin: str = "quill_touched_stranger",
) -> CharacterRolls:
    """Roll the six aptitudes. Pure: (seed, character_id) → same character, forever."""
    stream = chargen_stream(character_id)  # registered roll site
    aptitudes: dict[str, int] = {}
    rolls: dict[str, tuple[int, int]] = {}
    for index, aptitude in enumerate(APTITUDES):
        roll = roll_2d6(seed, stream, index)
        aptitudes[aptitude] = roll.total
        rolls[aptitude] = (roll.die_one, roll.die_two)
    # hp_max derivation is a chargen RULE, resolved here at command time;
    # the payload stores the result so no fold ever recomputes it.
    hp_max = 4 + aptitudes["might"]
    return CharacterRolls(
        character_id=character_id,
        name=name,
        origin=origin,
        aptitudes=aptitudes,
        rolls=rolls,
        hp_max=hp_max,
        coin=STARTING_COIN,
    )


def roll_pool(seed: int, character_id: str) -> list[PoolRoll]:
    """The deterministic guided-dice pool: six base 2d6 values plus MAX_REROLLS
    spare(s), at indexes 0..(5+MAX_REROLLS) on the ('chargen', character_id)
    stream. The player assigns six of these to aptitudes (build_character); a
    "reroll" is choosing a spare over a base value — nothing is re-rolled, so
    the pool is a pure function of (seed, character_id) and replays identically."""
    stream = chargen_stream(character_id)
    size = len(APTITUDES) + MAX_REROLLS
    pool: list[PoolRoll] = []
    for index in range(size):
        roll = roll_2d6(seed, stream, index)
        pool.append(PoolRoll(index, roll.die_one, roll.die_two, roll.total))
    return pool


def _validate_assignment(assignment: dict[str, int]) -> None:
    """A guided assignment must cover the six aptitudes with distinct, in-range
    pool indexes (a placement, not a free-for-all)."""
    if set(assignment) != set(APTITUDES):
        raise ValueError(
            f"assignment must cover exactly the six aptitudes {sorted(APTITUDES)}; "
            f"got {sorted(assignment)}"
        )
    indices = list(assignment.values())
    if len(set(indices)) != len(indices):
        raise ValueError("each pool value may be assigned to only one aptitude")
    pool_size = len(APTITUDES) + MAX_REROLLS
    out_of_range = sorted(i for i in indices if not 0 <= i < pool_size)
    if out_of_range:
        raise ValueError(
            f"pool indexes must be in [0, {pool_size - 1}]; out of range: {out_of_range}"
        )


def build_character(
    seed: int,
    character_id: str,
    *,
    name: str,
    origin: str = "quill_touched_stranger",
    assignment: dict[str, int],
) -> CharacterRolls:
    """Build a character from a PLAYER assignment of pool values to aptitudes
    (guided dice). ``assignment`` maps each aptitude to a pool index (validated:
    the six aptitudes, distinct in-range indexes). Pure and replayable — the
    pool is seed-derived, the choice lives in the event. hp_max is a chargen
    RULE resolved here so no fold recomputes it."""
    _validate_assignment(assignment)
    pool = {p.index: p for p in roll_pool(seed, character_id)}
    aptitudes: dict[str, int] = {}
    rolls: dict[str, tuple[int, int]] = {}
    for aptitude in APTITUDES:
        chosen = pool[assignment[aptitude]]
        aptitudes[aptitude] = chosen.total
        rolls[aptitude] = (chosen.die_one, chosen.die_two)
    hp_max = 4 + aptitudes["might"]
    return CharacterRolls(
        character_id=character_id,
        name=name,
        origin=origin,
        aptitudes=aptitudes,
        rolls=rolls,
        hp_max=hp_max,
        coin=STARTING_COIN,
        assignment=dict(assignment),
        pool_size=len(APTITUDES) + MAX_REROLLS,
    )


def chargen_events(
    rolled: CharacterRolls, *, location_id: str, region: str | None, world_time: int
) -> list[EventSpec]:
    """The character_created event for one rolled character."""
    faces: list[int] = []
    for aptitude in APTITUDES:
        faces.extend(rolled.rolls[aptitude])
    return [
        EventSpec(
            stream_id=f"character:{rolled.character_id}",
            event_type=EventType.CHARACTER_CREATED,
            world_time=world_time,
            location_id=location_id,
            rng={
                "stream": list(chargen_stream(rolled.character_id)),
                "index": rolled.pool_size - 1,
                "rolls": faces,
            },
            payload={
                "character_id": rolled.character_id,
                "name": rolled.name,
                "origin": rolled.origin,
                "aptitudes": rolled.aptitudes,
                "rolls": {k: list(v) for k, v in rolled.rolls.items()},
                "hp": rolled.hp_max,
                "hp_max": rolled.hp_max,
                "coin": rolled.coin,
                "location_id": location_id,
                "region": region,
                # Guided-dice audit: how the player placed the pool. Absent for
                # the auto-rolled path, so its stored payload is unchanged.
                **(
                    {"assignment": rolled.assignment, "chargen_mode": "guided"}
                    if rolled.assignment is not None
                    else {}
                ),
            },
        )
    ]
