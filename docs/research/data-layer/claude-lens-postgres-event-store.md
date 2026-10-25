All claims verified sufficiently — the decisive one (opaque `bytea` state + `LOCK TABLE IN EXCLUSIVE MODE` per insert in the `eventsourcing` lib) confirmed from source. Synthesizing.

# Everquill — Postgres as Event Store + Projection Host

**Lens:** concrete Postgres engineering for the event-sourced canon. **Verdict up front:** single append-only events table, per-stream versions with a UNIQUE constraint, JSONB payload with a few promoted typed columns, synchronous same-transaction projections for gameplay-critical state, checkpointed replay for everything else, SKIP LOCKED timers table as the outbox, **no partitioning yet**, and **build on plain psycopg3 — no framework earns its keep here.**

---

## 1. Scale reality check (this shapes every decision)

- Alpha: ~30 heavy players x ~300 events/day ≈ **9k events/day ≈ 3.3M/year**. Average write rate: ~0.1 events/sec.
- Full 10k-player headroom, worst case all-heavy: ~3M events/day ≈ **35 events/sec average, ~1.1B rows/year**.
- Real-world reference points: a production Postgres event store accumulated ~1M events over 6 years on a t2.micro with light resource usage, and batched inserts hit ~10k events/sec on modest hardware ([kspeakman, Event Storage in Postgres](https://dev.to/kspeakman/event-storage-in-postgres-4dk2)). Postgres handles billions of rows in one table when indexes are kept lean and inserts batched ([TigerData, Handling Billions of Rows](https://www.tigerdata.com/blog/handling-billions-of-rows-in-postgresql)).

Conclusion: Everquill's write volume is **3-5 orders of magnitude below** where Postgres event stores get interesting. Every architectural choice below should optimize for correctness, auditability, and simplicity — never throughput.

## 2. Event table design

**Single table, not per-aggregate tables.** One-table-for-all-events is the consensus shape; it gives cheap global ordering, one place to audit, and one replay path. Per-aggregate tables buy nothing at this scale and complicate the Context Assembler's cross-entity queries ([breadcrumbscollector](https://breadcrumbscollector.tech/implementing-event-sourcing-in-python-part-2-robust-event-store-atop-postgresql/), [SoftwareMill](https://softwaremill.com/implementing-event-sourcing-using-a-relational-database/)).

**Per-stream version + UNIQUE(stream_id, version) is the concurrency mechanism.** Two writers loading the same character at version N both try to append N+1; Postgres rejects one with a constraint violation — optimistic concurrency with zero application locking. Corroborated by four independent implementations ([kspeakman](https://dev.to/kspeakman/event-storage-in-postgres-4dk2), [SoftwareMill](https://softwaremill.com/implementing-event-sourcing-using-a-relational-database/), [eugene-khyst reference impl](https://github.com/eugene-khyst/postgresql-event-sourcing), [Derzhavets](https://dev.to/tim_derzhavets/building-a-production-ready-event-store-in-postgresql-schema-design-projections-and-replay-25o8)). Everquill is effectively single-writer per character (one player, one turn loop), so conflicts will be rare — but the timer worker and the turn loop CAN race on the same character (a training block completing while the player acts). The constraint makes that race safe and deterministic: loser retries against the new state. This is exactly the savescum-proof property the canon needs.

**JSONB payload + promoted typed columns.** JSONB gives schema evolution without migrations and — critically for Everquill — SQL-queryable payloads for lazy rumor propagation ("what deeds happened in region X since epoch E with visibility > tavern-gossip") and claim derivation. Promote to typed columns only what you index/filter on: stream, type, world time, location. Don't bury referee-critical fields (dice results, plausibility tier) in unqueryable blobs, and don't explode every field into columns either.

**Global `bigserial` sequence: keep it, but know its one flaw.** Postgres sequences are non-transactional: rollbacks leave gaps (harmless) and transactions can commit out of order relative to their sequence numbers. A checkpointed async consumer reading "WHERE id > last_seen" can permanently skip an event that commits late — the "lost events" anomaly ([kspeakman](https://dev.to/kspeakman/event-storage-in-postgres-4dk2), [eugene-khyst](https://github.com/eugene-khyst/postgresql-event-sourcing), [SoftwareMill](https://softwaremill.com/implementing-event-sourcing-using-a-relational-database/)). Three known fixes, with measured costs:

| Fix | Cost | Verdict for Everquill |
|---|---|---|
| Transactional position-counter table | ~13x throughput drop (1,600 → 120 req/s in kspeakman's benchmark) — still 100x our ceiling | Fine, but unnecessary |
| `LOCK TABLE IN EXCLUSIVE MODE` per insert (what the Python `eventsourcing` lib does) | Serializes ALL writers globally | Overkill |
| Record `xid8` via `pg_current_xact_id()`, consumers only read events with `transaction_id < pg_snapshot_xmin(pg_current_snapshot())` | ~Free; consumers lag by at most the longest in-flight transaction | **Recommended** |

The xid8 trick costs one column and one WHERE predicate, and keeps the anomaly impossible rather than unlikely — matching the "wrong intel must be deterministic, never random" bar.

### Illustrative DDL

```sql
CREATE TABLE event (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id  xid8        NOT NULL DEFAULT pg_current_xact_id(),
    stream_id       uuid        NOT NULL,          -- character, place, faction, world-system
    stream_type     text        NOT NULL,
    version         int         NOT NULL,          -- per-stream, starts at 1
    event_type      text        NOT NULL,          -- 'deed.duel_won', 'timer.training_done', ...
    world_time      bigint      NOT NULL,          -- game-clock tick
    location_id     uuid,                          -- promoted: rumor propagation queries
    payload         jsonb       NOT NULL,          -- incl. seed, 2d6 rolls, plausibility tier
    meta            jsonb       NOT NULL DEFAULT '{}', -- causation_id, correlation_id, actor
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (stream_id, version)                     -- optimistic concurrency, savescum-proof
);
CREATE INDEX ON event (stream_id, version);         -- replay a character
CREATE INDEX ON event (location_id, world_time)     -- lazy rumor propagation
    WHERE location_id IS NOT NULL;
CREATE INDEX ON event (event_type, world_time);     -- propagation rules by deed class
-- REVOKE UPDATE, DELETE ON event FROM app_role;    -- enforce append-only at the grant level
```

Sealed deaths need no special mechanism: death is just an event, and append-only + REVOKE makes it immutable. Legacy inheritance reads the dead character's stream directly.

## 3. Projection strategy: synchronous first, checkpointed replay for the rest

The decisive advantage of Postgres-as-event-store over a dedicated event DB: **projections can update in the same transaction as the append** — either the event lands AND current-stats/KNOWN-sheet update together, or nothing happens. No eventual consistency, no dual-write problem, no message broker ([Dudycz, Projections and Read Models](https://event-driven.io/en/projections_and_read_models_in_event_driven_architecture/), [SoftwareMill](https://softwaremill.com/implementing-event-sourcing-using-a-relational-database/)). Eventual consistency is an implementation choice, not an architectural necessity — and a turn-based game that must show the player correct state on the very next turn should not opt into it.

**Tier 1 — synchronous (same transaction as append):** current stats, per-character KNOWN sheets, claim-store writes, scene manifest deltas, active clocks. The turn processor appends events and applies each registered projector inline. At ~1 turn/action per player these transactions are trivially fast.

**Tier 2 — checkpointed async (the few that earn it):** region-epoch rumor caches (already lazy by design — cache invalidation can ride NOTIFY or a 1s poll) and any future analytics. Standard pattern: a checkpoint row per projection storing last processed `(transaction_id, event_id)`; worker claims its checkpoint with `FOR UPDATE SKIP LOCKED`, reads the next batch under the xmin-safe predicate, applies, advances checkpoint in the same transaction — at-least-once delivery made effectively exactly-once by the transactional checkpoint ([eugene-khyst](https://github.com/eugene-khyst/postgresql-event-sourcing)).

**Rebuilds:** at alpha volume (single-digit millions of rows), truncate-and-replay of any projection is seconds to minutes — do the simple thing. If a rebuild ever needs zero downtime: build the new projection under a new name, replay to catch-up, atomically swap (blue/green) ([Dudycz](https://event-driven.io/en/projections_and_read_models_in_event_driven_architecture/), [Derzhavets](https://dev.to/tim_derzhavets/building-a-production-ready-event-store-in-postgresql-schema-design-projections-and-replay-25o8)). Because every projection is rebuildable, projector bugs are recoverable by fix-and-replay — this is the property that makes the claim store's "wrong intel must be reproducible" guarantee cheap to keep.

```sql
CREATE TABLE projection_checkpoint (
    projection_name  text PRIMARY KEY,
    last_tx_id       xid8   NOT NULL,
    last_event_id    bigint NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now()
);
```

One rule from the field worth adopting: **one writer per projection table** — never have two processes updating the same read model ([Dudycz](https://event-driven.io/en/projections_and_read_models_in_event_driven_architecture/)).

## 4. World clock: timers table + SKIP LOCKED worker = the outbox

The due-jobs worker is a textbook Postgres job queue, and `FOR UPDATE SKIP LOCKED` is the canonical race-free claim: workers atomically grab different due rows, and a crashed worker's transaction rollback returns the job to pending automatically ([DB Pro](https://www.dbpro.app/blog/postgresql-skip-locked), [Netdata](https://www.netdata.cloud/academy/update-skip-locked/), [AmineDiro](https://aminediro.com/posts/pg_job_queue/)). Que, Oban, and graphile-worker all run on this pattern in production. Documented limits appear at thousands of concurrent workers / millions of jobs/sec — Everquill needs one or two workers.

This table doubles as the **transactional outbox** for Batch API calls: the turn processor inserts the timer row in the same transaction as the triggering event, so an intent to resolve a training block can never be lost or orphaned. The worker claims due rows, submits to the Anthropic Batch API with the timer id as idempotency key, and on batch completion appends the resolution event (which fires Tier-1 projections like any other append). At-least-once + idempotent append = safe.

```sql
CREATE TABLE timer (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    stream_id     uuid   NOT NULL,
    kind          text   NOT NULL,        -- training, research, travel, front, exam
    due_world     bigint NOT NULL,
    due_at        timestamptz NOT NULL,
    payload       jsonb  NOT NULL,
    status        text   NOT NULL DEFAULT 'pending',  -- pending|claimed|submitted|done|failed
    attempts      int    NOT NULL DEFAULT 0,
    batch_ref     text,                   -- Anthropic batch id once submitted
    created_by    bigint NOT NULL REFERENCES event(id)  -- provenance
);
CREATE INDEX ON timer (due_at) WHERE status = 'pending';
-- Worker: SELECT ... WHERE status='pending' AND due_at <= now()
--         ORDER BY due_at FOR UPDATE SKIP LOCKED LIMIT 20;
```

One caveat from queue-on-Postgres experience: completed timer rows churn (UPDATE-heavy) unlike the append-only event table, so let autovacuum run and periodically archive/delete old done rows.

## 5. Partitioning: skip it, with a tripwire

Industry guidance converges on **~100M rows or 50–100GB** as the partition-consideration threshold, with under 10GB actively unsuitable — small partitioned tables pay planning and routing overhead for zero benefit ([fklezin, When to Consider Postgres Partitioning](https://medium.com/@fklezin/when-to-consider-postgres-partitioning-in-2026-71189ac88728), [TigerData](https://www.tigerdata.com/learn/when-to-consider-postgres-partitioning), [Postgres docs](https://www.postgresql.org/docs/current/ddl-partitioning.html)). Alpha produces ~3.3M rows/year — **decades from the threshold**. Even at full 10k-player worst case (~1.1B rows/year) the main partitioning payoffs (dropping old partitions, VACUUM windows) barely apply to an append-only canon you never delete.

Tripwires to revisit: sustained >500k events/day, events table >50GB, or VACUUM/REINDEX runs exceeding ~30 minutes. Migration later is a standard online operation (create partitioned table, backfill, swap), so nothing needs pre-building — just keep `world_time`/`recorded_at` NOT NULL so a future range key exists.

## 6. Framework call: BUILD on plain psycopg3 — skip the frameworks

Evaluated the one serious Python candidate, John Bywater's `eventsourcing` (v9.6, actively maintained, 5,400+ commits, Postgres via psycopg3) ([GitHub](https://github.com/pyeventsourcing/eventsourcing), [docs](https://eventsourcing.readthedocs.io/en/stable/topics/persistence.html)). Verified from its source ([postgres.py](https://raw.githubusercontent.com/pyeventsourcing/eventsourcing/main/eventsourcing/postgres.py)), three disqualifiers for Everquill specifically:

1. **`state bytea`** — events are opaque serialized blobs. This kills SQL-queryable payloads, which lazy rumor propagation and claim derivation depend on. You'd end up building a parallel queryable copy of every event, defeating the point.
2. **`LOCK TABLE ... IN EXCLUSIVE MODE` on every insert** (to keep notification IDs in commit order) plus `autovacuum_enabled=false` on the events table — reasonable framework trade-offs, but they're global decisions made for you, and the xid8 predicate achieves the same guarantee without serializing writers.
3. **Domain-model coupling** — its value is `Aggregate` base classes, `@event` decorators, and transcoders. Everquill's deterministic referee engine IS the aggregate logic and already exists; the framework's largest component is dead weight here.

Also considered and rejected: **message-db** (Eventide's Postgres event store — solid, but brings its own conventions and stored-procedure API for less code than the hand-rolled version), **Marten** (.NET only), **Kafka/EventStoreDB/Kurrent** (absurd at 35 events/sec; and losing same-transaction projections is a real regression).

What "build" actually costs, per the sources that built it: the store is a table, two constraints, an `append(stream_id, expected_version, events[])` function that catches the unique violation, a replay query, and the checkpoint loop — **roughly 200–400 lines of psycopg3** ([kspeakman](https://dev.to/kspeakman/event-storage-in-postgres-4dk2), [breadcrumbscollector](https://breadcrumbscollector.tech/implementing-event-sourcing-in-python-part-2-robust-event-store-atop-postgresql/)). The hard parts of Everquill (referee determinism, claim schema, context assembly) are domain logic no framework ships.

**Snapshots: also skip for now.** Character streams replay in milliseconds at hundreds-to-thousands of events; "well-designed streams do not accumulate large numbers of events" and snapshots are a later optimization behind the same replay interface ([kspeakman](https://dev.to/kspeakman/event-storage-in-postgres-4dk2)). Since Tier-1 projections keep current stats materialized anyway, full replay is only for rebuilds and audits.

## 7. Validation of committed decisions (this lens)

- **Event-sourced canon on Postgres: CONFIRMED** — and strengthened: same-transaction projections are the single biggest practical win of Postgres over dedicated event stores, and Everquill's decisions (2), rebuildable projections, depend on it.
- **Claim store as projection: CONFIRMED**, with one refinement — claims should carry the `event.id` of their source deed(s) as provenance FKs, making "wrong intel is causal and reproducible" a joinable property, not a convention.
- **Lazy rumor propagation: CONFIRMED** as the right consumer shape — it's a Tier-2 checkpointed reader over `(location_id, world_time)` indexes; needs the xid8-safe read predicate to never miss a deed.
- **World clock via timer table: CONFIRMED**, upgraded to explicit outbox semantics for Batch API submissions.
- **One challenge:** the architecture doc says "cached per region-epoch, never eager fan-out" — correct, but ensure cache invalidation keys off `event.id` high-water marks per region, not wall-clock, or a late-committing deed can be permanently excluded from an epoch cache (same lost-event anomaly, one level up).

## Sources

- kspeakman, Event Storage in Postgres — https://dev.to/kspeakman/event-storage-in-postgres-4dk2
- eugene-khyst, postgresql-event-sourcing (xid8 ordering, checkpointed subscriptions) — https://github.com/eugene-khyst/postgresql-event-sourcing
- SoftwareMill, Implementing event sourcing using a relational database — https://softwaremill.com/implementing-event-sourcing-using-a-relational-database/
- Oskar Dudycz, Guide to Projections and Read Models — https://event-driven.io/en/projections_and_read_models_in_event_driven_architecture/
- Tim Derzhavets, Production-Ready Event Store in PostgreSQL — https://dev.to/tim_derzhavets/building-a-production-ready-event-store-in-postgresql-schema-design-projections-and-replay-25o8
- breadcrumbscollector, Robust event store atop PostgreSQL (Python) — https://breadcrumbscollector.tech/implementing-event-sourcing-in-python-part-2-robust-event-store-atop-postgresql/
- pyeventsourcing/eventsourcing (README, persistence docs, postgres.py source) — https://github.com/pyeventsourcing/eventsourcing ; https://eventsourcing.readthedocs.io/en/stable/topics/persistence.html ; https://raw.githubusercontent.com/pyeventsourcing/eventsourcing/main/eventsourcing/postgres.py
- fklezin, When to Consider Postgres Partitioning in 2026 — https://medium.com/@fklezin/when-to-consider-postgres-partitioning-in-2026-71189ac88728
- TigerData, When to Consider Postgres Partitioning — https://www.tigerdata.com/learn/when-to-consider-postgres-partitioning
- PostgreSQL docs, Table Partitioning — https://www.postgresql.org/docs/current/ddl-partitioning.html
- DB Pro, PostgreSQL FOR UPDATE SKIP LOCKED — https://www.dbpro.app/blog/postgresql-skip-locked
- Netdata, Using FOR UPDATE SKIP LOCKED for Queue Workflows — https://www.netdata.cloud/academy/update-skip-locked/
- AmineDiro, Implementing a Postgres job queue — https://aminediro.com/posts/pg_job_queue/
- TigerData, Handling Billions of Rows in PostgreSQL — https://www.tigerdata.com/blog/handling-billions-of-rows-in-postgresql