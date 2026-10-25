-- 0003_timers.sql — world-clock timer table (Sprint 1, Team A).
--
-- Structure per docs/research/data-layer/claude-synthesis.md §2.5, adapted:
--   * subject_id is text (our entity ids are authored strings, not uuids).
--   * timer_key is the deterministic domain id ('timer_<stream slug>_<version>'
--     of the timer_started event) known BEFORE any insert, so event payloads
--     can reference the timer they start without id circularity. The sweeper's
--     idempotency key is 'timer:<timer_key>' (synthesis 'timer:{id}').
--   * due_at (real-world) is derived deterministically from world_due in
--     Sprint 1 (epoch + world_due minutes) because there is no world→real
--     time mapping yet; the mapping and the 15–30s procrastinate sweep are a
--     later sprint. Sprint 1 sweeps manually via
--     `python -m everquill_engine.cli clock-advance` on world time.
--
-- This table is BOTH a projection of timer_* events (rebuildable) and the
-- ops queue the sweeper claims from with FOR UPDATE SKIP LOCKED.

CREATE TABLE timer (
    id               bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    timer_key        text        NOT NULL UNIQUE,
    kind             text        NOT NULL,       -- training|research|travel|craft|recovery|worldgen|rumor
    subject_id       text        NOT NULL,
    due_at           timestamptz NOT NULL,       -- real-world; Sprint-1: epoch + world_due minutes
    world_due        bigint      NOT NULL,       -- world-clock stamp for the outcome event
    payload          jsonb       NOT NULL,
    status           text        NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'fired', 'cancelled')),
    created_event_id bigint      NOT NULL REFERENCES event (id),
    fired_event_id   bigint      REFERENCES event (id),
    attempts         int         NOT NULL DEFAULT 0
);

CREATE INDEX timer_due_pending ON timer (due_at) WHERE status = 'pending';
CREATE INDEX timer_world_due_pending ON timer (world_due, id) WHERE status = 'pending';
