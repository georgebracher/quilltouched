# Ticket: move the last engine decisions off the parser's free text

Written 2026-10-18 after the portfolio hardening pass. Sized for one Codex run.

## Why

Design law: no LLM call decides success, difficulty or state. The engine still
keyword-matches the parser's free-text `approach` field in four functions, frozen
in `tests/test_approach_boundary.py` (`DECISION_READS`):

| Function | Decision it makes from `approach` wording |
|---|---|
| `resolver/common.py::_intent_speech_text` | room-directed speech, info-seeking, name exchange, scope subject |
| `resolver/common.py::_matching_law` | which authored law applies (`approach_keywords`) |
| `resolver/deltas.py::_transaction_coin_delta` | purchases and coin transfers (also reads the player's own words) |
| `resolver/tier.py::decide_tier` | a targetless move stays in the room ("bar", "room") |

Matching is whole-word since 2026-10-18 ("barrel" no longer counts as "bar"), but the
parser's choice of words can still change an outcome.

## Do

1. Add closed, typed fields to `docs/contracts/intent.schema.json` (bump the minor
   version) for each decision above, for example `addressee: room | target | null`,
   `speech_act: question | introduction | statement | null`,
   `transaction: {kind: buy | give | pay_for, item_key, count} | null`,
   `invoked_law_ids: [...]` restricted to laws supplied in the parse call.
2. Mirror them in `everquill_engine/intent.py` (closed typed model; the schema
   equivalence test must stay green).
3. Teach the parser prompt (`llm/prompts/parser.md`) to fill them; update the offline
   parser path (`llm/parser.py`) only if its shape changes.
4. Switch each function in `DECISION_READS` to the typed field and delete its entry
   (the ratchet fails until you do).
5. Relabel `evals/` for the new fields and run the parser eval. Paid, but small:
   pilot 10 utterances, report the measured cost, then run the rest under a cap. Log
   the before and after in `llm/EVAL-LOG.md`.

## Done when

- `DECISION_READS` is empty and `make release-check` passes against a scratch
  Postgres (never the shared dev DB, which wipes the live world).
- The eval shows the new fields at or above the old held-out accuracy (91.7%).

## Also open, not in this ticket

Long functions left after the split: `resolver/referee.py::_rolled_or_free_outcome`
(254 lines), `resolver/referee.py::resolve_intent` (244), `resolver/tier.py::decide_tier`
(226), `api/main.py::action` (207). The dev database is still shared with the live
service (George: not yet).
