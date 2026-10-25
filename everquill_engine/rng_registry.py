"""Roll-site registry: THE table of semantic RNG stream ids.

Every place the engine draws dice is a registered ROLL SITE with its own
semantic stream id. Streams share no state (dice.py design goal 2), so a
new draw at one site can never shift the sequence of any other site —
but that guarantee is only real if sites never share a stream. Sprint 1
violated it by pooling every action outcome on one generic
``("character:<id>", "action")`` stream; this registry is the fix.

Rules (binding):

- Rolling code builds streams ONLY through the builder functions below —
  never inline tuples — so every draw is attributable to a registered
  site.
- The table is APPEND-ONLY. ``tests/test_rng_registry.py`` diffs it
  against the frozen fixture ``tests/golden/roll_sites.json``: changing
  or removing a registered site fails the build (it would re-key
  historical dice); new sites must be appended to the fixture in the
  same commit with a documented reason.
- Migration ``0006`` adds DB uniqueness on ``(rng->'stream',
  rng->'index')`` so a reused index can never silently commit twice.

Stream-id migration note (documented pin change): action
outcomes moved from the pooled ``action`` stream to per-action-type
streams, and HOPELESS flavor draws moved to their own site. Historical
events keep their stored rng records verbatim (replay never re-rolls —
folds only merge counters per stream key), so old logs stay valid;
fresh runs draw from the new streams.
"""

from __future__ import annotations

from dataclasses import dataclass

from everquill_engine.intent import ACTION_TYPES

__all__ = [
    "RollSite",
    "ROLL_SITES",
    "chargen_stream",
    "action_outcome_stream",
    "hopeless_flavor_stream",
    "timer_fire_stream",
]


@dataclass(frozen=True, slots=True)
class RollSite:
    """One registered roll site. ``stream`` is the semantic template —
    ``{character_id}`` / ``{timer_key}`` placeholders are filled by the
    builder functions."""

    site_id: str
    stream: tuple[str, ...]
    draws: str  # what draws here and how the index advances
    owner: str  # the module.function that rolls


def _site(site_id: str, stream: tuple[str, ...], draws: str, owner: str) -> RollSite:
    return RollSite(site_id=site_id, stream=stream, draws=draws, owner=owner)


#: THE module-level roll-site table. Append-only — see module docstring.
ROLL_SITES: dict[str, RollSite] = {
    "chargen": _site(
        "chargen",
        ("chargen", "{character_id}"),
        "six 2d6 draws at indexes 0..5, one per aptitude in APTITUDES order",
        "chargen.roll_character",
    ),
    **{
        f"action:{action_type}": _site(
            f"action:{action_type}",
            ("character:{character_id}", f"action:{action_type}"),
            "one 2d6 outcome draw per resolved rollable action of this type; "
            "index advances via world_state.rng_counters",
            "resolver.resolve_intent",
        )
        for action_type in sorted(ACTION_TYPES)
    },
    "hopeless_flavor": _site(
        "hopeless_flavor",
        ("character:{character_id}", "hopeless_flavor"),
        "one 2d6 draw per HOPELESS-band action; the roll picks the failure "
        "flavor only (never an outcome tier); index advances via "
        "world_state.rng_counters",
        "resolver.resolve_intent",
    ),
    "timer_fire:training": _site(
        "timer_fire:training",
        ("timerfire", "{timer_key}"),
        "one 2d6 draw at index 0 per timer fire, seeded by "
        "timer_fire_seed(timer_key, created_event_id)",
        "clock.resolve_timer_fire",
    ),
}


def chargen_stream(character_id: str) -> tuple[str, str]:
    return ("chargen", character_id)


def action_outcome_stream(character_id: str, action_type: str) -> tuple[str, str]:
    if action_type not in ACTION_TYPES:
        raise ValueError(f"no registered action roll site for {action_type!r}")
    return (f"character:{character_id}", f"action:{action_type}")


def hopeless_flavor_stream(character_id: str) -> tuple[str, str]:
    return (f"character:{character_id}", "hopeless_flavor")


def timer_fire_stream(timer_key: str) -> tuple[str, str]:
    return ("timerfire", timer_key)
