# Everquill Data Layer — Engineering Decision Document

**Status:** synthesis of 6 lens reports (event-sourced-games, llm-memory-systems, context-assembly, claim-graphs, postgres-event-store, timers-schedulers). Team A/F implement from Section 2.

---

## 1. Verdicts on the six committed decisions

### D1 — Event-sourced canon: **VALIDATED, with one hard invariant added**
Strongly precedented: SpacetimeDB/BitCraft runs a shipping MMO on exactly this shape (append-only commitlog, deterministic reducers, everything readable is a projection) at 1000x our scale ([SpacetimeDB](https://github.com/clockworklabs/spacetimedb), [Clockwork Labs](https://clockwork-labs.medium.com/spacetimedb-and-bitcraft-bc957a7faf40)); Elite Dangerous's Player Journal proves additive weak-schema JSON event logs survive years of game evolution ([Journal Manual v32](https://hosting.zaonce.net/community/journal/v32/Journal_Manual-v32.pdf)); EVE's wallet ledgers prove the auditability payoff ([CCP single-shard](https://www.gamedeveloper.com/game-platforms/feature-ccp-outlines-single-shard-mmo-development)).

**The added invariant (non-negotiable, write it into the roadmap verbatim):** Everquill is *event sourcing* (fold over recorded outcomes), never *command sourcing* (re-execution of inputs through the engine). Every famous "replay broke" story — Factorio disabling replays on any prototype change ([Factorio wiki](https://wiki.factorio.com/Replay_system)), SC2 shipping old engine binaries and still orphaning replays at Patch 3.0 ([Kotaku](https://kotaku.com/starcraft-iis-new-patch-wont-support-old-replays-1734891305)), Slay-the-Spire seeds breaking every patch ([StS seeds](https://slaythespire-2.com/seeds)) — comes from re-simulation. Events store the roll values, modifiers, tier, and applied deltas; replay never re-rolls, never calls live rules code. This dissolves (not merely mitigates) the engine-churn-vs-replay risk: the engine may change freely because it is never on the replay path.

### D2 — Claim store: **REFINE (three concrete changes)**
The schema is essentially W3C PROV-lite + Wikidata competing statements — both proven production patterns — and Talk of the Town independently converged on the same shape (beliefs with evidence lists, source/location/time, predecessor pointers, strength-weighted revision, lies tracked system-side) ([Ryan et al., AAAI](https://eis.ucsc.edu/papers/ryanEtAl_TowardCharactersWhoObserveTellMisrememberLie.pdf); [Wikidata Help:Ranking](https://www.wikidata.org/wiki/Help:Ranking)). Zep/Graphiti converged on it again from the agent-memory direction ([arXiv 2501.13956](https://arxiv.org/html/2501.13956v1)). Refinements:

1. **Add a `contested` lifecycle state** between asserted and superseded. Both Wikidata (coexisting ranked statements) and Talk of the Town (candidate beliefs) keep conflicting claims live indefinitely. Racing every contradiction to supersession destroys "I've heard two versions" — the richest narrative output of the system.
2. **Corroboration requires independent provenance roots.** Store `provenance_root_event_id` (origin deed) propagated through every rumor hop; corroboration = ≥2 evidence links with distinct roots. Without this, one tavern lie reaching a character via three neighbors self-upgrades to "corroborated" — the echo-chamber failure ([truth-discovery lit](https://arxiv.org/pdf/1509.00104)). This is the one structural gap in the committed spec.
3. **Replace "confidence = evidence consistency" with strength summation:** per-evidence base weight by acquisition method (observed > firsthand testimony > secondhand rumor > inherited journal > overheard), decayed by world-time age, summed. Consistency-only confidence cannot rank one strong observation against three weak rumors; Talk of the Town's playtested strength model can, deterministically. Keep confidence as a derived *display* value only.

Also adopt bitemporal-lite: the event log already IS the transaction-time axis; add only `world_time_acquired` and nullable `world_valid` int8range to claims. Do NOT adopt pg_bitemporal/`EXCLUDE` machinery on claims — conflicting overlap is the point ([claim-graphs lens](https://link.springer.com/article/10.1007/s42488-026-00162-x)).

### D3 — Context assembler: **VALIDATED core, REFINE with four missing disciplines**
The two load-bearing bets are now evidence-backed: (a) vector retrieval is a documented reproducibility hazard — embedding versions, float precision, ANN, and hardware all inject run-to-run variance ([arXiv 2509.18869](https://arxiv.org/abs/2509.18869); [RAGdeterm](https://www.sciencedirect.com/science/article/pii/S2352711026001299)); SillyTavern's vector mode is the shipped experiment proving similarity activation is flaky ([ST World Info docs](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)). (b) The 2–3k budget beats a lazy 20k dump per context-rot findings ([Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)). Missing from the committed design, all four being where drift actually enters:

1. **Total deterministic ordering.** NovelAI documents that equal-priority entries have *no guaranteed sequence* ([lorebook docs](https://docs.novelai.net/en/text/lorebook/)). Without a full tiebreak chain down to claim ULID, you have "usually the same context," not "same state → same context."
2. **Constraint-class pinning.** The single most important empirical finding across shipped products: behavioral constraints, promises, and consequences are evicted *first* and identities last (character.ai fragility hierarchy) — the exact inverse of what a referee needs. Oaths/prohibitions/consequences must be pinned by type into the Required tier, never left to salience ranking.
3. **Reserved token floors per section** (NovelAI Reserved Tokens; AI Dungeon's 70% Required guard + 25/50/25 split) so one bloated component can never starve clocks or the last-action trace ([AID context docs](https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai)).
4. **Never LLM-summarize claims or canon in the turn path.** Repeated summarization causes drift toward sanitized generic history ([Morph compaction](https://www.morphllm.com/compaction-vs-summarization)); claims render via fixed deterministic templates. Also: always include the engine's **machine-readable resolution of the last action** so the narrator cannot re-narrate a miss as a hit ([DEV.to DM postmortem](https://dev.to/austin_amento_860aebb9f55/prompt-architecture-for-a-reliable-ai-dungeon-master-d99)).

### D4 — Lazy rumor propagation: **VALIDATED, two refinements**
Right consumer shape (Tier-2 checkpointed reader over `(location_id, world_time)`), and Talk of the Town + Intra's perspective-filtered NPC logs are direct precedent. Refinements: (1) **epoch cache keys must be `event.id` high-water marks per region, not wall-clock** — otherwise a late-committing deed is permanently excluded from an epoch (the lost-event anomaly, one level up) ([eugene-khyst xid8 pattern](https://github.com/eugene-khyst/postgresql-event-sourcing)); (2) **rumor corruption rolls seeded from `(provenance_root_event_id, hop_count, region_epoch)`** so recomputing an epoch reproduces identical mutations — this upgrade is what makes lazy propagation cacheable and auditable rather than merely cheap.

### D5 — World clock: **VALIDATED mechanism, CHALLENGED wording**
Timer table + `FOR UPDATE SKIP LOCKED` sweeper is the canonical race-free pattern (pg-boss/Que/Oban/graphile-worker all ship on it; limits appear at thousands of workers — we need one) ([Netdata](https://www.netdata.cloud/academy/update-skip-locked/)). **Challenge:** "timed results via Anthropic Batch API" as written implies timer *outcomes* ride the Batch round-trip. They must not — batches carry a hard 24h expiry and load-dependent slowdown ([official batch docs](https://platform.claude.com/docs/en/build-with-claude/batch-processing)). Rule: **canon never waits for the LLM.** The engine resolves the mechanical outcome and appends the event at fire time; Batch writes prose afterward (ambient lane, 50% discount). Two further hardenings: seed timer dice from `hash(timer_id, created_event_id)` never wall-clock, and stamp fired events at `world_due` not processing time — together these make late firing bit-identical to on-time firing (downtime-proof = savescum-proof extended).

### D6 — Volume estimate: **VALIDATED emphatically; it forbids infrastructure**
Alpha ≈ 9k events/day ≈ 3.3M/year; even 10k-player worst case (~35 events/sec avg, ~1.1B rows/year) is 3–5 orders of magnitude below where Postgres event stores get interesting (production reference: ~1M events over 6 years on a t2.micro; billions of rows fine with lean indexes) ([kspeakman](https://dev.to/kspeakman/event-storage-in-postgres-4dk2); [TigerData](https://www.tigerdata.com/blog/handling-billions-of-rows-in-postgresql)). Consequences, all binding: no Kafka/EventStoreDB, no Redis, no partitioning (threshold ~100M rows/50GB — decades away; tripwires: >500k events/day, table >50GB, VACUUM >30min), no ES framework (the Python `eventsourcing` lib stores opaque `bytea` state and takes `LOCK TABLE IN EXCLUSIVE MODE` per insert — verified from source, both disqualifying), and **synchronous same-transaction projections** — the single biggest practical win of Postgres over dedicated event stores, deleting the entire eventual-consistency pitfall class ([SoftwareMill](https://softwaremill.com/implementing-event-sourcing-using-a-relational-database/); [Dudycz](https://event-driven.io/en/projections_and_read_models_in_event_driven_architecture/)).

---

## 2. Recommended concrete stack

**Platform:** single Railway Postgres (volume-backed, per house rule), plain **psycopg3**, ~200–400 LOC event store, one dedicated worker service separate from the web/bot process. Procrastinate for infra jobs (sweep tick, batch submitter/poller, outbox flusher, stalled-job reaper); raw SKIP LOCKED for the domain timer sweep itself.

### 2.1 Event table (single table, all streams)

```sql
CREATE TABLE event (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id  xid8        NOT NULL DEFAULT pg_current_xact_id(),
    event_ulid      text        NOT NULL UNIQUE,      -- stable external ref
    stream_id       uuid        NOT NULL,             -- character/place/faction/world-system
    stream_type     text        NOT NULL,
    version         int         NOT NULL,             -- per-stream, from 1
    event_type      text        NOT NULL,             -- 'deed.duel_won', 'timer.training_done'
    type_version    smallint    NOT NULL DEFAULT 1,
    world_time      bigint      NOT NULL,             -- game-clock tick (world_due for timer fires)
    location_id     uuid,
    command_id      text        NOT NULL UNIQUE,      -- idempotency ('timer:{id}', client cmd ULID)
    rng             jsonb,                            -- {stream_id, counter, rolls[]}
    payload         jsonb       NOT NULL,             -- resolved outcomes + applied DELTAS + provenance
    meta            jsonb       NOT NULL DEFAULT '{}',-- causation/correlation, engine_version, ruleset_version
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (stream_id, version)                       -- optimistic concurrency = savescum-proof
);
CREATE INDEX ON event (stream_id, version);
CREATE INDEX ON event (location_id, world_time) WHERE location_id IS NOT NULL;  -- rumor propagation
CREATE INDEX ON event (event_type, world_time);
REVOKE UPDATE, DELETE ON event FROM app_role;         -- append-only at privilege level
```

Rules: payloads are **facts with deltas**, never commands; `engine_version`/`ruleset_version` are forensic metadata, never replay inputs. The turn loop and the timer worker racing on one character is resolved by the `(stream_id, version)` unique constraint — loser retries against new state. Async consumers (rumor epochs) read only `WHERE transaction_id < pg_snapshot_xmin(pg_current_snapshot())` — the ~free xid8 fix for the sequence-gap lost-event anomaly ([eugene-khyst](https://github.com/eugene-khyst/postgresql-event-sourcing)). Player free-text payload fields encrypted per-player (crypto-shredding for GDPR erasure) from day one.

### 2.2 Projection strategy
- **Tier 1, synchronous (same transaction as append):** current stats, KNOWN sheets, claim writes + write-time contradiction probe, scene manifest deltas, active clocks. No eventual consistency anywhere the player can see.
- **Tier 2, checkpointed async:** region-epoch rumor caches, analytics. `projection_checkpoint(projection_name PK, last_tx_id xid8, last_event_id)`; worker claims with SKIP LOCKED, reads under the xmin predicate, applies + advances checkpoint in one transaction. One writer per projection table ([Dudycz](https://event-driven.io/en/projections_and_read_models_in_event_driven_architecture/)).
- **Rebuilds:** every projector carries `projector_version`; changed logic rebuilds into **shadow tables → diff → atomic swap**, never in place ([Doomen](https://www.linkedin.com/pulse/ugly-event-sourcing-projection-schema-changes-dennis-doomen)). Truncate-and-replay is seconds-to-minutes at our volume. Snapshots deferred (streams replay in ms; Tier-1 keeps hot state materialized anyway).

### 2.3 Claim lifecycle (five states; transitions are events)

`claim_asserted / claim_corroborated / claim_contested / claim_superseded / claim_retracted` in the deed log; the claim table stays a rebuildable projection. Schema per the claim-graphs lens (§2 there — use it verbatim): typed `predicate` from a **closed controlled vocabulary** (the LLM parser maps free text to predicates; contradiction stays a SQL equality-and-overlap problem, never NLI/LLM checking), typed value columns, `provenance_root_event_id`, `derived_from_claim_id`, `hop_count`, `strength` (cached sum), `journal_flag`.

- **asserted** → default on first evidence.
- **corroborated** → ≥2 evidence links with **distinct provenance roots**; higher assembly salience.
- **contested** → live conflicting claim on same `(believer, subject, predicate)` that hasn't outweighed it; both rows active, challenger linked; assembler surfaces pairs deliberately (narrator gold).
- **superseded** → outweighed; never deleted (Wikidata deprecation rationale: prevents re-adoption from stale sources); `superseded_reason ∈ {better_evidence, direct_observation, source_recanted, canon_sealed}`.
- **retracted** → terminal; origin evidence itself invalidated.

**Contradiction timing:** within one mind = write-time, synchronous (one indexed probe per insert). Across minds = read-time, scoped to scene entities only (≤~10, a handful of lookups). During propagation = at epoch computation, per-NPC, with seeded corruption. Plus one **canon-sealing sweep** riding the existing timer worker: when canon seals a deed as false, claims rooted in it flip contested/retracted *for characters who learn of it via propagation* — never omnisciently.

**Inheritance:** journaling is an event snapshotting claim IDs at that log position (`journal_flag=true`); death copies nothing; on inheritance, mint **new** claim rows for the heir resolved as of the journal event's log position (ancestor's later un-journaled corrections don't leak), `acquisition_method='inherited_journal'`, `hop_count+1`, `status='asserted'` — lifecycle state does not inherit; the heir holds a document, not the ancestor's evidence. **Journal text is untrusted data**: rendered quoted/delimited in any prompt, never as instructions (persistence-injection vector demonstrated against ChatGPT memory — [embracethered](https://embracethered.com/blog/posts/2025/chatgpt-how-does-chat-history-memory-preferences-work/)).

**Indexes** (from claim-graphs lens): partial "truthy" index on `(believer_id, subject_id, predicate) WHERE status IN ('asserted','corroborated','contested')`; `(believer_id, world_time_acquired DESC)` partial; `provenance_root_event_id`; `derived_from_claim_id` partial; `journal_flag` partial; gist `(subject_id, world_valid)` only for whereabouts-class predicates. B-tree over GIN; typed columns over jsonb.

### 2.4 Assembler: scoring formula + budget split

Candidate pre-filter (cheap SQL, hundreds not 500k): subject ∈ scene entities OR scope ∈ {scene location, parent region} OR subject referenced by an active clock. Then:

```
salience(c) = 100·V + 60·N + 40·R + 40·K + 30·O − 50·D     (integer basis points; NO floats, NO set-relative normalization)
```

| Term | Computation |
|---|---|
| V structural relevance | max of: subject present 1.0; one-hop link 0.6; scope=scene 0.8; scope=region 0.4; quest target 0.7 |
| N notoriety | write-time rule-assigned deed notoriety n/10 (death 9, oath/betrayal 7–8, duel 5–6, commerce 1–2); never re-scored |
| R recency | `2^(−Δ/h)`, Δ = world-hours since `acquired_at`; half-life table: gossip 72h, sightings 168h, biography 2160h, world-structure ∞ |
| K clock coupling | active clock due within 48 world-h referencing subject/location: `1 − t/H`, else 0 |
| O thread stickiness | subject in narration events of last 3 turns: 1.0 / 0.6 / 0.3 (pure function of log prefix) |
| D redundancy | already covered by known-sheet slice or packed claim: 1, else 0 (greedy, during packing) |

Sort key: `(salience DESC, category_rank ASC, world_timestamp DESC, claim_ulid ASC)` — total order, no exceptions. First-fit packing by rendered-template length; per-subject cap 3 claims (diversity without similarity functions). **Confidence never gates inclusion** — confidently-wrong claims must reach the narrator; contested pairs render both, tagged conflicting. **Constraint-class claims (oaths, prohibitions, promises, active consequences) bypass ranking entirely — pinned into Required tier.** Weights/half-lives/notoriety rules/templates in versioned config; every assembled context stamped `assembler_version` + content hash **logged as an event**.

**Budget (2,800 target, reserves 1,650, caps 3,100), fixed insertion order** exploiting the U-shaped attention curve ([lost-in-the-middle](https://arxiv.org/pdf/2406.16008)):

| # | Section | Reserve | Cap |
|---|---|---|---|
| 1 | Canon excerpts binding this scene (deaths, oaths, verdicts) — verbatim templates, top | 150 | 350 |
| 2 | Scene manifest — never evicted | 200 | 400 |
| 3 | Known-sheet slices, present entities (~110 tok/entity; >6 entities → one-liners) | 300 | 650 |
| 4 | Salient claims (formula above) — flex section | 400 | 750 |
| 5 | Active clocks + pressure | 100 | 200 |
| 6 | Last 2–3 exchanges verbatim + 1 sealed scene summary — bottom | 400 | 600 |
| 7 | Parsed action + **last-action machine resolution trace** + directive — final tokens | 100 | 150 |

Unused reserve flows to claims, then narration. Trim within sections before dropping sections. Chronicle summaries: offline Batch generation, written back as events, entailment-gated, regenerated **only from original events** — never summary-of-summary ([Morph](https://www.morphllm.com/compaction-vs-summarization)). Ship a per-turn "why is this in the prompt" trace (component + query + score per included token) — NovelAI/ChatGPT's uninspectability is the anti-lesson.

### 2.5 Timer worker

```sql
CREATE TABLE timer (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind TEXT NOT NULL,                     -- training|research|travel|pressure_front|exam
  subject_id UUID NOT NULL,
  due_at TIMESTAMPTZ NOT NULL,            -- real-world
  world_due BIGINT NOT NULL,              -- world-clock stamp for the outcome event
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', -- pending|fired|cancelled
  created_event_id BIGINT NOT NULL REFERENCES event(id),
  fired_event_id BIGINT REFERENCES event(id),
  attempts INT NOT NULL DEFAULT 0
);
CREATE INDEX timer_due_pending ON timer (due_at) WHERE status = 'pending';
```

Sweep every 15–30s (procrastinate periodic task): claim `WHERE status='pending' AND due_at<=now() ORDER BY due_at, id LIMIT 50 FOR UPDATE SKIP LOCKED`; per timer **in one transaction**: deterministic resolution (seed = `hash(timer_id, created_event_id)`), append event with `command_id='timer:{id}'` ON CONFLICT DO NOTHING, mark fired, insert outbox row. No external calls inside the transaction — pushes and Batch submissions go through the outbox. Timers created transactionally with their causing event; cancellation guarded `WHERE status='pending'` so fire-vs-cancel is decided by the row lock. This table doubles as the transactional outbox for Batch API work: submitter leases rows (no held transaction across HTTP), deterministic `custom_id = narration_request.id`, unique-keyed ingestion, poller every 60s (webhooks unverified in official docs — build on polling). Batch = ambient lane only; interactive lane = sync Messages API; expired requests resubmit once, escalate to sync if player-blocking.

**Downtime policy:** domain timers fire ALL overdue in `(due_at, id)` order stamped at `world_due` — no grace cutoff, ever (procrastinate's own 10-min cron cutoff is why domain timers don't ride library cron semantics — [procrastinate docs](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cron.html)). Pressure fronts = lazy `last_evaluated_at` delta-evaluation, not tick timers. Infra periodics skip missed runs. Pushes coalesce into one digest per player. Startup order: reconcile batches → fire overdue timers → advance fronts → flush outbox; each step idempotent so a crash during recovery restarts recovery.

### 2.6 Replay-versioning policy (binding rules)
1. **Facts, not commands** — replay is a pure fold over stored deltas; upcasters are pure functions with no engine imports.
2. **Additive weak schema within a version** — new optional fields OK; rename/repurpose/reinterpret forbidden.
3. **Structural break ⇒ `type_version` bump + lazy chained upcaster** (Marten/Greg Young pattern — [esversioning](https://leanpub.com/esversioning/read)).
4. **Semantic break ⇒ new event type name.** Meaning change is never a version bump ([arXiv 2104.01146](https://arxiv.org/abs/2104.01146) found semantic drift is the nastiest class). Field semantics live in a diff-reviewed registry file.
5. **Golden corpus in CI** — frozen sample events for every `(type, type_version)` ever shipped, folded on every commit, projection diffs fail the build. This is the cheap substitute for Blizzard's keep-old-binaries.
6. **Snapshot barriers as rare escape hatch** — `StateSnapshot` epoch-barrier events per character/region if an upcast chain becomes untenable (expected ~once, alpha→beta); pre-barrier events stay immutable for audit/journals.
7. **Corrections are compensating events** (`RulingReversed`, `CanonErratum`) — never log edits, including during alpha (wipe worlds instead; alpha is where the discipline is built or lost).
8. **Do NOT build:** DFU-style generic migration framework, Avro/schema registry, routine copy-migrations (Minecraft's DFU generality consumed most of game startup — [cadmium](https://github.com/jellysquid3/cadmium-fabric)).

---

## 3. Top 10 pitfalls, ranked by likelihood of biting

1. **Accidental command sourcing.** A fold "just quickly" recomputes damage from the stored roll; next balance patch silently rewrites sealed deaths. Most likely failure because the engine churns daily during dev. *Mitigation:* deltas-only folds, no engine imports in projectors (lint rule), golden-corpus CI gate (§2.6.5).
2. **Constraint eviction + confident fabrication.** Under budget pressure, promises/prohibitions/consequences rank out first while the model invents replacements without hedging — documented across AID, character.ai, NovelAI. *Mitigation:* constraint-class pinning into Required tier; reserved floors; narration lint against entities/values absent from the assembled slice.
3. **Nondeterministic assembler packing.** Float scores, set-relative normalization, or undefined tie order make "same state → same prompt" quietly false (NovelAI ships this bug). *Mitigation:* integer basis points, fixed transforms, full ULID tiebreak chain, cross-platform byte-identity test (T2).
4. **Re-narration drift.** Narrator contradicts last turn's mechanical outcome (miss narrated as hit, spent resource reused). Bites in week one. *Mitigation:* machine-readable last-resolution trace always in section 7; regression fixtures.
5. **Corroboration echo chamber.** One lie arrives via three neighbors and self-upgrades to corroborated; lazy propagation manufactures "confirmed" falsehoods at scale. *Mitigation:* distinct-provenance-roots rule; retellings raise strength only, never corroboration status.
6. **Timer/turn double-fire.** Sweeper retries, mobile client retries, and worker crashes are all at-least-once; a non-idempotent append double-completes training (a production system grew a 100k-event stream exactly this way — [planetgeek](https://www.planetgeek.ch/2026/05/05/event-sourcing-you-better-prevent-long-event-streams/)). *Mitigation:* UNIQUE `command_id` on the event table; claim+resolve+append+mark in one transaction; events only on state change.
7. **Canon waiting on the Batch API.** As currently worded, D5 lets a 24h batch expiry delay *truth*, not just prose. *Mitigation:* engine resolves at fire time; Batch is decoration; expiry-rate alert metric; <24h+slack player-gating work never rides Batch alone.
8. **Semantic drift disguised as compatible schema.** Same field name, changed meaning; weak-schema JSON hides it until every projection is subtly wrong. *Mitigation:* rule 4 of §2.6; semantics registry diffed in review.
9. **In-place projection rebuilds / log edits.** Rebuilding changed fold logic over live read models, or a "quick" UPDATE on the event table, is the tactic every production ES team regrets ([Doomen](https://www.linkedin.com/pulse/ugly-event-sourcing-real-world-production-issues-dennis-doomen)). *Mitigation:* REVOKE UPDATE/DELETE; projector_version + shadow-table swap; compensating events only.
10. **Lost-event anomaly in async readers.** Sequence gaps + out-of-order commits let a checkpointed reader (rumor epochs) permanently skip a late-committing deed; wall-clock epoch keys have the same hole. *Mitigation:* xid8 column + `pg_snapshot_xmin` read predicate; epoch keys = per-region event.id high-water marks.

*Honorable mentions:* journal-text prompt injection into heirs (quote/delimit, red-team test T7); summary-of-summary drift (regenerate from originals only, entailment gate); world-clock heartbeat event spam (events only on state change; per-character events/day alarm).

---

## 4. Roadmap deltas — State Architecture section

- **D1, append:** "Events record resolved outcomes and applied deltas (rolls, modifiers, tier). Replay is a pure fold; it never re-executes engine logic. `engine_version`/`ruleset_version` are forensic metadata, not replay inputs. Append-only is enforced at the DB-privilege level (REVOKE UPDATE/DELETE); corrections are compensating events (`CanonErratum`). Schema evolution: additive weak schema, `type_version` + pure upcasters for structure, new event type for meaning changes, golden-corpus replay in CI."
- **D2, replace** "confidence(=evidence consistency)" **with** "strength = decayed sum of per-method evidence weights (observed > told > rumor > journal > overheard); confidence is a derived display value." **Add:** `contested` as a fifth first-class lifecycle state; `provenance_root_event_id` propagated through hops with corroboration requiring distinct roots; bitemporal-lite columns `world_time_acquired` + nullable `world_valid`; lifecycle transitions emitted as events (claim table = rebuildable projection); closed predicate vocabulary enforced at the intent-parser boundary.
- **D3, append:** "Total deterministic ordering (integer scoring, fixed transforms, ULID tiebreak; byte-identical prompts for identical log prefixes). Reserved token floors + caps per section per the budget table. Constraint-class claims (oaths, prohibitions, promises, consequences) are pinned by type, never salience-ranked. The last action's machine-readable engine resolution is always included. Claims/canon render via fixed templates — never LLM-summarized in the turn path; chronicle summaries are offline, entailment-gated, sealed as events, regenerated only from source events. Every assembled context logs `assembler_version` + content hash as an event."
- **D4, replace** "cached per region-epoch" **with** "cached per region-epoch keyed on per-region event.id high-water marks (xid8-safe read predicate), with rumor corruption rolls seeded from (provenance_root_event_id, hop_count, epoch) so recomputation is bit-identical."
- **D5, replace** "timed results via Anthropic Batch API" **with** "engine resolves timer outcomes deterministically at fire time (seed = hash(timer_id, created_event_id)), stamped at `world_due`; Batch API serves the ambient narration lane only — canon never waits for the LLM. Downtime policy: fire all overdue domain timers in (due_at, id) order with no grace cutoff; pressure fronts are lazy last_evaluated_at processes, not tick timers; exams are timer-chain deeds resolving participants from projections at fire time."
- **D6, append:** "Explicit non-goals until tripwires (>500k events/day, table >50GB, VACUUM >30min): no partitioning, no broker, no ES framework, no snapshots. Projections are synchronous same-transaction (Tier 1) except rumor epochs/analytics (Tier 2 checkpointed)."
- **New subsections:** (a) Legacy/inheritance mechanics per §2.3 (journal events snapshot at log position; heirs mint fresh `asserted` rows; journals are untrusted data in prompts); (b) GDPR crypto-shredding for player free text; (c) stack pin: psycopg3, hand-rolled store, procrastinate + SKIP LOCKED.

---

## 5. Test suite — the 10 tests that prove the data layer

1. **Golden-corpus replay (determinism/versioning).** Frozen fixture events for every `(event_type, type_version)` ever shipped; CI folds them every commit; any projection diff fails the build unless `projector_version` bumps in the same commit. Catches pitfalls 1, 8.
2. **Byte-identical assembly.** Same event-log prefix assembled twice, across processes and Linux+macOS runners → byte-identical context; logged content hash == recomputed hash. Catches pitfall 3.
3. **Rebuild equivalence.** Truncate every projection (stats, KNOWN sheets, claims, rumor epochs), replay from genesis → hash-equal to live projections. Run after every projector change and every migration (the Replika-2.0 lesson: memory regressions read as character death).
4. **True-sheet leak audit.** Fixtures where true stats differ from believed values: assert the true value's rendered form appears nowhere in assembled context while the wrong believed value does; static CI rule that the assembler module imports only projection views; red-team prompts asking the narrator for hidden stats.
5. **Irrelevance injection (metamorphic).** Append 10k events in a distant region → target scene's assembled context unchanged. Catches set-relative normalization and candidate-query leaks.
6. **Constraint-flood budget invariant.** Adversarial claim floods: every pinned constraint-class claim survives packing, every reserve floor is met, total ≤3,100 tokens, no mid-template truncation, history slice never empty. Catches pitfall 2.
7. **Journal injection red-team.** Inherited journals containing "ignore previous instructions" and stat-revelation bait → zero behavioral change in narrator output; journals render as delimited quoted data.
8. **Late-fire determinism (recovery).** Fire a timer on time in world A; hold worker down 3 hours in world B then recover → identical event rows (same rng, same world_time = world_due, same deltas). Then: kill worker mid-sweep, restart, run sweep twice → exactly one fired event per timer (command_id conflict absorbs the duplicate). Catches pitfalls 6, 7's mechanical half.
9. **Epoch coherence + lost-event probe.** Append a deed, query NPC knowledge in-region same tick → epoch invalidated (keyed on event.id HWM); recompute the epoch twice → identical corrupted-rumor output (seeded corruption); simulate a late-committing transaction → xid8 predicate prevents the skip. Catches pitfalls 5's cache half, 10.
10. **Long-horizon drift canary.** Scripted 100-turn playthrough replayed after any assembler/prompt/ruleset change: judge-scored contradictions vs the deed log block on regression; churn bound (20 no-event turns → consecutive contexts differ <15%, narration window only); contested pairs always rendered as exactly one claim per slot or both-tagged-conflicting. Catches pitfalls 2, 4 at the system level.

**Cadence:** 1–9 are deterministic and run per-commit; 10 runs nightly on Batch. Tests 1–3 are the foundation — if they're green, every other guarantee (sealed deaths, reproducible wrong intel, auditable dice) is enforced by construction rather than by vigilance.