# Player appearance + the Pack (paper-doll) — design note [PARKED, not Sprint 4]

George, 2026-07-15. Question raised: do we worry about what the player looks
like, and if items have graphical (sprite) form, should the player see their
appearance in the inventory, standard paper-doll with the player centred?

**Scope: NOT Sprint 4** (The Self & The Social). This belongs to the **Pack
(inventory) screen** and the **sprite/art system** (Team E lane), both later.
Captured here so it is not lost and does not drift into the current sprint.

## Design direction
- Items are locked as **sprite-based, flat 2D, generated on the fly and stored**
  (concept session). So items will have visual form; the Pack can show it.
- **Paper-doll Pack, player centred.** Equipped items render on/around the
  figure, so one screen answers "what do I look like" and makes the kit
  tangible. Standard RPG convention, correct here.
- **Surface division (keep them distinct):**
  - **Self view** (built, Sprint 4) = your *nature*: stats, believed standing,
    origin. Deliberately text-forward, no portrait.
  - **Pack** (future) = the *visual you*: inventory + appearance assembled from
    what you carry/wear.
- **Isekai angle (word-forward, on-brand):** you arrive as an undefined
  "stranger" (summoned/chosen). Rather than a chargen dress-up, let appearance
  **assemble from acquired items and deeds**, so your look becomes a record of
  what you have done. Fits the Quill theme (the world writes you as you act).

## Open forks (decide when we build the Pack/sprite system)
- How much avatar does a heavily narrated, typed game actually want? Risk of a
  dress-up minigame distracting from the word-forward core.
- Does the PC also appear in the **scene canvas** (Play screen), or only in the
  Pack? A first-person-feel scene argues for Pack-only; a "you in the world"
  feel argues for placing the PC sprite in-scene too.
- Generated-sprite pipeline: how the PC base + item layers compose (the
  on-the-fly sprite plan).

## Ownership
Design: Claude. Build: later (sprite system Team E; Pack screen Claude UI).
Do NOT start until Sprint 4 finishes (parser X2 + chargen API X3).
Related: [[project_everquill]] · docs/tickets/sprint-4-codex-handoff.md (parked list).
