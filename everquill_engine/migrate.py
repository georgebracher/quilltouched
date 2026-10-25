"""Tiny plain-SQL migration runner: ``python -m everquill_engine.migrate``.

No framework (stack pin: psycopg3 only — synthesis §2). Rules:

- Migrations are ``migrations/NNNN_name.sql`` files, applied in filename
  order, each inside its own transaction (DDL is transactional in
  Postgres); a failed file rolls back completely and stops the run.
- Applied filenames are recorded in ``schema_migrations``; a file is
  never re-applied and never edited after it has shipped — schema
  changes are new files, mirroring the append-only discipline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from everquill_engine.db import REPO_ROOT, connect, resolve_database_url

__all__ = ["MIGRATIONS_DIR", "pending_migrations", "apply_migrations"]

MIGRATIONS_DIR = REPO_ROOT / "migrations"

_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def _migration_files(migrations_dir: Path) -> list[Path]:
    return sorted(p for p in migrations_dir.glob("[0-9]*.sql") if p.is_file())


def pending_migrations(conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Migration files not yet recorded in schema_migrations, in order."""
    with conn.cursor() as cur:
        cur.execute(_TRACKING_DDL)
        cur.execute("SELECT filename FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
    conn.commit()
    return [p for p in _migration_files(migrations_dir) if p.name not in applied]


def apply_migrations(conn, migrations_dir: Path = MIGRATIONS_DIR, *, echo=None) -> list[str]:
    """Apply all pending migrations; returns the filenames applied."""
    applied: list[str] = []
    for path in pending_migrations(conn, migrations_dir):
        sql = path.read_text(encoding="utf-8")
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        applied.append(path.name)
        if echo:
            echo(f"applied {path.name}")
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m everquill_engine.migrate",
        description="Apply pending plain-SQL migrations from migrations/.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list pending migrations without applying"
    )
    args = parser.parse_args(argv)

    if not resolve_database_url():
        print(
            "DATABASE_URL is not set (env or repo-root .env) — nothing to migrate against.",
            file=sys.stderr,
        )
        return 2

    with connect() as conn:
        if args.dry_run:
            pending = pending_migrations(conn)
            if not pending:
                print("no pending migrations")
            for path in pending:
                print(f"pending: {path.name}")
            return 0
        # Through migrate_and_rebuild, like a server start, so a migration that
        # adds a projection is backfilled here too (third audit F3).
        from everquill_engine.store import migrate_and_rebuild

        applied = migrate_and_rebuild(conn)
        for name in applied:
            print(f"applied {name}")
        if not applied:
            print("no pending migrations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
