-- 0001_event_store.sql — the append-only canon log (Sprint 1, Team A).
--
-- BINDING shape: docs/research/data-layer/claude-synthesis.md §2.1, with the
-- Sprint-1 ticket's column naming (stream_version / payload_version align with
-- everquill_engine/events.py; stream + entity ids are text, not uuid, because
-- world-content ids are authored strings like 'npc.duskwell.mara').
--
-- Rules (docs/roadmap.md State architecture v2):
--   * EVENT sourcing, never COMMAND sourcing: payloads are facts with deltas.
--   * Append-only at the privilege level: UPDATE/DELETE revoked below.
--     Corrections are compensating events, never edits.
--   * (stream_id, stream_version) UNIQUE = optimistic concurrency
--     (savescum-proof; racing writers lose and retry against new state).
--   * command_id UNIQUE = idempotency (duplicate append absorbed).
--     A multi-event command stores its raw command_id on the first event and
--     '<command_id>#<n>' on siblings, so one probe answers "seen before?".
--   * transaction_id (xid8) exists for future async consumers (rumor epochs
--     read WHERE transaction_id < pg_snapshot_xmin(...)); Tier-1 sync
--     projections do not use it.

CREATE TABLE event (
    id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id  xid8        NOT NULL DEFAULT pg_current_xact_id(),
    stream_id       text        NOT NULL,
    stream_version  int         NOT NULL CHECK (stream_version >= 1),
    world_time      bigint      NOT NULL,             -- integer world MINUTES (docs/engine/stats.md)
    event_type      text        NOT NULL,
    location_id     text,                             -- nullable; rumor-propagation index key
    command_id      text        NOT NULL UNIQUE,
    rng             jsonb,                            -- {stream, index, rolls[]} — null when no dice
    payload         jsonb       NOT NULL,
    payload_version smallint    NOT NULL DEFAULT 1 CHECK (payload_version >= 1),
    meta            jsonb       NOT NULL DEFAULT '{}',
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (stream_id, stream_version)
);

-- The three indexes (synthesis §2.1). The UNIQUE constraint above already
-- provides the (stream_id, stream_version) btree.
CREATE INDEX event_location_world_time_idx
    ON event (location_id, world_time) WHERE location_id IS NOT NULL;
CREATE INDEX event_type_world_time_idx
    ON event (event_type, world_time);

-- Append-only at privilege level. The dev DB user is the table owner (and on
-- Railway dev, superuser) so this cannot bind the owner itself; it binds every
-- non-owner role from day one. Team F provisions the non-owner app_role at
-- deploy time and re-checks these grants (interface note in the Sprint-1
-- report). TRUNCATE deliberately NOT revoked: dev-only resets use it.
REVOKE UPDATE, DELETE ON event FROM PUBLIC;
