"""KNOWN-state reads for the API.

The API may consume ONLY the KnownState surface (docs/engine/known-state.md);
``load_fold_state`` / ``RefereeState`` are lint-forbidden in ``api/``. The one
sanctioned way to see a fold image is the state ``store.execute_command``
hands to ``resolve_fn`` inside its own locked transaction — so a read is
expressed as a command that extracts the KnownState and then aborts before
appending anything. The transaction rolls back; no event, no state change,
no command-id namespace growth (the random ``read:`` id is never stored).

This costs one world-lock acquisition per read — fine at alpha scale, and it
means the extracted view is always a consistent post-commit snapshot.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from everquill_engine.slots import load_slot_maps
from everquill_engine.store import execute_command
from everquill_engine.views import KnownState, SelfFacts, load_known_state, self_view
from everquill_engine.world import WorldContent

# Slot maps are authored content (content/world/slots.yaml) — load once per
# process; the loader tolerates absence.
_SLOT_MAPS = None


@dataclass(frozen=True, slots=True)
class ChargenStatus:
    seed: int
    world_time: int
    character_exists: bool


def _slot_maps():
    global _SLOT_MAPS
    if _SLOT_MAPS is None:
        _SLOT_MAPS = load_slot_maps()
    return _SLOT_MAPS


class _KnownStateCapture(Exception):
    """Control-flow carrier: aborts the read command with the extracted view."""

    def __init__(self, known: KnownState) -> None:
        self.known = known


def read_known_state(conn, world: WorldContent) -> KnownState:
    """A consistent KnownState snapshot of the connection's current world.

    Respects the connection's search_path, so with a per-account schema set
    this reads that account's world.
    """
    for _ in range(2):  # second try only on an astronomically unlikely id collision
        command_id = f"read:{secrets.token_hex(8)}"

        def capture(state):
            raise _KnownStateCapture(load_known_state(state, world, _slot_maps()))

        try:
            result = execute_command(conn, command_id, capture)
        except _KnownStateCapture as cap:
            return cap.known
        if not result.absorbed:  # pragma: no cover - capture always raises
            raise RuntimeError("read command completed without capturing state")
    raise RuntimeError("could not obtain a free read command id")  # pragma: no cover


class _SelfCapture(Exception):
    """Control-flow carrier: aborts the read command with the Self view."""

    def __init__(self, me: SelfFacts | None) -> None:
        self.me = me


def read_self(conn, world: WorldContent, character_id: str) -> SelfFacts | None:
    """A consistent Self-view snapshot of the connection's world —
    the player's own build plus their earned standing. Same sanctioned
    fold-capture path as read_known_state (the ``state`` is the fold image
    execute_command hands us; self_view is a KnownState-side view function).
    None when the world has no character yet."""
    for _ in range(2):  # second try only on an astronomically unlikely id collision
        command_id = f"read:{secrets.token_hex(8)}"

        def capture(state):
            raise _SelfCapture(self_view(state, character_id))

        try:
            result = execute_command(conn, command_id, capture)
        except _SelfCapture as cap:
            return cap.me
        if not result.absorbed:  # pragma: no cover - capture always raises
            raise RuntimeError("read command completed without capturing state")
    raise RuntimeError("could not obtain a free read command id")  # pragma: no cover


class _ChargenStatusCapture(Exception):
    """Control-flow carrier: aborts the read command with chargen state."""

    def __init__(self, status: ChargenStatus) -> None:
        self.status = status


def read_chargen_status(conn, world: WorldContent, character_id: str) -> ChargenStatus:
    """A consistent chargen status snapshot via the same read-command pattern.

    The API needs only world seed/time plus whether character_created already
    folded. The full fold image stays inside store.execute_command.
    """
    for _ in range(2):
        command_id = f"read:{secrets.token_hex(8)}"

        def capture(state):
            if state.world is None:
                raise RuntimeError("genesis must exist before chargen reads")
            raise _ChargenStatusCapture(
                ChargenStatus(
                    seed=state.world["seed"],
                    world_time=state.world["world_time"],
                    character_exists=character_id in state.characters,
                )
            )

        try:
            result = execute_command(conn, command_id, capture)
        except _ChargenStatusCapture as cap:
            return cap.status
        if not result.absorbed:  # pragma: no cover - capture always raises
            raise RuntimeError("read command completed without capturing state")
    raise RuntimeError("could not obtain a free read command id")  # pragma: no cover
