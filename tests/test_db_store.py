"""Event store integration (skips cleanly without DATABASE_URL).

Runs against the dev Railway Postgres (.env). Tests own the whole
database state via fresh_reset — this DB is the project's dev DB, per
the original ticket.
"""

from __future__ import annotations

import pytest

from everquill_engine.events import EventSpec, EventType, event_ref
from everquill_engine.folds import PROJECTOR_VERSIONS
from everquill_engine.migrate import MIGRATIONS_DIR
from everquill_engine.store import (
    PROJECTION_TABLES,
    ProjectorVersionError,
    append_command,
    event_ulid,
    fresh_reset,
    load_fold_state,
    rebuild_projections,
)


def _spec(stream="character:pc", etype=EventType.INTENT_PARSED, wt=0, **payload):
    return EventSpec(stream_id=stream, event_type=etype, world_time=wt, payload=payload)


@pytest.fixture()
def clean_conn(db_conn):
    fresh_reset(db_conn)
    return db_conn


def _count_events(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM event")
        return cur.fetchone()[0]


class TestAppend:
    def test_append_assigns_gapless_stream_versions(self, clean_conn):
        append_command(clean_conn, "c1", [_spec(a=1), _spec(a=2)])
        append_command(clean_conn, "c2", [_spec(a=3)])
        with clean_conn.cursor() as cur:
            cur.execute(
                "SELECT stream_version FROM event WHERE stream_id='character:pc' ORDER BY id"
            )
            assert [r[0] for r in cur.fetchall()] == [1, 2, 3]

    def test_command_id_idempotency_duplicate_absorbed(self, clean_conn):
        first = append_command(clean_conn, "dup", [_spec(a=1), _spec(a=2)])
        assert not first.absorbed and len(first.event_rows) == 2
        second = append_command(clean_conn, "dup", [_spec(a=1), _spec(a=2)])
        assert second.absorbed and second.event_rows == ()
        assert _count_events(clean_conn) == 2  # nothing double-applied

    def test_multi_event_commands_use_ordinal_columns(self, clean_conn):
        """Pin updated for the command-identity change (documented reason): the stored shape
        changed from '<command_id>#<n>' suffix aliasing to real
        (command_id, event_ordinal) columns with a composite UNIQUE —
        'pay#1' can no longer alias sibling 1 of 'pay'."""
        append_command(clean_conn, "c1", [_spec(a=1), _spec(a=2), _spec(a=3)])
        with clean_conn.cursor() as cur:
            cur.execute("SELECT command_id, event_ordinal FROM event ORDER BY id")
            assert [tuple(r) for r in cur.fetchall()] == [("c1", 0), ("c1", 1), ("c1", 2)]

    def test_command_ids_with_hash_are_rejected(self, clean_conn):
        """'#' is reserved by the retired suffix encoding and can
        never re-enter the namespace."""
        with pytest.raises(ValueError, match="#"):
            append_command(clean_conn, "pay#1", [_spec(a=1)])
        assert _count_events(clean_conn) == 0

    def test_event_ref_substitution_within_command(self, clean_conn):
        result = append_command(
            clean_conn,
            "c1",
            [
                _spec(kind="root"),
                _spec(etype=EventType.CLAIM_WRITTEN, **{
                    "claim_id": "claim_x", "believer_id": "pc",
                    "claim": {
                        "subject_entity_id": "npc.dev.hedda", "claim_text": "t",
                        "value_or_range": None, "layer": "inquiry", "source": "s",
                        "observer": None, "method": "witnessed",
                        "world_date": "Day 1, 06:00", "scope": "local",
                        "confidence": "consistent",
                    },
                    "provenance_root_event_id": event_ref(0),
                    "hop_count": 0, "journal_flag": False,
                }),
            ],
        )
        root_id = result.event_rows[0]["id"]
        assert result.event_rows[1]["payload"]["provenance_root_event_id"] == root_id
        with clean_conn.cursor() as cur:
            cur.execute("SELECT provenance_root_event_id FROM claim WHERE claim_id='claim_x'")
            assert cur.fetchone()[0] == root_id

    def test_optimistic_concurrency_constraint_exists(self, clean_conn):
        import psycopg

        append_command(clean_conn, "c1", [_spec(a=1)])
        with pytest.raises(psycopg.errors.UniqueViolation):
            with clean_conn.transaction():
                with clean_conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO event (stream_id, stream_version, world_time,
                            event_type, command_id, payload, meta,
                            event_ulid, stream_type)
                        VALUES ('character:pc', 1, 0, 'intent_parsed', 'clash',
                                '{}', '{}', '00000000000000000000000000', 'character')
                        """
                    )

    def test_projections_written_in_same_transaction(self, clean_conn):
        """If the append transaction commits, the Tier-1 rows are there;
        a rolled-back duplicate leaves them untouched."""
        append_command(clean_conn, "genesis", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        with clean_conn.cursor() as cur:
            state = load_fold_state(cur)
        assert state.world == {
            "seed": 7, "world_time": 0, "rng_counters": {}, "last_event_id": 1,
        }
        append_command(clean_conn, "genesis", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=999),
        ])
        with clean_conn.cursor() as cur:
            state = load_fold_state(cur)
        assert state.world["seed"] == 7  # duplicate absorbed whole


class TestAppendOnlyDiscipline:
    def test_migration_revokes_update_delete(self):
        """The privilege revoke ships in the migration (synthesis §2.1).
        NOTE: the dev connection is the table owner (Railway superuser),
        which no REVOKE can bind — real enforcement lands when the API
        provisions the non-owner app_role at deploy (interface note)."""
        sql = (MIGRATIONS_DIR / "0001_event_store.sql").read_text(encoding="utf-8")
        assert "REVOKE UPDATE, DELETE ON event" in sql

    def test_rebuild_from_empty_is_empty(self, clean_conn):
        assert rebuild_projections(clean_conn) == 0


class TestEventIdentity:
    """Event_ulid + stream_type columns."""

    def test_appends_stamp_deterministic_ulid_and_stream_type(self, clean_conn):
        append_command(clean_conn, "c1", [_spec(a=1), _spec(stream="world", a=2)])
        with clean_conn.cursor() as cur:
            cur.execute(
                "SELECT event_ulid, stream_type, world_time, stream_id, stream_version"
                " FROM event ORDER BY id"
            )
            rows = cur.fetchall()
        assert [r[1] for r in rows] == ["character", "world"]
        for ulid, _stype, wt, stream_id, version in rows:
            assert ulid == event_ulid(wt, stream_id, version)
            assert len(ulid) == 26

    def test_python_and_sql_backfill_derivations_agree(self, clean_conn):
        """The 0009 plpgsql backfill and store.event_ulid MUST produce the
        same value for the same (world_time, stream_id, stream_version) —
        this pins the shared derivation (the function body below is the
        migration's, verbatim)."""
        body = (MIGRATIONS_DIR / "0009_event_identity_versioning_crypto.sql").read_text(
            encoding="utf-8"
        )
        start = body.index("CREATE OR REPLACE FUNCTION pg_temp._eq_event_ulid")
        end = body.index("END $$;", start) + len("END $$;")
        with clean_conn.cursor() as cur:
            cur.execute(body[start:end])
            samples = [
                (0, "world", 1),
                (10, "character:pc", 3),
                (598734, "region:dev", 12),
            ]
            for wt, stream_id, version in samples:
                cur.execute(
                    "SELECT pg_temp._eq_event_ulid(%s, %s, %s)", (wt, stream_id, version)
                )
                assert cur.fetchone()[0] == event_ulid(wt, stream_id, version)
        clean_conn.rollback()


class TestProjectorVersions:
    """Persisted projector versions gate every append."""

    def test_checkpoint_rows_match_the_code(self, clean_conn):
        with clean_conn.cursor() as cur:
            cur.execute(
                "SELECT projection_name, projector_version FROM projection_checkpoint"
            )
            assert dict(cur.fetchall()) == PROJECTOR_VERSIONS

    def test_append_refuses_on_version_mismatch_until_rebuild(self, clean_conn):
        with clean_conn.cursor() as cur:
            cur.execute(
                "UPDATE projection_checkpoint SET projector_version = projector_version + 1"
                " WHERE projection_name = 'claim'"
            )
        clean_conn.commit()
        with pytest.raises(ProjectorVersionError, match="claim"):
            append_command(clean_conn, "c1", [_spec(a=1)])
        clean_conn.rollback()
        # A rebuild restamps the code's versions and appends flow again.
        rebuild_projections(clean_conn)
        append_command(clean_conn, "c2", [_spec(a=1)])
        assert _count_events(clean_conn) == 1


class TestShadowRebuild:
    """Rebuild = shadow tables → diff → atomic swap, and the
    swapped-in tables keep the runtime role's privileges + timer FKs."""

    def test_rebuild_repairs_a_tampered_projection(self, clean_conn):
        append_command(clean_conn, "genesis", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        with clean_conn.cursor() as cur:  # owner-only tamper, off the books
            cur.execute("UPDATE world_state SET seed = 999999")
        clean_conn.commit()
        assert rebuild_projections(clean_conn) == 1
        with clean_conn.cursor() as cur:
            cur.execute("SELECT seed FROM world_state")
            assert cur.fetchone()[0] == 7

    def test_swap_preserves_grants_and_timer_fks(self, clean_conn):
        append_command(clean_conn, "genesis", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        rebuild_projections(clean_conn)
        with clean_conn.cursor() as cur:
            for table in PROJECTION_TABLES:
                for privilege in ("SELECT", "INSERT", "UPDATE"):
                    cur.execute(
                        "SELECT has_table_privilege('app_role', %s, %s)",
                        (table, privilege),
                    )
                    assert cur.fetchone()[0], f"app_role lost {privilege} on {table}"
                cur.execute(
                    "SELECT has_table_privilege('app_role', %s, 'DELETE')", (table,)
                )
                assert not cur.fetchone()[0], f"app_role gained DELETE on {table}"
            cur.execute(
                """
                SELECT count(*) FROM pg_constraint
                WHERE conrelid = 'timer'::regclass AND contype = 'f'
                """
            )
            assert cur.fetchone()[0] == 2  # created_event_id + fired_event_id
        clean_conn.rollback()


class TestReputationProjection:
    """Reputation folds VERBATIM (no clamp — event sourcing)
    and is a rebuildable projection like every other Tier-1 table."""

    @staticmethod
    def _rep(actor, scope, subject, amount):
        return {
            "delta_type": "reputation", "entity_id": actor,
            "scope": scope, "subject_id": subject, "amount": amount,
        }

    def _dump(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT actor_id, scope, subject_id, value FROM reputation ORDER BY 1, 2, 3"
            )
            return cur.fetchall()

    def test_reputation_folds_and_accumulates_across_commands(self, clean_conn):
        append_command(clean_conn, "g", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        append_command(clean_conn, "r1", [_spec(
            etype=EventType.OUTCOME_RESOLVED, wt=1,
            state_deltas=[
                self._rep("pc", "disposition", "npc_jorun", 2),
                self._rep("pc", "standing", "loc.harrowdown", 1),
                self._rep("pc", "renown", "", 1),
            ],
        )])
        append_command(clean_conn, "r2", [_spec(
            etype=EventType.OUTCOME_RESOLVED, wt=2,
            state_deltas=[self._rep("pc", "disposition", "npc_jorun", -1)],
        )])
        # +2 then -1 = 1: applied verbatim, no clamp (the resolver bounds at
        # command time; the fold never does — synthesis §2.6 rule 1).
        assert self._dump(clean_conn) == [
            ("pc", "disposition", "npc_jorun", 1),
            ("pc", "renown", "", 1),
            ("pc", "standing", "loc.harrowdown", 1),
        ]

    def test_reputation_survives_rebuild(self, clean_conn):
        append_command(clean_conn, "g", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        append_command(clean_conn, "r1", [_spec(
            etype=EventType.OUTCOME_RESOLVED, wt=1,
            state_deltas=[self._rep("pc", "disposition", "npc_jorun", 3)],
        )])
        before = self._dump(clean_conn)
        rebuild_projections(clean_conn)  # truncate-and-replay through the fold
        assert self._dump(clean_conn) == before
        assert ("pc", "disposition", "npc_jorun", 3) in before


class TestDeedProjection:
    """Deed_recorded events materialize as a rebuildable
    projection, exactly like reputation, so the resolver receives projected
    deeds instead of reading the log."""

    @staticmethod
    def _deed(actor="pc", location="loc.dev.tavern", notoriety=3, description="pc won"):
        return {
            "deed": {
                "actor_entity_id": actor,
                "description": description,
                "location_id": location,
                "witness_ids": ["npc.dev.sorrel"],
                "notoriety": notoriety,
                "world_date": "Day 1, 06:10",
            },
            "caused_by": 1,
        }

    def _dump(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT deed_order, actor_id, location_id, notoriety, world_time,"
                " description, source_event_id FROM deeds ORDER BY deed_order"
            )
            return cur.fetchall()

    def test_deed_recorded_materializes_one_row(self, clean_conn):
        append_command(clean_conn, "g", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        result = append_command(clean_conn, "d1", [
            _spec(
                stream="region:dev", etype=EventType.DEED_RECORDED, wt=10,
                **self._deed(description="the Quill-touched bested Hedda"),
            )
        ])

        source_event_id = result.event_rows[0]["id"]
        assert self._dump(clean_conn) == [
            (
                1, "pc", "loc.dev.tavern", 3, 10,
                "the Quill-touched bested Hedda", source_event_id,
            )
        ]
        with clean_conn.cursor() as cur:
            state = load_fold_state(cur)
        assert state.deeds == [
            {
                "deed_order": 1,
                "actor_entity_id": "pc",
                "location_id": "loc.dev.tavern",
                "notoriety": 3,
                "world_time": 10,
                "description": "the Quill-touched bested Hedda",
                "source_event_id": source_event_id,
            }
        ]

    def test_deeds_survive_rebuild_identically(self, clean_conn):
        append_command(clean_conn, "g", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        append_command(clean_conn, "d1", [
            _spec(stream="region:dev", etype=EventType.DEED_RECORDED, wt=10, **self._deed())
        ])
        before = self._dump(clean_conn)

        rebuild_projections(clean_conn)

        assert self._dump(clean_conn) == before

    def test_fresh_reset_clears_deeds(self, clean_conn):
        append_command(clean_conn, "g", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        append_command(clean_conn, "d1", [
            _spec(stream="region:dev", etype=EventType.DEED_RECORDED, wt=10, **self._deed())
        ])
        assert self._dump(clean_conn)

        fresh_reset(clean_conn)

        assert self._dump(clean_conn) == []

    def test_deed_projector_version_mismatch_forces_rebuild(self, clean_conn):
        with clean_conn.cursor() as cur:
            cur.execute(
                "UPDATE projection_checkpoint SET projector_version = projector_version + 1"
                " WHERE projection_name = 'deeds'"
            )
        clean_conn.commit()
        with pytest.raises(ProjectorVersionError, match="deeds"):
            append_command(clean_conn, "d1", [
                _spec(
                    stream="region:dev", etype=EventType.DEED_RECORDED, wt=10,
                    **self._deed(),
                )
            ])
        clean_conn.rollback()

        rebuild_projections(clean_conn)
        append_command(clean_conn, "d2", [
            _spec(stream="region:dev", etype=EventType.DEED_RECORDED, wt=10, **self._deed())
        ])
        assert len(self._dump(clean_conn)) == 1


class TestMigrateAndRebuild:
    """A migration that adds a projection backfills it on an existing world
    (audit 2026-10-24, codex F5: 0016 left upgraded worlds' deeds empty)."""

    def test_an_upgraded_world_gets_its_history_in_the_new_projection(self, clean_conn):
        from everquill_engine.store import migrate_and_rebuild

        append_command(clean_conn, "g", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        append_command(clean_conn, "d1", [
            _spec(stream="region:dev", etype=EventType.DEED_RECORDED, wt=10,
                  **TestDeedProjection._deed()),
        ])
        replayed = TestDeedProjection._dump(None, clean_conn)
        assert replayed
        # Wind the world back to before 0016: no deeds table, no checkpoint.
        with clean_conn.transaction():
            clean_conn.execute("DROP TABLE deeds")
            clean_conn.execute("DELETE FROM projection_checkpoint WHERE projection_name = 'deeds'")
            clean_conn.execute("DELETE FROM schema_migrations WHERE filename = '0016_deeds.sql'")

        applied = migrate_and_rebuild(clean_conn)

        assert applied == ["0016_deeds.sql"]
        assert TestDeedProjection._dump(None, clean_conn) == replayed

    def test_an_interrupted_backfill_finishes_on_the_next_start(self, clean_conn):
        """The migration committed but the rebuild never ran (a killed process,
        or the CLI migrator): the stale version makes the next start rebuild
        (audit codex-003)."""
        from everquill_engine.store import migrate_and_rebuild

        append_command(clean_conn, "g", [
            _spec(stream="world", etype=EventType.WORLD_CREATED, seed=7),
        ])
        append_command(clean_conn, "d1", [
            _spec(stream="region:dev", etype=EventType.DEED_RECORDED, wt=10,
                  **TestDeedProjection._deed()),
        ])
        replayed = TestDeedProjection._dump(None, clean_conn)
        with clean_conn.transaction():  # the state a migration leaves before its backfill
            clean_conn.execute("DELETE FROM deeds")
            clean_conn.execute("DELETE FROM projection_checkpoint WHERE projection_name = 'deeds'")

        assert migrate_and_rebuild(clean_conn) == []  # nothing pending, still rebuilt
        assert TestDeedProjection._dump(None, clean_conn) == replayed

    def test_a_fresh_world_is_not_rebuilt(self, clean_conn):
        from everquill_engine.store import migrate_and_rebuild

        assert migrate_and_rebuild(clean_conn) == []  # already current
