"""Seeded, stream-keyed, replay-deterministic 2d6.

Design goals (binding — see docs/roadmap.md §4 State Architecture):

1. **Replay determinism forever.** Every disputed outcome must be
   re-derivable from the event log. Therefore a roll is a *pure function*
   of ``(world_seed, stream_key, sequence_index)`` — nothing else. Same
   three inputs → same dice, on any machine, in any future version.

2. **Named RNG streams.** Rolls draw from independent streams keyed by
   e.g. ``(character_id, stream_name)``. Adding a new roll site later
   (a new stream, or extra draws on one stream) can NEVER shift the
   sequence of any other stream, because streams share no state.

3. **No hidden generator state.** We deliberately do NOT use
   ``random.Random`` sequences: a stateful generator makes roll N depend
   on every draw before it, which breaks goal 2 the first time anyone
   inserts a roll site. Instead each die is derived from SHA-256 over a
   canonical, versioned, injective encoding of (seed, stream, index).
   Hash output is mapped to 1–6 by rejection sampling (no modulo bias).

The pure function is :func:`roll_2d6`. :class:`DiceRoller` is a thin
convenience wrapper that tracks the next sequence index per stream; its
counters are plain data, snapshot-able for persistence and rebuildable
by replaying the event log (persistence itself is out of engine scope).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["StreamKey", "Roll2d6", "roll_2d6", "DiceRoller"]

# Bump ONLY if the derivation scheme must change; old events stay
# re-derivable because the version is part of the hash preimage.
_SCHEME = b"everquill.dice.v1"

# Type alias: a stream key is an ordered tuple of string parts,
# e.g. ("char:9f2...", "combat") or ("world", "weather"). A bare string
# is accepted anywhere a StreamKey is and is treated as a 1-tuple.
StreamKey = tuple[str, ...]


def _normalize_stream(stream: StreamKey | str) -> StreamKey:
    """Coerce a bare string to a 1-tuple; validate parts are strings."""
    if isinstance(stream, str):
        return (stream,)
    parts = tuple(stream)
    if not parts or not all(isinstance(p, str) for p in parts):
        raise TypeError("stream key must be a non-empty str or tuple of str")
    return parts


def _encode_stream(stream: StreamKey) -> bytes:
    """Injective (length-prefixed) encoding of a stream key.

    Length-prefixing guarantees ("ab", "c") and ("a", "bc") can never
    collide, which separator-joining would allow.
    """
    out = bytearray()
    for part in stream:
        raw = part.encode("utf-8")
        out += b"%d:" % len(raw)
        out += raw
    return bytes(out)


def _die_face(seed: int, stream_bytes: bytes, index: int, die: int) -> int:
    """One unbiased d6 face from SHA-256, by rejection sampling.

    Bytes >= 252 are rejected (252 = 42 * 6 is the largest multiple of 6
    that fits in a byte) so every face is exactly equiprobable. If all 32
    digest bytes are rejected (probability (4/256)**32, i.e. never), the
    preimage is re-hashed with a bumped attempt counter.
    """
    attempt = 0
    while True:
        preimage = b"|".join(
            (
                _SCHEME,
                str(seed).encode("ascii"),
                stream_bytes,
                str(index).encode("ascii"),
                str(die).encode("ascii"),
                str(attempt).encode("ascii"),
            )
        )
        for byte in hashlib.sha256(preimage).digest():
            if byte < 252:
                return byte % 6 + 1
        attempt += 1


@dataclass(frozen=True, slots=True)
class Roll2d6:
    """One resolved 2d6 draw: the auditable record of a dice event.

    The Chronicle shows post-roll dice in full — every death must be
    auditable without trusting prose — so this carries the individual
    faces, the stream, and the sequence index, not just the total.
    """

    stream: StreamKey
    index: int
    die_one: int
    die_two: int

    @property
    def total(self) -> int:
        return self.die_one + self.die_two


def roll_2d6(seed: int, stream: StreamKey | str, index: int) -> Roll2d6:
    """Pure 2d6 draw: ``(seed, stream, index)`` → dice, forever.

    ``seed``   — the world seed (one per world/campaign, an int).
    ``stream`` — named stream key, e.g. ``(character_id, "combat")``.
    ``index``  — 0-based sequence index within that stream (must be >= 0).

    Calling this twice with the same arguments returns equal rolls; no
    call can influence any other (there is no shared state to perturb).
    """
    if index < 0:
        raise ValueError(f"sequence index must be >= 0, got {index}")
    key = _normalize_stream(stream)
    stream_bytes = _encode_stream(key)
    return Roll2d6(
        stream=key,
        index=index,
        die_one=_die_face(seed, stream_bytes, index, die=1),
        die_two=_die_face(seed, stream_bytes, index, die=2),
    )


class DiceRoller:
    """Convenience wrapper: per-stream sequence counters over :func:`roll_2d6`.

    The roller holds NO entropy state — only the next index per stream.
    Counters are exposed via :meth:`counters` as plain data so a caller
    (later, the persistence layer) can snapshot them, and can always be
    rebuilt by counting each stream's rolls in the event log.
    """

    def __init__(
        self,
        seed: int,
        counters: Mapping[StreamKey | str, int] | None = None,
    ) -> None:
        self._seed = seed
        self._counters: dict[StreamKey, int] = {}
        if counters:
            for stream, next_index in counters.items():
                if next_index < 0:
                    raise ValueError(f"counter for {stream!r} must be >= 0")
                self._counters[_normalize_stream(stream)] = next_index

    @property
    def seed(self) -> int:
        return self._seed

    def next_index(self, stream: StreamKey | str) -> int:
        """The sequence index the next :meth:`roll` on this stream will use."""
        return self._counters.get(_normalize_stream(stream), 0)

    def roll(self, stream: StreamKey | str) -> Roll2d6:
        """Draw the next 2d6 on ``stream`` and advance that stream's counter.

        Only the named stream's counter moves; every other stream's
        future sequence is untouched (stream independence).
        """
        key = _normalize_stream(stream)
        index = self._counters.get(key, 0)
        result = roll_2d6(self._seed, key, index)
        self._counters[key] = index + 1
        return result

    def counters(self) -> dict[StreamKey, int]:
        """Snapshot of per-stream next-index counters (a defensive copy)."""
        return dict(self._counters)
