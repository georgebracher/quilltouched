# Sprint 5 — Consequence & Legacy (the plan)

Status: ACTIVE. Supersedes docs/tickets/sprint-5-proposal.md (the open questions
are resolved below). George's decisions (2026-07-15):
- Next sprint = **Consequence & Legacy** (confirmed).
- Death = **wounded/spared tier, THEN death** (near-misses wound or spare with a
  mark; only a true hopeless fight plus a bad roll kills; death still means an
  heir).
- Rumours = **surface on every ambient look** (Slice 1b).
- Two-layer reputation = stays PARKED (not folded in).

Design law (binding): the engine referees; the LLM only parses + narrates; no
NPC awe the deed log did not earn; append-only event log is the source of truth;
death narration binds to the sealed death record. CODE only where possible so it
deploys to the already-claimed live worlds; content stays frozen.

## The through-line
The world is legible and playable but INERT and CONSEQUENCE-FREE. QA proved it:
punch the apex wyvern, deal it a wound, take none, walk away at full HP with zero
renown. Sprint 5 makes deeds travel (Consequence), makes hopeless fights bite
(Danger), and makes death a beginning not a wall (Legacy).

## Slice sequence (each a verifiable, deployable CODE slice)

### Slice 1 — seeds become talk  [DONE, deployed]
Authored rumor_seeds surface as ambient talk on the research path.

### Slice 1b — rumours on every ambient look  [IN PROGRESS]
Surface a seed on every untargeted ambient observation (per George). Makes the
world audibly alive. Reuses the Slice 1 picker.

### Slice 2 — deeds become rumours (Consequence core; the roadmap S4-A heart)
Bridge `deed_recorded` events -> rumour claims that spread:
- **Distance:** BFS over the authored `carriage_days` travel graph. A deed
  reaches its own location immediately, adjacent locations after a delay, far
  locations later or not at all, past a horizon never.
- **Time:** spread is a function of elapsed world-MINUTES since the deed; stale
  rumours fade from the talk pool.
- **Notoriety:** deed `notoriety` sets reach + speed + lifespan. Derive weight
  from the deed's own facts (already carried on the deed delta).
- **Renown feed (DECIDED: yes).** When word of a deed propagates to "enough" of
  the vale, the actor's `renown` scope rises. This gives the unused renown
  writer an honest source and closes the loop the scope was built for. Renown
  rises from ACTUAL propagation, not a flat per-deed bump.
- Reuses `_claim` -> intel -> CLAIM_WRITTEN with `derived_from_claim_id` /
  `hop_count` (already in the payload, always null/0 today) to model the
  retelling chain; respects the echo-chamber corroboration rule (2+ links with
  DISTINCT root_event_id).
- The rumour pool is a PROJECTION rebuilt from the deed log + seeds + world-time,
  never free-floating state (same discipline as the reputation projection).
- NOTE (from the scaffolding map): deeds are minted only on PHYSICAL + fail-
  forward outcomes with witnesses. If notorious SOCIAL acts should spread too,
  widening the deed-mint sites is a small sub-task; flag its scope in the ticket.
- Freshness window: provisional value in world-minutes, tuned later.
- Faithful rumours first; distortion is Slice 5.

### Slice 3 — Danger: hopeless fights bite (wounded/spared/death ladder)
The commit beat fires but the payoff is thin. Make proceeding into a hopeless or
desperate fight actually cost:
- The PC TAKES REAL WOUNDS in a hopeless/desperate fight (QA: took none).
  Persistent, surfaced on the Self view.
- **Outcome ladder (George's "wounded/spared then death"):**
  - desperate / near-miss -> wounded, or spared-with-a-mark (a lasting flag /
    scar the world can reference), NOT death.
  - true HOPELESS + a bad roll -> a sealed death (Slice 4 consumes it).
  - hopeless is always outcome_tier miss (the roll picks HOW you fail); the
    ladder decides wound vs spare vs death from the band + roll.
- Real notoriety: a hopeless-fight deed writes a high-notoriety deed that Slice 2
  propagates ("the idiot who swung on the Quarryman").
- Sealed feats (resurrection etc.) fail forward on missing components (already
  scaffolded; harden here).
- Death narration binds to the sealed death record; no invented heroics.
- Combat depth (single-exchange -> resolved-to-conclusion) is a KNOWN gap from
  QA; decide in the ticket whether Slice 3 addresses it or defers to a combat
  slice, to avoid scope creep.

### Slice 4 — Legacy: death is not game over
PC death -> a sealed death record -> roll an HEIR into the SAME world:
- Thin inheritance (no plot armour). The dead PC persists as an entity.
- Journals carry the dead PC's intel to the heir.
- The world remembers ("the one who punched the Quarryman") via the Slice 2
  rumour/renown trail.
- Heir chargen + arrival reuses the existing creation + arrival screens (Claude,
  client). Multi-character account model.
- DoD (roadmap S5): die stupidly, roll an heir, walk into the bar, hear the tale
  of the fool who punched the wyvern, find the journal, learn the blind side.

### Slice 5 — distortion + world-remembers polish
Bounded deterministic distortion as rumours travel (hash-seeded off deed id +
hop count; numbers inflate, names blur, wrong credit; never new facts, always a
link back to the source deed). Polish the "world remembers you" surfacing.

## Owner split (as established)
Claude: this plan + the slice tickets, the death/heir + arrival UX and any
client, review, driving + verifying Codex, narrator guidance so rumours read as
talk and deaths bind to the record. Codex: the engine coding (rumour projection
+ writer + spread math, the wound/spare/death ladder, the heir system,
distortion) via bounded LLM-written tickets + the eval loop where the parser or
narrator prompt is touched. Verify on the local UTC scratch DB; deploy CODE only.

## Scope discipline (hard boundaries)
Harrowdown-local. Rumours propagate within the vale + near roads only. No
worldgen (S6/later). Content frozen for live worlds; every slice is CODE. Each
slice ships deployable and verified before the next. Park sudden new-system ideas
in a backlog note, do not let them redirect the slice sequence.

## Verify story
Every slice: resolver/projection tests + one API smoke on a fresh QA world
(never George's world); rebuild-stability for any new projection; live smoke
after deploy. Death/heir slices additionally assert the sealed record binds and
the heir arrives into the same world with the dead PC persisted.
