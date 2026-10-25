# Progression: uncapped, but not cheese-able (design spec)

George, 2026-07-15. The game has **no level cap** (locked long ago: infinite
grind allowed, band-relative progression). The risk of "no cap" is the Skyrim
wall: sneak into a corner by a sleeping bear and max Sneak before you leave the
tutorial. Growth must come from genuine, varied challenge, never from repetition.

This spec is backed by a 3-agent research pass (Skyrim ceiling mechanics, the
Skyrim exploit catalogue, and anti-grind design across use-based RPGs). Sources
are in the research outputs; key ones cited inline.

## What the research settled

**Skyrim is the cautionary tale.** Skills hard-cap at 100 (start 15); the 2013
"Legendary" patch resets a maxed skill to 15 and refunds perks, which
*effectively* removes the old level-81 cap. Crucially, **Skyrim's core skill-gain
formula has no anti-grind at all**: a trivial action grants the same XP every
time, forever. Their only brakes are (1) a steep cost curve `~level^1.95` and (2)
a few hand-placed content locks (a picked lock gives no repeat XP). Across 20
years Bethesda fixed *min-maxing*, never *trivial repetition*. That gap is the
exact space our difficulty band lets us fill.

**The cheese pattern (from the exploit catalogue):** every Skyrim exploit shares
a shape. XP is paid for *use*, not for *overcoming difficulty*; a safe,
infinitely-repeatable target or state exists (a sleeping/essential/paralysed
foe, a corpse, a self-buff with no target, a crafting station); self-sustaining
resource loops remove the natural limiter; and the whole thing is AFK-able
(rubber-band the run key). Kill any one leg and the cheese dies.

**Both of our instincts are shipped, proven mechanics:**
- **(a) Challenge-relative gains, trivial → zero.** WoW: below the "grey level" a
  kill gives literally **0 XP**, with a *smooth linear decay* down to it and a
  *bonus for facing up*. FFXI: "Too Weak to be Worthwhile" gives **0 XP**, con
  tiers scale reward with difficulty, and a per-level cap stops a fluke
  over-band win from paying a jackpot. This is the single highest-leverage
  mechanism, and our engine already computes the band it needs.
- **(b) Same-route diminishing returns.** Smash Bros stale-move negation (repeat
  a move, it weakens; vary, it refreshes) and Guild Wars 1/2 anti-farm DR
  (farm one spot, drops decay; move on, they reset). Two known failure modes:
  players defeat naive DR by *rotating a small set of targets* (so canonicalise
  target signatures and demand real variety), and *hidden* DR breeds resentment
  (so show it).

## The design (ranked, band-native)

Our deterministic engine already assigns every action a plausibility band
(trivial / routine / risky / desperate / hopeless) relative to the actor. That
band is the whole game here; the top mechanisms bolt straight onto it.

1. **Challenge-relative growth (the primary gate).** Map the band to a growth
   multiplier. An action that resolved as **trivial or routine for you** yields
   **zero** growth. Risky and up yield growth that rises with the band. Use a
   smooth ramp to zero, never a cliff (WoW), and a per-band cap so a lucky win
   far above your band cannot be farmed for a windfall (FFXI). Charming the
   barkeeper is trivial for a charmer, so it teaches nothing; cracking someone
   genuinely hard does.
2. **Legibility (mandatory companion).** We already show the band pre-roll in the
   assessment. Add whether it will teach you: "trivial, no growth" vs "a real
   test". In a typed game this is nearly free and turns the gate from a hidden
   punishment into an informed choice. Invisible anti-cheese (GW1) breeds
   resentment; visible rules (Smash, FFXI Check) do not.
3. **Same-route diminishing returns (secondary layer).** Track a rolling window
   of recent (action_type, canonicalised-target, approach) tuples. Each exact
   repeat multiplies growth down; real variety refreshes it. Canonicalise the
   target so "Maren about the road" ten ways collapses to one signature, and
   show the decay diegetically: "you do not seem to be getting better at this."
4. **Challenge streak / momentum (the carrot).** Consecutive at-or-above-band
   actions build a small bonus (FFXI Experience Chain, up to ~+50%); a trivial
   action or an exact repeat breaks it. This reads beautifully in prose for a
   narrative game: "your momentum builds". Facing up and varying become a reward,
   not only the stick of 1 and 3.
5. **Self-scaling cost curve (uncapped backstop).** Each point of a stat costs
   more raw growth than the last (Skyrim's `level^1.95`), asymptotically. No hard
   cap, but the top of the curve crawls, so even a gap in 1/3 cannot inflate a
   stat quickly. Pairs with the no-cap promise. Never use this *instead* of 1;
   on its own it only slows grinding (Skyrim proves it).
6. **Growth binds to the resolved outcome (hygiene).** Grant growth from the
   outcome the engine actually resolves, never from the mere submission of text
   (the Final Fantasy II lesson: count a use only when the turn truly executes).
   Our event-sourced architecture already satisfies this.

## Feel / messaging
- Never a silent wall. When a route stops teaching, say so in fiction.
- The Self screen already promises "none of them cap". This spec is how that
  promise stays honest without becoming a grind exploit.

## Ownership
Design: Claude (this spec). Build: Codex, when the training/progression system
lands (post-Sprint 4; ties to the exclusive-foreground training + world-clock
economy in `docs/isekai-playbook.md`). Not built yet. Research outputs archived
in the session task logs.
