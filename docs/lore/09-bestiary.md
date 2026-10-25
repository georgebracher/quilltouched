# 09 — Bestiary

Scope: the monster ladder slime→dragon on the absolute (never level-scaled) world scale — threat bands, institutional letter-grade KNOWN vs true sheets, and the free common-sense tier entries everyone knows (roadmap §3.3, playbook §4 ADOPT). **v1 (B1, Sprint 1): the Harrowdown regional roster.** Later sprints extend the ladder upward and outward. True sheets live in `content/world/harrowdown.yaml`; TRUE blocks below are engine/authoring context only and never reach the narrator.

## How to read this file

Three layers per creature, matching the game's knowledge model:

- **Common sense** — free category knowledge. Every adult in the region knows it; the narrator may use it without provenance.
- **Guild dossier** — the hall's letter-grade KNOWN. Institutional, sourced, and capable of being wrong in causal, reproducible ways.
- **TRUE** — what research can surface. Engine and authoring only.

The absolute scale runs slime to dragon. No dragon appears in this file because no dragon appears in this region; the vale's apex is a wyvern, and the gap between the two is the point. Common sense knows the gap: *a wyvern is an apex beast and still no dragon* is a vale proverb, usually delivered to someone talking too loudly in a tavern.

## Regional roster

| Entity | Guild grade (KNOWN) | Threat band (TRUE) |
|---|---|---|
| `creature.harrowdown.ditch_slime` | F | 1 |
| `creature.harrowdown.cairn_rat` | F | 2 |
| `creature.harrowdown.chalk_adder` | E | 3 |
| `creature.harrowdown.downland_wolf` | D | 5 |
| `creature.harrowdown.barrow_wight` | C | 7 |
| `creature.harrowdown.quarryman` | A (warrant) | 14 |

Letter grades are the guild's institutional read of bands it cannot measure directly. The two columns agree here better than they do in most regions, because most of the vale's monsters are boring. The two entries where the dossier is wrong are marked.

### Ditch slime — grade F

**Common sense:** wet cellars, ditches, bridge-shadow. A walking pace outruns one. Ruins leather, rope, and sleeping drunks. Salt kills small ones.
**Guild dossier:** "Nuisance class. Clearance posting only. Verify the cellar after rain." Sourced from a century of tail-counts; sound.
**TRUE:** nothing research adds. Some things are what they look like.

### Cairn rat — grade F

**Common sense:** big grey rats out of the barrows, granary raiders in autumn. Bites go bad more often than they should.
**Guild dossier:** "F, pack vermin. Bite-rot is dirt in the wound; wash and poultice." Attributed to a Severwick healer's letter, forty years old.
**TRUE:** the bite-rot is not dirt. Cairn rats den in barrow soil and carry something of what the barrows hold; a wound that weeps past three days is starting a smaller, slower version of what a wight's grip does. The healer's letter is the dossier's error: **sample contamination** — the rats she examined were common granary rats caught on Wool Row, never barrow-denned stock.

### Chalk adder — grade E

**Common sense:** pale snake on pale paths, invisible until it moves. Kills sheep and children; an adult has a day to reach a healer. Does not chase.
**Guild dossier:** "E. Venomous, non-aggressive. Boot leather defeats a strike below the knee." Sound, and repeated to every F plate at registration.
**TRUE:** the day of grace shortens to hours if the bitten keeps walking. The guild knows; the phrasing on the dossier predates the evidence and nobody has resat the entry.

### Downland wolf — grade D

**Common sense:** packs of four to eight on the high downs. Tests before it commits; noise and fire end most encounters. Winter changes the arithmetic.
**Guild dossier:** "D. Pack predator. **Will not cross running water.**" The water claim is the dossier's error: an **inherited note missing its qualifier**. It was copied from a Dunmere fen-pack dossier, where it holds in flood season. Downland packs cross the Lund at Sedge Ford in the dry months, and two dead shepherds' families can date exactly when trusting the note stopped being safe.
**TRUE:** vale packs are led by the oldest female, and a pack that loses her scatters within a season. The wolf posting on the Harrowdown board is priced for six wolves. It is one pack, and it has one keystone.

### Barrow wight — grade C

**Common sense:** something dead walks the barrow field on Hollow Tor. Shepherds will not graze the tor; carters do not overnight below it. People who go into barrows after grave-goods get funerals.
**Guild dossier:** "C. Revenant class, bound ground. Do not engage after dark. Last verified encounter: 34 years ago, one survivor." Honest about its own age — the guild has no fresh data because nobody has taken the posting in a generation.
**TRUE:** the wight cannot leave sight of its own barrow, and its strength waxes hard during the six nights centered on the winter Quarterday (`02-universe-laws.md`, Hollow Tor). Grave-goods in the outer barrows are real and unlooted. The binding radius is the researchable fact that turns a C-grade horror into a solvable problem, and nobody in the vale knows it.

### The Quarryman — grade A, standing warrant

**Common sense:** the wyvern that closed the Redcliff quarry nine years ago. Takes oxen and horses off the high pasture. Has killed every party sent up the track. Six went up with Jorun Pike; two came down (`npc.harrowdown.jorun_pike` — ask him once, he will answer once).
**Guild dossier:** "A-threat. Warrant requires Severwick seal. **Roosts the north face of Redcliff Scar.** Strikes at dawn from the sun-side." Provenance: the survivors' debrief, nine years old. The roost line is the dossier's error: **outdated info.** Quarry blasting scarred the north face before the guild ever wrote the entry; it roosts the south overhang now, and a party staging off the dossier would put the scar between themselves and their retreat.
**TRUE:** threat band 14 — HOPELESS for any fresh plate, and still HOPELESS for a C-plate veteran. Research can move the fight, never erase it: the south overhang, the daylight pattern (it hunts when the thermals rise off the chalk, weather-bound, predictable to within an hour by anyone who watches for a week), and what it does with what it takes. Nobody has watched for a week and lived to file the notes. The monastery record-halls at Severwick hold the kingdom's wyvern-hunt archives; that lead is real (`11-travel-network.md`).

## Grading note

The guild grades what it can afford to verify. F through D entries rest on decades of cheap evidence and are usually sound. C and up rest on survivor testimony, old letters, and courage the hall cannot requisition — which is exactly where the KNOWN sheet and the true sheet drift apart, and exactly where a careful reader of dossiers earns a living.

## Wrong-intel plants → scope error profiles (Sprint 3, B)

The three marked dossier errors above are now machine-consumable, deterministic **error profiles** authored as inline `knowledge_scope` errors on `prop.harrowdown.guild_board` in `content/world/harrowdown.yaml` (reconciled from Team B's `harrowdown-scopes.yaml`, Sprint 3 wave 1), so failed research yields the AUTHORED wrong answer, not a generic one:

| Subject | Wrong dossier value | Mechanism | Corrected by |
|---|---|---|---|
| `creature.harrowdown.cairn_rat` | "bite-rot is dirt in the wound" | sample contamination | Toller Whin (deep research) / firsthand |
| `creature.harrowdown.downland_wolf` | "will not cross running water" | inherited note missing its qualifier | Toller Whin (deep research) / firsthand |
| `creature.harrowdown.quarryman` | "roosts the north face" | outdated | Toller Whin (deep research) / firsthand / the Severwick lead |

The chalk adder's unrevised "day of grace" phrasing is carried as a fourth, minor `outdated` profile. The confident-WRONG value is narrator-safe KNOWN-layer content (the ballads-lie); the truth is `never_narrator` until earned as a claim. Each creature's **surface bands vs deep truths** (the researchable facts that re-tier a fight — the Quarryman's south roost and cache-ledge weak point, the wight's binding radius) are folded into the sources' inline `knowledge_scope` reveals in `content/world/harrowdown.yaml`: the guild board carries the surface/band tiers (0–2); Toller Whin carries the deep truths and the `weak_point` reveals. (The resolver caps single-roll research depth at tier 2, so B's tier-3/4 lore-ladder truths are authored at reachable tier-2 reveals — see `tests/fixtures/scope-world.yaml`.) The vale's new lay research site, **Toller Whin** (`npc.harrowdown.toller_whin`, at the chapel), is where the guild's tier-2 errors get corrected — and carries its own `transcription_error` plant on the burned pre-fire rolls.
