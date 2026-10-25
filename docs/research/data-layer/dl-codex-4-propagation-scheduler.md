# Everquill: Lazy Rumor Propagation and World-Clock Scheduling

## Executive recommendation

Everquill should use two related forms of simulation level-of-detail:

1. **Rumors:** analytically derive each region’s belief state only when requested. Evaluate deeds against graph distance, arrival time, notoriety decay, and deterministic distortion; cache the result by region and world-time epoch. Never create `(deed, NPC)` propagation records.
2. **NPC knowledge:** begin with the region projection, then apply the NPC’s direct evidence, social channels, faction biases, and deterministic exposure filter on demand.
3. **World time:** represent all training, research, travel, exams, and pressure fronts as durable Postgres timer occurrences against one authoritative world clock.
4. **Delivery:** execute timers at least once but make their effects exactly-once through unique event-log idempotency keys.
5. **LLM work:** pre-generate presentation through the batch API when possible, but make the rules engine commit the result independently. A late or missing batch must never delay world state.

This preserves the central rule: NPC decisions consume **KNOWN claims**, while the deterministic resolver still uses TRUE state.

---

## 1. Lazy propagation model

### 1.1 Required data

A deed event needs enough structured public material to derive rumors without exposing true sheets:

```text
deed_id
event_seq
world_id
effective_world_at
origin_region_id
travel_graph_version
deed_type
rumor_seed {
    public_actor,
    public_action,
    public_target,
    public_outcome,
    public_location,
    quantities_or_bands,
    visible_consequences
}
base_notoriety          # 0–100
sensationalism          # 0.0–0.75
witness_count
witness_quality         # normalized 0.0–1.0
direct_witness_ids
rules_version
```

`rumor_seed` is the potentially observable account, not the complete true event. Hidden stats, motives, undiscovered participants, and sealed facts must never enter the rumor pipeline.

Supporting versioned data:

```text
travel_edge(from_region, to_region, carriage_days, graph_version)
region_profile(region_id, hear_threshold, forget_threshold,
               archive_strength, channels, profile_version)
propagation_rules(rules_version, half_lives, mutation_tables, algorithm_version)
```

Roads should be directed where appropriate. Riverboats, mountain passes, sea routes, borders, and seasonal roads can therefore have different weights in each direction.

### 1.2 Distance and arrival

For deed \(d\) and destination region \(r\):

\[
D(d,r)=\operatorname{shortestPath}_{G_d}(d.origin,r)
\]

where each edge weight is measured in **carriage-days**, and \(G_d\) is the immutable graph version recorded on the deed.

Use Dijkstra for positive weights. Running it on the reversed graph from the requested destination computes distances from every possible origin in one pass.

\[
arrival(d,r)=d.time + D(d,r)\text{ world-days}
\]

If no route exists, distance is infinite and the ordinary rumor never arrives. Magical communication, official couriers, letters, or eyewitness travel should be separate channels/events rather than exceptions buried inside the distance formula.

Pinning deeds to an immutable graph version makes replay deterministic. A later road opening affects later deeds. If bridge closures must interrupt rumors already in transit, that can later be upgraded to time-dependent shortest paths, but it is unnecessary complexity for the first implementation.

### 1.3 Notoriety, reach, and forgetting

Use half-life decay because it is inspectable and easy to tune.

For deed \(d\):

\[
B_d=n_d \times q_d \times (1+s_d)
\]

- \(n_d\): base notoriety, 0–100.
- \(q_d\): witness/corroboration multiplier, initially 0.5–1.5.
- \(s_d\): sensationalism, initially 0–0.75.

At first arrival:

\[
S_{arrival}=B_d \times 2^{-D/H_D}
\]

At region epoch time \(\tau\):

\[
S(d,r,\tau)=S_{arrival}
\times 2^{-(\tau-arrival)/H_T}
\]

- \(H_D\): distance half-life in carriage-days.
- \(H_T\): memory half-life in world-days.

The region has heard the rumor only if:

```text
τ >= arrival
and S_arrival >= region.hear_threshold
```

It still actively remembers the rumor if:

```text
S(d, r, τ) >= region.forget_threshold
```

Archives, guild registries, temples, and courts can lower the forgetting threshold or make selected categories permanent. That remains a pure rule: no separate “region learned deed” row is required.

Reasonable starting parameters:

| Deed class | Distance half-life | Memory half-life |
|---|---:|---:|
| Minor/local | 2 carriage-days | 7 world-days |
| Public violence, guild result | 6 carriage-days | 30 world-days |
| Major political or supernatural deed | 15 carriage-days | 180 world-days |
| Epochal disaster | 30 carriage-days | Effectively permanent in archives |

Initial regional thresholds could be `hear = 8`, `forget = 3`, modified by literacy, trade traffic, censorship, isolation, or official recordkeeping. These are balance parameters, not schema commitments.

This model produces the desired behavior naturally:

- High-notoriety deeds travel farther.
- Remote regions receive them later.
- Minor stories disappear.
- Famous deeds become persistent history.
- Sensational deeds spread farther but can also distort more.

### 1.4 Deterministic distortion

Distortion must be structured, reproducible, and unable to invent mechanical truth.

Seed a versioned, cross-platform PRNG with:

```text
seed = first_128_bits(
    SHA256(canonical_uuid(deed_id) || canonical_uuid(region_id))
)
```

Do not use Python’s process-randomized `hash()`. The mutation algorithm and candidate ordering must also be versioned.

A proposed mutation probability is:

\[
p=\operatorname{clamp}\left(
0.10
+0.55(1-2^{-D/H_D})
+0.20(1-q)
+0.20s
-0.20c,\,
0,\,
0.90
\right)
\]

where:

- \(q\) is normalized witness quality.
- \(c\) is normalized independent corroboration.
- \(s\) is sensationalism.

For each whitelisted field, consume the next deterministic PRNG value. If it falls below the field’s mutation probability, apply one type-safe mutation:

- Exact location → neighboring landmark or broader region.
- Exact quantity → adjacent quantity band.
- Named actor → title, faction, or plausible regional alias.
- Outcome → adjacent severity wording, never a mechanical state change.
- Motive → culturally plausible attributed motive.
- Certainty/provenance → “a merchant swears” versus “the guild records.”
- Target identity → category substitution only where the public account was ambiguous.

The regional variant should be frozen at its first-arrival epoch. Later deterioration should come from an explicit retelling, propaganda, forged record, or counter-rumor deed—not from silently changing the same remembered story as time passes.

Every distorted claim retains:

```text
source_deed_id
source_kind = rumor
region_id
first_arrival_epoch
mutation_algorithm_version
mutation_codes[]
```

That gives debugging without revealing the true version to the client.

### 1.5 Region epochs

Use a fixed rumor epoch, initially **six world-hours**:

```text
epoch(T) = floor(T / 6 world-hours)
τ = epoch_start(epoch(T))
```

Regional circulation changes only at epoch boundaries. A deed at 01:00 can be directly known by witnesses immediately, but it enters the town’s ambient rumor pool at 06:00 or later, subject to travel time.

This quantization is valuable because it makes a cache entry exact rather than approximately stale:

```text
(region_id, epoch_id, graph_version_set,
 rules_version, region_profile_version)
```

It also gives the fiction a natural rhythm: morning markets, evening taverns, courier arrivals, and guild notices.

### 1.6 Pure region evaluation

```python
EPOCH = world_hours(6)

def region_knowledge(region_id, world_time):
    epoch_id = floor(world_time / EPOCH)
    tau = epoch_id * EPOCH

    versions = active_propagation_versions(region_id, tau)
    key = (
        region_id,
        epoch_id,
        versions.rules,
        versions.region_profile,
        versions.algorithm,
    )

    cache = load_region_cache(key)
    highwater = deed_log_highwater()

    if cache is not None:
        delta = rumor_affecting_events(cache.deed_seq, highwater)

        if not any(
            event_can_change_region(event, region_id, tau, cache.payload)
            for event in delta
        ):
            advance_cache_watermark(key, highwater)
            return cache.payload

    claims = []

    # Candidate index is rebuildable from the deed log. It is not truth.
    deeds = candidate_deeds(
        effective_at_or_before=tau,
        not_globally_expired_at=tau,
    )

    # Normally only a few immutable graph versions are represented.
    distance_maps = {}

    for deed in deeds:
        graph_version = deed.travel_graph_version

        if graph_version not in distance_maps:
            distance_maps[graph_version] = reverse_dijkstra(
                destination=region_id,
                graph_version=graph_version,
            )

        distance = distance_maps[graph_version].get(
            deed.origin_region_id,
            INFINITY,
        )

        if distance == INFINITY:
            continue

        arrival = deed.effective_world_at + world_days(distance)

        if tau < arrival:
            continue

        base = (
            deed.base_notoriety
            * witness_multiplier(deed)
            * (1.0 + deed.sensationalism)
        )

        distance_half_life, time_half_life = half_lives(deed.deed_type)
        arrival_score = base * pow(2, -distance / distance_half_life)

        profile = region_profile(region_id, tau)

        if arrival_score < profile.hear_threshold:
            continue

        current_score = arrival_score * pow(
            2,
            -(tau - arrival).world_days / time_half_life,
        )

        if (
            current_score < profile.forget_threshold
            and not profile.archives(deed.deed_type)
        ):
            continue

        variant = deterministic_mutation(
            rumor_seed=deed.rumor_seed,
            seed=(deed.deed_id, region_id),
            distance=distance,
            first_arrival_epoch=ceil(arrival / EPOCH),
            rules_version=deed.rules_version,
        )

        claims.append(
            KnowledgeClaim(
                subject=variant.subject,
                predicate=variant.predicate,
                value=variant.value,
                source_deed_id=deed.deed_id,
                source_kind="rumor",
                provenance_region=region_id,
                arrived_at=arrival,
                salience=current_score,
                mutations=variant.mutation_codes,
            )
        )

    # Preserve contradictory claims. Do not consult TRUE state to reconcile them.
    payload = sort_and_group_claims(claims)

    write_cache_compare_and_swap(
        key=key,
        deed_seq=highwater,
        payload=payload,
    )
    return payload
```

`candidate_deeds` can use a rebuildable scalar index containing each deed’s maximum possible expiry at zero distance. That eliminates ancient, low-notoriety deeds before graph evaluation without storing region fan-out.

### 1.7 NPC knowledge and action

An NPC query refines the regional projection:

```python
def npc_beliefs(npc_id, world_time):
    npc = project_npc_at(npc_id, world_time)
    regional = region_knowledge(npc.region_id, world_time)

    direct = direct_claims_from_log(
        npc_id=npc_id,
        world_time=world_time,
        sources=("witness", "conversation", "letter", "journal", "official_record"),
    )

    heard = []

    for claim in regional:
        channel = npc_channel_access(npc, claim)
        coverage = rumor_coverage(claim.salience, channel)

        # Determines exposure only; it does not alter the regional distortion.
        u = stable_hash01(claim.source_deed_id, npc_id)

        if u < coverage:
            heard.append(claim)

    return merge_beliefs(
        direct=direct,
        regional=heard,
        faction_priors=npc.faction_priors,
        preserve_contradictions=True,
    )
```

NPC policy consumes this belief set. For example, guards may arrest someone because they believe a distorted guild notice; the combat or escape resolver still evaluates against true guards, true laws, and true positions.

No NPC belief should be silently reconciled against truth. Direct evidence, official records, and rumors receive source rankings, but contradictory claims remain representable.

### 1.8 Cache invalidation rules

A region cache is a rebuildable projection, never canonical data.

| Change | Invalidation behavior |
|---|---|
| World time enters a new epoch | New cache key; old epoch remains immutable until garbage-collected. |
| New ordinary deed occurs after the current epoch start | Current regional cache remains valid; deed becomes eligible next epoch. Direct witnesses know immediately. |
| Backdated/catch-up deed has effective time at or before the epoch | Lazy high-watermark check tests whether it can reach and affect this region. Rebuild only if relevant. |
| Retraction, correction, propaganda, or supersession event | Rebuild if it references a cached deed or creates a relevant competing claim. |
| Travel graph changes | New graph version namespace; no destructive invalidation. |
| Propagation or distortion rules change | New rules/algorithm version namespace. Historical replay can retain the original version. |
| Region threshold/channel changes | New region-profile version namespace. |
| NPC moves, changes faction, reads a letter, or witnesses something | Does not invalidate the region cache; only the NPC refinement changes. |
| Cache TTL expires | Performance-only eviction; never changes semantics. |

A new deed therefore causes no writes to region or NPC caches. A cache read compares its stored deed-log sequence with the current high-water mark and examines only the delta. This is lazy invalidation rather than global invalidation.

### 1.9 Complexity

Let:

- \(N\): total deeds.
- \(V,E\): travel graph vertices and edges.
- \(C\): indexed candidate deeds for a region epoch.
- \(K\): claims surviving propagation filters.
- \(P\): NPC population.

| Operation | Complexity |
|---|---:|
| Append deed | \(O(1)\), plus explicit witness records; **no \(P\) factor** |
| Distance cache miss | \(O((V+E)\log V)\) |
| Distance cache hit | \(O(1)\) lookup per candidate |
| Candidate retrieval | \(O(\log N+C)\) with time/expiry indexes |
| Region projection miss | \(O((V+E)\log V+C)\) |
| Region projection hit | \(O(1)\) lookup plus \(O(K)\) serialization |
| NPC belief query | \(O(K+J)\), where \(J\) is direct evidence |
| Lazy new-deed validation | \(O(\Delta C)\) since cached high-watermark |
| Worst case | \(O(N+(V+E)\log V)\) if nearly every deed remains legendary |

Cache storage is proportional to **queried region-epochs**, not `deeds × regions × NPCs`.

This resembles MMO interest management—filtering state to relevant consumers rather than broadcasting everything—but the consumer here is a region-time query. Interest management is a recognized scaling technique for large distributed virtual environments. [IBM’s survey](https://research.ibm.com/publications/interest-management-for-distributed-virtual-environments-a-survey) describes the underlying relevance-filtering problem.

---

## 2. World-clock scheduler

### 2.1 Clock representation

Do not continuously increment a clock row. Anchor world time to database time:

```sql
CREATE TABLE world_clock (
    world_id             uuid PRIMARY KEY,
    world_at_anchor      bigint NOT NULL,       -- integer world seconds
    real_anchor          timestamptz NOT NULL,
    rate_ppm             integer NOT NULL DEFAULT 1000000,
    revision             bigint NOT NULL DEFAULT 0
);
```

Conceptually:

```text
world_now =
    world_at_anchor
    + elapsed_real_seconds(real_anchor, database_now)
      × rate_ppm / 1,000,000
```

A paid or earned skip:

1. Locks the world row.
2. Calculates current world time.
3. Adds the skipped duration.
4. Resets both anchors.
5. Increments the clock revision.
6. Recomputes derived wake times for that world’s pending timers.

All clocks advance together because every timer is expressed in absolute world time.

### 2.2 Timer occurrence table

```sql
CREATE TABLE world_timer (
    timer_id              uuid PRIMARY KEY,
    world_id              uuid NOT NULL REFERENCES world_clock,
    series_id             uuid NOT NULL,
    occurrence_no         bigint NOT NULL,

    kind                   text NOT NULL,
    subject_id             uuid,
    priority               smallint NOT NULL DEFAULT 100,

    started_world_at       bigint NOT NULL,
    due_world_at           bigint NOT NULL,
    wake_at                timestamptz NOT NULL, -- scheduling accelerator

    state                  text NOT NULL,        -- pending/leased/completed/retry
    payload                jsonb NOT NULL,
    rules_version          text NOT NULL,

    result_revision        integer NOT NULL DEFAULT 1,
    authoritative_spec     jsonb NOT NULL,
    presentation_spec      jsonb NOT NULL,
    presentation_spec_hash bytea NOT NULL,

    lease_owner            text,
    lease_until            timestamptz,
    attempts               integer NOT NULL DEFAULT 0,
    last_error             text,

    completed_event_id     uuid,
    created_at             timestamptz NOT NULL DEFAULT clock_timestamp(),

    UNIQUE (series_id, occurrence_no)
);

CREATE INDEX world_timer_due_idx
ON world_timer (wake_at, due_world_at, priority, timer_id)
WHERE state IN ('pending', 'retry');
```

`due_world_at` is authoritative. `wake_at` merely makes the queue indexable. The handler must recheck `due_world_at <= world_now` before committing.

An update of all pending `wake_at` values for one world after a skip is \(O(A_w)\), where \(A_w\) is that world’s active timer count. Unlike rumor fan-out, this is bounded by active scheduled work, not population or deed history.

### 2.3 Overlapping clocks

Each timer represents one semantic boundary:

- Training segment completion.
- Research completion.
- Travel arrival.
- Injury recovery.
- Disaster stage transition.
- Guild exam opening, closing, or result.
- Craft completion.

Progress labels such as “cataloguing” or “cross-referencing” should be derived from elapsed fraction on read, not implemented as frequent timers.

Character occupations are a separate constraint:

```text
training: exclusive foreground occupation
travel: exclusive position-changing occupation
research: exclusive or facility-bound according to its rules
disasters/exams: world-level and continue independently
```

The action-commit transaction must reject incompatible overlapping occupations. World-level pressure fronts continue while a character trains or travels.

### 2.4 `SKIP LOCKED` worker

PostgreSQL explicitly identifies `SKIP LOCKED` as suitable for multiple consumers of a queue-like table, while warning that it is not a general consistent-reading mechanism. That is exactly the intended use here. [PostgreSQL `SELECT` documentation](https://www.postgresql.org/docs/current/sql-select.html)

```sql
WITH picked AS (
    SELECT timer_id
    FROM world_timer
    WHERE state IN ('pending', 'retry')
      AND wake_at <= clock_timestamp()
    ORDER BY wake_at, due_world_at, priority, timer_id
    FOR UPDATE SKIP LOCKED
    LIMIT 50
)
UPDATE world_timer AS t
SET state       = 'leased',
    lease_owner = :worker_id,
    lease_until = clock_timestamp() + interval '2 minutes'
FROM picked
WHERE t.timer_id = picked.timer_id
RETURNING t.*;
```

The claim transaction ends immediately. It must not remain open during rule evaluation, network calls, or LLM generation.

Expired lease recovery:

```sql
UPDATE world_timer
SET state       = 'retry',
    lease_owner = NULL,
    lease_until = NULL
WHERE state = 'leased'
  AND lease_until < clock_timestamp();
```

Retries use capped exponential backoff. A repeatedly failing timer raises an alert but is never silently dead-lettered or marked completed.

### 2.5 Exactly-once effect over at-least-once execution

The idempotency key is the logical occurrence, not the worker attempt:

```text
timer:<series_id>:<occurrence_no>
```

Completion transaction:

```python
def complete_timer(timer):
    with transaction():
        # Serializes causally interacting events inside one world.
        lock_world_row(timer.world_id)

        if earlier_unfinished_timer_exists(
            world_id=timer.world_id,
            order=(timer.due_world_at, timer.priority, timer.timer_id),
        ):
            release_for_retry(timer)
            return

        assert timer.due_world_at <= authoritative_world_now(timer.world_id)

        event = insert_event(
            event_type="timer_completed",
            effective_world_at=timer.due_world_at,
            recorded_at=database_now(),
            idempotency_key=f"timer:{timer.series_id}:{timer.occurrence_no}",
            payload=deterministic_completion_payload(timer),
            on_conflict="do_nothing",
        )

        if event.was_inserted:
            update_rebuildable_projections(event)
            enqueue_notification_outbox(event)
            materialize_next_occurrence_if_recurring(timer)

        mark_timer_completed_from_existing_or_new_event(timer)
```

The event log needs a unique constraint on `idempotency_key`. `INSERT ... ON CONFLICT DO NOTHING` provides the atomic duplicate barrier. [PostgreSQL `INSERT` documentation](https://www.postgresql.org/docs/current/sql-insert.html)

If a worker crashes after inserting the event but before changing the timer status, the next attempt encounters the existing event and repairs the timer row without applying the effect again.

Notifications, analytics, and external messages should use an outbox keyed by the completion event ID. Never perform those side effects directly inside the timer transaction.

### 2.6 Catch-up after downtime

The contract should be:

> A missed consequential timer fires late, never disappears, and never applies twice.

On worker startup:

1. Reclaim expired leases.
2. Scan `wake_at <= now`.
3. Process due occurrences in deterministic world-time order.
4. Preserve `effective_world_at = original due_world_at`.
5. Record actual recovery time separately as `recorded_at`.

Policies by timer type:

| Timer type | Catch-up behavior |
|---|---|
| One-shot research/training/travel | Complete once immediately. |
| Exam or disaster occurrence | Execute every missed consequential occurrence in order. |
| Recurring fixed schedule | Derive the next due time from the previous scheduled time, not late completion time. |
| Cosmetic progress update | Do not enqueue; derive from elapsed time. |
| Large backlog | Drain in bounded transactions with cross-world fairness; do not semantically coalesce irreversible events. |

For example, if the service is down across an exam and a disaster stage:

```text
exam_opened at day 90
disaster_stage_2 at day 91
exam_closed at day 92
```

Those events are committed in that order with their original effective dates, even if all are recorded on day 93.

Google’s distributed-cron analysis similarly emphasizes persistent launch identity, tracking scheduled time, and either idempotent external operations or unambiguous lookup after partial failure. [Google SRE: Distributed Periodic Scheduling](https://sre.google/sre-book/distributed-periodic-scheduling/)

### 2.7 Batch LLM integration

The batch API must be treated as an opportunistic pre-generation path, not as the timer’s authority. Anthropic documents that Message Batches can take up to 24 hours, that results may be returned out of request order, and that `custom_id` should be used for correlation. Batch processing is priced at 50% of standard API usage. [Anthropic batch guide](https://platform.claude.com/docs/en/build-with-claude/batch-processing), [Message Batch API](https://platform.claude.com/docs/en/api/messages/batches/create)

“Up to 24 hours” should not be treated as an earlier delivery guarantee. Everquill’s two-hour and eight-hour timers therefore always need a fallback.

#### Start-time flow

When the player commits a timed action:

1. The deterministic engine creates an authoritative `result_spec`.
2. A sanitized `presentation_spec` is derived from it.
3. Both receive a revision and content hash.
4. The timer and `timer_started` event commit.
5. A batch outbox row is inserted in the same transaction.
6. The batch submitter groups compatible requests by model, prompt version, and approximate due window.

Example `custom_id`:

```text
eq_<base32(timer_id)>_r<revision>
```

The batch prompt may phrase or organize facts, but it may not decide gains, success, research truth, injuries, or state.

#### Revision protection

Interruptible training and research can change because of fires, attacks, travel, or aborts. Any authoritative change:

```text
increments result_revision
recomputes presentation_spec_hash
marks older batch requests superseded
```

A batch result is accepted only if its revision and hash still match.

#### Result race

```python
def accept_generated_artifact(timer_id, revision, spec_hash, artifact, mode):
    validate_schema(artifact)
    validate_known_only_content(artifact)

    INSERT INTO generated_artifact(...)
    VALUES (..., mode)  # mode = batch/synchronous/template
    ON CONFLICT (timer_id, revision) DO NOTHING
```

The unique `(timer_id, revision)` winner prevents a late batch from overwriting synchronous fallback content.

#### Due-time behavior

At the timer boundary:

- Commit deterministic completion whether or not prose exists.
- If a valid batch artifact exists, attach it.
- Otherwise mark presentation as pending.
- Do not block the timer worker on an LLM call.

#### On-open fallback

```python
def open_completed_result(timer_id):
    timer = load_completed_timer(timer_id)

    if artifact_exists(timer.id, timer.result_revision):
        return artifact()

    if acquire_short_generation_lock(timer.id, timer.result_revision):
        try:
            artifact = synchronous_llm(
                timer.presentation_spec,
                idempotency_key=timer.presentation_spec_hash,
            )
            accept_generated_artifact(
                timer.id,
                timer.result_revision,
                timer.presentation_spec_hash,
                artifact,
                mode="synchronous",
            )
        except Exception:
            accept_generated_artifact(
                timer.id,
                timer.result_revision,
                timer.presentation_spec_hash,
                deterministic_template(timer),
                mode="template",
            )

    return wait_for_winner_then_read()
```

Research should always have structured Chronicle/Inquiry findings available in the template fallback. Training should always have exact gains and a factual completion card without requiring an LLM; batch prose is optional flavor.

If a time skip makes a result immediately due, the same on-open path runs. Payment capture should happen only after authoritative completion and an acceptable durable result artifact have been stored. If synchronous generation fails, keep the factual template but recredit any promise that explicitly included generated presentation.

#### Batch operating rules

- Submit immediately after timer creation.
- Flush small deadline-homogeneous batches frequently rather than mixing urgent and multi-day requests.
- Store batch IDs and request IDs durably.
- Match responses only through `custom_id`.
- Accept results early but keep them sealed until the timer is due.
- Retry an expired batch only if sufficient time remains.
- Discard stale revisions.
- If synchronous generation already won, record the late batch as superseded.
- Never serialize true sheets into `presentation_spec`.

### 2.8 Important failure cases

| Failure | Required result |
|---|---|
| Worker offline past due time | Timer executes late with original effective time. |
| Worker crashes after claim | Lease expires; another worker retries. |
| Worker crashes after event insert | Duplicate event is rejected; timer status is repaired. |
| Two workers claim different timers in one world | World lock and earlier-timer check preserve semantic order. |
| Batch does not finish before due | State completes; on-open synchronous/template fallback. |
| Batch finishes after fallback | Unique artifact constraint rejects overwrite. |
| Timer specification changes | Revision/hash mismatch discards old generation. |
| Player skips while batch is running | All due world timers catch up; opening uses fallback if needed. |
| Notification send fails | Outbox retries independently; completion remains committed. |
| Projection update is buggy | Rebuild projection from the event log; never alter the event. |

---

## 3. Prior-art interpretation

Classic epidemic or gossip algorithms distribute updates by repeated peer contact and provide robust eventual spread. They are a good metaphor for rumor reach, but literally simulating every transmission would violate Everquill’s lazy-evaluation law. The proposed exponential reach envelope is the analytic substitute: it reproduces delayed, distance-limited, eventually fading dissemination without storing individual transmissions. [Demers et al., “Epidemic Algorithms for Replicated Database Maintenance”](https://www.cs.cornell.edu/courses/cs6452/2012sp/papers/demers-epidemic.pdf)

MMO interest management provides the more direct architectural precedent: only compute or transmit state relevant to a particular spatial consumer. Everquill’s region query is effectively an area-of-interest calculation over history rather than a broadcast of live entity updates. [Han et al., “A Scalable Interest Management Scheme for Distributed Virtual Environments”](https://pure.kaist.ac.kr/en/publications/a-scalable-interest-management-scheme-for-distributed-virtual-env/)

Simulation LOD supports replacing detailed off-screen simulation with a cheaper representation as long as materially important outcomes remain stable. Everquill should use region-level belief as the low-detail representation and refine to an NPC only when that NPC enters a decision. [Carlson and Hodgins, “Simulation Levels of Detail for Real-Time Animation”](https://graphicsinterface.org/proceedings/gi1997/gi1997-1/)

Dwarf Fortress is useful product precedent for persistent generated history, rumors, reputation, and re-encountering retired characters, but it should not be copied as a scheduling architecture. Everquill can deliver the same sense of accumulated history through event-log projections without continuously simulating every off-screen person. [Bay 12 Games’ official feature description](https://bay12games.com/dwarves/features.html)

---

## Recommended implementation decisions

- Six-world-hour rumor epochs.
- Directed, versioned travel graph measured in carriage-days.
- Exponential distance and memory half-lives.
- Regional distortion frozen at first arrival.
- SHA-256-derived deterministic seeds and versioned mutation tables.
- Append-only rumor-affecting events; no mutable rumor truth.
- Lazy high-watermark invalidation, not fan-out invalidation.
- NPC refinement from region claims plus direct evidence.
- Anchored world clock plus absolute `due_world_at`.
- Indexed derived `wake_at`, recalculated after clock jumps.
- `SKIP LOCKED` leases for worker concurrency.
- Unique completion-event keys for exactly-once effects.
- Missed consequential timers fire late, never disappear, and never double-apply.
- LLM batch results are replaceable presentation artifacts, never authoritative outcomes.
- Synchronous on-open generation followed by a deterministic template fallback.

## Sources

- [PostgreSQL: `SELECT`, row locking, and `SKIP LOCKED`](https://www.postgresql.org/docs/current/sql-select.html)
- [PostgreSQL: `INSERT ... ON CONFLICT`](https://www.postgresql.org/docs/current/sql-insert.html)
- [PostgreSQL: explicit and advisory locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [Anthropic: Batch processing guide](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- [Anthropic: Create a Message Batch API](https://platform.claude.com/docs/en/api/messages/batches/create)
- [Google SRE: Distributed Periodic Scheduling with Cron Service](https://sre.google/sre-book/distributed-periodic-scheduling/)
- [Demers et al.: Epidemic Algorithms for Replicated Database Maintenance](https://www.cs.cornell.edu/courses/cs6452/2012sp/papers/demers-epidemic.pdf)
- [IBM Research: Interest Management for Distributed Virtual Environments—A Survey](https://research.ibm.com/publications/interest-management-for-distributed-virtual-environments-a-survey)
- [Han et al.: A Scalable Interest Management Scheme for Distributed Virtual Environments](https://pure.kaist.ac.kr/en/publications/a-scalable-interest-management-scheme-for-distributed-virtual-env/)
- [Carlson and Hodgins: Simulation Levels of Detail for Real-Time Animation](https://graphicsinterface.org/proceedings/gi1997/gi1997-1/)
- [Bay 12 Games: Dwarf Fortress features](https://bay12games.com/dwarves/features.html)