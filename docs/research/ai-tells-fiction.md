# AI Tells in Fiction — Guardrails for the Everquill Narrator

Research doc, 2026-07-13. Sources: writing-community discussion, slush-pile editorial reporting, craft criticism of AI fiction, and academic detection work on creative text. Full sources list at the bottom.

## Why this doc exists

Everquill's narrator generates 1-3 paragraph scene narrations turn-by-turn, indefinitely, from the same model and the same prompt scaffold. That is a different exposure profile from "AI wrote a short story":

- A short story gets judged once, whole. Our narrations get read **back-to-back, in bulk, forever**. A tic that is invisible in one 200-word passage becomes the dominant impression by turn 40.
- Serial generation has a documented failure mode the one-shot case doesn't: **context poisoning**. Once a cliché or structure lands in context, the model treats it as established style and doubles down instead of varying (Record Crash; confirmed mechanically by the syntactic-templates work — models re-emit templates at far higher rates than humans, and 76% of those templates trace to pre-training data, surviving RLHF).
- Post-training also **flattens** long-run output: emotion variance collapses toward neutral-with-portent, stylistic across-sample variance shrinks to ~0.5x human, and stories move in uniform thematic steps (Narrative Flattening, arXiv 2605.27878). For us that reads as: session hour three feels like porridge.

The good news: several classic whole-piece tells barely apply to us (see "Exposure profile" below), and most of what does apply is either promptable or measurable.

---

## (a) Ranked tell list

Ranked by importance **for our serial case**. Tags: scope `[whole-piece | serial | both]`, fix `[prompt-fixable | lint-detectable | both]`.

### Tier 1 — will kill us if unmanaged

**1. Echo vocabulary / phrase tics across generations** — `[serial]` `[both]`
The single worst serial tell. The same stock phrases recur across turns because they are the statistically safe choice every time: *shiver down her spine, knuckles whitening, the air was thick with, barely above a whisper, eyes gleamed/glinted/sparkled, a testament to, couldn't help but, ministrations, what seemed like an eternity, unspoken tension*. The roleplay community has been maintaining literal ban-token lists for these for years (Sukino's SillyTavern banned-tokens list groups them by theme: eyes, shivers, voice, air/atmosphere, body language, abstract clichés). One instance is a cliché; the fifth instance in a session is a fingerprint.

**2. Manufactured hook endings** — `[serial]` `[both]`
Every narration ends on an ominous atmospheric closer, an ellipsis, a "something watched from the treeline", a portentous question. In a novel this is a chapter-craft choice; in turn-by-turn generation it's the model's default "end of message" move (curt-dialogue-with-cliffhanger is a named web-fiction tell; RP benchmarks test "escalation pacing" as a known failure axis). At one hook per turn, tension inflation bankrupts itself in ten turns and the player stops believing the scene.

**3. Scene-structure templating** — `[serial]` `[both]`
Every narration = observation → action resolution → atmospheric closer. Same opening shape ("The tavern is..." / participial opener / "As you step..."), same paragraph roles, same closer register. The academic result is blunt: LLMs produce repeated **syntactic templates** (POS-sequence patterns) at rates far above human reference text, and the templates persist through fine-tuning (arXiv 2407.00211). Record Crash calls the felt version "droning consistency" — after enough exposure the voice is unmistakable across pieces. Our fixed prompt scaffold makes this *worse* than the general case.

**4. Escalating melodrama / affect ratchet over long sessions** — `[serial]` `[prompt-fixable, partially lint-detectable]`
Two coupled failure modes over a long session: (i) the ratchet — each turn's portent enters context, so the next turn escalates to stay dramatic (context poisoning applied to tone); (ii) the flatten — post-trained models compress high-arousal states (conflict ~20%→7.5%, surprise ~21%→13% in matched continuations) into uniform mild portent, so everything is *slightly* ominous and nothing is actually alarming. Both destroy contrast, which is the thing our tier system (trivial → impossible) needs prose to express.

**5. Emotion signposting / over-clarification of subtext** — `[both]` `[both]`
"Eyes sparkled with determination", "a mixture of fear and awe", "she felt a surge of relief". Also the trailing analysis clause: "..., a reminder that nothing here was free." The model names the emotion, then explains the subtext, because unstated meaning is a gap it is trained to fill. Editors flag this as the fastest craft tell ("shows you the character's file card, not the character"). Distinct sub-tell: the **abstract noun pair** ("curiosity and dread", "grief and resolve") — tidy poster-line emotion pairs no human drafts naturally.

### Tier 2 — strong tells, reliably measurable

**6. Uniform sentence rhythm (low burstiness)** — `[both]` `[lint-detectable, promptable with limits]`
Human prose alternates short punches with long runs; LLM prose clusters in the 10-20 word band with low variance (contrasting-linguistic-patterns work; every stylometric study finds tight clustering of LLM output vs the broad human spread). Symmetrical two-beat sentences ("The X did Y, and the Z did W.") compound it. This is the tell that survives even when vocabulary is clean.

**7. Negative parallelism** — `[both]` `[both]`
"It wasn't a current. It was a summons." / "not just X, but Y" / "no longer a man, but a warning". Named by every source from Wikipedia's signs-of-AI-writing to web-fiction spotters, who report it as the #1 micro-tell in AI serials. One per scene reads as style; one per turn reads as a machine.

**8. Rule-of-three addiction** — `[both]` `[both]`
Triplet descriptors and triplet clauses: "geometry of madness, a wound in the fabric of what is, older than law and time" (real quoted example from an AI web serial). Three feels complete to the model; one ugly specific detail is almost always stronger. Trivially regexable.

**9. Over-adjectivization / purple prose** — `[both]` `[both]`
High adjective and adverb density, "look-at-me adjectives, solemnly poetic similes, portentous cadences" (Max Read on OpenAI's showcase story), settings over-described with nominal/adjectival stacking. The give-away isn't any single adjective, it's the *rate*, which makes it a clean corpus metric.

**10. Body-language tic loop** — `[both]` `[both]`
Characters constantly nod, smirk, chuckle (darkly), sigh, raise an eyebrow, clench jaws; breath hitches; someone tucks a strand of hair. A small closed set of face/hand actions stands in for characterisation. In serial output the same three gestures cycle forever — countable, cappable.

**11. Em-dash (and ellipsis) overuse** — `[both]` `[lint-detectable, promptable]`
The famous one. Newer models substitute semicolons/commas but keep the same interruptive clause shape, so lint the *rate of clause-interruption punctuation*, not just the glyph.

### Tier 3 — real, but lower stakes for us

**12. Tidy closure / summary coda** — `[both, whole-piece origin]` `[prompt-fixable, weakly lintable]`
"Despite everything, hope remained." The essay habit of ending sections by resolving them leaks into fiction as a per-scene moral bow. Our per-turn version: narrations that end by *interpreting* the scene instead of leaving it. Related: forced sentimentality — the "corny, Reddit-inflected" register critics keep flagging.

**13. Incoherent reach-metaphors** — `[both]` `[prompt-fixable, barely lintable]`
Beautiful-sounding images that don't parse: "constraints humming like a server farm", "smiled like sunrise over a sink", "the air sweet with cane and forgetting" (all real quoted examples from craft critiques). The ICLR-accepted finding: seemingly novel LLM n-grams are often nonsensical or non-pragmatic — the model decorates rather than sees. Genre bleed is a sub-case: expressions cherry-picked "from wherever, genre be damned", including fanfic registers, into high-fantasy prose.

**14. "Little did they know" foreshadowing / omniscience leak** — `[whole-piece, appears per-turn]` `[prompt-fixable]`
Narrator hints at future events ("it would be the last time", "for now"). Doubly wrong for us: the engine hasn't rolled the future yet, so foreshadowing is either a lie or a spoiler of clock state the narrator shouldn't leak.

**15. Sensory-detail checklisting** — `[both]` `[both]`
One sight, one sound, one smell, dutifully, every scene ("damp earth, woodsmoke and the sour tang of fermenting cocoa" — quoted in craft criticism as instant AI). Sensory detail should be load-bearing (changes the player's read) or absent.

**16. Character voice flattening** — `[serial]` `[prompt-fixable, hard to lint]`
All NPCs converge on one register over a long session — either quippy Marvel-sidekick or solemn cipher ("every character sounds the same" is a standing criticism of AI fiction; flattening work shows stylistic variance collapse mechanically). Compounded by positivity bias: NPCs agree too easily, conversations refuse to end (Bicking's long-session RP observations).

**17. Same-model stylistic uniformity (batch level)** — `[serial]` `[lint-detectable]`
Burrows' Delta and embedding studies show each model's outputs form a tight cluster far from the broad human spread. Not player-facing per turn, but it's the statistical shadow of tells 1-6, and it's measurable on a corpus.

### Exposure profile: what we're immune to vs what's worse for us

**Naturally immune / greatly reduced** (whole-piece tells the architecture handles for us):
- Global arc tidiness and rushed endings — the engine owns arc; there is no ending to bow-tie.
- The "three-chapter quality cliff" (AI serials pass early screening then collapse) — our quality has to be per-turn anyway; there is no facade to keep up.
- Plot/state inconsistency drift — dice, HP, inventory, death records live in the engine, not the prose. The narrator can't quietly resurrect anyone; `outcome.schema.json` makes deaths auditable without trusting prose.
- Essay scaffolding (intros, "in conclusion", headers), citation fabrication, promotional register — nonfiction tells, mostly N/A.

**Actively worse for us** (serial amplifiers):
- Tic accumulation: thousands of generations from one model+prompt = every Tier 1/2 tell multiplied. The reader sees the corpus, not the sample.
- Hook-rate: every turn ends. A per-piece tell ("dramatic closer") becomes a per-30-seconds tell.
- Template convergence: fixed scaffold + fixed context shape actively trains the session toward one structure.
- Context poisoning: our rolling context *contains our own previous output*. Any tic that gets in gets reinforced. This is the argument for lints that gate what re-enters context, not just what ships to the player.
- Register collapse across tiers: flattening means `trivial` and `desperate` turns drift toward the same mild-portent voice — which breaks the game's legibility promise, not just its prose quality.

---

## (b) Draft narrator anti-tell constraint block

Ready to paste into Team C's narrator prompt. Numbered for reference in eval failures. Ban-list phrases should live in a maintained separate list (seed below in the lint spec) — the block references it rather than inlining all of it.

```text
PROSE RULES — NON-NEGOTIABLE

1. BANNED PHRASES. Never use any phrase on the banned list (provided
   separately). If a phrase feels familiar from other fantasy, cut it and
   state the concrete thing instead.

2. EMOTIONS ARE SHOWN OR ABSENT. Never name a feeling ("fear", "relief",
   "determination") and never pair two ("awe and dread", "a mixture of X
   and Y"). Show one physical or tactical consequence, or let it pass
   unmarked. Eyes do not sparkle, gleam, glint, or fill with anything.

3. SUBTEXT STAYS SUB. Never explain what a moment means, never add a
   trailing "...a reminder that" / "...as if" analysis clause. If an NPC
   means more than they say, leave the gap for the player.

4. ENDINGS: default to ending on a concrete, actionable fact of the scene
   (a thing the player could act on). Atmospheric or ominous closers are
   a spice: never two turns in a row, and only when the resolved tier
   earned it. Never end on an ellipsis. Never pose a question to the
   player.

5. NO FORESHADOWING. You know only what this scene shows. Never "little
   did", "would prove", "for now", "not yet". The dice have not been
   rolled for the future and you do not leak clocks.

6. SAY WHAT IT IS. No negative parallelism: no "not X, but Y",
   "it wasn't X — it was Y", "no longer X". State the thing directly.

7. ONE BEATS THREE. No triplet lists of adjectives, images, or clauses.
   One specific detail, precisely chosen. At most one "A, B, and C" list
   per narration, and only for actual inventory-like content.

8. ADJECTIVE BUDGET. Roughly one adjective per noun, most nouns bare. No
   stacked pairs ("cold, unforgiving"). No -ly adverb on a verb that
   could just be a better verb.

9. RHYTHM: vary sentence length hard. Use flat short sentences for facts.
   Do not open consecutive sentences with the same shape. Symmetrical
   two-beat sentences are rationed, not a default. Max one em dash per
   narration; prefer full stops.

10. REGISTER FOLLOWS TIER.
    - trivial/routine: dry, transactional, near-zero atmosphere. It is
      allowed to be boring; boring is the contrast budget.
    - risky: tension through concrete facts (distances, numbers, what's
      between you and the exit), not through mood words.
    - desperate/hopeless: short sentences. No poetry. Costs and options.
    - strong_hit: understatement. Never fanfare, never "triumph".
    - hit_with_complication: the complication is stated as plainly as
      the win.
    - miss: name the specific cost, flat. No melodrama, no consolation,
      no lesson.
    - impossible: dry irony is licensed; wonder is not manufactured.

11. BODY LANGUAGE IS RATIONED. Nodding, smirking, chuckling, sighing,
    eyebrow-raising, jaw-clenching: at most one such gesture per
    narration, never the same one twice in a row across turns. Prefer
    characters interacting with objects over face-acting.

12. SENSES ARE LOAD-BEARING. At most one non-visual sense per narration,
    and only if it changes what the player understands. Never run a
    sight-sound-smell checklist.

13. METAPHOR: at most one per narration, physically coherent, and built
    from this world's furniture (trade, tide, rot, ledgers, salt), not
    gothic stock. If it sounds like it belongs on a poster, cut it.

14. NO MORALS. Never close by interpreting the scene, drawing a lesson,
    or reassuring the player. The scene ends where the information ends.

15. NPCS PUSH BACK. People refuse, lie, get bored, end conversations,
    and want things. Never let agreeableness or politeness resolve a
    scene the dice did not.
```

Notes for Team C:
- Rule 10 is the load-bearing one: it turns the tier ladder into a *prose contrast budget*, which directly counters the flattening/ratchet failure (tell 4). If everything is written at "risky" register, the game loses legibility.
- Rules are numbered so eval failures can cite them (`R6 violation, 3x in window`).
- Keep the ban list out of the prompt if token budget is tight; rules 1-3 catch the generative pattern behind most of it. But cheap models follow lists better than principles — test both.

---

## (c) Draft lint spec for the eval harness

Run over a corpus of generated narrations (eval-set runs and/or sampled live sessions). Two gate levels: **FAIL** (block/regenerate or fail the eval run) and **WARN** (track trend, human review). All thresholds are *initial values* — calibrate against a baseline run and 2-3 human-written reference passages of comparable length before enforcing.

Per-narration checks run on each turn; window checks run on rolling windows of turns *within a session* (that's where serial tells live); corpus checks run per eval batch.

### L1. Banned-phrase regex — per-narration, FAIL
Exact/patterned match against the phrase list. Any hit = fail that narration.
Seed list (extend from Sukino banned-tokens + Wikipedia signs + our own catches):
```
shiver(s|ed)? (down|up|ran)   | send(ing|s)? shivers
knuckles whiten               | white-?knuckl
air (was|is|hung) (thick|heavy|charged)
barely above a whisper        | voice barely
eyes? (sparkl|gleam|glint|twinkl|alight|glow)\w* with
a (mix|mixture) of \w+ and \w+
testament to                  | tapestry
what (seemed|felt) like an eternity
couldn'?t help but            | despite (him|her|them)sel
unspoken (tension|understanding)
heart (pound|hammer|race)ed in (his|her|their) (chest|ears)
breath (hitch|caught)
little did                    | would (later|soon|come to) (prove|learn|regret)
dance as old as time          | symphony of
something (stirred|coiled|shifted) (with)?in
in that moment                | a (single|lone) tear
```
Threshold: 0 per narration. Corpus report: hits per 100 narrations, by phrase.

### L2. Cross-turn n-gram tic detector — window (50 turns), FAIL
The serial tell #1 catcher. Stopword-filter, drop proper nouns / required game terms (allowlist from lore glossary), then count content 3-grams and 4-grams across the window.
- Any content 3-gram in > 5% of narrations in the window: WARN. > 8%: FAIL.
- Any 4-gram (content or not, minus allowlist) appearing ≥ 3 times within any 20 consecutive turns: FAIL.
Rationale: syntactic-templates research shows template re-emission is the model's signature; frequency across turns is exactly what the reader experiences.

### L3. Hook-ending ratio — window (20 turns), FAIL
Classify each narration's final sentence as HOOK if any of: ends "..."; ends with a question mark; final clause opens with "Somewhere/Far away/Above/Below/Behind you"; contains "waiting|watching|for now|not yet|something|whatever it was" in the last 12 words; ends on a present-participle atmosphere clause ("..., watching."). 
- HOOK ratio > 25% in window: WARN. > 40%: FAIL.
- ≥ 3 consecutive HOOK endings: FAIL.
Also track ending-type entropy (hook / concrete-fact / dialogue / action): entropy collapse = WARN.

### L4. Punctuation rates — per-narration + corpus, WARN→FAIL
- Em dashes: > 1 per narration WARN; corpus mean > 0.6/narration FAIL.
- Ellipses: > 0 in narration prose WARN (allowed in dialogue); corpus mean > 0.15 FAIL.
- Semicolons in narration prose: corpus mean > 0.3/narration WARN (dash-substitution shadow).

### L5. Adjective/adverb density — per-narration + corpus, WARN→FAIL
POS-tag (spaCy is fine).
- ADJ/token ratio: narration > 0.12 WARN; corpus mean > 0.085 FAIL.
- -ly adverbs: > 3 per 100 words WARN; corpus mean > 1.8/100 FAIL.
- Adjective pairs ("ADJ, ADJ noun" / "ADJ and ADJ noun"): > 1 per narration WARN.

### L6. Sentence-length burstiness — window (20 turns), FAIL
Pool sentences in window; compute CV (stdev/mean) of sentence length in words.
- CV < 0.45: WARN. CV < 0.35: FAIL (uniformity tell).
- Share of sentences in the 10-22 word band > 75%: WARN.
- Narrations containing zero sentences ≤ 6 words, over a 10-turn window > 80%: WARN (rhythm rule R9 not landing).

### L7. Construction regexes — per-narration, count-capped
- Negative parallelism: `\bnot (just|merely|only|simply)\b.{0,50}\bbut\b`, `\bit was(n't| not) [^.]{0,40}[.;] It was\b`, `\bno longer\b.{0,30}\bbut\b`. > 1 per narration FAIL; corpus mean > 0.15/narration FAIL.
- Rule-of-three: `(\w+), (\w+),? and (\w+)` where all three same POS class (ADJ or abstract NOUN): > 1 per narration WARN; corpus mean > 0.3 FAIL.
- Trailing participial analysis: sentence-final `, \w+ing [^.]{10,60}\.` at rate > 0.4/narration WARN.

### L8. Emotion-naming rate — per-narration, FAIL
Lexicon of named emotions (fear, dread, awe, relief, determination, sorrow, joy, anticipation, unease, ...) matched in narration prose (dialogue excluded).
- "mix/mixture of X and Y" where X,Y emotional nouns: FAIL outright (also in L1).
- Named-emotion tokens > 1 per narration: WARN; corpus mean > 0.5: FAIL.

### L9. Body-language tic counter — window (100 turns), WARN→FAIL
Lexicon: nod, smirk, chuckle, sigh, grin, shrug, eyebrow, jaw, wince, flinch, exhale.
- Per-lemma cap: > 5 hits per 100 narrations for any single gesture: WARN; > 8: FAIL.
- Same gesture in consecutive narrations ≥ 2 times in window: WARN.

### L10. Opening/closing shape templating — window (50 turns), WARN
Signature = first sentence's coarse shape (POS of first 3 tokens + length bucket), same for last sentence.
- Any single opening signature > 30% of window: WARN; > 45%: FAIL.
- Same for closing signature. This is the cheap proxy for the syntactic-template finding.

### L11. Affect ratchet / flattening — session-level, WARN
Score each narration for arousal/intensity (small classifier or lexicon like NRC-VAD; GoEmotions-style categories if we want the full Narrative Flattening replication).
- Monotonic intensity increase across ≥ 10 consecutive turns whose resolved tiers did NOT escalate: WARN (ratchet).
- Rolling intensity variance < 50% of baseline-corpus variance over 30 turns: WARN (flatten).
- Cross-check register-vs-tier: mean intensity for `trivial` turns should sit measurably below `desperate` turns; if the gap closes, R10 is failing — WARN.

### L12. Lexical-diversity drift — session-level, WARN
MATTR (window 100 tokens) per narration, tracked across the session. Drop > 15% from the session's first-decile mean: WARN. Catches late-session vocabulary collapse that per-narration checks miss.

### Harness notes
- Order cheap→dear: L1/L4/L7/L8 are regex (run at generation time, can gate regeneration); L2/L3/L6/L9/L10 need only tokenisation (post-hoc per window); L5 needs POS; L11/L12 need models — batch eval only.
- Generation-time use: L1 + L7 + L8 failures are safe auto-regenerate triggers (deterministic, no false-positive drama). Window lints should never auto-regenerate — they inform prompt iteration.
- Context hygiene: consider running L1/L2 on what re-enters the rolling context, not just what ships — the context-poisoning finding says a tic you let into context is a tic you'll see again.
- Calibrate every threshold on (i) a baseline generation run and (ii) human reference prose before enforcement; the numbers above are informed starting points, not lab-validated constants.

---

## Register note: why a George-derived base register counters the default AI literary voice

The default AI literary register is ornate, symmetrical, portentous, and emotionally labelled — every tell in Tier 1/2 is a symptom of it. The George-voice corpus distillation (George's private voice notes, style guide v2) points the opposite direction on nearly every axis: opinion/fact first, one concrete specific over three generic items, blunt short-sentence cadence, allergy to abstract noun pairs and to neat setup/payoff symmetry, verdicts stated flat rather than decorated. Notably, that project's own review found the residual AI tell in humanized output was *over-architected sentence symmetry and tidy abstract pairings* — exactly our tells 5-7 — which independently confirms the ban-the-structure approach over ban-the-words alone.

For Everquill: keep that base register (direct, concrete, UK-dry, no bullshit) and let fantasy in through **nouns and furniture, not through cadence**. The world provides tide-rot, ledgers, salt, oaths; the sentences stay plain. Wonder is rationed to where the tier ladder licenses it (`impossible` attempts, `strong_hit` on `desperate` odds), which keeps it legible as signal instead of wallpaper. A narrator that is allowed to be boring on `trivial` turns is what makes the `desperate` turns land.

---

## (d) Sources

Writing community / practitioners:
- Makin, "How to Identify AI-Written Web Fiction" — Record Crash. Serial-specific tells incl. context poisoning, three-chapter cliff, droning consistency, not-X-but-Y. https://recordcrash.substack.com/p/how-to-identify-ai-written-web-fiction
- Sukino, SillyTavern Banned Tokens list (community-maintained RP slop phrases). https://huggingface.co/Sukino/SillyTavern-Settings-and-Presets/blob/main/Banned%20Tokens.md
- AI Dungeon help, "How to avoid/fix repetition in my story" (incl. "saying different things the same way"). https://help.aidungeon.com/faq/how-to-avoidfix-repetition-in-my-story
- Ian Bicking, "Roleplaying driven by an LLM: observations & open questions" — long-session repetition, conversations that can't end, positivity bias. https://ianbicking.org/blog/2024/04/roleplaying-by-llm
- Linda Maye Adams, "The Problem with AI and Fiction Writing" — mood discordance. https://lindamayeadams.com/2024/05/05/the-problem-with-ai-and-fiction-writing/
- Justis Mills, "AI Can't Write Good Fiction". https://justismills.substack.com/p/ai-cant-write-good-fiction
- LeviTheWeasel, rp-benchmark — escalation pacing as a tested RP failure axis. https://github.com/LeviTheWeasel/rp-benchmark

Editorial / slush pile:
- Neil Clarke, Clarkesworld editor's desk on AI submissions (traits kept deliberately vague; detection used for triage). https://clarkesworldmagazine.com/clarke_08_25/
- NPR, "Sci-fi magazine Clarkesworld stops submissions after a rush of AI-made stories". https://www.npr.org/2023/02/24/1159286436/ai-chatbot-chatgpt-magazine-clarkesworld-artificial-intelligence
- Time, "Sci-Fi Publishers Are Getting Unwanted AI-Generated Pitches". https://time.com/6257471/clarkesworld-ai-science-fiction/

Craft criticism:
- Tuhin Chakrabarty, "AI-slop, GrantaGate and Bad Writing" — incoherent metaphors, forced rule-of-three, genre-blind expression borrowing. https://tuhinchakrabarty.substack.com/p/ai-slop-grantagate-and-bad-writing
- Max Read, "Is OpenAI's new story-generating model good at writing?" — corny sentimentality, misattached imagery, portentous cadence. https://maxread.substack.com/p/is-openais-new-story-generating-model

Academic:
- Chakrabarty et al., "Art or Artifice? LLMs and the False Promise of Creativity" (CHI 2024) — expert stories pass 84.7% of TTCW tests vs 9-30% for LLM stories; weakness concentrated in originality. https://arxiv.org/abs/2309.14556
- Shaib et al., "Detection and Measurement of Syntactic Templates in Generated Text" — models emit templates above human rates; 76% of model templates trace to pre-training data (vs 35% human); survive RLHF. https://arxiv.org/abs/2407.00211
- "Narrative Flattening: How Post-Training Compresses Thematic, Affective, and Stylistic Variation in LLM Fiction" — emotion-variance collapse, ~0.5x human across-story stylistic variance, uniform thematic steps; metric designs reused in L11/L12. https://arxiv.org/html/2605.27878
- "Stylometric comparisons of human versus AI-generated creative writing" (Humanities & Social Sciences Communications) — Burrows' Delta; LLM outputs cluster tightly by model, far from the broad human spread. https://www.nature.com/articles/s41599-025-05986-3
- Muñoz-Ortiz et al., "Contrasting Linguistic Patterns in Human and LLM-Generated News Text" — uniform sentence-length distributions, low burstiness (basis for L6). https://arxiv.org/abs/2308.09067

General tell taxonomies:
- Wikipedia, "Signs of AI writing" — rule of three, negative parallelism, em-dash overuse, -ing analysis clauses, inflated symbolism, tidy conclusions, overused vocabulary. https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing
- ContentBeta, "List of 300+ AI Words, Phrases and Sentences to Avoid". https://www.contentbeta.com/blog/list-of-words-overused-by-ai/

Internal:
- George voice style guide v2 (private notes, not in this repo) — register basis; independent confirmation that residual AI tells in humanized output are structural (symmetry, abstract pairs), not lexical.
- `docs/contracts/outcome.schema.json` — tier vocabulary used in R10/L11 (`tier_resolved`, `outcome_tier`).
