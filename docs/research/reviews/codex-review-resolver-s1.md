# Adversarial Architecture Review

Review baseline: `03ba16a` (`main`). Read-only verification ran 63 pure engine/contract/golden tests; all passed. DB tests were not run because they destructively reset the configured database.

## CRITICAL

### CRITICAL-1 — The LLM’s “advisory” `stat_hint` directly changes outcomes

**Evidence:** [intent.schema.json:5](<docs/contracts/intent.schema.json:5>), [resolver.py:664](<everquill_engine/resolver.py:664>), [resolver.py:676](<everquill_engine/resolver.py:676>)

**Failure scenario:** The schema says every hint is advisory, but the resolver selects `actor["aptitudes"][intent["stat_hint"]]`. With seed 42, the same physical attack against Hedda resolves:

- `stat_hint="might"` → might 5 → `ROUTINE`
- `stat_hint="wits"` → wits 10 → `TRIVIAL`, no roll and no physical delta
- `stat_hint="presence"` → presence 4 → `RISKY`

Parser variance therefore changes difficulty and state. The LLM is indirectly refereeing.

**Bounded fix:** Ignore `stat_hint` for resolution. For v1, use the engine-owned `DEFAULT_STAT_FOR_ACTION`; later, select aptitudes only through engine-owned techniques/action metadata. Retain the hint solely for parse audit and mismatch telemetry.

### CRITICAL-2 — NPC/creature HP deltas are logged and narrated but discarded from state

**Evidence:** [resolver.py:363](<everquill_engine/resolver.py:363>), [folds.py:75](<everquill_engine/folds.py:75>), [0002_projections.sql:26](<migrations/0002_projections.sql:26>)

**Failure scenario:** A strong hit emits `{"delta_type":"hp","entity_id":"npc...","amount":-3}` and exposes it in the committed outcome. `_apply_sheet_delta()` finds no `character_sheet` row for the NPC and silently returns. The log and narrator say the NPC was injured; the operational state records nothing, so subsequent actions operate on unchanged authored truth.

**Bounded fix:** Add a server-only mutable entity-state projection for all damageable entities, seeded when entities are committed, and apply HP/inventory/position deltas there. Until that exists, reject outcomes targeting non-projected mutable state rather than silently dropping them.

## HIGH

### HIGH-1 — Command execution is neither end-to-end transactional nor safely retried

**Evidence:** [cli.py:180](<everquill_engine/cli.py:180>), [cli.py:259](<everquill_engine/cli.py:259>), [store.py:110](<everquill_engine/store.py:110>), [store.py:176](<everquill_engine/store.py:176>)

**Failure scenario:** Two requests read turn count 6, the same actor state, and the same RNG counter. Both become `turn_pc_7`. The first action commits; the second, even if semantically different, is absorbed as a duplicate. With distinct command IDs, the loser receives `ConcurrencyError`, but no caller reloads state and re-runs resolution. Retrying only the stale `EventSpec`s can reuse the old RNG index and stale deltas.

Additionally, CLI reads start an ambient psycopg transaction before `append_command()`; its `conn.transaction()` then becomes a savepoint. A scripted session can remain one outer transaction, so a late failure rolls back earlier “committed” turns.

**Bounded fix:** Use a client-generated immutable command ULID. Implement one orchestration transaction that locks/reads state, resolves, appends, and commits. On `ConcurrencyError`, reload and re-resolve under the same command ID. Reject unexpected ambient transactions at the store boundary.

### HIGH-2 — Concurrent disjoint streams can overwrite Tier-1 world state

**Evidence:** [store.py:185](<everquill_engine/store.py:185>), [store.py:270](<everquill_engine/store.py:270>), [folds.py:279](<everquill_engine/folds.py:279>)

**Failure scenario:** Commands on two different character streams both load the same `world_state`. Each folds its event locally, then performs a full-row upsert. The later writer overwrites the earlier writer’s RNG counters, world time, or `last_event_id` with its stale image. No `(stream_id, version)` conflict protects the singleton world row. Live Tier-1 state then differs from the event log until a rebuild.

World time is also computed as an absolute `old_time + cost`; concurrent actions can collapse 10 and 60 minutes into 60 rather than 70.

**Bounded fix:** Lock `world_state FOR UPDATE` before resolution, or use compare-and-set/projector version checks. Serialize global-clock advancement and merge RNG counters atomically rather than replacing the JSON document.

### HIGH-3 — Replay versioning is not implemented; the golden test permits silent historical rewrites

**Evidence:** [folds.py:267](<everquill_engine/folds.py:267>), [store.py:374](<everquill_engine/store.py:374>), [test_folds.py:57](<tests/test_folds.py:57>), [test_folds.py:64](<tests/test_folds.py:64>)

**Failure scenario:**

- `payload_version` is ignored by `fold_event`; there is no pure upcaster registry.
- There is no `projector_version`.
- Corpus coverage checks only event-type names, so adding version 2 of an existing type does not require a version-2 fixture.
- A developer can change a fold and regenerate the snapshot; CI passes without a projector-version bump.
- Rebuild truncates and directly repopulates live tables rather than building/diffing a shadow projection.

A balance or projector change can therefore reinterpret every historical event during rebuild.

**Bounded fix:** Introduce a `(event_type, payload_version)` registry with pure chained upcasters, persisted projector versions, enforced fixture coverage for every pair, and a test requiring a projector-version bump on projection diffs. Rebuild into versioned shadow tables, diff, then atomically swap.

### HIGH-4 — Append-only enforcement is ineffective for the actual connection role

**Evidence:** [0001_event_store.sql:45](<migrations/0001_event_store.sql:45>), [test_db_store.py:122](<tests/test_db_store.py:122>)

**Failure scenario:** The migration revokes `UPDATE, DELETE` only from `PUBLIC` and explicitly acknowledges that the development/Railway owner or superuser remains unrestricted. No migration provisions a non-owner `app_role`. A bug, compromised API, or maintenance query using `DATABASE_URL` can update, delete, or truncate canon.

**Bounded fix:** Separate migrator/owner and runtime roles. Connect the application as a non-owner with explicit `SELECT/INSERT` and sequence privileges only; revoke `UPDATE`, `DELETE`, and `TRUNCATE` explicitly. Add a live privilege test using `has_table_privilege()` and an attempted mutation.

### HIGH-5 — The claim projection cannot implement the binding claim lifecycle

**Evidence:** [0002_projections.sql:41](<migrations/0002_projections.sql:41>), [0002_projections.sql:46](<migrations/0002_projections.sql:46>), [0002_projections.sql:69](<migrations/0002_projections.sql:69>)

**Failure scenario:** The table lacks the contract’s controlled `predicate`, typed values, `strength`, `derived_from_claim_id`, evidence links, and `world_valid`. Its active-claim index omits `predicate`. Consequently:

- write-time contradiction probes cannot be expressed as indexed equality queries;
- distinct-root corroboration cannot be calculated from multiple evidence links;
- inheritance lineage and time-valid whereabouts cannot be represented;
- “confidence” remains persisted where the v2 contract requires evidence strength.

**Bounded fix:** Replace the minimal free-text shape with the synthesis §2.3 typed schema and required partial/lineage/recency indexes before claim-producing gameplay is exposed.

### HIGH-6 — Duplicate claim/timer domain IDs make live projection and replay disagree

**Evidence:** [store.py:201](<everquill_engine/store.py:201>), [store.py:308](<everquill_engine/store.py:308>), [store.py:348](<everquill_engine/store.py:348>), [folds.py:184](<everquill_engine/folds.py:184>)

**Failure scenario:** Claims are not preloaded. If two valid events carry the same `claim_id`, live projection keeps the first through `ON CONFLICT DO NOTHING`; rebuild folds both into a dictionary and keeps the last. Timer starts have a similar mismatch: live conflict updates only status/fire fields, while rebuild inserts the later timer’s kind, subject, due time, and payload.

**Bounded fix:** Make domain-ID uniqueness canonical, not projection-local. Reject duplicate `claim_id`/`timer_key` before committing the event, and make folds raise consistently on duplicates during both incremental projection and rebuild.

### HIGH-7 — CI does not execute the database data-layer DoD

**Evidence:** [conftest.py:17](<tests/conftest.py:17>), [ci.yml:51](<.github/workflows/ci.yml:51>), [test_db_determinism.py:89](<tests/test_db_determinism.py:89>)

**Failure scenario:** CI intentionally supplies no `DATABASE_URL`, so store, migration, real rebuild-equivalence, xid8, constraints, and privilege tests skip. Broken SQL or incremental-vs-rebuild divergence can merge while the declared “tests 1–3 green” DoD appears green.

**Bounded fix:** Add an ephemeral PostgreSQL service to CI, run migrations and all DB tests against it, and fail if any DB-marked test skips.

### HIGH-8 — Player-authored text is stored unencrypted

**Evidence:** [resolver.py:681](<everquill_engine/resolver.py:681>), [store.py:132](<everquill_engine/store.py:132>), [0001_event_store.sql:31](<migrations/0001_event_store.sql:31>)

**Failure scenario:** `intent_parsed` stores the complete intent, including player-authored `approach` and quoted dialogue, directly in plaintext JSONB. Backups and replicas retain it permanently, and deleting a player key cannot crypto-shred it as required by synthesis §2.1.

**Bounded fix:** Encrypt player-authored fields before append using a per-player envelope key; store ciphertext and a key reference, while leaving engine-required structured enums plaintext. Test that raw utterances do not appear in event dumps.

## MEDIUM

### MEDIUM-1 — No enforced KNOWN-state boundary exists for API/narrator consumers

**Evidence:** [0002_projections.sql:23](<migrations/0002_projections.sql:23>), [store.py:218](<everquill_engine/store.py:218>), [world.py:80](<everquill_engine/world.py:80>), [test_resolver.py:189](<tests/test_resolver.py:189>)

**Failure scenario:** `load_fold_state()` returns exact PC aptitude numbers, and `WorldContent` exposes authored `true_sheet` objects. There is no Tier-1 KNOWN-sheet table/view or safe query object. A future scene/context endpoint that serializes the convenient full state object leaks character aptitudes; returning a world entity leaks authored threat and aptitude numbers. The current leak test checks event-log text only, not actual API/narrator payloads.

No active API leak was found in the present hello/health endpoints, and `outcome_contract()` itself does not expose true numbers.

**Bounded fix:** Add explicit `RefereeState` and `KnownState` repositories/types, with narrator/API code able to import only the latter. Validate real API and narrator payloads against the closed schemas and add denylist tests for aptitude/threat fields.

### MEDIUM-2 — The sibling `command_id#n` encoding has namespace collisions

**Evidence:** [store.py:112](<everquill_engine/store.py:112>), [store.py:137](<everquill_engine/store.py:137>)

**Failure scenario:** A legal command ID `pay#1` is indistinguishable from sibling 1 of command `pay`. If `pay` lands first, a later independent `pay#1` is absorbed at the initial probe. If `pay#1` lands first, multi-event `pay` rolls back on its sibling collision and is reported as absorbed even though its base command never committed.

Partial sibling writes cannot interleave because the inserts are transactional; the flaw is namespace aliasing.

**Bounded fix:** Use a `command` table keyed by raw command ULID and store `command_id + event_ordinal` as separate columns with `UNIQUE(command_id, event_ordinal)`. At minimum, enforce a strict ULID grammar that excludes the suffix syntax.

### MEDIUM-3 — Timer deadlines and tie ordering are not replay-stable

**Evidence:** [store.py:348](<everquill_engine/store.py:348>), [store.py:374](<everquill_engine/store.py:374>), [store.py:407](<everquill_engine/store.py:407>), [0003_timers.sql:23](<migrations/0003_timers.sql:23>)

**Failure scenario:** `due_at` is materialized as Unix epoch plus `world_due` minutes, so every current pending timer is decades overdue to the contract’s real-time `due_at <= now()` sweeper. Separately, live timer IDs follow insertion order, but rebuild reinserts timers in sorted `timer_key` order. Two pending timers with equal due time can therefore reverse their prescribed `(due_at, id)` fire order after rebuild.

**Bounded fix:** Record the actual real-world deadline as a timer-start fact and fold it verbatim. Use stable `created_event_id`/event ULID as the tie-breaker rather than a rebuild-generated projection identity.

### MEDIUM-4 — RNG roll-site independence and counter uniqueness are conventional only

**Evidence:** [resolver.py:761](<everquill_engine/resolver.py:761>), [folds.py:284](<everquill_engine/folds.py:284>), [test_dice.py:63](<tests/test_dice.py:63>)

**Failure scenario:** Every action outcome for a character shares the generic `("character:<id>", "action")` stream. Adding a new draw at another action roll site using that stream shifts all later outcome rolls. The tests prove only that distinct streams do not perturb each other. The database also has no uniqueness constraint for `(rng.stream, rng.index)`, so a stale retry can commit a reused index if stream-version serialization is bypassed or broadened.

The counter is rebuildable from stored RNG records under the current convention, but duplicates and gaps are silently accepted.

**Bounded fix:** Register stable semantic roll-site IDs and require each site to use its own stream. Add a canonical uniqueness constraint or reservation row for stream/index and tests that inserting a new roll site does not change existing outcome streams.

### MEDIUM-5 — Intent schema enforcement is partial, and duration semantics are ignored

**Evidence:** [resolver.py:179](<everquill_engine/resolver.py:179>), [resolver.py:641](<everquill_engine/resolver.py:641>), [intent.schema.json:64](<docs/contracts/intent.schema.json:64>)

**Failure scenario:** `_validate_intent()` does not reject additional properties, duplicate/invalid target IDs, empty approaches, malformed dialogue, invalid plausibility hints, malformed duration hints, or ambiguity values. These inputs can be committed despite `additionalProperties:false`. `"train for one hour"` and `"train until the caravan leaves"` also both receive the same fixed duration because `duration_hint` is never consumed.

**Bounded fix:** Validate into a closed typed model generated from the JSON Schema before resolver entry. Bind supported duration forms deterministically or reject them as unsupported rather than silently replacing them.

### MEDIUM-6 — Event DDL omits stable external identity and stream typing

**Evidence:** [0001_event_store.sql:21](<migrations/0001_event_store.sql:21>), [resolver.py:1028](<everquill_engine/resolver.py:1028>)

**Failure scenario:** The synthesis shape requires `event_ulid` and `stream_type`; neither exists. `outcome_contract()` exposes the database identity as a string. Logical copy/merge workflows cannot retain globally stable references without preserving database IDs, and stream-type queries must parse text prefixes. No `projection_checkpoint` table exists for the declared xid8-safe Tier-2 consumers.

**Bounded fix:** Add immutable unique event ULIDs, explicit stream type, and checkpoint DDL before external references or rumor workers ship. Keep bigint `id` as the local ordering key.

### MEDIUM-7 — Existing worlds are not pinned to an immutable authored-content version

**Evidence:** [world.py:22](<everquill_engine/world.py:22>), [cli.py:188](<everquill_engine/cli.py:188>), [cli.py:194](<everquill_engine/cli.py:194>)

**Failure scenario:** Genesis stores only the YAML filename while true sheets and laws are reloaded from the current file. Editing an NPC threat band or law under the same filename changes future rulings in an existing world without a canon event or reconstructable content version.

Historical deltas still replay unchanged, but the event log is not sufficient to explain which authored truth governed a ruling.

**Bounded fix:** Commit and verify a content manifest hash/version at genesis, retain immutable server-side content snapshots by hash, and represent in-world semantic changes as new canon events or new worlds.

## LOW

### LOW-1 — Folded contracts still admit floating-point domain values

**Evidence:** [outcome.schema.json:202](<docs/contracts/outcome.schema.json:202>), [outcome.schema.json:280](<docs/contracts/outcome.schema.json:280>), [world.py:99](<everquill_engine/world.py:99>)

**Failure scenario:** Flag values and deed notoriety permit arbitrary JSON numbers, and rumor notoriety is normalized to `float`. A future rule can therefore place floats into event payloads and folded flags/scoring despite the integer-only architecture. Serialization and equality behavior can then differ across Python/Postgres boundaries.

Current resolver-emitted applied amounts and world-time values are integers.

**Bounded fix:** Restrict folded numeric domain fields to integers or integer basis points in schemas and loader types; reserve floats only for noncanonical presentation coordinates.

## Sound properties observed

- Folds do not import dice, ladder, resolver, clock, chargen, or world rules, and current HP/coin/training amounts are stored before folding.
- Dice faces, modifiers, tiers, and applied deltas are stored; replay does not re-roll.
- Wall-clock `recorded_at` and xid8 transaction metadata are excluded from canonical dumps and folds.
- The xid8 event column, stream-version uniqueness, location/world-time index, event-type/world-time index, and timer pending indexes are present.
- Current scripted `outcome_contract()` values validate against `outcome.schema.json`; no authored aptitude or threat values were found in that narrator-facing structure.
- Multi-event inserts and their Tier-1 writes are atomic when `append_command()` owns the top-level transaction; partial sibling interleaving is not possible.