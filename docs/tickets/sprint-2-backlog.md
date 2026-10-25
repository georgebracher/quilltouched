# Sprint 2 backlog

## Brand rename follow-through (Quilltouched, locked 2026-07-13)
Brand pass DONE at S1 close: client title/header/manifest, quilltouched.gitm.gg live + CORS, roadmap header. REMAINING (bounded ticket, decide keep-vs-rename per surface): retire everquill.gitm.gg (redirect first); Pages project + Railway project display names (cosmetic, dashboard); repo rename everquill → quilltouched (optional — internal slug may stay per house precedent, registry key stays `everquill` either way with alias); `everquill_engine` package (recommend KEEP — pure internal); grep remaining player-visible "Everquill" strings in lore/docs prose (research/history files stay untouched).

# Play screen layout v2 (George's mock, 2026-07-13 — roadmap §3.8)
Five zones: status strip (date/coin/timer) · scene canvas (background + slot-positioned sprites, items appear in-scene, tap-to-card) · right-edge nav rail · compact transcript (System lines legible; full Chronicle a tap away) · typed composer. NEW data need: authored anchor slots per location type + deterministic slot assignment in the scene manifest (A/B). S1 playtest lessons: lead suggested actions with dice-rolling ones; dead entities need a dispatched state in the manifest; already-dead targets render "[Already dispatched]".

# Deferred findings from the S1 Codex review

Source: `docs/research/reviews/codex-review-resolver-s1.md` (baseline 03ba16a). The CRITICAL/transactional cluster is being fixed in Sprint 1; these are consciously deferred with owners.

| Finding | What | Owner / when |
|---|---|---|
| HIGH-3 | Upcaster registry (`(event_type, payload_version)` chains), persisted projector versions, fixture coverage per version pair, shadow-table rebuild + diff + swap | A, Sprint 2 (before any payload shape changes ship) |
| HIGH-5 | Full claim schema per synthesis §2.3 (typed predicate vocabulary, strength, evidence links, lineage, world_valid + indexes) | A+F, Sprint 2/3 — BLOCKS claim-producing gameplay (research actions in the LLM loop) |
| HIGH-7 | CI ephemeral Postgres service; fail if any DB-marked test skips | F, Sprint 2 |
| HIGH-8 | Crypto-shredding for player-authored text (per-player envelope keys) — synthesis says day-one; consciously deferred while alpha worlds are wipeable; MUST land before real players | F, Sprint 2/3, hard gate before alpha |
| MEDIUM-1 | Explicit RefereeState/KnownState repository split; API/narrator can only import KnownState; denylist payload tests | A+C, Sprint 2 (assembler work) |
| MEDIUM-4 | Roll-site registry (semantic stream per site) + DB uniqueness on (rng.stream, rng.index) | A, Sprint 2 |
| MEDIUM-5 | Closed typed intent model generated from schema; consume/reject duration_hint deterministically | A+C, Sprint 2 (parser wiring) |
| MEDIUM-6 | event_ulid + stream_type columns + projection_checkpoint DDL | A, Sprint 2 (before rumor workers) |
| LOW-1 | Integer-only folded numeric domains in schemas/loader | C, Sprint 2 |
