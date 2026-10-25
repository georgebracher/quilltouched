# Hardening Pass 1 — close the audit P1s (pre-broader-alpha)

Source: the tri-model deep audit report of 2026-07-14 (commit ee84247; the report itself is kept outside this repo). Verdict: supervised testing OK, unsupervised/paid alpha NO-GO until these close. Scope = the fixable-now P1s; the timer worker (audit #5) is deferred to Sprint 4, deep account-lifecycle/DR (audit #7/#8 beyond fail-closed) deferred.

Rules unchanged. **DB-contention rule (learned 4x): `pgrep -fl pytest` empty before any suite; run ALONE on your OWN scratch DB `everquill_test_<team>`; never two suites on one DB; the shared `everquill_test`/live DB is off-limits for parallel runs.**

Already verified/resolved this session (do NOT redo): APP_DATABASE_URL + EVERQUILL_MASTER_KEY are SET in prod (append-only + crypto active live); client base-less deploy fixed via guarded client/deploy.sh.

## Wave 1 (parallel — disjoint lanes; only Team A runs DB suites)

### Team A — engine: canonical turn record + fail-closed + contested data
Lane: everquill_engine/**, tests/**, migrations/0013_*.sql, docs/engine/**. Own scratch DB.
- **Canonical public-turn record (audit #1, the headline).** Persist the COMPLETE player-visible turn result — the public outcome contract (redacted) + narration prose + assembler meta — as canon keyed by command_id, at commit time (extend/【use the narration_generated event or a dedicated public_turn projection】). One authoritative record that the API serves for: first response, duplicate/retry, and reconnect/Chronicle rebuild. It must be exactly-once and survive response loss (prose generated but HTTP lost → the record already holds it; retry returns the SAME record, not a re-resolved different outcome). Expose a read: `store.public_turn(conn, command_id)` and `store.recent_public_turns(conn, character_id, n)` for the client Chronicle. Tests: response-loss (commit record, drop response, retry → identical record), reconnect rebuild.
- **Contested claims surfaced (audit: contradiction_ids hardcoded empty → contested feature inert).** The KnownState/InquiryClaim surface must expose real `contradiction_ids`/`contested_by_claim_id` (they exist in claims.py; the API adapter hardcodes []). Make the engine view populate them so the adapter can pass them through. Test: two conflicting claims → the view reports the contested link both ways.
- **Fail-closed (audit #6/#7).** In a production mode (env EVERQUILL_REQUIRE_SECURE=1, set on Railway by F), the engine/db startup RAISES if EVERQUILL_MASTER_KEY is absent (no fail-open DEK storage) and if the runtime connection is the table owner (append-only REVOKE wouldn't bind). Dev stays lenient. Tests: require-secure + missing key → raises; owner connection under require-secure → refuses.
- **Category contract (audit: gate expects `person`, prod emits `npc`).** Decide the canonical entity category vocabulary and make the engine view emit it consistently (the fix can live here or in the gate — coordinate with C; document the decision in known-state.md). Persons = npc + character.
- Keep all tests green; goldens/pins per replay rules; projector bumps where folds change.

### Team C — LLM: typed narration boundary + gate completeness (offline)
Lane: docs/contracts/**, evals/**, llm/**.
- **Narrator gate → bound to allowed deltas (audit #2, Codex reproduced kill-on-miss).** Move from word-list checks to clause-level agreement: the narration must not assert an outcome the committed deltas don't support (a kill needs a wound_transition dispatched/death delta; invented inventory/door actions need matching deltas). Build a typed "allowed-facts" set from the outcome contract and gate the prose against it. Keep G1-G6; strengthen G3 (kill-on-miss / invented-state) to be semantic, not lexical.
- **Fix the npc/person category mismatch** in the gate's person detection (coordinate with A's category decision — persons = npc + character). Add a fixture using PRODUCTION categories (npc) so the harness catches the contract, not just the 'person' fixtures.
- Re-run the narration eval harness green; add fixtures for kill-on-miss and invented-inventory that the OLD gate passed and the new one rejects.

### Infra sub-task (Team F-infra) — one authoritative release gate
Lane: Makefile, .github/**, pyproject.toml (lint config), docs/ops/**.
- **Authoritative release gate (audit #8).** One command (`make release-check` or a CI job) that runs: engine `tests/`, `api/tests`, `llm/` tests, client `npm run build` + lint, Python ruff, and FAILS on zero-collection or a missing tool (a green default `pytest` that silently skips api/tests+llm is the finding). CI runs all of it with an ephemeral Postgres.
- **Fix the 3 E501 lint failures** (audit: Python lint currently fails) in llm/* — reflow, don't `# noqa`.
- Do NOT run the DB suites concurrently with Team A. This sub-task is mostly config; if you must run a DB check, coordinate/serialize.

## Wave 2 (after Team A lands) — API + client consume the new surfaces

### Team F — api: serve canonical record, degrade-not-block, wire contested/decrypt
Lane: api/**, migrations (apply), docs/ops/**.
- Serve A's canonical public-turn record for first response, duplicate (return the stored record WITH its narration, not narration:null), and a new `GET /api/turns?since=` for client Chronicle reconnect.
- **Rate-limit degrade-not-block (audit #4, violates "never meter the conversation").** The deterministic engine path must NEVER be blocked by the daily turn cap / spend breaker; only the PAID LLM layers (parser/narrator) degrade (fall back to no-narration / canned-intent) when caps hit. Budget reserved atomically ONCE per command (fix confirmation double-counting).
- **Adapter fixes (audit #2 context integrity):** pass through A's real contradiction_ids (stop hardcoding []); DECRYPT prior player text before it reaches the assembler (currently reaches it as an encryption marker); normalize entity categories to the agreed vocab; enforce the assembler's final token cap after pinned claims.
- **Fail-closed readiness:** set EVERQUILL_REQUIRE_SECURE=1 on Railway; readiness 503s if the secure preconditions fail. Remove owner-DB migration authority path where feasible / document the residual.
- Deploy + live-verify: response-loss retry returns identical record; a rate-capped account still plays (deterministic, no narration) rather than being blocked.

### Team D — client: Chronicle durability + reconnect + 429
Lane: client/**.
- Persist the turn Chronicle locally (not session-only) and rebuild from `GET /api/turns` on reconnect/reload (audit #1 client half) — a reload must not lose the visible history.
- Full 429 handling in System voice (the engine path shouldn't 429; if a paid-layer degrade happens, show it diegetically). Composer-loss-on-in-flight-request fix.

## Deferred (ticketed, not this pass)
Timer worker (Sprint 4). Deep account lifecycle: export/rotation/multi-device/logout (audit #5 beyond the invite-persistence check). Full tenant-complete encrypted offsite DR (audit #9 beyond fail-closed). Client PWA/asset-budget polish (audit P2/P3). Content-drift override removal (needs the legacy-world wipe — George's pending call). Docs/registry refresh (audit #10 — fold into closeout).
