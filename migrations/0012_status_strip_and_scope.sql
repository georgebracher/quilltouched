-- 0012_status_strip_and_scope.sql — Sprint 3 wave 1, Team A (engine).
--
-- Read-path support for the Codex/status-strip surfaces landed this wave.
-- No new columns, no new projection: the knowledge system (source scope,
-- appraisal tiers, the `weak_point` predicate, research-written Inquiry
-- claims) is authored config (content/world YAML) + closed code vocabulary
-- (everquill_engine/claims.py) + rebuildable claim events — none of it needs
-- schema. What DOES benefit from an index is the new per-character read F
-- wires for D's status strip.
--
-- (a) STATUS STRIP — active timers by owner.
-- views.ChronicleFacts now carries `active_timers` (coin + world date were
-- already there); the API's /api/facts (Team F) serves the status strip from
-- the pending timers a character owns:
--     SELECT ... FROM timer WHERE subject_id = %s AND status = 'pending'
--     ORDER BY world_due
-- The existing timer indexes are keyed on due time alone (timer_due_pending,
-- timer_world_due_pending) for the sweeper — none lead with subject_id, so a
-- per-character lookup scans all pending timers. This partial index makes the
-- status-strip read an index range scan and orders it for free. Projection
-- tables are copied `(LIKE ... INCLUDING ALL)` into the shadow on a rebuild,
-- so this index survives the shadow-swap like the others.

CREATE INDEX timer_active_by_subject
    ON timer (subject_id, world_due)
    WHERE status = 'pending';
