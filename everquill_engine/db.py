"""Database access helpers.

The ONLY modules in ``everquill_engine`` that may import psycopg are this
one, ``store``, ``migrate`` and ``cli``. Rules modules (dice, ladder,
folds, chargen, resolver, clock, world) stay persistence-free so the
referee remains a pure library.

``DATABASE_URL`` resolution (interface decision #4):

1. the ``DATABASE_URL`` environment variable, if set;
2. else the repo-root ``.env`` file (gitignored, points at the project's
   Railway dev Postgres) — unless ``EVERQUILL_IGNORE_DOTENV=1``, which
   simulates "unset" so the no-database test path can be proven even on
   machines where ``.env`` exists.

Every DB-integration test calls :func:`resolve_database_url` and skips
cleanly when it returns ``None`` (CI stays green with no database).
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["REPO_ROOT", "resolve_database_url", "connect"]

# everquill_engine/db.py -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_dotenv_value(dotenv_path: Path, key: str) -> str | None:
    """Minimal .env parser: KEY=VALUE lines, '#' comments, optional quotes.

    Deliberately tiny — the engine does not depend on python-dotenv.
    """
    try:
        text = dotenv_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        return value or None
    return None


def resolve_database_url(*, env: os._Environ[str] | dict[str, str] | None = None) -> str | None:
    """DATABASE_URL from env, then repo-root .env; None when unavailable."""
    environ = os.environ if env is None else env
    url = environ.get("DATABASE_URL")
    if url:
        return url
    if environ.get("EVERQUILL_IGNORE_DOTENV") == "1":
        return None
    return _read_dotenv_value(REPO_ROOT / ".env", "DATABASE_URL")


def connect(url: str | None = None):
    """Open a psycopg3 connection (autocommit OFF — callers own transactions).

    Imports psycopg lazily so the pure-rules modules can be used (and the
    non-DB test suite can run) without psycopg installed.
    """
    import psycopg

    resolved = url or resolve_database_url()
    if not resolved:
        raise RuntimeError(
            "DATABASE_URL is not set (env or repo-root .env). "
            "The event store needs the dev Postgres; see docs/tickets/sprint-1.md #4."
        )
    return psycopg.connect(resolved)


#: Hosts a test suite may wipe. The DB suites TRUNCATE and the API suite's
#: teardown deletes by pattern, so a remote URL (the shared Railway database
#: a repo-root .env once named) is refused unless explicitly allowed.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def require_local_test_database(url: str) -> str:
    """Return ``url`` if its host is local, else raise. Set
    EVERQUILL_ALLOW_REMOTE_TEST_DB=1 to run the suites somewhere else on purpose
    (audit 2026-10-24, claude #13)."""
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname or ""
    if host not in _LOCAL_HOSTS and os.environ.get("EVERQUILL_ALLOW_REMOTE_TEST_DB") != "1":
        raise RuntimeError(
            f"refusing to run DB tests against non-local host {host!r}: they wipe data. "
            "Point DATABASE_URL at a throwaway local Postgres, or set "
            "EVERQUILL_ALLOW_REMOTE_TEST_DB=1 if you mean it."
        )
    return url
