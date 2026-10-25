# Everquill Prompt Template v1.2 (locked — implements docs/art/style-bible.md)

**Changelog v1.2 (Sprint 2, batch 3 — George-approved, sprint-2 decisions
header):** the batch-2 retry framing prefix is promoted into the template as
the **opening sentence of every humanoid sprite prompt**. Batch 2 measured
the same margin language going **0/4 in-frame mid-prompt vs 4/4 front-loaded**
— position beats wording. The v1.1 in-suffix frame-fill sentence is removed
from the humanoid suffix (the prefix owns framing now; contradicting numbers
would fight it). Also locked: the **framing tail** after the negatives; a
**signature-feature emphasis** rule (must-render features go to the prompt's
front, same position lesson); **alpha-clean as a STANDARD pipeline step** for
all transparent sprites (batch-2 halo finding); and an **exterior variant** of
the background preamble. Creatures and items are unchanged — they framed
correctly in both batches and take no prefix. Pipeline implementation:
`tools/spritegen/generate.py`.

**Changelog v1.1 (Sprint 1, batch 2):** humanoid framing fix per batch-1
findings (`style-tests.md`) — the frame-fill clause moved out of the shared
preamble into the class suffixes; humanoids now fill **~70%** of frame height
with an explicit empty-margin sentence above the head and below the feet
(was 80%, which clipped all 4 batch-1 humanoids at the frame edges).
Creatures stay at 80%, items at 70% — both classes already framed correctly.
Also new: **Scene background** block (landscape 1536×1024, opaque) — see
style-bible §10. *(Superseded for humanoids by v1.2: the in-suffix clause
alone went 0/4.)*

For **gpt-image-1**, direct API. Prompt formulas (v1.2):

- **Humanoid NPC** = `FRAMING PREFIX` (+ optional `SIGNATURE-FEATURE
  EMPHASIS`) `+ PREAMBLE + NPC SUFFIX + subject description + NEGATIVE
  CONSTRAINTS + FRAMING TAIL`.
- **Creature / Item** = `PREAMBLE + CLASS SUFFIX + subject description +
  NEGATIVE CONSTRAINTS`.

API params are part of the lock: `model=gpt-image-1`, `size=1024x1024`,
`background=transparent`, `output_format=png`. Style tests use
`quality=medium`; production entities may use `medium` or `high` per batch
budget. (Scene backgrounds override size/background — see their block below.)

Do not edit clauses per-sprite. Subject descriptions add content, never style.

## Framing prefix (locked, v1.2 — MUST be the humanoid prompt's OPENING sentence)

> A zoomed-out full-body character sprite floating in the center of a mostly
> empty transparent canvas. The entire figure, including the top of the head
> and the soles of both feet, is completely inside the frame with large empty
> transparent margins on every side: the figure occupies only the central 60
> percent of the canvas height, leaving at least 15 percent of the canvas
> height as empty margin above the head and at least 15 percent as empty
> margin below the feet.

Position is load-bearing: this block opens the prompt, before the preamble.
Moving it later in the prompt is a template violation (batch-2 data: 0/4
mid-prompt, 4/4 front-loaded).

## Framing tail (locked, v1.2 — appended after the negatives on humanoid prompts)

> The figure must not touch any edge of the canvas. No outer glow and no soft
> halo around the figure; the silhouette edge is hard and clean.

## Signature-feature emphasis (v1.2)

When an entity has a signature feature that MUST render (a scar, a ruined
arm, a badge of office), insert immediately after the framing prefix:

> The character's single most important identifying feature is {FEATURE}.
> {FEATURE} must be clearly visible.

and name the feature in the subject description's first clause. Same finding
as framing: front position is what makes the model honor it. Retry budget for
a missing signature feature: 3 attempts (George-approved, sprint 2).

---

## Preamble (locked, 13 clauses)

> Flat-color 2D game sprite in Japanese light-novel illustration style.
> Clean closed ink outlines in warm near-black (#2A2430), uniform weight, with thinner interior detail lines.
> Flat cel shading only: each surface is one solid fill plus at most one hard-edged warm shadow step and at most one hard-edged highlight step.
> No gradients, no airbrushing, no texture noise, no glow.
> Muted storybook palette: warm parchment neutrals, earthy browns and leathers, desaturated iron and brass metals, with restrained ink-blue accents only where the subject calls for them.
> Humanoid figures are about five heads tall — stylized light-novel proportions, clearly not chibi and clearly not realistic adult proportions.
> Exactly one subject, complete and uncropped.
> Centered composition.
> Strong, instantly readable silhouette that survives being shrunk very small.
> Even neutral front-lighting, no dramatic rim light or colored stage lighting.
> Transparent background with no scenery, no ground plane, and no cast or contact shadow.
> Crisp clean vector-like finish with solid uniform color fills.
> No text, no letters, no numbers, no watermark, no signature, no logo, no frame, no user-interface elements.

## Class suffixes (locked — humanoid framing moved to the v1.2 prefix; creature/item keep their v1.1 fill clauses)

**Humanoid NPC (v1.2 — frame-fill sentence removed; the framing prefix owns framing):**
> Full-body neutral standing pose in three-quarter view turned toward the viewer's left, weight even on both feet, arms relaxed at the sides or holding a single signature prop below chest height, calm neutral expression.

**Creature:**
> Full-body left-facing profile view, head and snout pointing toward the viewer's left, neutral standing idle stance, all limbs visible, tail readable in the silhouette if the creature has one, filling about 80 percent of the frame height.

**Item:**
> A single item alone at a 45-degree hero angle showing its front face and one side, floating on the transparent background, no hands, no table or surface, filling about 70 percent of the frame.

## Scene background block (new in v1.1 — implements style-bible §10)

Backgrounds do NOT use the sprite preamble (its transparency and
single-subject clauses conflict). A background prompt =
`BACKGROUND PREAMBLE + location description + BACKGROUND NEGATIVES`.
API parameter overrides: size 1536 by 1024, background `opaque` (omit the
transparent flag), output format `png`, quality `medium` unless the batch
budget says `high`.

**Background preamble (locked):**
> Flat-color 2D game scene background in Japanese light-novel illustration style, interior environment art with no people and no creatures.
> Clean ink outlines in warm near-black, uniform weight, with thinner interior detail lines.
> Flat cel shading only: each surface is one solid fill plus at most one hard-edged warm shadow step and at most one hard-edged highlight step, no gradients, no airbrushing, no texture noise, no bloom.
> Muted storybook palette: warm parchment neutrals, earthy browns and leathers, desaturated iron and brass, restrained ink-blue accents only where the scene calls for them.
> Straight-on wide interior view at standing eye level, like a visual-novel location backdrop.
> The lower third of the image is a clear, open, uncluttered floor area with no furniture or props inside it, so characters can be composited standing there; furniture and set dressing sit in the middle and upper bands of the frame.
> Even warm interior lighting, no dramatic light shafts, no lens effects.
> Crisp clean vector-like finish with solid uniform color fills.

**Background negatives (locked):**
> Do not include any people, characters, creatures, animals, or silhouettes of them. Do not use photorealism, 3D rendering, painterly brushwork, or pixel art. Do not add gradients, soft shading, bloom, sparkles, fog, or lens effects. Do not add any readable text, letters, numbers, signage lettering, posters with words, or watermarks. Do not add user-interface elements, frames, or borders. Do not place furniture, props, or clutter in the lower third of the image.

**Location description rules:** 1–3 sentences, concrete set dressing named by
palette role (style-bible §5), what mood the room carries, which fixtures are
visible in the mid/upper bands. Never restate style words; never request
readable text (notice boards and signs stay blank or use illegible scribble
marks per §10).

**Exterior variant (v1.2):** for outdoor locations (square, street, road),
three clauses of the background preamble swap wording — everything else is
identical, including the lower-third clear ground band:

- "interior environment art" → "outdoor environment art"
- "Straight-on wide interior view at standing eye level" → "Straight-on wide
  exterior street-level view at standing eye level"
- "Even warm interior lighting, no dramatic light shafts, no lens effects" →
  "Even warm daylight under a lightly overcast sky, no dramatic shadows, no
  light shafts, no lens effects"

The floor-band clause reads "ground area" instead of "floor area" for
exteriors. The negatives are unchanged (no people applies doubly outdoors).

## Negative constraints (locked — appended verbatim to every sprite prompt; backgrounds use their own negatives above)

> Do not use chibi or super-deformed proportions. Do not use realistic seven-or-eight-head adult proportions. Do not use photorealism, 3D rendering, painterly brushwork, or pixel art. Do not add gradients, soft shading, bloom, sparkles, or lens effects. Do not add any background, floor, shadow, frame, or border. Do not add any text, runes, letters, numbers, health bars, status boxes, or watermarks. Do not add extra characters, props, or duplicate views of the subject.

## Subject description rules

- 1–3 sentences, concrete and physical: build, age, clothing, materials,
  the ONE signature feature, and palette-role words ("worn brown road
  leather", "brass fittings", "ink-blue trim") — never hex codes in prompts.
- Name materials by palette role (style-bible §5) so fills land on-palette.
- Never restate style words (the preamble owns style). Never request text on
  objects — rank letters, labels, and titles are applied by the UI layer.

## Alpha-clean (STANDARD pipeline step as of v1.2 — George-approved)

Batch 2 finding: the model bakes a semi-transparent glow halo around the
figure into raw transparent renders (6–12% semi-alpha pixels; one render came
back with a semi-alpha wash across the whole canvas). Every transparent
sprite is therefore post-processed deterministically before commit:

1. **Keep** all solid pixels (alpha > 200) plus a ~3 px anti-aliasing ring
   around them (ring pixels keep their original partial alpha).
2. **Zero** the alpha of everything else — detached low-alpha halo, wash,
   stray specks.

The clean never touches the art itself, only detached low-alpha. It is a
no-op on an already-clean render (idempotent). Raw renders are archived
off-repo; committed files are always the cleaned ones.

**Post-clean validation (every sprite):** exact canvas size and RGBA mode;
all four corner pixels alpha 0 (true transparency, no matte); no solid
(alpha > 200) pixel on any frame edge; residual semi-alpha ≤ 1% of pixels.
Implemented in `tools/spritegen/generate.py`.

## Worked example (scarred traveler, v1.2 humanoid formula)

> [FRAMING PREFIX] The character's single most important identifying feature
> is a long pale scar crossing her left cheek. The scar must be clearly
> visible. [PREAMBLE] [NPC SUFFIX] A weathered woman in her thirties with a
> pale scar crossing her left cheek, dark hair tied back, dressed in worn
> brown traveling leathers with a dark belt, buckled satchel strap across the
> chest, and sturdy boots. [NEGATIVE CONSTRAINTS] [FRAMING TAIL]
