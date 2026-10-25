# Sprint 5 proposal — "Consequence & Legacy" (the stakes layer)

Status: PROPOSAL for George's review. Informed by the roadmap (original S4
"Danger & Consequence" + S5 "Death & Legacy", both deferred) and the 2026-07-15
playtest.

## Why this next
After Sprint 4 + the playability pass, the game is now genuinely playable: you
create yourself, explore Harrowdown, ask NPCs and get real answers, read the
guild board, and chase a lead (the Quarryman, a bounty, the chandler's grief).
But chasing a lead has no teeth yet. The Quarryman is authored HOPELESS, yet
there is no real death, no legacy, no consequence that makes pursuing it MEAN
something, and the world does not react to what you do. Exploration without
stakes goes hollow fast (the same "self-sustaining, plays itself" trap George
has flagged before on other games). This sprint makes the leads matter.

## The three pillars

### 1. Consequence — the world reacts to your deeds (rumor propagation v1)
The `rumor_seeds` are authored and the deed log is append-only, but there is "no
writer yet" (claims.py). Wire it: deeds propagate outward as rumors by
distance / time / notoriety; NPCs and boards surface rumors (about the world AND
about YOU); wrong-intel distortion as rumors travel. This is the engagement
engine — it turns a static board into a living one and makes notoriety real.
Deployable CODE (no content edits). Engine (Codex) + design (Claude).

### 2. Danger — the commit-beat actually pays off
Hopeless feats (punch the Quarryman) already trigger the `<<Proceed?>>` beat, but
the payoff is thin. Land the signature outcome: proceed into a hopeless fight ->
a real, sealed death (or a documented hard lesson / spared-with-a-mark), bound to
committed facts (no invented heroics). Persistent wounds, real notoriety. Sealed
feats (resurrection) fail-forward on missing components. Engine (Codex) + the
death-narration gate (Codex).

### 3. Legacy — death is not game over (S5 foundation)
PC death -> a sealed death record -> roll an HEIR into the SAME world with thin
inheritance (no plot armor); the dead PC persists as an entity; journals carry
their intel; the world remembers ("the idiot who punched the Quarryman"). Even a
minimal version is huge: it closes the loop danger opens. Engine (Codex) + the
heir chargen/arrival UX (Claude, reuses the creation + arrival screens).

## The two-layer reputation (parked from S4) — fold in here or keep parked?
Believed-vs-true standing is a CONSEQUENCE/knowledge feature and would fit this
sprint's theme (a "read someone" action; deeds shifting true vs believed). George
to decide: fold into this sprint, or keep parked.

## Scope discipline
Harrowdown-local still (George's standing choice). Rumor propagation stays within
the vale + the near roads. No worldgen yet (S6/later). Content stays frozen for
live worlds — all three pillars are CODE, so they deploy to existing worlds.

## Suggested order (each a verifiable, deployable slice)
1. Rumor propagation v1 (consequence + dynamic leads) — highest engagement value.
2. Death -> heir -> legacy (the stakes payoff).
3. Danger polish (signature death, sealed-feat fail-forward).
4. (optional) two-layer reputation, if George un-parks it.

## Owner split (as established)
Claude: design, the sprint plan/tickets, the heir/death UX + any client, review,
driving + verifying Codex. Codex: the engine coding (rumor engine, death/heir
system, narration gates), via bounded LLM-written tickets + the eval loop where
the parser/narrator is touched. Verify on local UTC scratch DB; deploy code only.

## Open questions for George
- Is "Consequence & Legacy" the right next sprint, or do you want danger/combat
  depth first, or worldgen (now unblocked by the locked canon)?
- Two-layer reputation: fold in, or stay parked?
- How brutal is death — permadeath-to-heir always, or a wounded/spared tier
  before death for near-misses?
