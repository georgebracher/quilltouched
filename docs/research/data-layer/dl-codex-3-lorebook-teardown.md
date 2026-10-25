# Everquill Context Assembler: Teardown of Shipped LLM-Game Memory Systems

*Research reviewed 13 July 2026.*

## Executive findings

None of the examined systems satisfies Everquill’s invariant of **same authoritative state → byte-identical narrator context**:

- **NovelAI Lorebook** has the strongest context-packing machinery: reservations, insertion stages, explicit trimming, recursive activation, and a good context viewer. Its lexical activation, unbounded cascades, and undefined equal-priority ordering prevent strict determinism.
- **AI Dungeon** has the clearest fixed prompt layout and source-specific budget cascade. Its current automatic memory introduces lossy LLM summaries and embedding retrieval, while Story Cards remain vulnerable to delayed activation, substring collisions, and silent budget exclusion.
- **SillyTavern** has the most expressive activation controls: Boolean key conditions, bounded recursion, inclusion groups, source merging, and insertion positions. It also has the largest state space of configuration traps, optional randomness, hidden timed state, and vector-retrieval unpredictability.
- **KoboldAI World Info** is the useful minimal baseline: shallow lexical scanning and GUI-order insertion. It lacks graceful budget arbitration, per-entry priority, and recursive expansion.
- **MemGPT/Letta** provides the best architectural metaphor—pinned working context plus paged external memory—but delegates retrieval, consolidation, and often memory writes to the LLM. That is fundamentally incompatible with Everquill’s deterministic authority model.

The decisive difference is that these systems mostly treat memory as **text that might become relevant**. Everquill has structured state and can instead make context a reproducible, typed projection:

> `context = assemble(narrator_safe_state_snapshot, policy_version, tokenizer_version)`

True stats should not be candidates that are filtered out. They should be **unrepresentable in the assembler’s input type and inaccessible to its data-access layer**.

## Comparative mechanics

| System | Activation | Budget behavior | Ordering and placement | Determinism verdict |
|---|---|---|---|---|
| NovelAI Lorebook | Literal/regex keys, AND keys, always-on entries, cascades through other context | Per-entry cap and reservation; higher insertion order processed first; configurable trimming | Processing order and insertion position are separate; equal insertion order is explicitly unspecified | Close in fixed configurations, but lexical cascades and priority ties violate the contract |
| AI Dungeon | Story Card keywords; automatic Memory Bank uses embeddings; Story Summary uses LLM compression | Required sources consume up to and beyond 70%; remaining budget divided among cards, history, and retrieved memories | Fixed final prompt layout; selection priority differs from placement order | Story Cards can be reproducible, but the complete system cannot |
| SillyTavern | Literal/regex keys, Boolean secondary conditions, recursion, groups, probability, vector similarity | Global World Info token/percentage cap; constants and high-order entries win; vectors have an additional entry cap | Multiple source-merge strategies and insertion positions | Only a carefully restricted keyword-only subset is deterministic |
| KoboldAI | Constant entries or comma-separated primary/secondary keys over recent actions | Active World Info shares context with Memory/story; large active sets can produce overflow instead of pruning | Memory, World Info, retained story with Author’s Note at depth, current input; entries follow GUI order | Mostly reproducible, but brittle and underspecified at overflow |
| MemGPT/Letta | Pinned blocks plus model-issued retrieval and memory-management calls | External memory is paged; recent conversation is compacted or summarized under pressure | Pinned system/core memory, recent FIFO conversation, then model-requested pages/tool results | Architecturally useful but intentionally agentic, not deterministic |

---

## 1. NovelAI Lorebook

### Exact activation mechanism

A Lorebook entry has activation configuration and entry text. Only the entry text is sent to the model; the entry title and keys are not automatically included.

Classic Lorebook activation supports:

- Case-insensitive literal keys.
- JavaScript-style regular expressions delimited with `/.../`; case behavior then depends on regex flags.
- An `&` syntax requiring multiple terms within the activation window.
- Always-on entries.
- A per-entry **Search Range**, measured in characters rather than tokens or turns, with a documented maximum of 10,000 characters.
- Key-relative insertion, where content is positioned relative to the last occurrence of the matching key.
- Cascading activation, where already active non-story context can activate additional Lorebook entries.

For cascading activation, the normal story Search Range is not applied to the non-story text being scanned. A recursively triggered entry can therefore enter the active set because of text in Memory, Author’s Note, or another Lorebook entry. The entry that caused the cascade is not guaranteed to survive final budget packing, leaving a downstream entry in context without its triggering parent. The classic documentation exposes no strict user-set recursion-depth ceiling comparable to SillyTavern’s recursion limit. [NovelAI Lorebook documentation](https://docs.novelai.net/en/text/lorebook/)

NovelAI’s newer model paths are not completely uniform: some models replace the classic placement interface with Boolean “Advanced Conditions,” including keyword, active-entry, model, mode, numeric, and string conditions. Mechanics therefore depend on the selected model generation path.

### Budget cascade

NovelAI separates several concepts that simpler systems collapse:

1. **Token Budget** limits how much of an individual entry may be used.
2. **Reserved Tokens** pre-allocate room for an entry before ordinary packing. Reservation is capped by the entry’s actual length.
3. **Insertion Order** controls which entries reserve and attempt insertion first. Higher values are processed first.
4. **Insertion Position** controls where accepted text ultimately appears in the context.
5. **Trim direction and trim unit** control which part of an oversized entry survives.
6. **Do Not Trim** changes an entry to all-or-nothing insertion.

Fractional values between zero and one can express portions of the available model context. Context is constructed in stages, and the Context Viewer records inclusion, exclusion reason, matched key, reservation, token count, trim behavior, stage, and order. [NovelAI Advanced Context Settings](https://docs.novelai.net/en/text/editor/advancedsettings/)

This is the best packing model among the systems reviewed because it distinguishes:

- Candidate activation.
- Admission priority.
- Reserved capacity.
- Final prompt placement.
- Record-local trimming.

Those are separate decisions in a serious context assembler.

### Ordering and priority

NovelAI’s effective ordering is:

1. Context-building stage.
2. Descending Insertion Order for reservation and admission.
3. Entry/category placement policy.
4. Final Insertion Position within the assembled prompt.

Crucially, the documentation says entries with the same Insertion Order have **no guaranteed processing order**. A context budget near the cutoff can therefore accept different equal-priority entries unless another stable tiebreaker is imposed outside the documented mechanism.

Key-relative insertion adds another dependency: placement can change when the matched occurrence changes, even if the Lorebook entries themselves do not.

### Documented and reported failures

- **Cascade avalanches:** Interlinked entries can fill most of the context with high-priority characters while displacing the location or immediate scene. Users have reported exactly this failure when cascading and priority interact. [Cascade versus insertion-order report](https://www.reddit.com/r/NovelAi/comments/ot969t/cascading_activation_or_insertion_order_which_to/)
- **Secret leakage:** If a character’s public and secret information share the same name key, activating the character also exposes the secret to the narrator. Users commonly split “surface” and “secret” entries or manually enable secrets later. [Lorebook spoiler-leak discussion](https://www.reddit.com/r/NovelAi/comments/1sr0q6y/how_can_you_write_lorebooks_in_a_way_that_doesnt/)
- **Placement-dependent activation:** Users have observed keys behaving differently when Key-Relative Insertion is enabled, including triggering from Memory or Author’s Note but not as expected from story text. [Key-relative activation report](https://www.reddit.com/r/NovelAi/comments/zuf6ar/lorebook_keys_not_activating_from_story_context/)
- **Crowding and stale invention:** Once the story and lore approach the context ceiling, previously invented model facts can outweigh or conflict with newly activated lore. [Long-story context report](https://www.reddit.com/r/NovelAi/comments/1ghu50e/trouble_understanding_how_people_run_longer/)
- **Invisible identity:** Titles and activation metadata are not model-visible unless the author repeats identifying information inside the entry.

### Everquill takeaway

Steal NovelAI’s **reservation model, explicit trimming policy, staged construction, and context receipt**. Reject text-key activation, key-relative placement, uncapped cascades, and undefined equal-priority ordering.

---

## 2. AI Dungeon: Plot Essentials, Story Cards, Author’s Note, and automatic Memory

### Naming matters

AI Dungeon has renamed several systems:

- Legacy **Memory** is now **Plot Essentials**: user-maintained, always-on information.
- Legacy **World Info** is now **Story Cards**: keyword-activated lore.
- **Author’s Note** remains a high-influence near-output instruction.
- The newer **Memory System** adds generated memories, a Memory Bank, and Story Summary.

These mechanisms coexist and should not be treated as one “memory” feature.

### Exact activation mechanism

#### Plot Essentials

Plot Essentials is always included while budget permits and is intended for short, currently important facts. AI Dungeon advises against negative instructions because models tend to ignore the negation and reproduce the named concept. [Plot Essentials documentation](https://help.aidungeon.com/faq/plot-essentials)

#### Story Cards

Story Cards activate when a trigger appears in scanned player input or story text:

- Matching is case-insensitive.
- Leading and trailing spaces in configured triggers are significant.
- Matching is substring-like: `cat` can match `catalog`.
- A trigger ending in a space may fail on punctuation such as `cat.`.
- Only the card’s Entry is sent to the model; card name and triggers are omitted.
- A trigger first produced in an AI response cannot affect that same generation. It becomes available on the following turn.

The scan window is budget-sensitive. The documented minimum is four actions; when more than 500 Story Card tokens are available, the lookback is approximately available tokens divided by 100—900 available tokens produces roughly a nine-action scan. Activated cards are ranked by recency and frequency of trigger use, then included until their budget is exhausted. [Story Cards documentation](https://help.aidungeon.com/faq/story-cards)

#### Automatic Memory System

The current automatic system uses two lossy mechanisms:

- A memory is generated from groups of six actions. The first is created around action 12 for actions 1–6, leaving the newest six actions unsummarized.
- Story Summary updates approximately every 15 actions and recursively compresses its prior contents.
- Memory Bank entries are embedded and semantically ranked against the most recent action.
- When the bank is full, low-use memories are removed; frequently retrieved old memories can persist indefinitely.

Edits to old story text do not automatically repair already generated summaries or memories. [AI Dungeon Memory System](https://help.aidungeon.com/faq/the-memory-system)

### Budget cascade

AI Dungeon divides context into **Required** and **Dynamic** sources.

Required sources include Instructions, Plot Essentials, Story Summary, Author’s Note, Front Memory, and Last Action. When Required content exceeds roughly 70% of the context:

1. Front Memory and Last Action remain complete.
2. Remaining required sources compete in this admission order:
   - Author’s Note
   - Plot Essentials
   - AI Instructions
   - Story Summary
3. If a source only partially fits, its end is trimmed.
4. Lower-priority required sources may be omitted.

After Required content, the remaining space is divided approximately into:

- 25% Story Cards.
- 50% Story History.
- 25% Memory Bank.

When Memory Bank is disabled, history can receive about 75%. Story history is packed from newest to oldest; Memory Bank retrieves the highest semantic matches that fit. [AI Dungeon context construction](https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai)

### Final placement order

Admission priority is not the same as prompt placement. The current documented final assembly is:

1. Instructions
2. Plot Essentials
3. Story Cards
4. Story Summary
5. Memory Bank
6. Story History
7. Author’s Note
8. Last Action
9. Front Memory

Author’s Note is intentionally close to the generation boundary and is therefore disproportionately influential. AI Dungeon recommends keeping it to roughly three or four sentences; excessive content can cause the model to focus on it instead of the current action. [Author’s Note documentation](https://help.aidungeon.com/faq/what-is-the-authors-note)

### Documented and reported failures

- **One-turn-late lore:** A person or place invented in an AI response can be described incorrectly before its card activates on the next generation. Users repeatedly interpret this as “the card was ignored.” [Story Card activation discussion](https://www.reddit.com/r/AIDungeon/comments/1ttfrp0/why_the_ai_ignore_the_story_cards/)
- **Substring and whitespace collisions:** Short triggers activate inside unrelated words, while space-qualified triggers miss punctuation. [Story Card anti-trigger discussion](https://www.reddit.com/r/AIDungeon/comments/1bbolul/about_story_cards/)
- **Budget disappearance:** Story Cards are among the first dynamic sources to disappear when context is crowded; this is easy to confuse with an activation failure. [Story Card capacity report](https://www.reddit.com/r/AIDungeon/comments/1qvmh5p/anybody_else_problems_with_story_cards/)
- **False summaries:** Users report summaries changing locations, roles, genders, species, and whether events happened at all. Compressed or malformed prose can then influence future narration. [Memory accuracy report](https://www.reddit.com/r/AIDungeon/comments/1ivhg9n/dungeon_ais_memory_system_is_bad/)
- **Semantic retrieval noise:** Memory Bank can retrieve a superficially related but narratively wrong memory, especially across long scenarios. [Memory retrieval report](https://www.reddit.com/r/AIDungeon/comments/1oh06mo/memories_worse_than_usual/)
- **Coverage gaps and duplication:** Information may temporarily exist in neither recent history nor summary/memory, while other facts appear in multiple channels. AI Dungeon’s own rework discussion acknowledges these transition problems. [Memory and summary pipeline discussion](https://www.reddit.com/r/AIDungeon/comments/1q6sb95/a_journey_down_memory_and_summary_lane/)
- **Secret leakage:** A Story Card’s whole entry becomes narrator-visible once its public trigger fires. The system has no claim-level knowledge or observer boundary.
- **Author’s Note dominance:** Placement near the generation point gives it influence disproportionate to its size, so stale or broad notes can override the immediate scene.

### Everquill takeaway

Steal AI Dungeon’s **named prompt lanes, lane-specific minimums, explicit overflow cascade, fixed final placement, and recent-history direction**. Do not import LLM-generated summaries or embedding-ranked Memory Bank retrieval into the authoritative context path.

---

## 3. SillyTavern World Info and vector storage

### Exact keyword activation

SillyTavern World Info combines several independent gates:

- Case-insensitive literal primary keys by default.
- JavaScript regular expressions.
- Configurable case sensitivity and whole-word matching.
- Optional secondary keys with four logics:
  - `AND ANY`: a primary and any secondary.
  - `AND ALL`: a primary and all secondary keys.
  - `NOT ANY`: a primary and none of the secondary keys.
  - `NOT ALL`: a primary unless all secondary keys are present.
- Additional scan sources such as character description, personality, scenario, persona, character note, and creator notes.
- Constant entries that require no key.
- Per-entry activation probability.
- Character/persona filters.
- Inclusion groups.

Only World Info content is normally inserted; entry title and keys are not automatically model-visible. [SillyTavern World Info documentation](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)

### Inclusion groups and randomness

Entries can belong to an inclusion group where only one group member wins. The default group behavior can use weighted random selection. “Prioritize Inclusion” changes this to a deterministic highest-Order winner. Group scoring can further restrict competition to entries with the strongest key-match count.

Thus, the same messages and lore can legitimately produce different context when probability or weighted group selection is enabled.

### Source merging and ordering

World Info can come from chat, persona, character, and global sources. Chat Lore and Persona Lore are merged before Character and Global lore. Character and Global sources then follow a configured merge strategy:

- Sort all together by Order.
- Character first.
- Global first.

Order has two effects:

- During budget competition, constant entries are considered first, followed by normal entries with higher Order.
- For final placement, larger Order values are generally inserted closer to the end of the chosen insertion location.

Entries can be placed before or after character definitions and examples, at the top or bottom of Author’s Note, at a configured chat depth and role, or through named prompt outlets. Author’s Note insertion points are ignored when Author’s Note is disabled.

This creates several distinct “orders”: source merge, admission priority, inclusion-group winner, insertion position, and location-local order.

### Budget handling

World Info has a global activation budget configurable as:

- A percentage of the model context.
- An absolute token cap.

Once exhausted, further entries are not activated for the prompt. Constants receive first consideration; high-Order entries have priority; directly triggered entries are favored over entries reached recursively.

This is a sensible admission principle but can produce silent omissions unless the operator inspects the generated prompt.

### Scan depth and recursion

SillyTavern distinguishes scan depth from recursion depth:

- **Scan Depth** is measured in chat messages.
- Depth zero scans no ordinary chat messages, though recursion and Author’s Note sources may still matter.
- **Min Activations** can extend scanning farther back until enough entries activate, subject to a maximum depth and budget.
- **Max Recursion Steps** controls World Info-to-World Info activation:
  - `0`: no explicit recursion cap; budget eventually stops it.
  - `1`: no recursive pass.
  - `2`: one recursive pass.
  - Higher values add passes.
- Individual entries can be non-recursable, can block further recursion, or can be delayed until a particular recursion level.

Min Activations and Max Recursion Steps are alternative recursion/search-control modes rather than freely composable limits.

SillyTavern also provides message-count-based sticky, cooldown, and delay effects. These counters can differ across branches, edits, and swipes, so replaying the visible tail alone is insufficient to reproduce activation state.

### Vectorized World Info

Vectorized World Info replaces or supplements keyword activation with similarity between recent chat messages and World Info content:

- Entries can be marked vectorized individually or globally.
- Vector activation does not disable keyword activation. An entry with both may activate through either path.
- A separate **Max Entries** limit caps vector results.
- The ordinary World Info token budget still applies afterward.
- Probability, character filters, inclusion groups, and other entry gates remain active.
- Vector retrieval uses configured query messages, not World Info Scan Depth.

The documentation explicitly warns that exact inserted results cannot be predicted and recommends keyword matching where determinism matters. [SillyTavern World Info vectorization](https://docs.sillytavern.app/usage/core-concepts/worldinfo/#vectorized-entries)

The related chat-vectorization system stores old messages or chunks, embeds recent messages as the query, and retrieves prior chunks. Typical defaults described in the documentation include two query messages, roughly 400-character chunks, three retrieved results, and retention of several recent unshuffled messages. Dynamic relevance ordering also harms prompt caching because the retrieved text and its position change between turns. Experimental summarization can further degrade retrieval quality. [SillyTavern Chat Vectorization](https://docs.sillytavern.app/extensions/chat-vectorization/)

Even if one embedding build appears numerically repeatable, its result depends on the embedding model, index version, chunking, threshold, floating-point ties, and rebuild history. That is not a suitable determinism contract.

### Documented and reported failures

- **Configuration invisibility:** Users routinely misdiagnose wrong lore attachment, inadequate budget, Author’s Note being disabled, secondary-key logic, or scan depth as model failure. [Budget configuration report](https://www.reddit.com/r/SillyTavernAI/comments/1negans/lorebook_budget_settings/)
- **Accidental impossible conditions:** An unintended secondary key can stop an entry from ever activating. [Secondary-key failure report](https://www.reddit.com/r/SillyTavernAI/comments/1ugteja/ai_not_reading_the_lore_book_i_wrote/)
- **Anonymous injected text:** Because titles and keys are omitted, otherwise correct lore may not clearly identify its subject. [Anonymous Lorebook-entry report](https://www.reddit.com/r/SillyTavernAI/comments/1u1l8xj/stop_sending_anonymous_lorebook_entries/)
- **Vector noise:** Low thresholds admit irrelevant entries; high thresholds miss paraphrases. Longer query text can make similarity less specific rather than more useful. [Vector-storage operator guide and failure discussion](https://www.reddit.com/r/SillyTavernAI/comments/1s5uvhq/complete_guide_to_setup_and_configure_vector/)
- **Recursive fan-out:** Incidental terms inside one entry trigger other entries until the budget fills.
- **Randomized replays:** Probability and weighted inclusion groups produce different context from identical visible chat.
- **Hidden temporal state:** Sticky/cooldown/delay counters make activation depend on more than the text being scanned.
- **Prompt-cache churn:** Semantically retrieved chunks change order and content across turns; SillyTavern’s own documentation warns this can make vectorization and caching counterproductive.
- **Operational inconsistencies:** Users have reported constant entries failing until lore was recreated or another normal entry existed, indicating attachment, migration, or state-corruption failure modes beyond the documented selector. [Constant-entry failure report](https://www.reddit.com/r/SillyTavernAI/comments/1sfl8oa/lorebook_not_insertingactivating/)

### Everquill takeaway

Steal SillyTavern’s **direct-over-recursive priority, explicit recursion ceiling, visited-entry semantics, Boolean eligibility conditions, source-specific caps, and prompt inspection**. Reject vector activation, probabilities, weighted-random groups, text-derived timed state, and its combinatorial configuration surface.

---

## 4. KoboldAI World Info

### Scope

This section describes the shipped classic **KoboldAI Client** implementation, not every newer KoboldCpp or third-party frontend behavior. The original repository now directs many users toward KoboldCpp but remains the clearest primary source for classic World Info mechanics. [KoboldAI Client repository](https://github.com/KoboldAI/KoboldAI-Client)

### Exact activation mechanism

Classic World Info supports:

- **Constant entries**, which bypass key matching.
- Comma-separated primary keys.
- **Selective mode**, where a primary hit is gated by a hit from the comma-separated secondary-key list.
- Scanning of the current submission and a configurable number of recent historical actions.
- A `World Info Depth` setting whose source default is three historical actions.
- Optional dynamic scanning of generated output in some client modes.

The API exposes entry comment/title, constant flag, content, primary keys, secondary keys, selective flag, UID, and GUI order. [KoboldAI API documentation](https://github.com/KoboldAI/KoboldAI-Client/blob/main/userscripts/api_documentation.md) [KoboldAI source](https://github.com/KoboldAI/KoboldAI-Client/blob/main/aiserver.py)

Classic World Info does not recursively scan the text of newly activated World Info entries for more entries. Operators seeking lore-to-lore activation were advised to place the secondary key in recent story or Memory, or to duplicate content. [KoboldAI recursion discussion](https://www.reddit.com/r/KoboldAI/comments/1207lwl/is_there_a_way_to_fetch_world_info_entries_recursively/)

### Budget and ordering

The classic constructed context is broadly:

1. Memory.
2. Active World Info.
3. Retained story, with Author’s Note inserted at its configured story depth.
4. Current submission.

World Info entries follow the stable list/folder order shown in the GUI. There is no equivalent of NovelAI’s reserved tokens or SillyTavern’s per-entry Order competition.

Active World Info shares the model’s total context with Memory, Author’s Note, retained story, input, and output reservation. If Memory plus active World Info consumes too much space, the implementation can raise an overflow error stating that active World Info keys use too many tokens rather than deterministically pruning low-priority entries.

### Documented and reported failures

- **Common-key flooding:** A broadly used key keeps unrelated World Info active and consumes the story budget. Users have worked around this by disabling entries or copying only the needed facts into Memory. [World Info overflow report](https://www.reddit.com/r/KoboldAI/comments/11kao5l/problem_with_maximun_amount_of_tokens/)
- **No graceful degradation:** Too much active lore can stop generation instead of producing a traceable reduced context.
- **No semantic identity:** The title/comment is management metadata, not necessarily model-visible content.
- **No recursive composition:** A location entry cannot naturally pull its residents, factions, or laws without all necessary keys appearing in scanned story.
- **Model ignores late or crowded facts:** Users report World Info facts losing to recent prose or model invention even while technically present. [World Info memory discussion](https://www.reddit.com/r/KoboldAI/comments/q889j7/any_tips_for_improving_the_ais_memory_of_world_info/)
- **Poor operator comprehension:** In a community survey, fewer than 40% of 111 respondents believed they understood primary keys, illustrating the gap between simple implementation and understandable behavior. [KoboldAI survey results](https://www.reddit.com/r/KoboldAI/comments/zrztn1/survey_results/)

### Everquill takeaway

KoboldAI demonstrates the value of a small, inspectable mechanism, but it also shows why Everquill needs **priority lanes, reservations, bounded graph expansion, and deterministic overflow handling** from the outset.

---

## 5. MemGPT and Letta

### The paging model

MemGPT models an LLM’s context after virtual memory:

- **Main context** is the limited working set visible to the model.
- **External context** is larger storage accessed through functions.
- System instructions are pinned.
- Recent conversation behaves approximately like a FIFO buffer.
- Old conversation can be truncated or recursively summarized.
- Editable core/working memory stores persistent high-value facts.
- **Recall memory** retains the full event history.
- **Archival memory** stores longer-term material outside the immediate context.
- Search functions return paginated results to avoid overflowing the context.
- Memory-pressure events warn the model before compaction so it can save information.
- The model can request a heartbeat or another processing step to continue paging before yielding to the user.

The implementation validates function calls, executes them, and returns tool results or errors to the model. Recall and archival databases may support text, timestamp, and embedding queries. [MemGPT paper](https://arxiv.org/abs/2310.08560)

### Current Letta mechanics

Letta’s modern version exposes **memory blocks** with:

- Label.
- Description.
- Value.
- Character limit.
- Optional read-only status.

Blocks are serialized into a structured, XML-like part of the prompt and remain visible every turn. Descriptions tell the agent how a block should be used. Blocks can be shared between agents; concurrent changes use last-write-wins behavior. [Letta memory blocks](https://docs.letta.com/guides/core-concepts/memory/memory-blocks)

The broader hierarchy is:

1. System instructions and always-visible blocks.
2. Recent conversation.
3. Compacted conversation or summaries.
4. Files available through explicit open, grep, or semantic-search tools.
5. Archival memory outside the immediate context.
6. External RAG or application data.

Archival items are retrieved into context only when the agent calls the relevant tool. [Letta context hierarchy](https://docs.letta.com/guides/core-concepts/memory/context-hierarchy)

### Budget and ordering

MemGPT/Letta does not assign a static priority score to every stored fact. Priority is architectural:

- Pinned instructions and core blocks are always present.
- Recent conversation occupies the working window.
- Compaction makes room when it grows.
- External pages appear only after the model chooses a query and tool.
- Pagination limits each retrieval response.
- Core block character limits bound always-on material, although current product behavior and limits have changed over releases.

This is true paging rather than precomputed top-\(K\) packing.

### Documented and reported failures

- **Lossy recursive summarization:** The MemGPT paper explicitly recognizes that recursive summaries lose detail.
- **Incorrect tool behavior:** The paper reports that weaker models frequently emitted malformed or hallucinated function calls; reliable memory management depended heavily on model capability.
- **Retrieval non-determinism:** The LLM decides whether to search, which query to issue, which page to request, and what to retain.
- **Memory-write non-determinism:** The model decides which facts deserve core or archival memory and how to phrase them.
- **Stale or noisy accumulation:** Unattended agents can preserve obsolete conclusions or low-quality summaries without a deterministic consolidation rule.
- **Concurrent update loss:** Shared memory blocks use last-write-wins rather than claim-level conflict resolution.
- **Compaction regressions:** Letta release notes document fixes for double or runaway compaction, stale manually edited blocks, structured content lost during summarization, duplicated blocks, and incorrect context-window resets. These fixes show that paging state and compaction boundaries are operationally difficult even in a purpose-built system. [Letta releases](https://github.com/letta-ai/letta/releases)
- **Provider-dependent tool reliability:** Users have reported inconsistent memory and tool-call behavior across OpenAI, Anthropic, and local models. [Letta tool-call issue](https://github.com/letta-ai/letta/issues/1776)

### Everquill takeaway

Steal the **hierarchy, pinned working set, pressure telemetry, explicit external pages, and bounded retrieval results**. Do not let the narrator decide what to retrieve, write, compact, or treat as authoritative.

---

## Cross-system conclusions

### What repeatedly works

Across the shipped systems, several patterns improve reliability:

- Keeping enduring facts separate from recent prose.
- Giving high-value material reserved capacity.
- Separating admission priority from final prompt placement.
- Limiting recursive expansion.
- Showing operators the actual assembled context.
- Keeping recent actions in chronological order.
- Making external memory page-sized rather than dumping the entire store.
- Using explicit, self-contained records instead of assuming the model can infer what anonymous text describes.

### What repeatedly fails

The same failures recur despite different interfaces:

1. Text triggers are mistaken for entities.
2. Relevance retrieval is mistaken for truth or narrative eligibility.
3. “Active” is mistaken for “actually admitted under budget.”
4. A model-generated summary is treated as a faithful historical record.
5. Secret and public information coexist in the same activated text block.
6. Priority ties and hidden state make prompt reconstruction unreliable.
7. Records are trimmed into ambiguous fragments.
8. Operators cannot explain why a record was included or excluded.

---

## The 10 mechanics Everquill should steal

1. **Typed prompt lanes with fixed placement.**  
   Build separate lanes for narrator contract and action outcome, perceived scene, present entities, known claims, active clocks, canon excerpts, and recent narration. Give each lane a stable location in the prompt.

2. **Per-lane minimums, ceilings, and an explicit spill cascade.**  
   Reserve room for the outcome, scene manifest, present-entity identifiers, and urgent clocks before admitting optional claims or canon. Publish the exact order in which optional lanes lose capacity.

3. **Structured activation predicates.**  
   Replace keywords with queries over entity IDs, scene membership, observer knowledge, location, claim scope, world timestamp, clock state, and relationship type. Display names should never be selectors.

4. **Direct eligibility outranks transitive expansion.**  
   Claims directly about a present entity, current location, current action, or due clock should beat records reached through relationships. This preserves SillyTavern’s best recursion-priority rule without lexical recursion.

5. **Bounded graph expansion with a visited set.**  
   Any relationship expansion should declare allowed edge types, maximum hops, maximum fan-out per root, and a global candidate ceiling. Cycles should terminate by stable record ID, not by budget exhaustion.

6. **A stable total order with a final unique-ID tiebreaker.**  
   Every query must end with a complete `ORDER BY`, including explicit null ordering and canonical collation. A plausible ordering tuple is lane priority, directness, current-scene membership, clock urgency, world recency, provenance priority, then immutable record ID.

7. **Atomic, self-identifying, provenance-bearing records.**  
   Every injected claim should identify its subject and include the narrator-relevant source, observer, method, world time, scope, confidence, and contradiction/supersession status. Maintain canonical full and compact renderings; never token-slice a record into an unidentified fragment.

8. **Explicit temporal validity rather than hidden cooldown state.**  
   Represent activation intervals, expiry, supersession, and clock deadlines in authoritative world time. Avoid turn-local sticky state or random activation probabilities.

9. **Hierarchical paging controlled by the assembler.**  
   Keep the scene working set hot, claims and recent events in structured recall, and canon in colder storage. The assembler—not the narrator—issues deterministic page queries and decides which page fits.

10. **A first-class context receipt.**  
    For every turn, record state snapshot/version, policy version, tokenizer version, query parameters, candidate IDs, accepted IDs, exclusion reasons, token counts, compact/full rendering choice, final order, and a hash of the serialized context. This is the equivalent of NovelAI’s Context Viewer upgraded into a replay artifact.

---

## The 5 failure modes Everquill must test against

1. **Context avalanche**

   Construct a scene containing entities with dense, cyclic relationships, common aliases, many active clocks, and hundreds of locally relevant claims. Verify that expansion stops at declared hop, fan-out, candidate, and token ceilings; direct scene facts remain present; and repeated runs select identical IDs.

2. **Budget knife-edge and priority ties**

   Create equal-ranked records where the next record exceeds the budget by one token. Vary database insertion order, query plan, process restart, and storage engine. The same atomic record must always win, no record may be partially serialized, and the final context hash must remain identical.

3. **True-stat and spoiler taint**

   Seed engine-only sheets and hidden claims with unique canary strings, including values connected to public entities through relationships. Run ordinary, recursive, compact-rendering, error, logging, and receipt paths. The canaries must never appear in candidates, serialized context, model request logs, or diagnostics.

4. **Stale and contradictory knowledge**

   Give different observers incompatible claims about the same subject, then supersede one claim without deleting its history. The narrator should receive only claims eligible for the current observer, with provenance and contradiction state intact. The assembler must not silently resolve them using true state or confidence alone.

5. **Replay, edit, and clock-boundary drift**

   Reconstruct the same world snapshot from differently ordered event replays and require a byte-identical context. Then advance the authoritative clock by one tick or change one claim’s knowledge scope and verify that only the expected records change. Pin tokenizer and policy versions so an infrastructure upgrade cannot masquerade as a state change.

---

## Where Everquill’s structured store can beat all of them

| Prior-art weakness | Everquill advantage |
|---|---|
| Names and substrings stand in for identity | Queries use immutable entity, location, event, claim, and clock IDs |
| Similarity stands in for eligibility | Eligibility is a Boolean result of scope, observer, provenance, time, and scene rules |
| Whole lore entries mix public and secret facts | Knowledge is claim-granular; narrator-safe projections can exclude inaccessible claims before serialization |
| Text recursion follows incidental words | Expansion follows an allow-listed typed relationship graph |
| Model summaries become pseudo-history | Append-only events remain authoritative; summaries, if used at all, are disposable presentation artifacts |
| Hidden cooldowns, probability, or model choices affect activation | Every selector input is part of explicit authoritative state |
| Trimming produces anonymous fragments | Records have deterministic full/compact variants and are admitted atomically |
| Budget exclusion is silent | Every exclusion has a lane, reason, token cost, and receipt entry |
| Model memory writes accumulate stale conclusions | Claims preserve source, observer, method, timestamp, corroboration, contradiction, and supersession |
| Secrets are protected by hoping their key does not fire | True state is absent from the assembler’s schema and data-access authority |

### Required information-flow boundary

The strongest advantage only exists if Everquill enforces the true-stat rule architecturally:

- Define a `NarratorStateView` or equivalent type containing only outcome tier, perceived scene data, known-sheet projections, narrator-eligible claims, active clock presentations, and canon references.
- Give the assembler a repository interface or database view that cannot query true-sheet columns or tables.
- Do not pass a generic game-state object and rely on serializer exclusions.
- Generate known-sheet projections from knowledge and observation records, not by joining to the true sheet at prompt time.
- Use allow-list serialization; unknown fields must fail closed.
- Keep context receipts limited to narrator-safe identifiers and selection metadata.
- Run canary-based information-flow tests in CI.
- Treat any true-stat appearance in candidates—not merely in the final prompt—as a security failure.

### Recommended deterministic assembly shape

A suitable 2–3k-token build sequence is:

1. Reserve the narrator contract, resolved typed-action outcome, and perceived scene manifest.
2. Add present-entity identifiers and known-sheet slices in immutable entity-ID order.
3. Query directly relevant claims by subject, location, observer, scope, and world time.
4. Perform bounded typed-edge expansion for explicitly allowed supporting claims.
5. Add active clocks in urgency order with a stable clock-ID tiebreaker.
6. Admit canon excerpts and recent event presentations from their remaining lane budgets.
7. Select each record’s full or precomputed compact representation.
8. Serialize through a canonical formatter using a pinned tokenizer.
9. Emit the context and its receipt/hash together.

This turns memory assembly from a probabilistic retrieval problem into a deterministic compilation step. The LLM may vary its narration, but it will vary from the same evidence package whenever authoritative state is the same.

## Sources

### Primary documentation, code, and papers

- [NovelAI Lorebook](https://docs.novelai.net/en/text/lorebook/)
- [NovelAI Advanced Context Settings](https://docs.novelai.net/en/text/editor/advancedsettings/)
- [AI Dungeon: What Goes Into the Context Sent to the AI](https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai)
- [AI Dungeon Story Cards](https://help.aidungeon.com/faq/story-cards)
- [AI Dungeon Plot Essentials](https://help.aidungeon.com/faq/plot-essentials)
- [AI Dungeon Author’s Note](https://help.aidungeon.com/faq/what-is-the-authors-note)
- [AI Dungeon Memory System](https://help.aidungeon.com/faq/the-memory-system)
- [SillyTavern World Info](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)
- [SillyTavern Chat Vectorization](https://docs.sillytavern.app/extensions/chat-vectorization/)
- [KoboldAI Client repository](https://github.com/KoboldAI/KoboldAI-Client)
- [KoboldAI Client source](https://github.com/KoboldAI/KoboldAI-Client/blob/main/aiserver.py)
- [KoboldAI API documentation](https://github.com/KoboldAI/KoboldAI-Client/blob/main/userscripts/api_documentation.md)
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)
- [Letta Memory Blocks](https://docs.letta.com/guides/core-concepts/memory/memory-blocks)
- [Letta Context Hierarchy](https://docs.letta.com/guides/core-concepts/memory/context-hierarchy)
- [Letta releases and compaction fixes](https://github.com/letta-ai/letta/releases)
- [Letta tool-call reliability issue](https://github.com/letta-ai/letta/issues/1776)

### User and operator reports

- [NovelAI: cascading activation versus insertion order](https://www.reddit.com/r/NovelAi/comments/ot969t/cascading_activation_or_insertion_order_which_to/)
- [NovelAI: Lorebook secret and backstory leakage](https://www.reddit.com/r/NovelAi/comments/1sr0q6y/how_can_you_write_lorebooks_in_a_way_that_doesnt/)
- [NovelAI: keys and key-relative insertion](https://www.reddit.com/r/NovelAi/comments/zuf6ar/lorebook_keys_not_activating_from_story_context/)
- [NovelAI: long-story context pressure](https://www.reddit.com/r/NovelAi/comments/1ghu50e/trouble_understanding_how_people_run_longer/)
- [AI Dungeon: Story Cards appearing ignored](https://www.reddit.com/r/AIDungeon/comments/1ttfrp0/why_the_ai_ignore_the_story_cards/)
- [AI Dungeon: Story Card trigger collisions](https://www.reddit.com/r/AIDungeon/comments/1bbolul/about_story_cards/)
- [AI Dungeon: Story Cards under context pressure](https://www.reddit.com/r/AIDungeon/comments/1qvmh5p/anybody_else_problems_with_story_cards/)
- [AI Dungeon: automatic memory accuracy](https://www.reddit.com/r/AIDungeon/comments/1ivhg9n/dungeon_ais_memory_system_is_bad/)
- [AI Dungeon: incorrect Memory Bank retrieval](https://www.reddit.com/r/AIDungeon/comments/1oh06mo/memories_worse_than_usual/)
- [AI Dungeon: memory and summary coverage](https://www.reddit.com/r/AIDungeon/comments/1q6sb95/a_journey_down_memory_and_summary_lane/)
- [SillyTavern: Lorebook budget omissions](https://www.reddit.com/r/SillyTavernAI/comments/1negans/lorebook_budget_settings/)
- [SillyTavern: secondary-key activation failure](https://www.reddit.com/r/SillyTavernAI/comments/1ugteja/ai_not_reading_the_lore_book_i_wrote/)
- [SillyTavern: anonymous injected Lorebook entries](https://www.reddit.com/r/SillyTavernAI/comments/1u1l8xj/stop_sending_anonymous_lorebook_entries/)
- [SillyTavern: vector-storage configuration and noise](https://www.reddit.com/r/SillyTavernAI/comments/1s5uvhq/complete_guide_to_setup_and_configure_vector/)
- [SillyTavern: constant-entry insertion failure](https://www.reddit.com/r/SillyTavernAI/comments/1sfl8oa/lorebook_not_insertingactivating/)
- [KoboldAI: World Info context overflow](https://www.reddit.com/r/KoboldAI/comments/11kao5l/problem_with_maximun_amount_of_tokens/)
- [KoboldAI: World Info memory limitations](https://www.reddit.com/r/KoboldAI/comments/q889j7/any_tips_for_improving_the_ais_memory_of_world_info/)
- [KoboldAI: lack of World Info recursion](https://www.reddit.com/r/KoboldAI/comments/1207lwl/is_there_a_way_to_fetch_world_info_entries_recursively/)
- [KoboldAI community survey](https://www.reddit.com/r/KoboldAI/comments/zrztn1/survey_results/)