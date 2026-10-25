-- 0017_test_turn_capture.sql — TEST-ONLY plaintext turn capture.
--
-- This is a global operator/debug path, not canon. The encrypted append-only
-- event log remains unchanged; normal accounts default OFF forever unless an
-- owner explicitly flips public.accounts.test_capture for that one account.
--
-- Like 0007/0010/0015, every statement touching account/debug state is
-- public-qualified because migrations are also applied inside each per-account
-- world schema.

ALTER TABLE public.accounts
    ADD COLUMN IF NOT EXISTS test_capture boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS public.test_turn_capture (
    id                     bigserial PRIMARY KEY,
    world_id               text,
    command_id             text,
    kind                   text CHECK (kind IN ('action', 'confirm')),
    world_time             bigint,
    utterance              text,
    action_type            text,
    target_entity_ids      jsonb,
    approach               text,
    pending_confirmation   boolean,
    tier_resolved          text,
    outcome_tier           text,
    state_deltas           jsonb,
    narration              text,
    system_note            text,
    created_at             timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT ON public.test_turn_capture TO app_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_role;
REVOKE UPDATE, DELETE, TRUNCATE ON public.test_turn_capture FROM app_role;
