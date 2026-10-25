"""End-to-end determinism + rebuild equivalence against the real dev DB.

Sprint DoD tests (skip cleanly without DATABASE_URL):

1. DETERMINISM — same seed + same intent script, run twice in SEPARATE
   PROCESSES (fresh CLI subprocess each time, --fresh wipe between),
   must produce byte-identical event rows (all columns except the two
   documented infra columns: transaction_id, recorded_at).
2. REBUILD EQUIVALENCE — truncate every projection, replay the log,
   hash-equal to the incrementally-maintained tables.
3. CONTRACT — every committed outcome_resolved row renders to a dict
   that validates against docs/contracts/outcome.schema.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import jsonschema
import pytest

from everquill_engine.resolver import outcome_contract
from everquill_engine.store import (
    canonical_event_dump,
    canonical_projection_dump,
    rebuild_projections,
)
from everquill_engine.views import outcome_public
from tests.harness import FIXTURE_WORLD, REPO_ROOT, SCRIPT_PATH, load_schema


def _run_cli(db_url: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL=db_url)
    result = subprocess.run(
        [sys.executable, "-m", "everquill_engine.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=300,
    )
    assert result.returncode == 0, f"cli failed:\n{result.stdout}\n{result.stderr}"
    return result


def _scripted_run(db_url: str) -> str:
    """One full fresh scripted run in separate processes; returns play stdout."""
    play = _run_cli(
        db_url, "play", str(FIXTURE_WORLD),
        "--seed", "42", "--script", str(SCRIPT_PATH), "--fresh",
    )
    # Fire the training timer too — timer determinism is part of the run.
    # Pin updated for the typed-intent boundary (documented reason): the scripted block
    # 'until nightfall' now BINDS — committed at world minute 160 (08:40),
    # it runs to the next 18:00 = world minute 720, past the script's end
    # (665), so the sweep advances 60 minutes to reach it. Before duration
    # binding the hint was silently ignored (due at 640, already overdue).
    _run_cli(db_url, "clock-advance", "--minutes", "60")
    return play.stdout


@pytest.fixture(scope="module")
def two_runs(db_url):
    """Run the script twice in separate processes; capture dumps + stdout.

    NOTE: every test in this module reads the DB state left by run 2;
    no test may mutate the shared dev DB after this fixture.
    """
    from everquill_engine.db import connect

    dumps, projections, outputs = [], [], []
    for _ in range(2):
        outputs.append(_scripted_run(db_url))
        with connect(db_url) as conn:
            dumps.append(canonical_event_dump(conn))
            projections.append(canonical_projection_dump(conn))
    return dumps, projections, outputs


class TestDeterminism:
    def test_same_seed_same_script_byte_identical_event_rows(self, two_runs):
        dumps, _, _ = two_runs
        assert dumps[0].encode() == dumps[1].encode()
        assert dumps[0].count("\n") > 30  # a real run, not two empty logs

    def test_chronicle_output_is_deterministic_too(self, two_runs):
        _, _, outputs = two_runs
        assert outputs[0] == outputs[1]
        assert "<<Assessment:" in outputs[0]


class TestRebuildEquivalence:
    def test_truncate_replay_hash_equal(self, two_runs, db_url):
        from everquill_engine.db import connect

        _, projections, _ = two_runs
        with connect(db_url) as conn:
            live = canonical_projection_dump(conn)
            assert live == projections[-1]
            folded = rebuild_projections(conn)
            assert folded > 30
            rebuilt = canonical_projection_dump(conn)
        assert rebuilt == live


class TestCommittedContracts:
    def test_every_stored_outcome_validates_against_schema(self, two_runs, db_url):
        from everquill_engine.db import connect

        schema = load_schema("outcome.schema.json")
        with connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, payload FROM event WHERE event_type='outcome_resolved'"
                " ORDER BY id"
            )
            rows = cur.fetchall()
        assert len(rows) == 10  # one per scripted intent
        for event_id, payload in rows:
            # outcome.schema.json v1.3 = the PUBLIC projection.
            contract = outcome_public(outcome_contract({"id": event_id, "payload": payload}))
            jsonschema.validate(contract, schema)

    def test_timer_fired_exactly_once_and_stamped_at_world_due(self, two_runs, db_url):
        from everquill_engine.db import connect

        with connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT world_time, payload FROM event WHERE event_type='timer_completed'"
            )
            rows = cur.fetchall()
            assert len(rows) == 1
            world_time, payload = rows[0]
            assert world_time == payload["completed_at_world_time"]
            cur.execute("SELECT status, world_due FROM timer")
            (status, world_due), = cur.fetchall()
            assert status == "fired" and world_due == world_time

    def test_state_survived_by_construction(self, two_runs, db_url):
        """A brand-new process sees the world exactly where it was left."""
        from everquill_engine.db import connect
        from everquill_engine.store import load_fold_state

        with connect(db_url) as conn, conn.cursor() as cur:
            state = load_fold_state(cur)
        assert state.world is not None and state.world["seed"] == 42
        pc = state.characters["pc"]
        # Pin updated for the advisory stat_hint (documented reason): it is
        # advisory-only, so the 'train' shape now trains the ENGINE-selected
        # aptitude (DEFAULT_STAT_FOR_ACTION['train'] = will). Chargen will is
        # 7 (seed 42); the scripted training block adds 1.
        assert pc["aptitudes"]["will"] == 8  # 7 rolled + 1 trained, from the log alone
        assert json.dumps(pc["flags"])  # projections intact and JSON-safe
