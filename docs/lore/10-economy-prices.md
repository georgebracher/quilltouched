# 10 — Economy & Prices

Scope: copper/silver/gold coin anchors — the price table for goods, services, wages, guild fees, and fines that keeps contracts, costs, and rumor-era prose consistent (playbook §4 ADOPT). **v1 (B1, Sprint 1): Harrowdown anchors, coin trust, and the vale's trade.** The machine-readable copy of the goods table is `content/world/harrowdown.yaml` `prices:`; that file and this one must not drift.

## Coin

100 copper **pennies** = 1 silver **mark**. 100 marks = 1 gold **sovereign**.

Pennies are the vale's real currency. Marks appear at market and in guild business. Sovereigns are things people have heard of: a working farm sells for three, and Maren Ostler (`npc.harrowdown.maren_ostler`) claims to have held one once, as the end of a story that changes with the teller.

## Coin trust

Coin is a KNOWN sheet like everything else: a mark is a claim about silver, and claims have provenance.

- **Severwick crown-mint marks** pass at face. The mint mark is the provenance stamp everyone in the vale can read.
- **Old-kingdom marks** pass at weight, and weighing costs a penny at the merchant factor's scales. Clipped coin moves east out of Dunmere every year; the factor keeps a shears-marks chart nailed to his stall.
- **Pennies always pass.** Nobody clips copper.
- **The Blotted pay in kind** and take no notes of hand. A Blotted trade is closed when the goods change hands and never reopened. The vale finds this alarming and reliable in equal measure.

## Price anchors

All figures in pennies. These anchor prose, contracts, and rumor-era prices; the engine reads the YAML copy.

**Bed and board (the Drowned Ram, `loc.harrowdown.tavern`)**

| | pennies |
|---|---|
| Common-room straw, per night | 2 |
| Private room, per night | 8 |
| Common meal (stew, bread, greens) | 2 |
| Ale, pint | 1 |
| Bread, loaf | 1 |

**Gear (Market Row rates; no local smith-guild chapter, so blade prices carry Severwick freight)**

| | pennies |
|---|---|
| Tallow candle | 1 |
| Sealed lamp oil, pint (Ferrier's) | 8 |
| Knife | 60 |
| Spear | 150 |
| Leather jerkin | 300 |
| Shortsword | 600 |
| Mail shirt | 4,000 |

**Potions, by grade**

| Grade | pennies | What the money buys |
|---|---|---|
| Poultice (hedge-grade) | 20 | Herbs and honesty. Works on wounds that were going to close anyway, faster. |
| Lesser potion, unsealed | 300 | Healer-brewed. The label is the brewer's word. |
| Field potion, unsealed | 1,200 | Journey-stable for a season. Same word, higher stakes. |
| Sealed potion | 6,000 | Healers' guild wax seal. **The seal buys recourse, never potency** — a sealed bottle can still be a bad batch, and the guild pays blood-price when its seal proves false. That guarantee is what costs twenty times the brew. |

**Wages, fees, bounties**

| | pennies |
|---|---|
| Laborer, day | 10 |
| Guild registration (F plate) | 20 |
| Plate deposit, refunded on surrender | 50 |
| Quarterday exam fee, forfeit on failure | 100 |
| Appraisal ceremony offering | 10 |
| Carriage seat, per day | 30 |
| Sedge Ford toll, per cart | 5 |
| Board posting: granary rats (F) | 40 |
| Board posting: wolf pack (D) | 250 |

**Fines (the reeve's schedule)**

| | pennies |
|---|---|
| Brawling on Market Row | 50 |
| Trading without a stall token | 20 per day |
| Carrying a false guild plate | The plate is branded through, the deposit forfeit, and the guild bars the name for life. The reeve adds nothing; the guild's punishment is worse than his. |

Rold Tanner's "stall tax" (`npc.harrowdown.rold_tanner`) appears on no schedule. It runs two to five pennies a stall, collection days irregular, and it clears the row faster than the reeve's real fines do. The bailiff's share is the reason no one has been fined for collecting it.

## What the vale sells

Wool south to Severwick on the weekly wagon; tallow and sealed lamp oil in both directions; mutton on the hoof at the season drives. What it buys: iron, salt, cloth worth wearing, and certified anything — the vale produces no guild-sealed goods except Ferrier's oil, and Elam's seal is a merchant-guild trade mark, not a craft warranty. The distinction feeds a running Market Row argument about what, exactly, anyone's seal is worth. The healers' guild table above is the serious version of the same question.
