# Sprint 4 — The Self & The Social

**Reshapes the roadmap's Sprint 4 ("Danger & Consequence").** George's 2026-07-14 supervised
playtest (world `f8b61187`, 10 turns in the Drowned Ram) proved the real gap is not danger — it's
that **the character has no weight**: you can't break through to NPCs, you can't shape who you are,
and there is no reputation for the world to remember you by. The danger items (adjudicator,
commit-beat death polish, creature sprites) are NOT invalidated — they move to a later slice (S4b /
fold into S6). The one danger item that belongs HERE is *deed-log → rumor propagation*, because that
**is** the global-renown half of reputation. Everything below hangs off one axis:

> **The weight of you = what you CHOOSE (chargen build) + what you EARN (reputation), meeting at the
> social roll — where charisma + standing decide whether people open up, believe you, or shut you out.**

## What already exists (do NOT rebuild — extend)
- **Social IS a real roll:** `2d6 + presence` vs the target's `will` (`resolver.py` DEFENDING_APTITUDE
  / resolve_difficulty). Strong/mixed/miss branches already fire and write per-NPC flags
  (`rapport_<id>`, `owes_favor_<id>`, `rebuffed_<id>`) + disposition claims.
- **Chargen rolls honestly:** `chargen.roll_character` rolls a seeded `2d6` per aptitude
  (hash-derived, replayable). HP = 4 + might.
- **Claim system** (Chronicle/Inquiry, provenance, contradiction_ids) — reused for identity-as-claims.

## What is broken / missing (the sprint)
1. **`dialogue` is a no-roll shape** (`resolver.py` `no_roll_shapes`), so free-text talk that means to
   *move* someone auto-resolves to nothing. Playtest: 8 conversational turns, ~all `trivial` no-ops.
2. **The disposition flags are orphans** — nothing reads `rapport_`/`owes_favor_` back into
   difficulty, so winning someone over does not compound. Booleans, not a scaled score.
3. **No reputation anywhere** (grep-confirmed): no per-person disposition score, no per-town standing,
   no global renown, and nothing feeds any of it into the social roll.
4. **Chargen has no agency and no self** — stats are blind-rolled, there is no creation screen, no
   isekai arrival, and investigating yourself returns nothing ("say something about yourself" → "nothing
   comes of it"). The character record holds `name=the Quill-touched`, `origin=quill_touched_stranger`,
   aptitudes — none of it reachable by the player.
5. **Composer chips spoil the mystery** — partially fixed 2026-07-14 (wyvern-naming chips
   de-spoilered in `client/src/intents.ts`, staged not deployed); the proper fix is discovery-gating.

## Locked design decisions
- **Chargen model = GUIDED DICE** (George, 2026-07-14). Keep the seeded `2d6` rolls (honest-dice canon);
  agency comes from **assigning** which rolled value lands on which aptitude + **one reroll**. The
  assignment is a player choice recorded in `character_created`; the reroll consumes the next
  chargen-stream index (still hash-derived, still auditable, still replayable). Validation: the
  assignment must be a permutation of the rolled pool; ≤1 reroll.
- **Reputation = three scopes**, all event-sourced deltas → a rebuildable `reputation` projection:
  - `disposition` — per (actor ↔ NPC) pair, scaled int (proposed −3…+3). Replaces the boolean flags.
  - `standing` — per (actor ↔ settlement), scaled int. Witnessed local deeds/social wins move it.
  - `renown` — per actor, global, band-scaled (a spreading name). This is *rumor propagation v1*:
    deeds propagate outward by distance/time/notoriety (roadmap S4-A), decayed by distance.
  - Decay-over-time is NOTED but DEFERRED (v1 = monotone from deeds; no time-decay yet).
- **Reputation feeds the roll:** social difficulty v2 = target guard (`will`) − disposition(actor,target)
  − standing(actor, here) ± approach-fit. Charisma (presence) stays the attacking stat, so a
  presence-built character genuinely talks better — the payoff for the guided-dice push.
- **Identity is claims.** "The System records what you know — not what is true" applies to the SELF:
  self-assertion writes a claim ABOUT the PC into the world (name, origin, story) that NPCs can
  believe / doubt / contradict, exactly like any other claim.

## Build order (bottom-up — verify each layer before the next; house rule)

### Wave 1 — DATA: reputation state (engine + migration)
Lane: `everquill_engine/**` (new `reputation.py`, folds, delta types), `migrations/00NN_reputation.sql`,
`tests/**`. Own scratch DB (`everquill_test_s4a`); `pgrep -fl pytest` empty first; never two suites on one DB.
- New delta types: `disposition_delta`, `standing_delta`, `renown_delta` (append-only events).
- `reputation` projection table (actor_id, scope, subject_id|settlement_id|NULL, value, last_event_id)
  + a pure fold that rebuilds it from the event log. Replay-safe; projector bump.
- Migrate the existing per-NPC flags: the social branch stops writing boolean `rapport_/owes_favor_/rebuffed_`
  and writes scaled `disposition_delta` instead (old flags kept readable for legacy worlds; no live world
  depends on them beyond this session).
- **Verify:** fold a scripted event stream → assert disposition/standing/renown values; rebuild-from-scratch equals incremental.

### Wave 2 — CORE: social resolution v2 (engine)
Lane: `everquill_engine/resolver.py`, parser contract (`docs/contracts/**`), `tests/**`.
- **Close the dialogue trap:** addressing an NPC with a *want* (persuade / ask-for / get-them-to)
  resolves as a `social` contest, not a no-roll `dialogue`. Keep `dialogue` for pure info/RP.
  Mechanism: the parser flags intent-to-move; `dialogue` carrying a want escalates to `social`
  (document the rule in the parser contract; add golden utterances both ways).
- **Difficulty v2:** `resolve_difficulty(social)` subtracts disposition(actor,target) + standing(actor,here),
  ± approach-fit. Clamp to a sane band. Reputation now changes the odds.
- **Outcomes v2:** strong/mixed/miss write **scaled** disposition deltas (+2 / +1 / −1 proposed) and,
  when the win is witnessed and consequential, standing/renown deltas. The loop closes — next roll is easier.
- **Verify:** same NPC, two social turns — second is measurably easier after a win; a miss lowers disposition and is remembered.

### Wave 3 — INTERFACE: chargen + arrival + Self view + chip de-spoiler (engine hooks + client)
Lane: `everquill_engine/chargen.py`, `api/**` (chargen + self endpoints), `client/src/**`.
- **Guided-dice chargen:** engine rolls the six-value pool + supports a validated assignment + one reroll;
  `api` exposes roll → assign/reroll → commit. Client **creation screen** (roll → place → reroll once →
  confirm) + an **isekai arrival beat** (who you were before the Quill touched you; sets origin flavor +
  a claimable backstory + starting kit).
- **Self view:** a Character/Self screen where investigating yourself returns your sheet **as narrative**
  + your reputation (disposition per known NPC, standing per town, renown) with the **known-vs-true**
  split; self-assertion to an NPC writes an identity claim into the world.
- **Chip de-spoiler proper:** discovery-gate specific chips (only surface "ask about the Quarryman" after
  the player has learned it exists); keep generic safe verbs always. (Staged label fix already in `intents.ts`.)
- **Verify:** create a presence-built charmer end-to-end; open Self and see who you are + your standing.

### Wave 4 — INTEGRATION: the Jorun loop
- Create a character (roll → push the 11 onto presence → arrival) → walk into the Ram → press Jorun.
  First meeting: presence vs his guard, no standing yet → mixed; he cracks slightly, your Harrowdown
  standing ticks up. Return later → the roll is easier → he opens up. Investigate yourself → see your
  name, origin, and standing. Tell Maren you're a scholar from the drowned coast → it is recorded as a
  claim she half-believes, and it can later be contradicted.

## Definition of Done
The exact loop that failed in the playtest now works AND compounds: talking can succeed, charisma you
CHOSE matters, reputation you EARNED changes the odds, and investigating yourself tells you who you are.
No LLM call decides any number (engine still owns disposition, standing, renown, difficulty, dice).
True sheets never serialize. Event log append-only; reputation is a rebuildable projection. All suites
green on isolated scratch DBs; `make release-check` green; goldens/pins updated per replay rules.

## Deferred out of this sprint (was roadmap S4 "Danger")
Adjudicator + precedent ledger; commit-beat death signature polish; hopeless failure-flavor bands;
sealed-feat law hardening; creature-scale sprites. Revisit as S4b or fold into S6. (Commit beat itself
already exists from S3.)
