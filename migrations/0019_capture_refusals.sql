-- 0019: test capture also records refused actions and <<Proceed?>> beats, so a
-- logged play session shows every attempt, not only the ones that resolved
-- (frustration reviews, 25 Oct 2026). Re-runnable: each account schema applies
-- the public-qualified DDL again.
ALTER TABLE public.test_turn_capture DROP CONSTRAINT IF EXISTS test_turn_capture_kind_check;
ALTER TABLE public.test_turn_capture
    ADD CONSTRAINT test_turn_capture_kind_check
    CHECK (kind IN ('action', 'confirm', 'pending', 'refused'));
ALTER TABLE public.test_turn_capture ADD COLUMN IF NOT EXISTS http_status int;
