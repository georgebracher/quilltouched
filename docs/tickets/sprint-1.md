# Sprint 1 — The Referee (no LLM in the play loop)

Rules: bounded tickets, read before changing, summarize plan first, no scope creep. Build order is law. The data-layer decision doc (`docs/research/data-layer/claude-synthesis.md` §2) is BINDING for anything touching events, claims, projections, or timers.

**Sprint DoD:** a human plays the tavern scene end-to-end via CLI with canned intents; dice honest; every event append-only in Postgres; state survives restart; determinism proven by test (same seed + same intent script → identical event log).

## Interface decisions (locked here so parallel teams conform — do not renegotiate)

1. **Aptitude vocabulary LOCKED:** `might, finesse, wits, will, presence, lore`. Team A publishes `docs/engine/stats.md`; Team C's `stat_hint` enum and Team B's true sheets use exactly these.
2. **intent schema v1.1:** add `rest` to `action_type` (C owns the schema edit + a golden case). Compound actions stay single-intent + `compound_action` flag in Sprint 1.
3. **World-content format** (A owns the loader + validation; B authors to it): YAML files under `content/world/*.yaml`:
   ```yaml
   locations:
     - id: loc.<region>.<slug>       # e.g. loc.duskwell.tavern
       name: ...
       type: tavern|guild_hall|church|road|square|shop
       region: <region>
       connections: [{to: <loc id>, carriage_days: N}]
   entities:
     - id: npc.<region>.<slug>       # npc.|creature.|item.|prop.
       name: ...
       kind: npc|creature|item|prop
       location: <loc id>
       true_sheet:
         aptitudes: {might: N, finesse: N, wits: N, will: N, presence: N, lore: N}
         threat_band: N              # int, feeds band_for_gap
         tags: [..]
       common_knowledge: [category-level facts everyone knows]
       portrait: <assets path or null>
   prices: {inn_night_copper: N, ...}
   rumor_seeds: [{deed: ..., notoriety: N}]
   ```
4. **Dev database:** `DATABASE_URL` in the repo-root `.env` (gitignored; points at the project's Railway Postgres, currently empty). DB-integration tests skip cleanly when `DATABASE_URL` is unset so CI stays green.
5. **Wave order:** A+B+C+E parallel now → F (API: scene-manifest + canned-action endpoints, DATABASE_URL wiring, deploy, restore drill) after A lands → D (Play screen + composer against F's real API) after F lands.

## Team A — Engine: the Referee (the sprint's spine)
Lane: `everquill_engine/**`, `tests/**`, `docs/engine/**`, `migrations/**`, `content/world/dev-fixture.yaml`, pyproject.
- Event store per synthesis §2.1: single event table (envelope columns + jsonb payload, `UNIQUE(stream_id, version)`, `command_id` UNIQUE, xid8 column, `REVOKE UPDATE, DELETE` in migration), plain-SQL migrations + tiny runner (psycopg3, no framework — stack pin).
- Tier-1 synchronous projections (same transaction): character sheet, known-sheet/claims (v1: claims written by observation/research deltas), scene manifest. Rebuild-equivalence: truncate projections → replay → identical.
- Chargen: aptitude rolls via named dice streams → character entity + events. No class picker (aptitudes + origin only).
- Resolver: canned intent (conforming to `docs/contracts/intent.schema.json`) + state → tier (band_for_gap + authored sealed/impossible overrides) → risk label → roll → outcome per `outcome.schema.json` → typed deltas → events. HOPELESS = failure-flavor only. Every miss deposits at least one delta (intel/scar/journal-line hook).
- World clock v1: `world_time` ticks advance per action; timer table per synthesis §2.5; sweeper = manual CLI command (`clock advance`), no daemon yet.
- World loader for the format above + a minimal `content/world/dev-fixture.yaml` (tavern + 3 NPCs, clearly marked DEV FIXTURE — B's real region replaces it at integration).
- CLI: `python -m everquill_engine.cli` plays the tavern with canned intents; prints Chronicle-style output (rolls shown post-resolution).
- Tests: determinism (same seed + script → byte-identical event log), rebuild equivalence, idempotent command_id, band monotonicity intact, golden-corpus fixture v1 (freeze sample events for every event type shipped).
- Defer: crypto-shredding, async projections, batch integration, heir flow.

## Team B — Seed region v1: Duskwell (or better name, your call)
Lane: `docs/lore/**`, `content/world/<region>.yaml`.
- One town + tavern + 6 NPCs with full true sheets (locked aptitudes, threat bands), guild hall + Skill Church presence, 4–6 regional creatures spanning the monster ladder, price anchors, travel connections (carriage-days), rumor seeds.
- Fill lore stubs to v1 depth: 02 universe laws (core physics + what magic costs), 04 guilds (hall anatomy, F–SSS, exam cadence), 05 Skill Church (pro-Quill orthodoxy), 09 bestiary (regional entries), 10 economy, 11 travel network.
- Register: direct, concrete, no purple prose — follow the constraint block in `docs/research/ai-tells-fiction.md`. (Final humanizer + george-voice editorial pass happens outside this ticket.)
- Resurrection law already exists in `docs/lore/laws-format.md` — instantiate its components as world facts (where IS a thin place? does anyone hold a soul anchor?).

## Team C — Parser prototype, OFFLINE only
Lane: `docs/contracts/**`, `evals/**`, `llm/**` (new).
- Schema v1.1: add `rest` action_type; expand goldens 20 → 50 (cover rest, more dialogue splits, more research/train/travel variety, adversarial phrasings, 5+ trivial everyday).
- Parser: claude-haiku-4-5, structured output (tool schema = intent.schema.json), prompt in `llm/prompts/parser.md`, runner `llm/parser_eval.py` (Anthropic API key from env `ANTHROPIC_API_KEY` or `~/.claude/keys.local.md`; never print it).
- Iterate prompt until ≥90% field-level accuracy on the 50 goldens; report the confusion cases. Budget: haiku, trivial cost. ZERO production wiring.

## Team E — Art batch 2
Lane: `docs/art/**`, `assets/**`.
- Apply the documented humanoid framing fix (fill 80%→70% + explicit head/feet margin) to `prompt-template.md` (bump template version); regenerate the 4 NPC portraits.
- New asset class: scene backgrounds — add spec to style bible (flat-color LN interior, no characters, sprite-safe floor band, landscape 1536×1024); generate the tavern interior.
- Placeholder silhouette set (npc/creature/item, neutral gray, on-palette) for async-gen placeholders.
- Contact sheet v2 for George's sign-off (this batch = the G0.1 decision packet). Budget cap $5, same regen discipline.

## Team F — after A lands (do not start before)
Lane: `api/**`, `Makefile`, `.github/**`, `docs/ops/**`, `migrations/` (apply only).
- Wire `DATABASE_URL` on the Railway app service (reference `${{Postgres.DATABASE_URL}}`); run migrations against dev DB; restore drill (dump → R2 → restore to scratch schema, documented + scripted).
- API v1: `GET /api/scene` (perceived scene manifest), `POST /api/action` (canned intent JSON → resolver → outcome), both backed by the real engine. No parser — canned intents only.
- Telemetry skeleton (per-turn event counts, timings). Redeploy; verify live.

## Team D — after F lands (do not start before)
Lane: `client/**`.
- Play screen v1: prose-transcript stream (Chronicle-style output), composer that posts canned intents (dropdown of the golden intents for now — typed input arrives with the parser in Sprint 2), tableau strip from `GET /api/scene` (silhouettes fine until E's sprites wire in).
- Against the REAL API only (local `make dev` or the Railway URL). No mock data.

## George
- **G1.1** Sprite/style sign-off moved here: judge batch 2 (fixed humanoids + tavern background).
- **G1.2** Region name veto (B proposes).
