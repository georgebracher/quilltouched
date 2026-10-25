"""World bootstrap: genesis + dev chargen when the DB is empty.

Uses the engine's shared authorities — ``genesis_specs`` (ONE genesis
shape for CLI, harness and API; includes the content_manifest
event and hp seeds) and ``execute_command`` (world lock,
idempotency probe, one internal retry). Command ids match the CLI
(``genesis``, ``chargen:pc``), so a world initialized by either path is
the SAME world and re-running either is absorbed as a duplicate.

Boundary note: this module no longer reads fold state.
Idempotency comes entirely from ``execute_command``'s command-id
absorption — ``genesis`` / ``chargen:pc`` re-runs are no-ops — and the
fold image chargen needs (seed, world clock) arrives via the state
handed to ``resolve_fn`` inside the store's own transaction, never
through a referee-surface import.

With per-account worlds (interface decision 1) this bootstrap runs once
per Postgres world schema: the caller sets the connection's search_path
to the account's schema first (api/accounts.py), so the same shared
content YAML genesis lands in every account's own event log.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from everquill_engine.chargen import chargen_events, roll_character
from everquill_engine.genesis import content_sha256, genesis_specs
from everquill_engine.store import execute_command, stored_content_manifest

PC_ID = "pc"


def starting_location(world):
    """Authoritative starting location for the account PC."""
    return next(
        (loc for loc in world.locations.values() if loc.type == "tavern"),
        next(iter(world.locations.values())),
    )


def bootstrap_genesis(conn, world, seed: int) -> dict[str, Any]:
    """Idempotently ensure world genesis exists, without creating the PC.

    Guided chargen uses this path: world + locations + entities are committed
    first, and the character_created event is appended later by /api/chargen.
    """
    summary: dict[str, Any] = {
        "world_file": Path(world.source).name,
        "genesis_applied": False,
        "chargen_applied": False,
        "content_drift": None,
        "content_manifest_missing": False,
    }

    # Genesis: absorbed as a duplicate when the world already exists (the
    # 'genesis' command id is shared with the CLI).
    result = execute_command(conn, "genesis", lambda _state: genesis_specs(world, seed))
    summary["genesis_applied"] = not result.absorbed

    # Committed content manifest vs the configured world YAML.
    with conn.transaction():
        with conn.cursor() as cur:
            manifest = stored_content_manifest(cur)

    if manifest is None:
        summary["content_manifest_missing"] = True
    else:
        actual = content_sha256(world.source)
        if manifest["sha256"] != actual:
            summary["content_drift"] = {
                "committed_sha256": manifest["sha256"],
                "current_sha256": actual,
                "committed_source": manifest.get("content_source"),
            }

    return summary


def bootstrap(conn, world, seed: int) -> dict[str, Any]:
    """Idempotently ensure genesis + the dev PC exist. Returns a summary dict.

    ``content_drift`` in the summary is the content-drift check: set (with the
    stored vs actual hashes) when the DB world's committed content manifest
    no longer matches the configured world YAML — the API must then refuse
    to resolve actions against drifted authored truth (503, not silent
    re-ruling). ``content_manifest_missing`` marks pre-manifest worlds.
    """
    summary = bootstrap_genesis(conn, world, seed)

    if summary["content_drift"] is None:
        start = starting_location(world)

        def chargen_fn(state):
            # state is the fold image execute_command loads under the world
            # lock — the sanctioned way to see seed/clock without importing
            # the referee surface.
            if state.world is None:
                raise ValueError("genesis must land before chargen")
            rolled = roll_character(state.world["seed"], PC_ID, name="the Quill-touched")
            return chargen_events(
                rolled,
                location_id=start.id,
                region=start.region,
                world_time=state.world["world_time"],
            )

        result = execute_command(conn, f"chargen:{PC_ID}", chargen_fn)
        summary["chargen_applied"] = not result.absorbed

    return summary
