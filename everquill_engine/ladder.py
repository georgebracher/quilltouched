"""The plausibility ladder: tiers, risk labels, gap→band, 2d6 outcomes.

Pure data + pure functions. Everything here is deterministic and
stateless; nothing here reads prose, state stores, or dice — callers
roll (dice.py) and then map (this module).

Roadmap references: §3.1 (ladder + risk labels), §2 Core Loop
(2d6 three-tier resolution), §4 State Architecture.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

__all__ = [
    "PlausibilityTier",
    "RiskLabel",
    "OutcomeTier",
    "HopelessFlavor",
    "Outcome",
    "ROLLABLE_TIERS",
    "band_for_gap",
    "outcome_for_roll",
]


class PlausibilityTier(enum.IntEnum):
    """The plausibility ladder (roadmap §3.1), in ladder order.

    Numeric order is ladder order (harder = greater) so band
    monotonicity is directly comparable. Notes:

    - TRIVIAL never rolls (narrate only — tap-verb territory).
    - ROUTINE / RISKY / DESPERATE are real 2d6 checks.
    - HOPELESS rolls, but the band shape is all-failure: the roll
      selects the failure flavor only. Best case is never victory.
    - SEALED and IMPOSSIBLE are NOT gap-derived and are never returned
      by :func:`band_for_gap`. SEALED is gated by authored component
      laws (resolver checks components — later sprint); IMPOSSIBLE
      violates universe physics and never rolls (fiction reacts to the
      attempt; it is still a deed).
    """

    TRIVIAL = 0
    ROUTINE = 1
    RISKY = 2
    DESPERATE = 3
    HOPELESS = 4
    SEALED = 5
    IMPOSSIBLE = 6


class RiskLabel(enum.IntEnum):
    """Pre-roll risk labels (roadmap §3.1) — always words, never percentages.

    Engine-calculated and shown before the roll. Numeric order is
    severity order. Computing the label for a concrete action (stakes x
    band) is resolver scope (Sprint 1+); Sprint 0 fixes only the
    vocabulary so it is stable for the commit-beat dialog and the
    Chronicle. ``RiskLabel.DESPERATE`` (a stakes word) is distinct from
    ``PlausibilityTier.DESPERATE`` (a difficulty band) by design — the
    roadmap uses both.
    """

    GUARDED = 0
    PERILOUS = 1
    DIRE = 2
    DESPERATE = 3
    SUICIDAL = 4


class OutcomeTier(enum.Enum):
    """2d6 three-tier resolution (PbtA-style, roadmap §2).

    STRONG_HIT — clean success.
    HIT_WITH_COMPLICATION — success with a cost ("yes, but…" — where the
    narrator earns its keep).
    MISS — failure; every miss still writes something (intel, rumor,
    scar, journal line). The loop always deposits value.
    """

    STRONG_HIT = "strong_hit"
    HIT_WITH_COMPLICATION = "hit_with_complication"
    MISS = "miss"


class HopelessFlavor(enum.Enum):
    """Failure flavor for the HOPELESS band — the roll picks HOW you fail.

    Mapped from the same 2d6 totals as the normal bands, but every band
    is a miss (roadmap §3.1: devoured / ignored-then-noticed / the
    dragon is amused, you live wrecked):

    CATASTROPHIC — the "devoured" band (totals that would miss anyway).
    PUNISHING    — mauled but alive (the would-be "yes, but…" band).
    SPARED       — the would-be strong hit: you live, wrecked. Still a
                   MISS. Best case is never victory.
    """

    CATASTROPHIC = "catastrophic"
    PUNISHING = "punishing"
    SPARED = "spared"


@dataclass(frozen=True, slots=True)
class Outcome:
    """Resolved outcome of one 2d6 check against one band."""

    tier: OutcomeTier
    hopeless_flavor: HopelessFlavor | None = None


#: Bands that route through the 2d6 outcome mapping at all.
ROLLABLE_TIERS: frozenset[PlausibilityTier] = frozenset(
    {
        PlausibilityTier.ROUTINE,
        PlausibilityTier.RISKY,
        PlausibilityTier.DESPERATE,
        PlausibilityTier.HOPELESS,
    }
)

# Gap → band thresholds. PROVISIONAL Sprint-0 values — content authors tune
# these against seed-region threat bands in Sprint 1; the *shape*
# (monotonic, unbounded at both ends) is the locked contract, the
# numbers are not. Each row is (max_gap_inclusive, band); gaps above
# the last row are HOPELESS.
_BAND_THRESHOLDS: tuple[tuple[int, PlausibilityTier], ...] = (
    (-4, PlausibilityTier.TRIVIAL),
    (0, PlausibilityTier.ROUTINE),
    (3, PlausibilityTier.RISKY),
    (7, PlausibilityTier.DESPERATE),
)


def band_for_gap(gap: int) -> PlausibilityTier:
    """Map a stat gap to a difficulty band. Pure, total, monotonic.

    ``gap`` = (difficulty demanded by the target's TRUE sheet) minus
    (the acting stat), an unbounded int. Positive = outmatched,
    negative = you outclass the task. Both stats are uncapped
    (roadmap §2: progression is band-relative), so this function must
    accept any int and be monotonic non-decreasing: a bigger gap NEVER
    yields an easier band. Growth moves the same action down the
    ladder — the re-tier toast is the level-up.

    Returns only gap-derived bands (TRIVIAL..HOPELESS). SEALED and
    IMPOSSIBLE are authored properties of the action, never produced
    by arithmetic.
    """
    for max_gap, band in _BAND_THRESHOLDS:
        if gap <= max_gap:
            return band
    return PlausibilityTier.HOPELESS


def outcome_for_roll(band: PlausibilityTier, total: int) -> Outcome:
    """Map a 2d6 total to an outcome under ``band``. Pure.

    Normal rollable bands (ROUTINE / RISKY / DESPERATE) use the
    three-tier split: 10+ strong hit, 7–9 hit with complication,
    6- miss. Band difficulty enters through modifiers applied to the
    total BEFORE this call (resolver scope) — the split itself is
    fixed so the Chronicle's post-roll audit stays legible.

    HOPELESS is all-failure: the tier is always MISS and the same
    totals select :class:`HopelessFlavor` instead (10+ merely SPARED).

    TRIVIAL, SEALED and IMPOSSIBLE never reach the 2d6 mapping:
    TRIVIAL narrates without dice, IMPOSSIBLE never rolls, and SEALED
    rolls only after the resolver verifies authored components (later
    sprint) — at which point it resolves as the band the components
    unlock, not as "SEALED". Passing them here is a caller bug.
    """
    if not 2 <= total <= 12:
        raise ValueError(f"2d6 total must be in 2..12, got {total}")
    if band not in ROLLABLE_TIERS:
        raise ValueError(f"{band.name} does not route through the 2d6 outcome mapping")

    if band is PlausibilityTier.HOPELESS:
        if total >= 10:
            flavor = HopelessFlavor.SPARED
        elif total >= 7:
            flavor = HopelessFlavor.PUNISHING
        else:
            flavor = HopelessFlavor.CATASTROPHIC
        return Outcome(tier=OutcomeTier.MISS, hopeless_flavor=flavor)

    if total >= 10:
        return Outcome(tier=OutcomeTier.STRONG_HIT)
    if total >= 7:
        return Outcome(tier=OutcomeTier.HIT_WITH_COMPLICATION)
    return Outcome(tier=OutcomeTier.MISS)
