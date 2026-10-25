# Release gate (`make release-check`)

The one authoritative "is this safe to ship?" command. It exists because a green
default `pytest` was **misleading**: `pyproject.toml` sets `testpaths = ["tests"]`,
so bare `pytest` collected only the engine suite and silently skipped `api/tests`
and every `llm/` unit — 93 tests the headline number never covered. CI compounded
it (no LLM tests, no client behavior, Python lint red). This is audit finding #8;
the gate closes it.

## The command

```bash
make release-check
```

One command, run the same way locally and in CI. It runs, and must be green on,
**all** of:

| Portion                     | Command it runs                              | Notes |
|-----------------------------|----------------------------------------------|-------|
| Python lint                 | `ruff check everquill_engine api tests llm`  | full shipped+tested surface |
| Engine tests                | `pytest tests`      (own scratch DB)         | DB-backed (see below) |
| API tests                   | `pytest api/tests`  (own scratch DB)         | DB-backed (see below) |
| LLM unit tests              | `pytest llm`                                 | pure — no DB, no network |
| Client build                | `npm -C client run build`                    | `tsc -b && vite build` |
| Client lint                 | `npm -C client run lint`                     | `oxlint` |

It runs correctness first and **lint last**, so a run surfaces every suite's
result before the style gate rather than bailing at the first long line.

## What makes it fail (the whole point)

1. **Zero-collection is a failure, not a pass.** Before running, the gate does a
   `--collect-only` on each of `tests`, `api/tests`, `llm` and fails if any
   collects 0 tests (pytest exit code 5). A suite that silently disappears — the
   original finding — turns the gate red instead of green.
2. **A missing tool is a failure, not a skip.** `ruff`, `pytest`, and `npm` are
   checked up front. If any is absent the gate fails; it never quietly degrades
   the way `make lint`/`make test` do.
3. **A skipped DB test is a failure when a DB is available.** When `DATABASE_URL`
   is set (CI, or a local opt-in) the engine + api suites must run with **zero
   skips**. The gate greps the pytest summary for skips and fails on any — a
   skipped DB-marked test is a broken gate, never a green one.
4. Any test failure, lint error, or client build/lint error.

## Requiring the database

`REQUIRE_DB=1 make release-check` fails instead of printing PARTIAL PASS when no
`DATABASE_URL` is given. Use it wherever the gate is a done-check
(CI sets it). The DB fixtures also refuse a non-local
database host unless `EVERQUILL_ALLOW_REMOTE_TEST_DB=1`: the suites wipe data.

## Database awareness (local vs CI)

The engine `tests/` and `api/tests` DB-backed tests need Postgres. They skip
cleanly when no `DATABASE_URL` is resolvable (`tests/conftest.py`,
`api/tests/conftest.py`). The gate keys its behavior off the `DATABASE_URL`
**environment variable**:

- **`DATABASE_URL` set** (CI's ephemeral Postgres, or a deliberate local run) —
  the DB suites run **authoritatively**: zero-collection fails, and **any skip
  fails**. This is the full gate. The engine `tests/` and `api/tests` suites are
  **not** run against `DATABASE_URL` directly — see *Per-suite DB isolation*
  below.
- **`DATABASE_URL` unset** (default local) — the DB suites run in **no-DB mode**
  (`EVERQUILL_IGNORE_DOTENV=1`, so DB tests skip and pure tests still run), and
  the gate prints a clear NOTE that the DB portions were *not* verified and exits
  as a **PARTIAL PASS**. This keeps local runs off the shared dev DB (they never
  connect), so a local `make release-check` cannot collide with a DB test suite.

To run the full gate including the DB suites locally (only when no other DB suite
is running — concurrent DB suites truncate each other's tables mid-run):

```bash
DATABASE_URL=postgresql://USER:PASS@HOST:PORT/DB make release-check
```

The `EVERQUILL_IGNORE_DOTENV=1` escape hatch (resolution order is env var, then
repo-root `.env`) is what lets the no-DB path be provable on a machine whose
`.env` points at a database.

## Per-suite DB isolation (why two scratch databases)

The engine `tests/` and `api/tests` DB suites **both** use the `public` schema
for the LEGACY shared world. Run in one `pytest tests api/tests` process against
one database, they collide: the engine suite's `fresh_reset` seeds the
dev-fixture world into `public`, so the committed content manifest's
`content_source` becomes `dev-fixture.yaml`; the api suite's
`test_legacy_shared_world_stays_readable_unauthed` then reads that as MEDIUM-7
content drift (committed `dev-fixture.yaml` vs configured `harrowdown.yaml`) and
gets a 503 where it expects 200. This is the "never two DB suites on one
Postgres / one public schema" hazard, and it hit CI's ephemeral PG too.

So when `DATABASE_URL` is set the gate runs the two suites as **separate pytest
invocations against separate scratch databases** on the same server:

- engine `tests/`  → `everquill_rc_engine_<pid>`
- api `api/tests`  → `everquill_rc_api_<pid>`

Neither shares `public` with the other, so the collision cannot happen. The gate
creates both scratch DBs before the run and drops them after (even on failure),
using the server's `postgres` maintenance database for the `CREATE`/`DROP
DATABASE` DDL (via `psycopg`, so no `psql` client is required). Each scratch DB
starts empty and self-migrates: the engine `db_conn` fixture runs
`apply_migrations`, and api startup migrates + bootstraps the legacy world.

Because DDL creates the scratch DBs, the operator (or CI user) must have
**`CREATE DATABASE`** on the server `DATABASE_URL` points at. In CI the ephemeral
`postgres` superuser has it; locally, point `DATABASE_URL` at any Postgres where
you can create databases (a throwaway local server, **not** the shared dev DB —
the scratch DBs live beside it and never touch it). The DB runs also export
`PGTZ=UTC` so a `timestamptz`-rendering test is deterministic regardless of the
operator's machine timezone (CI's Postgres is already UTC; a local server
inherits the host TZ).

## CI (`.github/workflows/ci.yml`)

Two jobs, and `make release-check` is the single source of truth for both:

- **`release`** — the authoritative gate. Stands up an ephemeral `postgres:16`
  service, sets `DATABASE_URL`, installs Python + Node deps, then runs
  `make release-check PY=python`. Because `DATABASE_URL` is set, the DB suites run
  with the zero-skip guarantee. `PY=python` is passed because CI has no `.venv`.
- **`no-db`** — the boot-and-degrade contract, kept from before: the API must
  boot without a database, serve `/healthz` = `ok`, degrade game endpoints to
  503, and answer an unauthed `POST /api/action` with **410** (the shared world
  is sealed — auth answers before the DB check).

The previous split `python` / `node` jobs were folded into `release` so the CI
gate and the local gate run exactly the same checks.

## Lint scope

`ruff check` covers `everquill_engine api tests llm` — the shipped and tested
Python surface. `tools/` (the offline sprite generator) is deliberately **out of
scope**: it is a local asset-generation script, not imported by the engine/api/
llm at runtime, and it is not part of the release surface. Ruff config
(line-length 100, rule set `E,F,I,UP,B`) lives in `pyproject.toml`.

## Status (2026-07-14, DB-isolation pass)

The gate is fully green, **including the DB suites**. The `llm/parser_eval.py:266`
E741 that Hardening Pass 1 left as a noted residual has since been cleared by its
owner, so `ruff check everquill_engine api tests llm` reports **All checks
passed** and repo-wide E501 is 0. `tools/spritegen/generate.py:569` still has an
E741 but is out of gate scope (`tools/` is not part of the release surface).

A full `DATABASE_URL=… make release-check` run is green end to end: tool
preflight, per-suite zero-collection guard (tests / api/tests / llm), 24 llm
units, then — on **separate scratch databases** (see *Per-suite DB isolation*) —
the engine suite (379 passed) and the api suite (100 passed) with **zero skips**,
and finally the client build + lint and `ruff`, ending in
`release-check: PASSED — full gate including DB suites.` The earlier collision
(engine `fresh_reset` drifting the shared `public` legacy world into a 503 for
the api suite's `test_legacy_shared_world_stays_readable_unauthed`) is gone
because the two suites no longer share a database.
