# Playtest findings — 2026-07-15 (George, live, guided flow)

George played the live build (quilltouched.gitm.gg, guided claim). It exposed
core-loop bugs and a dead-end that make the game not actually playable yet, on
TOP of the Sprint 4 features. These are mostly pre-existing core-loop problems
surfaced by real deep play, not Sprint 4 regressions. Capture + triage below.

## P0 — GAME-BREAKERS (the game is not playable until these are fixed)

**ROOT CAUSE of #1 + #2 (they are ONE problem): the travel/exploration surface
was never built.** resolver.py:1173 movement needs a target LOCATION from the
travel network, but /api/scene only exposes entities (NPCs/items), never travel
connections (intents.ts: "No movement intents in v1 ... Sprint 2 wires the
map/travel surface" — it never got wired). So any "go to X / go outside" makes a
movement intent with no resolvable location -> the error. Also intra-scene moves
("go to the bar", where the bar is part of the tavern, not a separate location)
are mis-classified as travel instead of trivial repositioning. Net: you are
confined to one room with no exit and nothing to do. This is the CENTRAL gap,
and it is a real feature build (travel: engine scene surface + parser roster +
client destination picker + content leads), not a one-line fix.

1. **Movement is broken** = travel surface unbuilt (see root cause). The single
   biggest blocker. → design (Claude, the travel/exploration model + UX) +
   engine/parser/scene wiring (Codex).
2. **Dead-end: nothing to do** = the same root. No exploration, so no leads, no
   places to go; NPCs stonewall and the corkboard is bare because there is
   nowhere the loop can send you. Fixing travel + giving NPCs/board real leads is
   what opens the game up. → design (Claude) + content/engine (Codex).
3. **Coin never decrements.** Bought/poured a drink (should cost ~2 copper) and
   gave Maren a copper, but the coin at the top stayed at 30 both times. The
   economy does not deduct. → engine bug. Codex.
4. **Narrator invents inconsistent wounds.** Punched Pike: turn 1 "split lip",
   turn 2 "wounded arm tucked against him", turn 3 "wounded leg". One wound
   state, three different invented body parts across turns. Violates the "no
   invented state" law. → narration fidelity / gate. Codex (narrator + gate).

## P1 — UX / clarity gaps

5. **No conversation continuity (sticky addressee).** Mid-conversation with
   Pike, a follow-up ("about his captain's plate") with no name went to the
   whole room, not Pike. In a conversation you should not have to re-type the
   person's name every turn. The parser is (correctly, post-X2) cautious about
   an unnamed addressee with 2+ people present; the fix is a conversation
   context that keeps the current addressee sticky. → feature. Claude (UX design)
   + Codex (parser/engine context).
6. **Failed/errored action leaves your text in the composer.** You must delete
   it char by char. Need a clear button and/or auto-clear on submit. → UI.
   Claude. Quick.
7. **Pills, not a dropdown.** The suggested-action pill row is still there (the
   agreed direction is one dropdown, no horizontal scroll). → UI. Claude (this
   is ticket C1, now clearly wanted).
8. **Coin unit is unlabeled.** "30 of whatever the thing is at the top" — is it
   copper? Label it (e.g. "30 copper" / a coin glyph with the unit). → UI. Claude.
9. **"one mark on the Chronicle" is unclear.** A recurring line the player does
   not understand. Clarify what a Chronicle mark means, or reword. → messaging.
   Claude.
10. **Codex entry "Market Square" with no context.** A Codex/known entry names
    "Market Square" but the player has no idea what it is. → content/UI (surface
    what a known location IS, or don't seed a bare name). Claude + content.

## Not confirmed this session
- Did guided creation actually show (place-your-hand + arrival)? George did not
  mention it; verify he went through it vs auto-genesis.
- Did any social/persuasion roll fire (the X2 fix)? Not reported; the dead-end
  may have prevented reaching a clean persuasion attempt.

## Priority
P0 first (movement, dead-end, coin, wounds) — without them there is no game to
play. Then P1. Split: Claude = UI (6,7,8,9) + design the leads/exploration for
(2) and the sticky-addressee UX (5); Codex = the bugs (1,3,4) + engine context
for (5) + content for (2), driven + verified by Claude.

## Round 2 (live smoke, post-fixes) — 2026-07-15
Ran a live production smoke after deploying the fixes. Confirmed:
- Movement / exploration works (leave tavern -> Market Row, position delta).
- Guided chargen end-to-end works (claim guided -> pool -> commit -> play).
- **Asking an NPC a question now surfaces authored knowledge** (intel claim) —
  the "no one gives information" fix works live.

Remaining (PARSER-CLASSIFICATION variance, eval-gated, George's call on direction):
- A conversational follow-up ("and what about the quarry?") sometimes parses as
  `meta` (system query) instead of continuing the conversation (`dialogue`), so
  the sticky-addressee engine fix (correct + deployed) does not get a chance to
  apply. Needs a parser rule + goldens: an unnamed follow-up while in a
  conversation is dialogue to the current partner, not meta.
- "buy an ale" sometimes parses as a trivial social with no buy-signal, so the
  coin detector (correct + deployed) does not fire. Needs the parser to reliably
  mark a purchase, or the detector to key off buy/order verbs more robustly.
These are inherently imperfect (LLM classification variance at the boundary);
worth a focused parser-tuning pass through llm/parser_eval with George's steer.

## Status of the 10 original findings
DEPLOYED + working: movement/exploration (1,2), wounds (4), dropdown (7), clear
button (6), coin label (8), NPC-answers-questions (part of 2). PARTIAL (engine
fixed, parser-gated): coin-on-buy (3), sticky addressee (5). Cosmetic/deferred:
Chronicle-mark wording (9), Market Row Codex label (10). Content (tavern board,
richer leads) HELD by the content-freeze — future worlds only.

## Round 3 (Claude deeper QA smokes, autonomous) — 2026-07-15
Fuller Harrowdown playthroughs on throwaway QA worlds (never George's world),
after the parser-round-3 deploy. The exploration loop is healthy: multi-hop
movement (tavern -> Market Row -> guild hall -> chandlery), the guild board,
research, NPC dialogue (Fenn answers), and trivial combat (ditch slime) all
resolve cleanly. Found and fixed / queued:

- **[FIXED, gated, merged fc2c6d4, deploy held for George] Observing your
  current location 422'd.** "observe the room" / "survey the tavern" / "look
  around the tavern" hit the target-addressability check and returned "that is
  not something you can act on from where you stand", while "look around" /
  "look around the room" worked. Fix: in decide_tier, an observation whose target
  is the actor's own current location drops to the ambient no-roll look (mirrors
  the movement escape hatch). First-turn friction; a player's first instinct is
  to look around.

- **[FIX QUEUED, ticket written] Blocked movement is narrated as travel
  (design-law violation).** "go to the drove road" while the only exit is Market
  Row returns 200 with ZERO deltas (PC does NOT move, /api/scene confirms), but
  the sonnet narrator writes "Bran crosses the tavern floor... the drove road
  waits past ...", implying travel that never happened. The engine already
  computes the correct note (system_note = "You can go to: Market Row") for a
  blocked move; the API just needs to skip sonnet and surface that note
  deterministically (like the rest/degraded path), so the player sees their real
  exits instead of confabulated motion. This is the "I can't tell what happened /
  at a loss" feeling George reported, root-caused. Engine tag + API routing, no
  prompt change, no eval.

- **[NOTED, needs George's design call] Targetless physical attack silently
  retargets to whatever creature is present.** Naming an absent creature ("attack
  the cairn rat" while only the ditch slime is present) drops the unresolved
  target and hits the present creature instead (the narrator is honest about
  which creature, but the player's named target was ignored with no feedback).
  Design decision: reject with "there is no cairn rat here" vs auto-target the
  sole present threat. Not fixed pending George.

## Round 4 (Claude commit-beat baseline, autonomous) — 2026-07-15
Navigated a high-might QA PC tavern -> Market Row -> drove road -> quarry track
(all adjacent hops, position deltas clean) to reach the Quarryman (the apex
wyvern, threat 14) and exercise the `<<Proceed?>>` commit beat. NO new code bugs;
movement, combat, the beat, and confirm all work and narration stayed honest.
This is DESIGN baseline for the Danger sprint, not a bug list.

- **Commit beat works.** "charge the Quarryman and beat it to death with my
  fists" -> pending_confirmation true (the beat fired). Confirm -> resolved
  desperate/strong_hit on honest dice [5,6] -1 might = 10; wound_transition on
  the Quarryman; narration bound to the roll ("this adds to it... one arm
  folding wrong"), no invented heroics.
- **STAKES ARE THIN (the Danger-sprint thesis, now with data).** The fresh PC
  punched the apex wyvern, DEALT it a wound, took NONE (hp stayed 14/14,
  unhurt), and gained ZERO renown. No PC wound, no death, no notoriety, no world
  reaction. Exactly the "danger payoff is thin / world plays itself" gap Sprint 5
  ("Consequence & Legacy") is meant to close. Punching a dragon should not be
  survivable-and-free.
- **Combat is single-exchange.** "beat it to death" resolved as ONE exchange
  (a strong_hit that damaged but did not kill and did not end the fight), not a
  fight-to-conclusion. Combat depth is a Danger/B-team question.
- **Balance note.** A downland wolf (threat 5) resolved TRIVIAL (instant kill)
  for a min-maxed high-might PC, same tier as the threat-1 ditch slime. Tiering
  vs mid creatures may collapse to trivial for a maxed aptitude; a Sprint-6
  B-team balance concern (depends on exact PC might).
- **Minor / verify.** The narrator said "pulls the blade clear" on an
  unspecified/unarmed attack. Check whether guided PCs start with a weapon; if
  not, this is equipment confabulation (narrator inventing a fact) and belongs
  in the narrator-integrity backlog.
