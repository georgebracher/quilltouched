-- 0015_account_chargen_mode.sql — Sprint 4 X3 guided-dice chargen.
--
-- Additive account metadata for deferred character creation. Existing accounts
-- default to 'auto', preserving the current claim -> auto-genesis path. Guided
-- accounts record 'guided' so api/accounts.py bootstraps world genesis only;
-- /api/chargen later appends the character_created event.
--
-- This is GLOBAL account state and stays public-qualified because migrations
-- are also applied inside every per-account world schema.

ALTER TABLE public.accounts
    ADD COLUMN IF NOT EXISTS chargen_mode text NOT NULL DEFAULT 'auto';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'accounts_chargen_mode_check'
          AND conrelid = 'public.accounts'::regclass
    ) THEN
        ALTER TABLE public.accounts
            ADD CONSTRAINT accounts_chargen_mode_check
            CHECK (chargen_mode IN ('auto', 'guided'));
    END IF;
END $$;
