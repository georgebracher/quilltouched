# Sprint 2 — The Mouth and Ears (Quilltouched becomes the game)

Rules unchanged: bounded tickets, read before changing, summarize plan first, no scope creep. Binding contracts: `docs/research/data-layer/claude-synthesis.md` §2, roadmap State Architecture v2 + §3.8 layout v2, `docs/research/ai-tells-fiction.md` (narrator constraint block + lints).

**Sprint DoD:** a player with their OWN account and world types a free-text action on their phone at quilltouched.gitm.gg; the parser reads it (temp 0, strict tool); Dire-and-up intents get the `<<Proceed?>>` beat; the engine resolves with honest dice; the narrator returns prose BOUND to the committed outcome (anti-tell constraints enforced); the scene canvas shows slot-positioned sprites over the location background. Per-turn cost telemetry live.

**George decisions applied this sprint (locked 2026-07-13):** template v1.2 framing prefix · keeper/sister proportion re-rolls + traveler scar regen · alpha-clean standard · Harrowdown · Quarterday · 100 pennies/mark, 100 marks/sovereign · Dunmere canon · train trains will.

## Locked interface decisions
1. **Accounts v1 = per-account worlds.** Invite-code + device token (no passwords). Each account bootstraps its OWN Harrowdown instance (world_id = account-scoped). Shared-world multi-PC stays future work; the shared-PC embarrassment dies this sprint.
2. **Commit beat = two-phase resolution.** `POST /api/action` on Dire+/sealed/irreversible intents returns `{pending_confirmation, assessment}` WITHOUT resolving; `POST /api/action/confirm {command_id}` resolves. Trivial/Guarded/Perilous auto-commit (ghost-echo). Engine owns the tier→confirmation-required table.
3. **Narration is synchronous post-commit:** parse → (beat?) → resolve+commit → assemble context (deterministic, narration_context.schema) → narrator (claude-sonnet-5, ~2-3k in / ≤400 out) → prose returned with the outcome. Prose stored as a narration event bound to the outcome event id. Parser = claude-haiku-4-5, temperature 0, strict tool — both LOAD-BEARING, never change silently.
4. **Player text is untrusted data everywhere:** quoted/delimited in all prompts, never instructions. Red-team goldens required (injection utterances).
5. **Anchor slots:** location types carry authored slot maps (Team B authors; format: `slots: [{slot_id, x_pct, y_pct}]` per location type in a new `content/world/slots.yaml`); scene manifest assigns entity→slot deterministically (hash(entity_id) over free slots, stable per scene). Team A implements assignment; Team D renders.

## Wave 1 (parallel, now)

### Team A1 — engine service surface
Lane: `everquill_engine/**`, `tests/**`, `migrations/0006_*.sql`, `docs/engine/**`.
- Typed intent model generated/validated from intent.schema v1.1 at the resolver boundary (MEDIUM-5; consume duration_hint deterministically or reject).
- **KnownState/RefereeState repository split (MEDIUM-1):** narrator/API-facing query objects can only produce Chronicle facts + Inquiry claims + perceived manifest; static import-lint test that `api/` and `llm/` modules cannot import RefereeState.
- Scene manifest: slot assignment (interface decision 5), `dispatched` condition surfaced, dead entities marked; resolver: targeting a dispatched entity → trivial no-op with explicit `[Already dispatched]` summary + zero deltas.
- Roll-site registry (MEDIUM-4): semantic stream ids per roll site + uniqueness constraint on (rng.stream, rng.index).
- Two-phase commit beat (interface decision 2): assess-without-resolving path, pending-confirmation storage (timer-table style row, expires after 10 world-minutes of inaction), confirm path resolves under the original command_id.
- Suite green both modes; extend goldens for new event/payload shapes per replay rules.

### Team B — slots + content batch 2
Lane: `docs/lore/**`, `content/world/**` except dev-fixture.
- `content/world/slots.yaml`: slot maps for location types (tavern, guild_hall, church, square, shop, road) matching Team E's background compositions (tavern floor band first).
- Harrowdown consistency pass with locked decisions (Quarterday cadence, coin ratios, Dunmere references) — already mostly authored; verify + fix drift.
- Content for the narrator: per-location atmosphere notes (3-5 concrete sensory facts each, direct register per ai-tells constraint block) as a new `atmosphere:` field per location; per-NPC voice notes (1-2 lines: cadence, vocabulary, what they never say) in true_sheet.tags or a `voice:` field — agree shape with A1's loader (coordinate via the YAML format; A1 owns loader changes, propose the field shapes in your report if loader lacks them — do NOT edit the loader).
- Bestiary/lore: no expansion this sprint beyond fixing references.

### Team C — parser prod + narrator + assembler
Lane: `docs/contracts/**`, `evals/**`, `llm/**`.
- **Held-out eval set** (50 NEW goldens the prompt has never referenced; include 5 injection attempts — "ignore previous instructions", stat-revelation bait, system-prompt fishing) + report parser accuracy on held-out BEFORE any prompt tweaks; then iterate if needed (same conditions: haiku, temp 0, strict tool).
- **Context assembler v1** (`llm/assembler.py`): deterministic, per narration_context.schema — scene manifest + KnownState slices + last-resolution machine trace + active clocks + location atmosphere; integer scoring + ULID tiebreaks per State Architecture v2; token budget with section floors; logs assembler_version + content hash. Consumes ONLY Team A1's KnownState surface.
- **Narrator v1** (`llm/narrator.py` + `llm/prompts/narrator.md`): claude-sonnet-5, ≤400 output tokens, prose bound to the outcome contract (narration_constraints enforced in prompt: no_npc_awe_unearned, entity_facts_only, bind-to-dice — a miss narrated as a hit is a CRITICAL bug), anti-tell constraint block from docs/research/ai-tells-fiction.md verbatim, register: direct/concrete, tier-keyed (trivial turns are allowed to be quiet; impossible tier gets the System's dry irony).
- **Narration eval harness v1:** 20 fixture outcomes → narrate → lint (banned-phrase regex from the research doc, hook-ending detector, contradiction check vs outcome fields via simple assertions: tier word present, no invented entity names outside context). Batch/serial tic lint (n-gram repetition across the 20) — thresholds from the research doc.
- All offline modules with clean interfaces; Team F wires them into the API in wave 2.

### Team E — art batch 3 + portrait pipeline
Lane: `docs/art/**`, `assets/**`, `tools/spritegen/**` (new).
- Template v1.2: promote the front-loaded framing prefix (George-approved); regenerate keeper + sister (proportion re-rolls toward the 5-head band) and traveler (scar MUST render — signature-feature retry budget 3); alpha-clean applied as standard.
- Backgrounds: guild hall interior + Harrowdown street/square (slot-map coordination with Team B — backgrounds must leave the authored slot zones clear).
- **Portrait gen-at-commit pipeline v1** (`tools/spritegen/generate.py`): given an entity id + description from world YAML, produce a style-locked sprite (template v1.2), alpha-clean, save to `assets/sprites/<entity_id>.png` + manifest json. Run it for ALL current Harrowdown entities (≈15). Budget cap $10 this sprint (larger batch, George-approved decisions applied).
- Contact sheet v3 for the record (no sign-off gate unless something misses the checklist).

## Wave 2 (after A1 + C land) — Team F
Lane: `api/**`, `Makefile`, `.github/**`, `docs/ops/**`, `migrations/0007_accounts.sql`, root requirements.
- Accounts v1 (interface decision 1): invite codes (env-seeded list), device token issuance, account→world bootstrap, all endpoints account-scoped. Kill the shared PC.
- Wire parser + beat + narrator into `POST /api/action` per interface decision 3; ANTHROPIC_API_KEY on Railway (from the secret store — never printed); per-turn cost telemetry (input/output tokens, model, latency per stage) in the JSON lines + a daily rollup endpoint.
- CI: ephemeral Postgres service, all DB tests run, fail-on-skip for DB-marked tests (HIGH-7).
- Client prod config: VITE_API_BASE bare-origin documented in deploy docs; redeploy + live verify (typed action end-to-end on the live URL, paste evidence).

## Wave 3 (after F) — Team D + hardening
- **Team D** (lane `client/**`): layout v2 — scene canvas (backgrounds + slot-positioned sprites from the manifest, silhouette fallback), status strip (date/coin/timer), edge nav rail (Character/Pack stubs + Codex placeholder), compact transcript (System lines legible, full Chronicle expandable), typed composer (free text → parser; canned suggestions REMAIN as quick-picks, rolled-actions first per S1 lesson), `<<Proceed?>>` commit-beat dialog, narrator prose rendering, account onboarding (invite code entry).
- **Team A2** (after D starts, lane engine+migrations 0008+): claim schema v2 per synthesis §2.3 (HIGH-5), upcaster registry + projector versions + shadow rebuild (HIGH-3), event_ulid + stream_type + projection_checkpoint (MEDIUM-6), crypto-shredding for player text (HIGH-8 — hard gate before invite codes go beyond George).
- **Codex adversarial review round 2:** parser/narrator injection surface + KnownState leak audit + two-phase beat races. Fix crew on findings.

## George
- **G2.1** Play the typed loop when wave 3 lands (the real fun-or-kill).
- **G2.2** Invite-code list (who gets in besides you).
