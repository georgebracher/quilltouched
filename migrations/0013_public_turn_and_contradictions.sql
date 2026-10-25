-- 0013_public_turn_and_contradictions.sql — Hardening Pass 1, Team A (engine).
--
-- Three engine-boundary audit P1s land here (audit-room 2026-07-14):
--
-- (a) MULTI-EDGE CONTRADICTIONS (audit #2 "multi-edge claim contradictions
--     are lossy"; contested feature inert because contradiction_ids was
--     hardcoded []). claim.contested_by_claim_id holds only the LATEST
--     contesting claim, so a claim contested by two others silently forgot
--     the first. claim.contradiction_ids is the FULL sorted, deduped set of
--     claim ids that have contested this claim — accumulated by the
--     claim_contested fold (everquill_engine/folds.py) and surfaced on
--     views.InquiryClaim so Team F can pass real ids to the assembler.
--     This is a fold-output change → claim projector_version 2 → 3
--     (folds.PROJECTOR_VERSIONS); the checkpoint bump is (c).
--
-- (b) CANONICAL PUBLIC-TURN LOOKUP (audit #1, the headline). The
--     narration_generated event now also carries the redacted public
--     outcome + the turn's command_id, so store.public_turn(command_id)
--     serves ONE authoritative player-visible record for first response,
--     duplicate/retry, and Chronicle rebuild. This partial expression
--     index makes that lookup a point read.
--
-- (c) projection_checkpoint claim bump (HIGH-3): the stored projector_version
--     must equal folds.PROJECTOR_VERSIONS at this commit or every append
--     refuses. 0009 seeded claim=2; this sets it to 3 in lockstep with (a).

-- (a) contradiction_ids -----------------------------------------------------------
ALTER TABLE claim
    ADD COLUMN contradiction_ids jsonb NOT NULL DEFAULT '[]'::jsonb;

-- Backfill from the LOG (not the single contested_by_claim_id column) so a
-- live row equals what a truncate-and-replay rebuild through the
-- claim_contested fold produces: the full deduped, sorted set of contesters.
UPDATE claim c SET contradiction_ids = COALESCE((
    SELECT jsonb_agg(v ORDER BY v) FROM (
        SELECT DISTINCT e.payload->>'contested_by_claim_id' AS v
        FROM event e
        WHERE e.event_type = 'claim_contested'
          AND e.payload->>'claim_id' = c.claim_id
          AND e.payload->>'contested_by_claim_id' IS NOT NULL
    ) s
), '[]'::jsonb);

-- (c) projector version bump (lockstep with folds.PROJECTOR_VERSIONS['claim']=3)
UPDATE projection_checkpoint
    SET projector_version = 3, updated_at = now()
    WHERE projection_name = 'claim';

-- (b) point lookup for store.public_turn(command_id) over narration canon.
-- Partial + expression: only narration_generated rows carry turn_command_id.
CREATE INDEX event_narration_turn_command
    ON event ((payload->>'turn_command_id'))
    WHERE event_type = 'narration_generated';
