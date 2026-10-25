-- 0002_projections.sql — Tier-1 synchronous projection tables (Sprint 1, Team A).
--
-- Every table here is a REBUILDABLE projection of the event log (truncate +
-- replay must reproduce it bit-for-bit — tests/test_db_rebuild.py). Projections
-- are written in the SAME transaction as the event append (synthesis §2.2
-- Tier 1: no eventual consistency anywhere the player can see).
--
-- Folds are pure functions over stored deltas (everquill_engine/folds.py) and
-- NEVER recompute from engine rules — event sourcing, not command sourcing.

-- The single world row (one world per database in Sprint 1; multi-world is a
-- later F concern). Holds the world seed (server-side only), the current
-- world clock in minutes, and the per-stream dice counters (rebuildable from
-- the rng column of the log; materialized so restarts don't replay).
CREATE TABLE world_state (
    singleton     boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    seed          bigint  NOT NULL,
    world_time    bigint  NOT NULL,
    rng_counters  jsonb   NOT NULL DEFAULT '{}',  -- {json-encoded stream key: next index}
    last_event_id bigint  NOT NULL
);

-- TRUE character sheet projection. SERVER-SIDE ONLY: aptitudes here are true
-- stats and must never be serialized to the client or any narrator context
-- path (design law). The API (Team F) exposes known-sheet views only.
CREATE TABLE character_sheet (
    entity_id     text    PRIMARY KEY,
    name          text    NOT NULL,
    origin        text    NOT NULL,
    aptitudes     jsonb   NOT NULL,               -- {might,finesse,wits,will,presence,lore}: int
    hp            int     NOT NULL,
    hp_max        int     NOT NULL,
    coin          int     NOT NULL,               -- copper
    location_id   text,
    inventory     jsonb   NOT NULL DEFAULT '{}',  -- {item_id: qty}
    flags         jsonb   NOT NULL DEFAULT '{}',  -- {flag_key: value} (scars, hooks, dispositions)
    titles        jsonb   NOT NULL DEFAULT '[]',  -- [{title, deed_ref}]
    last_event_id bigint  NOT NULL
);

-- Claims (v1 minimal per the Sprint-1 ticket): rows written by observation /
-- research deltas, with the provenance fields of the outcome-schema
-- claim_write plus the synthesis §2.3 lineage columns that must exist from
-- day one (provenance_root_event_id, hop_count, status, journal_flag).
-- Lifecycle transitions beyond 'asserted' land with the claim-graph sprint.
CREATE TABLE claim (
    claim_id                 text    PRIMARY KEY,  -- deterministic: claim_<stream slug>_<version>
    believer_id              text    NOT NULL,
    subject_entity_id        text    NOT NULL,
    claim_text               text    NOT NULL,
    value_or_range           text,
    layer                    text    NOT NULL CHECK (layer IN ('chronicle', 'inquiry')),
    source                   text    NOT NULL,
    observer                 text,
    method                   text    NOT NULL,
    world_date               text    NOT NULL,
    scope                    text    NOT NULL,
    confidence               text    NOT NULL
        CHECK (confidence IN ('uncorroborated', 'consistent', 'strongly_corroborated')),
    status                   text    NOT NULL DEFAULT 'asserted'
        CHECK (status IN ('asserted', 'corroborated', 'contested', 'superseded', 'retracted')),
    provenance_root_event_id bigint  NOT NULL,
    hop_count                int     NOT NULL DEFAULT 0,
    journal_flag             boolean NOT NULL DEFAULT false,
    world_time_acquired      bigint  NOT NULL,
    origin_event_id          bigint  NOT NULL
);

CREATE INDEX claim_believer_subject_idx
    ON claim (believer_id, subject_entity_id)
    WHERE status IN ('asserted', 'corroborated', 'contested');
CREATE INDEX claim_provenance_root_idx ON claim (provenance_root_event_id);

-- Scene manifest: where every committed entity currently is, with only the
-- manifest-safe fields (name, kind, common knowledge, portrait). True sheets
-- of authored entities never enter the log or this table — they stay in the
-- world-content YAML, read by the resolver as config.
CREATE TABLE scene_manifest (
    entity_id        text    PRIMARY KEY,
    location_id      text,
    kind             text    NOT NULL,             -- location|npc|creature|item|prop|character
    name             text    NOT NULL,
    region           text,
    common_knowledge jsonb   NOT NULL DEFAULT '[]',
    portrait         text,
    last_event_id    bigint  NOT NULL
);

CREATE INDEX scene_manifest_location_idx ON scene_manifest (location_id);
