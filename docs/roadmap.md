# QUILLTOUCHED — Concept & Build Roadmap

*Brand LOCKED 2026-07-13: **Quilltouched** (George — "they become the touched by the Quill"; the Quill religion lore stays as authored; in-fiction keeps the hyphen "Quill-touched", the brand drops it). The prior working title Everquill is DEAD as a brand (everquill.games is a competing AI-DM game in alpha) but LIVES ON as the internal slug/codename (repo, registry key, Railway/Pages project names, engine package) per house precedent — public surfaces say Quilltouched, infra says everquill until/unless the Sprint 2 rename ticket says otherwise. Player-facing URL: https://quilltouched.gitm.gg (everquill.gitm.gg still resolves; retire it in Sprint 2).*

**One-liner:** A mobile-first, typed-action **isekai-inflected** fantasy RPG where an LLM narrates but never referees — a deterministic math engine owns every roll, every stat, and every fact in a hand-authored, locked universe that permanently remembers everything you do, even after you die.

**Tagline:** *The System records what you know — not what is true.*

**Research inputs:** `docs/isekai-playbook.md` (decision doc) + 11 raw reports in `docs/research/`. The playbook's verdicts are folded into this doc; read it before authoring lore or prompts.

Code name: `everquill` (the engine package and internal names predate the Quilltouched rename).

---

## 1. North Star

Every feature is measured against these five pillars. If a ticket doesn't serve one, it's scope drift.

1. **The engine is the referee, the LLM is the mouth.** No LLM call ever decides success, difficulty, or state. Players cannot talk their way past math.
2. **Type anything, and it matters.** Free-text actions (typed, spoken, or tap-seeded) resolve fairly and permanently. Even failures write world facts.
3. **The universe is locked but alive.** Hand-authored laws; generated cities/NPCs seeded by player history; everything generated is committed to canon forever.
4. **Knowledge is the real progression.** What your character *knows* (true sheet vs known sheet) converts hopeless fights into desperate ones. The Codex is the metagame.
5. **Death is real, the world persists.** No plot armor. Legacy characters inherit a scarred world and almost nothing else.

---

## 2. Core Loop

```
Player input (typed / voice→transcript / tap-seeded from tableau, Codex, Pack)
      ↓
INTENT PARSER (small LLM, structured output)
  → {action_type, target, approach, stat, dialogue?, plausibility_tier}
      ↓
RULES ENGINE (pure Python, deterministic, seeded RNG, zero LLM imports)
  → tier lookup → difficulty from entity TRUE sheet → 2d6+mods roll
  → outcome TIER + state deltas (HP, inventory, flags, position, intel, deeds)
      ↓
STATE STORE (Postgres — single source of truth)
  → deltas committed; deed log appended; rumor propagation queued
      ↓
NARRATOR (quality LLM)
  → fed: outcome tier + KNOWN sheets + scene manifest + canon excerpts
  → writes prose; may commit "furniture" entities (validated, written to state)
      ↓
CLIENT: prose stream + scene tableau re-render from state
```

**Resolution: 2d6 three-tier (PbtA-style).** Strong hit / hit with complication / miss. The "yes, but…" band is where the narrator earns its keep. Every miss writes something (intel, rumor, scar, journal line) — the loop always deposits value.

**Progression: uncapped, band-relative, time-priced.** No level/stat/skill-rank caps anywhere — internal stats are unbounded integers; growth moves actions across the plausibility ladder relative to the stat gap (Hopeless → Desperate → Routine as you grow), so the 2d6 stays honest at every power level. The world NEVER level-scales (locked universe = absolute scale; you permanently outgrow goblins). Grinding = **timed training blocks on the world clock, EXCLUSIVE occupation** (anti-EVE: foreground, not background — training is what the character is doing, you can't do anything else during it; opportunity cost while other clocks tick is the point). Declared blocks ("drill the spear until the caravan leaves") resolve offline: zero marginal LLM cost, natural session-ender, fits one-daily-visit. Committed but interruptible: progress checkpoints per segment (dawn), abort keeps pro-rated gains, world events can break in — training location = exposure. Skip semantics: world-time cost identical waited or skipped (all clocks advance equally); the skip only collapses the real-world wait. Self-training grinds fundamentals; training under a master/facility teaches knowledge-gated specifics (a technique is intel with a source — journals make a dead master's technique learnable). Each next gain costs more time than the last: rising cost, never a ceiling. Displayed without numbers: unbounded skill ranks in the Chronicle (Spearwork IV→V→VI…), deed-minted titles, and self re-tier toasts (`[Reappraised: Wyvern — DESPERATE → ROUTINE]`). Guardrails: grind is optional prestige, never a content gate; power breeds new problem classes (notoriety, politics, things that notice unbounded growth) so stakes survive endgame.

**Character creation:** rolls set aptitudes + origin; **no class picker** — classes and titles emerge from resolved behavior (hidden practice vectors; at thresholds the System offers recognition: Envoy, Pathfinder, Whisper-Regent). Witnessed feats mint titles via the deed log (`[Title Earned: Ratcatcher of Dunmere]`) that propagate by rumor — the XP replacement. Chargen scene = the Quill-touched awakening (god's-waiting-room dress, seeds first possibly-unreliable KNOWN entries).

---

## 3. Systems Spec (locked decisions from concept phase)

### 3.1 Plausibility ladder
| Tier | Rolls? | Behavior |
|---|---|---|
| Trivial | No | Narrate only (tap-verb territory) |
| Routine / Risky / Desperate | Yes | Real 2d6 checks, difficulty from true sheet |
| **Hopeless** | Yes — failure-flavor only | Legal action, no success band. Roll picks *how* you fail (devoured / ignored-then-noticed / the dragon is amused, you live wrecked). Best case is never victory. |
| **Sealed** | Only when components met | Feat gated by authored **laws** (see 3.2). Unmet → fails forward: fiction reacts, deed logged, something noticed you. |
| Impossible | Never | Violates universe physics. Fiction reacts to the attempt ("mad man yells at clouds") — still logged as a deed, still has social consequences. |

**Commit beat:** tiered to the ladder. Trivial/routine = inline ghost-echo auto-commit; Dire-and-up, sealed, or irreversible = full System dialog `<<Assessment: DESPERATE. Proceed?>>` — one dialog per commitment, roll resolves inside it, doubles as parse-confirmation and masks roll latency. Misparse/mishear insurance, not plot armor. Speaks only from common sense + known sheet — never leaks true stats.

**Risk labels (engine-calculated, shown pre-roll, always in words never percentages):** Guarded / Perilous / Dire / Desperate / Suicidal. Post-roll, the dice and known modifiers are shown in full (the Chronicle) — every death must be auditable without trusting prose.

### 3.2 Author laws, not quests
Sealed feats (e.g. resurrection) are defined as **component requirement lists** ("a soul anchor made before death · a life offered in exchange · a place where the veil is thin · within a season · the dead must be willing"), not scripted quest chains. Engine checks components against state — any route that assembles them counts, including routes we never authored. Out-of-band creativity ("does World-Tree sap count as a soul anchor?") escalates to the **adjudicator** (one high-quality LLM call with lore bible + precedent ledger) whose ruling is committed to the **precedent ledger** as permanent canon. The universe accretes case law.

**Magic = cost ledger, not permission list.** Every effect prices in components, time, permanence trade-offs, corruption, attention from entities. Costs are engine-enforced state deductions. Low-magic classic fantasy keeps the classifier's physics legible.

### 3.3 True sheet vs known sheet — the two-layer Codex (Chronicle / Inquiry)
- **True sheet** (engine-only): real stats. Resolver always rolls against these. Never shown, never fed to the narrator.
- **The Chronicle (authoritative KNOWN):** exact immutable facts of record — time, coin, inventory, wounds, named abilities, public guild rank, and post-roll dice results with known modifiers. Narrator cannot contradict it.
- **The Inquiry (fallible KNOWN):** dossiers, motives, weaknesses, geography, threat reads. Every entry carries a provenance stamp (named source, acquisition method, world-date, scope). May be incomplete, outdated, or confidently wrong. UI shows provenance, never confidence bars.
- **Claim schema** (the data model): subject · claim · value/range · source · observer · method · world timestamp · scope · confidence (= evidence consistency, never truth-probability) · corroboration · contradictions · inheritance status.
- **Wrong intel is causal, never random:** deterministic error mechanisms only (contamination, local-mistaken-for-universal, disguise, insufficient appraisal tier, corrupt official, transcription error, outdated info, counterintelligence, inherited note missing its qualifier). Same bad experiment, same conditions → same misleading evidence.
- **Common sense tier** is free category-level knowledge from the lore bible (everyone knows dragons are apex).
- **Research is actions**: Appraisal tiers reveal FIELDS, not accuracy (surface → category → bands → ranged estimate + provenance → motives). Failed research writes *wrong intel at high confidence* (the ballads lie). Rumors arrive as ambient low-confidence intel, distorted by distance.
- **Intel changes the action space**: techniques are knowledge-gated (no universal skill tree — you can't attempt what you don't know exists); "punch the dragon" is hopeless forever; "the bare patch on its left breast" only exists in your action space because you know it exists. Research converts hopeless → desperate. The re-tier toast IS the level-up: `[Reappraised: HOPELESS → DESPERATE]`.

### 3.4 Deed log & rumor propagation
Every significant outcome (including deaths and impossible-tier attempts) is a deed: fact, location, witnesses, notoriety score. Rumors propagate by distance/time/sensationalism — the next village knows, the far coast doesn't (or knows a distorted version). Worldgen consumes the deed log: new cities/NPCs are generated downstream of player history.

### 3.5 Two-speed generation
- **Furniture** (narrator, inline): guard names, alleys, taverns — validated, committed to state.
- **Structural** (worldgen step, offline): cities, factions, NPCs of importance — generated with lore bible + deed log as inputs, validated, committed. The narrator can never improvise a duke.

### 3.6 Knowledge sources have scope
Libraries/sages/archives get catalogs derived from region + history + proximity-to-subject. Peak dragon intel lives near where dragons were fought. Distant sources degrade to confident-but-wrong ballads, not absence. Failed local research returns **leads** ("the monastery at the pass keeps the dragonslaying records") — the zero-authoring quest generator.

### 3.7 Legacy system
World is source of truth; the PC is just an entity. On death: entity persists (corpse, grave, reputation, enemies, stash, unfinished business). **Inheritance is brutally thin**: the world remembers everything, the heir inherits almost nothing. Isekai framing: entry = local **"Quill-touched"** awakening (the blessing is Codex-sight, soul-bound → heirs keep it; natives can't see the System); heir roll voiced in reincarnation language.

**Heir flow (6 phases, target <90s from death to first meaningful heir decision):** (1) sealed death — engine commits the full death record before narration; most deaths abrupt, no auto-eloquence; (2) silence + factual death card (Mourn / See what the world did / Choose heir); (3) world pulse — advance only justified time, show only what the heir could know; (4) three candidates — kin / apprentice / finder-stranger, no rerolling, declined candidates persist as NPCs; (5) stance toward the dead (complete/avenge/understand/protect/clear/reject/exploit — nonbinding); (6) enter through an event, not a menu.

**Journals:** low-friction capture — after significant scenes the engine proposes 2–5 grounded facts, player picks what the character records (+optional typed/voice note). Journals are world objects under deterministic rules (carried/cached/sent/stolen/burned; destruction always telegraphed). A journal can be wrong — the heir inherits the claim, not the truth.

**Death discipline:** death possible, not routine — injury/capture/retreat/disgrace carry most failure weight; no grief taxes or heir debuffs; memorials are concrete facts, never generated praise; append-only canon (savescumming structurally dead); no death farming — dying never yields power/currency/components. Heir restarts at the world's narrative altitude, never the tutorial.

**Resurrection** of a prior PC: five inspectable laws (identity · memory · vessel · passage · power), known early, achieved endgame — and it **never rewinds**: the heir's deeds stay real, the resurrected returns displaced by elapsed history. A difficult reunion, not a loaded save.

### 3.8 Client — 4 screens, mobile-first PWA
**Play screen layout v2 (George's mock, 2026-07-13 — supersedes the v1 chip-strip):** portrait, five zones top-to-bottom: (1) status strip — world date, coin, active timer (Chronicle-exact facts, numerals allowed); (2) **scene canvas** dominating the upper half — location background (Team E's per-type set) with entity sprites POSITIONED in the room via authored anchor slots per location type + deterministic slot assignment (same scene → same arrangement; scene manifest gains slot hints — Team A/B, Sprint 2); created/dropped items appear in-scene; tap = known-sheet card + target pre-select; fog-of-war unchanged (render only the perceived manifest); (3) right-edge navigation rail to Character/Pack/Codex; (4) **compact transcript** below the scene (scene-first, text-second) — System lines (assessment, dice) stay legible in compact view, full Chronicle one tap away (the dice are the trust surface); (5) typed composer at the bottom. First-session legibility rule from S1 playtest: lead canned/suggested actions with ones that roll dice; "look around" becomes the narrator's atmospheric payoff once prose lands.
**UI language = the isekai System grammar, in the "Inked System" skin** (quill-stroke chrome, vellum-dark fill, restrained glow — the Quill IS the System, so the journal/heir fiction and the UI are the same object). `[bracket]` toasts, `???` for unknown fields (including your own stats), three outcome chimes, `<<Proceed?>>` dialogs. Pre-taught interface — zero tutorial cost. Boxes live in Codex/toasts; prose stays prose (no blue-box spam in narration). System speaks terse machine-English; no JP honorifics anywhere — register carried by diegetic titles.
- **Play**: prose stream + composer + **scene tableau** (sprites positioned over background, rendered from the *perceived* scene manifest — fog-of-warred subset of true scene state; every tappable is guaranteed real). Tap entity → known-sheet card + thin verb list (Look/Approach/Speak) that pre-seeds the composer. Verbs cover trivial tier ONLY — anything with stakes routes through the composer or it becomes a menu CRPG.
- **Character**: stats, skills, scars, reputation. Glance screen.
- **Pack**: inventory (state entities, nearly free).
- **Codex**: the deep one. Fact cards (claim/source/location/confidence), filters, contradiction badges (bookkeeping yes, suggestions NEVER — correlation is the player's joy). Hypotheses = snap cards together + optional typed note → research target. Map lives here (known-sheet of geography, blank past the ridge).

**Voice**: "speak to the world" — on-device STT → transcript lands in composer, editable, then sends. Parser splits declared actions from in-character dialogue. Narrator TTS = post-MVP audio mode.

### 3.9 Sprite pipeline (flat 2D)
- **Style bible first**: palette, proportions, outline rules, one prompt template. Everything gen'd through it.
- **Backgrounds**: authored finite set per location *type* (tavern, library, road, shrine…). Pre-gen batch.
- **Entities**: sprite/portrait generated **once at entity commit time** (gpt-image-1, transparent PNG), stored as a field on the entity's canonical record, reused forever. Heir recognizes the betrayer's face before the prose says a word.
- **On-the-fly**: furniture entities get a category silhouette placeholder instantly; async gen swaps in the real sprite and commits it to the entity/location/item for all future encounters.
- **Cost control**: cache by entity ID, batch pre-gen common categories, sub-$5 batch discipline (proven pipeline: curl gpt-image-1 directly).

### 3.10 Pacing & cost economy (world-time gating)
The world runs on a clock, and expensive things take in-world time mapped to real time. This is the cost ceiling AND the monetization surface, and it's fully diegetic — no visible message limits, ever.

- **Gate the slow-in-fiction, not the loop.** Conversation and quick actions stay instant (the core loop must feel snappy). Timed: research, travel, crafting, healing/recovery, structural worldgen, rumor spread (already time-based by design). Research at the archive takes hours-to-days of real time depending on depth.
- **Timers = predictable $/DAU.** Instant-turn cadence plus timer caps put a hard ceiling on LLM spend per free player per day. Price time skips above the marginal LLM cost they trigger — skips literally fund the compute they consume.
- **Batch-generate behind timers.** Anything the player is waiting on has no latency pressure → generate results via the Anthropic Batch API (50% discount) during the wait. The gated content is also the cheapest content.
- **Timer UX rules (evidence-backed, see playbook §7):** timers land AFTER a payoff, never before one (no come-back-tomorrow ransom); duration previewed before committing ("a cursory search tonight; a full concordance takes eight hours"); bands ~2h/8h/20–24h/48–72h designed for ONE daily visit — nothing decays, expires, or needs a claim tap; completion automatic + offline + one optional push; a long project never freezes the fantasy (other scenes/Codex work always available); show fictional progress ("cataloguing → cross-referencing"), not just digits. First session generous, world-time introduced via an optional rewarding project before it ever blocks anything.
- **Skips accelerate the WORKER, never the world (v2 — George, 2026-07-13, multiplayer-safe).** The world clock is a property of the world, never manipulable per player (future shared worlds: multiple PCs in one world must stay in sync; the per-character event-stream architecture already supports this). A skip compresses the task's remaining duration — "you work through the night" — it does not move any world clock. Compounding guard (the researched pay-to-win backfire): **permanent-progression accrual is budgeted per world-day** wherever gains accrue (training teaches at most what a world-day can teach, paid or not) — skips buy the character back sooner (convenience, scheduling), never a higher ceiling than the patient player reaches. Never improves odds; same route, loot, prose depth. Audit every skip for second-order compounding. Mastered routes decay into cheap/free sweeps (a road you've survived becomes skippable).
- **Pricing:** one transparent conversion shown at purchase ("removes 8h — $X"); no currency-within-currency; provisional bands ≤2h $0.49–0.69 · ≤8h $1.29–1.79 · ≤24h $2.49–3.49 · ≤72h $4.99–5.99, declining per-hour on remaining time, last 10–15 min free; packs $1.99/$4.99/$9.99, no whale packs at launch; never show a discount while blocked. **Compute floor: list price ≥3.57× the p95 LLM cost the skip triggers** (30% store fee, 60% margin) — if the floor beats the band, don't sell that skip. Charge only on durable successful delivery; auto-recredit failed generations. First skip free at introduction + modest earnable supply.

### 3.10b Narration voice & anti-AI-tell pipeline (George, 2026-07-13)
Two tracks, one register. **Authored prose** (lore bible content, scene seeds, marketing): run the humanizer pass THEN george-voice (standing house rule), with fantasy theming tweaks on the voice layer — base register stays direct, concrete, no-bullshit; the theming dials formality up slightly, never into high-fantasy purple. **Runtime narration** (can't run skills per turn): both are distilled into the narrator prompt as hard constraints + enforced by eval-harness lints. Serial generation is our real exposure — we're naturally immune to whole-piece tells (tidy arcs, moral closure) but MORE exposed to serial tells: phrase/metaphor tics recurring across turns, hook-ending addiction, escalating melodrama, scene-structure templating. Team C's eval harness therefore lints across a CORPUS of generated narrations (n-gram tic frequency, hook-ending ratio, adjective density, structure variety), not single outputs. Research doc: docs/research/ai-tells-fiction.md (feeds the narrator constraint block + lint spec). Joins the no-unearned-awe rule as standing narrator prompt QA.

### 3.10c The world only answers as the world: deflection & synthesis (George, 2026-07-13)
Two sides of one rule governing player real-world knowledge.
**Deflection:** the narrator is never a chatbot. Off-domain/meta queries (parser already classifies these — `action_type: meta`) get zero out-of-fiction answers; the fiction reacts to the *behavior*: babble about otherworld cooking at the bar and the bartender cuts you off for being drunk; do it publicly and the deed log writes "raves about otherworld notions" (rumor fuel; the Blotted take an interest). Abuse becomes content, not a jailbreak surface. Genuine meta commands (settings, help) answer in System chrome, never through NPCs.
**Synthesis:** real-world knowledge is usable ONLY by enacting it through in-world materials and procedures. Inventions unknown to this world (the canonical example: gunpowder) are achievable — components exist under in-world names (nitre crusts, charcoal, brimstone), and the engine validates attempts against hidden dependency graphs (the binding Bookworm supply-chain model: concept → tested procedure → specialist → tooling → inputs → facility → legality → time). Knowledge gives direction, never omnipotence: knowing the recipe ≠ typing it into existence; wrong proportions fail reproducibly (and dangerously). Novel inventions route through the adjudicator + precedent ledger like sealed feats; on success **the invention exists in canon permanently** — massive-notoriety deed, faction reactions, forbidden-knowledge exposure, economy shifts. World-changing tech carries resurrection-tier costs and attention by design. This is "intel is the cheat skill" at maximum expression.

### 3.11 Guilds, professions & ranks
Multiple profession guilds (adventurer, merchant, smith, healer, scribe — each a regulator per the Bookworm model), ranks **F → SSS**. Rules: rank is institutional KNOWN certification, never TRUE power (rank-mismatch disaster stays canon drama); **rank-up tests are scheduled world-clock events** (quarterly trials — deadlines for training blocks, failed exams are witnessed deeds that rumor-spread); rank gates legal permissions (postings, trade rights, prices), not capability; two parallel recognition systems by design — System titles minted metaphysically from deeds vs guild ranks certified institutionally from tests, and they can disagree (the System knows you're Wyvern-Slayer; the guild has you at D because you never sat the exam); **rank dies with the character** — the heir starts at F under a famous surname.

### 3.12 The Quill cosmology (George, 2026-07-13)
The Quill is the world's believed god, and the game's real metaphysics ARE the theological dispute. **Pro-Quill faith** (working name: the Open Page — orthodoxy, runs the Skill Church): the Page is open, you hold the pen; `<<Proceed?>>` is the Quill asking consent — their proof of free will. **Anti-Quill faith** (working name: the Blotted): the Author writes us into corners and calls it a story; they seek to live *unwritten* — refusing ceremonies, distrusting records, dwelling in the margins (and their undocumented knowledge dies with them every generation). Both read the same true evidence; both are half right (honest dice = no story is pre-written; but the world WAS authored). Rules: the game NEVER confirms the answer; "what is the Quill?" is the deepest forbidden-knowledge domain (exposure track, never fully closed by the precedent ledger); the player's Quill-touched sight is religiously charged — prophet's mark to one church, the Author's finger to the other (NPC reactions rumor-driven); death rites split by denomination ("he wrote his last line himself" vs "the Quill wrote him into a corner"); System chrome doubles as scripture (impossible-tier mockery = the Author's marginalia). **DECIDED (George, 2026-07-13): the Quill mystery is BOTTOMLESS.** No end state, ever — no "world at peace and you are god." Like the source genre and the real world: defeat the biggest threat and the victory itself uncovers the next development with new issues and struggles. Design consequences: the forbidden-knowledge exposure track on the Quill never terminates (every revelation is real but opens a deeper question); endgame content model = escalation without ceiling, matching uncapped progression (there is always a bigger band, always a new pressure front); the adjudicator treats "prove what the Quill is" as permanently unsatisfiable — component laws can gate revelations, never the final answer.

---

## 4. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Engine | Pure Python 3.12 package (`everquill_engine`) | Zero LLM/network imports. Seeded RNG. CLI-playable. Property-tested. |
| API | FastAPI + uvicorn | Proven house stack. |
| DB | Railway-managed Postgres (volume-backed plugin) | NEVER a bare container (Invoice Helper lesson). psycopg3. |
| LLM — parser | `claude-haiku-4-5` | Structured output, ~cheap per turn. Aliases only, never dated snapshots. |
| LLM — narrator | `claude-sonnet-5` | Quality where it counts. |
| LLM — adjudicator | `claude-sonnet-5` (high effort), escalation-only | Rare calls, rulings cached forever in precedent ledger. |
| Sprites | gpt-image-1 (direct curl) | Transparent PNGs, style-bible prompt template. |
| Media storage | Cloudflare R2 bucket (`everquill-media`) | Object storage for generated art and backups. |
| Client | Vite + React + TS, mobile-first PWA | Agent-friendliest frontend stack; no store friction at alpha; wrap later (Capacitor) if wanted. |
| STT | Web Speech API first; Whisper API fallback | On-device = free + instant. |
| Deploy — client | Cloudflare Pages, its own project and subdomain | Its own Pages project, because the PWA needs its own service-worker scope and manifest. |
| Deploy — backend | Railway: FastAPI API + volume-backed Postgres + gen/timer worker | Registry-first auth, project token, `railway up --service`. Backend CANNOT go static-Cloudflare like Star Math/Saltmarch: true sheets must never reach the client, dice/timers/batch-gen are server-authoritative, keys live behind the API. All-CF (Workers+D1) rejected — would force a TS engine rewrite and drop Postgres for ~$10–20/mo savings. `/clips`-style Worker proxy on the zone stays an option later. |

### State architecture v2 (Teams A + F — BINDING; full decision doc: docs/research/data-layer/claude-synthesis.md, implement from its §2)

Research-validated 2026-07-13 (6-lens Claude workflow + 4 Codex deep-dives, all in docs/research/data-layer/). All six original decisions survived; the refinements below are part of the contract.

- **EVENT sourcing, never COMMAND sourcing (the hard invariant).** Events record resolved outcomes and applied deltas — roll values, modifiers, tier, state changes. Replay is a pure fold over stored deltas; it NEVER re-executes engine logic (this is what killed Factorio/SC2/StS replays). `engine_version` is forensic metadata, not a replay input — so the engine may change daily without touching canon. Append-only enforced at DB-privilege level (REVOKE UPDATE/DELETE); corrections are compensating events (`CanonErratum`), never log edits — including during alpha (wipe worlds instead). Schema evolution: additive weak schema; `type_version` + pure upcasters for structural breaks; a NEW event type for meaning changes; golden-corpus replay in CI.
- **Claims: five lifecycle states, strength not confidence.** asserted / corroborated / **contested** (both live, surfaced as "I've heard two versions" — narrator gold) / superseded (never deleted) / retracted. Transitions are events; the claim table is a rebuildable projection. `strength` = decayed sum of per-method evidence weights (observed > told > rumor > inherited journal > overheard); confidence is display-only. **Corroboration requires ≥2 evidence links with distinct `provenance_root_event_id`s** — the echo-chamber rule (one lie via three neighbors must never self-upgrade). Closed predicate vocabulary enforced at the parser boundary (contradiction stays a SQL problem, never LLM judgment). Bitemporal-lite: `world_time_acquired` + nullable `world_valid` only.
- **Assembler: deterministic to the byte.** Integer basis-point scoring (structural relevance, write-time notoriety, recency half-lives, clock coupling, thread stickiness, redundancy penalty), full tiebreak chain down to claim ULID — same log prefix ⇒ byte-identical prompt, tested cross-platform. Reserved token floors + caps per section (budget table in the decision doc; ~2,800 target). **Constraint-class claims (oaths, prohibitions, promises, active consequences) are PINNED by type, never salience-ranked** — shipped products evict them first and that's exactly backwards for a referee. The last action's machine-readable engine resolution is always included (anti re-narration drift). Claims/canon render via fixed templates — never LLM-summarized in the turn path; chronicle summaries are offline Batch work, entailment-gated, regenerated only from source events. Every assembled context logs `assembler_version` + content hash as an event.
- **Rumor epochs: keyed on per-region event.id high-water marks** (xid8-safe read predicate — wall-clock keys permanently skip late-committing deeds), with corruption rolls seeded from `(provenance_root_event_id, hop_count, epoch)` so recomputation is bit-identical. Canon-sealing sweep flips claims only for characters who LEARN of it via propagation — never omnisciently.
- **World clock: canon never waits for the LLM.** Engine resolves timer outcomes deterministically AT FIRE TIME (seed = hash(timer_id, created_event_id)), stamped at `world_due`; the Batch API is the ambient narration lane only (24h expiry means batch can decorate truth, never delay it). Timer table + FOR UPDATE SKIP LOCKED sweeper (procrastinate); timer table doubles as transactional outbox for pushes/batch. Downtime policy: fire ALL overdue domain timers in order, no grace cutoff ever; pressure fronts are lazy last-evaluated processes; pushes coalesce to one digest.
- **Inheritance mechanics:** journaling = an event snapshotting claim IDs at that log position; heirs mint NEW asserted-state claims resolved as of the journal position (`inherited_journal` method, hop+1) — lifecycle never inherits. **Journal text is untrusted data** — rendered quoted/delimited in prompts, never as instructions (persistence-injection is a demonstrated attack).
- **Explicit non-goals until tripwires** (>500k events/day, table >50GB, VACUUM >30min): no partitioning, no broker, no ES framework, no snapshots. Projections synchronous same-transaction (player-visible) except rumor epochs/analytics (checkpointed async, shadow-table rebuilds). Stack pin: psycopg3 + hand-rolled store + procrastinate. GDPR: player free-text encrypted per-player (crypto-shredding).
- **The 10-test suite (decision doc §5) is the data layer's DoD:** golden-corpus replay, byte-identical assembly, rebuild equivalence, true-sheet leak audit, irrelevance injection, constraint-flood invariant, journal-injection red-team, late-fire determinism, epoch coherence, 100-turn drift canary. Tests 1–3 green ⇒ sealed deaths, reproducible wrong intel, and auditable dice are enforced by construction.
- **Durability:** volume-backed Railway Postgres + daily dumps shipped to R2. Restore drill is a Sprint 1 F-team ticket, not a someday.

**Per-turn cost budget (target):** parser ≤1k tokens haiku + narrator ≤3k tokens sonnet ≈ well under $0.02/turn. Trivial-tier actions skip the narrator (template or haiku-narrated). Timed-action results go through the Batch API at 50% off. Instrument from Sprint 2; alpha gate at Sprint 6 requires measured cost per player-hour, with the world-clock timer caps (3.10) as the hard $/DAU ceiling.

---

## 5. The Six Agent Teams

| Team | Name | Owns | Primary deps |
|---|---|---|---|
| **A** | Engine & Rules | State schema, resolver, tiers, dice, chargen, deed log, precedent-ledger storage, save/load, engine CLI | B (content schemas) |
| **B** | World & Canon | Lore bible, laws/cost models, seed region content, entity templates, threat bands, library scopes, rumor params | — (content authority; George-heavy) |
| **C** | LLM Layer | Parser, narrator, adjudicator, prompt templates, structured-output contracts, **eval harness** (golden transcript suite), cost guards | A (intent/outcome schemas) |
| **D** | Client | 4 screens, composer, tableau, Codex pinboard, voice input, PWA shell | A+F (real API — never mock data) |
| **E** | Art & Sprites | Style bible, background sets, gen-at-commit worker, placeholder silhouettes, R2 storage, cache | B (entity categories) |
| **F** | Platform & Infra | Repo, CI, migrations, Railway/Pages deploys, R2 bucket, accounts, telemetry, cost dashboards, QA harness | — |

Ticket discipline (house rules): bounded tickets, read before changing, summarize plan first, no scope creep. Claude tests blind, Codex gets bounded tickets, George judges.

---

## 6. Sprint Plan

Sprints are scope-gated, not calendar-gated (nominally ~1 week of agent-team throughput each). **Build order is law: config → data → core → interface → integration. No UI against mock data, ever. Each sprint ends with a runnable, verified slice.**

### Sprint 0 — Foundations & Decisions
- **All/F**: repo scaffold at canonical path, CI, `make dev`, Railway project + volume-backed Postgres, hello-world API live, Pages project, R2 bucket.
- **A**: engine package skeleton, dice + tier enums, first property tests.
- **B**: lore bible v0 skeleton (universe laws doc structure, magic cost-ledger format, common-sense category table).
- **C**: intent/outcome JSON contracts drafted with A; eval-set format defined.
- **D**: PWA shell boots, calls hello API.
- **E**: style bible v0 — palette/proportions/prompt template + 10 style-test sprites for George sign-off.
- **George**: name sign-off, registry entry, media/client stack confirmations.
- **DoD**: fresh clone → `make dev` → playable nothing, but every pipe is real. Registry entry merged.

### Sprint 1 — The Referee (no LLM anywhere)
- **A**: full resolver (trivial→impossible), chargen rolls, deed log, **world clock** (in-world time advancing per action — rumor/timer substrate), state persistence to Postgres; **tavern scene playable via CLI with canned intents**.
- **B**: seed region v1 — one town, one tavern, 6 NPCs with true sheets, threat bands, starter laws (1 sealed feat: resurrection). Author against the playbook's furniture checklist: guild hall anatomy + F–SSS plates and exam schedules, Skill Church (as pro-Quill orthodoxy), **Quill cosmology dossier** (both churches' doctrine + the sealed truth-or-bottomless decision, §3.12), summoning history, Demon Lord dossier (church answer + truth, separately), bestiary ladder, coin price anchors, travel network in carriage-days, System diction sheet, explicit-absences list (no slavery content, no harems, no VRMMO logic, no Earth-food).
- **C**: parser prototyped OFFLINE against eval set (50 golden utterances → intents), zero production wiring.
- **D**: Play screen renders real engine transcript + composer posts canned intents through the real API.
- **E**: tavern background + 6 NPC portraits through the style pipeline; placeholder silhouette set.
- **F**: migrations, scene-manifest endpoint, telemetry skeleton.
- **DoD**: a human plays the tavern via CLI *and* via the barebones Play screen; dice honest, state survives restart. **The game is provably fun with placeholder prose or it isn't fun.**

### Sprint 2 — The Mouth and Ears (LLM wired)
- **C**: parser + narrator in the live loop; narrator fed known-sheets/scene manifest only; furniture-commit validation path.
- **A**: commit beat on hopeless/lethal; furniture entity commits.
- **D**: tableau v1 — positioned sprites from perceived manifest, tap → known-sheet card + thin verbs pre-seeding composer.
- **E**: portrait gen-at-commit worker live (async placeholder→swap).
- **B**: prompt-facing canon excerpt format; narrator style guide.
- **F**: per-turn token/cost instrumentation.
- **DoD**: tavern slice playable in PWA with free text + taps; every tappable real; sprites persistent; cost per turn measured.

### Sprint 3 — Knowledge (the Codex earns its screen)
- **A**: known/true sheet split enforced across resolver + API (server never leaks true sheets).
- **B**: library scope tables, lead graphs, wrong-intel ballad content.
- **C**: research-action resolution prompts; wrong-intel-on-failure writes.
- **A+F**: first **timed actions** — research runs on the world clock in real time, completes offline, results land on return (timer infra + notify hook).
- **D**: Codex v1 — fact cards, filters, contradiction badges, hypothesis snapping (+optional typed note), map-in-Codex v0; timed-research "findings await" re-entry flow.
- **E**: item/prop sprite categories.
- **F**: intel/fact schema migrations.
- **DoD**: the canonical flow works end-to-end: *know lizards have weak tummies → hypothesize dragons do → search THIS library → confirmed/denied/false-confirm/lead*. Locality provably limits what each library returns.

### Sprint 4 — Danger & Consequence
- **A**: hopeless failure-flavor bands; sealed component checks; deed log → rumor propagation v1 (distance/time/notoriety).
- **B**: sealed-feat law hardening; rumor distortion tables.
- **C**: adjudicator + precedent ledger (rulings committed as canon); god-mode/impossible-tier reactions.
- **D**: voice input (STT → editable transcript → send); dialogue-vs-action affordances.
- **E**: creature-scale sprites (the dragon).
- **F**: precedent/rumor migrations; load tests.
- **DoD**: "I punch the dragon to death" produces the commit beat, then a signature death; a component-incomplete resurrection fails forward and something noticed; a novel sealed-route attempt gets adjudicated and the ruling persists.

### Sprint 5 — Death & Legacy
- **A**: PC death → entity persistence; heir chargen into same world; journals as intel-carrying items; thin inheritance rules.
- **B**: relationship-choice hooks (kin/apprentice/stranger); epitaph/deed content for dead PCs.
- **C**: two-speed worldgen — structural generation (city/major NPC) consuming deed log.
- **D**: death/heir flow UX; graveyard in Codex.
- **E**: on-the-fly sprite gen fully wired for structural worldgen output.
- **F**: multi-character account model.
- **DoD**: die stupidly, roll an heir, walk into the bar, hear the tale of the idiot who punched Vermithrax, find the journal, learn the blind side. World demonstrably remembers.

### Sprint 6 — Harden & Closed Alpha
- **All**: balance pass (B leads), prompt/eval hardening to green (C), cost tuning to budget (C+F), onboarding ramp polish — first 10 minutes tap-only viable AND timer-free (D), art coverage pass (E), telemetry + crash/cost dashboards (F).
- **C+F**: timed-action results routed through the Batch API (50% off); time-skip **stub** (grant/consume an hourglass item — no payment rail yet, just proves the accelerate path).
- **DoD**: live URL, ~5 alpha testers playing on phones, measured cost per player-hour vs the timer-capped $/DAU ceiling, zero true-sheet leaks in audit, closeout-clean repo. **Death-system gates:** ≥90% of testers can explain the mechanical cause of their death; median death→first-heir-decision <90s; heirs described as different people, not "the same build again."

### Dependency spine
A→C (schemas before prompts) · A/F→D (real API before UI) · B→A (content before resolver tuning) · E style-lock → all gen. Teams B, E, F have long independent runways — they never block on the spine.

---

## 7. Risks & Kill-Criteria

| Risk | Mitigation |
|---|---|
| Parser quality (the real boss fight) | Eval harness from Sprint 1, golden-set gating every prompt change; tap verbs shrink the parse surface; commit beat backstops lethal misparses. |
| LLM canon drift | Narrator is stateless-by-design: fed state snapshots, never chat-history-as-memory. |
| Narrator flattery (Realist Hero failure) | Standing prompt-QA rule: no NPC awe, deference, or heroic framing the deed log didn't earn; no invented sacrifices, witnesses, or final words at death — narration binds to the sealed death record. |
| True-sheet leaks | Server-side enforcement (API never serializes true sheets to client or narrator context); automated leak audit in CI. |
| Per-turn cost creep | Instrumented from Sprint 2; haiku parser; alpha gate on measured $/player-hour. |
| Art inconsistency | Style bible + gen-once-at-commit; no regen of committed sprites. |
| Scope drift | This doc's North Star section is the referee; north-star check in every ticket template (streamer-pipeline discipline). |
| Sprint 1 fails the fun test | Cheapest possible kill point — canned-intent CLI proves/disproves the loop before any LLM or client spend. |

---

## 8. Open Decisions (George, Sprint 0)

1. **Name** — Everquill stands unless vetoed.
2. **Client stack confirm** — Vite+React+TS PWA (recommended) vs other.
3. **Media storage confirm** — new personal R2 bucket (recommended).
4. **Sprint cadence** — scope-gated (recommended) vs calendar.
5. **Alpha auth** — device-local + invite code (recommended) vs accounts-first.
6. **Monetization posture** — direction locked: world-time gating + paid time skips (3.10). Timer infra ships Sprint 3, skip stub Sprint 6; the actual payment rail is post-alpha. Likely MoR (Lemon Squeezy) given no UK establishment — decide at alpha exit.
7. **Free-player pacing dials** — instant turns per day before soft-slow, base timer durations (research hours, travel). Set provisional values in Sprint 3, tune with alpha telemetry.
