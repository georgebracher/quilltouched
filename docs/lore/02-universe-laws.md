# 02 — Universe Laws

Scope: the hand-authored physics of the locked universe — where the Impossible/Sealed boundary sits, and the registry of component laws in the `laws-format.md` shape (roadmap §3.2). **v1 (B1, Sprint 1): starter physics, the veil, one registered law with its Harrowdown instantiation, and the magic cost ledger in short form.** Later sprints add laws to the registry; the full ledger lands in `03-magic-cost-ledger.md`.

## The ladder is physics

The plausibility ladder is how the world works, and working people know it the way sailors know tides. A shepherd knows a wolf can be driven off and a wyvern cannot. The guild letter-grades monsters because the underlying gradient is real, even where the guild's read of it is wrong.

- **Hopeless is legal.** You can walk up the Quarry Track with a spear. The world will resolve what happens; the best case is that you live wrecked. Jorun Pike (`npc.harrowdown.jorun_pike`) is the vale's standing proof.
- **Sealed feats are component lists.** Some acts are barred until the world's own requirements are assembled. Any route that assembles them counts, including routes never authored. The registry below holds the laws.
- **Impossible acts get no roll.** Unmaking a written deed. Raising the dead by grief alone. Flight by wanting it. The attempt is still a deed: witnessed, logged, remembered. The vale's word for people who try is "cloud-shouter," and the vale keeps their names.

## The veil

The dead cross once, outward. That is the base physic. Everything the two churches argue about sits on top of it; neither disputes the crossing itself.

The veil is thinner in some places than others. **Thin places** are sites where, under the right components, the crossing can be made in the other direction. They are rare, local, and known mostly as ground people avoid.

**The vale's thin place is Hollow Tor** — the barrow field on the high downs above the Cairn Road, west of town. Public knowledge stops here: shepherds will not graze the tor, carters will not overnight below it, and on some winter nights lights walk the barrows. A barrow wight (`creature.harrowdown.barrow_wight`) holds the field.

**TRUE (engine and authoring only — never narrator context):**

- Hollow Tor carries the veil-thin attribute. Its recurring thin window is the six nights centered on the winter Quarterday. The window has held as long as the barrows have stood.
- The wight is strongest inside the window and can never leave sight of its own barrow.

## Registry of component laws

| law_id | Name | Status | Definition |
|---|---|---|---|
| `law.resurrection` | The Five Laws of Return | Known early, achieved endgame | Worked example in `laws-format.md` (binding) |

One law registered at v1. Summoning's historical law is later-sprint work (`07-summoning-history.md`).

### Harrowdown instantiation of `law.resurrection`

What each component looks like from inside this region, today. Public rows are fair game for rumor, sermon, and research leads. These are research targets, never quest markers.

| Component | What exists in the vale (public) |
|---|---|
| identity | The chapel's parish rolls seal a true-name at every appraisal ceremony — and the roll fire thirty years back destroyed every entry older than that (`05-skill-church.md`). Vale wedding custom presses each spouse's true name into a wax seal kept by the other; most households own a pair. |
| memory | Journals are devotional objects under Open Page practice, and long-married witnesses are common. The component is cheap where record-keeping is pious. |
| vessel | Chapel-yard burial is the norm and the vale preserves nothing. Thirty-year-old remains fail any preservation threshold. A crafted vessel has never been made here, or never admitted to. |
| passage | Hollow Tor, above. Locals know it is avoided; almost nobody alive knows why in terms precise enough to use. |
| power | No known holder. The known price is a life willingly offered. The vale does not talk about this component, which is itself a fact worth noticing. |

**TRUE (engine and authoring only — never narrator context):**

- `item.harrowdown.marriage_seal` is anchor-class, bound to Reyla Ferrier, crafted at her wedding decades before her death. It satisfies *identity* for her.
- Elam Ferrier (`npc.harrowdown.elam_ferrier`) has spent thirty years assembling the Five Laws for his wife. He holds identity (the seal) and memory (his journals, his witness-standing). He has mapped the Hollow Tor window to the night. His open problems are vessel (she drowned; the chapel-yard remains are thirty years gone) and power (the only life he has standing to offer is his own, and he is running out of years in which the offer means anything). The shop front is the disguise; the lore 8 on his true sheet is the truth.

## Magic is a cost ledger

Magic exists, is narrow, and is paid for. No effect is a permission; every effect is a purchase, and the engine collects. Ledger form: **components · time · permanence · corruption · attention.**

| Effect | Components | Time | Permanence | Corruption | Attention |
|---|---|---|---|---|---|
| Mending poultice (hedge-craft) | Vale herbs, clean linen | Hours to act | Wound closes; the scar stays | None | None |
| Warding chalk (hedge-craft) | Chalk cut from a named barrow | A night to lay the line | Fades by next season | None | The warded thing knows a line was laid, and by whom |
| True-name sealing (church rite) | Ceremony, a drop of blood on the roll | One Quarterday eve | Permanent entry | None | Anyone who reaches the rolls can read it — legibility is the price |
| Veil-work at a thin place | Per `law.resurrection` | The thin window, no longer | Never rewinds | Exposure accrues per the forbidden-knowledge track | Entities that watch the veil learn your name |

What the vale has never seen: thrown fire, passage through walls, speech across distance. Ballads say the capital's war-colleges manage the first. Nobody in Harrowdown can verify a ballad, and the guild dossier on the subject is one fifty-year-old letter. Absence of a caster is a fact about the vale. It is not a ruling on the universe.
