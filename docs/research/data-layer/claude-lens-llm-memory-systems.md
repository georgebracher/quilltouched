**Phase 4 — Verification notes** (adversarial pass on load-bearing claims): AI Dungeon budget mechanics come from the official help center (primary, confirmed). NovelAI and SillyTavern mechanics come from official docs (confirmed). Legacy AID WI ~1,386-char cap is single-source community research (plausible, legacy-era only). character.ai "8-9K window" and "forgets in 10-15 messages" are third-party estimates that conflict with another source's "20-30 messages" — reported as ranges, low precision. ChatGPT internals come from empirical reverse-engineering (embracethered, Willison) — confirmed as of 2025; "Dreaming" background process is single-source (plausible). Replika 2.0 regression reports are multi-blog but non-official (medium confidence).

---

# Memory & Recall in Shipped LLM Products — Field Report for Everquill's Context Assembler

## 1. Executive summary

Every shipped LLM narrative product converges on the same architecture Everquill already committed to — a deterministic selector that injects a bounded slice of state into the prompt — and every one of them documents the same failure family: **silent eviction under budget pressure, followed by confident fabrication**. The model never says "I don't know who has the key"; it invents an answer. Lorebook systems (NovelAI, SillyTavern) are the most mature prior art for the selection layer and are worth stealing from wholesale: per-entry priority, reserved-token floors, bounded recursion, mutual-exclusion groups, and timed activation effects. The single most important empirical finding for Everquill: **behavioral constraints, promises, and consequences are evicted first and identities last** (character.ai testing) — the exact inverse of what a game referee needs — so constraint-class claims must be pinned by type, never left to salience ranking.

## 2. Product-by-product

### 2.1 AI Dungeon — Memory System + Story Cards (World Info)

**Mechanism.** Context is assembled in fixed order: Instructions → Plot Essentials → Story Cards → Story Summary → Memory Bank → History → Author's Note → Last Action → Front Memory. Two tiers: **Required** (instructions, plot essentials, summary, author's note, front memory, last action) and **Dynamic** (story cards, memory bank, history). Story Cards are keyword string-matched against recent actions (minimum 4 actions scanned; when >500 tokens are free for cards, actions scanned = available tokens ÷ 100). The Memory System = Auto Summarization + a Memory Bank ranked by relevance to the most recent action.

**Token budgeting.** ~4K context on free tier. Guard rail: if Required elements exceed 70% of context, a priority cascade applies (Front Memory and Last Action always in full; then Author's Note → Plot Essentials → Instructions → Summary until full). Remaining tokens split ~25% Story Cards / ~50% History (75% if Memory Bank off) / ~25% Memory Bank. Sections are trimmed rather than dropped whole; lowest-priority items can vanish entirely.

**Failure modes reported.** Official docs admit the core failure plainly: once details scroll out of context "it's just making it up as best it can." Users report ignored character cards in long stories, repeated text on continue, contradicted traits. Legacy-era community research (Griffin/Dragon models) found: generic keys like "you" trigger constantly and eat the (then ~1,386-char) WI budget; entries needed re-reinforcement every ~50-200 characters of story or the model "lost focus" on them — i.e., **injection is necessary but not sufficient; placement and recency matter**.

### 2.2 NovelAI Lorebooks — closest prior art to the assembler

**Mechanism.** Entries carry activation keys (case-insensitive strings or case-sensitive regex; `&` operator = multiple keys required in-window). Search range: up to 10,000 characters of recent story, configurable per entry. **Cascading activation** (recursion): entries may match keys inside other non-story context entries, not just narrative. **Insertion order** is an explicit integer (highest processed first) — but ties have *no guaranteed sequence*, a documented nondeterminism. **Insertion position** is index-based (0 = top, -1 = bottom), plus key-relative insertion (place entry adjacent to the matched key's location, at a performance cost). **Force activation** ("Always On") bypasses keys.

**Token budgeting.** Two distinct knobs: **Token Budget** (max tokens an entry may consume; decimals 0-1 = percentage of context) and **Reserved Tokens** (pre-allocated floor claimed *before* context building — an entry can guarantee itself space). Community default guidance: lorebook total ~25% of context.

**Failure modes.** Nondeterministic tie ordering; hidden entries invisible in the context viewer (debuggability gap); model still invents lore conflicting with user canon when entries aren't triggered — keyword miss = silent absence.

### 2.3 SillyTavern World Info — the most feature-complete selector shipped

**Mechanism.** Everything NovelAI has, plus: **secondary key filters** with four operators (AND ANY / AND ALL / NOT ANY / NOT ALL — compound predicates over keys); **Scan Depth** (how many past messages are scanned; Min Activations can walk further back until N entries trigger, bounded by Max Depth/budget); **three per-entry recursion controls** (non-recursable; prevent further recursion; delay-until-recursion, i.e., only activatable by other entries, never directly); **Max Recursion Steps** global bound (mutually exclusive with budget-limited recursion); **Inclusion Groups** (entries sharing a group label are mutually exclusive — one wins by weight, order, or key-match count via Group Scoring); **Timed Effects** — Sticky (stays active N messages after trigger), Cooldown (can't re-trigger for N messages), Delay (inactive until chat is N messages old). **Vector Storage extension** replaces keyword scan with embedding similarity per entry; docs note it respects other filters but is **non-deterministic and embedding-model dependent**.

**Token budgeting.** Global budget cap for WI; on overflow, only highest-priority entries survive and *activation stops entirely* once budget is exhausted, even if keys are present. Priority: Constant entries first, then by order value; **directly-triggered entries outrank recursively-triggered ones** — a clean provenance-aware priority rule.

**Failure modes.** Documented: infinite loops via self-referencing macros/outlets; recursion chains exhausting budget; community guidance warns generic keys and oversized entries starve history. The hybrid keyword+vector mode exists precisely because pure keyword misses paraphrase and pure vector misses precision — and the community treats vector activation as flaky.

### 2.4 character.ai — the cautionary tale

**Mechanism.** Fixed context window (third-party estimates ~8-9K tokens; not officially confirmed) with no durable per-character state. Reported forgetting onset ranges from ~10-15 messages (one test) to ~20-30 and "after ~100 messages, earlier details slip" (aggregated complaints) — imprecise, but universally reported.

**Empirical fragility hierarchy** (single extended test, plausible): most durable = names, roles, broad relationships; medium = frequently re-mentioned concrete details (things the conversation naturally re-surfaces survive — accidental reinforcement); most fragile = **arguments, secrets, promises, behavioral constraints, consequences**. Central finding: **"confident forgetting"** — the model invents plausible replacements rather than flagging uncertainty, mutating the story through accumulated micro-errors. Users report *personality drift*, not just fact loss. "Better memory" was the top requested feature (~29% in one subreddit sample).

### 2.5 Replika — memory as retention risk

~25M users; persistent complaints of "goldfish memory": forgets prior sessions, confuses details, repetitive/shallow over time. The Replika 2.0 update (April 2026) reportedly *worsened* it — partial memory loss, dropped names and inside jokes, personality drift after migration. Lesson for Everquill: **memory regressions during migrations are perceived as character death by attached users** — an event-sourced canon that can rebuild projections after schema changes is a direct defense.

### 2.6 ChatGPT / Claude memory features

**ChatGPT.** Two layers: editable **Saved Memories** (the `bio` tool writes timestamped facts into "Model Set Context" in the system prompt) and **Reference Chat History** — which reverse-engineering showed is **not RAG/vector search**: it's a standing synthesized dossier (response preferences ~15 entries, past topics ~8, user insights ~14, plus ~40 recent conversation summaries with raw user messages) prepended to every chat. It cannot retrieve a specific year-old conversation. Willison called it "a system prompt hack." Newer reports describe a background synthesis process ("Dreaming," mid-2026, single-source). **Failure modes:** hallucinated memories observed *inside the dossier itself* (a fabricated "3 memory-wipe events" entry); indirect prompt injection can write persistent malicious memories (demonstrated spyware persistence); users can't fully inspect the derived profile.

**Claude.** Synthesized memory summary from chat history (updated ~daily) plus an explicit remember path; API-side **memory tool** = files under `/memories` the agent reads/writes — closer to Everquill's journal/claim model than ChatGPT's dossier.

**Everquill relevance:** the injection finding matters directly — **player-authored journals become inherited claims; that is a persistence-layer injection vector into heirs' context**. Treat journal text as untrusted data, never as instructions.

### 2.7 Postmortems / research on LLM-game state drift

- **Intra (Ian Bicking, 2025)** — LLM text adventure with formal state. Conclusions matching Everquill's bets: formal code must own ground truth ("is the door locked"); ungrounded object invention caused "an inflationary effect on the value of any object"; NPCs got **perspective-filtered event logs** (only same-room events) — a shipped mini-version of the claim store; flagged weakness: "the only memory is the event history… critical memories can easily be lost in time" because nothing promoted important events to durable salience. Also used stable entity IDs mirroring display names so the model never translates between them.
- **DEV.to "Reliable AI Dungeon Master"** — key anti-drift trick: pass a **machine-readable trace of the previous turn's resolution** (hit/miss, resources consumed, confiscated items) so the narrator cannot re-narrate a miss as a hit. Direct steal for Everquill: the assembler should always include the engine's structured resolution of the *last* action, not just its narration.
- **arXiv 2406.04482** — LLM-powered games exhibit "hallucinations, forgetfulness, misinterpretations… logical inconsistencies"; proposes detecting such bugs automatically **from player game logs** — Everquill's deed log makes this nearly free (consistency checkers replaying narration against canon).

## 3. What the Context Assembler should steal from lorebook design

Everquill uses structured queries, not keyword scans — correct call (SillyTavern's vector mode is the shipped experiment proving similarity activation is non-deterministic and flaky). But the lorebook *selection/packing* machinery translates directly:

1. **Two-tier budget cascade with a guard rail (AI Dungeon).** Required tier (scene manifest, active clocks, last-action resolution trace, pinned constraint-claims) vs Dynamic tier (salient claims, canon excerpts, rumor slices). Enforce a hard cap on Required (AID uses 70%) with an explicit priority order inside it, so a bloated scene manifest can never evict the last action. Trim within sections before dropping sections.
2. **Reserved tokens per component (NovelAI).** Give each assembler component a guaranteed floor (e.g., last-action trace and active clocks always get their reservation) so a claim flood can't starve them. Budget = floors first, then proportional split of the remainder (AID's 25/50/25 pattern).
3. **Total, deterministic ordering — fix NovelAI's tie bug.** NovelAI documents that equal insertion-order entries have no guaranteed sequence. Everquill's assembler must define a full tiebreak chain (priority → recency → claim/entity ID) so identical state always yields byte-identical prompts. This is also what makes prompt caching and replay-debugging work.
4. **Provenance-aware priority (SillyTavern).** Directly-relevant claims (subject present in scene) outrank transitively-pulled ones (claims about an absent entity referenced by a present claim). ST ships exactly this rule: direct keyword hits beat recursive activations.
5. **Bounded recursion = transitive claim closure with depth cap.** Pulling claims about entity A may reference entity B; ST's Max Recursion Steps and per-entry "non-recursable / prevent further / delay-until-recursion" flags map to: claim classes that never pull dependents, claims that terminate chains, and claims only includable via a parent (e.g., a secret's *existence* marker vs its content). Cap depth at 1-2; ST's docs warn uncapped chains exhaust budget.
6. **Inclusion groups = one-canonical-slot selection.** When multiple claims about the same subject+predicate qualify (rumor variants, superseded observations), emit exactly one per slot, chosen by a deterministic score (ST Group Scoring: match strength; Everquill: confidence × recency × corroboration). Prevents the narrator seeing contradictory claims *unless contradiction is the point*, in which case emit both explicitly tagged as conflicting.
7. **Timed effects = salience hysteresis.** Sticky → a claim surfaced this scene stays for N turns (coherence); Cooldown → flavor/canon excerpts can't repeat for N turns (anti-repetition, the AID "repeats everything" complaint); Delay → claims gated on world-clock or scene age. All deterministic counters on the event log, trivially rebuildable.
8. **Compound predicates (ST secondary keys AND/NOT)** → claim-store query filters: include claim only if subject present AND observer is the POV character AND NOT superseded. Design the query DSL to express these natively.
9. **Key-relative insertion (NovelAI)** → placement matters, not just inclusion. Legacy AID research showed injected facts "lose focus" if far from the active text. Put a claim near the manifest line of the entity it describes rather than in a distant lore block.
10. **Debuggability (anti-lesson).** NovelAI's hidden entries are invisible in its context viewer; ChatGPT's dossier is uninspectable. Ship an internal "why is this in the prompt" trace per turn — every included token attributable to a component + query + priority score. This is also your regression harness.

## 4. Failure modes to test for

| # | Failure mode | Origin | Test |
|---|---|---|---|
| 1 | **Constraint eviction** — promises, prohibitions, consequences ranked out before names | character.ai fragility hierarchy | Class-pin constraint claims; fuzz: overload salience pool, assert every active constraint-class claim survives packing |
| 2 | **Confident fabrication on missing claim** — narrator invents instead of hedging | character.ai, AID official docs | Withhold a claim the player asks about; assert narration hedges/asks rather than asserting a value; lint narration for entities/values absent from the assembled slice |
| 3 | **Re-narration drift** — narrator contradicts last turn's mechanical outcome | DEV.to DM postmortem | Always include machine-readable last-resolution; regression: miss narrated as hit, spent resource re-used |
| 4 | **Budget starvation cascade** — one oversized component evicts history/clocks | AID, ST budget docs | Property test: for adversarial claim floods, floors hold for every Required component; packing never returns an empty history slice |
| 5 | **True-sheet leakage** | Everquill invariant | Serializer-level type test: true-sheet objects have no path into assembler output; red-team prompts asking narrator for hidden stats |
| 6 | **Nondeterministic packing ties** | NovelAI tie behavior | Same event-log prefix ⇒ byte-identical prompt, across processes/restarts |
| 7 | **Recursion runaway** — transitive claim pulls blow the budget | ST recursion warnings | Depth cap asserted; cyclic claim references (A mentions B mentions A) terminate |
| 8 | **Stale projection/cache after new deed** — region-epoch cache serves pre-deed knowledge | Everquill lazy rumor design | Write deed → query NPC knowledge in-region same tick → assert epoch invalidation |
| 9 | **Reinforcement decay** — included-but-ignored facts far from active text | legacy AID research | Eval: fact placed in distant lore block vs adjacent to entity line; measure narration adherence |
| 10 | **Repetition loops** — same canon excerpt/rumor re-injected until narrator parrots it | AID "repeats everything" complaints | Cooldown counters on excerpt classes; n-gram overlap monitor on consecutive narrations |
| 11 | **Persistence injection** — player journal text acting as instructions in heir/NPC context | ChatGPT memory spyware demo | Journals rendered as quoted data with delimiters; red-team journals containing "ignore previous instructions", assert no behavioral change |
| 12 | **Summary/projection mutation drift** — derived summaries diverging from canon over rebuilds | AID auto-summarization, Replika 2.0 migration | Projections rebuilt from log must equal live projections (hash compare) after every migration; personality/known-sheet diff alarms |
| 13 | **Contradiction mishandling** — two claim variants both surfaced unflagged | NovelAI canon-conflict complaints | Inclusion-group test: same subject+predicate ⇒ one claim, or both explicitly tagged conflicting |
| 14 | **Selective drift, not amnesia** — facts survive but persona/tone mutates | character.ai personality drift reports | Longitudinal eval: fixed NPC over 200 turns, embed/judge tone consistency against character sheet |

## 5. Confidence notes

- **High (official docs/primary):** AI Dungeon context order, tiers, 70% guard, 25/50/25 split, card matching; NovelAI key/order/budget/reserved/cascade mechanics; SillyTavern full WI feature set and priority rules; Intra design notes; embracethered ChatGPT dossier structure.
- **Medium (multi-source, third-party):** Replika goldfish-memory complaints and 2.0 regression; Claude ~daily memory synthesis; ChatGPT "Dreaming" (single-source).
- **Low precision (single tests/estimates):** character.ai 8-9K window and message-count forgetting thresholds (10-15 vs 20-30 vs ~100 across sources); legacy AID 1,386-char WI cap and 50/200-char reinforcement figures (Griffin/Dragon era, obsolete models, directionally useful only).

## Sources

- [AI Dungeon: What goes into the Context sent to the AI](https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai)
- [AI Dungeon: What is the Memory System?](https://help.aidungeon.com/faq/the-memory-system)
- [AI Dungeon: Why does the AI forget or mix things up?](https://help.aidungeon.com/faq/why-does-the-ai-forget-or-mix-things-up)
- [AID World Info Research Sheet (community empirical, legacy)](https://github.com/valahraban/AID-World-Info-research-sheet/blob/main/AID%20WI%20Research%20Sheet.md)
- [NovelAI Lorebook documentation](https://docs.novelai.net/en/text/lorebook/)
- [SillyTavern World Info documentation](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)
- [World Info Encyclopedia (community best practices)](https://rentry.co/world-info-encyclopedia)
- [Character AI forgetting test (Medium, Jul 2026)](https://medium.com/@chuckmellisa/character-ai-keeps-forgetting-things-i-tested-what-it-remembers-and-what-disappears-first-97f4809d9b15)
- [Kenotic Labs: Why Does Character AI Forget Everything?](https://kenoticlabs.com/insights/character-ai-memory)
- [Roborhythms: Replika memory broken](https://www.roborhythms.com/replika-memory-broken-fix/) / [Replika 2.0 explained](https://www.roborhythms.com/replika-2-0-explained/)
- [Cuckoo Network: Negative feedback on LLM storytelling & roleplay apps](https://cuckoo.network/blog/2025/04/17/negative-feedback-on-llm-powered-storytelling-and-roleplay-apps)
- [Embrace The Red: How ChatGPT remembers you (reverse engineering)](https://embracethered.com/blog/posts/2025/chatgpt-how-does-chat-history-memory-preferences-work/)
- [Simon Willison: ChatGPT's new memory dossier](https://simonwillison.net/2025/May/21/chatgpt-new-memory/)
- [OpenAI Help: How does Reference Saved Memories work?](https://help.openai.com/en/articles/11146739-how-does-reference-saved-memories-work)
- [Anthropic: Memory tool docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
- [Ian Bicking: Intra — design notes on an LLM-driven text adventure](https://ianbicking.org/blog/2025/07/intra-llm-text-adventure)
- [DEV: Prompt Architecture for a Reliable AI Dungeon Master](https://dev.to/austin_amento_860aebb9f55/prompt-architecture-for-a-reliable-ai-dungeon-master-d99)
- [arXiv 2406.04482: Automatic Bug Detection in LLM-Powered Text-Based Games](https://arxiv.org/abs/2406.04482)