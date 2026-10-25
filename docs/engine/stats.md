# Aptitudes, Rolls & Bands (A1 — Sprint 1)

Status: **published interface** (Sprint-1 ticket, interface decision #1).
Team C's `stat_hint` enum and Team B's true sheets must use exactly this
vocabulary. Code counterpart: `everquill_engine/chargen.py`,
`everquill_engine/resolver/` (package), `everquill_engine/clock.py`.

## Vocabulary (LOCKED)

Six aptitudes, in canonical order:

| Aptitude | Covers |
|---|---|
| `might` | force, endurance, raw body |
| `finesse` | precision, speed, hands |
| `wits` | perception, reading people/rooms, quick thinking |
| `will` | resolve, discipline, resistance |
| `presence` | charm, command, weight in a room |
| `lore` | learning, letters, what the world is |

Locked: names, spelling, order. New aptitudes are a contract change, not
a content change.

## Roll method

Chargen rolls **2d6 per aptitude** from the dedicated dice stream
`("chargen", character_id)` at indexes 0–5 in the order above
(`everquill_engine.dice.roll_2d6` — pure function of
`(world_seed, stream, index)`, so a character re-rolls identically from
the log, forever). No class picker: aptitudes + origin only.

Derived at chargen (stored in the `character_created` payload; folds
never recompute): `hp_max = 4 + might`, `hp = hp_max`, starting coin
30 copper (flat v1 — origin purses are Team B content later).

## Ranges

- Chargen range: **2–12**, mean 7. A commoner adult sits ~4–8; trained
  professionals 8–12.
- **Uncapped forever after** (roadmap §2): aptitudes are unbounded
  integers, grown through training blocks (world-clock timers, +1 per
  completed block in v1 — rising per-gain costs land with the
  progression ticket). The world never level-scales.
- NPC/creature `threat_band` (world content): same scale, unbounded.
  Regional authoring guide: town civilians 3–6, competent professionals
  6–10, veterans/elites 12–20, regional monsters per the bestiary
  ladder. `threat_band` is a **combat** number (see below).

## Band interaction

`gap = difficulty − acting aptitude`, then `band_for_gap(gap)`
(`everquill_engine/ladder.py`; thresholds provisional Sprint-0 values,
shape locked):

| gap | band |
|---|---|
| ≤ −4 | TRIVIAL (no roll) |
| −3..0 | ROUTINE |
| 1..3 | RISKY |
| 4..7 | DESPERATE |
| ≥ 8 | HOPELESS (rolls pick failure flavor only) |

**Difficulty source per action shape** (resolver v1):

| action_type | difficulty | acting stat default |
|---|---|---|
| physical | max target `threat_band` | might |
| social | max target `will` | presence |
| observation (targeted) | max target `wits` | wits |
| research | 5 (ambient bar) | lore |
| craft | 5 (ambient bar) | finesse |
| movement / dialogue / meta / rest / train / untargeted observation | no roll (trivial shape) | — |

`stat_hint` from the intent overrides the acting-stat default; the
engine alone picks difficulty. Untargeted rollable actions use the
ambient bar 5. Authored `laws` in world content override the tier to
SEALED/IMPOSSIBLE before any gap math (see below).

**Risk labels** (pre-roll, words never percentages): ROUTINE→Guarded,
RISKY→Perilous, DESPERATE→Dire, HOPELESS→Suicidal. The fifth label
(Desperate, the stakes word) is reserved for lethal-stakes escalation —
lands with the danger sprint.

**Modifiers** (post-roll Chronicle, KNOWN-safe): one flat band modifier
labeled with the acting aptitude word — ROUTINE +1, RISKY 0,
DESPERATE −1, HOPELESS 0. Band-derived so it leaks nothing the risk
label didn't already say; raw stat gaps would leak true sheets. The 2d6
split itself is fixed (10+/7–9/≤6) so the post-roll audit stays legible.

**Appraisal claims** (observation) report the target's **threat read**:
the band a physical confrontation would resolve at for this actor now —
band words only, never numbers. A failed glance reads exactly one band
too kindly (wrong intel is causal, never random).

## Player-facing display

Raw aptitude numbers are TRUE-sheet data and stay server-side, including
the player's own (`???` fields, roadmap §3.8). The CLI/chargen shows
band words only: ≤4 faint, 5–6 plain, 7–8 sound, 9–10 keen, 11–12
gifted, 13+ uncanny.

## World clock (v1 spec, ticket #5)

`world_time` is an integer count of **world minutes**; minute 0 = Day 1,
06:00 (the awakening). This resolves the `delta_clock` unit note in
outcome.schema.json. Action time costs (`everquill_engine/clock.py`,
keep in lockstep):

| action_type | minutes |
|---|---|
| meta | 0 |
| dialogue | 2 |
| observation | 5 |
| physical | 10 |
| social | 15 |
| movement (in-town) | 15 |
| movement (between locations) | carriage_days × 1440 |
| research | 60 |
| craft | 60 |
| train (commit; block runs on a timer) | 5 + 480-minute block |
| rest | 480 |

Timers: table per synthesis §2.5; Sprint 1 fires them via the manual
sweeper `python -m everquill_engine.cli clock-advance [--minutes N]` —
all overdue timers fire in `(world_due, id)` order, no grace cutoff,
each deterministic with seed = `hash(timer_id, created_event_id)` and
idempotent under command id `timer:<timer_key>`.

## Laws (world-content extension, Team A)

The locked world-content format is silent on authored sealed/impossible
overrides, which the resolver requires (Sprint-1 ticket #4). The loader
therefore accepts an OPTIONAL top-level `laws:` list:

```yaml
laws:
  - law_id: law.<slug>
    name: diegetic name
    tier: sealed | impossible
    action_types: [social]            # optional; empty = any
    target_tags: [veiled]             # optional; matches entity true_sheet.tags
    invoke_phrases: ["hearth-oath"]    # optional; describes the feat to the parser (Laws list); the parser names the law in invoked_law_ids
    components: [hearth_token, ...]   # sealed only; v1 verifies each as a
                                      # boolean flag on the actor's sheet
    on_attempt_incomplete: [...]      # authored fail-forward floor
```

A law must declare at least one matcher. First matching law in file
order wins. Sealed with all components verified resolves at DESPERATE
(a sealed feat is never routine); unmet components fail forward — miss
without dice, deed logged, exposure flag set. Full predicate
verification per docs/lore/laws-format.md is a later sprint. Team B:
author real laws to this shape or negotiate the shape before authoring.

## Addendum (Sprint 1 wave 2)

Stat selection is engine-owned per action type (DEFAULT_STAT_FOR_ACTION); parser stat_hint never affects resolution (telemetry only). Note: the canned "train" action trains the engine-selected aptitude (will) — flip DEFAULT_STAT_FOR_ACTION["train"] if design wants otherwise.

## Addendum (Sprint 2 wave 1 — A1)

### Typed intent boundary (MEDIUM-5)

The resolver validates every intent into the closed typed model
(`everquill_engine/intent.py`, mirrors intent.schema.json v1.3 exactly —
schema-equivalence proven in `tests/test_intent.py`). Unknown keys,
duplicate targets, malformed dialogue/duration, out-of-vocabulary enums
→ `ResolverError` before any canon. Unknown targets are still rejected
against the scene roster.

### Duration binding (MEDIUM-5)

`duration_hint` is CONSUMED deterministically (`clock.bind_duration`) or
rejected — never silently defaulted. Since intent schema v1.3 (2026-10-24) the
engine binds only the closed fields; `text` (the player's words) is for the
narrator and never decides a time cost:

- **explicit** — `amount` × `unit` (`minute`, `hour`, `day`). The parser maps
  named spans by the prompt's rule (`the night` = 8 hours, `the day` = 12,
  `the evening` = 4, `half an hour` = 30 minutes). Cap: 30 days. A missing
  amount or unit → clear `ResolverError`.
- **until_condition** — `until` maps to the NEXT occurrence of a time of day:
  `dawn` → 06:00 · `midday` → 12:00 · `dusk` → 18:00 · `midnight` → 00:00.
  Exactly at the target time → tomorrow's (spans are strictly > 0). A world
  event ("until the caravan leaves", `until: null`) is rejected until event
  clocks exist.

Consumption per action shape:

| shape | consumption |
|---|---|
| train | block length (block starts after the 5-min commit; binding reference = commit time). Default 480. |
| rest | the rest span itself. Span ≥ 480 → inn price + recovery min(4, missing); shorter → free, recovery = span // 120 (capped 4). Default 480 (unchanged behavior). |
| everything else | occupied-time floor: `time_cost = max(base_or_travel_price, bound span)` |

### Roll-site registry (MEDIUM-4)

Every dice draw goes through a registered site
(`everquill_engine/rng_registry.py`; frozen fixture
`tests/golden/roll_sites.json` — append-only): `chargen`,
`action:<type>` (one stream per action type), `hopeless_flavor` (its
own site — the draw picks HOW you fail), `timer_fire:training`.
**Documented pin change:** action outcomes moved off the pooled
`('character:<id>','action')` stream; historical events keep their
stored rng verbatim (replay never re-rolls). Migration 0006 adds DB
uniqueness on `(rng->'stream', rng->'index')`.

### Dispatched targets (decision-5 cluster)

Entities at 0 hp surface the `dispatched` condition in the perceived
manifest. A **physical** action whose targets are ALL dispatched is
TRIVIAL with ZERO deltas and the explicit Chronicle line
`[Already dispatched.]` — no dice ever roll against a corpse (this also
covers weak actors, where gap math alone could still land ROUTINE).
Mixed targets price the fight off the living only.

### Two-phase commit beat + KnownState split

See `docs/engine/known-state.md` (published interface for Teams C/F):
the tier→confirmation table, pending-confirmation semantics (10
world-minutes of activity), and the exact KnownState exports.

### Laws: `irreversible` flag (optional)

`laws:` entries accept `irreversible: true` — forces the commit beat
regardless of tier (interface decision 2's third leg).
