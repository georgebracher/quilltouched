# 03 — Magic Cost Ledger

Scope: magic as a cost ledger, not a permission list — the pricing format (components, time, permanence trade-offs, corruption, attention from entities) and the ledger entries themselves; costs are engine-enforced state deductions (roadmap §3.2). **Filled to universe depth (Universe Canon v1, 2026-07-14) — this file is no longer a stub.** The short-form table in `02-universe-laws.md` is the seed; this file is the full rack. The machine-readable powers taxonomy is `content/canon/cosmology-powers.yaml`.

## The one rule

No effect is a permission. Every effect is a purchase, and the engine collects. This is what "low magic" MEANS in this world (`content/canon/anchors.yaml`, `anchor.low_magic`): not that magic is weak, but that nothing supernatural is ever free, and the price is state the engine deducts — never a mood the narrator sets.

## The ledger form

Five columns. Every entry prices all five, even where the answer is "none."

- **Components** — the physical inputs consumed or required. Named canon materials/flora, or a sealed-law component (`laws-format.md`).
- **Time** — the world-clock cost. Hedge-work is hours; a rite is a Quarterday eve; veil-work is a thin window that will not wait.
- **Permanence** — what it does and does not undo. Most magic here is one-directional: a closed wound scars, a sealed name cannot be un-said, a crossing never rewinds.
- **Corruption / exposure** — forbidden-knowledge exposure accrued (`content/canon/cosmology-powers.yaml`, `power.forbidden_exposure`). Hedge-craft accrues none; veil-work accrues heavily, and skips never bypass it.
- **Attention** — who or what now knows. The warded thing knows a line was laid. Anyone who reaches the rolls can read a sealed name. Entities that watch the veil learn the name of anyone who knocks.

## The tiers of power (low to sealed)

The four tiers of `content/canon/cosmology-powers.yaml`, priced. Each is a purchase at a different scale.

### Hedge-craft — the commonest "magic," barely magic at all

| Effect | Components | Time | Permanence | Corruption | Attention |
|---|---|---|---|---|---|
| Mending poultice | Vale herbs (woundwort, yarrow), clean linen | Hours to act | Wound closes; the scar stays | None | None |
| Warding chalk | Chalk cut from a named barrow | A night to lay the line | Fades by next season | None | The warded thing knows a line was laid, and by whom |
| Folk charm (a knot, a rowan-cross) | Common materials | Minutes | Comfort, mostly; the odd real small ward | None | None |

Hedge-craft is the floor. It bleeds into apothecary and husbandry, and most of it is honesty with a herb attached (`10-economy-prices.md`, the poultice that "works on wounds that were going to close anyway, faster"). It is why a low-magic world does not feel magic-less: the small stuff is everywhere and it is real.

### Church rites — institutional, public, fallible

| Effect | Components | Time | Permanence | Corruption | Attention |
|---|---|---|---|---|---|
| True-name sealing | Ceremony, a drop of blood on the roll | One Quarterday eve | Permanent entry | None | Anyone who reaches the rolls can read it — legibility is the price |
| Public appraisal | Offering, the parish book, the sister's hand | The ceremony | A public KNOWN entry, corrected only by a new ceremony | None | The parish, and eventually the cathedral copy |
| Reading the dead their lines | The rolls, a grave | The rite | Closes the death record; changes nothing about the dead | None | The parish remembers who was read and who was not |

The church's magic is record. Its power is that a sealed name becomes an identity anchor (`02-universe-laws.md`, `law.resurrection`, identity component) — and its cost is that record is public and fallible (`05-skill-church.md`). Corruption is local (a bishop), never the rite.

### Veil-work — the sealed, forbidden end

| Effect | Components | Time | Permanence | Corruption | Attention |
|---|---|---|---|---|---|
| Veil-work at a thin place | Per `law.resurrection` (identity, memory, vessel, passage, power) | The thin window, no longer | Never rewinds | Exposure accrues per the forbidden-knowledge track | Entities that watch the veil learn your name |
| An incomplete attempt | Any components assembled | The window, spent | Nothing crosses, no stake is taken | Exposure accrues **as if it had succeeded** | Something on the far side noticed the knock — an attention clock starts |

Veil-work is the model for every sealed feat: components must verify, and then the engine takes the costs (`laws-format.md`). The attempt is priced whether or not it works. Skips never bypass the exposure; the thin window is a real wait on the world clock.

## Sealed inventions are cost-ledger entries too

Real-world knowledge enacted through in-world materials is priced on the same rack. Gunpowder is the flagship (`content/canon/sciences-tech.yaml`, `tech.black_powder`):

| Effect | Components | Time | Permanence | Corruption | Attention |
|---|---|---|---|---|---|
| Black powder (first synthesis) | Nitre, brimstone, charcoal, the correct process | Milling, corning, repeated failed batches | The invention exists in canon **permanently** once accepted | Forbidden-knowledge exposure (a world-changing thing you now know) | Massive notoriety; faction reactions; an economy shift; the crown notices |

The point of pricing an invention this way: knowing the recipe is not the effect. The effect is paid for in wrong batches, time, exposure, and the attention a world-changing secret buys. World-changing tech carries resurrection-tier costs by design (roadmap §3.7).

## What the ledger forbids

- **No free effect.** If a generated or attempted effect has no entry on this rack, the fit-check rejects it (`content/canon/consistency-contract.yaml`, `inv.magic_has_a_price`).
- **No effect the narrator can grant.** Costs are engine-enforced state deductions. The narrator describes what the engine already took; it never waives a price to make a scene land.
- **No refund.** Permanence is one-directional. The engine does not un-deduct.

Absence of a caster is a fact about the vale, not a ruling on the universe (`02-universe-laws.md`). Battle-magic, if the war-colleges really manage it, is priced on this same rack — sealed and cost-ledgered, never a common permission.
