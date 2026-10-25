# Design: Slice 3 — Danger (make hopeless fights bite)

Status: DRAFT design by Claude, grounded in a full map of the wound/combat/death
system. George's decision: "wounded/spared tier, THEN death" (near-misses wound
or spare-with-a-mark; only a true hopeless fight + a bad roll kills; death means
an heir). This note designs the non-lethal DANGER; actual death couples to the
heir flow (see "Sequencing" below).

## What the code already has (from the map)
- A proto wounded/spared/mark ladder ALREADY exists for HOPELESS physical fights
  (ladder.py flavors spared / punishing / catastrophic; resolver.py ~1419-1440
  emits distinct deltas: catastrophic = big self-harm + a `scar_turn_N` flag;
  punishing = self-harm; spared = a hidden `journal_hook_turn_N` flag).
- Persistent-mark primitive exists (`_flag` delta, folded permanently).
- Wound surfacing exists (wound_words bands; self_view hp/hp_max/wounds).
- Death is fully SCAFFOLDED but has NO producer: DEATH_SEALED / HEIR_CREATED
  events, the `death_record` delta field, and a narration-gate consumer all
  exist; nothing emits them, and folds would raise on a death_record delta.

## Why the wyvern punch was free (root cause)
Three defangs:
1. **No counterattack.** Combat is single-exchange: the PC attacks, the foe
   never hits back within the exchange. The PC takes harm ONLY on its own
   miss/complication (or the HOPELESS block). A DESPERATE strong-hit wounds only
   the target. So a good roll against an apex foe costs the PC nothing.
2. **Apex fights read DESPERATE, not HOPELESS.** A might-10 PC vs a threat-14
   wyvern is gap 4 = DESPERATE (HOPELESS needs gap > 7). So the hopeless
   proto-ladder never even fired; the desperate path has no self-harm on a hit.
3. **The lethality clamp.** `_clamped_self_harm` floors PC hp at 1 and
   `_effective_threat` treats hp<=0 as "helpless but alive" — the PC cannot die.
Plus: zero renown in the smoke because the quarry track had NO witnesses, and a
deed is only written `if witnesses`.

## The Slice 3 design (non-lethal danger that BITES)
1. **Bilateral danger (the core fix): a dangerous foe hits back.** On a physical
   action against a foe in the DESPERATE or HOPELESS band, the actor takes
   counterattack harm scaled by the threat gap, REGARDLESS of the actor's hit
   tier. You can hurt the wyvern, but it mauls you for daring. This is what makes
   "punch the dragon" cost blood even on a good roll. Deterministic, scaled by
   the gap; a routine/risky fight (a wolf you outclass) does NOT counterattack.
2. **Make marks REAL and VISIBLE.** Promote the spared/scar marks from hidden
   inert flags to a surfaced, persistent mark: add a `scar_`-style public prefix
   (or a SelfFacts `marks` field) so a spared-with-a-mark shows on the Self view
   and the narrator can reference it. Optional light mechanical bite (a mark is a
   story hook first; heavy mechanics later).
3. **The spared tier gets a real mark**, not just a hidden journal flag — the
   "spared-with-a-mark" George chose.
4. **Solo notable deeds register.** A hopeless/desperate confrontation with a
   deadly foe should write a deed even without witnesses (the world learns of
   the fool who swung on the Quarryman — via the aftermath, the body, the heir).
   So the Slice 2 rumour/renown trail fires for the signature danger moment.
5. **Tiering:** rather than globally re-threshold (risky — affects all actions),
   the bilateral-counterattack rule delivers the danger even when an apex fight
   reads DESPERATE. Optionally, a vastly-overmatched physical fight (gap near the
   HOPELESS edge) can be nudged so the true apex reads HOPELESS; decide in the
   ticket, keep it targeted to physical, do not move the global bands.

## Sequencing: death couples to the heir (Slice 3 stays non-lethal)
Shipping actual death (lifting the clamp, emitting death_record) WITHOUT the heir
flow would dead-end the game (PC dead, no recovery). So:
- **Slice 3 (this): danger bites but is SURVIVABLE.** Real persistent wounds,
  visible marks, counterattack, solo deeds/renown. You can be broken and marked,
  not killed. Deployable with no dead-end.
- **Slice 4 (Legacy): death + heir TOGETHER.** Lift the clamp for a true
  hopeless + catastrophic roll, emit death_record + DEATH_SEALED, add the fold
  handler, roll an heir into the same world. Death and its recovery ship as one
  so there is never a game-over wall.
This honours George's "wounded/spared then death" ladder while sequencing the
irreversible part with its payoff.

## The one design decision for George (combat FEEL)
How hard should the counterattack bite? This sets the whole danger feel:
- **Bloody-but-survivable (recommended):** an apex fight always costs the PC real
  wounds, but Slice 3 keeps you alive (death waits for Slice 4). You learn "this
  thing is out of my league" through blood, then choose to flee or press on.
- **Brutal:** counterattack can drop you to near-death (1 hp, "at death's door")
  in one exchange, making the commit beat genuinely frightening before death even
  exists.
George also to confirm the Slice 3/Slice 4 split (danger now, death+heir next) vs
wanting death in the Danger slice (which needs heir built alongside).

## Owner split
Claude: this design, the ticket, the mark-surfacing UX, review, driving Codex.
Codex: the counterattack rule, mark surfacing, solo-deed rule, tests. Engine
only; no content; eval only if a prompt is touched (the narrator may need a note
so it voices counterattack wounds honestly — flag if so).
