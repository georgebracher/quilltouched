# Everquill Style Bible v0 (E0.1 — pending George sign-off, G0.1)

The locked visual spec for every generated sprite. All generation goes through
`docs/art/prompt-template.md`, which implements this document. No sprite ships
that violates this spec. Committed sprites are never regenerated (roadmap §3.9).

Sources: roadmap §3.8 (Inked System skin), §3.9 (sprite pipeline);
playbook §4 ADOPT "flat-color LN sprite style ~5 heads", AVOID "chibi or
7-head realism sprites".

---

## 1. Core style

**Flat-color light-novel illustration.** Japanese LN insert-art language,
simplified to game-sprite flatness: uniform color fills, hard-edged cel
shading, clean dark ink outlines. Storybook-muted, not saturated anime pop —
the world lives on vellum and the sprites must sit on the Inked System skin
(vellum-dark fills, ink-blue accents) without shouting over it.

Explicitly NOT:
- **NOT chibi / super-deformed** (playbook AVOID X-list).
- **NOT 7–8-head realism** (same).
- NOT painterly, NOT airbrushed, NOT pixel art, NOT 3D-render look.

## 2. Proportions

- Humanoids: **~5 heads tall** (4.75–5.25 acceptable). Adult characters vary
  by build/age within that band, never outside it.
- Children/small folk: same head scale, shorter bodies — never balloon the
  head to compensate (that way lies chibi).
- Creatures: naturalistic-simplified anatomy at whatever head ratio the
  species implies; the flatness/outline/palette rules carry the style, not a
  head count.
- Hands and feet simplified but present — no mitten hands, no missing digits.

## 3. Outlines

- Every sprite has a **clean, closed, uniform dark outline**.
- Outline color: **Outline Ink `#2A2430`** (warm near-black — never pure
  `#000000`, never a colored outline).
- Exterior contour weight: **~1% of sprite height** (≈10 px on a 1024 px
  subject). Interior detail lines: **~60% of exterior weight**.
- Lines are constant-width and deliberate: no sketchy tapering, no broken
  contours, no double lines, no hatching.

## 4. Cel shading limits

- Each surface = **flat base fill + max 2 additional steps**: one shadow
  step, one optional highlight step. Hard edges only.
- No gradients, no soft airbrush transitions, no texture noise, no bloom.
- Shadow steps shift toward **Sepia Shadow `#8A7358`** (warm), not toward
  grey or black. Highlights shift toward **Vellum `#EFE4C9`**.
- Light source: even, neutral, slightly upper-front. No dramatic rim light,
  no colored stage lighting.
- Restrained glow is reserved for the System/UI layer — **never baked into a
  sprite**.

## 5. Palette — 28 named colors

All fills come from this palette or its in-spec shade/highlight steps
(§4). "Role" is binding: don't dress a commoner in System Ink.

### Skin tones
| # | Hex | Name | Role |
|---|-----|------|------|
| 1 | `#F4DCC3` | Porcelain | Fair skin base |
| 2 | `#E3B98D` | Honey | Tan skin base |
| 3 | `#A9764F` | Umber | Brown skin base |
| 4 | `#6F4A32` | Deepbark | Deep skin base |

### Hair
| # | Hex | Name | Role |
|---|-----|------|------|
| 5 | `#23212B` | Ink Black | Hair — black |
| 6 | `#6B4226` | Chestnut | Hair — brown |
| 7 | `#D9C08B` | Ash Blonde | Hair — blonde |
| 8 | `#B05A2E` | Copperfire | Hair — red/auburn |
| 9 | `#B9BCC4` | Quill Silver | Hair — grey/silver/white |

### Leathers & cloth
| # | Hex | Name | Role |
|---|-----|------|------|
| 10 | `#7A5537` | Road Leather | Traveling leathers, straps, boots |
| 11 | `#4A3320` | Saddle Dark | Dark leather, belts, scabbards |
| 12 | `#C29B6C` | Buffhide | Light leather, aprons, satchels |
| 13 | `#6E3229` | Oxblood | Rich leather, bound books, accents |
| 14 | `#5E7052` | Weald Green | Travel cloaks, hunter cloth |
| 15 | `#6B7A88` | Slate Cloth | Commoner/urban cloth, uniforms |

### Metals
| # | Hex | Name | Role |
|---|-----|------|------|
| 16 | `#5A5E66` | Iron Grey | Iron, dark steel, blades |
| 17 | `#9FA8B2` | Steel Light | Polished steel, buckles, highlights on metal |
| 18 | `#C9A24B` | Guild Brass | Brass, gold, guild fittings, rank plates |
| 19 | `#A66A3F` | Coin Copper | Copper, bronze, low-value coin |

### Vellum / parchment neutrals
| # | Hex | Name | Role |
|---|-----|------|------|
| 20 | `#EFE4C9` | Vellum | Paper, pages, church whites, highlight pole |
| 21 | `#D9C8A4` | Parchment | Aged paper, plaster, bone, mid neutral |
| 22 | `#8A7358` | Sepia Shadow | Universal warm shadow pole (§4) |
| 23 | `#2A2430` | Outline Ink | ALL outlines (§3); darkest accent fill |

### The System accent (Inked System skin)
| # | Hex | Name | Role |
|---|-----|------|------|
| 24 | `#3A5E8C` | Quill Ink | Ink-blue System accent — Skill Church trim, quills, seals, magic-adjacent details. Sparingly. |
| 25 | `#22364F` | Deep Ink | Dark pole of Quill Ink; night blues |

### World & creature
| # | Hex | Name | Role |
|---|-----|------|------|
| 26 | `#7FB069` | Slime Jade | Slimes, potion greens, verdant accents |
| 27 | `#6E7F3E` | Goblin Moss | Goblinoid skin, swamp/moss tones |
| 28 | `#B03A3A` | Draught Crimson | Healing draughts, blood-adjacent accents, wax seals |

Ash-wolf and similar soot-grey creatures use Iron Grey / Slate Cloth bases
with Sepia Shadow steps and a single Draught Crimson or Guild Brass eye
accent — no dedicated fur color.

## 6. Background & canvas

- **Transparent background. Always.** True alpha PNG — no white matte, no
  vignette, no scenery, no ground plane, no cast/contact shadow (the tableau
  compositor owns grounding).
- Canvas 1024×1024. Subject centered. Frame fill by class (v1.1, after the
  batch-1 framing failures): **humanoids ~70%** of frame height with clear
  empty margin above the head and below the feet; **creatures ~80%**;
  **items ~70%**. Nothing cropped by the canvas edge.
- One subject per sprite. No props lying beside characters, no companion
  critters.

## 7. Pose-lock per entity class

Locked so every sprite of a class composites interchangeably in the tableau.

| Class | Pose lock |
|---|---|
| **Humanoid NPC** | Full body, neutral standing pose, **3/4 view turned toward viewer's left**, weight even, arms relaxed at sides OR holding one signature prop below chest height. Calm/neutral expression. No action poses, no dynamic camera. |
| **Creature** | Full body, **left-facing profile** (nose/head toward viewer's left), neutral standing/idle stance, all limbs visible, tail (if any) readable in silhouette. |
| **Item** | Single item, **45° hero shot** (rotated to show face + one side/top), floating on transparency, no hands, no surface, no sparkle FX. |

## 8. Legibility floor

Every sprite must still read at **120 px tall**:
- Silhouette alone identifies the entity class (person/creature/item).
- The one signature feature (scar, habit, tankard, rank plate shape) survives
  the downscale.
- Palette roles stay distinguishable (leather vs metal vs cloth).

Test = downscale to 120 px and look. If it muds out, the design is too busy —
simplify detail, don't sharpen it.

## 9. Acceptance checklist

Every generated sprite is checked before commit. ALL must pass:

- [ ] **Anatomy sane** — correct limb/digit count, no fused or melted forms, face coherent.
- [ ] **Proportions** — humanoids in the 4.75–5.25-head band; not chibi, not realism.
- [ ] **Palette compliance** — fills resolve to §5 colors or their in-spec shade/highlight steps; no off-palette saturated intruders.
- [ ] **Outline consistency** — closed, uniform, warm-dark outlines per §3.
- [ ] **Shading in limits** — flat fills, ≤2 steps per surface, no gradients/glow.
- [ ] **Silhouette readable** — passes the 120 px floor (§8).
- [ ] **Pose-lock respected** — matches the class pose in §7.
- [ ] **Transparent background** — true alpha, no matte fringe, no ground shadow.
- [ ] **No baked-in UI/text/watermarks** — no letters, numbers, logos, frames, health bars, signatures.

Fail any box → regenerate (respecting batch cost discipline). Never hand-wave
a partial pass into the canon record.

## 10. Scene backgrounds (new asset class — Sprint 1, batch 2)

Static location backdrops the tableau compositor places sprites onto.
Visual-novel style location art, same world register as the sprites.

- **Same style language as sprites:** flat LN illustration, clean warm-dark
  ink outlines, flat fills with ≤2 hard-edged shading steps per surface, no
  gradients/glow/texture noise. The §5 palette is binding — a background is
  built from the same 28 colors (vellum/parchment plasters, leathers and
  woods from the leather rows, iron/brass fixtures, restrained Quill Ink
  accents only where the location earns them).
- **NO characters, NO creatures.** Not even distant silhouettes. Life enters
  a scene only as composited sprites.
- **Sprite-safe floor band:** the lower third of the image is open,
  uncluttered floor — no furniture, props, or shadows inside it. Sprites
  stand in this band; furniture and set dressing live in the middle/upper
  bands. This is the background's single most important rule.
- **Camera:** straight-on wide interior view at standing eye level (VN
  backdrop framing). No dramatic angles, no fisheye, no forced perspective.
- **Canvas:** landscape **1536×1024**, opaque (backgrounds are the one asset
  class WITHOUT transparency).
- **Lighting:** even and warm for interiors; no light shafts, no bloom.
  Ambient glow sources (lanterns, hearths) render as flat fills + one hard
  highlight step, never a soft halo.
- **No text/UI:** notice boards, signs, and book spines stay blank or carry
  illegible scribble marks — never readable letters or numbers.

**Background acceptance checklist** (replaces the sprite checklist items
that don't apply):

- [ ] Palette compliance (§5) — fills resolve to the 28 colors or in-spec steps.
- [ ] Flat fills, ≤2 shading steps, no gradients/glow/texture noise.
- [ ] Zero characters or creatures anywhere in frame.
- [ ] Lower-third floor band clear of furniture/props/cast shadows.
- [ ] 1536×1024 landscape, opaque.
- [ ] Eye-level VN framing, no dramatic perspective.
- [ ] No readable text, no UI, no watermarks.
- [ ] Still reads as the location when scaled to a phone-width thumbnail.
