-- 0005_entity_state.sql — Sprint-1 review fix cluster (Team A).
--
-- (a) CRITICAL-2: entity_state — server-only MUTABLE projection for every
--     damageable committed entity (kind npc|creature). Seeded at world commit
--     from the entity_committed event's stored hp/hp_max facts; hp/condition/
--     position deltas targeting non-PC entities fold here in the SAME
--     transaction as the append (Tier 1). Rebuild (truncate + replay) covers
--     it like every other projection. The resolver reads authored true sheets
--     (config) PLUS this row for difficulty — a wounded wyvern is a different
--     fight. Folds RAISE on deltas targeting an entity with no state row:
--     silent drops are how CRITICAL-2 happened.
--
--     world_id is the owning world stream id ('world' — one world per
--     database in Sprint 1; the column exists so multi-world doesn't need a
--     projection rewrite).
--
-- (b) MEDIUM-2: command identity becomes (command_id, event_ordinal) — two
--     real columns with UNIQUE(command_id, event_ordinal) — killing the
--     '<command_id>#<n>' sibling suffix aliasing ('pay#1' vs sibling 1 of
--     'pay'). The store now also rejects '#' in command ids at append time,
--     so historical suffixed rows (which keep event_ordinal 0 and stay valid
--     under the new constraint) can never collide with new appends. The dev
--     DB predates alpha and is wiped by fresh_reset; rows are never edited.

-- (a) entity_state ------------------------------------------------------------
CREATE TABLE entity_state (
    entity_id             text   PRIMARY KEY,
    world_id              text   NOT NULL,
    hp                    int    NOT NULL,
    hp_max                int    NOT NULL CHECK (hp_max > 0),
    conditions            jsonb  NOT NULL DEFAULT '[]',
    location_id           text,
    updated_from_event_id bigint NOT NULL
);

CREATE INDEX entity_state_location_idx ON entity_state (location_id);

-- Runtime role needs the same projection privileges as the other Tier-1
-- tables (0004 pattern): SELECT for fold-state loads, INSERT + UPDATE for
-- the same-transaction upserts. No DELETE/TRUNCATE — rebuilds are owner ops.
GRANT SELECT, INSERT, UPDATE ON entity_state TO app_role;

-- (b) command identity columns -------------------------------------------------
ALTER TABLE event
    ADD COLUMN event_ordinal int NOT NULL DEFAULT 0 CHECK (event_ordinal >= 0);
ALTER TABLE event
    DROP CONSTRAINT event_command_id_key;
ALTER TABLE event
    ADD CONSTRAINT event_command_id_ordinal_key UNIQUE (command_id, event_ordinal);
