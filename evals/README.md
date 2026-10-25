# Everquill Eval Sets (Sprint 0 — C0.2; expanded Sprint 1 — C1; held-out + narration Sprint 2)

Golden data for the parser eval harness. Parser quality is the project's named boss fight (roadmap §7): this set gates every prompt and contract change from Sprint 1 onward. Sprint 1 expanded it from 20 to 50 cases against **intent schema v1.1** (`rest` action_type added; gu-020 re-pinned from `meta` to `rest`) and runs the prototype parser in `llm/` against it offline — no production wiring.

## Sprint 3 additions

- **`heldout-2.jsonl`** — 30 NEW cases (ho-001..ho-030), a SECOND held-out set authored WITHOUT reading prompt p9's worked examples (the contamination caveat the Sprint-2 log raised: p9 had steered one held-out round, so a truly uncontaminated read needs a set the prompt has never referenced). Focus: research/observation phrasings the prompt was never tuned on (`look into`, `ask around about`, `study the`, `check the records for`, `what do they say about`, `dig up`, `read up on`, `consult`, `pore over`, `find out what … believe`, `look … up in the archive`), plus a spread across the enum incl. the research-vs-dialogue boundary trap (`Ask [named person] about X` = dialogue, `ask around about X` = research), a feint, an impossible attempt, and one research-flavoured injection. Safety gates in `parser_eval.py::SAFETY_GATES["heldout-2"]` (plausibility ho-025, quoted ho-020/021, injection ho-030; the feint gate on ho-023 was dropped 25 Oct 2026 when ambiguity flags stopped claiming to force a confirmation). Run with `llm/parser_eval.py --file evals/heldout-2.jsonl`. Baseline (untouched p9): **91.7% field-level, gate FAIL on one quoted-speech miss** — logged in `llm/EVAL-LOG.md`. NOT iterated on: this set measures true accuracy and must stay unreferenced by the prompt.

## Sprint 2 additions

- **`fog-utterances.jsonl`**: 6 cases (fo-001..fo-006, 25 Oct 2026) run against the Harrowdown tavern as production sends it before any name is learned (`parser_eval.py::FOG_ROSTER`, pinned to the live roster builder by `api/tests/test_fog_aliases.py`). Unlearned people are `person_N` aliases; the cases check that descriptor references resolve to the alias as target, addressee and topic. Authored after prompt p13 and not tuned against. Run with `llm/parser_eval.py --file evals/fog-utterances.jsonl`.
- **`heldout-utterances.jsonl`** — 50 NEW cases (hu-001..hu-050) the parser prompt has never referenced, same schema and fixture roster as the goldens. Answers the Sprint 1 contamination caveat. Includes a 5-case injection block (hu-046..hu-050): instruction-override, system-prompt fishing, a tool-schema escape attempt, player-typed `<<System>>` markup, and an injection payload inside quoted dialogue. Safety gates for this set (defined in `llm/parser_eval.py::SAFETY_GATES`) add an injection gate: schema-valid + exact action_type — the utterance is data, never instructions. Run with `llm/parser_eval.py --file evals/heldout-utterances.jsonl`. Baseline-before-iteration discipline and all runs are logged in `llm/EVAL-LOG.md`.
- **`narration-fixtures.json`** — 20 narrator fixtures, each carrying an assembler view (the adapter shape documented in `llm/assembler.py`), the parsed-action slice, and a schema-valid `ResolvedOutcome`. Coverage: every `tier_resolved` value (incl. a dispatched trivial no-op, both hopeless dice flavors, sealed met/unmet, two impossible attempts), multiple misses, and one fixture (nf-18) with an injection payload embedded in the player's approach text and quoted speech. Consumed by `llm/narrator_eval.py`, which re-assembles each view deterministically, validates both contracts, narrates on claude-sonnet-5, and lints per `docs/research/ai-tells-fiction.md` (c). Regenerate only through the assembler so envelopes stay schema-valid.

## Schema v1.3 relabel (2026-10-24)

Every case in all three sets carries the six closed fields from intent schema v1.3
(`addressee`, `speech_act`, `topic_ids`, `transaction`, `invoked_law_ids`,
`movement_scope`). The harness supplies Topics, Prices and Laws lists for the fixture
world (`llm/parser_eval.py::LISTS`) alongside the roster below, and reports the v1.2
fields and the v1.3 fields as separate subtotals so new runs compare like with like
against the v1.2 baselines. Labelling rules are the p12 prompt's: speech fields only on
`dialogue`/`social`, topics only on questions, movement scope only on `movement`. The
golden labels and prompt p12 were committed before the held-out sets were labelled.

## Format — `golden-utterances.jsonl`

One JSON object per line:

| Field | Meaning |
|---|---|
| `id` | Stable case id (`gu-NNN`). Never reuse or renumber — eval history hangs off these. |
| `utterance` | Exactly what the player typed (or what a tap pre-seeded into the composer). |
| `expected_intent` | The golden parse, conforming to `docs/contracts/intent.schema.json`. |
| `notes` | Why the case exists, what it traps, and any scoring caveats. |

Every `expected_intent` machine-validates against the intent schema (all fields present; absence = `null`/`[]`).

## Fixture roster

Entity IDs resolve against a fixed golden-world roster the harness supplies with every parse call (the parser never invents IDs — in production it receives the scene manifest / Pack / Codex roster the same way). Roster state is per-case; cases are independent (e.g. the shortsword is on the smith's rack in gu-015 and in the pack in gu-016).

| ID | What |
|---|---|
| `npc_guard_captain_bren` | Guard captain at the duke's gate |
| `npc_gate_guard_tam` | Young gate guard; `itm_gate_keys` visible at his belt |
| `npc_librarian_esme` | Librarian at the Dunmere archive |
| `npc_barkeep_odo` | Tavern barkeep |
| `npc_smith_harl` | Smith; `itm_shortsword` on the rack |
| `npc_aldric` | Dead former companion, grave in Dunmere |
| `crt_dragon_vermithrax` | The dragon |
| `crt_ash_wolf` | Wounded ash-wolf |
| `itm_gate_keys`, `itm_shortsword`, `itm_potion_red_small`, `itm_rabbit_carcass` | Items |
| `crt_tavern_cat` | The tavern's cat |
| `itm_whetstone` | Whetstone on the smith's bench |
| `obj_practice_post`, `obj_stable_wall`, `obj_campfire`, `obj_water_trough`, `obj_ale_barrel` | Scene objects |
| `loc_market_square`, `loc_dunmere_archive`, `loc_monastery_pass`, `loc_inn_dunmere` | Locations |
| `hyp_dragon_soft_underbelly` | Player hypothesis card (Codex) — hypothesis IDs are legal research targets |

## Case map (50)

- **gu-001 / gu-002 — the misparse trap pair.** "Feint" vs "fight" toward the dragon: near-identical surface, distinct intents. The feint carries `could_be_feint_or_fight` and a deception-preserving `approach`; the fight carries neither. Both are `plausible` — tiering (hopeless) is the engine's job.
- **gu-003 — god-mode.** `impossible_in_fiction` hint; `social`, not `meta` (an in-fiction proclamation, deed-logged, System mockery licensed by the engine).
- **gu-004 — quoted dialogue vs action split.** Verbatim speech lands in `dialogue.quoted_speech`, never paraphrased into `approach`.
- **gu-005 — research targeting a hypothesis.** Archive + hypothesis card as targets; parser never invents research hours.
- **gu-006 — training with duration.** `until_condition` bound verbatim for the engine's caravan clock.
- **gu-007 — compound action.** Primary type + `compound_action` flag + all targets; decomposition policy is an open Sprint 1 question with Team A.
- **gu-008 — tap-seeded composer.** Speak-verb pre-seed; paraphrase keeps the dialogue object with `quoted_speech: null`.
- **gu-009 — inventory/Pack interaction.** Item ID from the Pack.
- **gu-010 — travel commitment.** Departure time is not a duration; engine prices the route.
- **gu-011 — sealed-feat attempt.** Resurrection rite: `dubious`, never `impossible_in_fiction` — sealed is legal fiction that fails forward.
- **gu-012–gu-020 — everyday trivial/routine variety** covering the rest of the `action_type` enum: barkeep order (social), look around (observation), climb (movement), haggle (social), sharpen (craft), track (observation), "Where am I?" (meta), cook (craft), rest-until-morning (`rest` since v1.1, + duration).

### Sprint 1 expansion (gu-021–gu-050)

- **gu-021, gu-022, gu-038 — rest/wait cases** for the new v1.1 `rest` action_type (bare wait with until-condition; nap with no bindable span; idiomatic "kill some time"). With re-pinned gu-020 that's four `rest` cases.
- **gu-023–gu-026, gu-050 — quoted-vs-paraphrase splits:** quoted whisper with first-name addressee resolution (gu-023), paraphrased instruction (gu-024), quoted shout to the room / `addressee_id: null` (gu-025), paraphrased info-probe (gu-026), quoted vow at a grave (gu-050).
- **gu-027–gu-031 — research/train/travel variety:** first two `explicit`-mode `duration_hint` cases (gu-027 "for three hours", gu-028 "the evening"), research with a location-as-subject (gu-028), trivial in-town movement (gu-029), travel with an unresolvable prop (gu-030 — the horse must not become an id), training with no resolvable target (gu-031).
- **gu-032–gu-038 — ADVERSARIAL block (7):** contradictory negation trap "I definitely don't stab him (I stab him)" (gu-032, MUST flag `contradictory_negation`), double negative resolving affirmative (gu-033), sarcasm typed as a declaration (gu-034, MUST flag `sarcasm_or_literal`, stays `plausible`), emoji/chat noise (gu-035), typo storm (gu-036), dictation disfluencies + "make my character" wrapper (gu-037), idiom "kill some time" (gu-038).
- **gu-039–gu-043 — mundane trivial block (5):** wash face, count coins (meta Pack query), stretch, pet the cat, warm hands.
- **gu-044, gu-045 — two more compound actions:** barrel-shove + bolt (physical+movement), distract-the-smith + pocket-whetstone (social+theft, mirrors gu-007). Both pin primary type + `compound_action` + all targets per the v0 ruling.
- **gu-046 — second sealed-feat attempt:** carving a soul anchor (resurrection-law component prep) — `dubious`, never `impossible_in_fiction`.
- **gu-047 — assessment observation** with a stat, aimed at a person.
- **gu-048 — ambiguous addressee:** "the guard" with two guards in the roster — `addressee_id: null`, empty targets, `ambiguous_addressee` flagged.
- **gu-049 — second impossible-tier case** (arm-flap flight) pairing with gu-003 for the safety-critical plausibility check.

Enum coverage: all ten `action_type` values appear at least once (incl. `rest` ×4); all three `plausibility_hint` values appear (`impossible_in_fiction` ×2, `dubious` ×2); both `duration_hint` modes are exercised (`until_condition` ×6, `explicit` ×2).

## Scoring policy (v0)

- **Exact-match fields:** `action_type`, `target_entity_ids` (set equality), `plausibility_hint`, `ambiguity_flags` (set equality), `dialogue.addressee_id`, `duration_hint.mode`.
- **Verbatim-preserving:** `dialogue.quoted_speech` — wording must survive; normalized casing/punctuation allowed. `duration_hint.text` must preserve the stated condition.
- **Judged loosely:** `approach` is free text — score on whether load-bearing nuance survives (the feint's deception, the compound's dual purpose), not string match. `stat_hint` is advisory and PROVISIONAL; mismatches are warnings, not failures, until Team A locks the aptitude list.
- **Documented near-misses:** some category calls are genuinely arguable (gu-014 movement-vs-physical, gu-017 observation-vs-movement). The golden answer pins one so drift is visible; a near-miss on exactly these flagged cases is review-worthy, not an auto-fail. Cases whose notes say MUST are hard failures.

## Regeneration / validation

No prompts or API calls live in this directory. To re-validate the set against the contract after edits:

```bash
python3 -c "
import json, pathlib
from jsonschema import Draft202012Validator  # pip install jsonschema
schema = json.loads(pathlib.Path('docs/contracts/intent.schema.json').read_text())
v = Draft202012Validator(schema)
for n, line in enumerate(pathlib.Path('evals/golden-utterances.jsonl').read_text().splitlines(), 1):
    case = json.loads(line)
    assert set(case) == {'id', 'utterance', 'expected_intent', 'notes'}, (n, 'line keys')
    errs = list(v.iter_errors(case['expected_intent']))
    assert not errs, (case['id'], [e.message for e in errs])
print('golden set OK')
"
```
