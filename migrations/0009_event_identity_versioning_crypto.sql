-- 0009_event_identity_versioning_crypto.sql — Sprint 2 wave 3 (Team A2).
--
-- (a) MEDIUM-6: event_ulid + stream_type on the event table.
--     event_ulid is the STABLE EXTERNAL id (outcome_contract exposes it;
--     bigint id stays the local ordering key). It is DERIVED
--     DETERMINISTICALLY — Crockford base32 of 48 bits of world-time
--     milliseconds || 80 bits of md5('everquill.event_ulid.' ||
--     stream_id || ':' || stream_version) — so identical (seed, script)
--     runs produce byte-identical logs (determinism suite) while
--     UNIQUE(stream_id, stream_version) guarantees uniqueness. The
--     Python writer (everquill_engine/store.py:event_ulid) and the
--     plpgsql backfill below implement the SAME derivation; the tests
--     assert they agree.
--
-- (b) MEDIUM-6: projection_checkpoint. Doubles as HIGH-3's persisted
--     projector_version (one row per projection table; Tier-1 rows keep
--     last_tx_id/last_event_id NULL — the append transaction IS their
--     checkpoint). Tier-2 workers (rumor epochs — later sprint) claim
--     rows and advance last_tx_id under the xid8 read predicate.
--     The append path verifies stored projector_version == the code's
--     folds.PROJECTOR_VERSIONS and refuses to write a projection built
--     by different fold logic — a fold change without a rebuild is now
--     a loud error, never silent live/replay divergence (HIGH-3).
--
-- (c) HIGH-8: account_key — the per-account envelope-key singleton
--     (worlds and accounts are 1:1, so the key lives in the world
--     schema). dek is AES-GCM-wrapped under EVERQUILL_MASTER_KEY when
--     set (wrap_mode 'kek-v1') or raw in dev ('raw'). DELETING the row
--     is the GDPR shred: every player-text ciphertext written under it
--     (intent approach / quoted speech) becomes permanently unreadable;
--     events still fold. app_role may create/read the key but never
--     delete it — shredding is an operator action on the owner
--     connection (everquill_engine.crypto.shred_account_key).

-- (a) event identity -------------------------------------------------------------
ALTER TABLE event
    ADD COLUMN event_ulid  text,
    ADD COLUMN stream_type text;

-- Exact integer arithmetic ONLY in this function: numeric '/' rounds at
-- its chosen result scale, so trunc(n / 32) can step a whole unit on
-- 128-bit values (found by the tests/test_db_store.py derivation pin) —
-- div()/mod() are the exact truncating forms. 281474976710656 = 2^48 as
-- a literal because numeric '^' is likewise inexact at this size.
CREATE OR REPLACE FUNCTION pg_temp._eq_event_ulid(
    world_time bigint, stream_id text, stream_version int
) RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    alphabet constant text := '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
    h bytea := decode(
        md5('everquill.event_ulid.' || stream_id || ':' || stream_version::text), 'hex');
    n numeric := mod(world_time::numeric * 60000, 281474976710656::numeric);
    result text := '';
    i int;
BEGIN
    FOR i IN 0..9 LOOP  -- 48-bit time || first 10 md5 bytes = 128 bits
        n := n * 256 + get_byte(h, i);
    END LOOP;
    FOR i IN 1..26 LOOP
        result := substr(alphabet, mod(n, 32)::int + 1, 1) || result;
        n := div(n, 32);
    END LOOP;
    RETURN result;
END $$;

UPDATE event SET
    event_ulid = pg_temp._eq_event_ulid(world_time, stream_id, stream_version),
    stream_type = split_part(stream_id, ':', 1)
WHERE event_ulid IS NULL;

ALTER TABLE event
    ALTER COLUMN event_ulid SET NOT NULL,
    ALTER COLUMN stream_type SET NOT NULL;

CREATE UNIQUE INDEX event_ulid_key ON event (event_ulid);
CREATE INDEX event_stream_type_idx ON event (stream_type, id);

-- (b) projection checkpoints + projector versions ---------------------------------
CREATE TABLE projection_checkpoint (
    projection_name   text        PRIMARY KEY,
    projector_version int         NOT NULL CHECK (projector_version >= 1),
    last_tx_id        xid8,
    last_event_id     bigint,
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- Seed rows MUST match everquill_engine.folds.PROJECTOR_VERSIONS at this
-- commit (claim is v2 — the HIGH-5 typed rebuild; everything else v1).
-- tests/test_db_store.py asserts DB rows == code.
INSERT INTO projection_checkpoint (projection_name, projector_version) VALUES
    ('world_state', 1),
    ('character_sheet', 1),
    ('entity_state', 1),
    ('claim', 2),
    ('claim_evidence', 1),
    ('scene_manifest', 1),
    ('timer', 1);

GRANT SELECT, INSERT, UPDATE ON projection_checkpoint TO app_role;

-- (c) account envelope key ---------------------------------------------------------
CREATE TABLE account_key (
    singleton  boolean     PRIMARY KEY DEFAULT true CHECK (singleton),
    key_id     text        NOT NULL,
    dek        bytea       NOT NULL,
    wrap_mode  text        NOT NULL CHECK (wrap_mode IN ('kek-v1', 'raw')),
    created_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT ON account_key TO app_role;
REVOKE UPDATE, DELETE, TRUNCATE ON account_key FROM app_role;
