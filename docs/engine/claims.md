# Claim schema v2 + crypto-shredding — the consuming teams' surface

Sprint 2 wave 3, Team A2. Closes HIGH-5 (claim lifecycle per
`docs/research/data-layer/claude-synthesis.md` §2.3), HIGH-8
(crypto-shredding), with HIGH-3/MEDIUM-6 mechanics documented in
`docs/engine/events.md` (wave-3 addendum). This page is the contract
for `llm/` (Team C) and `api/` (Team F).

## The closed predicate vocabulary (llm/ boundary)

`everquill_engine/claims.py` is a PURE module (safe to import from
`llm/` — it carries no referee state):

- `PREDICATES` — the registry, APPEND-ONLY. Shipped set:
  `observed_statement` (v1 migration target, generic statement),
  `threat_assessed` (exclusive; value = band word),
  `common_knowledge` (accumulative; value = the fact),
  `disposition_toward` (exclusive; rapport/owes_favor/rebuffed/…),
  `personal_lesson` (accumulative), `whereabouts` (exclusive,
  world_valid-ranged; registered ahead of rumor propagation, no writer
  yet), `weak_point` (Sprint 3, accumulative; value = a known
  vulnerability. Written by deep appraisal tiers; the resolver reads it
  as a target-specific modifier that turns a HOPELESS physical fight into
  a DESPERATE option — knowledge changes the action space, roadmap §3.3).
- `enforce_predicate(predicate, *, value_text=…, value_num=…,
  value_range=…, world_valid=…)` — **THE parser-boundary hook.** When
  the LLM parser maps player free text to a claim, call this BEFORE the
  intent leaves `llm/`; it raises `PredicateError` on any
  out-of-vocabulary predicate or wrong-typed value. Contradiction stays
  a SQL equality problem because this gate exists — never weaken it to
  a warning.
- `BASE_EVIDENCE_WEIGHT` — observed 100 > told 60 > rumor 35 >
  inherited_journal 20 > overheard 10 (integer basis points, ordering
  binding). `decayed_weight` halves per 30 world-days, floor 1.
  `claim.strength` = decayed sum of the claim's evidence links, cached
  at the last lifecycle write.

## What the claim projection now holds

`claim` table (migration 0008): typed `predicate` + `value_text` /
`value_num` (bigint — integer-only, LOW-1) / `value_range` /
`world_valid` (int8range), `acquisition_method`, `strength`,
`provenance_root_event_id`, `source_agent_id`, `derived_from_claim_id`,
`hop_count`, `journal_flag`, `status` (five states),
`contested_by_claim_id`, `superseded_by_claim_id`, `superseded_reason`.
`claim_evidence` holds one row per evidence link
(`claim_id, event_id, root_event_id, acquisition_method, base_weight,
world_time`). Index set per synthesis §2.3: `claim_active_key`
(believer, subject, predicate — partial on live statuses),
`claim_active_recent`, `claim_by_root` (0002's
`claim_provenance_root_idx`), `claim_by_parent`, `claim_journaled`,
gist `claim_world_valid`. Pre-v2 rows were migrated forward in 0008
(free text → `observed_statement`, provenance preserved) with the SAME
mapping the `claim_written` v1→v2 upcaster applies, so live tables and
rebuilds agree.

## What KnownState serves (api/ + llm/ read side)

`views.InquiryClaim` kept every existing field (`value_or_range` is now
fed from `value_text`) and gained: `predicate`, `value_text`,
`acquisition_method`, `strength`, `hop_count`,
`contested_by_claim_id`, and (Hardening Pass 1, audit #2)
`contradiction_ids` — the FULL sorted tuple of claim ids contesting this
claim. `contested_by_claim_id` is the single LATEST contester (lossy for
multi-edge conflicts); `contradiction_ids` keeps them all. **Team F: pass
`contradiction_ids` through to the assembler; stop hardcoding `[]`.**
The claim projection gained a `contradiction_ids jsonb` column (migration
0013) accumulated by the `claim_contested` fold → claim projector_version
3. Contested pairs arrive as two active claims pointing at each other —
surface them deliberately (narrator gold);
`superseded`/`retracted` rows never reach `inquiry_claims()` (the
projection keeps them for audit, the partial indexes drop them).
`confidence` remains a display value; rank by `strength` when the
assembler starts consuming v2 fields.

## Lifecycle in one paragraph

Writes go through the store's append transaction: an identical
re-assertion on the same `(believer, subject, predicate)` becomes a
`claim_corroborated` evidence link on the existing claim (status flips
to `corroborated` ONLY when links span ≥ 2 distinct provenance roots —
one deed retold three times raises strength, never corroboration); a
conflicting value on an exclusive predicate emits
`claim_contested` both ways, or `claim_superseded` when the challenger
outweighs (fresh direct observation wins ties;
`superseded_reason ∈ better_evidence | direct_observation |
source_recanted | canon_sealed`); `claim_retracted` is terminal.
Everything is an event; the tables rebuild from the log.

## Crypto-shred read path (Team F contract)

What changed under you — WITHOUT any `api/` edit:

- `POST /api/action` responses are UNAFFECTED: `execute_command` /
  `assess_or_execute` / `confirm` hand back **plaintext** event rows
  (the owner's own turn); encryption happens only on the INSERTED row.
  `outcome_contract` gained `event_ulid` (serve it; it is the stable
  external id) — `event_id` still parses as the bigint string your
  `context.last_resolution_trace` expects.
- Anything that reads **stored** `intent_parsed` payloads (or
  `pending_confirmation.intent`) from the DB now sees
  `{"$enc": …}` markers on `intent.approach` and
  `intent.dialogue.quoted_speech`. Owner read path:
  `store.decrypt_event_payload(cur, payload)` — safe to apply
  unconditionally (plaintext passes through; post-shred it renders
  `[shredded]`). The beat's confirm path already decrypts internally.
- `ensure_account_key(cur)` (in `everquill_engine.crypto`) is exported
  so `/api/claim` can mint the key AT CLAIM TIME (call it on the
  account's world connection after bootstrap); otherwise the store
  mints it lazily at the first player-text append — both are correct,
  claim-time is tidier.
- Erasure runbook: on a deletion request, run
  `crypto.shred_account_key(cur, world_id=<the account's world id>)` on the
  OWNER connection inside the account's world schema (app_role deliberately
  cannot DELETE the key row; the world id also erases any plaintext
  `public.test_turn_capture` rows), then drop the account row. Backups need no scrubbing — without
  the DEK the ciphertext is noise. If `EVERQUILL_MASTER_KEY` is set
  (production MUST), a stolen DB backup cannot decrypt even pre-shred.
- **DEPLOY REQUIREMENT (orchestrator):** root `requirements.txt` must
  gain `cryptography>=42` (engine extra `crypto`) BEFORE the next
  deploy — the store now refuses (loudly) to append player-text events
  without it rather than storing plaintext.
- `EVERQUILL_MASTER_KEY` (64 hex chars) should be set on Railway before
  invite codes go beyond George (HIGH-8 is the hard gate for that);
  without it DEKs are stored raw (`wrap_mode='raw'`, dev-grade).

## Growth notes

`load_fold_state` now preloads claims + evidence (the lifecycle folds
and the write-time probe read them; KnownState claims work on the DB
path). Full-image loading is fine at alpha scale; if claim volume ever
hurts, move the probe to per-key lazy SQL against `claim_active_key` —
the index is already the probe's shape.
