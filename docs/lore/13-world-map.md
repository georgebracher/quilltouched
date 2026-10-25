# 13 — The World Map (the initial base map)

Scope: the authored base map George asked for (`content/canon/decisions-resolved.md` decision 6 + FINAL CONFIRM). The realm/kingdom shape, its regions and seats, Harrowdown's place in it, distances in carriage-days, and the frontier where bottomless expansion happens. Machine companion: `content/canon/map.yaml` (the surface worldgen reads). **v2 — CANON LOCKED 2026-07-14 (George). The base, not the whole; more regions appear later by design.**

## Scale (CONFIRMED — canon locked 2026-07-14)

The world is **one kingdom inside a larger, unmapped world**, not a single self-contained realm. The kingdom (**Aldreth**) is the political container: a crown, a capital, provinces, seats, and towns. **Harrowdown is one small vale**, in one province (the **Lundmarch**, seat at Severwick), near the kingdom's wild inland edge. Past the kingdom's borders in every direction is frontier and then blank map — other kingdoms, seas, wastes, the burned lands, and wherever the summonings pull souls from. None of that is authored. It is where worldgen grows.

This serves three things already in canon: the Codex map that goes "blank past the ridge" (roadmap §3), dragons being near-single-digit in the *known* world (`content/canon/bestiary.yaml`), and the bottomless anchor (`anchor.bottomless_core`) — a world that can always be larger than the map.

**The settlement base is exactly 1 capital + 1 large city + 5 towns, and everything past those 7 is frontier-open.** Capital = **Aldcaster**. Large city = **Severwick** (the Lundmarch seat). Five towns = **Harrowdown, Dunmere, Cranholt, Larkhythe, Milbury** (the last two authored this pass). The Cindermarch is a burned, unpeopled province — a lore node, not one of the 7 settlements.

**Names are APPROVED (George):** Aldreth, Aldcaster, the Lundmarch, the Cindermarch, the Fellmarch, the Meres. The existing names are locked and untouched: Harrowdown, Dunmere, Cranholt, Severwick, the River Lund, Hollow Tor, Redcliff Scar, Sedge Ford, Stanwick.

## The shape in one line

The vale is a hinge. South and downriver, the land gets civilized — Severwick the seat, then the far capital. North and uphill, it gets wild — the high country, then the burned province where dragons were fought. Harrowdown sits between the two, on the chalk downs where the Lund runs.

## The regions

**The kingdom of Aldreth** — medieval, low-magic, run on wool, tallow, and the written record. Held together by the crown, the five guilds, and the churches.

**The Lundmarch** (province; seat Severwick) — the chalk-and-river province the vale belongs to. Wool towns, farm shires, and fen edges, the Lund running south to the seat. The kingdom's inland edge; past its upland rim the settled map thins to frontier. Holds the kingdom's **large city and all five of its towns** (only the capital lies outside it):

- **Harrowdown** *(town)* — the seed region and the one you play. A backwater vale on the downs; apex threat a wyvern (the Quarryman), and still no dragon. Landmarks already canon: Hollow Tor and its barrow field, Redcliff Scar and the closed quarry, Sedge Ford, the River Lund.
- **Dunmere** *(town)* — fen-edge wool town, two days west over Sedge Ford. Chronic rat trouble, standing bounties. The province's western edge. (Stub — named and placed, interior authored in its own sprint, per `11-travel-network.md`.)
- **Cranholt** *(town)* — timber holt over the downs, three days northeast. Snowed off part of winter. The last settled step before the high country. (Stub.)
- **Larkhythe** *(town — authored this pass)* — the South Road's halfway town, **two days south of Harrowdown** down the Lund. A river wool-staple: vale fleece is weighed, baled, and barged on to Severwick here, so it runs on wharves, weigh-houses, and the Merchants' Guild scales. The Stanwick bridge — the last chokepoint before the seat — is a day further down its road, so Larkhythe → Severwick is **two more days** (Harrowdown → Severwick stays four). (Stub.)
- **Milbury** *(town — authored this pass)* — corn-and-cheese country in the Lund's river-meadows, **two days west of Larkhythe** off the South Road. Watermills, dairy, and the settled heartland's **steadfolk** (`people.halfling_kin`) — the demihuman town, so long-intermarried most families are some part steadfolk without making anything of it, and the commonest seat of mixed heritage (`people.mixed_heritage`). (Stub.)
- **Severwick** *(the large city)* — the seat, four days south down the Lund (through Larkhythe and the Stanwick bridge). River port, crown mint, cathedral, guild seat, and the **monastery record-halls** that hold the kingdom's wyvern-hunt archives — the records **carried south out of the burned north**. The direction the vale means when it says "civilization." (Stub.)

**Aldcaster** (the capital; far south) — the kingdom's heart, a season away by the time a Harrowdown deed arrives as a ballad with the names wrong. Seat of the crown, the great cathedral, and the **war-colleges** — the only attributed source of battle-magic (`power.battle_magic`, unverified from the vale). Where the Demon Lord legend is maintained hardest (`08-demon-lord-dossier.md`) and the summoning annals are controlled. Confirmed to exist; its interior and exact distance are deferred to its own sprint.

**The Cindermarch** (the burned province; **far north** — confirmed) — a province the fire took generations ago, burned by the **Cinder Dam** (the Mother Dragon; see below). Dragon-scorched, unpeopled, a season north past the high country. The deepest dragon and wyvern lore lives here on-site (peak intel sits near where the thing happened, roadmap §3); the archive at Severwick is only the safe copy **carried south**. This is the drama of distance made into a place — the best answers are the furthest and most dangerous to reach. It exists in canon as a lore node; its interior is dangerous frontier, not a walkable town set. It is also the **endgame ground**: the Cinder Dam lairs in its deep north, placed but distant, her approach sealed by season and by her own brood.

## The frontier (where the map is open)

Three edges are unauthored on purpose. Worldgen expands only outward from them (`content/canon/map.yaml` `frontier_rule`), never between two authored places.

- **The Fellmarch** — the high country north and uphill, past Cranholt and Redcliff, where the downs become crag and mountain. **Draconic country**: the ladder rises with the ground (wyvern → drake → dragon → the burned north beyond). It is seeded with the **Cinder Dam's scattered young** — the Screel (a young wyvern of the high passes) and the Corrie Drake (a drakeling in a deep corrie), each a rung below her, along with the vale's own Quarryman, the brood-member that reached the settled edge. Also the **orc-kin borderland** (`people.orc_kin`, a settled people distinct from the feral warband orcs of `bestiary.orc`). This is the primary bottomless-expansion direction — the player climbs the ladder here as they earn the altitude, up toward the placed Dam in the burned north beyond. The Redcliff quarry and its wyvern are the vale's first inch of it.
- **The Meres** — wet country west past Dunmere: fen, bog, and drowned ground toward an unmapped coast. Blotted camps and the Fen Kalendar reading.
- **The beyond** — everything past the borders and the Codex map's edge. Deliberately blank. The outermost frontier: other kingdoms, seas, the source of the summonings, wherever dragons flee *to*.

## The Mother Dragon — the placed apex (the "top")

Dragons are not just canon-existent any more: one living apex is **placed** on the map. The **Cinder Dam** — the Mother Dragon (`bestiary.yaml` `mother_dragon`, `creature.cindermarch.cinder_dam`) — is the singular calamity-class living dragon, seated in a mountain-root in the deep north of the **Cindermarch**, the province she burned generations ago. She is the source the frontier's lesser draconic descend from: over generations her brood has spread *down* the high country — the Fellmarch wyverns and drakes, the burned-approach drakeling, and the vale's own Quarryman, the one that reached the settled edge. Each is a rung below her; killing her young never touches her band.

She is **the top the whole ladder climbs toward** — "I'll try and get the top." She sits at the head of the escalation hook (`beyond_the_ladder`): while she stands, the tier above dragons stays shut; if she is genuinely felled in play, what *she* fled becomes the world's next threat. Placed but distant — the vale never feels her daily; the endgame does. Her approach is sealed by season and by her own brood, not by a lock.

## Distances (carriage-days; source `11-travel-network.md`, unchanged)

| From Harrowdown | To | Days | Road | Chokepoint |
|---|---|---|---|---|
| west | Dunmere | 2 | the Cairn Road | Sedge Ford |
| northeast | Cranholt | 3 | the Drove Road | high downs, weather |
| south | Larkhythe | 2 | the South Road (first leg) | the Lund market |
| south | Severwick (the large city) | 4 | the South Road (via Larkhythe) | the Lund bridge at Stanwick |
| south, then west | Milbury | 4 (2 to Larkhythe + 2) | South Road, then the meadow lanes | the meadow lanes |
| northeast | Redcliff / the Quarryman | — | the Quarry Track | dead end (the wyvern) |
| south, then further | the capital (Aldcaster) | ~a season by rumor | downriver past Severwick | deferred |
| north, past the high country | the Cindermarch (& the Cinder Dam) | ~a season | no safe road | frontier |

Rumor travels at the same speed the carts do: a deed is fact in Dunmere in two days, a story in Severwick in four, and a ballad with the names wrong in the capital in a season. Distance is the distortion engine, and the price of a good answer.

## The layout (north up)

```
                        ~~~  THE BURNED NORTH  ~~~
                    region.cindermarch — the Cinder Province
             dragon-scorched ruin · deepest dragon/wyvern lore (carried south)
        >>> THE CINDER DAM — the Mother Dragon, placed living apex (sealed approach) <<<
                 a season north, past the high country · mostly blank
                                     ^  (no safe road; frontier)
                                     |
                 ========   THE FELLMARCH (high country)   ========
                 crag · fell · mountain — DRACONIC frontier
                 the Dam's scattered brood: the Screel, the Corrie Drake
                 wyvern -> drake -> dragon · orc-kin borderland
                 FRONTIER-OPEN: worldgen climbs the ladder here
                                     ^
                          Redcliff Scar / the Quarryman
                        (Quarry Track — dead end, the wyvern)
                                     |
   THE MERES                        |  Quarry Track
 (fen frontier,          Cranholt  (*)  3d NE  (Drove Road, over the downs)
  west, blank)                 \      |
        \                       \     |
   Dunmere (*)---- 2d W ----[ HARROWDOWN ]  <-- you are here
   fen-edge          Cairn Road  |   chalk-down vale on the River Lund
   wool town        (Sedge Ford) |   apex = a wyvern, and still no dragon
                                 |  South Road (down the Lund)
                                 |  2d S
                                 v
          Milbury (*)---2d W---Larkhythe (*)
          steadfolk farm town   river wool-staple town
          mills · mixed-kin     |  South Road (Stanwick bridge)
                                |  2d S   [Harrowdown -> Severwick = 4d total]
                                v
                            Severwick (*)
             THE LARGE CITY & SEAT of the Lundmarch province
              river port · crown mint · cathedral · guild seat
              MONASTERY RECORD-HALLS = wyvern-hunt archives (safe copy, carried south)
                                 |
                                 |  downriver, ~weeks
                                 v
                        ~~~  THE HEARTLAND (south)  ~~~
                            region.aldcaster
                  THE CAPITAL & CROWN SEAT — a season by ballad
              war-colleges (battle-magic) · crown chronicle · summoning annals
                                 |
                       (blank past the heartland: other kingdoms,
                        the sea, the unmapped world)
```

`(*)` = named neighbour, placed and connected, interior authored in its own sprint.

## Resolved (canon locked 2026-07-14, George)

Nothing on this map is open any more. George's final confirms are applied:

- **Scale:** CONFIRMED — one kingdom (Aldreth) inside a larger unmapped world, sized to exactly **1 capital + 1 large city + 5 towns + frontier-open beyond**.
- **Names:** APPROVED — Aldreth (kingdom), Aldcaster (capital), the Lundmarch (province), the Cindermarch (burned province), the Fellmarch (high country), the Meres (fen frontier).
- **Two new towns:** authored — **Larkhythe** (South Road river wool-staple, 2d south of Harrowdown) and **Milbury** (steadfolk farm-and-mill town, 2d west of Larkhythe).
- **Burned province:** CONFIRMED far **north**, past the high country (dragon country = mountains), records carried **south** to Severwick.
- **Regional sects:** a first-class, repeatable pattern — each region may carry its own reading of the one true Quill (`content/canon/map.yaml` regions carry an optional `sect:` field; `cosmology-powers.yaml` `quill_worship_regional.pattern`). Crown's Hand / Scored Page / Fen Kalendar are the seeded examples.
- **Living dragon placement:** RESOLVED — the **Cinder Dam** (the Mother Dragon) is placed in the deep north of the Cindermarch, with her scattered young across the Fellmarch/frontier. She is the endgame apex; felling her opens `beyond_the_ladder`.

## Binding notes

- Existing distances and names are unchanged; this map references them, it does not rewrite them. The locked region file (`content/world/harrowdown.yaml`) and the travel doc (`11-travel-network.md`) stay authoritative for what they already state.
- Worldgen grows the map only outward from a frontier-open edge, never between two authored places, and every generated region runs the consistency-contract fit-check (`content/canon/consistency-contract.yaml`).
- The map is a KNOWN sheet like everything else: a vale's idea of the world is fallible and gets more wrong with distance. What is drawn here is the true geography; what a character believes about it is earned.
