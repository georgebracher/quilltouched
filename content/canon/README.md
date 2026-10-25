# Universe Canon v2 — the authored seated base of what exists

**Team B (World & Canon). CANON LOCKED 2026-07-14 (George).** Ticket: `docs/tickets/universe-canon.md`.
All DNA decisions are resolved (`content/canon/decisions-resolved.md`, incl. the FINAL CONFIRMS);
nothing is flagged or pending. Sprint 5 worldgen may proceed against this base.

This is the machine-readable TRUE super-set the player's Codex is a discovered subset of, and the
canon that worldgen (Sprint 5) and the adjudicator (sealed feats, synthesis, e.g. gunpowder)
validate every generated/discovered thing against. It generalizes the thin lore bible
(`docs/lore/**`) upward and lifts Harrowdown's instances (`content/world/harrowdown.yaml`) up to
the universe level they are examples of.

George is the quality gate on the universe's DNA. Read `anchors.yaml` FIRST — the four established
anchors and the six DNA decisions are all RESOLVED and applied there (canon locked 2026-07-14).

## Format chosen, and why

**YAML files under `content/canon/`, one per category, plus a schema, an anchors file, and the
consistency contract.**

- YAML is the project's content lingua franca — the engine already parses YAML world files
  (`everquill_engine/world.py`). It is human-reviewable by George and diffable in review.
- The canon is a **different object** from a region instance file. `harrowdown.yaml` has a LOCKED
  per-entity schema ("Do not add fields") whose rows are INSTANCES. The canon holds the CATEGORIES
  those instances slot under and carries fields an instance never does — threat-band RANGES,
  taxonomy parents, tech-tiers, composition edges, fit-check bounds. So it lives in its own
  directory with its own schema (`schema.yaml`), and the region files stay untouched.
- Instances are mapped from the **canon side** (each category's `instances:` list), so lifting
  Harrowdown up required no edits to the locked/other-team region files.

## Files

| File | What |
|---|---|
| `anchors.yaml` | The 4 established anchors + 6 DNA decisions, all RESOLVED (canon locked). Machine-flags worldgen reads. |
| `schema.yaml` | Field schemas per category + ID conventions. |
| `bestiary.yaml` | The creature ladder (slime -> dragon), 18 rungs across 7 families. |
| `materials.yaml` | The synthesis "periodic table", 34 substances incl. the gunpowder trio. |
| `flora.yaml` | Plants/herbs/fungi, 15 species with properties + wrong-intel seats. |
| `items.yaml` | Item archetypes, 21 classes from knife to soul-anchor. |
| `texts-knowledge.yaml` | 13 fields of study + 12 canonical texts (the research tree). |
| `sciences-tech.yaml` | 7 fields at the ceiling + 10 inventions (sealed/beyond) + the impossible list. |
| `cosmology-powers.yaml` | The Quill/veil/churches/laws + the magic ladder (every power is a purchase). |
| `peoples-factions.yaml` | 6 peoples + 11 factions, broad strokes. |
| `consistency-contract.yaml` | **The fit-check** — prose doctrine + the checkable shape worldgen/adjudicator consume. |

## The four anchors, as applied (confirm in `anchors.yaml`)

1. **Low magic** — applied. Magic is a cost ledger; hedge-craft common, rites institutional,
   veil-work singular, battle-magic UNVERIFIED (war-colleges, sealed-if-real). *Confirm the
   ceiling for arcane force stays here.*
2. **Pre-gunpowder ceiling** — applied. Gunpowder = the flagship sealed invention (nitre +
   brimstone + charcoal). 6 more reachable sealed inventions authored; steam/electricity/firearms
   marked `beyond` (gated behind prerequisite sealed feats). *Confirm the reachable/beyond split.*
3. **Slime -> dragon ladder** — applied on the engine threat_band scale. Wyvern = 14 (the
   Quarryman); young dragon 18-24; ancient/calamity 25-40+ (HOPELESS even to an elite).
   *Confirm the top-band numbers and whether a living dragon is placed anywhere yet.*
4. **Bottomless / extensible core** — applied. The fit-check ESCALATE verdict + append-on-accept
   is the growth model; the Quill's final answer is the one permanent gap. *Confirm append-on-accept.*

## Coverage (per-category counts)

Bestiary 18 · Materials 34 · Flora 15 · Item archetypes 21 · Knowledge domains 13 · Texts 12 ·
Tech fields 7 · Inventions 10 (+6 impossible) · Forces 5 + Powers 4 · Peoples 6 · Factions 11.
Breadth over exhaustiveness, with a strong spine per the ticket.

## The consistency contract, in one line

Every candidate is checked against global invariants (absences, true/known split, magic-has-a-price,
tech-ceiling, low-magic density), then its category fit-check. Verdict is **FIT** (admitted as a
KNOWN instance), **REJECT** (trips an invariant), or **ESCALATE** (coherent but out-of-band -> the
adjudicator + precedent ledger -> APPENDED to canon permanently). Details in
`consistency-contract.yaml`.

## Stub laws filled while here (they ARE canon)

`docs/lore/03-magic-cost-ledger.md`, `docs/lore/07-summoning-history.md`,
`docs/lore/08-demon-lord-dossier.md` were 5-line stubs — filled to universe depth this pass.

## DNA decisions — RESOLVED (canon locked 2026-07-14)

All the v1 open creative decisions are ruled and applied (`content/canon/decisions-resolved.md`):

- **Demon Lord** — DEAD MYTH and/or PROPAGANDA (maintained either way); TRUE half never narrator-facing.
- **Demihumans** — EXIST (attested, rare, humans dominant). Two more peoples LOCKED IN: steadfolk
  (halfling-kin) and marchfolk (orc-kin, people-vs-feral split). Interbreeding canon (mixed heritage).
- **Sole god** — the Quill is the one true creator; worship is PLURAL + REGIONAL (a first-class,
  repeatable per-region sect pattern). No rival pantheon.
- **Dragons** — the current apex, with the placed **Cinder Dam** (the Mother Dragon) seated in the
  burned north and her scattered young across the frontier; `beyond_the_ladder` opens when she falls.
- **Map** — 1 capital + 1 large city + 5 towns + frontier-open beyond; names approved.
- **Working names** — "Open Page" / "the Blotted" and the region names all confirmed.

## Where v2 extends

Per-region canon consumption (worldgen selecting canon rows for a new region); deeper undead/
construct/aberration tracks; the full sealed-invention dependency graphs as machine data (not just
`combines_into` edges); demihuman regional content once existence is confirmed; the precedent-ledger
schema once the adjudicator lands (Sprint 3+); a formal biome->flora->fauna coherence table.
