"""Property-style tests for the plausibility ladder and 2d6 outcome mapping."""

import itertools

import pytest

from everquill_engine.ladder import (
    ROLLABLE_TIERS,
    HopelessFlavor,
    OutcomeTier,
    PlausibilityTier,
    RiskLabel,
    band_for_gap,
    outcome_for_roll,
)

ALL_TOTALS = range(2, 13)


class TestEnumStability:
    """The vocabularies are contracts (UI copy, event payloads, Chronicle).

    Names, storage values, and ladder order must not drift. If one of
    these fails, someone changed a contract — that needs a payload
    upcast plan, not a test edit.
    """

    def test_plausibility_tier_members_and_order(self):
        assert [t.name for t in PlausibilityTier] == [
            "TRIVIAL",
            "ROUTINE",
            "RISKY",
            "DESPERATE",
            "HOPELESS",
            "SEALED",
            "IMPOSSIBLE",
        ]
        assert [t.value for t in PlausibilityTier] == list(range(7))

    def test_risk_label_members_and_order(self):
        assert [label.name for label in RiskLabel] == [
            "GUARDED",
            "PERILOUS",
            "DIRE",
            "DESPERATE",
            "SUICIDAL",
        ]
        assert [label.value for label in RiskLabel] == list(range(5))

    def test_outcome_tier_wire_values(self):
        assert {t.value for t in OutcomeTier} == {
            "strong_hit",
            "hit_with_complication",
            "miss",
        }

    def test_hopeless_flavor_wire_values(self):
        assert {f.value for f in HopelessFlavor} == {
            "catastrophic",
            "punishing",
            "spared",
        }

    def test_ladder_orderable(self):
        assert PlausibilityTier.TRIVIAL < PlausibilityTier.ROUTINE < PlausibilityTier.HOPELESS
        assert RiskLabel.GUARDED < RiskLabel.DIRE < RiskLabel.SUICIDAL


class TestBandForGap:
    def test_monotonic_over_wide_sweep(self):
        """Bigger gap NEVER yields an easier band (unbounded stats)."""
        gaps = range(-500, 501)
        bands = [band_for_gap(g) for g in gaps]
        for earlier, later in itertools.pairwise(bands):
            assert later >= earlier, "band mapping regressed: bigger gap gave easier band"

    def test_total_over_extreme_ints(self):
        """Stats are uncapped ints — the mapping must accept anything."""
        assert band_for_gap(-(10**9)) == PlausibilityTier.TRIVIAL
        assert band_for_gap(10**9) == PlausibilityTier.HOPELESS

    def test_only_gap_derived_bands_returned(self):
        """SEALED and IMPOSSIBLE are authored, never produced by arithmetic."""
        produced = {band_for_gap(g) for g in range(-100, 101)}
        assert PlausibilityTier.SEALED not in produced
        assert PlausibilityTier.IMPOSSIBLE not in produced

    def test_full_gap_derived_range_reachable(self):
        produced = {band_for_gap(g) for g in range(-100, 101)}
        assert produced == {
            PlausibilityTier.TRIVIAL,
            PlausibilityTier.ROUTINE,
            PlausibilityTier.RISKY,
            PlausibilityTier.DESPERATE,
            PlausibilityTier.HOPELESS,
        }

    def test_growth_moves_action_down_the_ladder(self):
        """The re-tier toast: same task, bigger stat → easier band."""
        task_difficulty = 12
        weak, strong = 2, 14
        assert band_for_gap(task_difficulty - weak) > band_for_gap(task_difficulty - strong)


class TestOutcomeMapping:
    def test_three_tier_split_for_normal_bands(self):
        for band in (PlausibilityTier.ROUTINE, PlausibilityTier.RISKY, PlausibilityTier.DESPERATE):
            for total in ALL_TOTALS:
                outcome = outcome_for_roll(band, total)
                if total >= 10:
                    assert outcome.tier is OutcomeTier.STRONG_HIT
                elif total >= 7:
                    assert outcome.tier is OutcomeTier.HIT_WITH_COMPLICATION
                else:
                    assert outcome.tier is OutcomeTier.MISS
                assert outcome.hopeless_flavor is None

    def test_hopeless_never_returns_success(self):
        """All-failure band shape: every total is a MISS, no exceptions."""
        for total in ALL_TOTALS:
            outcome = outcome_for_roll(PlausibilityTier.HOPELESS, total)
            assert outcome.tier is OutcomeTier.MISS
            assert outcome.tier is not OutcomeTier.STRONG_HIT
            assert outcome.tier is not OutcomeTier.HIT_WITH_COMPLICATION

    def test_hopeless_roll_selects_failure_flavor_only(self):
        for total in ALL_TOTALS:
            outcome = outcome_for_roll(PlausibilityTier.HOPELESS, total)
            if total >= 10:
                assert outcome.hopeless_flavor is HopelessFlavor.SPARED
            elif total >= 7:
                assert outcome.hopeless_flavor is HopelessFlavor.PUNISHING
            else:
                assert outcome.hopeless_flavor is HopelessFlavor.CATASTROPHIC

    def test_non_rollable_bands_rejected(self):
        for band in (
            PlausibilityTier.TRIVIAL,
            PlausibilityTier.SEALED,
            PlausibilityTier.IMPOSSIBLE,
        ):
            assert band not in ROLLABLE_TIERS
            for total in (2, 7, 12):
                with pytest.raises(ValueError):
                    outcome_for_roll(band, total)

    def test_impossible_totals_rejected(self):
        for total in (0, 1, 13, -3):
            with pytest.raises(ValueError):
                outcome_for_roll(PlausibilityTier.ROUTINE, total)

    def test_rollable_tiers_exact(self):
        assert ROLLABLE_TIERS == {
            PlausibilityTier.ROUTINE,
            PlausibilityTier.RISKY,
            PlausibilityTier.DESPERATE,
            PlausibilityTier.HOPELESS,
        }
