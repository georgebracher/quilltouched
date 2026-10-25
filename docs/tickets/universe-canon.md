# Universe Canon v1 — the authored seated base of what exists

George (2026-07-14): "a large seated base of items/creatures/books/materials known to exist in the world; the player can find/form OTHER things (books, items, creatures) AS LONG AS they fit in line with our seated base." This is the machine-readable TRUE base state that makes "locked universe" enforceable — the super-set the player's Codex is a discovered subset of, and the canon that worldgen (Sprint 5) and the adjudicator (invention/synthesis, e.g. gunpowder) validate every generated/discovered thing against.

This is a WORLDBUILDING DRAFT for George's review — he is the quality gate on the universe's DNA. Draft against the anchors below (all already-made decisions), and FLAG each at the top for his confirm/correct.

## Established anchors (confirm with George; do not silently change)
- **Low magic.** Magic is rare, costly, cost-ledger-based; resurrection is tricky-but-possible (the Five Laws). Not a high-magic world.
- **Classic fantasy, medieval, PRE-GUNPOWDER tech ceiling.** Metallurgy/smithing/alchemy exist; gunpowder/firearms do NOT exist yet — gunpowder is an ACHIEVABLE, world-changing, sealed-feat-tier invention (components exist under in-world names: nitre, brimstone, charcoal). This is the model for all "real-world knowledge enacted through in-world materials."
- **Monster ladder** from the isekai research: slime → goblin → orc/ogre → wyvern → dragon (legendary/near-mythical). Dragons are top-tier and rare.
- **Bottomless (like the Quill).** Endless undiscovered depth — the canon is a strong authored CORE, not a finite closed set; player/worldgen discovery extends it, gated by the fit-check.

## Read first
docs/lore/** (existing thin bible — generalize Harrowdown's content UP to universe level), docs/research/ (the isekai trope + LN-mechanics research — the monster ladder, appraisal tiers, materials/craft models), docs/research/data-layer/claude-synthesis.md (claim/known-sheet model the canon feeds), content/world/harrowdown.yaml (its creatures/items/materials are INSTANCES of universe categories — lift them up).

## Deliver: a machine-readable Universe Canon (propose format — YAML under content/canon/ or docs/lore/canon/)
Categories (a strong v1, breadth over exhaustiveness — enough seated base that the world feels real and generation has rails):
1. **Bestiary** — the universe creature taxonomy: the full ladder (slime→dragon) + regional/biome variants, each with a category, threat band range, habitat, common-knowledge vs research-depth facts. Harrowdown's six are instances.
2. **Materials & substances / reagents** — the crafting+synthesis "periodic table": metals, ores, stone, cloth, alchemical reagents (nitre, brimstone, charcoal, herbs-as-reagents), their properties and what they combine into. This is what the adjudicator checks inventions against (gunpowder = nitre+brimstone+charcoal+process).
3. **Flora** — plants/herbs/fungi + properties (medicinal, poisonous, alchemical), feeding potions/research.
4. **Item archetypes** — the classes of thing that exist: weapon/armor/tool/consumable/relic types; what's mundane vs rare vs sealed-tier.
5. **Texts, books & knowledge** — the "textbooks/research/science" George named: what fields of study exist (metallurgy, herblore, veil-lore, history, cartography...), the researchable knowledge tree, and canonical texts/tomes that exist in the world (what an archive can hold).
6. **Sciences & tech ceiling** — an explicit statement of what's KNOWN (the ceiling) and what's BEYOND it (the space inventions push into). Pre-gunpowder chemistry, medieval engineering, no electricity/steam/etc.
7. **Cosmology & powers** — link/lift the Quill + churches + veil + laws (mostly authored in docs/lore); the pantheon and metaphysical forces.
8. **Peoples & factions (base)** — the demihuman set (humans dominant, elves/dwarves/beastfolk rare+regional per the playbook), broad-strokes only.

## The consistency contract (the point of the whole thing)
Define, in prose + a checkable shape, HOW discovered/generated content is validated as "fitting the seated base": a new creature must slot into the taxonomy + threat ladder; a new item must be composed of canon materials at/below the tech ceiling; a new book must be within an existing knowledge domain or a legitimately-discovered new one; an invention beyond the ceiling routes through the adjudicator + precedent ledger (gunpowder pattern) and, on acceptance, is APPENDED to canon permanently. This is the interface worldgen (Sprint 5) and the adjudicator consume.

## Fill the stub laws while here
docs/lore/03-magic-cost-ledger.md, 07-summoning-history.md, 08-demon-lord-dossier.md are still 5-line stubs — fill to universe depth as part of the canon (they ARE canon).

## Out of scope
Not building the worldgen/adjudicator consumers (that's Sprint 5 + the sealed-feat system) — just the canon they'll read, plus the consistency contract that specifies the interface. Not per-region content (that's authored per region like Harrowdown).

## Report
Format chosen + why; the canon's category coverage (counts per category); the anchors as you applied them + any you need George to confirm; the consistency-contract spec; which stub laws you filled; the biggest open creative decisions for George.
