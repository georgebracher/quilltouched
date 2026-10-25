-- 0010_invite_rate_limit_prefix.sql — Sprint 2 wave 3 (API hardening crew).
-- EQ-R2-10 (invite table), EQ-R2-06 (rate/spend controls), EQ-R2-11 (prefix
-- uniqueness). All three tables are GLOBAL (public) and explicitly
-- schema-qualified: migrations re-run inside every world schema, so every
-- statement here must stay an idempotent no-op there (0007 is the model).

-- (a) EQ-R2-10: invite — hash-only invite codes replacing the env-string
--     comparison as the claim authority. ONLY sha256 hex of a code is
--     stored; raw codes live in the gitignored docs/ops/invite-codes.md
--     and (for the original five) the EVERQUILL_INVITE_CODES env var,
--     which api/accounts.py seeds into this table at startup and lazily
--     at claim time (ON CONFLICT DO NOTHING), so existing codes keep
--     working with zero env changes. Claiming is one atomic
--     UPDATE ... WHERE claimed_at IS NULL RETURNING — no read-then-write
--     race, and unknown vs used are indistinguishable to the caller
--     (uniform 403: the validity-state oracle is gone).
--     public.accounts.invite_code_used keeps carrying the RAW code of a
--     successful claim: it is dead (single-use) after the claim, the ops
--     re-issue runbook keys on it, and its UNIQUE constraint stays as a
--     second single-claim guard.

CREATE TABLE IF NOT EXISTS public.invite (
    code_hash  text        PRIMARY KEY,  -- sha256 hex of the raw invite code
    created_at timestamptz NOT NULL DEFAULT now(),
    claimed_at timestamptz,              -- NULL = unclaimed; set once, atomically
    claimed_by text                      -- account_id of the claimer
);

GRANT SELECT, INSERT, UPDATE ON public.invite TO app_role;
REVOKE DELETE, TRUNCATE ON public.invite FROM app_role;

-- Seed: five ADDITIONAL high-entropy alpha codes (word-word-word-4hex,
-- ~63 bits from a 48k wordlist + 16 hex bits — far above the original
-- five). Hash-only here; raw values appended to the gitignored
-- docs/ops/invite-codes.md. These work WITHOUT being added to the env.
INSERT INTO public.invite (code_hash) VALUES
    ('307380c42c7ecf67c445b23be2c73e07883eee3c3544840793c055f456fe2cf5'),
    ('165dc78611bfd560c8d0bc9801a94afb4b3055f5486c85616db1c5e9c761efaf'),
    ('bfcb848038827d26e48c728195630d21531f8a1f8df50dd33920c05e3f9fcb35'),
    ('ece93e7a0a38da481be0a44fde8f04fd4cee330c32ab47d12b7c1211eb848b98'),
    ('e1f2420954cf7dd7866ed4bbf8f476f384a8206faabe72502d46b4965d23b8ad')
ON CONFLICT (code_hash) DO NOTHING;

-- (b) EQ-R2-06: rate_limit — FIXED-WINDOW counters (documented choice:
--     a full token bucket buys smoothness alpha does not need; a fixed
--     window is one upsert per hit, race-free under ON CONFLICT row
--     locking, and its worst case — 2x burst straddling a window edge —
--     is acceptable at alpha scale). One row per (bucket, window);
--     window_start is floor(epoch/window)*window so day windows align
--     to UTC midnight. Buckets in use: turn:<account_id> (per-minute),
--     turnday:<account_id> (daily turn ceiling), claim:ip:<ip> and
--     claim:global (invite-claim throttles). Rows are tiny and pruned
--     opportunistically by operators; app_role never deletes.

CREATE TABLE IF NOT EXISTS public.rate_limit (
    bucket_key   text        NOT NULL,
    window_start timestamptz NOT NULL,
    count        integer     NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_key, window_start)
);

GRANT SELECT, INSERT, UPDATE ON public.rate_limit TO app_role;
REVOKE DELETE, TRUNCATE ON public.rate_limit FROM app_role;

-- (c) EQ-R2-11: accounts.prefix — the 8-hex schema/world prefix becomes a
--     real column with a DATABASE uniqueness constraint. The old
--     application-level LIKE pre-check raced: two concurrent claims
--     rolling the same 32-bit prefix could both pass it and share a
--     world schema. Now the second INSERT fails on this index and the
--     claim path retries with a fresh account id (api/accounts.py).

ALTER TABLE public.accounts ADD COLUMN IF NOT EXISTS prefix text;

UPDATE public.accounts SET prefix = substr(account_id, 1, 8) WHERE prefix IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS accounts_prefix_key ON public.accounts (prefix);

ALTER TABLE public.accounts ALTER COLUMN prefix SET NOT NULL;
