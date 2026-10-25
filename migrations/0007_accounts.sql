-- 0007_accounts.sql — Sprint 2 wave 2 (Team F). Accounts v1 + LLM cost ledger.
--
-- (a) accounts — invite-code + device-token accounts (interface decision 1).
--     No passwords: POST /api/claim exchanges a valid invite code for a
--     random 256-bit device token; ONLY the sha256 hex of the token is
--     stored. One account per invite code (UNIQUE) — losing the device
--     token means an operator deletes the row and re-issues the code.
--     Each account owns its own world: world_id = 'harrowdown--<account_id
--     first 8 hex>' living in Postgres schema 'world_<prefix>' (created and
--     migrated idempotently by the API on the first authenticated call —
--     see api/accounts.py). This table is GLOBAL and therefore explicitly
--     schema-qualified: migrations are re-applied inside every world
--     schema, and these statements must stay idempotent no-ops there.
--
-- (b) llm_usage — per-stage LLM cost telemetry (parse / narrate), one row
--     per model call. Backs GET /api/ops/usage daily rollups. Global table
--     (public), same idempotency requirement as accounts.
--
-- app_role: runtime may read + append. No UPDATE/DELETE — accounts are
-- managed by operators on the owner connection; usage rows are a ledger.

CREATE TABLE IF NOT EXISTS public.accounts (
    account_id         text        PRIMARY KEY,   -- 32 hex chars (128-bit random)
    invite_code_used   text        NOT NULL UNIQUE,
    device_token_hash  text        NOT NULL UNIQUE, -- sha256 hex of the raw token
    created_at         timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT ON public.accounts TO app_role;
REVOKE UPDATE, DELETE, TRUNCATE ON public.accounts FROM app_role;

CREATE TABLE IF NOT EXISTS public.llm_usage (
    id                          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                          timestamptz NOT NULL DEFAULT now(),
    account_id                  text,          -- null for legacy/ops calls
    world_id                    text,
    command_id                  text,
    stage                       text NOT NULL, -- 'parse' | 'narrate'
    model                       text NOT NULL,
    input_tokens                integer NOT NULL DEFAULT 0,
    output_tokens               integer NOT NULL DEFAULT 0,
    cache_read_input_tokens     integer NOT NULL DEFAULT 0,
    cache_creation_input_tokens integer NOT NULL DEFAULT 0,
    latency_ms                  integer NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS llm_usage_ts_idx ON public.llm_usage (ts);

GRANT SELECT, INSERT ON public.llm_usage TO app_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_role;
REVOKE UPDATE, DELETE, TRUNCATE ON public.llm_usage FROM app_role;
