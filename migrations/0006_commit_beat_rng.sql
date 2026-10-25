-- 0006_commit_beat_rng.sql — Sprint 2 wave 1 (Team A1).
--
-- (a) pending_confirmation — the two-phase commit beat's storage
--     (interface decision 2). Timer-table-style OPERATIONAL row, NOT a
--     projection: no event exists until the player confirms, so an
--     unconfirmed assessment leaves zero canon and rebuilds ignore this
--     table (fresh_reset clears it). One row per assessed command_id;
--     the parsed intent is stored VERBATIM so the confirm path resolves
--     exactly what was assessed, under the original command id.
--     Expiry is world-activity based: expires_world_time =
--     created_world_time + 10 world-minutes; a confirm arriving at or
--     past it marks the row expired and returns a clean "the moment has
--     passed" error — never a stale resolution (everquill_engine/beat.py).
--
-- (b) MEDIUM-4: canonical uniqueness on (rng->'stream', rng->'index').
--     Roll-site independence is now structural (rng_registry.py gives
--     every site its own stream); this index makes counter reuse — a
--     stale retry committing a duplicate (stream, index) draw — a
--     constraint violation instead of a silent double-spend of dice.
--     Partial (rng IS NOT NULL): most events carry no dice.
--     NOTE (dev/Railway): the shared dev DB is wiped by test runs; if a
--     pre-0006 log somehow holds duplicate draws, this CREATE fails —
--     fresh_reset (or redeploy/reseed) the dev world first.

-- (a) pending_confirmation ------------------------------------------------------
CREATE TABLE pending_confirmation (
    command_id          text        PRIMARY KEY,
    character_id        text        NOT NULL,
    intent              jsonb       NOT NULL,   -- the parsed intent, verbatim
    tier                text        NOT NULL,   -- assessed plausibility tier (words)
    risk_label          text,                   -- pre-roll risk word; null = no-roll shape
    world_minutes_cost  int         NOT NULL DEFAULT 0,  -- duration preview shown at the beat
    created_world_time  bigint      NOT NULL,
    expires_world_time  bigint      NOT NULL,   -- created + 10 world-minutes
    status              text        NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'expired')),
    confirmed_event_id  bigint      REFERENCES event (id),
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX pending_confirmation_open_idx
    ON pending_confirmation (character_id, expires_world_time)
    WHERE status = 'pending';

-- Runtime role: the beat reads, inserts and transitions rows. No DELETE —
-- expired/confirmed rows are ops history until a dev reset.
GRANT SELECT, INSERT, UPDATE ON pending_confirmation TO app_role;

-- (b) rng draw uniqueness (MEDIUM-4) --------------------------------------------
CREATE UNIQUE INDEX event_rng_stream_index_key
    ON event ((rng->'stream'), (rng->'index'))
    WHERE rng IS NOT NULL;
