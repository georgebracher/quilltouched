"""In-memory test harness: genesis + chargen + turns without a database.

Shares the CLI's genesis spec builder (everquill_engine.genesis) and
the store's event_ref substitution so pure tests fold exactly what the
DB would store (minus DB-assigned ids, which are simulated
sequentially — the same values a fresh database produces).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from everquill_engine.chargen import chargen_events, roll_character
from everquill_engine.folds import FoldState, fold_event
from everquill_engine.genesis import genesis_specs
from everquill_engine.resolver import resolve_intent
from everquill_engine.store import _substitute_event_refs
from everquill_engine.world import WorldContent, load_world

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_WORLD = REPO_ROOT / "content" / "world" / "dev-fixture.yaml"
SCRIPT_PATH = REPO_ROOT / "tests" / "fixtures" / "tavern-script.json"
CONTRACTS = REPO_ROOT / "docs" / "contracts"


def load_script() -> list[dict[str, Any]]:
    return json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))["intents"]


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def intent_schema_v11() -> dict[str, Any]:
    """intent.schema.json with the LOCKED v1.1 'rest' addition.

    interface decision #2: the LLM layer owns the schema file edit;
    until it lands, tests validate against the locked target vocabulary
    by patching 'rest' into a copy of the v1 enum.
    """
    schema = load_schema("intent.schema.json")
    enum = schema["properties"]["action_type"]["enum"]
    if "rest" not in enum:
        enum.append("rest")
    return schema


class Sim:
    """Deterministic in-memory world: same folds, simulated event ids."""

    def __init__(self, seed: int = 42, world_path: Path = FIXTURE_WORLD) -> None:
        self.seed = seed
        self.world: WorldContent = load_world(world_path)
        self.state = FoldState()
        self.next_id = 0
        self.turn = 0
        self.rows: list[dict[str, Any]] = []
        self._genesis()
        self._chargen()

    # -- plumbing ---------------------------------------------------------

    def apply_specs(self, specs) -> list[dict[str, Any]]:
        inserted: list[int] = []
        rows = []
        for spec in specs:
            self.next_id += 1
            payload = _substitute_event_refs(
                json.loads(json.dumps(dict(spec.payload))), inserted
            )
            row = {
                "id": self.next_id,
                "stream_id": spec.stream_id,
                "stream_version": 0,  # not used by folds
                "world_time": spec.world_time,
                "event_type": str(spec.event_type),
                "location_id": spec.location_id,
                "command_id": f"sim_{self.next_id}",
                "rng": dict(spec.rng) if spec.rng is not None else None,
                "payload": payload,
                "payload_version": spec.payload_version,
            }
            inserted.append(self.next_id)
            fold_event(self.state, row)
            rows.append(row)
            self.rows.append(row)
        return rows

    def _genesis(self) -> None:
        # ONE genesis authority (everquill_engine.genesis) shared with the
        # CLI: content_manifest + damageable-entity hp seeds included.
        self.apply_specs(genesis_specs(self.world, self.seed))

    def _chargen(self) -> None:
        start = next(iter(self.world.locations.values()))
        rolled = roll_character(self.seed, "pc", name="the Quill-touched")
        self.apply_specs(
            chargen_events(
                rolled, location_id=start.id, region=start.region, world_time=0
            )
        )

    # -- play --------------------------------------------------------------

    @property
    def pc(self) -> dict[str, Any]:
        return self.state.characters["pc"]

    def run_turn(self, intent: dict[str, Any]):
        self.turn += 1
        resolution = resolve_intent(
            intent=intent,
            actor=self.pc,
            world=self.world,
            manifest=self.state.manifest,
            entity_states=self.state.entities,
            reputation=self.state.reputation,
            deeds=self.state.deeds,
            world_time=self.state.world["world_time"],
            rng_counters=self.state.world["rng_counters"],
            seed=self.seed,
            turn=self.turn,
        )
        rows = self.apply_specs(resolution.events)
        outcome_row = rows[resolution.outcome_event_index]
        return resolution, outcome_row
