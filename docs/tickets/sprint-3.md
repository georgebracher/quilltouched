# Sprint 3 — Knowledge & the Codex (the metagame earns its screen)

Built while George is away from testing — additive on proven architecture, independent of playtest feel. Rules unchanged: bounded tickets, read before changing, summarize plan first, no scope creep. Binding: roadmap §3.3 (Chronicle/Inquiry), §3.6 (knowledge sources scope), isekai-playbook §3 (two-layer Codex) + §5 (LN deep-cut appraisal/knowledge-gating), docs/research/data-layer/claude-synthesis.md §2.3 (claim lifecycle — ALREADY SHIPPED as claims.py; you consume it).

**Sprint DoD:** a player researches something ("search the archive for anything on the Quarryman"), the engine resolves it against THIS source's scope, writes an Inquiry claim (right on success, confidently-WRONG on a bad roll), it appears on the Codex screen as a provenance-stamped card, the player pins cards into a hypothesis and re-researches to confirm/deny; the map shows only seen places. Appraisal reveals FIELDS not numbers. Knowledge unlocks new actions (a known weak point becomes a targetable action). Engine 335+ / API green throughout.

## Critical DB-contention rule (learned 3x)
Every DB-touching agent: `pgrep -fl pytest` MUST be empty before starting a suite; run your suite ALONE on YOUR OWN uniquely-named scratch DB (create `everquill_test_<yourteam>` from the .env base URL). NEVER two suites on one DB.

## Team A — engine: research resolution + knowledge-gated actions
Lane: everquill_engine/**, tests/**, migrations/0012_*.sql, docs/engine/**. Own scratch DB `everquill_test_s3a`.
- Research/observation resolution writes Inquiry claims via the shipped claims.py: success → accurate claim (predicate + value from source scope); **bad roll → a confidently-WRONG claim at high strength** (deterministic wrong value from the source's error profile — never random; reproducible). Rumor arrives as low-strength claims.
- **Source scope**: a source entity (library/archive/sage/veteran) carries a `knowledge_scope` (subjects it can speak to + max appraisal tier + an error profile). Researching a subject outside scope returns "nothing here — but a lead" (a pointer claim to a better source). Team B authors the scopes; you build the resolution + the `lead` outcome shape.
- **Appraisal tiers** (Kumo model): research depth reveals FIELDS not accuracy — tier 0 surface desc → tier N ranged estimate + provenance. Never exact numbers to KnownState.
- **Knowledge-gated actions**: an action targeting a known weak point (a claim of predicate `weak_point`/`threat_assessed` about an entity) becomes available/altered — a "hopeless" fight gains a "desperate" option when the intel exists. Wire the resolver to consult the actor's claims for target-specific action modifiers.
- **Folded-in polish (engine):** (a) surface `coin` (+ active timers) on the KnownState ChronicleFacts so the API can serve the status strip — D needs it; expose via views.py. (b) R2-09 narration-as-canon: wire the narration_generated event (A2 added the type+fold) so the API can append prose+assembler_version+content_hash bound to the outcome under an idempotent `narrate:<ulid>` command — provide the store entry point + document the api call in docs/engine/api-wiring-notes.md (append, don't edit api/).
- Tests + goldens per replay rules; projector bumps where folds change.

## Team B — content: knowledge sources, scopes, wrong-intel
Lane: docs/lore/**, content/world/** (not dev-fixture, not slots.yaml structure).
- Author `knowledge_scope` for Harrowdown's sources: the guild board, Maren (road/local rumor), the Skill Church records, a Harrowdown archive/scholar if one exists (add one if the town lacks a real research site — a parish clerk, a hedge-scholar), and the burned-province lead for real dragon/wyvern lore (distance = the drama). Each: subjects, max appraisal tier, error profile (what wrong answer this source confidently gives — the ballads-lie mechanic).
- Expand the deterministic wrong-intel plants (already 3 in the bestiary) into the claim/scope system so failed research yields authored-flavored wrong answers, not generic ones.
- Appraisal-tier text for the key entities (Quarryman, barrow wight, the chandler's secret) — surface bands vs deep truths.
- Register per ai-tells constraint block. Coordinate field shapes with A (propose in report; A owns loader).

## Team C — LLM: research parsing, appraisal output, Codex assembly, held-out evals
Lane: docs/contracts/**, evals/**, llm/**.
- Parser: research/observation intents already parse; add held-out coverage for research phrasings ("look into", "ask around about", "study the", "check the records for"). **Build a FRESH held-out set (evals/heldout-2.jsonl, 30 cases) authored WITHOUT reading prompt p9's worked examples** (C's own flagged caveat) — report true uncontaminated accuracy.
- Assembler: surface Inquiry claims + contested pairs into narration context so the narrator can voice "the ballads say X, but the archivist doubts it"; ensure appraisal/research outcomes narrate the finding, not raw data.
- Codex-facing formatting helpers (pure, in llm/ or a shared module the client's API consumes via F later): fact-card render shape (claim → {text, source, when, confidence-word, contested?}), hypothesis evaluation (given pinned claim ids, what research target resolves them) — this is logic the API will call; define the interface.

## Team D — client: the Codex screen + status strip
Lane: client/**.
- **Codex screen** (the deep one, roadmap §3.8 nav rail already stubs it): fact cards from the player's Inquiry claims (via a new authed GET /api/codex — coordinate the shape with what A/C expose; if the endpoint isn't live yet, build against the claim/InquiryClaim shape in docs and a local fixture, wire to real when F lands it — FLAG clearly, do not ship mock data as if real). Filters (by subject/source/recency), contradiction badges on conflicting cards (the engine marks contested — render it, never invent connections), hypothesis pinboard (snap 2+ cards → a hypothesis with an optional typed note → a research-target chip that pre-seeds the composer). Map-in-Codex v0: known locations only (from scene history / travel claims), blank past the ridge.
- **Status strip**: add coin + active timer once A/F expose them on the scene or a facts endpoint (the gap you flagged in S2). Date already there.
- Keep the layout-v2 skin; mobile-first; build green; bump eq-shell cache.

## Team F (after A + C) — API surface
Lane: api/**, migrations (apply), docs/ops/**. Own scratch DB.
- GET /api/codex (authed): the player's Inquiry claims as fact cards (KnownState only — no true values), filterable; POST /api/hypothesis (pin claim ids + note → stored, returns research-target suggestions). Wire narration-as-canon (A's entry point). Add coin/timer to the scene or a /api/facts endpoint for D's status strip.
- Deploy + live-verify: research an entity → card appears in /api/codex; a bad-roll research → a wrong card; redaction still holds. Per-turn cost unaffected.

## Held for AFTER George's playtest (do not start)
Sprint 4 combat-danger tuning (hopeless bands feel, sealed-feat components); ALL of Sprint 5 (death/heir/legacy — depends on the core loop feeling right). Safe S4 additive parts (rumor propagation, adjudicator + precedent ledger) are the natural playtest-independent follow-on to THIS sprint if momentum continues.
