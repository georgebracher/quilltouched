"""Property-style tests for replay-deterministic, stream-keyed dice."""

import pytest

from everquill_engine.dice import DiceRoller, roll_2d6

SEED = 20260713
STREAMS = [
    ("char:ald", "combat"),
    ("char:ald", "social"),
    ("char:mira", "combat"),
    ("world", "weather"),
]


class TestDeterminism:
    def test_same_seed_stream_index_same_roll(self):
        """Same (seed, stream, index) → identical dice, every time."""
        for stream in STREAMS:
            for index in range(200):
                a = roll_2d6(SEED, stream, index)
                b = roll_2d6(SEED, stream, index)
                assert a == b
                assert (a.die_one, a.die_two) == (b.die_one, b.die_two)

    def test_random_access_matches_sequential(self):
        """Index-addressed draws equal roller-sequential draws (replay)."""
        roller = DiceRoller(SEED)
        sequential = [roller.roll(("char:ald", "combat")) for _ in range(50)]
        for i, roll in enumerate(sequential):
            assert roll == roll_2d6(SEED, ("char:ald", "combat"), i)
            assert roll.index == i

    def test_pinned_values_never_drift(self):
        """Regression pin: these exact dice must reproduce forever.

        If this test ever fails, replay determinism is broken and every
        historical event log is unverifiable. Do not update the pins;
        fix the code (or bump the scheme version and keep v1 readable).
        """
        pinned = [roll_2d6(20260713, ("char:ald", "combat"), i) for i in range(5)]
        assert [(r.die_one, r.die_two) for r in pinned] == [
            (2, 6),
            (4, 4),
            (6, 2),
            (5, 3),
            (2, 1),
        ]

    def test_different_seeds_diverge(self):
        stream = ("char:ald", "combat")
        a = [roll_2d6(SEED, stream, i) for i in range(100)]
        b = [roll_2d6(SEED + 1, stream, i) for i in range(100)]
        assert [(r.die_one, r.die_two) for r in a] != [(r.die_one, r.die_two) for r in b]

    def test_different_indices_diverge(self):
        stream = ("char:ald", "combat")
        faces = {(roll_2d6(SEED, stream, i).die_one, roll_2d6(SEED, stream, i).die_two)
                 for i in range(100)}
        assert len(faces) > 1


class TestStreamIndependence:
    def test_interleaved_draws_never_shift_another_stream(self):
        """Drawing from stream X never changes stream Y's sequence.

        This is the guarantee that lets us add new roll sites in later
        sprints without shifting existing streams.
        """
        x, y = ("char:ald", "combat"), ("char:mira", "combat")

        clean = DiceRoller(SEED)
        y_alone = [clean.roll(y) for _ in range(30)]

        noisy = DiceRoller(SEED)
        y_interleaved = []
        for i in range(30):
            for _ in range(i % 4):          # varying bursts of X noise
                noisy.roll(x)
            y_interleaved.append(noisy.roll(y))

        assert y_alone == y_interleaved

    def test_distinct_streams_have_distinct_sequences(self):
        rolls = {
            stream: [(r.die_one, r.die_two) for r in (roll_2d6(SEED, stream, i) for i in range(50))]
            for stream in STREAMS
        }
        sequences = list(rolls.values())
        for i in range(len(sequences)):
            for j in range(i + 1, len(sequences)):
                assert sequences[i] != sequences[j]

    def test_stream_key_encoding_is_injective(self):
        """("ab","c") and ("a","bc") must be different streams."""
        a = [roll_2d6(SEED, ("ab", "c"), i) for i in range(50)]
        b = [roll_2d6(SEED, ("a", "bc"), i) for i in range(50)]
        assert [(r.die_one, r.die_two) for r in a] != [(r.die_one, r.die_two) for r in b]

    def test_bare_string_stream_equals_one_tuple(self):
        assert roll_2d6(SEED, "world", 7) == roll_2d6(SEED, ("world",), 7)


class TestRollShape:
    def test_faces_in_range_and_total_consistent(self):
        for stream in STREAMS:
            for i in range(500):
                r = roll_2d6(SEED, stream, i)
                assert 1 <= r.die_one <= 6
                assert 1 <= r.die_two <= 6
                assert r.total == r.die_one + r.die_two
                assert 2 <= r.total <= 12

    def test_all_faces_reachable(self):
        seen = set()
        for i in range(2000):
            r = roll_2d6(SEED, ("coverage",), i)
            seen.add(r.die_one)
            seen.add(r.die_two)
        assert seen == {1, 2, 3, 4, 5, 6}

    def test_negative_index_rejected(self):
        with pytest.raises(ValueError):
            roll_2d6(SEED, ("char:ald", "combat"), -1)

    def test_empty_stream_rejected(self):
        with pytest.raises(TypeError):
            roll_2d6(SEED, (), 0)


class TestRollerCounters:
    def test_counters_snapshot_and_resume(self):
        """A roller restored from counters continues the exact sequence."""
        first = DiceRoller(SEED)
        for _ in range(10):
            first.roll(("char:ald", "combat"))
        first.roll(("world", "weather"))
        snapshot = first.counters()

        resumed = DiceRoller(SEED, counters=snapshot)
        assert resumed.roll(("char:ald", "combat")) == roll_2d6(
            SEED, ("char:ald", "combat"), 10
        )
        assert resumed.roll(("world", "weather")) == roll_2d6(SEED, ("world", "weather"), 1)

    def test_counters_returns_copy(self):
        roller = DiceRoller(SEED)
        roller.roll(("char:ald", "combat"))
        snap = roller.counters()
        snap[("char:ald", "combat")] = 999
        assert roller.next_index(("char:ald", "combat")) == 1

    def test_next_index_does_not_advance(self):
        roller = DiceRoller(SEED)
        assert roller.next_index("fresh") == 0
        assert roller.next_index("fresh") == 0
        roller.roll("fresh")
        assert roller.next_index("fresh") == 1
