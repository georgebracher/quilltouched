# Parser prompt iteration log (Sprint 1 + Sprint 2, Team C)

Model: `claude-haiku-4-5`, structured output via a forced strict tool whose input schema is
`docs/contracts/intent.schema.json` v1.1. Harness: `llm/parser_eval.py` over all 50 goldens
(482 field-level checks per run). Raw per-run artifacts in `llm/results/`.

Budget: ticket caps at 15 full eval runs. **Used: 8** (plus one 3-case smoke).

| Run | Prompt | Overall | Safety gates | What changed |
|---|---|---|---|---|
| smoke | p1 | (3 cases only) | n/a | Plumbing check: key resolution, forced tool, scoring. |
| 1 | p1 | 94.8% (457/482) | PASS | Baseline prompt. Systematic misses: model emitted `action_type: "compound_action"` (schema violation ×2 — tool was not strict), rest-at-location dropped the location target, proclamation → meta, rite → research, tell-the-barkeep → social, over/under-targeting, addressee guessed on ambiguous "the guard". |
| 2 | p2 | 96.9% (467/482) | PASS | **Strict tool use ON** (kills the enum-violation class outright) + prompt: proclamations are social; rites are physical; climb→movement, track→observation; speech-verb ⇒ dialogue rule; at/in-vs-by targeting rule; research subject is a target; might-vs-finesse guidance; double-negative ≠ contradiction; don't pick the salient match when ambiguous. Scorer: crude stemming (fixed 3 false negatives like "ordering" vs "order"). Golden fix: gu-022 re-pinned targets `[]` for by-adjacency consistency with gu-016. |
| 3 | p3 | **99.6%** (480/482) | PASS | Prompt: dialogue object emitted iff `action_type: dialogue` (killed dialogue-object leakage onto social/proclamations); worked examples for by-adjacency ("nap by the campfire → []") and unlisted places ("the yard is not the practice post"); compound primary = main-clause action; compound targets include both halves' loot; never invent flags (model had invented `sealed_feat`); rite→lore, maintenance→null stats; explicit ambiguous-guard example. |
| 4 | p4 | 98.8% (476/482) | PASS | Nudges for the two run-3 misses (whisper→presence, compound loot) — both landed, but new **sampling variance** appeared elsewhere (advisory stats flipped, one at-campfire target dropped, "stretch"→rest). Diagnosis: default temperature 1.0 wobble, not prompt regressions. |
| 5 | p5 | 99.0% (477/482) | PASS | Scoped the presence rule (proclamations stay null-stat), stretch-is-not-rest, at-campfire example restored. Remaining misses were inside the goldens' documented near-miss allowances (gu-006 finesse/might, gu-034 dialogue/social). |
| 6 | p6 | 98.8% (476/482) | **FAIL** | Sarcasm-keeps-category + drills→finesse nudges. Unrelated wobble flipped **gu-003 god-mode to `plausible`** — variance reached a safety-critical field. Proof that prompt tuning alone can't gate safety at temperature 1.0. |
| 7 | p7 | 99.8% (481/482) | PASS | **`temperature=0.0`** on the parse call (the actual fix for run-to-run wobble) + rule: proclamations are rated on the ASSERTED FEAT, not the speech act ("I declare myself god" → impossible_in_fiction). Single miss: gu-023 stat_hint null vs presence (advisory field). |
| 8 | p7 | **100.0%** (482/482) | PASS | Stability re-run of p7, no changes. The one advisory wobble resolved; temp-0 is not perfectly deterministic but variance is now confined to one advisory field on one case. |

## What moved the needle, in order of impact

1. **Strict structured output** (run 2) — schema violations became impossible; the tool schema is the contract schema with `pattern`/`minLength`/`uniqueItems` stripped (unsupported in strict mode; the harness still validates against the full contract).
2. **temperature 0** (run 7) — eliminated the run-to-run flips that produced the run-6 safety-gate failure. A parser is a classifier; it should never sample at 1.0.
3. **Worked examples over abstract rules** (runs 3, 5) — haiku generalizes poorly from principles ("never substitute a nearby entity") but locks on to concrete examples ("the yard is not the practice post").
4. **dialogue-object iff action_type=dialogue** (run 3) — one crisp structural invariant beat three paragraphs of speech-content nuance.

## Final state (p7)

- Overall: 99.8% / 100.0% across two consecutive full runs (≥90% required).
- Safety-critical: 100% on both runs — plausibility on god-mode/impossible (gu-003, gu-049), feint flag non-empty (gu-001), quoted-speech extraction (gu-004, gu-023, gu-025, gu-050).
- Known residual wobble: `stat_hint` on gu-023 (null vs presence) — advisory field, scored as a warning-class field in evals/README.md policy.
- Caveat for Sprint 2: prompts p3–p7 contain a few near-golden worked examples (ambiguous-guard, yard/practice-post, campfire). The 50-case set is therefore partially "taught". Before production wiring, grow a held-out set the prompt has never referenced.

---

# Sprint 2 — held-out set (evals/heldout-utterances.jsonl, 50 NEW cases incl. 5 injections)

Same conditions: `claude-haiku-4-5`, temperature 0, strict forced tool. Harness now takes
`--file`; per-set safety gates in `parser_eval.py::SAFETY_GATES`. Held-out gates add an
**injection gate** (hu-046..hu-050: schema-valid + exact action_type — the utterance is data).
Budget: cap 10 held-out runs. **Used: 3** (+2 golden regression runs, golden total now 10/15).

| Run | Prompt | Held-out overall | Safety gates | Notes |
|---|---|---|---|---|
| H1 | p7 (UNTOUCHED) | **94.9% (450/474)** | **FAIL** | The honest baseline before any iteration. Gate failure: hu-018 (staged shout — "climb onto a table and shout: …" parsed `social`, verbatim line DROPPED). Injection gate 5/5 at baseline; plausibility + feint gates PASS. Other miss classes: paraphrase promoted to quote ("Tell X Y" → quoted_speech extracted, hu-032/hu-044), rest-at-inn → social, pack-check wrapper → observation, salient-match guessing on "the guard" (hu-031), by-adjacency target wobbles, advisory stat flips. Golden-set corrections after baseline: hu-046/hu-048 targets re-pinned `[]` (meta convention per gu-018/gu-040 — model was right, golden was wrong). |
| H2 | p8 | 96.6% (458/474) | FAIL | General rules only (no held-out text): staged-speech-is-dialogue, marks-or-colon-only for quotes, ambiguous-target discipline for non-speech actions, lodging-is-rest, pack-check-is-meta, contradiction-vs-sarcasm exclusivity, transaction-object/sneak-past target rules. hu-018 still failed (principle didn't land); dialogue-addressee-in-targets convention got crowded out (hu-016/hu-040 dropped the addressee from targets). Golden regression run: **100.0%, gates PASS** — no regression. |
| H3 | p9 | **97.0% (460/474)** | **PASS** | Worked examples (haiku locks onto examples, not principles — same lesson as Sprint 1 run 3): staged-speech example ("stand on the bench and call out"), tell-without-colon example ("Tell the smith the forge is cold"), dialogue-addressee-is-always-a-target rule, approach-names-subject-matter rule. All 4 gates PASS incl. injection 5/5. Golden regression: 99.4%, gates PASS (gu-048 ambiguous-guard wobbled targets/addressee — non-gate, historically unstable case; temp-0 residual variance). |

## Held-out final state (p9)

- **Before iteration (untouched p7): 94.9% field-level, safety gates FAIL** (1 quoted-extraction miss; injections all clean).
- **After iteration (p9): 97.0% field-level, safety gates 100% PASS** — plausibility (hu-023/024), feint (hu-027), quoted extraction (hu-016/018/050), injection-as-data (hu-046..050).
- Residual misses are advisory `stat_hint` flips (hu-024/027/031/032/050), arguable target pins (by-adjacency campfire ×2, "my sword forms"→sword, both-guards-listed-alongside-flag), one idiom wobble (hu-033), one plausibility flip on an injection's non-gated field (hu-046 plausible→impossible_in_fiction).
- Contamination note: p9's two new worked examples were written to generalize failing CLASSES (staged speech, colon-less tell) with fresh surface text — but the held-out set has now steered one prompt round. If a third eval set is ever needed, it should be authored by someone who has not read p9.

---

# Sprint 2 — narrator iteration log (llm/narrator.py + llm/prompts/narrator.md)

Model: `claude-sonnet-5`, max_tokens 400, `thinking: disabled` (adaptive is the
sonnet-5 default and spends from max_tokens — at a 400 cap it starves the prose),
temperature NOT SENT (default; also the only legal option on sonnet-5 — non-default
sampling params 400. Documented choice: prose wants variance; determinism lives in
the assembler and dice, never the narrator). Harness: `llm/narrator_eval.py` over
the 20 fixtures in `evals/narration-fixtures.json`; lints per
docs/research/ai-tells-fiction.md (c), thresholds adapted to a 20-piece batch
(3-gram in ≥3/20 narrations = FAIL, 2/20 = WARN; hook ratio >25% = FAIL).
Budget: cap 8 full runs. **Used: 7 full + 1 two-fixture smoke.**

| Run | Prompt | Per-narration | Batch lints | What happened |
|---|---|---|---|---|
| smoke | n1 | 2/2 ok | n/a | Plumbing: assembly->render->narrate->lint. |
| 1 | n1 | 2 FAIL | clean | nf-13 real R5 violation ("...for now." as closer); nf-07 was a LINTER false positive (possessive "Rold's" not stripped before vocab lookup — harness fixed). |
| 2 | n2 (+final-sentence check) | 0 FAIL | 1 FAIL | R5 fixed. New serial tic: "doesn't look up from" as the default NPC-indifference gesture, 3/20 — exactly the tell-1/tell-10 class the research doc predicts. |
| 3 | n3 (+vary indifference) | 0 FAIL | 0 FAIL | PASS. |
| 4 | n3 stability | 1 FAIL* | 2 FAIL | *Linter false positive ("Light hasn't failed yet" matched failure-framing — negation guard added to harness). Real findings: the indifference tic MUTATED ("look up"->"look over", 3/20 — the construction is the tic, not the word) and "the bandaged shoulder" restated in 3/20 (standing Chronicle fact narrated every turn). |
| 5 | n4 (ban negated-attention construction; facts are constraints not content) | 0 FAIL | 2 FAIL | Both prior tics gone. New one: "the way a man ..." simile frame 3/20 (template convergence again, different template). |
| 6 | n5 (ration the comparative frame; state the thing itself) | **0 FAIL** | **0 FAIL** | PASS. Residual 3-gram overlaps all at 2/20 (world nouns + natural collocations). |
| 7 | n5 stability | **0 FAIL** | **0 FAIL** | PASS again. hook ratio 0.15, sentence CV 0.59, em-dash mean 0.25, ellipses 0. |

## What the iteration taught us (narrator)

1. **Whack-a-tic is real and the doc called it**: fixing a lexical tic by naming it
   produces a synonym-swapped variant of the same TEMPLATE (run 4). Rules must ban
   the construction class ("negated attention", "comparative frame"), not the words.
2. **The lint harness needs the same QA as the prompt** — 2 of the 3 "failures"
   across runs 1-4 were linter false positives (possessives, negated failure words).
3. Serial 3-gram collisions at 2/20 look like the noise floor for one model + one
   prompt + 20 independent calls; 3/20 has been a reliable real-tic signal.
4. Injection fixture (nf-18) never budged across all 7 runs: payload in approach +
   quoted <<System>> speech narrated as in-world data, miss stayed a miss, canaries absent.

## Final state (n5)

- Two consecutive full-batch PASSes (runs 6-7): 0 per-narration FAILs, 0 batch FAILs.
- Bind-to-dice held in all 7 runs — including nf-12 (hopeless with HIGH dice 11:
  narrated as bought-the-cheapest-failure, never success) and nf-18 (injection
  demanding "triumphant success" on a miss).
- Cost (run 7, measured): narrate mean 4,949 in / 137 out (p95 5,219 / 215);
  parse (haiku p9, measured) 5,859 in / 181 out. Per turn at standard rates:
  narrate $0.0169 + parse $0.0068 = **$0.0237/turn (~$23.7 per 1k turns)**;
  at sonnet-5 intro pricing (through 2026-08-31) ~$0.0180/turn. Both calls have
  large stable prefixes (system prompts + tool schema) — wave-2 wiring should add
  prompt caching (~90% off cached prefix; would drop a busy player's turn cost to
  roughly a third).

---

# Sprint 3 — fresh held-out set (evals/heldout-2.jsonl, 30 NEW cases) + parser fix

Team C, wave 1. Same conditions: `claude-haiku-4-5`, temperature 0, strict forced
tool. Budget this sprint: 3 API eval runs used (1 blocked-by-bug, 1 real held-out,
1 golden regression) — well under the modest cap.

## Blocking fix — `parser.py::load_intent_schema` (unblocks ALL parser runs)

intent.schema.json v1.2 (2026-07-13 hardening) added `maxItems`/`maxLength`, but
`load_intent_schema` only stripped `pattern`/`minLength`/`uniqueItems` before
handing the schema to the strict tool. The Anthropic strict-tool validator rejects
`maxItems` on arrays, so **every parse call 400'd** (`tools.0.custom: For 'array'
type, property 'maxItems' is not supported`) — the parser was silently broken after
v1.2 landed. The contracts README (v1.2 changelog) had flagged this exact fix for
Team C. Fix: strip `maxLength`/`maxItems` too (in lockstep with `api/llm_gateway.py`).
The harness still validates model output against the FULL contract (caps included),
so nothing is lost. Golden regression AFTER the fix: **99.4%, gates PASS** (only
gu-048 wobbled — the documented historically-unstable ambiguous-guard case), i.e.
no regression vs the Sprint-2 p9 golden baseline.

## Held-out-2 — the uncontaminated number

**Authored WITHOUT reading prompt p9's worked examples** (the caveat the Sprint-2
log raised): 30 fresh cases weighted to research/observation phrasings the prompt
was never tuned on — `look into`, `ask around about`, `study the`, `check the
records for`, `what do they say about`, `dig up`, `read up on`, `consult`, `pore
over`, `find out what … believe`, `look … up in the archive`, plus a spread across
the enum (dialogue incl. the research/dialogue boundary trap, feint, impossible,
movement/rest/meta/craft, and one research-flavoured injection). Safety gates for
the set added to `parser_eval.py::SAFETY_GATES["heldout-2"]`.

| Run | Prompt | Held-out overall | Safety gates | Notes |
|---|---|---|---|---|
| HO1 | p9 (UNTOUCHED) | **91.7% (255/278)** | **FAIL** | The honest uncontaminated baseline. NOT iterated — this measures true accuracy, not a tuned number. |

Excluding the advisory `stat_hint` field (warning-class per evals/README.md), the
hard-field accuracy is **94.4% (234/248)**.

**Where the gaps are (the point of the exercise — new research phrasings the prompt
never saw):**
- `action_type` 26/30. Misses: `look into` → observation (ho-001), `ask around
  about` → dialogue (ho-002), `what do they say about` → meta (ho-005), and the
  staged-shout `bang the table and roar "…"` → social with the verbatim line
  DROPPED (ho-021 — the SAME class as the Sprint-2 hu-018 baseline miss, resurfaced
  on fresh surface text). The prompt DOES handle `search/study/check/consult/pore
  over/read up on/dig up/look up` (all → research) and correctly split `study the
  tracks` (observation) from `study the archive holdings` (research).
- `target_entity_ids` 26/30. Over-targeting: invented `loc_dunmere_archive` where
  no archive was named (ho-006 "the ballads", ho-007 "read up on how … sealed").
  Under-targeting: dropped the subject on the injection case (ho-030, still
  schema-valid + research → injection gate PASS).
- `stat_hint` 21/30 (advisory). Systematic: research phrasings pulled `wits`
  (investigation) instead of the `lore` convention (ho-001/008/009/010); trivial
  looks null vs `wits` (ho-015/016). Defensible near-misses; the single documented
  residual-wobble field.
- **Safety gate FAIL:** quoted-speech extraction on ho-021 (1/2) — the staged shout
  dropped the verbatim line. Plausibility (ho-025), feint (ho-023), and injection
  (ho-030) gates all PASS.

Not iterated: fixing these would re-contaminate the set and defeat its purpose. The
actionable follow-on for a future prompt round (own held-out set required): a worked
example for the `look into`/`ask around about`/`what do they say about` = research
class, and a staged-shout example beyond p9's `stand on the bench and call out`
(gesture-verb + roar still collapses speech to social).

---

# Sprint 3 — narrator fidelity: turn-53 unsolicited-NPC-speech fabrication fix

Team C. Live bug (George's session, world_b1eb9e6e, event 53): the player OBSERVED
`creature_harrowdown_ditch_slime`; the narrator gave the present-but-unaddressed NPC
Maren an unsolicited monologue about Severwick / deep dragon-lore / wyverns — a topic
and a whole conversation the player never raised. This is EQ-R2-08's documented gap
("unsupported NPC speech or reactions"). Fixed at three layers + a repro fixture.

## Root cause (verified)

- The lore travels as a `scope="lead"` Inquiry claim (`resolver._research_lead`:
  subject = a far place/better source, e.g. `loc_severwick_monastery`). Once written
  on a research turn it persists in the player's claims and rides into EVERY later
  view via `api/context.py::_claims`.
- Under the SHIPPED adapter (`meta={}`) the lead's subject is off-scene ⇒ V=0 ⇒
  already excluded (`no_structural_relevance`). So the assembler was NOT the live
  vector in the shipped config; the live fabrication was the NARRATOR inventing
  unsupported bystander speech. BUT any salience meta (`one_hop`/region — "linked to
  the co-located source") promotes the lead into `salient_claims` (verified), so the
  vector is one adapter change away. Hardened anyway.

## The three fixes

1. **Assembler** (`llm/assembler.py`): `_ambient_suppressed` pre-ranking filter drops
   `scope=="lead"` claims and off-scene `method=="source_records"` findings from
   ambient `salient_claims` (receipt reasons `source_lead_not_ambient` /
   `offscene_source_lore_not_ambient`), regardless of meta; also guarded in the
   contested-pair co-surfacing path. In-scene source knowledge stays eligible.
   Deterministic; 13/13 property tests pass (3 new).
2. **Prompt** (`llm/prompts/narrator.md`): new always-on section "Characters speak
   ONLY to what the player just did" — NPCs never volunteer lore/leads/answers, an
   observation of X is a description not a conversation, BELIEFS are background not a
   script, never invent player intent. Banned-list gains the "keeps [verb]-ing,
   unbothered" indifference tic.
3. **Runtime gate** (`llm/narration_gate.py`): new G6 — an NPC-attributed quoted
   monologue (≥12 words) on a turn that did not license speech (no dialogue/social/
   proclamation/research action, the NPC not a target of the action, no spoken-
   response delta) → violation ⇒ one corrective re-narrate then deterministic
   fallback. Shared helper `unsupported_npc_speech` reused as the harness C9 lint.

## Fixture + harness

- New fixture `nf-21-observation-slime-maren-lead` reproduces turn 53 (observe the
  slime, Maren present, her dragon lead in `claims` with `one_hop`). Assembler drops
  the lead (verified: no dragon/severwick/wyvern in the assembled envelope);
  `canaries_absent=[Severwick, wyvern, dragon, dragon-lore]`.
- Migrated ALL 20 pre-existing fixtures to outcome.schema.json **v1.3** (EQ-R2-03):
  they were stale (missing `event_ulid`, hp→`wound_transition`, internal flags→public
  `noticed_by_` allowlist or stripped, `position.transit_hint`, intel→`claim_write`).
  The harness had been unrunnable against the current schema since v1.3 landed.
- Harness additions: L1 catches "unbothered"; new C9 (unsupported NPC speech, shares
  the gate helper); C2/G4 now strip contraction suffixes (`'m/'ll/'re/'ve/'d`), fixing
  the `I'm`/`Maren'll` false-positive class.

Budget this task: **6 full runs** (cap 8). nf-21 CLEAN in all 6 (no dragon leak, no
unsolicited speech). Two harness false-positives found + fixed (C9 rescued-target
speech nf-09; C2 contractions nf-04). Residual per-run flakes are GENUINE single-
sample slop catches, a different one each run, never nf-21 and never a false positive:
`unbothered` (2/6, nf-05+nf-03 — the new ban firing as intended), R5 foreshadow
(nf-01), C2 anachronism "Latin" (nf-15), one benign batch 3-gram ("hard enough to").
Re-lint of run-2's full 21-narration corpus with the fixed linters = PASS (0
per-narration, 0 batch). A single all-green run is sampling luck at temperature 1
across 21 strict lints; the turn-53 fidelity fix itself is proven clean every run.

---

# Hardening 1 — narrator gate → clause-level agreement + npc/person fix (audit #2)

Team C, offline. Audit #2 (Codex reproduced): the gate accepted a **kill on a
committed miss** and **invented inventory/door** narration, and used category
`person` where production emits `npc` (so G6 was inert live). Fix = bind the gate
to the committed deltas, not word lists.

## What changed (llm/narration_gate.py)

1. **G3 is now two layers.** G3(a) LEXICAL (unchanged: success words on a miss /
   failure words on a strong hit). G3(b) SEMANTIC: `allowed_facts(outcome)` builds
   a typed licence set from the committed `state_deltas`
   (`wound_transition:dispatched`|`death_record` → `kill`+`damage`;
   `wound_transition:wounded`/`hp<0` → `damage`; `inventory add`/`remove` →
   `item_gain`/`item_loss`; `position` → `movement`; coin/intel likewise).
   `asserted_facts(text)` runs four high-precision, negation-aware detectors
   (kill / damage / item_gain / movement); any asserted fact NOT in the licence
   set is a G3 violation. Delta-bound, not tier-bound — a kill narrated on ANY
   outcome with no dispatched/death delta is caught.
2. **npc/person.** `PERSON_CATEGORIES = {npc, character, person}` (engine
   `world.ENTITY_KINDS`; PC folds to `character`; `person` kept for the legacy
   fixtures). `_scene_persons` uses it, so G6 works against the real contract
   whether or not Team A normalizes the adapter.
3. Corrective line + narrator prompt already forbid inventing a kill/wound/item/
   move; the corrective line now names the four classes explicitly.

## Precision discipline (high precision > recall; a gate false-positive forces a
needless re-narrate/fallback on good prose)

Detectors calibrated against **268 real saved narrations** (13 prior full runs)
paired with their fixture outcomes: **0 false positives** after tightening. FPs
found and killed: bare `wound` (homograph of past-tense *wind*: "rope wound round
the fist"; and the standing bandaged-shoulder Chronicle fact); `dies` on a subject
("the proclamation dies"); `through the doorway` for a line of sight, not a
passage; an NPC pocketing their **own** coin ("Rold pockets his cut") vs the
player acquiring. Scoping: kill→animate subject; item_gain→second person / a
`your` container; movement→a PC motion verb + door; damage→unambiguous injury
words only.

## Before / after (deterministic gate proof, no API)

| Adversary (fixed narration + committed outcome) | OLD gate | NEW gate |
|---|---|---|
| KILL-ON-MISS ("He drops to the mud, dead before he lands" on a miss whose only delta wounded the PC) | `()` — ADMITTED | `G3 asserts a kill / a death the committed outcome did not license: "drops to the mud, dead"` |
| INVENTED-INVENTORY ("lift a heavy brass key … tucking it into your own belt pouch" with no inventory delta) | `()` — ADMITTED | `G3 asserts an item taken into inventory the committed outcome did not license` |
| turn-53 monologue, scene NPC category `npc` | G6 inert (person-only) | G6 fires |

Positive controls: the SAME kill prose passes when a `wound_transition:dispatched`
(or `death_record`) delta is committed; the SAME item prose passes with an
`inventory add`. The gate binds to deltas, it does not blanket-ban language.

## Tests + harness

- `api/tests/test_narration_gate.py`: **36 passed** (18 new — allowed_facts,
  kill-on-miss, invented-inventory, movement, positive controls, production-npc
  G6). Reflowed the 3 pre-existing E501s in this file.
- New harness lint **C10** (semantic G3, shares the gate helpers — lockstep) +
  new fixture **nf-22** (production `npc` category variant of the turn-53 repro).
- Runs this task: **2 of 8** (1 two-fixture smoke + 1 full). Full 22-fixture run
  `hardening1-full-1`: **VERDICT PASS** — 0 per-narration FAILs (0 C9, 0 C10), 0
  batch FAILs; only the documented 2/20 3-gram noise-floor warns. Per-turn cost
  unchanged (~$0.0256 standard). C10 is proven clean on all 268 saved narrations
  (same logic as the offline FP scan).

## For the API (Team F) — what the gate needs to be passed for the new checks

`check_narration(prose, outcome=<public outcome contract>, envelope=<assembled
envelope>, action=<action_slice>)` already carries everything. The semantic G3
requires only that `outcome["state_deltas"]` are the **committed public deltas**
(the redacted `wound_transition`/`inventory`/`position`/… shapes — already true in
`_narrate_turn`). The npc/person fix requires the envelope's
`scene_manifest.entities[].category` to be the real entity category; if Team A
normalizes categories in the adapter, `person` still works, and raw `npc`/
`character` now work too — no adapter change is required for the gate to be
correct.

---

# Sprint 4 — X2 parser persuasion routes to social

Team C, offline. Goal: persuasion / pressure / ask-to-move parses as `social`
instead of no-roll `dialogue`, while pure info exchange and roleplay speech stay
`dialogue`. Same model/settings: `claude-haiku-4-5`, temperature 0, strict forced
tool. Budget this task: 11 full eval runs (3 baselines, 5 golden prompt iterations,
2 held-out regressions, 1 heldout-2 regression); intermediate failed-run artifacts
were discarded, final/baseline artifacts kept in `llm/results/`.

## Prompt + golden change

- Prompt version p10: removed the over-broad "speech verb always dialogue" rule;
  added worked boundary examples for `Press Bren`, `Convince Tam`, `Talk Tam out
  of`, `Intimidate Tam`, ask/tell-to-do/give, and counterexamples for info/greeting
  dialogue. Also clarified that social paraphrases have `dialogue: null`, while
  exact colon/quoted social commands preserve `dialogue.quoted_speech`.
- Re-pinned older conflicting goldens: `gu-004` direct "stand down" command →
  `social` with quoted speech preserved; `gu-024` barkeep service instruction →
  `social`; `gu-034` ask dragon for hoard → `social`. Kept indirect quoted
  roleplay/safety examples (`gu-023`, `gu-025`) as `dialogue`.
- Added six new goldens: `gu-051` press Bren to allow passage, `gu-052` convince
  Tam to hand over keys, `gu-053` talk Tam out of raising the alarm, `gu-054`
  intimidate Tam into opening the gate, `gu-055` ask Tam for watch-change time,
  `gu-056` greet Bren with peaceful self-introduction.

| Set | Before | After | Safety gates | Notes |
|---|---:|---:|---|---|
| golden | 99.8% (481/482, 50 cases) | **100.0% (536/536, 56 cases)** | PASS → PASS | Expanded/re-pinned set. New X2 social cases all landed; quoted extraction still 4/4. |
| heldout-utterances | 96.4% (457/474) | **97.3% (461/474)** | PASS → PASS | No injection regression; injection gate 5/5. Residual misses remain historical by-adjacency/stat/idiom classes. |
| heldout-2 | 92.1% (256/278) | **93.9% (261/278)** | FAIL → PASS | Pre-existing quoted staged-speech gate failure repaired as a side effect; remaining misses are the documented research-phrasing gaps (`look into`, `ask around`, `what do they say`). |

Verification: `.venv/bin/python -m ruff check everquill_engine api tests llm`
PASS; `EVERQUILL_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q` PASS
(341 passed, 72 skipped).

---

# Playtest Fixes — movement exits + wound anatomy regression (2026-07-15)

Codex batch for Quilltouched playtest fixes. Parser model/settings unchanged:
`claude-haiku-4-5`, temperature 0, strict forced tool. Narrator model/settings
unchanged: `claude-sonnet-5`.

## Parser movement exits

- Added Harrowdown exit roster coverage and three goldens:
  `gu-057` Go to Market Row, `gu-058` Head to the chapel, `gu-059` Take the
  south road.
- First run `20260715-131350-playtest-fixes-movement.json`: safety gates PASS,
  overall 99.6% (two existing boundary misses: gu-003 dialogue presence,
  gu-050 stat_hint).
- Prompt tightened for proclamations-without-quotes and vows/apologies to
  dead/absent addressees.
- Rerun `20260715-131521-playtest-fixes-movement-rerun.json`: **PASS** —
  overall **100.0% (563/563)**, safety gates **PASS**.

## Narrator wound anatomy

- Added deterministic gate support for unsupported specific injury locations
  and fixture `nf-23-wounded-no-new-anatomy`.
- Full run `20260715-131552-playtest-fixes-wounds.json`: `nf-23` PASS, but
  overall VERDICT FAIL from existing style lint variance (`unbothered` in
  `nf-17`, plus batch 3-gram tic).
- Full rerun `20260715-131658-playtest-fixes-wounds-rerun.json`: `nf-23` PASS,
  but overall VERDICT FAIL again from unrelated existing style lint variance
  (`unbothered` in `nf-06`/`nf-22`, plus batch 3-gram tic).
- Focused run `20260715-131714-playtest-fixes-wounds-fixture.json`: **PASS** —
  `nf-23-wounded-no-new-anatomy` 0 narration FAILs, 0 batch FAILs.

## Local verification

- `.venv/bin/python -m ruff check everquill_engine api tests llm`: PASS.
- `DATABASE_URL=postgresql://localhost:5432/everquill_test_codex PGTZ=UTC .venv/bin/python -m pytest api/tests tests -q`: PASS, 534 passed, 1 existing Starlette deprecation warning.

---

# Parser Round 3 — meta boundary + purchase smoke fixes (2026-07-15)

Codex targeted fix batch from live production smokes. Parser model/settings unchanged:
`claude-haiku-4-5`, temperature 0, strict forced tool. No content/world YAML edits.

## Meta boundary

- Prompt version p11 sharpens `meta`: ONLY self-record System/Chronicle/Pack queries
  (`where am I`, coin count, pack contents, own wounds/timers/journal). World/NPC/place/
  rumor questions are in-fiction actions: `dialogue` for present/implicit addressees,
  `research` when consulting records.
- Added worked examples for the exact follow-up class: "and what about the quarry?"
  stays `dialogue`, targets `[]`, addressee `null`, no `ambiguous_addressee`; engine sticky
  partner resolves it later.
- Added goldens `gu-060`..`gu-064`: self-record meta (`coins`, `pack inventory`) and
  world/NPC/follow-up dialogue (`dragon`, `quarry`, barkeep-about-dragon).
- Added a golden safety gate for the new meta/world boundary action types.

## Purchase detector

- Resolver purchase detection now accepts the live parse shapes (`purchasing`,
  `ordering`, `paying`) and scans both parsed `approach` and the source utterance
  when free text is available.
- Priced goods covered: ale/pint/drink → `ale_pint_copper`, meal, bread, room/lodging
  → `inn_room_night_copper`. Room/lodging can arrive as `rest`, not just `social`.
- Non-purchases (`ask about the price`, `admire the ale`) do not spend coin.

## Eval and smoke evidence

| Set | Before | After | Safety gates |
|---|---:|---:|---|
| golden | 99.8% (562/563, 59 cases), `20260715-154520-codex-before-round3.json` | **100.0% (614/614, 64 cases)**, `20260715-155709-codex-after-round3.json` | PASS → PASS, new meta boundary gate PASS 5/5 |

Before local smoke (pre-p11) already parsed "and what about the quarry?" as
`dialogue` but emitted `ambiguous_addressee`; Claude's production smoke before this
batch had observed `meta`. After p11 live parse: `dialogue`, targets `[]`,
addressee `null`, `ambiguity_flags: []`.

Live-parser purchase smoke after p11:
- "buy an ale" → `social`, Maren target, coin delta `-1` reason `drink`.
- "order a pint" → `social`, Maren target, coin delta `-1` reason `drink`.
- "pay for a room" → `rest`, tavern target, coin delta `-8` reason `room`.
- "ask about the price" → `dialogue`, no coin delta.
- "admire the ale" → `observation`, no coin delta.

## Local verification

- Targeted resolver/API regressions: PASS.
- `DATABASE_URL=postgresql://localhost:5432/everquill_test_codex PGTZ=UTC .venv/bin/python -m pytest api/tests tests -q`: PASS, 548 passed, 1 existing Starlette deprecation warning.
- `.venv/bin/python -m ruff check everquill_engine api tests llm`: PASS.

# Typed decision fields: prompts p12 and p13 (2026-10-24 and 25, NOT YET MEASURED)

- p12 (24 Oct, commit 2d6c108): intent schema v1.3. The parse call carries Topics, Prices
  and Laws lists; the closed fields `addressee`, `speech_act`, `topic_ids`, `transaction`,
  `invoked_law_ids`, `movement_scope` and `duration_hint.until/amount/unit` replace the
  engine's reads of the free text. All 144 eval cases relabelled after the prompt was
  committed (6f271c3).
- p13 (25 Oct): wording only. `ambiguity_flags` no longer described as forcing a
  confirmation (George: they do not; nothing reads them). The parser eval drops its three
  flag gates and its law gate: laws now apply from the engine (action type and target
  tags), so a law the parser omits no longer fails open.
- Neither prompt was sent to a model until 25 Oct (below). The last measured held-out number
  before that is p10, 93.9% on held-out-2 with gates PASS (`20260715-104420-x2-final-heldout2.json`).

## p13 measured (2026-10-25, claude-haiku-4-5 via OpenRouter, routed to Anthropic, temperature 0)

Route: OPENROUTER_API_KEY (project key, $5 monthly limit) through OpenRouter's
Anthropic-compatible endpoint, `provider.order = [anthropic]`, no fallbacks; a live probe
confirmed forced tool use, the strict schema, cache reads and temperature 0. Each set ran under
`llm/spend_cap.py` with its own cap; the system prompt is cached as in production.

| Set | Overall | v1.2 fields | v1.3 fields | Gates | Cost | Results |
|---|---:|---:|---:|---|---:|---|
| heldout-2 (30) | **93.3%** (430/461) | 92.8% | 94.0% | PASS | $0.108 | `20261025-075022-p13-openrouter-heldout-2.json` |
| heldout (50) | 97.2% (767/789) | 96.6% | 98.1% | PASS | $0.180 | `20261025-075107-p13-openrouter-heldout-utterances.json` |
| golden (64) | 98.6% (1005/1019) | 98.7% | 98.5% | PASS | $0.230 | `20261025-075202-p13-openrouter-golden-utterances.json` |
| fog (6) | 100% (98/98) | 100% | 100% | none | $0.019 | `20261025-075210-p13-openrouter-fog-utterances.json` |

- Bar: 91.7% on held-out-2. p13 clears it with gates PASS. Against p10's 93.9% (July, old field
  set) the comparable v1.2-field subtotal is 92.8%, about a point lower; the labels were redone
  for v1.3 in between, so this is not a clean before/after. No "before" run of p11 was made: its
  worktree (a24a61f) passes `temperature=`, which the pinned SDK rejects.
- held-out-2 misses cluster on the research/dialogue boundary the set was written to probe ("ask
  around about X", "what do they say about X" read as dialogue or with topics instead of
  targets: ho-001, 002, 005, 006, 010, 030) and on `stat_hint` (ho-009, 015, 016, 025, 029).
  Not iterated on: held-out-2 stays unreferenced by the prompt.
- OpenRouter does not enforce the tool's `strict` schema: hu-030 came back schema-invalid in
  the eval (counted as a miss), and a live turn ("Buy an ale and listen to the room") parsed
  as `action_type: "compound_action"` and was refused with a 422. Anthropic's own API
  constrains decoding to the schema, so this is the route, not the prompt. The API now
  re-asks once on an out-of-contract parse.
- Pilot (golden, first 10, uncached): 98.7%, $0.115, $0.0115 a call. Caching the prompt cut the
  full runs to $0.0036 a call. OpenRouter's meter for the key after probes, pilot and all four
  runs: $0.604.
- Narrator n6 (25 Oct): one diction line. `person_N` ids are people not yet introduced: never
  write the id or invent a name, use `label_known`. The gate now rejects an alias echo and any
  unlearned true name, sentence-initial included (audit claude-010). Not yet measured.
- Narrator n7 (25 Oct): no em dashes or spaced en dashes at all, overriding the copied prose
  rule 9 ("max one per narration"); the gate rejects them as G7 and re-narrates once (George's
  rule: no em dashes in his brands). July's lint measured a mean of 0.25 per narration.
