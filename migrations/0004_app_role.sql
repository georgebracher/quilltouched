-- 0004_app_role.sql — non-owner runtime role for the API (Sprint 1, Team F).
--
-- WHY: migration 0001 revokes UPDATE/DELETE on event from PUBLIC, but the dev
-- connection (Railway managed PG default user 'postgres') is the table OWNER
-- (and superuser), so that revoke does not bind it. Append-only at the
-- privilege level only means something for a NON-owner role — this one.
--
-- The API's runtime connection should authenticate as app_role via
-- APP_DATABASE_URL (falls back to DATABASE_URL with a startup warning).
--
-- Secrets discipline: this file creates the role NOLOGIN and grants
-- privileges only. Enabling login is a per-environment, out-of-band step
-- (password never enters the repo):
--
--     ALTER ROLE app_role LOGIN PASSWORD '<from your secret store>';
--
-- Role creation is cluster-wide, not per-database, so guard for reruns
-- against another database on the same server.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
        CREATE ROLE app_role NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO app_role;

-- Event log: append + read ONLY. No UPDATE/DELETE/TRUNCATE grant, ever —
-- corrections are compensating events. (The REVOKE is belt-and-braces:
-- nothing above granted these, and 0001 already revoked from PUBLIC.)
GRANT SELECT, INSERT ON event TO app_role;
REVOKE UPDATE, DELETE, TRUNCATE ON event FROM app_role;

-- Tier-1 projections: the store's same-transaction upserts need
-- SELECT (fold-state load) + INSERT + UPDATE (ON CONFLICT DO UPDATE).
-- No DELETE/TRUNCATE: rebuild_projections/fresh_reset are owner/dev tools.
GRANT SELECT, INSERT, UPDATE ON world_state, character_sheet, claim,
    scene_manifest, timer TO app_role;

-- Migration bookkeeping is read-only for the runtime role; migrations
-- themselves always run on the owner connection.
GRANT SELECT ON schema_migrations TO app_role;

-- Identity columns (event.id, timer.id) draw from sequences.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_role;
