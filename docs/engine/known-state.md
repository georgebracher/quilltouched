# KnownState / RefereeState — the state surfaces (A1, Sprint 2 wave 1)

Status: **published interface** (Sprint-2 ticket, Team A1; fixes review
MEDIUM-1). Code: `everquill_engine/views.py`. Enforcement:
`tests/test_known_boundary.py` (static AST lint over `api/` and `llm/`).

## The split

| Surface | Who may touch it | What it holds |
|---|---|---|
| `RefereeState` | engine + service layer (`beat.py`) ONLY | full Tier-1 fold image (true sheets, entity hp, timers, rng counters) + authored `WorldContent` (true sheets, threat bands, laws) |
| `KnownState` | Teams C (assembler/narrator) and F (API) | Chronicle facts, Inquiry claims, perceived scene manifest — nothing else exists on the object |

`KnownState` is built by **extraction**: safe fields are copied out at
construction; no attribute path leads back to an aptitude, threat band,
or raw hp number. `tests/test_views.py::TestNoTrueSheetLeak` serializes
the entire surface and scans it.

## Exported names (the contract Teams C/F consume)

From `everquill_engine.views`:

- `load_known_state(fold_state, world, slot_maps=None) -> KnownState` —
  builder (slot_maps defaults to `content/world/slots.yaml`, tolerant of
  absence).
- `KnownState` — methods:
  - `chronicle_facts(character_id) -> ChronicleFacts`
  - `inquiry_claims(believer_id, subject_id=None) -> tuple[InquiryClaim, ...]`
  - `scene(character_id) -> SceneView`
  - `world_date` (property, Chronicle string)
- `ChronicleFacts` — `character_id, name, coin (exact int), wounds
  (WORD), named_abilities (titles), public_rank (None until guilds),
  inventory ({contract item: qty}), location_id, world_date`. Sprint-3
  addition (status strip, roadmap §3.8): `active_timers` — a tuple of
  `TimerFact` for the character's PENDING timers, sorted by
  `(due_world_time, timer_key)`.
- `TimerFact` — `timer_key, kind, due_world_time (int), due_at (real ISO
  str)`. KNOWN-safe: the timer's kind + due stamps, never its true-sheet
  payload. Coin + world_date were already exact-known; this closes the
  status-strip gap Team D flagged in S2.
- `InquiryClaim` — `claim_id, subject_entity_id, claim_text,
  value_or_range, source, observer, method, world_date, scope,
  confidence, status, journal_flag` (full provenance stamp; Inquiry
  layer only). Claim v2 additions (Sprint 2 wave 3, additive —
  docs/engine/claims.md): `predicate` (closed vocabulary),
  `value_text` (also feeds the compat `value_or_range` name),
  `acquisition_method`, `strength` (decayed evidence-weight sum,
  integer basis points), `hop_count`, `contested_by_claim_id`
  (contested pairs arrive as two live claims linking each other).
  Hardening Pass 1 addition: `contradiction_ids` — the FULL tuple of
  claim ids that contest this claim, sorted, both ways (audit #2; see
  "Contested claims" below).
- `SceneView` — `location_id, name, location_type, region, world_date,
  entities: tuple[PerceivedEntity, ...]`.
- `PerceivedEntity` — `entity_id (contract form, valid intent target),
  name, kind (fine-grained authored kind), category (coarse vocab — see
  "Entity category vocabulary" below), portrait, conditions (visible
  only: 'dispatched' at 0 hp, 'wounded' when visibly hurt, plus stored
  condition tags), slot_id, x_pct, y_pct` (slot fields null when
  unassigned).
- `wound_words(hp, hp_max) -> str` and `WOUND_BANDS` — the published
  wound vocabulary: `unhurt / scuffed / hurting / bloodied / at death's
  door / dispatched` (integer banding; the numbers never leave the
  engine).
- `RefereeState` — server-side only. `api/`/`llm/` importing it (or
  `FoldState` / `load_fold_state` / `everquill_engine.folds`) fails the
  static lint. Two Sprint-1 debt imports (`api/main.py`,
  `api/bootstrap.py`: `load_fold_state`) are frozen in the lint's
  `KNOWN_DEBT` ratchet — wave-2 wiring must shrink that list.

## Slot assignment (interface decision 5)

`content/world/slots.yaml` format (Team B authors):
`{location_type: {slots: [{slot_id, x_pct, y_pct}]}}` — loader
`everquill_engine/slots.py` (`load_slot_maps`, `assign_slots`).

Assignment is deterministic and presentation-only: entities present at
the location, sorted by id; each takes
`sha256('everquill.slots.v1|' + entity_id) % len(free_slots)` from the
remaining free slots. Same scene composition → same arrangement, any
machine. More entities than slots → the overflow gets `slot_id: null`.
File absent or location type unmapped → **stable ordering, slot_id
null** for everyone (Team D renders unslotted); nothing blocks on
Team B.

## Commit beat surface (interface decision 2)

From `everquill_engine.beat` (Team F wires these in wave 2):

- `assess_or_execute(conn, command_id, intent, *, world, character_id="pc") -> BeatResult`
- `confirm(conn, command_id, *, world) -> BeatResult`
- `Assessment` — `command_id, character_id, tier, risk_label,
  confirmation_required, world_minutes_cost (duration preview),
  created_world_time, expires_world_time, summary`.
- `BeatResult` — `status ('pending' | 'resolved' | 'absorbed'),
  assessment, append_result, resolution`.
- Errors: `NoPendingConfirmationError`, `ConfirmationExpiredError`
  ("the moment has passed").

Semantics:

- The engine-owned confirmation table lives in the resolver package
  (`resolver/tier.py::confirmation_required`, `resolver/common.py::CONFIRMATION_REQUIRED_FOR_RISK`): risk
  **Dire and up** (bands DESPERATE/HOPELESS), **SEALED** (met or
  unmet), or a law flagged `irreversible: true` → full `<<Proceed?>>`
  beat. Trivial/Routine/Risky and IMPOSSIBLE auto-commit.
- Assess computes tier/risk via `resolver.decide_tier` — **no dice, no
  events, no world time**. The parsed intent is stored VERBATIM in a
  `pending_confirmation` row (migration 0006; operational state, NOT a
  projection — rebuilds ignore it, `fresh_reset` clears it).
- Confirm resolves under the ORIGINAL command_id with the ORIGINAL
  stored intent; dice draw at confirm time (roll resolves inside the
  dialog). The pending row survives **strictly less than 10
  world-minutes of subsequent world activity** (`expires_world_time =
  created + 10`); at/past that, confirm marks it expired and raises
  `ConfirmationExpiredError` — never a stale resolution. A world where
  nothing happens never expires a beat.

## Round-2 HIGH fixes (2026-07-14, engine-fix crew)

Four security findings from `docs/research/reviews/codex-review-round2-s2.md`
closed at the engine boundary. `api/` wiring is in
`docs/engine/api-wiring-notes.md`.

### EQ-R2-01 — target addressability (`resolver.decide_tier`)

Membership in the authored world is NOT authorization. Before tiering,
`decide_tier` runs an engine-owned capability check
(`resolver._target_addressable`): physical/social/observation/dialogue/craft
targets must be a **co-located, perceptible** scene entity; inventory targets
must be **owned**; movement stays gated by the travel network; research
additionally reaches the **subjects of the actor's existing claims**
(`decide_tier(..., actor_claim_subjects=frozenset(dotted_ids))` — the beat
passes this from the fold image; `None` = empty). Unknown ids and unauthorized
ids are refused with ONE constant string, `resolver.UNADDRESSABLE_TARGET`, so
the boundary is not an existence oracle (tests assert byte-equality).

### EQ-R2-02 — hidden-entity visibility (the perceived-manifest choke point)

`resolver.is_perceptible(world, dotted_id, actor_flags)` is the single predicate
shared by `views.load_known_state` (scene build) and the addressability check.
An entity whose authored true-sheet carries the `resolver.HIDDEN_TAG`
(`"hidden"`) is absent from the perceived scene — and therefore from the parser
roster and narrator context, both built from that scene — UNTIL the perceiving
character's sheet holds its discovery flag `resolver.discovery_flag(id)` =
`discovered_<contract_id>`. The discovery fact is an ordinary `flag` delta any
outcome may carry (no new fold / delta type); `views.outcome_public` allowlists
the `discovered_` prefix. In `content/world/harrowdown.yaml` the only `hidden`
entity is `item.harrowdown.marriage_seal`.

### EQ-R2-03 — public outcome projection (`views.outcome_public`)

`outcome_public(contract, *, wounds_after=None)` redacts a
`resolver.outcome_contract(...)` dict for the player + narrator: hp deltas
collapse to `wound_transition` deltas carrying a fiction `effect`
(`wounded`/`recovered`/`dispatched`) with **no number and no cause** — the exact
hp stays only in the canonical `outcome_resolved` event; flag deltas survive
only for `views.PUBLIC_FLAG_PREFIXES`
(`owes_favor_/rebuffed_/noticed_by_/discovered_`), internal flags are stripped;
all other deltas (intel/deed/coin/inventory/position/timer) are KNOWN-safe and
pass through. `docs/contracts/outcome.schema.json` (v1.3) describes THIS public
shape. `wounds_after` (contract-entity-id → resulting wound word) upgrades a
kill's effect to `dispatched`; omit it for the coarse sign-based effect.

### EQ-R2-04 — intent-bound confirmations (`beat`)

Each pending `command_id` is bound to `beat.canonical_intent_hash(intent)`
(sha256 of the canonical-JSON parsed intent), stored in
`pending_confirmation.intent_hash` (migration 0011). A re-assessment with a
DIFFERENT intent raises `beat.BeatIntentMismatchError` (carrying the STORED
intent; API → 409); a matching one is idempotent. `beat.BeatResult` gained
`stored_intent` — the pending response returns the BOUND intent, never the
retry's redeclaration. Confirm still resolves the originally stored intent.

## Sprint 3 wave 1 (Team A — the knowledge system)

Additive on the shipped claim v2 system; `api/` wiring is in
`docs/engine/api-wiring-notes.md`, the source-scope field shape (Team B) is
`docs/engine/knowledge-scope.md`, migration `0012_status_strip_and_scope.sql`.

- **Research resolves against a source's scope** (roadmap §3.3/§3.6).
  `world.WorldEntity.knowledge_scope` (a `KnowledgeScope`) and
  `WorldContent.sources_at(location_id)` are new. A `research` outcome at a
  source writes ONE Inquiry claim: an appraisal FIELD on success (scope
  `appraisal_tier_<n>`, capped by the source's `max_appraisal_tier` — never a
  number), the source's confidently-WRONG answer on a bad roll (an exclusive
  `threat_assessed` claim at `told` strength 60, `scope` = the error's
  `distortion`), or a LEAD (`scope == "lead"`, `subject_entity_id` = a better
  source/location). No source present → unchanged ambient rumor (`rumor`, 35).
- **A co-located source opens its catalogue to research addressability**
  (`resolver.decide_tier` — EQ-S3A-02): a subject catalogued by a perceptible
  co-located source is addressable even off-scene, alongside the existing
  claim-subject reach.
- **Knowledge-gated actions** (`resolver.decide_tier`/`resolve_intent` —
  EQ-S3A-04): a held `weak_point` claim (new closed predicate,
  `claims.PREDICATES`) about the primary living physical target turns a
  HOPELESS confrontation into a DESPERATE option (`TierDecision.weak_point_target`
  is the target, `law_notes` records the unlock) and adds a named
  `weak_point` roll modifier (`resolver.WEAK_POINT_ROLL_BONUS = 2`, shown in the
  Chronicle dice). `threat_assessed` alone never downgrades the band. The
  service layer passes `actor_target_intel` (dotted subject → predicate set)
  to both `decide_tier` and `resolve_intent`; `beat._target_intel` builds it
  from the fold image.
- **Narration as canon**: `store.narrate_outcome(...)` appends the
  `narration_generated` event under idempotent command `narrate:<outcome ulid>`
  (A2 shipped the type+fold; audit-only). See api-wiring-notes.md for the call.

## Hardening Pass 1 (Team A — engine; audit-room 2026-07-14)

Four audit P1s close at the engine boundary. Migration
`0013_public_turn_and_contradictions.sql`; claim projector_version 2 → 3.

### Canonical public-turn record (audit #1, the headline)

ONE authoritative player-visible record per turn — the redacted public
outcome + narration prose + assembler meta — persisted as canon keyed by
the TURN command_id, at narration-commit time. **Decision: extend the
`narration_generated` event, serve from the log (no new projection, no
extra projector bump).** The event carries the assembler meta already;
Hardening Pass 1 adds two payload fields, `turn_command_id` (the original
turn command, what the client retries with) and `public_outcome` (the
redacted `views.outcome_public(...)` contract). Because the narrate command
is idempotent on `narrate:<ulid>`, the record survives response loss: prose
committed then HTTP lost → a retry is absorbed and the SAME record comes
back, never a re-resolved outcome or forked prose.

Reads (`everquill_engine.store`, the surface Team F consumes):

- `public_turn(conn, command_id) -> dict | None` — the record for a turn,
  keyed by the turn command_id. Serves first response, duplicate/retry, and
  reconnect. `None` until the turn is narrated. Fields: `turn_command_id,
  character_id, outcome_event_id, outcome_event_ulid, world_time,
  public_outcome, prose, assembler_version, content_hash, model,
  narration_event_id`.
- `recent_public_turns(conn, character_id, n) -> list[dict]` — the newest
  `n` records, **oldest-first** (chronological), for a Chronicle
  reconnect/rebuild (backs Team F's `GET /api/turns`). Same record shape.

`store.narrate_outcome(...)` gained matching optional kwargs
`turn_command_id=` + `public_outcome=`. **Team F wave-2 wiring:** pass both
at narrate time; serve `public_turn` on the duplicate path WITH its prose
(the audit's "duplicate omits narration" fix) and back `GET /api/turns`
with `recent_public_turns`. A partial expression index
(`event_narration_turn_command`) makes `public_turn` a point read.

### Contested claims surfaced (audit #2 — contradiction_ids were inert)

`claim.contested_by_claim_id` held only the LATEST contester, so a claim
contested by several others silently forgot the earlier edges, and the API
adapter hardcoded `contradiction_ids: []`. New column
`claim.contradiction_ids` (jsonb, sorted+deduped set) is accumulated by the
`claim_contested` fold and surfaced on `views.InquiryClaim.contradiction_ids`
(a tuple, both ways). Backfilled from the LOG so a live row equals a
truncate-and-replay rebuild. Fold change → **claim projector_version 3**
(golden snapshot regenerated with the bump; reason: multi-edge
contradiction surface). **Team F:** stop hardcoding `[]` — pass
`InquiryClaim.contradiction_ids` (and `contested_by_claim_id`) straight
through to the assembler.

### Fail-closed production gate (audit #6/#7) — `everquill_engine.security`

`assert_secure_startup(conn, *, env=None)` is a no-op unless
`EVERQUILL_REQUIRE_SECURE=1`. In that production mode it RAISES
`InsecureRuntimeError` when `EVERQUILL_MASTER_KEY` is absent/malformed
(no fail-open raw DEK storage, audit #6) or when the runtime connection can
bypass the append-only `REVOKE` on `event` — it OWNS the table or is a
superuser (`runtime_bypasses_append_only(conn)`, audit #7). Dev leaves the
flag unset and stays lenient (the engine + no-DB suites are unchanged, the
conn is never touched). api/-importable (no referee state). **Team F:** set
`EVERQUILL_REQUIRE_SECURE=1` on Railway and call `assert_secure_startup` at
boot / readiness; fail readiness (503) if it raises. Helper
`crypto.master_key_configured(env=None)` backs the key check.

### Entity category vocabulary (audit: gate expects `person`, prod emits `npc`)

The engine view now emits a coarse `category` on every `PerceivedEntity`
(`views.entity_category(kind)` / `views.ENTITY_CATEGORIES`), so the
narration gate and the API adapter match ONE vocabulary instead of the
fine-grained authored `kind`. **Agreed vocab (binding, coordinated with
Team C): persons = npc + character.** Full map (APPEND-ONLY, like the
predicate registry):

| kind | category |
|---|---|
| `character`, `npc` | `person` |
| `creature` | `creature` |
| `prop`, `item` | `object` |
| `location` | `place` |
| (unmapped) | `object` — safe non-person default |

`kind` stays on the entity for anything fine-grained. **Team C:** the gate's
person-detection (`category == "person"`) now matches production `npc`;
add a fixture using production categories. **Team F:** the adapter must map
`PerceivedEntity.category` (not `.kind`) into the assembler view's
`category` field.
