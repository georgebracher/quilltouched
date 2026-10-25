# Quilltouched Security + Architecture Review — Round 2

**Scope:** current working tree against baseline `03ba16a` (HEAD `dd939fe` plus pre-existing working-tree changes).  
**Method:** read-only static review, existing test/evaluation evidence, and bounded no-write in-memory reproductions. No database, external LLM, or production calls were made.

## Executive summary

| Severity | Count |
|---|---:|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 6 |
| LOW | 2 |

The strongest controls are the typed engine boundary, per-account schema routing, KnownState extraction, deterministic assembler, forced parser tool, and transactional beat locking.

The largest remaining risks are outside those controls:

1. The resolver authorizes targets against the entire authored world rather than the player’s addressable scene.
2. The perceived manifest includes authored entities marked hidden.
3. The public outcome contract exposes exact HP-derived internal deltas.
4. Pending confirmations are not bound to the intent displayed on retries.
5. Paid LLM paths lack input, concurrency, rate, and spend controls.

---

## HIGH findings

### EQ-R2-01 — Structured intents can mutate arbitrary off-scene entities

**Locations:** `api/main.py:683-692`, `api/main.py:708-772`, `docs/contracts/intent.schema.json:35-43`, `everquill_engine/intent.py:214-224`, `everquill_engine/resolver.py:208-221`, `everquill_engine/resolver.py:683-693`, `everquill_engine/resolver.py:396-413`, `everquill_engine/resolver.py:1019-1026`

An authenticated caller may submit the documented structured-intent form directly. This skips the parser’s scene roster. Schema validation checks only the target ID’s shape.

The engine’s `_roster()` then treats every authored entity, every location, and every manifest row as addressable:

```python
ids = set(world.entities) | set(world.locations) | set(manifest)
```

`decide_tier()` accepts membership in this global map as sufficient authorization. No locality check follows for physical, social, dialogue, observation, or research actions.

**Validated failure scenario:** from Market Row, a crafted physical intent targeted Fenn Bracey in the Guild Hall. The resolver accepted it as trivial and changed Fenn from 6 HP to 0. The resulting deed was incorrectly located at Market Row with Market Row witnesses. No travel or confirmation occurred.

This also creates an existence oracle for hidden entity IDs and permits impossible first-hand observation or research against distant subjects.

**Counterevidence and limits:** mutations remain within the caller’s per-account schema; no cross-account access was found. Dice and tier rules still apply, but they do not restore object addressability.

**Bounded fix:**

- Derive an engine-owned target-capability set before tiering.
- Require co-location and visibility for physical/social/dialogue/observation targets.
- Require ownership for inventory targets.
- Restrict movement to direct connections and research to known Codex subjects.
- Reject unknown and unauthorized targets identically to avoid an existence oracle.
- Consider replacing arbitrary structured quick-pick objects with opaque server-issued suggestion IDs, while retaining the engine check.
- Add regressions proving remote Fenn and the hidden marriage seal produce no events or mutations.

### EQ-R2-02 — Hidden authored entities leak through the “perceived” manifest

**Locations:** `content/world/harrowdown.yaml:318-328`, `everquill_engine/views.py:260-280`, `api/main.py:406-434`, `api/context.py:54-73`, `api/context.py:170-198`, `llm/assembler.py:368-378`, `llm/narrator.py:72-76`

`item.harrowdown.marriage_seal` is explicitly marked `SECRET (engine-only)` and tagged `hidden`. Nevertheless, `load_known_state()` includes every manifest entity at the player’s location. It performs no hidden-tag, discovery-fact, or perception check.

The resulting ID and name reach:

- `GET /api/scene`
- the free-text parser roster
- the narrator’s scene manifest

**Validated failure scenario:** when the PC is in Ferrier’s Chandlery, the actual KnownState/context builders expose:

```text
item_harrowdown_marriage_seal — Reyla's marriage seal
```

The parser is then invited to select the secret as a valid target, and the narrator is told it is a real perceived entity.

Raw tags do not leak, but the existence, identity, location, and exact target ID of a plot-critical resurrection component do.

**Bounded fix:**

- Add an engine-owned visibility predicate at `everquill_engine/views.py:260-280`.
- Exclude entities tagged `hidden` unless a committed discovery/perception fact makes them known to that character.
- Keep API, parser, and narrator consuming the same filtered projection.
- Add a regression asserting the seal is absent from KnownState, scene JSON, parser roster, and narrator context before discovery, and appears in all four afterward.

### EQ-R2-03 — Public outcome contracts expose exact HP and internal deltas

**Locations:** `everquill_engine/views.py:59-63`, `everquill_engine/resolver.py:300-306`, `everquill_engine/resolver.py:396-413`, `everquill_engine/resolver.py:1019-1026`, `everquill_engine/resolver.py:1249-1285`, `docs/contracts/outcome.schema.json:156-166`, `api/main.py:589-590`, `api/main.py:625-640`, `api/main.py:647-662`

KnownState correctly converts HP into wound words, but the outcome path bypasses KnownState.

For a trivial dispatch, the resolver reads the target’s exact current HP and emits its negation:

```python
remaining = int(state["hp"])
deltas.append(_hp(target_id, -remaining, ...))
```

`outcome_contract()` copies that amount unchanged. The contract is sent both to the client and the narrator.

**Validated failure scenarios:**

- An NPC at 1 HP produces `{"delta_type":"hp","amount":-1}`, revealing exact remaining HP.
- Near-death self-harm exposes the player’s own hidden HP through the resolver’s clamp-to-one calculation.
- Normal combat exposes the engine’s exact HP-unit damage model.

The outcome schema preserves rather than redacts this field. Prompt instructions cannot protect data already present in the model input, and the client sees it directly.

Generic internal flag keys and values are also copied. No currently secret-valued flag was found, but the path is unsafe for future flags.

**Bounded fix:**

- Keep exact deltas only in canonical server-side events.
- Create an allowlisted player/narrator `OutcomeView`.
- Convert HP changes to qualitative wound transitions or fiction-level effects such as `wounded` and `dispatched`.
- Allowlist public flag types and strip internal keys/values.
- Add end-to-end leak tests over the complete `/api/action` JSON and rendered narrator prompt, including target HP=1 and low player HP.

---

## MEDIUM findings

### EQ-R2-04 — Pending retry can display intent B while confirmation executes intent A

**Locations:** `everquill_engine/beat.py:219-248`, `everquill_engine/beat.py:291-309`, `everquill_engine/beat.py:358-390`, `api/main.py:785-793`

The first assessment stores intent A. A later `POST /api/action` with the same `command_id` and a different valid intent B finds the pending row, but the query does not load or compare the stored intent. The API returns the current request’s B alongside `<<Assessment stands. Proceed?>>`.

Confirmation independently reloads and resolves stored A.

**Failure scenario:**

1. Submit dangerous A under command X.
2. Retry/redeclare harmless B under X.
3. Receive a pending response displaying B.
4. Confirm X.
5. A executes.

No concurrency is required. This defeats the informed-confirmation purpose of the Dire+/sealed/irreversible beat.

World locks, row locks, expiry, original-intent persistence, and double-confirm absorption are all sound but do not bind the presented intent.

**Bounded fix:** bind each command ID to a canonical intent hash and return `409` on mismatch. Pending responses must always return the stored intent. Add an A→B→confirm regression.

### EQ-R2-05 — Structured intents have unbounded strings and arrays

**Locations:** `api/main.py:724-729`, `api/main.py:757-765`, `docs/contracts/intent.schema.json:35-48`, `docs/contracts/intent.schema.json:71-79`, `docs/contracts/intent.schema.json:94-116`, `everquill_engine/intent.py:118-130`, `everquill_engine/intent.py:214-226`, `llm/narrator.py:61-90`

The 2,000-character limit applies only to free-text input. Direct structured intents have no `maxLength`, `maxItems`, or overall serialized-size limit.

A no-write validation confirmed that a 2,000,000-character `approach` passes both JSON Schema and `parse_intent()`.

Consequences include:

- Very large event-log records and responses.
- Huge narrator prompts outside the assembler’s token budget.
- Provider context failures and retry amplification.
- Request-memory pressure.
- Quadratic duplicate checking in `parse_intent()` because `target in targets` operates on a growing list.
- Potentially expensive JSON Schema `uniqueItems` validation over large arrays.

**Bounded fix:**

- Add `maxLength` and `maxItems` at every intent level.
- Impose a small overall canonical-intent byte limit before schema validation.
- Cap the final rendered model input.
- Replace the list-based duplicate check with a set.
- Apply an ingress/body-size limit independent of application validation.

### EQ-R2-06 — Paid turn execution has no rate, concurrency, or spend controls

**Locations:** `api/main.py:693-721`, `api/main.py:723-756`, `api/main.py:799-807`, `api/llm_gateway.py:130-148`, `api/llm_gateway.py:171-185`, `everquill_engine/db.py:65-79`, `Procfile:1`

Any valid device token can issue unlimited fresh-command turns. A free-text turn can invoke Haiku and Sonnet; fresh command IDs bypass idempotency.

The SDK permits up to three parser attempts and two narrator attempts. Each synchronous request retains an unpooled database connection while awaiting model calls. Production is configured as one Uvicorn process.

The repository’s measured estimate is approximately `$0.0237` per typed full turn, or about `$237` per 10,000 turns before retry amplification.

Existing controls—authentication, output caps, timeouts, prompt caching, and the usage ledger—bound or observe individual calls only. There is no `429` path, per-account concurrency guard, global LLM semaphore, hard budget ceiling, or retry circuit breaker.

**Bounded fix:**

- Distributed per-account token bucket.
- One in-flight turn per account.
- Small global LLM-call semaphore.
- Daily call/spend ceilings with `429 Retry-After`.
- Retry budget and provider circuit breaker.
- Release database connections before model network waits where transaction semantics permit.

### EQ-R2-07 — Duplicate free-text commands pay for parsing before idempotency

**Locations:** `api/main.py:723-795`, `everquill_engine/beat.py:217-248`, `api/main.py:644-663`, `api/tests/test_api_pipeline.py:74-84`

Free-text parsing occurs before the engine checks whether the command is already pending or committed. Replaying one command ID therefore purchases another Haiku parse every time.

Only duplicate narration is suppressed. The current duplicate API test uses a structured intent and does not cover this paid path.

**Bounded fix:** probe command state before parsing and return the stored outcome or pending assessment with the stored parsed intent. Single-flight concurrent first submissions and bind the command to a canonical request hash so this repair also closes EQ-R2-04.

### EQ-R2-08 — Narrator correctness and injection resistance are prompt-only

**Locations:** `llm/narrator.py:61-90`, `llm/prompts/narrator.md:8-32`, `llm/prompts/narrator.md:52-54`, `api/llm_gateway.py:171-191`, `api/main.py:589-640`, `everquill_engine/resolver.py:619-629`, `api/context.py:92-112`, `llm/narrator_eval.py:181-188`

Player fields are correctly JSON-quoted for narration, and the prompt explicitly labels all context as untrusted data. Direct injection canaries resisted all seven recorded evaluation runs.

However, production accepts any nonempty text response. There is no runtime gate for:

- Success framing on a miss.
- Invented entities or objects.
- Unsupported NPC speech or reactions.
- Mechanics or system markup.
- Contradictions of committed deltas.

Existing evaluation evidence demonstrates the gap: the injection fixture’s only delta was `heard_someone_at_the_shutters`, but a supposedly passing narration invented a chair, table, movement inside the shop, and dialogue from Elam (`llm/results/20260713-191302-narr-full-1.json:188-194`). The linter detects unknown proper nouns and selected success/failure vocabulary, not unsupported common nouns or semantic inventions.

Second-order input is reachable: `_ensure_deposit()` can store the player’s `approach` as a claim, and `api/context.py` later feeds claim text back to the narrator. It remains JSON data, but still relies entirely on model obedience.

**Bounded fix:**

- Treat narration as untrusted output.
- Add a deterministic admissibility gate for markup, mechanics vocabulary, entity references, explicit constraints, and mechanically testable outcome contradictions.
- Use constrained structured narration output where possible.
- Fall back to deterministic engine prose when validation fails.
- Add stored claim/journal injection fixtures, not only same-turn approach injection.

### EQ-R2-09 — Narration provenance is not persisted or bound to the full content bundle

**Locations:** `docs/tickets/sprint-2.md:12`, `api/main.py:543-569`, `api/main.py:644-663`, `api/bootstrap.py:57-71`, `api/context.py:38-51`, `api/context.py:151-164`, `everquill_engine/events.py:154-195`, `everquill_engine/folds.py:360-375`

The locked contract requires prose, assembler version, and content hash to be stored as a narration event bound to the outcome event.

The API currently records them only in telemetry and the immediate response. Absorbed retries return the outcome with `narration: null`.

There is partial event scaffolding in `events.py`, but the fold registry has no `narration_generated` handler, so using it through the normal store path would fail on an unknown fold type.

Separately, bootstrap drift detection hashes only the main world YAML. Narrator atmosphere and slot maps are loaded from independent files. `harrowdown-narrator.yaml` is cached per process, so old and newly started workers can assemble different contexts from the same canonical event log without a content-drift refusal.

The assembler itself hashes the actual envelope, but that hash is not persisted canonically.

**Failure scenarios:**

- Outcome and prose are produced, but the HTTP response is lost. A retry recovers the outcome but not what the player was shown.
- A sidecar changes between deployments. The same event state assembles different narration context, while the world content manifest still passes.

**Bounded fix:**

- Add an audit-only fold for `narration_generated`.
- Append prose, outcome event identity, model, prompt version, assembler version, and context hash under an idempotent narration command.
- Return persisted narration on duplicate requests.
- Hash/version one immutable content bundle containing world YAML, narrator sidecar, slot maps, prompt versions, and assembler config.
- Refuse drift or explicitly migrate the world to a new bundle.

---

## LOW findings

### EQ-R2-10 — Public invite claim is a guessing oracle with no entropy enforcement

**Locations:** `api/main.py:368-393`, `api/accounts.py:69-71`, `api/accounts.py:84-123`

Invite codes are arbitrary environment strings. The public claim endpoint has no local rate limit or minimum entropy requirement and distinguishes unknown codes (`403`) from used codes (`409`).

A guessed valid code creates a persistent account and device token.

This is conditional on production invite-code entropy and any upstream throttling, neither of which is established in the repository.

**Bounded fix:** generate codes with at least 128 bits of entropy, store only hashes in an atomic database-backed invite table, add claim-specific distributed throttling, and minimize validity-state distinctions.

### EQ-R2-11 — Tenant schema identity is only a 32-bit prefix without a database uniqueness constraint

**Locations:** `api/accounts.py:54-66`, `api/accounts.py:97-120`, `api/accounts.py:149-174`, `migrations/0007_accounts.sql:22-27`

World and schema names use the first eight hex characters of the account ID. Sequential collisions are checked in application code, but the check and insert are not protected by a database uniqueness constraint over the prefix.

Two concurrent claims that randomly generate the same 32-bit prefix can both pass the pre-check and create accounts routed to the same schema.

The probability for any single pair is extremely low, account IDs are server-generated, and no attacker-controlled account-ID path was found. Impact would nevertheless be direct cross-account world sharing.

**Bounded fix:** use the full account ID in schema names or persist a prefix column with a database `UNIQUE` constraint and retry allocation on conflict.

---

## Controls found sound

### Injection and LLM authority

- The narrator renders all action, outcome, claim, and journal-capable text through `json.dumps(..., sort_keys=True)` at `llm/narrator.py:61-90`; no prompt-role or delimiter break was found there.
- The narrator prompt explicitly classifies all supplied data as untrusted at `llm/prompts/narrator.md:52-54`.
- Parser output is forced through one named strict tool at `api/llm_gateway.py:118-147`.
- Parser output is subsequently checked by JSON Schema and again by the engine’s closed typed model.
- `stat_hint`, plausibility, and duration hints do not acquire referee authority.
- The parser’s raw Markdown `## Utterance` delimiter is weaker than the narrator’s JSON encoding, but no tool-schema or engine-authority escape was found. Parser injection tests and downstream validation materially limit the consequence.

### True-sheet boundary

- `api/state.py`’s capture-and-abort read rolls back without appending an event and respects the connection’s account-specific `search_path`.
- KnownState structurally excludes aptitudes, threat bands, and raw HP.
- `tests/test_known_boundary.py` prevents API/LLM modules from importing referee-grade state.
- `harrowdown-narrator.yaml` currently feeds only the `atmosphere` section into context. Its `voice` section is ignored, and no TRUE/SECRET block is consumed.
- `canon_excerpts` is currently empty in the live adapter, so no lore TRUE block reaches the narrator.
- Exceptions are the hidden-entity visibility error and the separate outcome-delta path reported above.

### Authentication and tenant routing

- Device tokens use `secrets.token_hex(32)`—256 bits—and only SHA-256 digests are stored.
- A salt is unnecessary for a uniformly random 256-bit bearer token.
- Parameterized digest lookup does not expose a practical timing attack against that entropy.
- The ops token uses `hmac.compare_digest`.
- Schema names are derived from server-generated hex and checked against `^world_[0-9a-f]{8}$` before quoted DDL or `search_path` use.
- Request-supplied world IDs are exact-matched to the authenticated account and never interpolated into SQL.
- Entity IDs are not used to construct schema names or SQL syntax.
- No SQL-injection path or crafted world/entity cross-schema path was found.
- The unauthenticated legacy action path returns `410` before database or LLM work.
- The database `UNIQUE(invite_code_used)` constraint prevents two successful claims of one invite code. A simultaneous losing request may surface as an uncaught database error, but it cannot issue a second account.
- Same command IDs in different accounts remain isolated by per-account schemas.

### Commit-beat concurrency

- World and pending rows are locked transactionally.
- Concurrent double-confirm is absorbed after the first commit.
- A repeated assessment cannot overwrite the stored pending intent.
- Confirmation always resolves the originally stored intent.
- Expiry is checked under the same world lock and marks the row expired before returning `410`.
- No cross-account command-ID collision was found.
- No stale higher-risk transition within the ten-world-minute window was demonstrated.
- The remaining defect is presentation/binding of a mismatched retry intent, EQ-R2-04.

### Determinism and failure isolation

- The assembler uses integer scoring, canonical sorted JSON, explicit total-order sorting, and deterministic packing.
- Set usage is membership-only or converted through explicit sorting before output.
- No wall-clock input enters assembly decisions.
- Same inputs produce the same envelope and hash.
- Narration cannot mutate canonical state, and narration failure returns the committed outcome with `narration: null`.
- Resolution commits before narration begins.
- The determinism exception is the incomplete content-bundle/provenance binding in EQ-R2-09.

## Recommended repair order

1. Enforce engine-owned addressability and hidden-entity visibility.
2. Introduce a public/narrator-safe outcome projection.
3. Bind command IDs to canonical intents.
4. Cap structured inputs and add rate, concurrency, and spend controls.
5. Add runtime narration validation with deterministic fallback.
6. Persist narration and bind it to a versioned full-content bundle.
7. Harden invite and schema allocation.

*Review elapsed: approximately 24 minutes.*