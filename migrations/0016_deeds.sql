-- 0016_deeds.sql — Sprint 5 Slice 2 (deeds become rumors).
--
-- Deeds are a Tier-1 projection folded from append-only `deed_recorded`
-- events. The resolver remains pure: it receives this projected list the same
-- way it receives `reputation`, and never queries the event log for deeds.
--
-- The append-order key is `deed_order`, computed by the fold as events replay
-- in id order. `source_event_id` is the provenance root for the deed_recorded
-- event itself.
--
-- HIGH-3 checkpoint seed: lockstep with folds.PROJECTOR_VERSIONS['deeds']=1.

CREATE TABLE deeds (
    deed_order      bigint  NOT NULL,
    actor_id        text    NOT NULL,
    location_id     text    NOT NULL,
    notoriety       integer NOT NULL,
    world_time      bigint  NOT NULL,
    description     text    NOT NULL,
    source_event_id bigint  NOT NULL PRIMARY KEY,
    UNIQUE (deed_order)
);

GRANT SELECT, INSERT, UPDATE ON deeds TO app_role;

INSERT INTO projection_checkpoint (projection_name, projector_version)
VALUES ('deeds', 1);
