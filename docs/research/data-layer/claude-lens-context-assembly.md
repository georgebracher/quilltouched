# Context Assembly & Salience — Research Report for Everquill's Context Assembler

**Lens:** picking the right ~2–3k tokens from 500k+ facts, deterministically. Verdict up front: the committed architecture (structured queries, no vector similarity in the hot path, assembler as a named deterministic component) is **well supported by current evidence** — vector retrieval is now a documented reproducibility hazard, and the closest shipped analogs to your assembler (NovelAI's lorebook engine, Zep's temporal graph) are structured, not embedding-first. The main gaps in the committed design are: (a) no defined **total ordering / tie-break discipline**, (b) no **stability (anti-churn) term**, and (c) no stated **summarize-vs-quote policy** for canon excerpts. All three are where drift actually enters. Details below.

---

## 1. What the literature gives us (and what to reject)

### 1.1 The salience triad — adopt the shape, replace two of three legs

Park et al.'s Generative Agents ([arXiv 2304.03442](https://ar5iv.labs.arxiv.org/html/2304.03442)) is the canonical formula: `score = α·recency + α·relevance + α·importance`, with recency as exponential decay (factor **0.995 per sandbox game-hour**), importance as an **LLM-rated 1–10 integer**, relevance as **embedding cosine similarity**, all min-max normalized to [0,1], equal weights, top-ranked memories packed until the context is full.

For Everquill, keep the triad structure but swap components:

- **Recency**: keep, but drive it off the **world clock** (you have one), not wall time — same as Park's sandbox-hours choice.
- **Importance**: replace LLM-rated importance with **deed notoriety** computed by deterministic rules at write time. LLM importance scoring is nondeterministic and re-rateable; notoriety-from-rules is replayable from the event log. This is strictly better for your requirements.
- **Relevance**: replace cosine similarity with **structured overlap** (subject-in-scene, location scope, one-hop entity links). This is the big deviation and it's justified — see 1.2.

Also reject Park's **min-max normalization over the candidate set**: it makes each claim's score depend on what else is in the candidate pool, so an irrelevant new event elsewhere can reshuffle ranks. Use fixed bounded transforms instead (each component independently maps to [0,1] by its own formula, never relative to siblings).

### 1.2 Structured retrieval vs vector RAG — your consistency requirement decides it

The reproducibility literature has caught up with what you intuited: even with identical inputs, vector-based retrieval produces different results across runs, and the retrieval stage is the dominant source — embedding model versions, float precision, ANN algorithms, hardware, and distributed execution all inject variance ([On the Reproducibility Limitations of RAG Systems, arXiv 2509.18869](https://arxiv.org/abs/2509.18869); the [ReproRAG framework](https://www.emergentmind.com/topics/reprorag-framework) exists precisely because this nondeterminism was previously only anecdotal). The deterministic alternative — SQL/structured lookups where **the same query produces the same result every time** — is a recognized pattern ([RAGdeterm](https://www.sciencedirect.com/science/article/pii/S2352711026001299), which replaces embeddings with a relational store for exactly this reason; [overview](https://medium.com/@silverskytechnology/deterministic-vectorless-vs-semantic-vector-retrieval-in-rag-3bda54a0f900)).

**Confirmed: keep vectors out of the turn path entirely.** If you ever want fuzzy matching (e.g., "the scarred merchant" → entity resolution), do it in the **intent parser** (LLM side, already nondeterministic-tolerant), never in the assembler.

### 1.3 MemGPT/Letta — take the OS metaphor, reject the pager

MemGPT's contribution is the tiered memory model (small fixed "core" context = RAM; archival/recall stores = disk; paging between them) ([MemGPT/Letta overview](https://www.leoniemonigatti.com/blog/memgpt.html), [Letta on agent memory](https://www.letta.com/blog/agent-memory/)). But in MemGPT **the LLM itself decides when to page** via function calls — that is the anti-pattern for Everquill. Your assembler is the pager, and it's engine code. The useful import is the *tier discipline*: a fixed-size always-present core (scene manifest + clocks), a queried tier (claims, known-sheets), and a cold tier (full deed log) that never enters context except as sealed excerpts.

### 1.4 Zep/Graphiti — independent validation of the claim store

Zep's temporal knowledge graph ([arXiv 2501.13956](https://arxiv.org/html/2501.13956v1), [Graphiti](https://github.com/getzep/graphiti), [Neo4j write-up](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)) converged on almost your exact claim schema from the production-agent direction: every fact edge carries **validity intervals (valid_at/invalid_at)**; contradicted facts are **superseded, not deleted** (old edge's window closes, new edge opens, history stays queryable); and it's **bi-temporal** — tracking when an event *occurred* vs when it was *learned*. Two recommendations from this:

1. Make your claim store explicitly bi-temporal: `world_timestamp` (when the fact happened) **and** `acquired_at` (when this observer learned it). You listed acquisition method but the two timestamps do different work — recency decay should run on `acquired_at` for gossip freshness, while contradiction resolution runs on `world_timestamp`.
2. On contradiction, **close the old claim's validity window rather than overwrite** — you get "what did Mara believe last spring" for free, which the legacy/heir system will want.

### 1.5 NovelAI's lorebook — the closest shipped prior art, steal three mechanisms

NovelAI's context builder is the most battle-tested deterministic narrative context assembler in production ([lorebook docs](https://docs.novelai.net/en/text/lorebook/), [advanced settings](https://docs.novelai.net/en/text/editor/advancedsettings/)): keyword/state-triggered entries assembled in explicit **stages by Insertion Order**, with each entry carrying a **Priority**, a **Token Budget** (absolute or % of context), and **Reserved Tokens** — reservations are allocated *before* any entry is placed, guaranteeing critical sections can't be starved by verbose ones. Adopt all three: per-section reserved minimums, per-section caps, and a fixed insertion order (which also gives you the position control §1.6 demands).

### 1.6 Position matters: "lost in the middle"

LLMs show a U-shaped attention curve — recall is best for content at the beginning and end of context, worst in the middle (Liu et al.; see [Found in the Middle](https://arxiv.org/pdf/2406.16008) and [follow-up analysis](https://arxiv.org/pdf/2510.10276)). At 2–3k tokens the effect is mild but real. Layout rule: **canon constraints and scene manifest first, filler-ish claims in the middle, the player's action + active clocks + narration instructions last.** The things the narrator must not contradict go at the edges.

### 1.7 Summarize vs quote — where drift actually comes from

The compaction literature is unambiguous: repeated LLM summarization causes **summarization drift** — each pass silently discards low-frequency details until the agent "remembers" a sanitized, generic version of history ([Morph: compaction vs summarization](https://www.morphllm.com/compaction-vs-summarization)). The consensus policy ([same source](https://www.morphllm.com/compaction-vs-summarization); [Anthropic's context engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)): **store/quote verbatim** precise facts, numbers, names, outcomes; **summarize** only narrative connective tissue; keep high-value items anchored verbatim and never re-summarize them. Anthropic's core curation principle — "the smallest set of high-signal tokens that maximizes the likelihood of the desired outcome" — also validates your 2–3k budget over a lazy 20k dump: more context measurably degrades recall via context rot.

Everquill translation:
- **Claims and canon outcomes are never LLM-summarized in the turn path.** They render through **fixed deterministic templates** (`{observer} believes {subject}'s {attribute} is {value} — heard from {source}, {age} ago, {confidence}`). Template output is replayable; LLM paraphrase is not.
- **Chronicle summaries** (e.g., "the last three months in Vellich") are allowed but must be: generated offline (Batch API fits), **written back into the event log as their own events**, pinned by content hash, and only ever regenerated from the *original events* — never from a previous summary (no summary-of-summary chains; that's the drift vector).
- Recent narration: last 2–3 exchanges **verbatim**, older scene turns via one sealed scene summary.

---

## 2. Deliverable A — Scoring formula proposal

Score every candidate claim `c` (from the POV observer's claim store, pre-filtered by a cheap SQL candidate query: subject ∈ scene entities OR location ∈ {scene location, parent region} OR subject referenced by an active clock — keeps the scored set to hundreds, not 500k).

```
salience(c) = 100·V(c) + 60·N(c) + 40·R(c) + 40·K(c) + 30·O(c) − 50·D(c)
```

All components map independently to [0,1] via fixed transforms — **no set-relative normalization**. Compute in **integer basis points** (multiply weights by claims' component scores expressed as integers /1000) so scores are bit-identical across platforms; no floats in the ranking path.

| Term | Meaning | Deterministic computation from inputs you have |
|---|---|---|
| **V — structural relevance** | overlap with scene | subject is an entity present: **1.0**; subject one hop from a present entity (faction/kin/master link in entity graph): **0.6**; claim scope == scene location: **0.8**; scope == parent region: **0.4**; subject is the player's active quest target: **0.7**; take the **max**, not sum |
| **N — notoriety** | importance proxy | deed notoriety `n ∈ [0,10]` assigned by write-time rules (death 9, oath/betrayal 7–8, duel 5–6, commerce 1–2) → `n/10`. Never re-scored |
| **R — recency** | freshness | `2^(−Δ/h)` where Δ = world-hours since `acquired_at`, half-life `h` from a **category table**: gossip 72h, sightings 168h, biography 2160h, world-structure ∞ (R=1). Mirrors Park's decay but with legible half-lives instead of magic 0.995 |
| **K — clock coupling** | urgency | claim's subject or location is referenced by an active clock due within horizon H (e.g., 48 world-hours): `1 − time_to_due/H`, else 0 |
| **O — thread stickiness** | anti-churn | subject was referenced in narration events of the last 3 turns (this is *in the event log*, so still a pure function of log prefix): turn-1 → 1.0, turn-2 → 0.6, turn-3 → 0.3 |
| **D — redundancy** | dedupe | claim's (subject, attribute) already covered by a known-sheet slice or a higher-ranked claim already packed: 1, else 0 (evaluated during packing, greedy) |

**Notes on the design:**
- **Confidence deliberately does NOT gate inclusion.** A confidently-held wrong claim is exactly what must reach the narrator; confidence is *rendered in the template*, not used to rank. Bonus: if a claim in-context is actively contradicted by another claim the observer also holds, include **both** with the contradiction link rendered — contradictions are dramatic fuel and the schema already tracks them.
- **Total order requirement:** final sort key is `(salience desc, category_rank asc, world_timestamp desc, claim_ulid asc)`. Without the ULID tie-break you don't have "same state → same context," you have "usually the same context."
- **Packing:** first-fit by rank into the claims budget (measure rendered template length; skip-if-too-big and continue — deterministic). **Per-subject cap of 3 claims** — this is your diversity mechanism (an MMR substitute that needs no similarity function).
- **Versioning:** weights, half-life table, notoriety rules, and templates live in a versioned config; every assembled context is stamped with `assembler_version` and its **content hash logged as an event**. That makes every historical turn's context reproducible and auditable — the same guarantee your dice already have.

## 3. Deliverable B — Budget split (2,800-token target)

Fixed insertion order (top→bottom), with NovelAI-style **reserved minimums** allocated first, then elastic overflow redistributed **in the listed priority order**:

| # | Section | Reserve | Cap | Policy |
|---|---|---|---|---|
| 1 | Canon excerpts (sealed outcomes binding this scene: deaths, oaths, verdicts) | 150 | 350 | verbatim template renders; never summarized; **top of context** (primacy) |
| 2 | Scene manifest (location, world-time, weather, entities present + visible status) | 200 | 400 | always full; this is "core memory" — never evicted |
| 3 | Known-sheet slices for entities present | 300 | 650 | per-entity cap ~110 tokens; entities ranked by (interaction recency, notoriety); beyond 6 entities → name+one-liner only |
| 4 | Salient claims (§2 formula) | 400 | 750 | the flex section — absorbs most reclaimed budget |
| 5 | Active clocks (due within horizon) + world pressure | 100 | 200 | tersest section; high leverage |
| 6 | Recent narration: last 2–3 exchanges verbatim + 1 sealed scene summary | 400 | 600 | **bottom of context** (recency position) |
| 7 | Player's parsed action + narration directive | 100 | 150 | very last tokens before generation |

Reserves total 1,650; caps total 3,100; target ≈ 2,800. Unused reserve (e.g., a two-entity scene) flows to claims first, then narration. Rationale: sections 1–2 are the consistency contract (what the narrator must not contradict), section 4 is where believability-per-token is highest, and the small total is a feature — [context rot](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) means a lean curated slice beats a generous one even before cost.

## 4. Deliverable C — Drift-prevention test suite

**Tier 1 — Determinism (pure code, CI on every commit):**
1. **Replay identity:** assemble the same turn twice, and on Linux + macOS runners → **byte-identical** context (the integer-scoring rule exists to make this pass). Hash logged == hash recomputed.
2. **Golden context corpus:** ~50 curated scene fixtures (crowded tavern, dead-NPC references, contradicted intel, heir-inheritance, 30-entity battle) with checked-in golden context files. Any diff requires an explicit `assembler_version` bump in the same commit — standard golden-dataset discipline ([golden datasets vs random sampling](https://www.techment.com/blogs/llm-regression-testing/), [prompt regression testing](https://www.breakthebuild.org/prompt-regression-testing-101-how-to-keep-your-llm-apps-from-quietly-breaking/)).
3. **Irrelevance-injection (metamorphic):** append 10k events in a distant region → target scene's context unchanged. Catches set-relative normalization or candidate-query leaks.
4. **Ordering properties (property-based):** higher notoriety never ranks lower ceteris paribus; subject-present beats subject-absent; newer duplicate beats older; ULID tie-break total order holds under shuffle of insertion order.

**Tier 2 — Safety invariants:**
5. **True-sheet leak test:** fixtures where hidden true stats differ from believed values; assert the true value's rendered form appears **nowhere** in context, the believed (wrong) value does. Plus a static/CI rule: the assembler module may only import projection views, never true-sheet tables.
6. **Budget invariants:** adversarial fixtures never exceed 3,100 tokens; every reserve met; no mid-template truncation (render-then-measure, never slice strings).
7. **Churn bound:** 20 simulated turns with no new events → consecutive contexts differ only in the sliding narration window (diff < 15%). Guards narrator tone/fact whiplash.
8. **Rumor-epoch coherence:** cached region-epoch invalidates iff a qualifying deed is appended; stale-cache read after invalidation event = test failure.

**Tier 3 — Narrator-consumption evals (LLM-level, offline/Batch, nightly not per-commit):**
9. **Answerability probes:** for each golden context, ask the narrator model factual questions answerable only from it ("what does Mara believe about the duel?") and score against the claim store — catches template formats the model can't actually read, and position-sensitivity per [lost-in-the-middle](https://arxiv.org/pdf/2406.16008). Layer evaluators deterministic → semantic → judge ([Traceloop CI pattern](https://www.traceloop.com/blog/automated-prompt-regression-testing-with-llm-as-a-judge-and-ci-cd)).
10. **Summary entailment gate:** a chronicle summary is only sealed as a canon-excerpt event after an offline entailment check confirms every sentence is supported by its source events; regeneration always from original events, never from a prior summary ([summarization drift](https://www.morphllm.com/compaction-vs-summarization)).
11. **Long-horizon consistency canary:** scripted 100-turn playthrough replayed after any assembler/prompt change; judge-scored for contradictions against the deed log; block on regression vs baseline.

## Sources

- [Generative Agents: Interactive Simulacra of Human Behavior (Park et al.)](https://ar5iv.labs.arxiv.org/html/2304.03442)
- [On the Reproducibility Limitations of RAG Systems (arXiv 2509.18869)](https://arxiv.org/abs/2509.18869) · [ReproRAG](https://www.emergentmind.com/topics/reprorag-framework) · [RAGdeterm](https://www.sciencedirect.com/science/article/pii/S2352711026001299) · [Deterministic vs semantic retrieval](https://medium.com/@silverskytechnology/deterministic-vectorless-vs-semantic-vector-retrieval-in-rag-3bda54a0f900)
- [MemGPT/Letta virtual context management](https://www.leoniemonigatti.com/blog/memgpt.html) · [Letta: agent memory](https://www.letta.com/blog/agent-memory/)
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv 2501.13956)](https://arxiv.org/html/2501.13956v1) · [Graphiti](https://github.com/getzep/graphiti) · [Neo4j on Graphiti](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)
- [NovelAI Lorebook docs](https://docs.novelai.net/en/text/lorebook/) · [NovelAI advanced context settings](https://docs.novelai.net/en/text/editor/advancedsettings/)
- [Found in the Middle: positional attention bias (arXiv 2406.16008)](https://arxiv.org/pdf/2406.16008) · [Lost in the Middle as emergent property (arXiv 2510.10276)](https://arxiv.org/pdf/2510.10276)
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Morph: Compaction vs Summarization](https://www.morphllm.com/compaction-vs-summarization)
- [Prompt Regression Testing 101](https://www.breakthebuild.org/prompt-regression-testing-101-how-to-keep-your-llm-apps-from-quietly-breaking/) · [Golden datasets for LLM regression](https://www.techment.com/blogs/llm-regression-testing/) · [LLM-as-judge CI/CD (Traceloop)](https://www.traceloop.com/blog/automated-prompt-regression-testing-with-llm-as-a-judge-and-ci-cd)