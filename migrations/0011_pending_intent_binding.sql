-- 0011_pending_intent_binding.sql — Round-2 HIGH fix EQ-R2-04.
--
-- Bind each pending confirmation to the CANONICAL intent it was assessed
-- for. Before this, a re-assessment reusing a pending command_id with a
-- DIFFERENT valid intent got back a pending response showing the retry's
-- intent, while confirmation independently resolved the ORIGINAL stored
-- intent — a harmless redeclaration could front a dangerous confirmed
-- action (defeating the informed-confirmation purpose of the Dire+/sealed/
-- irreversible beat).
--
-- intent_hash = sha256 of the canonical-JSON PLAINTEXT parsed intent
-- (everquill_engine.beat.canonical_intent_hash), computed at assess time
-- and compared on every re-assess: a matching redeclaration is idempotent;
-- a mismatch raises BeatIntentMismatchError (API -> 409) and returns the
-- STORED intent. It is a one-way fingerprint of OPERATIONAL state (this
-- table is not a projection — rebuilds ignore it, fresh_reset clears it),
-- not canon; crypto-shredding the account key still removes the recoverable
-- plaintext intent (the ciphertext in `intent` becomes noise). Nullable so
-- the column adds cleanly over a DB migrated through 0010; rows written
-- before this migration (none in a fresh world) carry NULL and skip the
-- mismatch check (the beat treats a NULL hash as "unbound, idempotent").

ALTER TABLE pending_confirmation
    ADD COLUMN intent_hash text;
