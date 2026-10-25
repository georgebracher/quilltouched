# Everquill Event Taxonomy (A0.2)

Status: Sprint 0 draft — **for Team F review before schema work (F0.4)**.
Code counterpart: `everquill_engine/events.py` (`EventType` enum + `Event` envelope).
Binding context: `docs/roadmap.md` §4 "State architecture".

## Ground rules

- **Append-only.** The event log is the single source of truth. Events are never
  updated or deleted; a correction is a *new* event. Everything else — true/known
  sheets, the Chronicle, Inquiry claims, rumor state, scene manifests, timers view,
  titles — is a projection, rebuildable from the log. A bad projection is a bug,
  never a loss.
- **Payloads are versioned.** Every event carries `payload_version` (1-based, per
  event type). When a payload schema evolves, readers **upcast** old versions at
  read/projection time; stored events are never rewritten. Writers always emit the
  current version. This is the future-proofing contract: no migration ever touches
  a written event.
- **Vocabulary is append-only too.** New event types may be added in later sprints;
  existing names are never renamed or repurposed.
- **`death_sealed` is written BEFORE narration ever runs.** The engine commits the
  full mechanical death record first; the narrator is then bound to it (no invented
  final words, no plot armor, no prose-first deaths). If narration fails or drifts,
  the death already happened, exactly as rolled.

## The envelope

Every event is wrapped in the same envelope (frozen dataclass `Event`):

| Field | Type | Meaning |
|---|---|---|
| `event_id` | str | Globally unique id, assigned at append time by persistence (opaque to the engine). |
| `stream_id` | str | Aggregate stream, e.g. `character:<id>`, `region:<id>`, `timer:<id>`, `world`. |
| `stream_version` | int | 1-based, monotonic, **gap-free per stream**. Appends assert expected-next (optimistic concurrency, enforced by Team F's store). |
| `world_time` | int | World-clock timestamp in canonical ticks (unit fixed with the Sprint-1 world clock; opaque monotonic int until then). |
| `event_type` | enum | One of the 13 types below (storage value = snake_case string). |
| `payload_version` | int | 1-based schema version of the payload *for this event type*. |
| `payload` | mapping | JSON-safe body; shapes sketched below. Frozen at construction. |

Payload sketches below are **sketches** — field names indicative, not final. Final
JSON contracts are C0.1 (with Team A); the Postgres schema is F0.4. What is fixed
here: the 13 type names, their purpose, and which projections consume them.

---

## The core loop

### `action_declared`
- **Purpose:** the player committed an action — the moment after the commit beat
  (inline ghost-echo for trivial/routine; `<<Proceed?>>` dialog for dire-and-up,
  sealed, or irreversible). This is the audit anchor for "what did the player
  actually ask for": raw text preserved verbatim, before any parsing opinion.
- **Payload sketch:** `{character_id, raw_text, input_mode: typed|voice|tap_seeded,
  scene_id, commit_beat: inline|dialog, declared_at_world_time}`
- **Consumed by:** Chronicle (the player's own record of what was attempted),
  replay/audit projections, parser eval harness (Team C golden transcripts).

### `intent_parsed`
- **Purpose:** the structured intent the parser produced for a declared action,
  recorded so every resolution is re-derivable and every misparse is auditable.
  The parser (LLM) *proposes*; recording its output as an event is what lets the
  engine's verdict be checked against what was parsed, forever.
- **Payload sketch:** `{action_event_id, action_type, target_entity_id, approach,
  stat, dialogue?, plausibility_tier_claimed, parser_model, contract_version}`
- **Consumed by:** replay/audit, parser eval + drift monitoring (C), the resolver
  path (reads it as input downstream — Sprint 1).

### `outcome_resolved`
- **Purpose:** the engine's verdict — the only place success/failure is ever
  decided. Carries band, dice, outcome tier, and the resulting state deltas.
  Post-roll, dice and known modifiers are shown in full: every death must be
  auditable without trusting prose.
- **Payload sketch:** `{action_event_id, intent_event_id, band, risk_label,
  roll: {stream, index, die_one, die_two, total, modifiers: [...]},
  outcome_tier: strong_hit|hit_with_complication|miss, hopeless_flavor?,
  deltas: [{entity_id, field, from, to}, ...]}`
- **Consumed by:** true-sheet projections (HP, position, inventory, flags),
  Chronicle (post-roll dice of record), scene manifest, narrator context assembly
  (outcome tier + known slices only — never true stats), deed derivation.

---

## Knowledge (Chronicle / Inquiry)

### `claim_written`
- **Purpose:** a KNOWN-sheet entry was recorded — the claim schema of roadmap §3.3
  (subject · claim · value/range · source · observer · method · world timestamp ·
  scope · confidence · corroboration · inheritance status). Claims may be wrong;
  wrongness is causal, never random. The event records the claim *as acquired*,
  provenance and all.
- **Payload sketch:** `{claim_id, subject_entity_id, field, value_or_range,
  source, observer_id, method, scope, confidence, acquired_at_world_time,
  error_mechanism?: null|contamination|disguise|outdated|... , inherited_from?}`
- **Consumed by:** Inquiry projection (fallible dossiers), Chronicle projection
  (when the claim is a fact of record — e.g. post-roll dice, coin counts),
  context assembler (top-K salient claims into narrator prompts), Codex UI cards,
  action-space gating (techniques/weak points exist in your action space only if
  a claim says so).

### `claim_contradicted`
- **Purpose:** new evidence conflicts with an existing claim. Neither claim is
  edited or deleted — the contradiction is itself canon. The Codex shows the badge;
  correlation stays the player's joy (bookkeeping yes, suggestions never).
- **Payload sketch:** `{claim_id, contradicting_claim_id, detected_by:
  observation|research|testimony, note?}`
- **Consumed by:** Inquiry projection (contradiction badges, confidence =
  evidence-consistency recompute), Codex UI, context assembler (contradicted
  claims flagged in prompt slices).

---

## Deeds, titles, world memory

### `deed_recorded`
- **Purpose:** a significant outcome became a witnessed deed — the world's memory
  unit and the substrate of rumor propagation and worldgen. Includes deaths and
  impossible-tier attempts (the mad man who yelled at clouds is remembered).
- **Payload sketch:** `{deed_id, actor_entity_id, outcome_event_id?, description_key,
  location_id, witness_ids: [...], notoriety_score, sensationalism}`
- **Consumed by:** deed-log projection, lazy rumor propagation (computed on demand
  per region-epoch from deeds + propagation rules — never eager fan-out), title
  threshold checks, structural worldgen inputs (Sprint 5), memorials/epitaphs.

### `title_minted`
- **Purpose:** deed thresholds minted a System title (`[Title Earned: Ratcatcher
  of Dunmere]`) — the XP replacement. Metaphysical recognition, distinct from
  guild rank certification by design; the two may disagree.
- **Payload sketch:** `{character_id, title_key, display_name, minted_from_deed_ids:
  [...], witnessed: bool}`
- **Consumed by:** character known-sheet projection (titles are public knowledge
  once rumored), rumor propagation (titles travel), narrator context (earned
  framing only — no awe the deed log didn't earn), heir/legacy surname weight.

---

## World clock

### `timer_started`
- **Purpose:** a timed block began — training, research, travel, crafting,
  recovery, structural worldgen, exam schedules, pressure fronts. Timers are
  exclusive occupation where the design says so (training), and they are the
  cost ceiling: duration previewed before commit, results generated behind the
  wait (Batch API).
- **Payload sketch:** `{timer_id, owner_entity_id, kind: training|research|travel|
  craft|recover|worldgen|exam|front, subject_ref, starts_at_world_time,
  due_at_world_time, checkpoint_interval?, location_id, exclusive: bool}`
- **Consumed by:** timer-table projection (the due-jobs worker's queue — Team F),
  world-clock UI, skip-preview computation (which known deadlines move),
  training-exposure checks (location = exposure).

### `timer_completed`
- **Purpose:** a timer ran to term; results land. Completion is automatic and
  offline — nothing decays, nothing needs a claim tap. Whether waited or skipped,
  the world-time cost is identical; a skip only collapses the real-world wait,
  so completion carries no odds/loot difference by construction.
- **Payload sketch:** `{timer_id, completed_at_world_time, result_ref?
  (e.g. batch-generated findings id), gains: [...], skipped: bool}`
- **Consumed by:** timer-table projection (job cleared), character sheet
  projections (training gains, recovery), Inquiry (research findings →
  `claim_written` follow-ups), re-entry "findings await" UX, cost telemetry.

### `timer_aborted`
- **Purpose:** a timer was interrupted — player abort or world event breaking in.
  Committed but interruptible: pro-rated gains to the last checkpoint are kept
  and recorded here. An abort is not a refund and not a failure; it's a fact.
- **Payload sketch:** `{timer_id, aborted_at_world_time, cause: player|world_event,
  interrupting_event_id?, prorated_gains: [...], checkpoints_completed}`
- **Consumed by:** timer-table projection, character sheet projections (partial
  gains), narrator context (the interruption is scene material).

---

## Death & legacy

### `death_sealed`
- **Purpose:** a character died. The engine writes the **full death record before
  narration ever runs** — cause, killing roll reference, location, witnesses,
  the state of record at death. Most deaths are abrupt; no auto-eloquence. The
  narrator binds to this record; memorials are concrete facts, never generated
  praise. Savescumming is structurally dead because this event is appended first.
- **Payload sketch:** `{character_id, cause_outcome_event_id, location_id,
  world_time_of_death, witnesses: [...], wounds_of_record: [...],
  possessions_snapshot_ref, unfinished: [...]}`
- **Consumed by:** entity persistence (corpse, grave, stash, enemies — the PC
  remains a world entity), death card UI (factual: Mourn / See what the world
  did / Choose heir), heir flow phases 2–4, deed derivation (a death is a deed),
  audit ("≥90% of testers can explain the mechanical cause of their death").

### `heir_created`
- **Purpose:** an heir entered the same world through an event, not a menu.
  Records which candidate was chosen (kin/apprentice/finder-stranger), the
  nonbinding stance toward the dead, and the brutally thin inheritance manifest.
  Declined candidates persist as NPCs (their persistence is entity state, not
  a rewind — nothing about the dead is edited).
- **Payload sketch:** `{heir_character_id, predecessor_character_id, relation:
  kin|apprentice|stranger, stance: complete|avenge|understand|protect|clear|
  reject|exploit, inherited: [{item_or_claim_ref, ...}], entry_event_ref,
  world_pulse_elapsed_ticks}`
- **Consumed by:** character creation projection (heir starts at the world's
  narrative altitude), Inquiry (inherited journal claims arrive with
  `inherited_from` provenance — the heir inherits the claim, not the truth),
  guild projections (rank died with the character; F under a famous surname),
  Quill-touched continuity (soul-bound Codex-sight).

---

## Canon growth

### `entity_committed`
- **Purpose:** a generated entity (furniture inline from the narrator, or
  structural from offline worldgen) passed validation and was committed to canon
  **forever**. The narrator can never improvise a duke; this event is the only
  gate by which generated things become real. Sprite generation keys off this
  commit (gen-once, cached by entity id).
- **Payload sketch:** `{entity_id, entity_class: npc|location|item|faction|...,
  origin: furniture|structural, template_ref, true_sheet_ref (server-side only —
  NEVER serialized to client/narrator paths), name, location_id,
  generated_from: {deed_ids?, lore_refs?}}`
- **Consumed by:** entity registry / true-sheet store (server-side), scene
  manifest (perceived subset only), sprite gen-at-commit worker (Team E),
  common-sense tier seeding (category knowledge), worldgen dedupe.

---

## Stream conventions (proposal for F0.4)

- `character:<id>` — actions, intents, outcomes, claims *observed by* that
  character, timers they own, their death and titles.
- `region:<id>` — deeds located there, rumor-epoch anchors, structural commits.
- `world` — world-clock milestones, cross-region pressure fronts.
- `timer:<id>` — alternative: timers as their own streams if F prefers a
  cleaner due-jobs index; decide in F0.4, not here.

Open for F review: exact stream partitioning (above), event_id format (ULID
recommended for sortability), and whether `outcome_resolved.deltas` also fan out
as per-entity mini-events or stay embedded (embedded recommended — projections
can index into payloads; the log stays the truth either way).

---

## Sprint 1 additions (A1)

Vocabulary is append-only; these types joined the taxonomy with the
Sprint-1 event store (`everquill_engine/events.py`, migrations 0001–0003).
Stored envelope = the `event` table of `migrations/0001_event_store.sql`
(synthesis §2.1 shape: bigint id, xid8 transaction_id, stream_id,
stream_version UNIQUE-per-stream, world_time in world MINUTES,
event_type, nullable location_id, UNIQUE command_id, rng jsonb, payload
jsonb, payload_version, meta jsonb, recorded_at).

### `world_created`
- **Purpose:** genesis — commits the world seed (server-side only; the
  log never reaches the client) and anchors world_time 0. One per world.
- **Payload v1:** `{seed, content_source}`
- **Consumed by:** world_state projection (seed, clock, dice counters).

### `character_created`
- **Purpose:** chargen resolved — the six aptitude rolls (locked
  vocabulary) drawn on stream `("chargen", character_id)`, plus derived
  hp/coin, stored as facts so no fold ever recomputes them.
- **Payload v1:** `{character_id, name, origin, aptitudes, rolls, hp,
  hp_max, coin, location_id, region}`
- **Consumed by:** character_sheet projection (TRUE sheet — server-side
  only), scene_manifest.

### `time_advanced`
- **Purpose:** the world clock moved without an action (manual sweeper
  `clock-advance --minutes N`). Events only on state change — no
  heartbeat spam; the sweep itself emits nothing when nothing fires.
- **Payload v1:** `{minutes}`
- **Consumed by:** world_state projection (clock high-water).

### Sprint-1 conventions locked by the store
- Multi-event commands: first event stores the raw `command_id`,
  siblings `'<command_id>#<n>'` — idempotency probes the raw id; a
  duplicate command is absorbed whole (no partial replays).
- Same-command references: payloads may carry `{"$event_ref": i}`
  (see `everquill_engine.events.event_ref`) which the store replaces
  with the DB id of event *i* of the same command at insert time
  (used by claim provenance + timer created_event_id).
- Fan-out rule: `outcome_resolved.state_deltas` is the complete audit
  record, and its intel/deed/timer_started deltas are ALSO emitted as
  `claim_written`/`deed_recorded`/`timer_started` events in the same
  command. Folds read ONLY the dedicated events for those tables
  (one writer per row — see `everquill_engine/folds.py` docstring).
- Streams in use: `world` (genesis, entity commits, clock),
  `character:<id>` (chargen, intents, outcomes, claims, timers),
  `region:<region>` (deeds).

## Addendum (Sprint 1 wave 2)

- `content_manifest` (MEDIUM-7): genesis commits sha256 of the world YAML + loader version; world open hard-refuses on mismatch (EVERQUILL_ALLOW_CONTENT_DRIFT=1 dev override).
- `entity_state` projection (CRITICAL-2): server-only mutable state (hp, conditions, position) for all damageable non-PC entities, seeded at genesis, folded Tier-1; resolver difficulty reads authored sheet x current hp. Deltas targeting unseeded entities raise.
- Command identity (MEDIUM-2): events store (command_id, event_ordinal) with UNIQUE pair; the hash-suffix scheme is dead; command ids reject the # character.
- stat_hint is telemetry-only (CRITICAL-1): resolution uses engine-owned DEFAULT_STAT_FOR_ACTION exclusively; outcome meta records {stat_selected, stat_hint, stat_hint_mismatch}.

## Addendum (Sprint 2 wave 1 — A1)

- **RNG streams per roll site (MEDIUM-4):** new events draw from
  registered semantic streams (`rng_registry.py`): outcome rolls on
  `["character:<id>", "action:<type>"]`, HOPELESS flavor on
  `["character:<id>", "hopeless_flavor"]`; chargen/timer-fire streams
  unchanged. Historical events keep their stored `["character:<id>",
  "action"]` records and fold forever (replay never re-rolls; counters
  key per stream). Migration 0006 adds `UNIQUE ((rng->'stream'),
  (rng->'index')) WHERE rng IS NOT NULL` — a reused draw is a loud
  constraint violation.
- **Golden corpus extension (documented reasons):** events 13–14 freeze
  the two new rng stream shapes; event 15 freezes the trivial
  `[Already dispatched.]` outcome (zero deltas, no dice). Event 5 keeps
  the retired pooled stream on purpose — old logs must fold forever.
- **`pending_confirmation` (migration 0006) is NOT canon:** the
  two-phase commit beat stores assessed-but-unconfirmed intents there
  (verbatim). No event exists until confirm; an expired/abandoned beat
  leaves zero trace in the log. The table is operational (like the
  timer queue), not a projection — rebuilds ignore it, `fresh_reset`
  clears it. Confirm appends the normal `intent_parsed` +
  `outcome_resolved` (+ fan-out) command under the ORIGINAL command_id.

## Addendum (Sprint 2 wave 3 — A2: claim v2, upcasters, event identity, crypto-shredding)

### New event types (append-only vocabulary growth)

Claim lifecycle transitions are EVENTS (synthesis §2.3) — the claim
table stays a rebuildable projection. All five states
(`asserted / corroborated / contested / superseded / retracted`) are
reachable only through the log:

- **`claim_written` v2** — the assertion. Payload:
  `{claim_id, believer_id, claim: {subject_entity_id, predicate,
  value_text, value_num, value_range, world_valid, claim_text, layer,
  source, observer, method, acquisition_method, source_agent_id,
  world_date, scope, confidence}, provenance_root_event_id,
  derived_from_claim_id, hop_count, journal_flag, strength}`.
  `predicate` comes from the CLOSED registry
  (`everquill_engine.claims.PREDICATES`); `strength` is the cached
  decayed evidence-weight sum, stamped at write time (a fresh claim =
  its founding link's undecayed base weight). The fold also creates the
  founding `claim_evidence` link. v1 payloads upcast: free text →
  `observed_statement`, `value_or_range` → `value_text`, `method` →
  `acquisition_method` via the shared mapping.
- **`claim_corroborated`** — an evidence link attached to an EXISTING
  claim (the write-time probe converts an identical re-assertion into
  this instead of a duplicate row). Payload: `{claim_id, believer_id,
  evidence: {event_id (null = this event's own id), root_event_id,
  acquisition_method, base_weight, world_time}, strength, status}` —
  strength and status are RESULTS, computed at write time and applied
  verbatim by the fold. Status flips to `corroborated` only when the
  links span ≥ 2 DISTINCT provenance roots (echo-chamber rule: one deed
  retold three times raises strength, never corroboration); a contested
  claim stays contested (evidence raises strength, not verdicts).
- **`claim_contested`** — `{claim_id, contested_by_claim_id}`. Both
  rows stay active; emitted BOTH WAYS by the write-time contradiction
  probe when neither side outweighs the other.
- **`claim_superseded`** — `{claim_id, superseded_by_claim_id,
  superseded_reason ∈ better_evidence | direct_observation |
  source_recanted | canon_sealed}`. Rows are never deleted.
- **`claim_retracted`** — `{claim_id, reason}`. Terminal; origin
  evidence itself invalidated (canon-sealing sweep — the sweep itself
  is a later sprint; the event + fold + `claims.py` rules ship now).
- **`narration_generated`** — prose canonized, BOUND to its outcome:
  `{character_id, outcome_event_id, outcome_event_ulid, prose,
  assembler_version, content_hash, model}`. Audit-only fold (no
  projection). Builder: `everquill_engine.events.narration_spec`;
  append as its own command (`narrate:<outcome_event_ulid>`) after the
  outcome's command commits. Closes Team F's decision-3 TODO.
- `claim_contradicted` (Sprint-0 name) remains DECLARED-NEVER-SHIPPED;
  the shipped contradiction grammar is `claim_contested`.

### Write-time claim lifecycle (store-owned)

`store._claim_lifecycle_pass` runs inside every append transaction:
one indexed probe per incoming claim on
`(believer_id, subject_entity_id, predicate)` (index `claim_active_key`)
against the preloaded claim image, then the deterministic revision rule
(`everquill_engine.claims.revise`): equal value → corroborate (the
claim_written spec is REPLACED by claim_corroborated); differing value
on an exclusive predicate → challenger inserts + contested/superseded
events (fresh direct observation wins strength ties); otherwise plain
insert. Cross-mind contradiction stays read-time (assembler, scene
scope); propagation-time revision rides the future rumor epochs.

### Payload versioning is now REAL (HIGH-3)

- `(event_type, payload_version)` upcaster registry:
  `everquill_engine/upcasters.py` — pure chained functions, NO engine
  imports (AST lint in tests/test_upcasters.py). Folds upcast every row
  before folding; stored events are never rewritten.
- Version history lives in the upcasters module docstring: current
  bumps are `claim_written` v2, `outcome_resolved` v2 (typed intel
  claims + required `transit_hint` on position deltas — v1 rows upcast
  to `"unknown"`), `intent_parsed` v2 (player text may be
  envelope-encrypted).
- Golden corpus covers every shipped PAIR
  (`upcasters.SHIPPED_PAYLOAD_VERSIONS`); a shipped pair without a
  fixture fails the build.
- `folds.PROJECTOR_VERSIONS` is persisted in `projection_checkpoint`
  (migration 0009). Every append verifies DB == code and refuses to mix
  fold generations; `rebuild_projections` restamps. A fold change
  without a bump is caught by the snapshot gate (tests/test_folds.py);
  regeneration is refused unless the changed projection's version was
  bumped in the same commit.
- Rebuilds are SHADOW rebuilds: fold the log into `<table>__shadow`
  copies, diff canonical dumps, atomically swap (rename), re-apply
  grants + timer FKs — never truncate-in-place over a live read model.

### Event identity (MEDIUM-6)

`event.event_ulid` (26-char Crockford) is THE stable external id —
`outcome_contract` exposes it alongside the internal bigint string.
Derived deterministically (48-bit world-time ms ‖ 80-bit md5 of
`stream_id:stream_version`) so identical replays produce identical
logs; UNIQUE-indexed. `stream_type` = the prefix of `stream_id`
(`world` / `character` / `region`), backfilled and stamped at insert.

### Crypto-shredding (HIGH-8)

Player-authored free text — `intent.approach`,
`intent.dialogue.quoted_speech`, `intent.duration_hint.text` (registry:
`crypto.PLAYER_TEXT_PATHS`; journal free text joins when journaling
ships) — is AES-256-GCM encrypted AT APPEND under a per-account-world
envelope key (`account_key` singleton, migration 0009; DEK wrapped
under `EVERQUILL_MASTER_KEY` when set). The `pending_confirmation`
intent is encrypted the same way and decrypted at confirm. Deleting the
key row (`crypto.shred_account_key`, owner connections only) erases
those fields: dumps and backups hold them only as ciphertext, owners'
reads render `[shredded]`, and every event still folds. No projection reads an
encrypted field, and derived canon (deposit-claim texts, impossible-
attempt deed descriptions) deliberately no longer embeds the player's
words. Read-path contract for Team F: docs/engine/claims.md §"Crypto-
shred read path".

Known limits: what a shred does not erase (audits 2026-10-24 and 25).
- The narration prose. The narrator is given the player's approach and
  quoted speech and may repeat them ("Kneel," she says), and prose is
  stored in plaintext on `narration_generated` (it is model output, so it
  is not on the registry).
- The character name, in the `character_created` payload, the
  `characters` and `scene_manifest` projections and the prose. The API
  bounds it (1 to 40 printable characters, no newlines), the parser
  roster shows the player as "you", and the narrator receives it
  JSON-quoted.
- `public.test_turn_capture`, which stores the utterance and approach
  in plaintext for accounts flagged for testing; a shred with a world
  id deletes that account's rows, but not copies already in backups.
So a shred makes the typed fields unreadable but is not a full erasure.
Erasing the rest would mean encrypting narration prose under the same
key, which is not done.
