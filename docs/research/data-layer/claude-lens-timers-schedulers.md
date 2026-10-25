# Everquill World Clock — Durable Timers & Scheduled Jobs Report

**Lens:** patterns that don't lose work. Verdict up front: your architecture is well-shaped for this. Event-sourced canon + deterministic engine means the timer system gets its hardest property — "late firing produces identical outcomes" — almost for free, *if* you follow one discipline: timers are domain data in Postgres, not in-process schedules, and outcome seeds derive from the timer identity, never from processing wall-clock.

---

## 1. Core design decision: timer table + sweeper, not a cron scheduler

**State-based, not edge-based.** The Streamer Pipeline lesson generalized: a cron that "fires the 14:00 event" loses work when it's down at 14:00. A sweeper that asks *"what is due?"* against a durable table is inherently catch-up-safe — downtime just means the next sweep finds more rows. Everything below follows from this.

**Do not model domain timers as library jobs.** Job libraries treat scheduled tasks as infrastructure with grace-window semantics — procrastinate's periodic tasks explicitly *drop* runs more than 10 minutes late ([procrastinate cron docs](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cron.html)). That is correct for a metrics refresh and catastrophically wrong for "Mira's sword-training block completes Tuesday." Domain timers get their own table, part of the same schema as the deed log.

### Timer table

```sql
CREATE TABLE timer (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind          TEXT NOT NULL,          -- training|research|travel|pressure_front|exam
  subject_id    UUID NOT NULL,          -- character / region / front
  due_at        TIMESTAMPTZ NOT NULL,   -- real-world due time
  world_due     BIGINT NOT NULL,        -- world-clock timestamp the outcome is stamped with
  payload       JSONB NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',  -- pending|fired|cancelled
  created_event_id BIGINT NOT NULL REFERENCES event(id),  -- provenance
  fired_event_id   BIGINT REFERENCES event(id),
  attempts      INT NOT NULL DEFAULT 0
);
CREATE INDEX timer_due_pending ON timer (due_at) WHERE status = 'pending';
```

The partial index is the load-bearing piece: fired timers leave the index, so the sweep query stays O(due rows) forever regardless of history ([partial index design](https://oneuptime.com/blog/post/2026-01-30-partial-index-design/view), [Postgres docs: partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html)).

### Sweep + fire transaction (the whole worker, essentially)

```sql
BEGIN;
SELECT * FROM timer
WHERE status = 'pending' AND due_at <= now()
ORDER BY due_at, id          -- deterministic causal ordering
LIMIT 50
FOR UPDATE SKIP LOCKED;

-- per timer, in the SAME transaction:
--   1. run deterministic resolution (seeded 2d6; seed = f(timer_id, created_event_id))
--   2. INSERT INTO event (..., world_ts = world_due,
--        idempotency_key = 'timer:' || timer.id)
--      ON CONFLICT (idempotency_key) DO NOTHING;
--   3. UPDATE timer SET status='fired', fired_event_id=... WHERE id=...;
--   4. INSERT INTO notify_outbox (...);   -- push handled later, separately
COMMIT;
```

`FOR UPDATE SKIP LOCKED` gives atomic, race-free claiming — two workers never grab the same row, and a crashed worker's transaction rolls back, returning the timer to pending automatically ([Netdata: SKIP LOCKED queue workflows](https://www.netdata.cloud/academy/update-skip-locked/), [dbpro: the one-liner job queue](https://www.dbpro.app/blog/postgresql-skip-locked)). Because timer firing is pure DB + deterministic compute (no external calls), the hold-transaction-open variant is correct and simplest: crash recovery is Postgres rollback, no lease/visibility-timeout machinery needed.

**Two non-negotiable determinism rules:**
1. **Seed from identity, not from clock.** Dice seed = hash(timer_id, created_event_id [, canon RNG root]). A timer fired 3 hours late after downtime produces bit-identical outcomes. This is the same property that makes canon savescum-proof, extended to downtime-proof.
2. **Stamp events at `world_due`, not processing time.** Late real-world processing delays *notification only*; in world time the training block ended exactly when it ended. Projections rebuild identically whether the worker was up or down.

---

## 2. Library choice: procrastinate as harness, plain SKIP LOCKED for timers

You're Python + Postgres, so the field is: hand-rolled SKIP LOCKED loop, [procrastinate](https://github.com/procrastinate-org/procrastinate), or (Node-world reference point) [pg-boss](https://github.com/timgit/pg-boss). pg-boss validates the pattern — SKIP LOCKED, retries with exponential backoff, dead-letter queues, cron via a 30-second timekeeper — but it's Node, so it's a design reference, not a candidate.

**Recommendation: procrastinate for infrastructure jobs, raw SKIP LOCKED for the domain timer sweep.**

- **Procrastinate runs**: the sweep tick (periodic task, every 15–30s), the batch submitter, the batch poller, the outbox/push flusher, rumor-cache invalidation jobs. You get retries with backoff, LISTEN/NOTIFY wake-up, periodic scheduling, and transactional enqueue (defer a job in the same transaction as the state change — if the commit rolls back, the job never existed) without hand-rolling any of it ([procrastinate docs](https://procrastinate.readthedocs.io/), [LeanIX production writeup](https://engineering.leanix.net/blog/task-queues-in-python/)). Its multi-worker periodic-task coordination guarantees each tick is deferred once per period even with several workers ([cron docs](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cron.html)).
- **The sweep task itself** claims timer rows directly with the query above. The 10-minute periodic cutoff doesn't matter here: if every sweep tick during a 3-hour outage is dropped, the *first tick after restart* finds all overdue timers anyway. State-based wins.
- Procrastinate's `queueing_lock` ("only one job with this lock may be *todo*") is useful for singleton jobs like "one batch-submitter run at a time" ([queueing locks](https://procrastinate.readthedocs.io/en/stable/howto/advanced/queueing_locks.html)) — but note the known failure mode: a worker dying mid-job strands the lock, so keep a stalled-job reaper ([issue #1446](https://github.com/procrastinate-org/procrastinate/issues/1446)).

**Volume check:** alpha = tens of players × low hundreds of events/day ≈ single-digit events/minute. Design headroom 10k players ≈ 30–50 events/sec average, timer firings a fraction of that. Postgres queues are comfortable well past this — RudderStack pushed Postgres queues to ~100k events/sec with tuning ([RudderStack scaling lessons](https://www.rudderstack.com/blog/scaling-postgres-queue/)); you are 3–4 orders of magnitude below where queue-on-Postgres becomes a conversation. No Redis, no separate broker, ever, at this scale — and transactional enqueue with your canon writes is a correctness feature brokers can't give you.

**Hygiene** (cheap now, annoying later): fired timers and completed procrastinate jobs are UPDATE-churn; keep the partial indexes, periodically delete/archive fired timer rows (the deed log is the permanent record — timer rows are operational scaffolding), and if tables grow hot, set per-table `autovacuum_vacuum_scale_factor` below the 20% default ([PlanetScale: keeping a Postgres queue healthy](https://planetscale.com/blog/keeping-a-postgres-queue-healthy), [Microsoft: Postgres as a job queue consequences](https://techcommunity.microsoft.com/blog/adforpostgresql/potential-consequences-of-using-postgres-as-a-job-queue/4514332)).

**Topology on Railway:** one dedicated worker service (separate from web/bot), single process at alpha, asyncio concurrency inside. SKIP LOCKED makes adding a second process safe whenever needed — no code change. Nothing schedule-shaped lives in process memory; a Railway redeploy mid-sweep loses nothing because pending rows survive and locks release on disconnect.

---

## 3. Idempotency rules (the exactly-once contract)

SKIP LOCKED delivery is **at-least-once**; exactly-once is achieved at the *effect* layer, not the delivery layer ([Netdata](https://www.netdata.cloud/academy/update-skip-locked/), [idempotency in distributed systems](https://medium.com/javarevisited/idempotency-in-distributed-systems-preventing-duplicate-operations-85ce4468d161)). Rules, in priority order:

1. **Every timer firing has an idempotency key** (`timer:{id}`) with a UNIQUE constraint on the event log. Double-processing becomes a no-op INSERT conflict, never a double event. This is your exactly-once completion semantic.
2. **Claim, resolve, append, and mark-fired in one transaction.** Never mark a timer fired in a different transaction from the event append. Crash between them is then impossible by construction.
3. **No external side effects inside the firing transaction.** Push notifications, batch submissions, anything HTTP goes through an outbox row committed with the event, flushed by a separate job. Canon never blocks on, or partially commits around, an external call.
4. **External calls use the lease pattern, not hold-transaction.** Batch submission holds no DB transaction across HTTP; it reserves work rows (status flip with lease/`locked_until`), calls out, records the result. If it dies mid-call, the reaper re-leases and the idempotency key (below) absorbs the duplicate.
5. **Deterministic `custom_id` everywhere an external system echoes work back.** Batch requests carry `custom_id = narration_request.id`; result ingestion inserts keyed on it with a unique constraint, so re-ingesting a results file (or ingesting after a duplicate submission) is harmless.
6. **Timers are created transactionally with their causing event.** "Start training" appends the deed event AND inserts the timer in one commit — no orphan timers, no evented-but-untimed training.
7. **Cancellation is a status transition guarded by `WHERE status='pending'`**, racing cleanly with firing: exactly one of {fired, cancelled} wins, decided by the row lock.

---

## 4. Anthropic Batch API integration (timed narration lane)

Verified against the [official batch processing docs](https://platform.claude.com/docs/en/build-with-claude/batch-processing): batches are limited to 100k requests or 256 MB; most complete **under 1 hour**; hard **24-hour expiry** (`result_type: expired`, not billed, no result); results downloadable for **29 days**; per-request results are `succeeded | errored | canceled | expired`; completion detection in the official docs is **polling** `processing_status` until `ended`. (Third-party writeups describe a per-batch `webhook_url` — this is *not* in the official docs I fetched; treat webhooks as unverified and build on polling, which is fully sufficient here. Poller every 60s is standard practice: [agentbus batch guide](https://agentbus.sh/posts/how-to-use-the-anthropic-batch-api-for-high-volume-processing/).)

**Critical structural rule: canon never waits for the LLM.** When a timer fires, the deterministic engine resolves the mechanical outcome and appends the event immediately. Narration is decoration on top of settled canon. This decouples your timer SLAs from Anthropic's 24-hour ceiling entirely — a batch expiry can delay *prose*, never *truth*.

Two narration lanes:
- **Interactive lane** — player online, waiting: synchronous Messages API.
- **Ambient lane** — timed results, offline players, background world texture: Batch API at 50% discount. `narration_request` rows accumulate; the submitter groups them (every ~15 min or at N pending — your volumes make the 100k/256MB caps irrelevant) and submits one batch, persisting the `batch_id` row *before* flipping request rows to `submitted`.

**Batch state machine** (own table: `batch_submission(batch_id, status, submitted_at, ...)`):
- Poller task (every 60s) checks all non-terminal batches; on `ended`, streams the results file, upserts narrations by `custom_id`, marks requests done, enqueues push outbox rows.
- `expired` requests: resubmit once into the next batch; if a player is now online and blocked on it, escalate to the sync API. Deterministic `custom_id` + unique ingestion means an escalation racing a late resubmission cannot double-apply.
- **Timer/SLA interaction rule:** anything player-gating due in **< 24h + slack** never rides *only* on Batch. In practice, since most batches finish <1h, batch is fine for timers ≥ a few hours out, with the expiry-escalation path as the safety net. Anthropic explicitly warns expiries increase under load ([docs](https://platform.claude.com/docs/en/build-with-claude/batch-processing)) — track your expiry rate as an alert metric.
- The 29-day results window is a non-issue if the poller ingests promptly; it also means any downtime shorter than 29 days can still recover every completed batch.

---

## 5. Downtime-recovery policy (fire late, not never)

Per class — the classes genuinely need different rules, and conflating them is the classic mistake ([Quartz misfire instructions](https://androidexperto.com/quartz-scheduler-misfire-instructions-explained/) is the canonical taxonomy: fire-now vs skip vs collapse-many-into-one):

| Class | Policy | Why |
|---|---|---|
| **Domain timers** (training, research, travel, exams) | Fire **all** overdue, in `(due_at, id)` order, stamped at `world_due`. **No grace cutoff, ever.** | Late in real time, on time in world time. Deterministic seeds make late == on-time. Ordering preserves causality (a travel arrival that enables an exam sitting must fire first). |
| **Pressure fronts / continuous world processes** | One catch-up evaluation advancing by elapsed world time (store `last_evaluated_at` per front), not N replayed ticks. | Delta-time lazy evaluation, exactly the idle-game "welcome back" pattern ([Tideward offline progression](https://tideward.app/offline-progression/), [delta-time mechanics](https://www.geekextreme.com/idle-games-offline-progression-math/)) — and it's the same philosophy as your lazy rumor propagation (decision 4). Server-side, deterministic, recalculable. |
| **Infra periodic tasks** (batch poller, sweeps, reapers) | Skip missed occurrences; just run now. | They're state-based scans — self-healing by nature. Running the poller once now covers everything 40 missed runs would have. |
| **Batch submissions** | On startup: poll every non-terminal `batch_submission`; ingest `ended`, resubmit/escalate `expired`. | Covers the crash-during-outage window; 29-day results retention makes this robust to any realistic outage. |
| **Push notifications** | Send late but **coalesced**: one digest per player ("While you were away: training complete, caravan arrived") instead of N stale pushes. Never silently drop. | Avoids the post-outage notification storm; pushes are non-canon, at-most-once delivery is acceptable ([APNs/FCM delivery internals](https://blog.clix.so/how-push-notification-delivery-works-internally/)). |

**Startup order:** reconcile batches → fire overdue timers (ordered) → advance fronts → flush outbox (coalescing). Each step idempotent, so a crash *during recovery* just restarts recovery.

**One catch-up guardrail:** cap the firing loop's batch size (the `LIMIT 50`) and loop — after a multi-day outage you drain steadily rather than in one giant transaction. Collapse-style guardrails against runaway catch-up are standard ([hermes-agent catchup design](https://github.com/NousResearch/hermes-agent/issues/27327)) but apply them only to the recurring classes; domain timers always all fire.

**Offline players are not a special case.** A player returning after a week triggers nothing retroactive — their timers already fired at world-time, events are in the log, the Context Assembler just reads current projections. The push digest is the only "welcome back" machinery needed. This is the payoff of doing offline progression server-side against durable timestamps rather than simulating in the background ([server-side offline progression](https://edvins.io/rebuilding-the-welcome-back-mechanic-from-idle-games-in-react)).

---

## 6. Challenges to the committed architecture (lens-specific)

1. **Decision 5 says "timed results via Anthropic Batch API" — soften to "ambient-lane narration via Batch."** As committed, it reads like timer *outcomes* depend on batch round-trips. They must not: the 24h expiry ceiling and load-dependent slowdowns would put canon at the mercy of Anthropic's queue. Engine resolves at fire time; Batch only writes prose afterward.
2. **Add `world_due` as a first-class column now.** The real-time/world-time distinction is what makes the whole recovery policy coherent; retrofitting it after events exist with processing-time stamps would poison determinism.
3. **Exams need the timer-chain pattern:** an exam is a scheduled *future* deed whose participants are determined at fire time from projections (who's enrolled, who's alive, who arrived). Fire order (`due_at, id`) plus transactional timer creation makes "died the day before the exam" resolve correctly with zero special-casing — the death event seals first, the exam fire reads the projection.
4. **Pressure fronts as lazy processes, not tick timers.** If you schedule a front as repeating 6-hour tick timers you inherit the replay-N-ticks problem; model it as `last_evaluated_at` + evaluate-on-demand (on sweep, on scene entry, on downtime recovery) and it composes with lazy rumor propagation instead of fighting it.

## Sources

- pg-boss (SKIP LOCKED, retries, cron timekeeper): [GitHub](https://github.com/timgit/pg-boss), [docs](https://timgit.github.io/pg-boss/)
- Procrastinate: [GitHub](https://github.com/procrastinate-org/procrastinate), [docs](https://procrastinate.readthedocs.io/), [periodic tasks / 10-min late cutoff](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cron.html), [queueing locks](https://procrastinate.readthedocs.io/en/stable/howto/advanced/queueing_locks.html), [stalled-lock issue #1446](https://github.com/procrastinate-org/procrastinate/issues/1446), [LeanIX production experience](https://engineering.leanix.net/blog/task-queues-in-python/)
- SKIP LOCKED semantics & at-least-once: [Netdata academy](https://www.netdata.cloud/academy/update-skip-locked/), [dbpro one-liner job queue](https://www.dbpro.app/blog/postgresql-skip-locked), [AmineDiro pg job queue](https://aminediro.com/posts/pg_job_queue/), [Solid Queue / UPDATE SKIP LOCKED](https://www.bigbinary.com/blog/solid-queue)
- Partial indexes for job tables: [OneUptime partial index design](https://oneuptime.com/blog/post/2026-01-30-partial-index-design/view), [PostgreSQL docs](https://www.postgresql.org/docs/current/indexes-partial.html)
- Queue health / bloat at scale: [RudderStack 100k events/sec](https://www.rudderstack.com/blog/scaling-postgres-queue/), [PlanetScale queue health](https://planetscale.com/blog/keeping-a-postgres-queue-healthy), [MS Postgres-as-queue consequences](https://techcommunity.microsoft.com/blog/adforpostgresql/potential-consequences-of-using-postgres-as-a-job-queue/4514332)
- Misfire/catch-up policy taxonomy: [Quartz misfire instructions](https://androidexperto.com/quartz-scheduler-misfire-instructions-explained/), [hermes-agent catchup option](https://github.com/NousResearch/hermes-agent/issues/27327), [APScheduler misfire grace](https://github.com/agronholm/apscheduler/issues/146)
- Anthropic Batch API (official — 24h expiry, 29-day results, polling, result types, 100k/256MB): [platform.claude.com batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing); practical guides: [agentbus](https://agentbus.sh/posts/how-to-use-the-anthropic-batch-api-for-high-volume-processing/), [Temporal integration pattern](https://stevekinney.com/writing/anthropic-batch-api-with-temporal)
- Idle-game offline progression (delta-time, server-side): [Tideward](https://tideward.app/offline-progression/), [GeekExtreme delta-time](https://www.geekextreme.com/idle-games-offline-progression-math/), [Edvins welcome-back mechanic](https://edvins.io/rebuilding-the-welcome-back-mechanic-from-idle-games-in-react)
- Push delivery (APNs/FCM, at-most-once realities): [Clix delivery internals](https://blog.clix.so/how-push-notification-delivery-works-internally/), [DesignGurus 50M-device architecture](https://designgurus.substack.com/p/push-notification-architecture-apns)
- Idempotency/dedup patterns: [Suraj Sharma on duplicate jobs](https://medium.com/@surajs78/why-is-my-job-running-twice-understanding-idempotency-and-deduplication-in-distributed-systems-d56edbcad051), [GitLab idempotent Sidekiq jobs](https://docs.gitlab.com/development/sidekiq/idempotent_jobs/)