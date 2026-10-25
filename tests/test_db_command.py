"""S1 review-fix cluster, DB-integration side (skips without DATABASE_URL).

Covers: execute_command orchestration (ambient-transaction guard,
absorb-before-resolve, retry-once), world-lock interleaving,
append-time domain-id rejection, rebuild-stable timer
fire order, entity_state persistence/resolution/rebuild, and
content-manifest verification.
"""

from __future__ import annotations

import threading
from datetime import datetime

import pytest

from everquill_engine.chargen import chargen_events, roll_character
from everquill_engine.clock import real_due_at
from everquill_engine.events import EventSpec, EventType, event_ref
from everquill_engine.genesis import content_sha256, genesis_specs
from everquill_engine.ladder import PlausibilityTier
from everquill_engine.resolver import resolve_intent
from everquill_engine.store import (
    AmbientTransactionError,
    ConcurrencyError,
    DuplicateDomainIdError,
    append_command,
    canonical_projection_dump,
    due_timers,
    execute_command,
    fresh_reset,
    load_fold_state,
    rebuild_projections,
    stored_content_manifest,
)
from everquill_engine.views import self_view
from everquill_engine.world import LOADER_VERSION, load_world
from tests.harness import FIXTURE_WORLD

WORLD = load_world(FIXTURE_WORLD)
SEED = 42


def canned(action_type, targets=(), approach="do the thing", stat_hint=None):
    return {
        "action_type": action_type,
        "target_entity_ids": list(targets),
        "approach": approach,
        "stat_hint": stat_hint,
        "dialogue": None,
        "plausibility_hint": "plausible",
        "duration_hint": None,
        "ambiguity_flags": [],
        "addressee": None,
        "speech_act": None,
        "topic_ids": [],
        "transaction": None,
        "invoked_law_ids": [],
        "movement_scope": None,
    }


def _chargen(conn, character_id: str, seed: int = SEED) -> None:
    rolled = roll_character(seed, character_id, name=f"the {character_id}")
    specs = chargen_events(
        rolled, location_id="loc.dev.tavern", region="dev", world_time=0
    )
    execute_command(conn, f"chargen:{character_id}", lambda _s: specs)


def _turn(conn, intent, command_id, *, actor_id="pc", turn=1):
    holder = {}

    def resolve_fn(state):
        resolution = resolve_intent(
            intent=intent,
            actor=state.characters[actor_id],
            world=WORLD,
            manifest=state.manifest,
            entity_states=state.entities,
            reputation=state.reputation,
            deeds=state.deeds,
            world_time=state.world["world_time"],
            rng_counters=state.world["rng_counters"],
            seed=state.world["seed"],
            turn=turn,
        )
        holder["res"] = resolution
        return list(resolution.events)

    result = execute_command(conn, command_id, resolve_fn)
    return result, holder.get("res")


def _state(conn):
    with conn.transaction():
        with conn.cursor() as cur:
            return load_fold_state(cur)


def _count_events(conn) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM event")
            return cur.fetchone()[0]


@pytest.fixture()
def world_conn(db_conn):
    fresh_reset(db_conn)
    execute_command(db_conn, "genesis", lambda _s: genesis_specs(WORLD, SEED))
    _chargen(db_conn, "pc")
    return db_conn


class TestDeedRenownFeed:
    def test_notorious_deed_raises_renown_and_survives_rebuild(self, world_conn):
        _result, resolution = _turn(
            world_conn,
            canned("physical", ["npc_dev_torvald"], "challenge Torvald", "might"),
            "renown_deed",
        )
        deltas = resolution.events[resolution.outcome_event_index].payload["state_deltas"]
        assert any(
            delta["delta_type"] == "reputation"
            and delta["scope"] == "renown"
            and delta["amount"] == 2
            for delta in deltas
        )

        before = self_view(_state(world_conn), "pc")
        assert before.renown == 2

        rebuild_projections(world_conn)

        after = self_view(_state(world_conn), "pc")
        assert after.renown == before.renown == 2

    def test_no_deed_action_does_not_raise_renown(self, world_conn):
        _turn(world_conn, canned("observation", approach="look around"), "renown_none")

        assert self_view(_state(world_conn), "pc").renown == 0


class TestExecuteCommand:
    def test_duplicate_command_absorbed_before_resolving(self, world_conn):
        calls = []

        def counting(intent):
            def resolve_fn(state):
                calls.append(1)
                resolution = resolve_intent(
                    intent=intent, actor=state.characters["pc"], world=WORLD,
                    manifest=state.manifest, entity_states=state.entities,
                    world_time=state.world["world_time"],
                    rng_counters=state.world["rng_counters"],
                    seed=state.world["seed"], turn=1,
                )
                return list(resolution.events)
            return resolve_fn

        intent = canned("physical", ["npc_dev_hedda"], "arm-wrestle")
        first = execute_command(world_conn, "turn_pc_g42_1", counting(intent))
        assert not first.absorbed and len(calls) == 1
        second = execute_command(world_conn, "turn_pc_g42_1", counting(intent))
        assert second.absorbed and second.event_rows == ()
        assert len(calls) == 1  # duplicate absorbed WITHOUT re-resolving

    def test_ambient_transaction_is_rejected(self, world_conn):
        with world_conn.cursor() as cur:
            cur.execute("SELECT 1")  # opens an implicit transaction
        with pytest.raises(AmbientTransactionError):
            execute_command(world_conn, "turn_pc_g42_9", lambda _s: [])
        world_conn.rollback()
        assert _count_events(world_conn) > 0  # connection still usable

    def test_concurrency_error_reloads_and_reresolves_once(self, world_conn, monkeypatch):
        import everquill_engine.store as store_mod

        real = store_mod._append_in_cursor
        failures = {"n": 0}

        def flaky(cur, command_id, specs, **kwargs):
            if failures["n"] == 0:
                failures["n"] += 1
                raise ConcurrencyError("simulated stream race")
            return real(cur, command_id, specs, **kwargs)

        monkeypatch.setattr(store_mod, "_append_in_cursor", flaky)
        calls = []

        def resolve_fn(state):
            calls.append(state.world["world_time"])
            resolution = resolve_intent(
                intent=canned("physical", ["npc_dev_hedda"], "arm-wrestle"),
                actor=state.characters["pc"], world=WORLD,
                manifest=state.manifest, entity_states=state.entities,
                world_time=state.world["world_time"],
                rng_counters=state.world["rng_counters"],
                seed=state.world["seed"], turn=1,
            )
            return list(resolution.events)

        result = execute_command(world_conn, "turn_pc_g42_1", resolve_fn)
        assert not result.absorbed
        assert len(calls) == 2  # re-resolved exactly once, same command id
        assert all(row["command_id"] == "turn_pc_g42_1" for row in result.event_rows)

    def test_second_concurrency_failure_propagates(self, world_conn, monkeypatch):
        import everquill_engine.store as store_mod

        def always_racing(cur, command_id, specs, **kwargs):
            raise ConcurrencyError("permanent race")

        monkeypatch.setattr(store_mod, "_append_in_cursor", always_racing)
        calls = []

        def resolve_fn(state):
            calls.append(1)
            return [EventSpec(stream_id="character:pc",
                              event_type=EventType.INTENT_PARSED, world_time=0)]

        with pytest.raises(ConcurrencyError):
            execute_command(world_conn, "turn_pc_g42_2", resolve_fn)
        assert len(calls) == 2  # one retry, then give up


class TestWorldLockInterleaving:
    """Two characters' commands interleaved from two connections —
    world time accumulates (10 + 15), never collapses to max()."""

    def test_interleaved_commands_accumulate_world_time(self, db_conn, db_url):
        from everquill_engine.db import connect

        fresh_reset(db_conn)
        execute_command(db_conn, "genesis", lambda _s: genesis_specs(WORLD, SEED))
        _chargen(db_conn, "pca")
        _chargen(db_conn, "pcb")

        barrier = threading.Barrier(2, timeout=30)
        errors: list[Exception] = []

        def worker(actor_id, intent, command_id):
            try:
                with connect(db_url) as conn:
                    barrier.wait()
                    _turn(conn, intent, command_id, actor_id=actor_id, turn=1)
            except Exception as exc:  # pragma: no cover - failure reporting
                errors.append(exc)

        # Both target Torvald (threat 20, will 14): physical is HOPELESS
        # and social at worst HOPELESS for ANY chargen roll — both bands
        # ROLL, so both action streams must advance a counter.
        threads = [
            threading.Thread(target=worker, args=(
                "pca", canned("physical", ["npc_dev_torvald"], "challenge the drillmaster"),
                "turn_pca_g42_1",
            )),
            threading.Thread(target=worker, args=(
                "pcb", canned("social", ["npc_dev_torvald"], "win the drillmaster over"),
                "turn_pcb_g42_1",
            )),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, errors
        assert not any(t.is_alive() for t in threads)

        state = _state(db_conn)
        # physical costs 10, social costs 15: interleaving must total 25.
        assert state.world["world_time"] == 25
        counters = state.world["rng_counters"]
        # Pin re-derived for per-site RNG streams (documented reason).
        # pca vs Torvald is HOPELESS (threat 20, might 11 → gap 9) → the
        # hopeless_flavor site; pcb's social lands DESPERATE (will 14 vs
        # presence 10 → gap 4) → the action:social site.
        assert counters['["character:pca","hopeless_flavor"]'] == 1
        assert counters['["character:pcb","action:social"]'] == 1
        with db_conn.transaction():
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM event WHERE event_type = 'outcome_resolved'"
                )
                assert cur.fetchone()[0] == 2


def _claim_spec(claim_id: str, text: str = "t") -> EventSpec:
    # Deliberately v1-shaped: proves legacy writers/replayed scripts pass
    # through the claim-lifecycle probe via the same upcast view the folds
    # use. Distinct texts keep the specs distinct CLAIMS (identical
    # content would legally become corroborating evidence instead —
    # tests/test_db_claims.py covers that path).
    return EventSpec(
        stream_id="character:pc",
        event_type=EventType.CLAIM_WRITTEN,
        world_time=0,
        payload={
            "claim_id": claim_id, "believer_id": "pc",
            "claim": {
                "subject_entity_id": "npc.dev.hedda", "claim_text": text,
                "value_or_range": None, "layer": "inquiry", "source": "s",
                "observer": None, "method": "witnessed",
                "world_date": "Day 1, 06:00", "scope": "local",
                "confidence": "consistent",
            },
            "provenance_root_event_id": event_ref(0),
            "hop_count": 0, "journal_flag": False,
        },
    )


def _timer_spec(timer_key: str, world_due: int = 480, created=None) -> EventSpec:
    return EventSpec(
        stream_id="character:pc",
        event_type=EventType.TIMER_STARTED,
        world_time=0,
        payload={
            "timer_key": timer_key, "kind": "training", "subject_id": "pc",
            "world_due": world_due, "due_at": real_due_at(world_due),
            "payload": {"aptitude": "will", "owner_id": "pc"},
            "created_event_id": created if created is not None else event_ref(0),
        },
    )


def _anchor() -> EventSpec:
    return EventSpec(
        stream_id="character:pc", event_type=EventType.INTENT_PARSED, world_time=0,
        payload={"anchor": True},
    )


class TestDomainIdRejection:
    """Duplicate claim_id / timer_key rejected pre-commit."""

    def test_duplicate_claim_id_across_commands_rejected(self, db_conn):
        fresh_reset(db_conn)
        append_command(db_conn, "c1", [_anchor(), _claim_spec("claim_dup", "first")])
        before = _count_events(db_conn)
        with pytest.raises(DuplicateDomainIdError, match="claim_id"):
            append_command(db_conn, "c2", [_anchor(), _claim_spec("claim_dup", "second")])
        assert _count_events(db_conn) == before  # whole command rolled back

    def test_duplicate_claim_id_within_one_command_rejected(self, db_conn):
        fresh_reset(db_conn)
        with pytest.raises(DuplicateDomainIdError, match="within itself"):
            append_command(
                db_conn, "c1",
                [_anchor(), _claim_spec("claim_dup", "a"), _claim_spec("claim_dup", "b")],
            )
        assert _count_events(db_conn) == 0

    def test_duplicate_timer_key_across_commands_rejected(self, db_conn):
        fresh_reset(db_conn)
        append_command(db_conn, "t1", [_anchor(), _timer_spec("timer_dup")])
        before = _count_events(db_conn)
        with pytest.raises(DuplicateDomainIdError, match="timer_key"):
            append_command(db_conn, "t2", [_anchor(), _timer_spec("timer_dup")])
        assert _count_events(db_conn) == before


class TestTimerFireOrder:
    """Tie order is (world_due, created_event_id) — canon,
    identical live and after rebuild."""

    def test_rebuild_preserves_fire_order(self, db_conn):
        fresh_reset(db_conn)
        # Two timers due at the SAME world minute; keys chosen so a
        # timer_key sort would INVERT creation order.
        append_command(db_conn, "t1", [_anchor(), _timer_spec("z_first", 100)])
        append_command(db_conn, "t2", [_anchor(), _timer_spec("a_second", 100)])
        live_order = [t["timer_key"] for t in due_timers(db_conn, 100)]
        db_conn.rollback()
        assert live_order == ["z_first", "a_second"]  # creation order, not key order
        rebuild_projections(db_conn)
        rebuilt_order = [t["timer_key"] for t in due_timers(db_conn, 100)]
        db_conn.rollback()
        assert rebuilt_order == live_order

    def test_due_at_is_the_recorded_fact(self, db_conn):
        fresh_reset(db_conn)
        append_command(db_conn, "t1", [_anchor(), _timer_spec("timer_fact", 495)])
        (timer,) = due_timers(db_conn, 495)
        db_conn.rollback()
        # Compare instants, not ISO strings: psycopg returns timestamptz in the
        # session timezone, so a non-UTC server renders the same moment with
        # another offset and a string compare fails on a correct value.
        assert timer["due_at"] == datetime.fromisoformat(real_due_at(495))


class TestEntityStateDB:
    """End to end: damage persists, reads back into resolution,
    rebuild reproduces it."""

    def test_npc_damage_persists_and_rebuild_matches(self, world_conn):
        # Pin re-derived for per-site RNG streams (documented reason): the outcome now
        # draws from the per-type stream ('character:pc','action:physical')
        # index 0 — seed 42 gives [3, 5] = 8, +1 ROUTINE modifier = 9 →
        # still HIT_WITH_COMPLICATION → hedda takes -2 (deterministic).
        result, _res = _turn(
            world_conn, canned("physical", ["npc_dev_hedda"], "arm-wrestle"),
            "turn_pc_g42_1",
        )
        assert not result.absorbed
        state = _state(world_conn)
        hedda = state.entities["npc.dev.hedda"]
        assert (hedda["hp"], hedda["hp_max"]) == (7, 9)
        live = canonical_projection_dump(world_conn)
        world_conn.rollback()
        assert '"npc.dev.hedda"' in live
        rebuild_projections(world_conn)
        rebuilt = canonical_projection_dump(world_conn)
        world_conn.rollback()
        assert rebuilt == live

    def test_wounds_change_subsequent_resolution(self, world_conn):
        wound = EventSpec(
            stream_id="character:pc",
            event_type=EventType.OUTCOME_RESOLVED,
            world_time=0,
            payload={"state_deltas": [{
                "delta_type": "hp", "entity_id": "npc.dev.torvald",
                "amount": -10, "cause": "prior battle",
            }]},
        )
        append_command(world_conn, "wound", [wound])
        _result, res = _turn(
            world_conn, canned("physical", ["npc_dev_torvald"], "press the attack"),
            "turn_pc_g42_1",
        )
        # Authored threat 20 (HOPELESS for might 5); at 10/20 hp the
        # effective threat is 10 → gap 5 → DESPERATE. Different fight.
        assert res.tier is PlausibilityTier.DESPERATE

    def test_delta_targeting_unseeded_entity_rejected_not_dropped(self, world_conn):
        before = _count_events(world_conn)
        bad = EventSpec(
            stream_id="character:pc",
            event_type=EventType.OUTCOME_RESOLVED,
            world_time=0,
            payload={"state_deltas": [{
                "delta_type": "hp", "entity_id": "prop.dev.ghost",
                "amount": -1, "cause": "impossible",
            }]},
        )
        with pytest.raises(ValueError, match="no entity_state row"):
            append_command(world_conn, "badwound", [bad])
        assert _count_events(world_conn) == before


class TestContentManifest:
    """Genesis pins the authored bytes; open verifies them."""

    def test_genesis_records_manifest_and_drift_refuses(
        self, db_conn, tmp_path, monkeypatch
    ):
        from everquill_engine.cli import _verify_content_manifest

        try:
            world_file = tmp_path / "drift-world.yaml"
            world_file.write_bytes(FIXTURE_WORLD.read_bytes())
            world = load_world(world_file)

            fresh_reset(db_conn)
            execute_command(db_conn, "genesis", lambda _s: genesis_specs(world, 7))
            with db_conn.transaction():
                with db_conn.cursor() as cur:
                    manifest = stored_content_manifest(cur)
            assert manifest is not None
            assert manifest["sha256"] == content_sha256(world_file)
            assert manifest["loader_version"] == LOADER_VERSION

            monkeypatch.delenv("EVERQUILL_ALLOW_CONTENT_DRIFT", raising=False)
            assert _verify_content_manifest(db_conn, world) is None  # bytes match

            world_file.write_bytes(world_file.read_bytes() + b"\n# silent edit\n")
            error = _verify_content_manifest(db_conn, world)
            assert error is not None and "drift" in error

            monkeypatch.setenv("EVERQUILL_ALLOW_CONTENT_DRIFT", "1")
            assert _verify_content_manifest(db_conn, world) is None  # loud bypass
        finally:
            fresh_reset(db_conn)
