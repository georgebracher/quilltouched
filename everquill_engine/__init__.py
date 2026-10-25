"""Everquill deterministic rules engine.

The engine is the referee; the LLM is the mouth. Rules modules (dice,
ladder, events, folds, chargen, clock, resolver, world) are pure
Python: zero LLM, network, or database imports, ever. No code in this
package may decide anything from prose — it consumes structured
intents and state, and it emits rolls, tiers, and events.

Persistence lives in exactly four modules (ticket lane):
:mod:`everquill_engine.db`, :mod:`everquill_engine.store`,
:mod:`everquill_engine.migrate` and :mod:`everquill_engine.cli` — the
only places psycopg may be imported.

Surface:

- :mod:`everquill_engine.dice`     — seeded, stream-keyed, replay-deterministic 2d6.
- :mod:`everquill_engine.ladder`   — plausibility tiers, risk labels, gap→band
  mapping, 2d6 three-tier outcome mapping.
- :mod:`everquill_engine.events`   — append-only event envelope + event types + EventSpec.
- :mod:`everquill_engine.folds`    — pure Tier-1 projection folds (deltas in, rows out).
- :mod:`everquill_engine.world`    — locked world-content YAML loader/validator.
- :mod:`everquill_engine.chargen`  — aptitude rolls → character + events.
- :mod:`everquill_engine.clock`    — world clock v1 (minutes), action costs, timer fires.
- :mod:`everquill_engine.resolver` — the Referee: intent + state → outcome + events.
- :mod:`everquill_engine.store`    — event append + Tier-1 projector (psycopg3).
- :mod:`everquill_engine.cli`      — `python -m everquill_engine.cli play|clock-advance`.
"""

from everquill_engine.dice import DiceRoller, Roll2d6, roll_2d6
from everquill_engine.events import Event, EventSpec, EventType, event_ref
from everquill_engine.ladder import (
    HopelessFlavor,
    Outcome,
    OutcomeTier,
    PlausibilityTier,
    RiskLabel,
    band_for_gap,
    outcome_for_roll,
)

__version__ = "0.2.0"

__all__ = [
    "DiceRoller",
    "Event",
    "EventSpec",
    "EventType",
    "HopelessFlavor",
    "Outcome",
    "OutcomeTier",
    "PlausibilityTier",
    "RiskLabel",
    "Roll2d6",
    "band_for_gap",
    "event_ref",
    "outcome_for_roll",
    "roll_2d6",
    "__version__",
]
