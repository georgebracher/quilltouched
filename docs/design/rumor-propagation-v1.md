# Design: Rumor propagation v1 (the world reacts to your deeds)

Status: DRAFT design spec by Claude, grounding a Codex implementation ticket.
Roadmap anchor: Sprint 4 (Danger & Consequence), item A, first line:
"deed log -> rumor propagation v1 (distance / time / notoriety)". This is the
roadmap's own next item, not a new idea. It is also pillar #1 of the Sprint 5
proposal ("Consequence"). CODE only (no content edits) so it deploys to the
already-claimed live worlds.

## The problem it solves
Today the world is legible but inert. You explore Harrowdown, read the guild
board, ask NPCs, chase a lead, kill a slime, and none of it leaves a trace. The
board is static. NPCs never mention what you did. Your renown scope exists as a
number but nothing feeds it from your actual deeds and nothing reads it back to
you. This is the "self-sustaining, plays itself" hollowness George has flagged
on other games: without the world reacting, exploration has no feedback loop.

Rumor propagation is the smallest system that makes the world feel alive: your
deeds travel outward and come back to you as talk. It is the engagement engine
that turns a static board into a living one and makes notoriety real and earned.

## The design law it must obey (from CLAUDE.md)
"No NPC awe the deed log didn't earn." Every rumor must be traceable to a real,
committed deed (or an authored seed). No invented reputation. The narrator may
only voice a rumor the engine produced from a real fact. This is the whole point
of the deterministic-referee architecture, and rumors are the highest-risk place
to violate it, so the writer is engine-owned and deterministic.

## Player-facing behavior (what George should feel)
1. You do something notable (kill the thing menacing the quarry road; deck a
   guard in the tavern; solve the chandler's grief). It writes a deed.
2. Time passes / you travel. The deed becomes a rumor that spreads outward from
   where it happened, reaching nearby places first, distant places later or not
   at all, scaled by how notable it was.
3. Later, somewhere else, you read a board or ask an NPC and hear about it, told
   as talk, not as a system fact: "Heard someone put the ditch-thing down out on
   the quarry road." Sometimes garbled ("they say it took three of them").
4. Rumors about the WORLD (authored seeds: the Quarryman, Hollow Tor lights)
   propagate on the same rails, so the board and NPC chatter feel populated
   without hand-placing every line.
5. Over time this is what makes renown real: NPCs treat a known name
   differently because word actually reached them, not because a number moved.

## The three dials (distance / time / notoriety), stated as design intent
- **Notoriety (weight):** how big the deed was sets how far and fast it travels
  and how long it survives. A slain slime is a shrug; a slain wyvern is a saga.
  Derive weight from the deed's own facts (action kind, target scale, outcome
  tier), not a new authored field, so it works for any deed in any world.
- **Distance:** rumors reach the deed's location immediately, adjacent locations
  after a delay, farther locations later and fainter, past a horizon not at all.
  Distance = hops on the authored travel graph (reuse the existing connections;
  do not invent a coordinate system).
- **Time:** spread is a function of elapsed world-time since the deed. Rumors
  have a freshness that decays; a stale rumor fades from the talk pool. This is
  pure world_time arithmetic, deterministic and replay-safe.

## Distortion (truth degrades as it travels)
A rumor is not the deed. The farther it travels and the more notable it is, the
more it garbles: numbers inflate, names blur, the wrong person gets credit. v1
distortion is deterministic (hash-seeded off the deed id + hop count, same seed
discipline as the dice) and BOUNDED to a small authored/coded distortion table
so it never fabricates new facts, only degrades existing ones. A rumor always
carries a link back to its source deed so the engine (and an audit) can prove
provenance. Distortion is a v1 nice-to-have; if it risks the schedule, ship
faithful rumors first and layer distortion second.

## Scope discipline (hard boundaries for v1)
- Harrowdown-local. Rumors propagate within the vale and the near roads only.
  No cross-world, no worldgen (that is S6/later).
- CODE only. Reuse the authored rumor_seeds and travel graph as-is. No edits to
  content/world/*.yaml (frozen for live worlds).
- Deterministic + event-sourced + replay-safe. The rumor pool is a PROJECTION
  rebuilt from the deed log + seeds + world-time, never free-floating state.
  Same discipline as the reputation projection already shipped.
- Read path only surfaces rumors through EXISTING surfaces (boards on
  observation, NPCs on an information-seek). No new UI required for v1; the
  Codex/transcript already renders intel claims.
- Bounded output: one relevant rumor per surfacing, deterministic pick, no
  dumping the whole pool. Same restraint as the NPC-common-knowledge reveal.

## Verification story (how we know it works, on a live-safe world)
On a fresh QA world: do a notable deed at location X; advance world-time and
travel to adjacent location Y; assert an NPC/board at Y surfaces a rumor claim
that links back to the source deed; assert a far location Z past the horizon
does NOT (yet); assert the authored seeds surface on the same path. All at the
resolver/projection layer plus one API-level smoke. Never against George's world.

## Open design questions (for the ticket or for George)
- Does renown (global scope) get FED by this (deeds -> renown via the rumor that
  reached "enough" of the world), closing the loop I built the scope for? I lean
  yes: renown should rise when word of your deeds actually propagates, which is
  more honest than a flat per-deed bump. Confirm with George.
- Freshness/decay window in world-time units: provisional value, tuned later.
- Distortion in v1 or v1.1: recommend faithful-first, distortion as a fast
  follow so the core rails land clean.

## Owner split
Claude: this design, the ticket, review, driving + verifying Codex, any narrator
prompt guidance so rumors are voiced as talk not fact. Codex: the rumor
projection + writer + read-path wiring + distance/time/notoriety math + tests,
via a bounded ticket. Eval only if the parser/narrator prompt is touched.

---

## Mechanism (grounded in the current code)

What already exists and gets REUSED as-is:
- The claim pipeline. A rumor is just an Inquiry claim with `method="rumor"`.
  `_claim` (resolver.py ~561) builds it; the `intel` delta fans out to a
  `CLAIM_WRITTEN` event (resolver.py ~2291) whose payload ALREADY carries the
  propagation slots `provenance_root_event_id`, `derived_from_claim_id`,
  `hop_count` (today always None/None/0). It folds to `folds.claims` and surfaces
  through `views.InquiryClaim` / `KnownState.inquiry_claims`. So rumors need NO
  new surface, NO new view, NO new event type. They ride the dossier surface.
- The acquisition vocabulary: `"rumor"` = base evidence weight 35, with
  time-decay (STRENGTH_HALF_LIFE ~30 days) and the echo-chamber corroboration
  rule (2+ links with DISTINCT root_event_id to corroborate; retellings of one
  deed only raise strength). Rumors obey this for free.
- The `whereabouts` predicate spec (claims.py ~194), registered world-valid /
  exclusive, "no writer yet" — the slot a location-rumor writes into.
- The reputation projection's unused `renown` scope (folds.py ~199) as the
  eventual notoriety sink.
- Distance primitive: `Location.connections` = directed edges with
  `carriage_days` (0 intra-settlement); `Location.region` is the coarse bucket
  already used to key deed streams (`region:{region}`). Time primitive:
  integer world-MINUTES clock (clock.py), on every event envelope.

What does NOT exist and must be built (the gaps, per the map):
- Nothing reads `WorldContent.rumor_seeds` (loaded, consumed by nobody).
- No deed -> rumor bridge. `deed_recorded` events (stream `region:{region}`)
  have a NO-OP fold; deeds and claims are fully disconnected.
- No distance/time spread logic, no notoriety -> renown link, no seed distortion.

Two design notes the map surfaced that shape the slices:
- A `RumorSeed` is ONLY `{deed: freetext, notoriety: float}` — no subject,
  origin, or distance. So seed rumors are ATMOSPHERIC world-flavor claims (like
  the existing `_research_ambient` low-strength taproom rumor), NOT
  subject-linked dossier facts. That is fine and correct for v1.
- Deeds are minted ONLY on physical (and fail-forward) outcomes with witnesses.
  Broad social/notorious-act coverage would need widening the deed-mint sites,
  which is out of the current scaffold — a later slice, flagged for George.

## Slice plan (thin vertical slices, build-order law)

**Slice 1 (SAFE, zero open questions, autonomous now): seeds become talk.**
Consume the authored-but-dead `rumor_seeds`. When the player does an ambient
information action that hits the taproom/board rumor path (the existing
`_research_ambient` / board-observation surface), surface ONE world rumor drawn
deterministically from this world's `rumor_seeds`, as a low-strength
`method="rumor"` Inquiry claim (atmospheric, weight 35, decays). Deterministic
pick (hash-seeded off actor + world_time + turn, dice discipline), one per
surfacing, no dumping. Notoriety just weights the pick (louder seeds surface
more often). This is pure plumbing that makes the authored Quarryman / Hollow
Tor / Rold Tanner rumors actually reach the player, and it establishes the
"rumor rides the InquiryClaim surface" path every later slice reuses. No deed
bridge, no distance math, no renown write, no distortion. CODE only, deploys to
frozen worlds (the seeds are in their frozen content).

**Slice 2 (after George's steer): deeds become rumors (the roadmap's heart).**
Bridge `deed_recorded` -> rumor claims that spread by distance (BFS over
`carriage_days`) and time (elapsed world-minutes), scaled by deed `notoriety`.
Uses `derived_from_claim_id` / `hop_count`. Carries the OPEN QUESTION of whether
this also FEEDS `renown` (I lean yes) and the freshness window value.

**Slice 3 (after Slice 2): distortion + renown.** Bounded deterministic
distortion as rumors travel; wire notoriety -> renown so the scope I built gets
an honest writer. Possibly widen deed-mint sites for social/notorious acts
(flagged: out of current scaffold).

Slice 1 is the only slice with no design ambiguity, so it is the only one I run
autonomously now. Slices 2 and 3 wait for George's answers to the open questions
above.

## Slice 1 status + a reachability finding (2026-07-15)
Slice 1 is BUILT, gated, and merged (seeds surface on the subjectless ambient
RESEARCH path). A live parser probe then showed a reachability gap: the natural
utterances a player types to fish for gossip parse as OBSERVATION or DIALOGUE,
not research:
  "listen for the town gossip"   -> observation (no target)
  "keep an ear out for rumors"   -> observation (no target)
  "listen to the taproom talk"   -> observation (no target)
  "ask around town for news"     -> dialogue   (no target)
  "what's the word around here"  -> dialogue   (no target)
So live, Slice 1 seeds will surface only on an explicit "research the rumours"
action until the surface is broadened. The engine is correct; the surface is
narrow.

**Slice 1b (proposed, needs George's game-feel steer):** broaden the seed
surface to an untargeted INFORMATION-SEEK observation (reuse the existing
`_INFO_SEEK_RE`; "listen for gossip"/"keep an ear out"), and optionally a
subjectless information-seek dialogue to the room. The real decision is
FREQUENCY/FEEL, which is George's call, not a pure-plumbing choice:
  - How often should ambient rumours surface? Every qualifying action reads as
    spam; never reads as a dead world. Recommend a soft cadence (e.g. surface a
    fresh seed at most once per N ambient info-seeks, or bias toward unheard
    seeds) so the world feels alive without nagging.
  - Which actions count as "fishing for talk" vs just looking? An untargeted
    look ("look around") should stay atmospheric; only an explicit info-seek
    ("listen for gossip") should surface a rumour.
Hold for George.
