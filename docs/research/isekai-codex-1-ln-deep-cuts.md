# Everquill: Light-Novel/Web-Novel Deep-Cut Mechanics Report

## Core design conclusion

The strongest source-material lesson is not “add more stats.” It is to make knowledge, institutions, production capacity, and time into playable resources.

Everquill should preserve four boundaries:

1. **TRUE state remains deterministic.** The dice/rules engine owns stats, component laws, faction motives, recipes, clocks, and consequences.
2. **KNOWN state is character-specific and fallible.** Appraisals, rumors, reports, inherited journals, and research results create claims—not retroactive truth.
3. **Capability comes from dependencies.** A remembered idea is worthless without the correct artisan, materials, facility, legal permission, time, and validated procedure.
4. **Paid time skips accelerate waiting, never truth or success.** Skipping six hours must advance hostile clocks, prices, travel, production, and disasters by the same six hours. It must not improve a roll, erase consequences, or convert bad intel into good intel.

---

## Ascendance of a Bookworm: economy, guilds, and craft as dependency graphs

### 1. Innovation is a supply-chain quest, not a recipe unlock — **Steal directly**

**What it is.** Myne remembers the concept of paper and printing, but that knowledge does not conjure an industry. Plant fibers must be identified and processed; suitable ink must be developed because existing parchment ink damages plant paper; tools must be commissioned; presses require cooperation between carpenters, smiths, designers, merchants, and workshop managers. Movable type is bottlenecked by exceptional metalworking precision, while wax stencils depend on paper thin and strong enough to survive the process. Even colored inks behave unpredictably because trace mana in ingredients changes their results, forcing empirical documentation rather than deduction from first principles. [The printing-system summary documents the progression from woodblock to stencils, presses, specialized inks, and precision type.](https://ascendance-of-a-bookworm.fandom.com/wiki/Printing)

**Why it works in fiction.** Earth knowledge gives Myne direction, not omnipotence. Every breakthrough exposes another missing profession, incompatible material, entrenched interest, or scaling problem. Progress therefore generates characters, debts, negotiations, and new vulnerabilities.

**Everquill implementation.** Represent every major feat as a hidden dependency graph:

`Concept → tested procedure → specialist → tooling → input quality → facility → legal access → production time`

A free-text action such as “make printing ink from soot and oil” identifies an attempted procedure. The deterministic engine checks actual ingredients, proportions, local mana characteristics, equipment, operator competence, and prior validated knowledge.

Research outcomes should write claims into KNOWN intel:

- **10+**: correct relationship plus useful operating range.
- **7–9**: correct core principle but an omitted dependency, narrow safe range, or local-only result.
- **6−**: a plausible, confidently recorded false rule, ideally derived from the actual failed conditions.

Crucially, repeating the same bad experiment under the same conditions should reproduce the same misleading evidence. Wrong intel should be causal, not random LLM improvisation.

### 2. Guilds govern market entry, standards, and political permission — **Steal directly**

**What it is.** Ehrenfest’s guilds are legal and regulatory institutions, not decorative quest hubs. The Merchant’s Guild controls commercial registration, apprenticeships, shop openings, punishment, and inter-guild disputes. When plant paper threatens parchment, the eventual compromise reserves official contracts for parchment while allowing plant paper into other markets. New industries require fees, paperwork, guild formation, and sometimes territorial authorization. [The guild overview describes their legal status and the Merchant’s Guild’s jurisdiction.](https://ascendance-of-a-bookworm.fandom.com/wiki/Guilds) [The Gilberta Company history records the parchment/plant-paper market compromise and sale of production rights.](https://ascendance-of-a-bookworm.fandom.com/wiki/Gilberta_Company)

**Why it works in fiction.** A superior product does not automatically win. Incumbents possess law, standards, distribution, trained labor, and political relationships. Innovation creates bargaining problems rather than merely increasing a crafting number.

**Everquill implementation.** Give every settlement a regulatory map:

- who may trade;
- which guild certifies which product;
- what materials are reserved for sacred, military, or official uses;
- which monopolies are formal, customary, or criminal;
- who adjudicates violations;
- which rules apply only inside a city, duchy, temple domain, or trade league.

A new invention should alter prices and faction behavior before it becomes profitable. Players could license it, sell the procedure, conceal it, form a rival guild, bribe inspectors, relocate production, persuade an incumbent to absorb it, or manufacture illegally. These are different routes through the same component-law objective.

### 3. Commercial identity and trust are infrastructure — **Adapt**

**What it is.** Guild cards establish membership, hold funds, transfer money, and open restricted areas. They are bound to individuals through blood registration. Apprenticeships and temporary child registrations determine who may legally participate in commerce. [The guild-card system combines identification, access control, registration, and payment.](https://ascendance-of-a-bookworm.fandom.com/wiki/Guild_Card)

**Why it works in fiction.** The economy depends on legibility: institutions must know who is liable, who guarantees an apprentice, and which transactions they will enforce.

**Everquill implementation.** Avoid a universal magical debit card, but preserve the institutional function. Use guild seals, witness chains, letters of credit, blood marks, temple records, or noble guarantees. Registration should grant:

- enforceable contracts;
- safer storage and payments;
- wholesale prices;
- access to restricted auctions and facilities;
- reputational recourse after fraud.

The cost is traceability, dues, taxation, obligations, and vulnerability to blacklisting. An heir may inherit assets but not automatically inherit every personal guarantee.

### 4. Contracts have jurisdiction and dangerous literalism — **Steal, with strict scope**

**What it is.** Bookworm’s magical contracts use special materials and signatures, can carry lethal enforcement, may be limited by territorial jurisdiction, and can be altered or nullified only through defined authority. Merchant-guild copies can update after changes such as a signatory’s death. [The contract-magic summary distinguishes materials, signatories, copies, enforcement, and archducal authority.](https://ascendance-of-a-bookworm.fandom.com/wiki/Commoner_Magic_Utilities)

**Why it works in fiction.** Contract power does not eliminate politics. It relocates politics into wording, jurisdiction, custody, authority, and access to the materials required to create or void an agreement.

**Everquill implementation.** Contracts should never be resolved by the narrator deciding what sounds dramatic. Use a deterministic clause grammar with explicit:

- parties;
- consideration;
- prohibited/required acts;
- geographic scope;
- duration;
- enforcement;
- termination;
- exceptions;
- witnesses and required components.

The player may phrase the agreement freely, but the engine compiles it into visible clauses before signature. Ambiguity can remain only where the rules deliberately support it.

---

## Overlord: guild bases, authored loyalty, and irreplaceable capital

### 5. A guild base is accumulated institutional capital — **Steal for dynastic estates**

**What it is.** Nazarick is not merely a large home. Its floors, transit points, defenses, treasury, traps, automatic inhabitants, and custom NPC allocation constitute a captured and extensively rebuilt dungeon. Custom NPC creation is constrained by a base-level budget—Nazarick received 2,750 levels after its first-clear bonus—forcing tradeoffs between a few supreme guardians, specialized lower-level servants, and noncombat functions. [Nazarick’s layout and NPC-data budget are summarized here.](https://overlordmaruyama.fandom.com/wiki/Great_Tomb_of_Nazarick)

**Why it works in fiction.** The base externalizes the guild’s history. Its power comes from thousands of prior decisions, contributions from absent friends, accumulated loot, and specialized infrastructure. Losing part of it means losing history, not just hit points.

**Everquill implementation.** Make the player’s persistent estate the real cross-heir progression layer:

- archives and proven recipes;
- vaults and relic storage;
- workshops;
- trained retainers;
- wards and escape routes;
- political charters;
- family reputation;
- memorials that influence later heirs;
- unresolved liabilities.

Upgrades should consume space, upkeep, scarce specialists, and construction time. Estates should be raidable, infiltratable, confiscatable, or politically constrained. They must not be an invulnerable account-wide lobby.

### 6. NPC loyalty has multiple authorities and inherited interpretations — **Steal directly**

**What it is.** Nazarick’s custom NPCs embody their written settings and aspects of their creators. Their loyalty hierarchy privileges their personal creator, then the guildmaster, then other guild members; creator relationships and incidental statements become morally significant after the transition to reality. [The NPC overview notes the inherited nature and importance of creators’ words.](https://overlordmaruyama.fandom.com/wiki/Non-Playable_Character) [The stated loyalty hierarchy is creator, Momonga, then the remaining guild members.](https://overlordmaruyama.fandom.com/wiki/Sorcerer_Kingdom?page=1)

**Why it works in fiction.** “Loyal” is not a single scalar. A servant can sincerely worship the organization while interpreting its doctrine catastrophically, privileging an absent founder, or mistaking casual remarks for sacred instructions.

**Everquill implementation.** Every important retainer should have hidden TRUE fields such as:

- loyalty target;
- loyalty strength;
- doctrine;
- taboo;
- personal ambition;
- interpretation style;
- relationship with the current heir;
- relationship with the dynasty as an institution.

KNOWN intel might merely say “utterly loyal.” An heir inherits office and command rights, but not necessarily affection or ideological agreement. This produces succession drama without arbitrary betrayal.

### 7. Powerful legacy items are operationally irreplaceable — **Steal directly**

**What it is.** Ainz possesses YGGDRASIL currency, consumables, data crystals, cash-shop items, World Items, and equipment whose manufacture may be impossible in the New World. That uncertainty makes testing, substitution research, and conservation strategically important. Some World Items can bypass ordinary resurrection, and the most extreme items are effectively singular strategic assets. [World Items include effects that ordinary resurrection and cash items cannot reverse.](https://overlordmaruyama.fandom.com/wiki/World_Item)

**Why it works in fiction.** Overwhelming power remains tense because using an asset reveals information, spends a finite reserve, or risks losing something made by an absent guildmate. Scarcity converts “overpowered inventory” into strategic decision-making.

**Everquill implementation.**

- Give major relics provenance and a finite known count.
- Make identification incomplete: players may know an effect without knowing charges, side effects, counters, or reproducibility.
- Require destructive testing for some properties.
- Allow local substitutes that reproduce only part of an old artifact’s function.
- Let heirs inherit depleted inventories exactly as previous characters left them.

Never quietly refill “legendary” resources through routine daily rewards.

### 8. Resurrection is category-specific, not a universal convenience — **Adapt narrowly**

**What it is.** Overlord distinguishes normal resurrection, guild-base restoration of custom NPCs using system resources, and effects that can erase entities beyond ordinary recovery.

**Why it works in fiction.** Death rules follow ontology. A constructed guild guardian, native human, player entity, summoned creature, and World-Item victim are not interchangeable.

**Everquill implementation.** Preserve permanent player-character death. If restoration exists, it should apply only to explicitly defined categories—bound guardians, revenants, homunculi—and require the correct components and surviving anchor. Never offer generic gold resurrection. This reinforces Everquill’s component-law premise while allowing rare recovery systems that do not become plot armor.

---

## Log Horizon: contracts, territorial ownership, and emergent production

### 9. Contract magic can create a new rule only through extreme prerequisites — **Highest-priority steal**

**What it is.** Shiroe’s Contract Art Ceremony combines a high-level Scribe subclass, magical theory, enormous MP, consent, and Phantasmal-class paper and ink to formulate magic that did not previously exist. Rundelhaus’s contract changes his category to Adventurer, giving him access to cathedral rebirth. [The contract’s material and skill requirements are detailed here.](https://log-horizon.fandom.com/wiki/Magic_Contract)

**Why it works in fiction.** The miracle is earned through converging systems: scholarship, production, social agreement, rare materials, class expertise, and a narrow moment of opportunity. It feels like discovering a legal exploit in reality rather than receiving a new spell.

**Everquill implementation.** This is the ideal model for component-law feats. “Resurrect the queen” should expand into fixed requirements such as:

- metaphysical category and valid target;
- intact or substituted soul-anchor;
- named components;
- qualified officiant;
- exact location/time;
- consent or lawful proxy;
- countervailing cost;
- validated wording.

Every component may be obtained by any route—trade, theft, diplomacy, exploration, manufacture, inheritance—but the law itself is never negotiated by the narrator. Wrong research may misidentify one component or omit a constraint; the underlying rule remains fixed.

### 10. Ownership of a zone grants rule-setting power — **Steal with counterweights**

**What it is.** Purchasable zones turn property ownership into governance. Shiroe’s acquisition of the Guild Building lets him deny abusive guilds access to essential guild functions. Elsewhere, cathedral ownership creates leverage over revival infrastructure. Akiba’s public facilities also require upkeep, supported through fees and taxation. [Akiba’s ownership and upkeep economy is summarized here.](https://log-horizon.fandom.com/wiki/Akiba) [Cathedral ownership demonstrates how property can control a supposedly neutral system.](https://log-horizon.fandom.com/wiki/Cathedral)

**Why it works in fiction.** Political authority emerges from control over system-critical infrastructure rather than a crown alone.

**Everquill implementation.** Let ownership of bridges, ferries, shrines, mines, archives, guildhalls, wards, and caravanserais confer specific verbs:

- charge tariffs;
- restrict entry;
- prioritize production;
- issue licenses;
- maintain or neglect defenses;
- control access to records or rituals.

Counterweights should include upkeep, local legitimacy, sabotage, rival jurisdictions, labor dependence, and seizure. Buying a place must not confer absolute control over everyone inside it.

### 11. Manual practice plus class competence exceeds menu recipes — **Steal directly**

**What it is.** After the Catastrophe, menu-created food is nutritionally functional but tasteless. Flavorful food requires both real manual cooking and the Chef subclass at sufficient level. Ingredients, tools, fermentation time, and real knowledge matter again. [The Chef mechanics distinguish menu production from manual production and adjacent supply professions.](https://log-horizon.fandom.com/wiki/Chef)

**Why it works in fiction.** The world honors both embodied knowledge and formal system capability. Neither an Earth recipe nor a high skill rating is sufficient alone.

**Everquill implementation.** Free-text actions should support “overskill” discoveries when players combine:

- correct physical procedure;
- sufficient character competence;
- valid materials;
- appropriate environment;
- repeated evidence.

The engine, not the LLM, validates the combination. Successful discoveries become durable procedures that can be taught, licensed, stolen, or distorted through bad transmission.

### 12. Death can damage continuity without becoming a reload — **Transform for the heir system**

**What it is.** Log Horizon’s Adventurers revive at cathedrals, but revival consumes experience and memories; native People of the Land usually die permanently. [Spirit Theory ties reconstruction to information loss.](https://log-horizon.fandom.com/wiki/Spirit_Theory) Volume 4 explicitly centers the revelation that death costs memories. [The publisher-facing volume summary records that stake.](https://www.goodreads.com/book/show/50626393-log-horizon-vol-4-light-novel)

**Why it works in fiction.** Resurrection preserves plot continuity while slowly eroding identity and accumulated personal history.

**Everquill implementation.** Do not resurrect the player. Instead, apply the same continuity cost to inheritance:

- private memories die with the character;
- written KNOWN intel survives, including errors;
- unrecorded relationships become hearsay;
- retainers remember the predecessor through their own biases;
- damaged journals may lose provenance or qualifiers;
- the heir inherits assets and consequences, not omniscience.

This makes documentation a meaningful action and gives research notes dangerous longevity.

---

## The Rising of the Shield Hero: catastrophe clocks, asymmetric knowledge, and distrust economics

### 13. Waves are scheduled disasters whose failure changes the world — **Highest-priority steal**

**What it is.** Dragon Hourglasses forecast local Waves and register heroes for deployment. The deeper LN system links Waves to collisions between worlds, multiple regional hourglasses, hero survival, Guardian Beasts, and factions that can manipulate the disaster infrastructure. Waves become more frequent when heroes die, and failure can culminate in a world’s destruction. [The LN-based Wave overview details world collision, local registration, hero death, and changing intervals.](https://shield-hero.fandom.com/wiki/Waves_of_Calamity) [Dragon Hourglasses function as countdown, registration, and advancement infrastructure.](https://shield-hero.fandom.com/wiki/Dragon_Hourglass)

**Why it works in fiction.** A visible countdown forces preparation while incomplete knowledge prevents perfect planning. Disasters are both tactical encounters and political allocation problems: who gets defended, who receives the heroes, and what happens elsewhere?

**Everquill implementation.** Use world-time “pressure fronts”:

- breaches;
- plagues;
- celestial conjunctions;
- tax deadlines;
- monster migrations;
- sieges;
- harvest failures.

Multiple clocks should overlap so the player cannot solve everything. A failed event must leave permanent state: destroyed settlements, refugees, new monster ecologies, disrupted prices, dead specialists, altered borders. An heir continues in that damaged world.

**Monetization rule:** a paid skip advances every relevant clock. The interface must preview which known deadlines will move or trigger. A skip buys convenience, never a frozen world or guaranteed preparation success.

### 14. Each hero knows a different valid strengthening method — **Steal the epistemic structure, not belief-based physics**

**What it is.** Legendary Weapons possess multiple strengthening systems. The heroes initially dismiss one another’s methods because each assumes the world follows the game mechanics they personally recognize. Once they accept and test the others’ information, methods can be shared and combined. Weapons also absorb materials to unlock forms and develop mastery. [The Legendary Weapon overview includes material-derived forms and trauma-triggered special series.](https://shield-hero.fandom.com/wiki/Legendary_Weapons)

**Why it works in fiction.** The missing resource is not experience points but epistemic cooperation. Several characters each hold a correct fragment and remain weak because distrust prevents synthesis.

**Everquill implementation.** Seed institutions and cultures with partial, compatible truths:

- one monastery knows preparation;
- one guild knows the catalyst;
- a monster clan knows the safe location;
- a heretic text knows the correct timing;
- an old enemy knows the failure condition.

Physics should not become true merely because the character believes it. Belief should instead determine whether they attempt, recognize, or correctly operate a real method. Testing and cross-source comparison can move claims from rumor to working doctrine.

### 15. Reputation creates a distrust tax across the whole economy — **Steal directly**

**What it is.** Naofumi’s framing does more than make characters rude. It removes party access, equipment, patronage, fair prices, and institutional protection. He survives by learning merchant work, building bilateral relationships, and accumulating visible evidence of usefulness. The original premise explicitly makes betrayal and loss of supplies the foundation of his economic isolation. [The series summary records the theft, accusation, and withdrawal of kingdom support.](https://en.wikipedia.org/wiki/The_Rising_of_the_Shield_Hero)

**Why it works in fiction.** Reputation becomes material. Distrust changes transaction costs, not merely dialogue tone.

**Everquill implementation.** Model reputation as claims circulating through social graphs, not one global morality bar. A rumor can affect:

- quoted prices and required deposits;
- willingness to extend credit;
- guards’ presumption of guilt;
- availability of companions;
- access to research subjects;
- whether witnesses speak candidly;
- how later evidence is interpreted.

Different groups should know different versions of the same event. False accusations are especially compatible with TRUE versus KNOWN state.

Do not copy slavery as a convenient “trust solution.” Use escrow, hostages under reciprocal law, oath magic, guarantors, collateral, references, and repeated performance.

### 16. Curse power converts trauma into immediate strength and delayed debt — **Adapt carefully**

**What it is.** Legendary Weapons can unlock Curse Series through extreme negative emotions. They grant dramatic power while imposing proportional penalties; later Bless variants represent recovery or transformation. [The Curse and Bless series are summarized in the weapon system.](https://shield-hero.fandom.com/wiki/Legendary_Weapons)

**Why it works in fiction.** Power reflects character crisis and creates consequences beyond a combat cooldown.

**Everquill implementation.** Use “desperation techniques” that impose deterministic lasting costs: reputation damage, injury, lost lifespan, damaged relationships, corruption, or binding obligations. Avoid rewarding self-harm as an optimal grind, and never monetize relief from trauma-derived penalties.

---

## Dungeon-core web fiction: ecology, spatial authorship, and reciprocal predation

### 17. The dungeon consumes visitors but also needs them to return — **Steal as a living-world faction**

**What it is.** The genre commonly treats the core as a spatial organism that gains mana from intruders, spends it on rooms, traps, creatures, and rewards, and dies if the core is destroyed. The more interesting works complicate predation. *There Is No Epic Loot Here, Only Puns* begins with the assumption that people are “mana farms,” then has Delta reject mass killing and develop strange reciprocal relations with visitors. [The original Royal Road listing states that central inversion directly.](https://www.royalroad.com/fiction/15935/there-is-no-epic-loot-here-only-%20jeux%20de%20mots)

**Why it works in fiction.** A dungeon that kills everyone destroys its own traffic, reputation, trade ecosystem, and possible allies. A dungeon that offers no danger or reward attracts nobody. The core is therefore managing an ecology and a brand, not merely maximizing damage.

**Everquill implementation.** Treat each major dungeon as a persistent agent with hidden TRUE state:

- hunger;
- temperament;
- expansion objective;
- preferred visitor behavior;
- spawn budget;
- known blueprints;
- diplomatic capability;
- core vulnerabilities.

Characters should hold conflicting KNOWN profiles such as “malevolent death pit,” “sacred trial,” or “generous mushroom spirit.” Players may raid, feed, negotiate with, settle near, redirect, domesticate, exploit, or destroy it.

### 18. Absorption creates blueprints, not generic loot — **Steal**

**What it is.** Dungeon-core stories frequently let cores absorb matter or corpses to learn a blueprint, then spend mana to reproduce altered versions. Royal Road examples explicitly connect absorption, blueprint acquisition, and reproduction experiments. [“The Human Blueprint” demonstrates absorption followed by repeated reconstruction attempts and biological failure.](https://www.royalroad.com/fiction/79208/dungeon-core-in-a-xianxia-world/chapter/2309314/chapter-7-the-human-blueprint)

**Why it works in fiction.** Consumption enlarges the design vocabulary while preserving costs and imperfect understanding. Possessing a pattern does not guarantee competent creation.

**Everquill implementation.** Split crafting knowledge into:

- morphology/material pattern;
- animation principle;
- behavior training;
- sustaining resource;
- control mechanism.

An absorbed wolf corpse might reveal anatomy but not loyalty, reproduction, or a safe binding method. Research can mistakenly attribute a failed construct to the wrong missing layer.

### 19. Dungeon expansion is a spatial technology tree — **Steal**

**What it is.** Cores expand territory, upgrade spawners, appoint specialized creatures, alter habitats, and invest in rooms that generate resources or defend critical nodes. *Dungeon Life* foregrounds “Expansion and Upgrades” and repeated inspections as core progression. [The original Royal Road listing preserves that early structure.](https://www.royalroad.com/fiction/54476/dungeon-life/)

**Why it works in fiction.** Every upgrade changes both production and invasion routes. Geography makes progression legible and attackable.

**Everquill implementation.** Model dungeons, estates, and settlements as graphs:

`entrance → controlled nodes → production rooms → chokepoints → core/keystone`

Travel time, sound, supply lines, escape routes, scouting, and local ownership then become deterministic. Typed actions such as tunneling, flooding, smoking out, bargaining through a herald, or collapsing a bridge operate on the same graph.

### 20. Dungeon–settlement symbiosis produces emergent economies — **Steal**

**What it is.** Friendlier dungeon-core stories develop inspectors, adventurer traffic, harvestable nodes, nearby towns, and rules governing safe delving. The dungeon receives mana and information; the settlement receives materials, employment, defense, and trade.

**Why it works in fiction.** The “monster” becomes infrastructure. Destroying it may remove a danger but also collapse the regional economy.

**Everquill implementation.** Dungeon activity should feed settlement variables: inn revenue, injury rate, rare-material supply, migration, guild influence, cult activity, and military interest. A core’s death should be a permanent ecological and economic event—not simply “dungeon cleared.”

---

## How a Realist Hero Rebuilt the Kingdom: statecraft as resource allocation

### 21. Governance begins with an audit and liquidation of idle assets — **Steal**

**What it is.** Souma’s early power is administrative: establish the kingdom’s actual fiscal condition, assemble competent staff, mobilize assets, and redirect spending. The official publisher description foregrounds economic reconstruction, talent gathering, and administrative reform rather than adventuring. [Seven Seas’ volume-one page summarizes that premise.](https://sevenseasentertainment.com/books/how-a-realist-hero-rebuilt-the-kingdom-light-novel-vol-1/)

**Why it works in fiction.** State capacity comes from finding resources already present but misallocated, hidden, ceremonial, or captured by corrupt intermediaries.

**Everquill implementation.** Territory control should expose a ledger of uncertain quality, not perfect omniscience:

- treasury;
- recurring income and obligations;
- grain reserves;
- labor availability;
- military readiness;
- neglected assets;
- disputed property;
- corruption claims;
- infrastructure condition.

Audits are research actions. Officials can omit, misunderstand, falsify, or confidently misclassify assets. Better auditors reduce uncertainty but consume time and create enemies.

### 22. Food crises are production-allocation problems with delayed correction — **Steal, but make it more rigorous**

**What it is.** Elfrieden’s crisis is tied to land allocation, cash crops, disrupted trade, and failure to recognize or popularize alternative foods. Poncho’s knowledge and the Jewel Voice Broadcast are used to demonstrate edible ingredients. [The episode record captures the nationwide talent search and food-education broadcast.](https://en.wikipedia.org/wiki/List_of_How_a_Realist_Hero_Rebuilt_the_Kingdom_episodes)

**Why it works in fiction.** The solution requires both supply knowledge and mass behavior change.

**Everquill implementation.** Model agriculture with planting and harvest delays, soil suitability, seed stock, transport loss, storage, dietary custom, and merchant incentives. A decree to plant grain should not generate grain immediately. Switching crops may solve next season’s hunger while bankrupting textile workers now.

Public education can change demand, but only if households trust the messenger and can obtain the food. Avoid the novel’s occasional “everyone was foolish until the protagonist explained it” simplification; local resistance should usually have a material cause.

### 23. Mass communication is both administrative capacity and propaganda — **Steal**

**What it is.** Jewel Voice Broadcasts are repurposed for talent recruitment, cooking demonstrations, entertainment, diplomacy, and regular intergovernmental communication. A later hotline supports recurring bureaucratic information exchange between kingdoms. [The hotline example shows delegated officials exchanging information on a regular schedule.](https://novelfire.net/book/how-a-realist-hero-rebuilt-the-kingdom/chapter-53)

**Why it works in fiction.** Communication infrastructure lets policy scale, but it also lets rulers frame events and manufacture common attention.

**Everquill implementation.** Public proclamations should propagate claims into NPC KNOWLEDGE:

- faster through owned communication nodes;
- distorted by distance, rival messengers, literacy, and local trust;
- capable of changing expectations before material policy takes effect.

Announcements can move prices, trigger migration, provoke hoarding, expose secrets, or attract candidates. The narrator may render reactions, but deterministic propagation determines who heard which version.

### 24. Talent searches surface low-status specialists — **Steal with false positives**

**What it is.** Souma’s nationwide call recruits people whose apparently minor or eccentric capabilities become strategically important: administration, food knowledge, communication with animals, performance, and combat. The recruitment is explicitly nationwide rather than confined to established nobles. [The talent-search structure is recorded in the volume-one episode summaries.](https://en.wikipedia.org/wiki/List_of_How_a_Realist_Hero_Rebuilt_the_Kingdom_episodes)

**Why it works in fiction.** State capacity improves by discovering overlooked competencies, not merely leveling the ruler.

**Everquill implementation.** “Issue a call for experts” should be a timed world action producing a candidate pool shaped by:

- message reach;
- reward;
- reputation;
- travel danger;
- discrimination;
- rival recruitment;
- fraud;
- evaluator competence.

Candidate sheets are KNOWN intel. A celebrated engineer might be a persuasive fraud; an unremarkable apprentice may possess the exact hidden TRUE aptitude needed.

### 25. Infrastructure is policy made physical — **Steal**

**What it is.** Road networks, a new port city, engineering corps, and refugee settlement policy convert political decisions into geography and productive capacity. [The adaptation record identifies road construction, port planning, local opposition, and later refugee governance.](https://en.wikipedia.org/wiki/List_of_How_a_Realist_Hero_Rebuilt_the_Kingdom_episodes)

**Why it works in fiction.** Roads alter military reach, trade, migration, and state control simultaneously.

**Everquill implementation.** Infrastructure projects should:

- reserve labor and materials for real hours;
- change travel duration and encounter exposure;
- alter local prices;
- improve tax and military reach;
- create land disputes;
- produce vulnerable construction sites;
- remain unfinished if leadership dies or funding collapses.

This makes world-time gating substantive rather than a mobile-game timer pasted onto a static world.

---

## WN-native System mechanics for hidden TRUE stats

### 26. Appraisal improves by tiers and initially produces almost-useless output — **Highest-priority steal**

**What it is.** In *So I’m a Spider, So What?*, Appraisal begins with headaches and little more than a target’s name. Higher levels reveal species, level, resource totals, abilities, skills, titles, and deeper statistical detail. Targets may detect appraisal or block it, and social norms make unsolicited appraisal intrusive. [The tier-by-tier information ladder is documented here.](https://kumodesu.fandom.com/wiki/System/Skills/Appraisal)

**Why it works in fiction.** Information itself is progression. Early readings are partial and inconvenient; high-tier access creates tactical advantage but also social and counterintelligence consequences.

**Everquill implementation.** Appraisal should reveal fields, not a single accuracy percentage:

- Tier 0: surface description.
- Tier 1: category and obvious condition.
- Tier 2: broad qualitative bands.
- Tier 3: estimated range plus provenance.
- Tier 4: modifiers, resistances, or likely motives.
- Tier 5: exact values only where the fiction supports exact measurement.

Wrong readings should come from deterministic causes—disguise quality, unfamiliar category, interference, observer bias, counterfeit evidence—not narrative whim. Some targets should notice or deliberately feed the appraiser false signals.

### 27. Skill access depends on knowing that a skill exists — **Steal**

**What it is.** Kumo’s System allows skills to be purchased only when the user knows the skill name; affinities alter costs, practice can generate proficiency, exposure can unlock resistances, and books or teachers therefore control access to the possibility space. Titles can also grant skills. [The System overview describes knowledge-gated purchasing, proficiency, affinities, exposure, and title rewards.](https://kumodesu.fandom.com/wiki/System)

**Why it works in fiction.** A skill list becomes cultural capital. Libraries, teachers, monster traditions, and secret schools matter because they reveal options.

**Everquill implementation.** Characters should not see a universal tree. They acquire possible techniques through observation, instruction, experimentation, texts, dreams, titles, or inherited notes. KNOWN intel can include nonexistent techniques or incorrect prerequisites. The TRUE capability graph remains fixed.

### 28. Titles are behavioral records with mechanical consequences — **Steal carefully**

**What it is.** Kumo titles are granted for meeting hidden behavioral conditions and may grant skills or passive effects. They are not simply chosen perks; some commemorate disturbing acts and permanently change how the System treats the character. [The title mechanism and its skill grants are summarized in the System documentation.](https://kumodesu.fandom.com/wiki/System)

**Why it works in fiction.** Progression becomes autobiography. A build records what the character actually did.

**Everquill implementation.** Use earned epithets derived from witnessed or metaphysically significant behavior:

- “Oathbreaker of Red Ford”;
- “The Physician Who Stayed”;
- “Kin-Slayer”;
- “Three-Times Refused”;
- “Friend of the Hollow Court.”

Titles may affect first impressions, eligibility, supernatural recognition, or specialized actions. Public titles and metaphysical titles should differ: society can believe a false epithet while the component laws recognize the true deed.

### 29. Forbidden knowledge is itself a progression track — **Steal**

**What it is.** Kumo’s Taboo skill initially looks like a punishment marker. At its cap it reveals systemic truths about the world’s crisis, turning a malus into access to dangerous context. [The series record connects Taboo’s maximum level to revelation of the world’s impending collapse.](https://en.wikipedia.org/wiki/So_I%27m_a_Spider%2C_So_What)

**Why it works in fiction.** The same knowledge that enables meaningful action also burdens, implicates, or isolates the knower.

**Everquill implementation.** Create “forbidden domains” whose research accumulates exposure:

- resurrection law;
- divine anatomy;
- royal blood authentication;
- dungeon reproduction;
- the origin of the world’s calendar.

Higher exposure reveals more accurate TRUE relationships while increasing surveillance, corruption, legal danger, nightmares, or faction interest. Paid skips must never bypass exposure consequences.

### 30. Classes emerge from lived behavior and later consolidate — **Steal from The Wandering Inn**

**What it is.** *The Wandering Inn* awards classes and skills according to the roles people actually embody. Classes can specialize or consolidate; mundane work can establish an initial class, while higher identities reflect sustained choices and major experiences. Level and skill announcements generally arrive during sleep. [The class list describes role-based prerequisites and specialization.](https://wiki.wanderinginn.com/List_of_Classes) [The skill reference documents capstones and the relationship between class levels and skill awards.](https://wiki.wanderinginn.com/Skill)

**Why it works in fiction.** Character build and character arc are the same object. A person becomes an innkeeper, ruler, rebel, or protector by repeatedly performing that role.

**Everquill implementation.** Do not ask players to select a rigid class at creation. Track hidden practice vectors from resolved actions. At thresholds, offer recognition:

- repeated negotiation under threat may produce an Envoy path;
- maintaining a workshop and teaching apprentices may produce Master-Artisan;
- surviving expeditions through preparation rather than combat may produce Pathfinder;
- ruling through informants may produce Whisper-Regent.

Consolidation should occur when several roles become one coherent identity. The engine determines eligibility; the LLM only narrates the moment.

---

## Cross-source systems Everquill should build first

| Priority | System | Source model | Everquill form |
|---|---|---|---|
| S | Epistemic ledger | Kumo appraisal; Shield Hero’s partial methods | Per-character claims with source, confidence, timestamp, scope, and possible deterministic error |
| S | Component-law resolver | Log Horizon contract magic; Bookworm production | Fixed hidden dependency graphs fulfilled through any route |
| S | Persistent clocks | Shield Hero Waves; Realist Hero infrastructure | Disasters, production, travel, politics, and research advancing in the same world-time |
| S | Dynastic estate | Overlord guild base | Persistent but vulnerable archives, retainers, workshops, charters, relics, and liabilities |
| A | Institutional economy | Bookworm guilds; Log Horizon zones | Licenses, jurisdiction, standards, ownership powers, upkeep, and blacklisting |
| A | Socially distributed reputation | Shield Hero distrust; Realist broadcasts | Faction-specific beliefs affecting prices, access, credit, evidence, and recruitment |
| A | Behavioral progression | Kumo titles; Wandering Inn classes | Paths and epithets earned through resolved actions rather than selected from a universal tree |
| A | Living dungeons | Dungeon-core fiction | Stateful ecological factions whose destruction or alliance changes regional economies |
| B | Category-specific restoration | Overlord and Log Horizon | Construct/guardian restoration only; permanent player death remains intact |
| Avoid | Belief changes physics | Literalized Shield Hero strengthening | Belief changes attempted methods and interpretation, never TRUE rules |
| Avoid | Universal exact appraisal | Generic LitRPG status screens | Exact numbers only through justified instruments or exceptional mastery |
| Avoid | Timers isolated from danger | Conventional mobile gating | Every skip advances the whole simulation and previews known deadline consequences |

---

## Recommended data model for TRUE versus KNOWN intel

A durable claim should contain:

```text
Subject
Claim
Claimed value or range
Source character/document/instrument
Observer
Acquisition method
World timestamp
Geographic/jurisdictional scope
Confidence
Corroboration links
Contradictions
Inheritance status
```

The hidden TRUE record contains the actual value and causal modifiers. The narrator sees only the information permitted for the scene. Research never edits TRUE state; it creates or revises claims.

Confidently wrong intel should arise from reusable mechanisms:

- sample contamination;
- local phenomenon mistaken for universal law;
- disguised subject;
- insufficient appraisal tier;
- corrupt official;
- transcription error;
- correct recipe with wrong material species;
- post hoc causal inference;
- outdated information;
- deliberate counterintelligence;
- inherited note missing its original qualifier.

This is the cleanest way to make LN/WN-style appraisal, secret techniques, guild lore, and dynastic inheritance feel systemic rather than arbitrary.

---

## Sources

### Ascendance of a Bookworm

- [Printing: methods, ink compatibility, precision bottlenecks, and workshop scaling](https://ascendance-of-a-bookworm.fandom.com/wiki/Printing)
- [Guilds: legal entities, market regulation, and Merchant’s Guild authority](https://ascendance-of-a-bookworm.fandom.com/wiki/Guilds)
- [Guild cards: identity, access control, apprenticeship registration, and payments](https://ascendance-of-a-bookworm.fandom.com/wiki/Guild_Card)
- [Commoner magic utilities and contract enforcement](https://ascendance-of-a-bookworm.fandom.com/wiki/Commoner_Magic_Utilities)
- [Gilberta Company: production rights and parchment/plant-paper compromise](https://ascendance-of-a-bookworm.fandom.com/wiki/Gilberta_Company)

### Overlord

- [Great Tomb of Nazarick: floor structure and custom-NPC level budget](https://overlordmaruyama.fandom.com/wiki/Great_Tomb_of_Nazarick)
- [Custom NPCs: creator influence and base-dependent creation](https://overlordmaruyama.fandom.com/wiki/Non-Playable_Character)
- [NPC loyalty hierarchy in Nazarick](https://overlordmaruyama.fandom.com/wiki/Sorcerer_Kingdom?page=1)
- [World Items and effects beyond ordinary restoration](https://overlordmaruyama.fandom.com/wiki/World_Item)

### Log Horizon

- [Magic Contract: Scribe skill, rare materials, MP cost, and world-law rewriting](https://log-horizon.fandom.com/wiki/Magic_Contract)
- [Akiba: zone ownership, taxes, and facility upkeep](https://log-horizon.fandom.com/wiki/Akiba)
- [Chef: manual production, class requirements, inputs, and production time](https://log-horizon.fandom.com/wiki/Chef)
- [Spirit Theory: death, reconstruction, and information loss](https://log-horizon.fandom.com/wiki/Spirit_Theory)
- [Cathedral ownership and control of revival infrastructure](https://log-horizon.fandom.com/wiki/Cathedral)

### The Rising of the Shield Hero

- [Waves of Calamity: world collisions, hero survival, regional events, and changing frequency](https://shield-hero.fandom.com/wiki/Waves_of_Calamity)
- [Dragon Hourglass: countdowns, registration, teleportation, and restricted advancement](https://shield-hero.fandom.com/wiki/Dragon_Hourglass)
- [Legendary Weapons: material absorption, Curse Series, and Bless Series](https://shield-hero.fandom.com/wiki/Legendary_Weapons)
- [Series provenance and Naofumi’s economic/social isolation](https://en.wikipedia.org/wiki/The_Rising_of_the_Shield_Hero)

### Dungeon-core web fiction

- [There Is No Epic Loot Here, Only Puns — original Royal Road listing](https://www.royalroad.com/fiction/15935/there-is-no-epic-loot-here-only-%20jeux%20de%20mots)
- [Dungeon Life — original Royal Road listing](https://www.royalroad.com/fiction/54476/dungeon-life/)
- [Dungeon Core in a Xianxia World: blueprint absorption and reconstruction experiments](https://www.royalroad.com/fiction/79208/dungeon-core-in-a-xianxia-world/chapter/2309314/chapter-7-the-human-blueprint)

### How a Realist Hero Rebuilt the Kingdom

- [Seven Seas volume-one page: administrative-reform premise](https://sevenseasentertainment.com/books/how-a-realist-hero-rebuilt-the-kingdom-light-novel-vol-1/)
- [Episode/volume-derived policy summary: talent recruitment, food broadcasting, roads, ports, and refugees](https://en.wikipedia.org/wiki/List_of_How_a_Realist_Hero_Rebuilt_the_Kingdom_episodes)
- [Intergovernmental Jewel Voice Broadcast hotline](https://novelfire.net/book/how-a-realist-hero-rebuilt-the-kingdom/chapter-53)

### WN-native Systems

- [Kumo Appraisal information tiers](https://kumodesu.fandom.com/wiki/System/Skills/Appraisal)
- [Kumo System: skills, affinities, proficiency, exposure, and titles](https://kumodesu.fandom.com/wiki/System)
- [So I’m a Spider, So What? web-novel provenance and Taboo revelations](https://en.wikipedia.org/wiki/So_I%27m_a_Spider%2C_So_What)
- [The Wandering Inn official web-serial site](https://wanderinginn.com/)
- [The Wandering Inn class prerequisites and specializations](https://wiki.wanderinginn.com/List_of_Classes)
- [The Wandering Inn skill and capstone structure](https://wiki.wanderinginn.com/Skill)