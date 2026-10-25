# API wiring notes — Round-2 HIGH fixes (orchestrator applies to `api/`)

The engine-fix crew's lane excludes `api/**`. The engine changes for EQ-R2-03
and EQ-R2-04 are landed and green; the small `api/` (and one `llm/`) edits that
let production consume them are written out here for the orchestrator to apply
verbatim. Two independent changes; apply both.

Base: committed HEAD `2b1dd2e`, `api/main.py` as shipped.

---

## EQ-R2-03 — serve the redacted public outcome to client + narrator

`everquill_engine/views.py` now exports `outcome_public(contract, *, wounds_after=None)`.
It takes the canonical `resolver.outcome_contract(...)` dict and returns an
allowlisted projection: hp deltas collapse to `wound_transition` deltas
(fiction `effect` only — never a number/cause), and flag deltas survive only
for the public allowlist prefixes (`owes_favor_/rebuffed_/noticed_by_/discovered_`).
`docs/contracts/outcome.schema.json` (v1.3) now describes THIS public shape, so
`_validated_contract` must be handed the public view, not the raw contract.

The exact hp stays in the canonical `outcome_resolved` event server-side — only
the served/narrated view is redacted. Prompt instructions cannot protect data
already in the model input, so the redaction is structural and upstream of the
narrator.

### 1. import (top of `api/main.py`, with the other engine imports)

```diff
 from everquill_engine.resolver import ResolverError, outcome_contract
 from everquill_engine.store import ConcurrencyError, decrypt_event_payload
+from everquill_engine.views import outcome_public
 from everquill_engine.world import WorldContent, load_world
```

### 2. new helper — post-resolution wound words (add near `_stored_outcome_row`)

Lets the public view say `dispatched` (a kill) instead of a bare `wounded`,
using only KNOWN-safe words (scene conditions / PC chronicle). Optional in
`outcome_public`; without it hp deltas read `wounded`/`recovered` by sign, which
is already leak-safe.

```python
def _wounds_after(known, contract: dict[str, Any]) -> dict[str, str]:
    """Post-resolution wound WORDS for entities named in the contract's hp
    deltas, so the public outcome can distinguish a kill (`dispatched`) from a
    wound. Reads only KnownState-safe words — never a raw hp number."""
    try:
        scene = known.scene(PC_ID)
    except KeyError:
        return {}
    conditions = {e.entity_id: set(e.conditions) for e in scene.entities}
    out: dict[str, str] = {}
    for delta in contract.get("state_deltas", []):
        if delta.get("delta_type") == "hp":
            entity = delta.get("entity_id")
            if "dispatched" in conditions.get(entity, ()):
                out[entity] = "dispatched"
    return out
```

### 3. `_resolved_response` — redact before validating/narrating/returning

```diff
 def _resolved_response(
     conn,
     account: accounts_mod.Account,
     world_content: WorldContent,
     command_id: str,
     result,
     intent: dict | None,
 ) -> JSONResponse:
     outcome_row = result.append_result.event_rows[result.resolution.outcome_event_index]
-    contract = _validated_contract(conn, outcome_contract(outcome_row), command_id)
+    raw = outcome_contract(outcome_row)
+    # EQ-R2-03: the client and the narrator see ONLY the redacted public view;
+    # exact hp/internal flags remain in the canonical event server-side.
+    known = read_known_state(conn, world_content)  # post-resolution image
+    contract = _validated_contract(
+        conn, outcome_public(raw, wounds_after=_wounds_after(known, raw)), command_id
+    )
     committed_intent = _committed_intent(result.append_result.event_rows, intent)
     narration, narration_meta = _narrate_turn(
         conn, account, world_content, contract, committed_intent, command_id
     )
```

(No other line in `_resolved_response` changes — `contract` is already the value
fed to `_narrate_turn` and returned as `"outcome"`.)

### 4. `_absorbed_response` — redact the re-served duplicate

`_absorbed_response(conn, account, store_command_id, command_id)` has no
`world_content` in scope, so serve the coarse public view (still leak-safe; a
duplicate re-serve does not need the `dispatched` refinement):

```diff
     outcome_row = _stored_outcome_row(conn, store_command_id)
     if outcome_row is None:
         raise HTTPException(
             status_code=409,
             detail="command_id was already used but no outcome is on record",
         )
-    contract = _validated_contract(conn, outcome_contract(outcome_row), command_id)
+    contract = _validated_contract(
+        conn, outcome_public(outcome_contract(outcome_row)), command_id
+    )
```

### 5. telemetry contract (two sites: end of `/api/action` and `/api/action/confirm`)

The `contract = outcome_contract(...)` used only for `_turn_telemetry(...)` is
server-side ops data, not a client/narrator surface, so it is not a leak. For
consistency (no exact hp in log sinks) prefer the public view; either is
correct:

```diff
-            contract = outcome_contract(
-                result.append_result.event_rows[result.resolution.outcome_event_index]
-            )
+            contract = outcome_public(outcome_contract(
+                result.append_result.event_rows[result.resolution.outcome_event_index]
+            ))
             _turn_telemetry(request, command_id, account, result, contract)
```

### 6. `llm/narration_gate.py` — teach the fallback the redacted delta

The deterministic fallback prose now receives `wound_transition` (not `hp`).
Add a branch to `_delta_sentence` (leave the existing `hp` branch in place — the
gate's own unit tests call it directly with hp deltas):

```diff
 def _delta_sentence(delta: dict[str, Any], pc_id: str) -> str | None:
     kind = delta.get("delta_type")
     entity = delta.get("entity_id")
     if kind == "hp":
         amount = delta.get("amount") or 0
         if entity == pc_id:
             return "You come away hurt." if amount < 0 else "You feel somewhat restored."
         return "Your mark comes away the worse for it." if amount < 0 else None
+    if kind == "wound_transition":
+        effect = delta.get("effect")
+        if entity == pc_id:
+            return "You feel somewhat restored." if effect == "recovered" else "You come away hurt."
+        return None if effect == "recovered" else "Your mark comes away the worse for it."
```

No change needed to `check_narration`: G2 still catches the word "hp" in the
narrator's prose, and `_context_vocab` now simply gains the words
`wound_transition`/`wounded`/`dispatched` (all admissible).

`api/tests/test_narration_gate.py` and `api/tests/test_api_pipeline.py` assert
against hp deltas / the old schema; the orchestrator should update those
api-lane tests when applying this swap (out of the engine crew's lane).

---

## EQ-R2-04 — bind command_id to its canonical intent; 409 on mismatch

`everquill_engine/beat.py` now raises `BeatIntentMismatchError` when a pending
`command_id` is re-assessed with a DIFFERENT intent, and `BeatResult` gained
`stored_intent` (the canonical intent bound to a pending beat). Migration
`0011_pending_intent_binding.sql` adds the `pending_confirmation.intent_hash`
column — **apply it before deploy** (the beat's SELECT/INSERT reference it).

### 1. import (extend the existing beat import block in `api/main.py`)

```diff
 from everquill_engine.beat import (
+    BeatIntentMismatchError,
     ConfirmationExpiredError,
     NoPendingConfirmationError,
     assess_or_execute,
 )
```

### 2. map the mismatch to 409 (in the `/api/action` handler, the
`assess_or_execute` try/except around line 1218)

```diff
             try:
                 result = assess_or_execute(
                     conn, store_command_id, intent,
                     world=world_content, character_id=PC_ID,
                 )
             except ConfirmationExpiredError:
                 raise HTTPException(status_code=410, detail=MOMENT_PASSED) from None
+            except BeatIntentMismatchError as exc:
+                # EQ-R2-04: this command_id is bound to a different pending
+                # action. Return the STORED intent (what confirmation will
+                # actually resolve), never the retry's redeclaration.
+                raise HTTPException(
+                    status_code=409,
+                    detail={
+                        "error": "intent_mismatch",
+                        "message": "this command was already assessed for a different "
+                        "action — confirm the standing assessment, or declare again "
+                        "under a fresh command_id",
+                        "stored_intent": exc.stored_intent,
+                    },
+                ) from None
             except ResolverError as exc:
                 raise HTTPException(status_code=422, detail=str(exc)) from exc
```

### 3. pending re-assess returns the BOUND intent (same handler, the
`result.status == "pending"` block around line 1235)

```diff
             if result.status == "pending":
                 _turn_telemetry(request, command_id, account, result)
                 return JSONResponse({
                     "pending_confirmation": True,
                     "world_id": account.world_id,
                     "command_id": command_id,
-                    "intent": intent,
+                    # EQ-R2-04: the intent BOUND to this pending beat (the one
+                    # confirmation resolves), never the retry's redeclaration.
+                    # Equal to `intent` on the first assess; the mismatch guard
+                    # above 409s any divergent retry before it reaches here.
+                    "intent": result.stored_intent or intent,
                     "assessment": asdict(result.assessment),
                 })
```

`/api/action/confirm` needs no change — it never re-assesses; it resolves the
stored intent under the original id.

---

## Checklist for the orchestrator

- [ ] Apply migration `0011_pending_intent_binding.sql` (adds
      `pending_confirmation.intent_hash`) before the next deploy.
- [ ] `api/main.py`: import `outcome_public`; redact in `_resolved_response`,
      `_absorbed_response`, and (optional) the two telemetry sites; add
      `_wounds_after`.
- [ ] `api/main.py`: import `BeatIntentMismatchError`; 409 branch; pending
      response returns `result.stored_intent or intent`.
- [ ] `llm/narration_gate.py`: add the `wound_transition` fallback branch.
- [ ] Refresh the api-lane tests that asserted raw-hp deltas / old outcome
      schema (`api/tests/test_narration_gate.py`, `api/tests/test_api_pipeline.py`).
- [ ] `requirements.txt` still needs `cryptography>=42` (pre-existing HIGH-8
      gate, unchanged by this crew).

---

# Sprint 3 wave 1 (Team A — engine) additions

Three read/write surfaces landed this wave. All are additive; none edits
`api/`. Base: committed HEAD after S3A engine work.

## R2-09 — narration-as-canon: the store entry point (Team F decision-3)

`everquill_engine/store.py` now exports `narrate_outcome(...)` — THE entry
point that appends the `narration_generated` event binding prose to its
committed outcome. Call it AFTER an outcome command commits and the narrator
returns prose (the outcome id/ulid must already be canon). It is idempotent by
command_id `narrate:<outcome_event_ulid>`: a retry (or a duplicate re-narration
of the same outcome) is absorbed, so prose can never fork on one outcome. Prose
is model output, not player text — it is NOT encrypted.

### exact `api/` call (in `_resolved_response`, after `_narrate_turn` returns)

```python
from everquill_engine.store import narrate_outcome

# `result` is the BeatResult; `narration`/`narration_meta` come from
# `_narrate_turn(...)`. `conn` is the request's own world connection, and the
# outcome command has already committed at this point.
outcome_row = result.append_result.event_rows[result.resolution.outcome_event_index]
narrate_outcome(
    conn,
    character_id=PC_ID,
    outcome_event_id=outcome_row["id"],
    outcome_event_ulid=outcome_row["event_ulid"],
    world_time=outcome_row["world_time"],
    prose=narration,
    assembler_version=narration_meta["assembler_version"],
    content_hash=narration_meta["content_hash"],
    location_id=outcome_row.get("location_id"),
    model=narration_meta.get("model"),
)
```

Notes:
- Do NOT wrap this in `execute_command` — it is a bare append of one already
  final event; `narrate_outcome` takes the world lock and folds internally
  (the `narration_generated` fold is audit-only — no projection materializes).
- `_absorbed_response` (a re-served duplicate turn) should NOT re-narrate: the
  original turn already logged the narration under `narrate:<ulid>`; calling
  again is harmless (absorbed) but unnecessary.
- The confirm path (`/api/action/confirm`) resolves an outcome too — wire the
  same call at the end of its resolved branch, using its `result`.

## S3A status strip — coin + active timers (Team D needs it)

`views.ChronicleFacts` now also carries `active_timers: tuple[TimerFact, ...]`
(coin + world_date were already exact-known facts). `TimerFact` = `timer_key,
kind, due_world_time, due_at` — all KNOWN-safe (the timer's kind + due stamps,
never its true-sheet payload). D's status strip reads
`chronicle_facts(PC_ID).coin` + `.active_timers` off the same KnownState the API
already builds (`read_known_state(conn, world_content)`); no engine call
changes. Migration `0012_status_strip_and_scope.sql` adds the partial index
`timer_active_by_subject` so an F `/api/facts` SQL read of a character's pending
timers is an index scan (`WHERE subject_id = %s AND status = 'pending'`).

## S3A Codex — research/appraisal Inquiry claims + leads (Teams C/F)

No new endpoint shape here (F builds `GET /api/codex` from the existing
`KnownState.inquiry_claims(...)`), but the claims research now writes are worth
flagging to whoever renders them:

- Research against a source resolves through the source's `knowledge_scope`.
  Accurate findings and confidently-wrong findings BOTH arrive at strength
  `told` (60), stamped with `source_agent_id = <source dotted id>`; ambient
  rumor stays `rumor` (35). Rank cards by `strength` as claims.md says.
- A confidently-wrong research claim uses an exclusive predicate
  (`threat_assessed`) with the error's `distortion` in `scope`
  (e.g. `ballad_inflation`). A later direct observation SUPERSEDES it
  (observed 100 > told 60) — that is the confirm/deny loop; two sources
  disagreeing surface as a `contested` pair. Render `scope` and the
  contested link; never invent the contradiction.
- An out-of-scope research yields a LEAD: one claim whose `subject_entity_id`
  is the better source/location and whose `scope == "lead"`. Render `scope ==
  "lead"` claims as research-target chips pointing at that subject — not as
  facts about it.
- Appraisal reveals are stamped `scope == "appraisal_tier_<n>"`; a
  `predicate == "weak_point"` claim is the deep truth that unlocks a
  knowledge-gated action (the engine already applies the modifier — D just
  shows the newly-available/altered action).
