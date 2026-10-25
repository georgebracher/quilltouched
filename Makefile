# Everquill — repo plumbing (Sprint 0, F0.1)
# Targets degrade gracefully while other teams' components land.

.DEFAULT_GOAL := help

VENV := .venv
# Use the project venv's python when it exists, else system python3.
PY := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)

# Authoritative release-gate scope (audit #8). Python lint covers the shipped +
# tested surface; tools/ (offline sprite generator, not imported by the game) is
# out of scope on purpose — documented in docs/ops/release-gate.md.
LINT_DIRS := everquill_engine api tests llm
# Every suite here MUST collect > 0 tests or the gate fails: a suite that
# silently collects nothing is the finding, not a pass.
PYTEST_SUITES := tests api/tests llm

# --- release-check DB isolation (see docs/ops/release-gate.md) --------------
# The engine tests/ and api/tests DB suites BOTH use the public schema for the
# LEGACY shared world, so running them in ONE pytest process against ONE
# database collides: the engine suite's fresh_reset seeds the dev-fixture world
# into public, then the api suite's legacy-world test reads that content drift
# and gets 503 instead of 200. The fix is per-suite databases: each suite runs
# against its OWN scratch database on the same server as DATABASE_URL, so
# neither shares public with the other. This helper (invoked by release-check)
# creates or drops one scratch database and prints its URL. psycopg is an engine
# dependency, so no psql client is required in CI. CREATE/DROP DATABASE run on
# the server's maintenance `postgres` database (autocommit — DDL, no txn).
define RC_DBADMIN
import os, sys
from urllib.parse import urlsplit, urlunsplit
import psycopg

mode, dbname = sys.argv[1], sys.argv[2]
if not dbname.replace("_", "").isalnum():
    sys.exit("refusing unsafe scratch db name: %r" % dbname)
parts = urlsplit(os.environ["DATABASE_URL"])
admin = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, ""))
child = urlunsplit((parts.scheme, parts.netloc, "/" + dbname, parts.query, ""))
with psycopg.connect(admin, autocommit=True) as conn:
    conn.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % dbname)
    if mode == "create":
        conn.execute('CREATE DATABASE "%s"' % dbname)
if mode == "create":
    print(child)
endef
export RC_DBADMIN

.PHONY: help dev test lint release-check

help:
	@echo "Everquill make targets:"
	@echo "  make dev            - start the API: uvicorn --reload on http://127.0.0.1:8000"
	@echo "                        NOTE: the client dev server runs separately: npm -C client run dev"
	@echo "  make test           - run engine pytest (via $(VENV) if present) plus api tests if any;"
	@echo "                        skips cleanly with a message for components not landed yet"
	@echo "  make lint           - ruff check over python dirs (everquill_engine/, api/, tests/) if ruff is installed"
	@echo "  make release-check  - AUTHORITATIVE release gate (audit #8): ruff + engine/api/llm tests"
	@echo "                        + client build/lint. Fails on zero-collection or a missing tool."
	@echo "                        Set DATABASE_URL to run the DB-backed suites; otherwise those are"
	@echo "                        skipped with a NOTE (they run in CI against ephemeral Postgres)."
	@echo "                        See docs/ops/release-gate.md."

dev:
	@echo "Starting Everquill API on http://127.0.0.1:8000 (Ctrl-C to stop)."
	@echo "World bootstrap on startup: EVERQUILL_WORLD=$${EVERQUILL_WORLD:-content/world/harrowdown.yaml}"
	@echo "  (genesis + dev chargen committed idempotently if the event log is empty;"
	@echo "   DATABASE_URL from env or repo-root .env — without one the API serves 503s)"
	@echo "Client dev server is separate: npm -C client run dev"
	@if [ -f .env.localdev ]; then echo '[dev] using .env.localdev database'; fi
	@bash -c 'set -a; [ -f .env.localdev ] && . ./.env.localdev; set +a; exec $(PY) -m uvicorn api.main:app --reload --port 8000'

test:
	@if [ -f pyproject.toml ]; then \
		echo "== pytest (engine tests/ + api/tests) =="; \
		$(PY) -m pytest tests api/tests; rc=$$?; \
		if [ $$rc -eq 5 ]; then echo "-- pytest collected no tests yet — OK for Sprint 0"; \
		elif [ $$rc -ne 0 ]; then exit $$rc; fi; \
	elif [ -d api/tests ]; then \
		echo "-- engine package not landed yet (no pyproject.toml) — skipping engine tests"; \
		echo "== pytest (api) =="; \
		$(PY) -m pytest api; \
	else \
		echo "-- engine package not landed yet (no pyproject.toml) — skipping engine tests"; \
		echo "-- no api tests yet (api/tests/ absent) — skipping api tests"; \
		echo "Nothing to test yet. This is expected until Team A lands the engine."; \
	fi

lint:
	@RUFF=""; \
	if $(PY) -m ruff --version >/dev/null 2>&1; then RUFF="$(PY) -m ruff"; \
	elif command -v ruff >/dev/null 2>&1; then RUFF="ruff"; fi; \
	if [ -z "$$RUFF" ]; then \
		echo "ruff not installed — skipping lint (install with: $(PY) -m pip install ruff)"; \
		exit 0; \
	fi; \
	DIRS=""; \
	for d in everquill_engine api tests; do [ -d "$$d" ] && DIRS="$$DIRS $$d"; done; \
	if [ -z "$$DIRS" ]; then echo "no python dirs present yet — nothing to lint"; exit 0; fi; \
	echo "ruff check$$DIRS"; \
	$$RUFF check $$DIRS

# --- Authoritative release gate (audit #8) --------------------------------
# ONE command that must be green before a paid/unsupervised alpha. It runs the
# engine, api, and llm test suites, the client build + lint, and Python ruff,
# and FAILS on (a) any suite that collects zero tests, (b) a missing tool, and
# (c) — when a database is configured — any DB-marked test that skipped.
#
# DB awareness: the engine tests/ and api/tests DB-backed tests need Postgres.
#   * DATABASE_URL set (CI's ephemeral Postgres, or a local opt-in)  -> the DB
#     suites run authoritatively: zero collection fails, and ANY skip fails.
#   * DATABASE_URL unset (default local) -> those suites run in no-DB mode (DB
#     tests skip, pure tests still run) and the gate prints a NOTE that the DB
#     portions were not verified. Keeps local runs off the shared dev DB.
# Correctness first, lint last, so a run surfaces every suite result before the
# style gate — see docs/ops/release-gate.md.
release-check:
	@set -e; \
	echo "== release-check: authoritative release gate (audit #8) =="; \
	echo "-- tool preflight (a missing tool is a FAIL, never a skip) --"; \
	$(PY) -m ruff --version >/dev/null 2>&1 || { echo "FAIL: ruff missing — $(PY) -m pip install -e '.[dev]'"; exit 1; }; \
	$(PY) -m pytest --version >/dev/null 2>&1 || { echo "FAIL: pytest missing — $(PY) -m pip install -e '.[dev]'"; exit 1; }; \
	command -v npm >/dev/null 2>&1 || { echo "FAIL: npm/node missing — client build+lint cannot run"; exit 1; }; \
	echo "-- zero-collection guard: $(PYTEST_SUITES) --"; \
	for suite in $(PYTEST_SUITES); do \
		rc=0; EVERQUILL_IGNORE_DOTENV=1 $(PY) -m pytest "$$suite" --collect-only -q >/dev/null 2>&1 || rc=$$?; \
		if [ $$rc -eq 5 ]; then echo "FAIL: suite '$$suite' collected 0 tests (zero-collection gate)"; exit 1; fi; \
		if [ $$rc -ne 0 ]; then echo "FAIL: collection error in '$$suite' (rc=$$rc)"; exit 1; fi; \
		echo "   collection OK: $$suite"; \
	done; \
	echo "-- llm unit tests (pure: no DB, no network) --"; \
	rc=0; EVERQUILL_IGNORE_DOTENV=1 $(PY) -m pytest llm -q || rc=$$?; \
	[ $$rc -eq 0 ] || { echo "FAIL: llm unit tests (rc=$$rc)"; exit 1; }; \
	DB_SKIPPED=0; \
	if [ -n "$$DATABASE_URL" ]; then \
		echo "-- engine tests/ + api/tests (DB mode: SEPARATE per-suite scratch DBs — no public-schema collision) --"; \
		ENGINE_DB=everquill_rc_engine_$$$$; API_DB=everquill_rc_api_$$$$; \
		ENGINE_URL=$$($(PY) -c "$$RC_DBADMIN" create "$$ENGINE_DB") || { echo "FAIL: could not create scratch DB $$ENGINE_DB (needs CREATE DATABASE on the DATABASE_URL server)"; exit 1; }; \
		API_URL=$$($(PY) -c "$$RC_DBADMIN" create "$$API_DB") || { echo "FAIL: could not create scratch DB $$API_DB"; $(PY) -c "$$RC_DBADMIN" drop "$$ENGINE_DB" >/dev/null 2>&1 || true; exit 1; }; \
		ELOG=$$(mktemp); ALOG=$$(mktemp); erc=0; arc=0; \
		echo "   engine tests -> $$ENGINE_DB"; \
		DATABASE_URL="$$ENGINE_URL" PGTZ=UTC EVERQUILL_IGNORE_DOTENV=1 $(PY) -m pytest tests -rs > "$$ELOG" 2>&1 || erc=$$?; \
		echo "   api tests    -> $$API_DB"; \
		DATABASE_URL="$$API_URL" PGTZ=UTC EVERQUILL_IGNORE_DOTENV=1 $(PY) -m pytest api/tests -rs > "$$ALOG" 2>&1 || arc=$$?; \
		$(PY) -c "$$RC_DBADMIN" drop "$$ENGINE_DB" >/dev/null 2>&1 || true; \
		$(PY) -c "$$RC_DBADMIN" drop "$$API_DB" >/dev/null 2>&1 || true; \
		cat "$$ELOG"; cat "$$ALOG"; \
		fail=0; \
		if [ "$$erc" = "5" ]; then echo "FAIL: engine suite collected 0 tests"; fail=1; \
		elif [ "$$erc" != "0" ]; then echo "FAIL: engine DB suite failures (rc=$$erc)"; fail=1; \
		elif grep -qiE '([0-9]+ skipped|^SKIPPED)' "$$ELOG"; then echo "FAIL: engine DB-marked test(s) skipped while DATABASE_URL is set (a skipped DB test is a broken gate, not a green one)"; fail=1; fi; \
		if [ "$$arc" = "5" ]; then echo "FAIL: api suite collected 0 tests"; fail=1; \
		elif [ "$$arc" != "0" ]; then echo "FAIL: api DB suite failures (rc=$$arc)"; fail=1; \
		elif grep -qiE '([0-9]+ skipped|^SKIPPED)' "$$ALOG"; then echo "FAIL: api DB-marked test(s) skipped while DATABASE_URL is set (a skipped DB test is a broken gate, not a green one)"; fail=1; fi; \
		rm -f "$$ELOG" "$$ALOG"; \
		[ "$$fail" = "0" ] || exit 1; \
		echo "   engine+api: full DB run on isolated scratch DBs, zero skips (scratch DBs dropped)"; \
	else \
		echo "-- engine tests/ + api/tests (NO-DB mode: DB tests skip, pure tests run) --"; \
		LOG=$$(mktemp); \
		rc=0; EVERQUILL_IGNORE_DOTENV=1 $(PY) -m pytest tests api/tests -q > "$$LOG" 2>&1 || rc=$$?; \
		tail -3 "$$LOG"; rm -f "$$LOG"; \
		if [ $$rc -eq 5 ]; then echo "FAIL: engine+api collected 0 tests"; exit 1; fi; \
		if [ $$rc -ne 0 ]; then echo "FAIL: no-DB engine+api failures (rc=$$rc)"; exit 1; fi; \
		DB_SKIPPED=1; \
	fi; \
	echo "-- client build + lint + tests --"; \
	{ [ -d client/node_modules ] || npm -C client ci; } || { echo "FAIL: npm -C client ci"; exit 1; }; \
	npm -C client run build || { echo "FAIL: client build (npm -C client run build)"; exit 1; }; \
	npm -C client run lint  || { echo "FAIL: client lint (npm -C client run lint)"; exit 1; }; \
	npm -C client test      || { echo "FAIL: client tests (npm -C client test)"; exit 1; }; \
	echo "-- ruff check $(LINT_DIRS) --"; \
	$(PY) -m ruff check $(LINT_DIRS) || { echo "FAIL: ruff lint errors above"; exit 1; }; \
	echo ""; \
	if [ "$$DB_SKIPPED" = "1" ] && [ -n "$$REQUIRE_DB" ]; then \
		echo "release-check: FAIL — REQUIRE_DB is set but no DATABASE_URL was given."; \
		exit 1; \
	fi; \
	if [ "$$DB_SKIPPED" = "1" ]; then \
		echo "release-check: PARTIAL PASS — no-DB + lint + client all green."; \
		echo ">>> DB-backed engine tests/ + api/tests were NOT executed (no DATABASE_URL)."; \
		echo ">>> They run in CI against ephemeral Postgres, or locally with:"; \
		echo ">>>   DATABASE_URL=postgresql://USER:PASS@HOST:PORT/DB make release-check"; \
	else \
		echo "release-check: PASSED — full gate including DB suites."; \
	fi
