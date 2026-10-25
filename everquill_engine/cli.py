"""Engine CLI — the original fun-or-kill test artifact.

    python -m everquill_engine.cli play content/world/dev-fixture.yaml \
        --seed 42 [--script tests/fixtures/tavern-script.json] [--fresh]

    python -m everquill_engine.cli clock-advance [--minutes N]

``play`` runs the tavern scene against the real Postgres event store:
canned intents (scripted or picked from a numbered menu), Chronicle-
style output — pre-roll assessment in ladder words, post-roll dice +
modifiers in full, deltas listed. State survives restart by
construction (everything is the log + Tier-1 projections).

``clock-advance`` is the manual world-clock sweeper (no daemon in
Sprint 1): optionally advances the clock N minutes, then fires every
due timer deterministically (seed = hash(timer_id, created_event_id)),
each fire idempotent under its 'timer:<key>' command id.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from everquill_engine.chargen import chargen_events, roll_character
from everquill_engine.clock import resolve_timer_fire, world_date
from everquill_engine.db import connect, resolve_database_url
from everquill_engine.events import EventSpec, EventType
from everquill_engine.genesis import content_sha256, genesis_specs
from everquill_engine.resolver import (
    ResolverError,
    contract_id,
    outcome_contract,
    resolve_intent,
)
from everquill_engine.store import (
    due_timers,
    execute_command,
    fresh_reset,
    load_fold_state,
    migrate_and_rebuild,
    stored_content_manifest,
)
from everquill_engine.world import APTITUDES, LOADER_VERSION, WorldContent, load_world

PC_ID = "pc"
PC_STREAM = f"character:{PC_ID}"

#: Player-facing aptitude bands for chargen output — raw numbers are
#: true-sheet data and stay server-side (docs/engine/stats.md).
_APTITUDE_BANDS = ((4, "faint"), (6, "plain"), (8, "sound"), (10, "keen"), (12, "gifted"))


def _aptitude_band(value: int) -> str:
    for ceiling, word in _APTITUDE_BANDS:
        if value <= ceiling:
            return word
    return "uncanny"


def _die(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _canned_intent(
    action_type: str,
    *,
    targets: list[str] | None = None,
    approach: str,
    stat_hint: str | None = None,
    dialogue: dict | None = None,
    duration_hint: dict | None = None,
    transaction: dict | None = None,
    invoked_law_ids: list[str] | None = None,
) -> dict:
    """A complete intent dict conforming to docs/contracts/intent.schema.json.

    Speech turns are one-to-one statements and movement leaves the scene unless
    the caller says otherwise, matching how the parser fills the closed fields."""
    speech = action_type in ("dialogue", "social")
    return {
        "action_type": action_type,
        "target_entity_ids": targets or [],
        "approach": approach,
        "stat_hint": stat_hint,
        "dialogue": dialogue,
        "plausibility_hint": "plausible",
        "duration_hint": duration_hint,
        "ambiguity_flags": [],
        "addressee": "person" if speech else None,
        "speech_act": "statement" if speech else None,
        "topic_ids": [],
        "transaction": transaction,
        "invoked_law_ids": invoked_law_ids or [],
        "movement_scope": "away" if action_type == "movement" else None,
    }


def _build_menu(world: WorldContent, location_id: str) -> list[tuple[str, dict]]:
    """Deterministic canned-intent menu for the current scene."""
    menu: list[tuple[str, dict]] = [
        ("Look around the room", _canned_intent("observation", approach="take in the scene")),
    ]
    for entity in sorted(world.entities_at(location_id), key=lambda e: e.id):
        if entity.kind not in ("npc", "creature"):
            continue
        cid = contract_id(entity.id)
        menu.extend(
            [
                (
                    f"Size up {entity.name}",
                    _canned_intent(
                        "observation",
                        targets=[cid],
                        approach=f"read {entity.name} without being obvious",
                        stat_hint="wits",
                    ),
                ),
                (
                    f"Talk with {entity.name}",
                    _canned_intent(
                        "dialogue",
                        targets=[cid],
                        approach=f"open easy talk with {entity.name}",
                        dialogue={"addressee_id": cid, "quoted_speech": None},
                    ),
                ),
                (
                    f"Win {entity.name} over",
                    _canned_intent(
                        "social",
                        targets=[cid],
                        approach=f"draw {entity.name} out and earn a little trust",
                        stat_hint="presence",
                    ),
                ),
                (
                    f"Ask around about {entity.name}",
                    _canned_intent(
                        "research",
                        targets=[cid],
                        approach=f"work the taproom for what people say about {entity.name}",
                        stat_hint="lore",
                    ),
                ),
                (
                    f"Challenge {entity.name} to arm-wrestling",
                    _canned_intent(
                        "physical",
                        targets=[cid],
                        approach=f"put {entity.name}'s arm to the table",
                        stat_hint="might",
                    ),
                ),
            ]
        )
    menu.extend(
        [
            (
                "Whittle a charm from scrap wood",
                _canned_intent("craft", approach="whittle a small charm by the fire"),
            ),
            (
                # v1 training trains the engine-selected aptitude for the
                # 'train' shape (DEFAULT_STAT_FOR_ACTION: will) — stat_hint
                # is advisory-only, so the label says what
                # the engine will actually do.
                "Train your will until nightfall",
                _canned_intent(
                    "train", approach="drill focus and stillness in the yard",
                    stat_hint="will",
                    # The label's declared end condition now BINDS
                    # (block table: nightfall = next 18:00).
                    duration_hint={
                        "mode": "until_condition", "text": "until nightfall",
                        "until": "dusk", "amount": None, "unit": None,
                    },
                ),
            ),
            (
                "Take a room for the night",
                _canned_intent(
                    "rest",
                    approach="pay for a room and sleep",
                    transaction={"kind": "buy", "price_key": "inn_room_night_copper", "count": 1},
                ),
            ),
            (
                "Swear the hearth-oath",
                _canned_intent(
                    "social",
                    approach="swear a binding hearth-oath over the tavern fire",
                    stat_hint="will",
                    invoked_law_ids=["law_hearth_oath"],
                ),
            ),
            (
                "Levitate above the taproom",
                _canned_intent(
                    "physical",
                    approach="concentrate and levitate off the floorboards",
                    invoked_law_ids=["law_unwritten_flight"],
                ),
            ),
        ]
    )
    return menu


def _turn_count(cur) -> int:
    cur.execute(
        "SELECT count(*) FROM event WHERE stream_id = %s AND event_type = %s",
        (PC_STREAM, "intent_parsed"),
    )
    return cur.fetchone()[0]


def _genesis(conn, world: WorldContent, seed: int) -> None:
    # genesis_specs (shared with the test harness) includes the content-drift
    # content_manifest event and hp seeds for damageable entities.
    result = execute_command(conn, "genesis", lambda _state: genesis_specs(world, seed))
    if not result.absorbed:
        print(f"[World committed: {len(world.locations)} locations, "
              f"{len(world.entities)} entities]")


def _chargen(conn, world: WorldContent, seed: int, world_time: int) -> None:
    start = next(
        (loc for loc in world.locations.values() if loc.type == "tavern"),
        next(iter(world.locations.values())),
    )
    rolled = roll_character(seed, PC_ID, name="the Quill-touched")
    specs = chargen_events(
        rolled, location_id=start.id, region=start.region, world_time=world_time
    )
    result = execute_command(conn, f"chargen:{PC_ID}", lambda _state: specs)
    if result.absorbed:
        return
    print("[The Quill turns a page. You wake.]")
    for aptitude in APTITUDES:
        print(f"  {aptitude:<9} {_aptitude_band(rolled.aptitudes[aptitude])}")
    print(f"[You come to yourself in {start.name}. {world_date(world_time)}.]")


def _verify_content_manifest(conn, world: WorldContent) -> str | None:
    """Content-drift world-open check. Returns an error string to refuse on,
    None to proceed (possibly after printing a warning)."""
    with conn.transaction():
        with conn.cursor() as cur:
            manifest = stored_content_manifest(cur)
    if manifest is None:
        print("[warning: this world predates content manifests — authored-content "
              "drift cannot be verified]")
        return None
    actual = content_sha256(world.source)
    if manifest["sha256"] != actual:
        if os.environ.get("EVERQUILL_ALLOW_CONTENT_DRIFT") == "1":
            print("[WARNING: CONTENT DRIFT — the world YAML no longer matches the "
                  f"hash committed at genesis ({manifest['sha256'][:12]}… vs "
                  f"{actual[:12]}…). EVERQUILL_ALLOW_CONTENT_DRIFT=1 is set, "
                  "proceeding anyway. Rulings may not match this world's canon.]")
            return None
        return (
            f"authored content drift: {Path(world.source).name} hashes {actual[:12]}… "
            f"but this world was committed against {manifest['sha256'][:12]}…. "
            "Editing authored truth under the same filename changes rulings in an "
            "existing world without a canon event. Restore the original file, commit "
            "a new world, or set EVERQUILL_ALLOW_CONTENT_DRIFT=1 to override (dev only)."
        )
    if manifest.get("loader_version") != LOADER_VERSION:
        print(f"[note: world committed under loader {manifest.get('loader_version')!r}; "
              f"current loader is {LOADER_VERSION!r} — same bytes, newer interpreter]")
    return None


def _play_turn(conn, world: WorldContent, intent: dict, *, show_contract: bool) -> bool:
    """Resolve + commit one canned intent. Returns False when refused."""
    # Pre-reads in their own committed transaction: execute_command owns
    # the top-level transaction and refuses ambient ones.
    with conn.transaction():
        with conn.cursor() as cur:
            pre = load_fold_state(cur)
            turn = _turn_count(cur) + 1
    if pre.characters.get(PC_ID) is None or pre.world is None:
        raise RuntimeError("world/character missing — genesis must run before turns")
    # Client-deterministic command id with a world-generation component
    # (the seed): a replayed script against a fresh-reset world reuses
    # ids by design (determinism); a different world generation in the
    # same database can never collide with stale rows.
    command_id = f"turn_{PC_ID}_g{pre.world['seed']}_{turn}"

    outcome: dict = {}

    def resolve_fn(state):
        actor = state.characters.get(PC_ID)
        if actor is None or state.world is None:
            raise RuntimeError("world/character missing — genesis must run before turns")
        resolution = resolve_intent(
            intent=intent,
            actor=actor,
            world=world,
            manifest=state.manifest,
            entity_states=state.entities,
            reputation=state.reputation,
            deeds=state.deeds,
            world_time=state.world["world_time"],
            rng_counters=state.world["rng_counters"],
            seed=state.world["seed"],
            turn=turn,
        )
        outcome["resolution"] = resolution
        return list(resolution.events)

    try:
        result = execute_command(conn, command_id, resolve_fn)
    except ResolverError as exc:
        print(f"  [The world does not parse that: {exc}]")
        return False
    if result.absorbed:
        print("  [Already chronicled — duplicate command absorbed, nothing rolled twice.]")
        return False
    resolution = outcome["resolution"]
    for line in resolution.summary:
        print("  " + line)
    if show_contract:
        outcome_row = result.event_rows[resolution.outcome_event_index]
        print("  outcome.json: " + json.dumps(outcome_contract(outcome_row), sort_keys=True))
    return True


def cmd_play(args) -> int:
    if not resolve_database_url():
        return _die(
            "DATABASE_URL is not set (env or repo-root .env). "
            "The referee needs the dev Postgres."
        )
    try:
        world = load_world(args.world)
    except Exception as exc:  # WorldContentError carries file:line:[id]
        return _die(str(exc))

    with connect() as conn:
        migrate_and_rebuild(conn)
        if args.fresh:
            fresh_reset(conn)
            print("[--fresh: event log and projections wiped (dev only)]")

        with conn.transaction():
            with conn.cursor() as cur:
                state = load_fold_state(cur)
        if state.world is None:
            _genesis(conn, world, args.seed)
        else:
            if args.seed is not None and args.seed != state.world["seed"]:
                print(
                    f"[note: world already exists with seed {state.world['seed']}; "
                    f"--seed {args.seed} ignored]"
                )
            # Opening an existing world verifies the authored
            # content still matches the manifest committed at genesis.
            drift_error = _verify_content_manifest(conn, world)
            if drift_error:
                return _die(drift_error)
        with conn.transaction():
            with conn.cursor() as cur:
                state = load_fold_state(cur)
        if PC_ID not in state.characters:
            _chargen(conn, world, state.world["seed"], state.world["world_time"])
        with conn.transaction():
            with conn.cursor() as cur:
                state = load_fold_state(cur)

        actor = state.characters[PC_ID]
        location = world.locations.get(actor["location_id"])
        present = [
            row["name"]
            for eid, row in sorted(state.manifest.items())
            if row["location_id"] == actor["location_id"] and eid != PC_ID
            and row["kind"] in ("npc", "creature")
        ]
        print(f"\n== {location.name if location else actor['location_id']} — "
              f"{world_date(state.world['world_time'])} ==")
        if present:
            print("Present: " + ", ".join(present))

        if args.script:
            script = json.loads(Path(args.script).read_text(encoding="utf-8"))
            intents = script["intents"] if isinstance(script, dict) else script
            for i, entry in enumerate(intents, start=1):
                label = entry.get("label") if isinstance(entry, dict) and "label" in entry else None
                intent = entry["intent"] if isinstance(entry, dict) and "intent" in entry else entry
                print(f"\n> {i}. {label or intent['approach']}")
                _play_turn(conn, world, intent, show_contract=args.contract)
            return 0

        # Interactive: numbered canned intents.
        menu = _build_menu(world, actor["location_id"])
        while True:
            print("\nCanned intents:")
            for i, (label, _) in enumerate(menu, start=1):
                print(f"  {i:>2}. {label}")
            try:
                choice = input("> intent # (q to quit): ").strip()
            except EOFError:
                return 0
            if choice.lower() in ("q", "quit", "exit", ""):
                return 0
            if not choice.isdigit() or not 1 <= int(choice) <= len(menu):
                print("  [pick a number from the list]")
                continue
            label, intent = menu[int(choice) - 1]
            print(f"\n> {label}")
            _play_turn(conn, world, intent, show_contract=args.contract)
    return 0


def cmd_clock_advance(args) -> int:
    if not resolve_database_url():
        return _die("DATABASE_URL is not set (env or repo-root .env).")
    with connect() as conn:
        migrate_and_rebuild(conn)
        with conn.transaction():
            with conn.cursor() as cur:
                state = load_fold_state(cur)
        if state.world is None:
            return _die("no world in the event store yet — run play first")
        world_time = state.world["world_time"]

        if args.minutes:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT coalesce(max(stream_version), 0) FROM event"
                        " WHERE stream_id = 'world'"
                    )
                    next_world_version = cur.fetchone()[0] + 1
            world_time += args.minutes
            minutes = args.minutes

            def advance_fn(state, world_time=world_time, minutes=minutes):
                return [
                    EventSpec(
                        stream_id="world",
                        event_type=EventType.TIME_ADVANCED,
                        world_time=world_time,
                        payload={"minutes": minutes},
                    )
                ]

            execute_command(conn, f"clockadv_{next_world_version}", advance_fn)
            print(f"[Clock advanced {args.minutes} min -> {world_date(world_time)}]")

        fired = 0
        # Fire ALL overdue, in (world_due, created_event_id) order, no grace
        # cutoff ever (synthesis downtime policy). Each fire = its own
        # command transaction through execute_command (world lock held while
        # its rng counters merge — world-lock).
        with conn.transaction():
            timers = due_timers(conn, world_time)
        for timer in timers:
            fire = resolve_timer_fire(timer, timer["created_event_id"])
            owner = timer["payload"]["owner_id"]
            spec = EventSpec(
                stream_id=f"character:{owner}",
                event_type=EventType.TIMER_COMPLETED,
                world_time=timer["world_due"],  # stamped at world_due, always
                rng=fire["rng"],
                payload={
                    "timer_key": timer["timer_key"],
                    "kind": timer["kind"],
                    "owner_id": owner,
                    "completed_at_world_time": timer["world_due"],
                    "gains": fire["gains"],
                    "skipped": False,
                },
            )
            result = execute_command(
                conn, f"timer:{timer['timer_key']}", lambda _state, spec=spec: [spec]
            )
            if not result.absorbed:
                fired += 1
                gains = ", ".join(
                    f"{g.get('aptitude', g.get('flag_key', '?'))} "
                    f"{'+' + str(g['amount']) if 'amount' in g else 'set'}"
                    for g in fire["gains"]
                )
                print(
                    f"[Timer fired: {timer['timer_key']} ({timer['kind']}) "
                    f"at {world_date(timer['world_due'])} — {gains}]"
                )
        if fired == 0:
            print("[No due timers]")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m everquill_engine.cli",
        description="Everquill referee CLI — play the tavern, advance the clock.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="play a world file with canned intents")
    play.add_argument("world", help="world-content YAML (e.g. content/world/dev-fixture.yaml)")
    play.add_argument("--seed", type=int, default=42, help="world seed (genesis only)")
    play.add_argument("--script", help="JSON file of canned intents (non-interactive)")
    play.add_argument("--fresh", action="store_true",
                      help="DEV ONLY: wipe log + projections first")
    play.add_argument("--contract", action="store_true",
                      help="also print each outcome as its contract JSON")
    play.set_defaults(func=cmd_play)

    clock = sub.add_parser("clock-advance", help="advance world clock and fire due timers")
    clock.add_argument("--minutes", type=int, default=0, help="advance the clock N world-minutes")
    clock.set_defaults(func=cmd_clock_advance)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
