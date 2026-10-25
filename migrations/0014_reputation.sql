-- 0014_reputation.sql — Sprint 4 (The Self & The Social), Wave 1 (engine data).
--
-- Reputation is a NEW Tier-1 projection: the world's memory of the player as a
-- person, in three scopes, all folded from append-only `reputation` deltas
-- (everquill_engine/folds.py::_apply_reputation_delta). It replaces the orphaned
-- per-NPC boolean flags (rapport_/owes_favor_/rebuffed_) that nothing ever read
-- back into the social roll (docs/tickets/sprint-4.md §"what is broken/missing").
--
--   disposition — per (actor, NPC) pair  : how that NPC feels about the actor
--   standing    — per (actor, settlement): the actor's regard in a given town
--   renown      — per actor, global      : the spreading name (subject_id = '')
--
-- Values are signed ints applied VERBATIM by the fold — event sourcing, not
-- command sourcing: the fold never clamps or re-derives. The RESOLVER bounds the
-- value at command time and emits the already-bounded delta (folds.py module
-- docstring, synthesis §2.6 rule 1). One writer per row: the reputation fold.
--
-- HIGH-3: a new projection in folds.PROJECTOR_VERSIONS ('reputation' = 1) forces
-- a matching projection_checkpoint row here or store._verify_projector_versions
-- refuses every append. store.PROJECTION_TABLES gains 'reputation' in the same
-- commit — that tuple drives load_fold_state, _write_dirty, and the rebuild
-- shadow/grant DDL (_POST_SWAP_DDL is derived from it, so the grant below is
-- re-applied automatically after a shadow swap).

CREATE TABLE reputation (
    actor_id      text    NOT NULL,
    scope         text    NOT NULL CHECK (scope IN ('disposition', 'standing', 'renown')),
    subject_id    text    NOT NULL DEFAULT '',   -- NPC id | settlement id | '' for global renown
    value         integer NOT NULL DEFAULT 0,
    last_event_id bigint  NOT NULL,
    PRIMARY KEY (actor_id, scope, subject_id)
);

GRANT SELECT, INSERT, UPDATE ON reputation TO app_role;

-- HIGH-3 checkpoint seed (lockstep with folds.PROJECTOR_VERSIONS['reputation']=1).
INSERT INTO projection_checkpoint (projection_name, projector_version)
VALUES ('reputation', 1);
