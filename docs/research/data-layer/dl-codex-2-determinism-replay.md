# Everquill Determinism, Replay, and Schema-Evolution Policy

## Executive decision

Everquill should not treat “replay” as “run today’s engine against yesterday’s commands.”

The canonical event log must contain the resolved facts—including dice, rule inputs, modifier ledger, outcome, and exact state effects—so historical outcomes remain interpretable without executing new engine code. Engine determinism is required when producing or independently verifying an outcome; it is not required to explain an already committed outcome or rebuild projections from committed facts.

The governing rule is:

> A seed helps reproduce a decision, but the event record proves what was committed.

This follows event-sourcing and ledger practice: immutable records are preserved, corrections are additional records, and consumers adapt old representations without rewriting history. [Microsoft’s event-sourcing guidance](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing) explicitly recommends versioned immutable events, chained upcasters, compensating events, and snapshots; [TigerBeetle](https://docs.tigerbeetle.com/coding/recipes/correcting-transfers/) similarly handles errors by adding correcting transfers rather than modifying the originals.

## 1. Non-negotiable invariants

1. **Committed events are never updated or deleted.** Database permissions must deny `UPDATE` and `DELETE` on canonical tables. Corrections are appended events.

2. **A committed outcome is self-describing.** It must not require current combat rules, current content, an LLM call, or regeneration of random numbers to explain what happened.

3. **Every resolution names its exact environment:** `ruleset_id`, engine artifact digest, content-manifest digest, RNG algorithm version, and event-schema versions.

4. **Randomness is addressed, not consumed.** No global mutable RNG stream and no sequential per-character or per-scene stream may determine canonical outcomes.

5. **Retries are idempotent.** The same command or action ID can be submitted repeatedly but can produce at most one canonical resolution.

6. **Schema migration never changes historical meaning.** Upcasters may change representation, not reinterpret a valid old outcome under new rules.

7. **Narration is not canon.** Parser output, adjudicator rulings, and engine results are recorded; prose can be regenerated without changing the world.

8. **Unknown historical data stays unknown.** An upcaster must emit `not_recorded` rather than inventing a modern default.

## 2. Seeded RNG stream design

### 2.1 Do not use sequential streams

A single `random.Random(seed)` instance—or one mutable instance per character or scene—will diverge as soon as a developer adds, removes, or reorders a roll site. Python also warns that most `random` algorithms and seeding functions may change across Python versions. [Python’s reproducibility notes](https://docs.python.org/3.12/library/random.html#notes-on-reproducibility) guarantee only a narrower core sequence, not every helper method.

Use a stateless, keyed, addressable design instead. Counter-based RNGs establish the relevant prior art: any sample can be obtained independently without advancing through earlier samples. [Random123](https://random123.com/) and [JAX’s PRNG design](https://docs.jax.dev/en/latest/jep/263-prng.html) show how keyed splitting removes ordering dependencies between unrelated random calls.

### 2.2 Recommended construction

Create one cryptographically random secret root per player world or campaign. Store it encrypted server-side and append its commitment:

```text
WorldRngCommitted {
    rng_algorithm: "everquill-hmac-sha256-v1",
    root_commitment: SHA256(root_secret),
}
```

Derive epoch keys for bounded namespaces:

```text
epoch_key = HMAC-SHA256(
    root_secret,
    canonical("everquill/epoch/v1", world_id, epoch_kind, epoch_id)
)
```

Derive each random sample independently:

```text
sample = HMAC-SHA256(
    epoch_key,
    canonical(
        "everquill/sample/v1",
        rng_domain,
        decision_id,
        roll_site_id,
        roll_index,
        die_index
    )
)
```

HMAC is a standardized keyed-hash construction defined by [RFC 2104](https://www.rfc-editor.org/rfc/rfc2104). Canonical inputs should use [RFC 8785 canonical JSON](https://www.rfc-editor.org/rfc/rfc8785) or another frozen, byte-exact encoding.

For each d6:

1. Read a fixed-width unsigned integer from the digest.
2. Use rejection sampling so the mapping to `1..6` is unbiased.
3. Derive die 0 and die 1 separately.
4. Sum them for 2d6.

All mechanics should use integers or explicitly specified fixed-point arithmetic. Floats, unordered set iteration, wall-clock time, process-local hashes, locale, and platform-dependent serialization are forbidden in canonical resolution.

### 2.3 Namespace policy

Per-character and per-scene keys are useful **namespaces**, but never mutable streams:

- Character-only checks: namespace by `character_id`.
- Scene-local checks: namespace by immutable `scene_epoch_id`.
- Shared combat or social actions: namespace by `decision_id`, not by the initiating character.
- World generation: namespace by stable `region_id`, `location_id`, or `entity_id`.
- Timed jobs: namespace by `timer_id`.
- Loot tables: namespace by the committed encounter or container ID.

A new roll site receives a new semantic label such as `combat.attack.check` or `rumor.distortion.qualifier`. It cannot shift any existing sample because no sample depends on call count.

`roll_site_id` is a schema identifier, not a function name, source line, or stack trace. Renaming code must not rename the site unless designers intentionally create a new random decision.

### 2.4 What every roll records

Each canonical `RandomSampled` record should include:

```text
rng_algorithm
rng_epoch_id
rng_domain
decision_id
roll_site_id
roll_index
dice: [{sides: 6, value: 2}, {sides: 6, value: 5}]
total: 7
sample_commitment or digest
```

The committed dice values are authoritative. The derivation evidence supports verification but is not required to rebuild state.

For optional player-verifiable fairness, append a hash commitment to a scene key when the scene opens and reveal that key only after the scene epoch is permanently closed. Re-entering the location creates a new epoch. Do not reveal a key while it could predict future actions.

### 2.5 Saverscum prevention

- Allocate and persist a unique `command_id` before submission.
- Once the player confirms `Proceed?`, append `ActionCommitted` with its `decision_id`, parsed intent, assessed risk, state revision, and RNG namespace.
- The same `command_id` must always return the existing action or outcome.
- A disconnect does not cancel a committed action.
- If resolution is asynchronous, the pending action blocks conflicting changes to its consistency set and resumes using the same IDs.
- No result is shown before its outcome and effects are durably committed.
- A server restart or deploy resumes the pending decision; it does not allocate another roll.
- Player-visible seeds remain secret until their epoch closes, preventing outcome hunting by enumerating action IDs.

This mirrors financial idempotency practice: unique IDs make retries safe and immutable records prevent rollback. [TigerBeetle’s reliable-submission model](https://docs.tigerbeetle.com/coding/reliable-transaction-submission/) uses persistent IDs to ensure an operation is processed at most once.

## 3. Canonical event contract

### 3.1 Envelope

Every event should have a stable envelope independent of payload version:

```text
event_id
world_id
world_sequence
stream_id
stream_sequence
event_type
payload_version
schema_id
recorded_at
world_time
command_id
decision_id
causation_event_id
correlation_id
ruleset_id
engine_artifact_sha256
content_manifest_sha256
payload
previous_event_hash
event_hash
```

Use a transactionally allocated `world_sequence` to order cross-entity effects. Each stream also has a unique `(stream_id, stream_sequence)` constraint. Appends use an expected stream/world revision so concurrent writers cannot silently overwrite one another.

A hash chain provides tamper evidence, not by itself tamper prevention. For stronger assurance, periodically anchor a world-segment hash or Merkle root in an independently retained backup.

### 3.2 Resolution receipt

An action’s canonical commit should contain or reference:

- Raw player utterance and committed parsed intent.
- Chosen target and action IDs.
- Pre-resolution state hash and relevant fact/event references.
- Risk label and plausibility tier shown before confirmation.
- Rule checks and component requirements.
- Complete internal modifier ledger, with a visibility tag on each entry.
- Player-visible modifier ledger.
- Every random sample.
- Threshold and result-band calculation.
- Outcome classification.
- Exact domain effects: injuries, resources, clocks, claims, deeds, state transitions.
- Before/after values or unambiguous deltas for changed quantities.
- Causal links between the action, intermediate injuries, and any death.
- Post-resolution state hash.

Do not store only “attack succeeded” and expect future code to reconstruct damage. Conversely, do not store only an opaque state diff; preserve the domain meaning—such as `InjuryInflicted`—alongside exact effects.

The action, outcome, effects, deed, and possible death should be appended as one atomic commit batch. If the parser or adjudicator is an LLM, its accepted structured output is an input fact in this batch. Replaying must never call that LLM again.

### 3.3 Player and privileged audit views

The same receipt supports two renderers:

- **Privileged audit:** complete rule inputs and true modifiers.
- **Player audit:** dice, known modifiers, risk, causal chain, and outcome-relevant concealed-factor labels without serializing true-sheet values.

A player-facing explanation might say:

> You attempted a DESPERATE strike, rolled 5 on 2d6, and had +1 from your known spear training. The wyvern’s resistance was stronger than your character knew. The failed strike exposed your existing chest wound; the subsequent 8-point injury crossed the fatal threshold.

This answers “why did I die?” without exposing unrelated true-sheet information.

## 4. Three different meanings of replay

The word `replay` should never appear unqualified in code or operational procedures.

| Operation | Purpose | Executes historical engine logic? | Determinism required |
|---|---|---:|---|
| **Audit replay** | Explain what happened and why | No | Complete event evidence; deterministic renderer desirable |
| **Projection rebuild** | Recreate stats, known sheets, rumors, manifests, indexes | No command handlers, RNG, or LLMs | Deterministic, ordered, idempotent projectors |
| **Verification re-simulation** | Check that an old engine would produce the recorded outcome | Yes, using the exact archived artifact | Full engine, RNG, content, and runtime determinism |

### Audit replay

Reads raw events, upcasts their representation, follows causal IDs, and renders the recorded decision receipt. It must continue working even if the old engine artifact has been lost.

### Projection rebuild

Folds ordered, upcasted domain facts into a read model. It does not reconsider whether the original decision was correct. A new projection may expose new views of old facts, but it cannot alter canon.

### Verification re-simulation

Uses the recorded pre-state, intent, RNG address, ruleset, content manifest, Python/runtime image, and archived engine wheel. Its result is compared with the canonical event batch.

A mismatch raises an integrity alert; it never rewrites the log.

RTS lockstep provides the warning here: deterministic peers remain synchronized only when they process the same ordered inputs under the same simulation. Factorio treats divergent game state as a desync and uses ordered input actions and state comparisons to diagnose it. [Factorio’s lockstep description](https://www.factorio.com/blog/post/fff-302) is useful prior art, but Everquill’s continuously changing engine makes permanent reliance on old re-simulation unsafe.

Likewise, a roguelike seed run is reproducible only in conjunction with the same game version, settings, RNG algorithm, and action sequence. A seed alone is not an audit record.

## 5. Event schema evolution

### 5.1 Version every persisted payload

Maintain immutable schemas such as:

```text
ActionCommitted.v1
OutcomeResolved.v1
OutcomeResolved.v2
DeathSealed.v1
```

Any persisted shape change receives a new payload version. Never edit an old schema file in place. Keep the event type stable when meaning is stable; introduce a new event type when meaning changes.

Every supported historical version must have:

- Its original schema.
- A deserializer.
- An upcast path or explicit current handler.
- At least one golden fixture.
- An audit rendering policy.

Industry research identifies versioned events, weak/tolerant schemas, upcasting, in-place transformation, and copy-transform as the major evolution strategies. In-place mutation is the wrong default for Everquill because it damages the audit record. [The empirical study of 19 event-sourced systems](https://dspace.library.uu.nl/handle/1874/412217) documents these strategies and their trade-offs.

### 5.2 Upcaster chains

Use small, ordered, pure transformations:

```text
OutcomeResolved.v1 -> v2 -> v3 -> CurrentOutcomeResolved
```

Each upcaster must be:

- Deterministic and total for every valid input of its source version.
- Free of database, network, clock, configuration, RNG, and LLM access.
- Non-mutating.
- Independently tested.
- Explicit about provenance when producing multiple virtual events.

The raw event remains unchanged; the transformed event exists only in the read pipeline. This is the non-destructive chained model described by [Axon’s event-versioning guidance](https://docs.axoniq.io/axon-framework-reference/main/events/event-versioning/).

Rules for missing information:

- If a new field is mechanically derivable from old fields, derive it.
- If it was not recorded, emit `not_recorded`.
- Never insert a current gameplay default that could change historical meaning.
- If transformation needs other events, prefer a projection-level join.
- If genuinely new canonical information is required, append a migration or correction event rather than hiding a database lookup inside an upcaster.

Semantic changes do not belong in upcasters. A balance patch must not transform “fatal under ruleset 17” into “survivable under ruleset 24.”

### 5.3 Writer/reader deployment order

For a new event version:

1. Deploy readers, schemas, upcasters, and projection support first.
2. Verify all historical fixtures.
3. Enable the new writer version.
4. Observe mixed-version rebuilds.
5. Retire old writers only after pending actions and timers are accounted for.

Long-running timers record the ruleset selected at `TimerStarted`. Their completion normally honors that ruleset unless an explicit migration event changes the promise.

## 6. Snapshots and compatibility barriers

Standard event-sourcing snapshots are disposable performance caches; they do not replace events. [Microsoft](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing#problems-and-considerations) and [Axon](https://docs.axoniq.io/axon-framework-reference/development/snapshotting/) both make this distinction.

Everquill should use two separate mechanisms.

### 6.1 Projection checkpoints

These are disposable caches containing:

```text
projection_name
projection_version
last_world_sequence
source_event_hash
serialized_projection
projection_hash
```

Create them per processing batch or when rebuild/load metrics justify it. Deleting them must be safe because the projection can rebuild from events.

### 6.2 Canonical state-handoff checkpoints

To prevent a new engine from having to execute old decision logic, add an immutable compatibility barrier:

```text
StateCheckpointCommitted {
    state_schema_version,
    world_sequence,
    source_event_hash,
    ruleset_id,
    content_manifest_sha256,
    canonical_state_blob_sha256,
    canonical_state_blob_location,
}
```

The referenced blob contains the complete canonical true and known state needed by the next engine. It is content-addressed, immutable, and backed up with the event log. The checkpoint event itself remains in the append-only stream.

This is not permission to prune preceding events. It is a durable handoff: the new engine loads the checkpoint through a versioned state adapter and processes only later facts. Historical audit still reads the original events.

### 6.3 Snapshot schedule

Initial policy:

- Mandatory immediately after every `DeathSealed` and heir handoff.
- Mandatory before activating a new ruleset or canonical state-schema version.
- Mandatory before a migration that changes how active state is represented.
- Create an operational state checkpoint after 500 events since the last checkpoint.
- Also checkpoint when aggregate rehydration exceeds 50 ms at p95.
- At scene close, checkpoint if at least 100 canonical events occurred in the scene.
- Projection consumers checkpoint their offsets every successful batch.

Tune the numeric thresholds from production measurements, but retain the semantic triggers.

### 6.4 Release barrier procedure

Before a state-incompatible engine release:

1. Stop accepting new action confirmations.
2. Let committed resolutions finish.
3. Have the old release write checkpoints for every active world and character.
4. Verify each checkpoint’s state and source-event hash.
5. Shadow-load it with the new release.
6. Compare canonical state hashes.
7. Activate the new ruleset only after equality is proven.
8. Resume actions with the new `ruleset_id`.

This makes engine upgrades explicit state transitions rather than accidental reinterpretations.

## 7. Sealed deaths and migration

`DeathSealed` is gameplay-final and append-only. Schema migration does not unseal it.

A sealed death must include:

- Character and world IDs.
- Final state hash.
- Fatal outcome event ID.
- Ordered causal chain.
- Fatal injury/resource transition.
- Dice and modifier receipt references.
- Ruleset and content versions.
- World time and location.
- Player-audit visibility data.
- Checkpoint reference.

Policies:

1. **Representation migrations:** Upcast `DeathSealed.v1` to the current read model while preserving its old semantics.

2. **Balance changes:** Never revise old deaths merely because current balance would produce another result.

3. **Missing old fields:** Mark them `not_recorded`; do not fabricate a modern explanation.

4. **Actual integrity errors:** Append `CanonCorrectionIssued` or `DeathRecordCorrected` referencing the death, with operator, reason, evidence, affected fields, and authorization. Preserve both records.

5. **Administrative reinstatement:** If a death resulted from corruption, duplicate execution, or a violated invariant, restoration must be an explicit correction event—not deletion and not an in-world resurrection.

6. **In-world resurrection:** Remains ordinary gameplay canon governed by sealed-feat laws. It does not invalidate the historical death.

The player audit must display corrections as part of the history: “The original record said X; correction Y was issued because Z.”

## 8. Determinism regression harness

### 8.1 Golden fixture bundle

Each historically important scenario should be stored as a fixture bundle containing:

```text
raw_events.jsonl
expected_upcasted_events.jsonl
expected_projection_hashes.json
expected_audit.json
pre_state.json
committed_intent.json
expected_outcome_events.jsonl
fixture_manifest.json
```

The manifest pins:

```text
ruleset_id
engine_artifact_sha256
content_manifest_sha256
rng_algorithm
Python/runtime version
schema bundle version
```

Required fixture families:

- Ordinary 2d6 success and failure.
- Doubles and boundary totals.
- Impossible/sealed checks.
- Hidden modifier with player-safe audit.
- Injury chain ending in death.
- Timer completion across a deploy.
- Adjudicator precedent.
- Mixed old and new payload versions.
- Correction of a sealed record.
- Snapshot recovery and full rebuild.
- Duplicate command and crash recovery.

### 8.2 CI gates

Every change runs:

1. **RNG known-answer vectors:** fixed test secrets and roll addresses must produce exact dice forever.

2. **Repeated resolution:** same state, intent, rule/content versions, and RNG addresses must produce byte-identical canonical events.

3. **Historical interpretation:** every raw historical fixture must still upcast, rebuild projections, and render an audit under current readers.

4. **Pinned verification:** representative fixtures run under their archived engine artifact and reproduce their recorded event bundle.

5. **Snapshot equivalence:** rebuild from event zero and rebuild from every checkpoint must yield the same canonical state hash.

6. **Roll-site perturbation:** inserting an unrelated new roll site must not change existing roll vectors.

7. **Evaluation-order perturbation:** independently resolvable computations run in different orders and still produce identical results.

8. **Idempotency:** repeated submission, lost response, worker restart, and crash-after-commit all produce one outcome.

9. **Hash-seed matrix:** run with different `PYTHONHASHSEED` values to expose unordered iteration.

10. **Cross-runtime job:** run the production container plus another supported Python 3.12 patch image.

11. **First-divergence trace:** hash canonical state after every event and report the first mismatching event, borrowing the desync-bisection technique used by deterministic lockstep games.

12. **Nondeterminism guard:** fail CI if canonical engine modules import or call unauthorized randomness, wall clocks, network clients, LLMs, locale-sensitive operations, or unsorted collection traversal.

### 8.3 Golden-update policy

- Old fixtures are append-only.
- A deliberate mechanics change creates a new `ruleset_id` and new expected-outcome fixture.
- Existing historical expected outcomes are not regenerated with current code.
- Changing an old fixture requires a documented test-data correction and review.
- Upcaster or audit-output changes must show a semantic diff, not merely replace golden files.
- CI must retain at least one fixture for every historical payload and RNG version ever written to production.

## 9. Recommended implementation order

1. Freeze `everquill-hmac-sha256-v1` and publish known-answer vectors.
2. Define the stable event envelope and immutable schema registry.
3. Implement command idempotency and expected-version appends.
4. Define `ActionCommitted`, `RandomSampled`, `OutcomeResolved`, state-effect events, and `DeathSealed`.
5. Build the player and privileged audit renderers before lethal combat ships.
6. Add pure upcaster registration and mixed-version fixtures.
7. Add state hashes after every canonical commit.
8. Add projection rebuild and snapshot-equivalence tests.
9. Add canonical state-handoff checkpoints before the first incompatible engine release.
10. Archive every production engine wheel, container digest, ruleset, content manifest, and schema bundle.

## Sources

- [JAX PRNG Design — counter-based PRNGs, explicit key splitting, and avoidance of sequencing dependencies](https://docs.jax.dev/en/latest/jep/263-prng.html)
- [Random123 — stateless counter-based random-number generation](https://random123.com/)
- [Python 3.12 `random` reproducibility notes](https://docs.python.org/3.12/library/random.html#notes-on-reproducibility)
- [RFC 2104 — HMAC keyed hashing](https://www.rfc-editor.org/rfc/rfc2104)
- [RFC 8785 — JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [Factorio Friday Facts #302 — deterministic lockstep, ordered inputs, and desynchronization](https://www.factorio.com/blog/post/fff-302)
- [Microsoft Azure Architecture Center — Event Sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [Axon Framework — Event versioning and upcaster chains](https://docs.axoniq.io/axon-framework-reference/main/events/event-versioning/)
- [Axon Framework — Snapshotting](https://docs.axoniq.io/axon-framework-reference/development/snapshotting/)
- [Overeem et al. — empirical study of event-sourced schema-evolution strategies](https://dspace.library.uu.nl/handle/1874/412217)
- [TigerBeetle — reliable, idempotent transaction submission](https://docs.tigerbeetle.com/coding/reliable-transaction-submission/)
- [TigerBeetle — immutable correcting transfers](https://docs.tigerbeetle.com/coding/recipes/correcting-transfers/)