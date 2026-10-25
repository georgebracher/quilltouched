-- 0008_claim_v2.sql — Sprint 2 wave 3 (Team A2). HIGH-5: the full claim
-- schema per docs/research/data-layer/claude-synthesis.md §2.3 (shape
-- verbatim from the claim-graphs lens §2, adapted to text entity ids and
-- the integer-only numeric rule LOW-1: value_num is bigint, never numeric).
--
-- The claim table STAYS a rebuildable projection: lifecycle transitions
-- are EVENTS (claim_written / claim_corroborated / claim_contested /
-- claim_superseded / claim_retracted — everquill_engine/events.py), and
-- this migration's backfill of pre-v2 rows mirrors the claim_written
-- v1→v2 upcaster (everquill_engine/upcasters.py) EXACTLY, so a
-- truncate-and-replay rebuild reproduces what this file backfills.
--
-- v1 free-text claims map to the 'observed_statement' predicate with all
-- provenance preserved (the Sprint-2 ticket's migration rule). The
-- predicate vocabulary is CLOSED and enforced in code
-- (everquill_engine/claims.py, folds raise on unknown predicates) rather
-- than by a CHECK — the registry is append-only and a DB CHECK would
-- demand a migration per vocabulary addition. acquisition_method IS
-- CHECK-constrained: five values, binding order of evidence weight
-- (observed > told > rumor > inherited_journal > overheard).

-- (a) typed columns ------------------------------------------------------------
ALTER TABLE claim
    ADD COLUMN predicate              text,
    ADD COLUMN value_text             text,
    ADD COLUMN value_num              bigint,
    ADD COLUMN value_range            int8range,
    ADD COLUMN world_valid            int8range,
    ADD COLUMN acquisition_method     text,
    ADD COLUMN source_agent_id        text,
    ADD COLUMN derived_from_claim_id  text,
    ADD COLUMN strength               int,
    ADD COLUMN contested_by_claim_id  text,
    ADD COLUMN superseded_by_claim_id text,
    ADD COLUMN superseded_reason      text
        CHECK (superseded_reason IN
               ('better_evidence', 'direct_observation', 'source_recanted', 'canon_sealed'));

-- (b) backfill of pre-v2 rows — MUST stay byte-equivalent to
-- upcasters.upcast_claim_fields_v1_to_v2 + the founding-evidence strength
-- rule (one link at its undecayed base weight).
UPDATE claim SET
    predicate = 'observed_statement',
    value_text = value_or_range,
    acquisition_method = CASE method
        WHEN 'witnessed'         THEN 'observed'
        WHEN 'misjudged_glance'  THEN 'observed'
        WHEN 'survived_attempt'  THEN 'observed'
        WHEN 'hard_lesson'       THEN 'observed'
        WHEN 'appraisal_ii'      THEN 'observed'
        WHEN 'conversation'      THEN 'told'
        WHEN 'archive_research'  THEN 'rumor'
        WHEN 'rumor'             THEN 'rumor'
        WHEN 'inherited_journal' THEN 'inherited_journal'
        WHEN 'overheard'         THEN 'overheard'
        ELSE 'told'
    END
WHERE predicate IS NULL;

UPDATE claim SET strength = CASE acquisition_method
        WHEN 'observed'          THEN 100
        WHEN 'told'              THEN 60
        WHEN 'rumor'             THEN 35
        WHEN 'inherited_journal' THEN 20
        WHEN 'overheard'         THEN 10
    END
WHERE strength IS NULL;

ALTER TABLE claim
    ALTER COLUMN predicate SET NOT NULL,
    ALTER COLUMN acquisition_method SET NOT NULL,
    ALTER COLUMN strength SET NOT NULL;

-- value_or_range is fully superseded by the typed value_text (the
-- backfill above copied it). Dropping it keeps live rows byte-equal to
-- a truncate-and-replay rebuild through the v1→v2 upcaster (which emits
-- no value_or_range). The KnownState surface still exposes the field
-- name for Team C compatibility, populated from value_text.
ALTER TABLE claim DROP COLUMN value_or_range;

ALTER TABLE claim
    ADD CONSTRAINT claim_acquisition_method_check CHECK (acquisition_method IN
        ('observed', 'told', 'rumor', 'inherited_journal', 'overheard'));

-- (c) evidence links (corroboration substrate). A projection like claim:
-- folded from claim_written (founding link) and claim_corroborated
-- events. No FK — folds guarantee integrity and projection tables must
-- survive the shadow-rebuild swap without dependent-object surgery.
CREATE TABLE claim_evidence (
    claim_id           text   NOT NULL,
    event_id           bigint NOT NULL,   -- the evidence event (canon id)
    root_event_id      bigint NOT NULL,   -- provenance root, propagated through hops
    acquisition_method text   NOT NULL,
    base_weight        int    NOT NULL,
    world_time         bigint NOT NULL,   -- when acquired (decay input)
    PRIMARY KEY (claim_id, event_id)
);

GRANT SELECT, INSERT, UPDATE ON claim_evidence TO app_role;

-- Backfill: every pre-v2 claim holds exactly its founding evidence link.
INSERT INTO claim_evidence
    (claim_id, event_id, root_event_id, acquisition_method, base_weight, world_time)
SELECT claim_id, origin_event_id, provenance_root_event_id, acquisition_method,
       strength, world_time_acquired
FROM claim
ON CONFLICT DO NOTHING;

-- (d) THE synthesis §2.3 index set (claim-graphs lens §5). The old
-- (believer, subject) partial index is a strict prefix of the new hot
-- probe key and is dropped.
DROP INDEX IF EXISTS claim_believer_subject_idx;

CREATE INDEX claim_active_key ON claim (believer_id, subject_entity_id, predicate)
    WHERE status IN ('asserted', 'corroborated', 'contested');

CREATE INDEX claim_active_recent ON claim (believer_id, world_time_acquired DESC)
    WHERE status IN ('asserted', 'corroborated', 'contested');

-- claim_provenance_root_idx (0002) already covers the by-root walk.
CREATE INDEX claim_by_parent ON claim (derived_from_claim_id)
    WHERE derived_from_claim_id IS NOT NULL;

CREATE INDEX claim_journaled ON claim (believer_id, world_time_acquired)
    WHERE journal_flag;

-- gist over (text, int8range) needs btree_gist (trusted contrib; global,
-- so re-application inside world schemas is a no-op).
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE INDEX claim_world_valid ON claim USING gist (subject_entity_id, world_valid)
    WHERE world_valid IS NOT NULL;
