# Style Tests v0 — contact sheet (E0.1 → George sign-off G0.1)

10 test sprites in `assets/style-tests/`, generated with gpt-image-1
(1024×1024, quality medium, `background=transparent`, direct curl).
14 API calls total (10 subjects + 4 framing regens) ≈ **$0.62** — under the
$5 cap, regen cap (4) fully used.

Every prompt = locked preamble + class suffix + negative constraints from
`docs/art/prompt-template.md`, plus the per-sprite subject description below.
The 4 regens appended a keep-inside-the-frame margin sentence.

Verified programmatically: all 10 are 1024×1024 RGBA, corner pixels alpha=0
(true transparency, no matte), 0% semi-transparent pixels (hard-edged alpha,
no baked glow halo). Note when viewing raw files: some viewers show a
mustard/brown "background" — that is dead RGB under zero alpha; it never
renders when composited.

## Humanoid NPCs

### everquill-npc-tavern-keeper.png
Subject: "A stout middle-aged tavern keeper with a friendly broad face, short chestnut-brown hair and stubble, rolled-up cream shirt sleeves, a light tan leather apron over dark trousers, holding a single pewter tankard in one hand at his hip."
Assessment: **FAIL (framing)** — style/palette/outline on-spec, but head grazes the top edge and boots are clipped at the bottom even after regen; proportions ~4.5 heads (low end, stout build).

### everquill-npc-scarred-traveler.png
Subject: "A weathered woman in her thirties with a pale scar crossing her left cheek, dark hair tied back, dressed in worn brown traveling leathers with a dark belt, a buckled satchel strap across the chest, and sturdy boots." (Model added a held short sword — acceptable single signature prop.)
Assessment: **BORDERLINE (framing)** — best humanoid of the batch: ~5 heads, scar reads, leathers on-palette, silhouette strong; boot tips clipped at the bottom edge.

### everquill-npc-guild-receptionist.png
Subject: "A tidy young guild receptionist woman with ash-blonde hair in a neat bun, wearing a fitted slate blue-grey uniform vest with brass buttons over a cream blouse and a long dark skirt, holding a closed leather-bound ledger against her front."
Assessment: **FAIL (framing)** — costume/ledger/pose on-spec, but hair grazes the top and the skirt hem is cut at the bottom (feet never visible) in both attempts.

### everquill-npc-skill-church-sister.png
Subject: "A serene church sister in a cream vellum-white habit and hood with deep ink-blue trim at the edges, a small brass quill emblem hanging at her chest, hands folded together in front of her waist."
Assessment: **BORDERLINE (proportions)** — figure complete and reads whole (veil/hem touch edges without visible amputation); vellum + ink-blue + brass quill landed exactly on the Inked System look; but ~4 heads, chibi-adjacent, below the 4.75-head floor.

## Creatures

### everquill-creature-slime.png
Subject: "A small rounded fantasy slime creature, a soft dome-shaped blob of muted jade green jelly with a slightly darker green core visible inside, two simple dark dot eyes near its front."
Assessment: **PASS** — left-facing, in-frame, clean 2-step shading, silhouette instantly readable; green is sage-muted, slightly desaturated vs Slime Jade `#7FB069`.

### everquill-creature-goblin.png
Subject: "A scrawny goblin with mossy olive-green skin, hunched posture, long pointed ears and a hooked nose, wearing a ragged brown loincloth and a crude leather strap, gripping a short wooden club held low."
Assessment: **PASS (with notes)** — full body after regen, left profile, great hunched silhouette; toes graze the bottom edge but read complete; skin drifted olive-tan rather than Goblin Moss green.

### everquill-creature-ash-wolf.png
Subject: "A lean predatory wolf with sooty ash-grey fur, darker charcoal along the back and muzzle, faint pale grey underbelly, and a single ember-orange eye accent, standing alert with hackles slightly raised."
Assessment: **PASS** — left profile, fully in-frame, ember eye accent works, tail readable; faint canvas-grain texture in fills (mild no-texture-noise violation).

## Items

### everquill-item-healing-draught.png
Subject: "A small round-bellied glass potion vial with a short neck, filled with deep crimson liquid, stoppered with a simple cork and tied with a thin leather cord at the neck."
Assessment: **PASS** — 45° hero shot, in-frame, Draught Crimson + cork + cord all present; glass highlights slightly soft (borderline vs hard-edge rule).

### everquill-item-rank-plate.png
Subject: "A rectangular adventurer guild rank plate of polished brass with softly rounded corners, a plain blank face with a simple embossed border line, hanging from a short dark leather neck cord through a punched hole at the top."
Assessment: **PASS** — cleanest of the batch: blank face (rank letter stays a UI overlay), embossed border, brass on-palette, no text anywhere.

### everquill-item-leather-journal.png
Subject: "A thick leather-bound journal with a worn oxblood-brown cover, a wrap-around dark leather strap and small brass clasp, slightly ragged cream page edges visible along the side."
Assessment: **PASS** — the heir-fiction object reads perfectly: oxblood cover, strap + brass clasp, vellum page edges; in-frame, strong 120px silhouette.

## Summary vs acceptance checklist

| Check | Result |
|---|---|
| Anatomy sane | 10/10 |
| Proportions (4.75–5.25 heads) | 2/4 humanoids in band; keeper low, sister chibi-adjacent |
| Palette compliance | 8/10 clean; slime + goblin drifted muted/tan |
| Outline consistency | 10/10 |
| Shading in limits | 9/10 (draught glass soft highlights; wolf grain) |
| Silhouette at 120px | 10/10 |
| Pose-lock | 10/10 (views/angles all correct) |
| Transparent background | 10/10 (verified alpha) |
| No UI/text/watermarks | 10/10 |
| Uncropped in frame | 6/10 — all 3 creatures + all 3 items pass; humanoid NPCs clip |

**Systematic finding for v1:** gpt-image-1 + transparent background reliably
slams full-body humanoids into the top/bottom frame edges; the mid-prompt
margin sentence only partially helps. Recommend for prompt-template v1 (after
George's style call): change the fill clause for humanoids to "fills about 70
percent of the frame height, with clear empty margin above the head and below
the feet" — items/creatures already behave. Alternative: generate humanoids
with ~5% outpaint headroom or post-crop from a taller framing.

**For George (G0.1):** style direction, palette, and the Inked System look are
represented; the sign-off calls are (1) is this flat-LN register right, (2)
proportion strictness (sister/keeper drift toward 4 heads), (3) approve the
v1 framing fix above before batch generation.

---

# Batch 2 — Sprint 1 contact sheet (template v1.1 → George sign-off G1.1)

4 NPC regens in `assets/style-tests/batch-2/`, 1 tavern background in
`assets/backgrounds/`, 3 programmatic placeholders in `assets/placeholders/`.
11 API calls (4 base regens + 6 retries — retry cap fully used — + 1
background) ≈ **$0.52** against the $5 cap. All sprites verified: 1024×1024
RGBA, corner alpha 0, no solid pixel touching any frame edge.

## How the framing fix actually played out (read this first)

- **v1.1 clause alone (70% + head/feet margin sentence inside the class
  suffix): 0/4.** All four base regens slammed the figure into both the top
  and bottom edges, same as batch 1.
- **Retry round with the same clause FRONT-LOADED as the prompt's opening
  sentence** (60% target, "at least 15 percent empty margin above the head
  and below the feet", figure "floating in the center of a mostly empty
  transparent canvas"): **4/4 fully inside the frame.** Position in the
  prompt mattered more than the number.
- Retry prompt additions used (documented for the v1.2 decision):
  - Prefix: "A zoomed-out full-body character sprite floating in the center
    of a mostly empty transparent canvas. The entire figure, including the
    top of the head and the soles of both feet, is completely inside the
    frame with large empty transparent margins on every side: the figure
    occupies only the central 60 percent of the canvas height, leaving at
    least 15 percent of the canvas height as empty margin above the head and
    at least 15 percent as empty margin below the feet."
  - Tail: "The figure must not touch any edge of the canvas. No outer glow
    and no soft halo around the figure; the silhouette edge is hard and
    clean." Final keeper/sister attempts added anti-chibi + anti-texture
    emphasis ("adult with stylized light-novel proportions about five heads
    tall", "no canvas grain, paper texture, hatching, or scribble strokes").
- **New model behavior this batch:** every raw render carried a baked
  semi-transparent glow halo around the figure (6–12% semi-alpha; batch 1 had
  0%), and one render (sister, final attempt) came back with a
  semi-transparent wash over the whole canvas. Fixed with a deterministic
  **alpha-clean post-process**: keep the solid figure (alpha>200) plus its
  ~3 px anti-aliasing ring, zero all detached low-alpha. Raw outputs
  archived off-repo; committed files are the cleaned ones. This step needs a
  yes/no as a standard pipeline stage (Q4 below).

## Humanoid NPC regens (subjects verbatim from batch 1 — clean A/B)

### batch-2/everquill-npc-tavern-keeper.png
Prompt: batch-1 subject + v1.1 template + retry prefix/tail + anti-chibi/anti-texture emphasis (attempt 3 — attempt 1 clipped both edges, attempt 2 collapsed to ~3-head chibi and lost the stubble).
Framing: **FIXED** — solid figure fills 78.6% of frame height, margins 129 px above / 88 px below (batch-1 failure: head grazed top, boots clipped).
Checklist: anatomy PASS; proportions **~4 heads, below the 4.75 floor** (same call batch 1 raised; the anti-chibi emphasis pulled it up from 3, not to 5); palette PASS; outline PASS; shading PASS (very light grain); 120 px silhouette PASS; pose-lock PASS (tankard held low); transparency PASS after alpha-clean (raw had halo); no text PASS; **uncropped PASS**.

### batch-2/everquill-npc-scarred-traveler.png
Prompt: batch-1 subject + v1.1 template + retry prefix/tail (attempt 2 — attempt 1 clipped both edges).
Framing: **FIXED** — fills 88.8%, margins 72 px / 40 px (batch-1 failure: boot tips clipped). Over the 70% target but comfortably inside the frame.
Checklist: anatomy PASS; proportions ~4.5–4.75 heads, borderline low; palette PASS; outline PASS; shading **BORDERLINE** (visible canvas-grain texture in fills); 120 px PASS; pose-lock PASS (sword prop held low, batch-1 precedent); transparency PASS after clean; no text PASS; **uncropped PASS**. **Miss: the cheek scar did not render** (blush marks only) — the signature feature is absent at every scale; batch-1's render had it. Retry cap was spent on framing; flagged as Q3.

### batch-2/everquill-npc-guild-receptionist.png
Prompt: batch-1 subject + v1.1 template + retry prefix/tail (attempt 2 — attempt 1 clipped both edges).
Framing: **FIXED, but tight** — feet fully visible for the first time (batch-1 failure: skirt hem cut, feet never visible in two attempts); solid figure fills 94.9% with only ~5 px below the shoes. Uncropped, but way over the 70% target.
Checklist: anatomy PASS (face coherent, small mouth present); proportions ~5–5.5 heads, in band — **best-proportioned humanoid across both batches**; palette PASS (slate vest, brass buttons, cream blouse); outline PASS; shading PASS (flattest of the four); 120 px PASS; pose-lock PASS (ledger at front); transparency PASS after clean; no text PASS; **uncropped PASS**.

### batch-2/everquill-npc-skill-church-sister.png
Prompt: batch-1 subject + v1.1 template + retry prefix/tail + anti-chibi/anti-texture emphasis (attempt 3 — attempt 1 clipped both edges, attempt 2 was covered in scribble/hatch texture).
Framing: **FIXED** — fills 86.9%, margins 119 px / 21 px (batch-1 was BORDERLINE-complete; now clearly inside).
Checklist: anatomy PASS (hands slightly mitteny); proportions **~4 heads, chibi-adjacent — same finding as batch 1, twice in a row on this subject**; palette **BORDERLINE** (trim rendered desaturated slate-grey rather than Quill Ink blue; the brass quill emblem became a faint pale loop — batch 1 landed both better); outline PASS; shading PASS (minor hatch remnant in hood interior); 120 px PASS; pose-lock PASS; transparency: **raw render FAILED** (semi-alpha wash across the entire canvas, corners at alpha 58–126) → PASS after documented alpha-clean; no text PASS; **uncropped PASS**.

## Scene background (new class — style-bible §10)

### backgrounds/everquill-bg-tavern-interior.png
Prompt: §10 background preamble + location description (long communal tables and benches to the sides, back-wall bar with brass fittings and shelves of jugs and tankards, hanging iron lanterns with flat flame shapes, large cork notice board pinned with small blank parchment scraps, parchment plaster + dark timber beams, worn floorboards across the open lower third) + background negatives. One generation, no retries.
Checklist (§10): palette PASS (Road Leather / Buffhide / Parchment / Sepia register, warm and lived-in); flat fills PASS (minor plaster grain, small contained lantern glows); zero characters/creatures PASS; **floor band PASS with note** — flanking table and bench legs enter the lower-third band at the far left/right edges; the central ~50% of the width is clean open floorboards where sprites will actually stand; 1536×1024 opaque PASS; eye-level VN framing PASS; no readable text PASS (notice-board scraps are blank shapes); thumbnail legibility PASS. Rumor-hub energy: notice board + long tables + lanterns all read.

## Placeholder silhouettes (programmatic, Pillow — zero API cost)

`assets/placeholders/npc-silhouette.png`, `creature-silhouette.png`,
`item-silhouette.png` — 1024×1024 transparent, Steel Light `#9FA8B2` flat
fill, Outline Ink `#2A2430` uniform ~10 px contour (interior lines at 60%
weight on the item cube). Deliberately generic pictograms: standing humanoid
at the v1.1 70% fill target, left-facing quadruped, 45° crate. They read as
"art loading", not failed art, and match the class pose-locks so async swaps
don't jump.

## Batch 2 summary vs acceptance checklist

| Check | Result |
|---|---|
| Uncropped in frame | **4/4 humanoids** (batch 1: 0/4) — the sprint's target fix, landed |
| Anatomy sane | 4/4 |
| Proportions (4.75–5.25 heads) | 2/4 (receptionist in band, traveler borderline; keeper + sister ~4 heads — repeat of batch-1 finding) |
| Palette compliance | 3/4 clean (sister's ink-blue trim + brass emblem degraded vs batch 1) |
| Outline consistency | 4/4 |
| Shading in limits | 3/4 (traveler canvas grain) |
| Silhouette at 120 px | 4/4 |
| Pose-lock | 4/4 |
| Transparent background | 4/4 after alpha-clean (0/4 raw — halos are new model behavior this batch) |
| No UI/text/watermarks | 4/4 |
| Background §10 checklist | 8/8, one noted concession (flank furniture at band edges) |

## Sign-off questions for George (G1.1)

1. **Framing/template:** the fix works but only front-loaded — approve
   promoting the retry framing prefix into the template as **v1.2** (v1.1's
   in-suffix clause alone went 0/4)?
2. **Proportion strictness (carried from G0.1, now with data):** keeper and
   sister landed ~4 heads in BOTH batches even with explicit anti-chibi
   emphasis. Accept a widened 4.0–5.25 band (these two subjects read fine in
   the 120 px strip), or hold the 4.75 floor and budget re-rolls with
   proportion-first prompt surgery?
3. **Traveler's scar:** absent in the batch-2 render (retry cap went to
   framing). Accept — the scar also lives in narration/known-sheet — or
   spend one regen from the next batch's budget?
4. **Alpha-clean post-process:** approve as a standard pipeline step? The
   model baked glow halos into all raw renders this batch and one full
   canvas wash; the clean is deterministic (keep solid figure + 3 px AA
   ring) and rescued everything without touching the art itself.
5. **Tavern background:** approve the register, and accept flanking
   furniture at the floor-band edges (sprites stand center), or regen with a
   harder empty-floor clause?
6. **Placeholders:** approve the three grey pictograms as the async-gen
   placeholder look for Team D's tableau.

---

# Batch 3 — Sprint 2 contact sheet (template v1.2 — George standing approvals applied, no sign-off gate)

Template v1.2 promoted (framing prefix front-loaded — the batch-2 position
finding), alpha-clean now a STANDARD pipeline step, and the portrait
pipeline v1 (`tools/spritegen/generate.py`) ran the full Harrowdown roster.
**35 API calls ≈ $1.60 against the $10 cap:** 9 regen attempts + 24 pipeline
sprite calls (1024×1024, quality medium, transparent) + 2 backgrounds
(1536×1024, medium, opaque). Raw renders archived off-repo.

**Raw-halo update:** the batch-2 glow-halo behavior mostly did not recur —
raw semi-alpha ran 0.24–0.41% this batch (batch 2: 6–12%). Alpha-clean
stayed on as the standard step and was effectively a no-op on most renders;
it still catches the bad days. Corner alpha 0 and no-edge-contact verified
programmatically on every committed sprite.

## Regen A/B — keeper + sister (proportion re-rolls), traveler (scar)

Subjects verbatim from batch 1. All attempts kept in
`assets/style-tests/batch-3/` (`-attempt-N` files); canonical files are the
chosen finals. 3-attempt budget each (George-approved).

### batch-3/everquill-npc-tavern-keeper.png (= attempt 3; attempts 1–2 failed)
- A1 (v1.2 prompt + proportion block in slot 2, after the framing prefix):
  framing clean (74.5% fill) but **~3.7 heads** — slot-2 emphasis does
  nothing, matching batch 2.
- A2 (proportion block promoted to the prompt's FIRST sentence, framing
  prefix second): **~4.3 heads**, framing held (90.2%).
- A3 (keeper-specific wording "broad and heavy through the chest and belly
  but TALL, never squat" first): **~5.1 heads — IN BAND**, first time in
  three batches. Fill 97.2%, margins 17/12 px — tight but uncropped.
- Final checklist: anatomy PASS; proportions **PASS (~5.1)**; palette PASS;
  outline PASS; shading PASS (very light grain); 120 px PASS; pose-lock
  PASS (tankard at hip); transparency PASS (raw semi-alpha 0.41% →
  cleaned); no text PASS; uncropped PASS (tight margins noted).

### batch-3/everquill-npc-skill-church-sister.png (= attempt 2; attempt 3 regressed)
- A1 (slot-2 proportion block): ~3.8 heads, canvas grain — FAIL.
- A2 (proportion-first + habit-column wording): **~5.2 heads — IN BAND.**
  Fill 90.6%, margins 46/50 px.
- A3 (added trim/emblem palette push): trim stayed slate, emblem went
  grey-feather, and proportions slid back to ~4.6 — A2 kept.
- Final (A2) checklist: anatomy PASS; proportions **PASS (~5.2)**; palette
  **BORDERLINE** (trim renders desaturated slate rather than Quill Ink, the
  brass quill emblem reads as a plain brass drop — third batch running for
  this drift; UI layer may end up owning the emblem); outline PASS; shading
  PASS; 120 px PASS; pose-lock PASS; transparency PASS; no text PASS;
  uncropped PASS.

### Scarred traveler — **NO PASSING RENDER, 3 attempts spent (EXCEPTION)**
- A1 (v1.2: framing prefix first, scar emphasis second): framing and
  proportions excellent (~5 heads) — **scar absent.**
- A2 (scar emphasis first, framing second): scar came out as a
  smudge/blush, figure collapsed to ~4 heads with mitten gloves.
- A3 (scar-first with geometric wording + proportion block): **the scar
  finally rendered** (short pale line, clearly legible) — but the combined
  long front block cost the framing prefix its slot: 100% fill, head and
  boots on the frame edges. Checklist FAIL (uncropped).
- **Verdict: batch-1 traveler remains the canonical render** (scar present,
  boot-tips borderline). Lesson recorded below. Options for batch 4: accept
  scar-in-narration (George's original Q3 alternative) or spend one attempt
  on "scar sentence first, framing prefix IMMEDIATELY second, nothing else
  up front" — untested combination.

### Template finding (recorded for v1.3 consideration)
**The front slot is singular.** Whatever block opens the prompt wins;
whatever it displaces degrades. Proportion-first fixed proportions 4/4
(keeper A2/A3, sister A2/A3, rold) but framing held in only 5 of 9
proportion-first renders across the batch — the pipeline now runs one
bounded auto-retry (drop the proportion block, framing-first) on framing
failure, which caught all three NPC failures (maren/fenn/jorun). Long
combined front blocks (traveler A3) break framing outright.

## Portrait pipeline v1 — full Harrowdown run (15 entities)

`tools/spritegen/generate.py`: reads `content/world/harrowdown.yaml`, builds
the v1.2 prompt (class suffix by kind, authored visual descriptions, secret
tags excluded), calls gpt-image-1, alpha-cleans, validates (size / true
transparency / edge margins), writes `assets/sprites/<entity_id>.png` +
`assets/sprites/manifest.json` (entity_id, file, template_version,
prompt_sha, generated_at). Idempotent — manifest entries skip unless
`--force`. Verified: a second `--all` run made zero API calls.

| entity | outcome | calls | notes |
|---|---|---|---|
| npc.maren_ostler | generated | 3 | proportion-first framing fail → auto-retry PASS; ~4.7–5 heads; tankard at chest height |
| npc.fenn_bracey | generated | 3 | same auto-retry path; ~5 heads; ledger reads, chest plate faint (buttons only) |
| npc.jorun_pike | generated | 3 | same auto-retry path; **withered left arm rendered clearly** (signature-feature slot 2 works); plate rendered heart-shaped (off-canon shape, no text) |
| npc.elam_ferrier | generated | 1 | clean first roll; ~4.6 heads borderline-low; oil flask present |
| npc.rold_tanner | generated | 2 | first roll ~4.2 heads → re-roll with "tall heavyset" **~5.0 IN BAND**; coin pouch held low |
| npc.sister_odile | reused batch-3 | 0 | the sister regen final (A2) |
| creature.ditch_slime | reused batch-1 | 0 | checklist PASS in batch 1 |
| creature.cairn_rat | generated | 3 | nose+tail hit BOTH side edges twice (new systematic finding: long low quadrupeds); third roll landed 12/17 px side margins |
| creature.chalk_adder | generated | 1 | S-curve, head left, parchment mottling — clean |
| creature.downland_wolf | reused batch-1 | 0 | side margins 8/4 px — legal but tightest sprite in the set |
| creature.barrow_wight | generated | 2 | framing fail → auto-retry WITH new creature framing prefix PASS; ink-blue eye pinpricks present |
| creature.quarryman | generated | 3 | rolls 1–2 grew front legs (dragon, lore violation — "still no dragon"); roll 3 with bat/pterosaur wording = proper 2-legged wyvern |
| prop.guild_board | generated | 1 | blank parchment scraps, zero text |
| prop.reyla_grave | generated | 1 | blank worn face; wax flowers slightly saturated vs muted-crimson intent |
| item.marriage_seal | generated | 1 | worn crimson wax, indistinct impression, no letters |

**Creature framing prefix (new, retry-only):** long-bodied creatures in
strict left profile slam nose/tail into the side edges (cairn rat 2/2, wolf
reuse nearly). The pipeline's bounded retry now front-loads a
creature-worded framing prefix (70% of canvas WIDTH target) — validated
once (barrow wight). Candidate for v1.3 as a first-shot clause for
wide-aspect creatures.

## Scene backgrounds (×2) — with slot-band notes for Team B/D

Both 1536×1024 opaque, one generation each, §10 checklist PASS with the
same flanking-furniture concession George accepted for the tavern (set
dressing dips into the 67–80% strip at the edges; the bottom fifth is
genuinely clear).

### backgrounds/everquill-bg-guild-hall-interior.png
Counter along the back wall (ledgers, hand-bell, blank plate rack), posting
board left with blank pinned scraps, benches right, plaster + timber,
lanterns. No people, no text.
**Usable sprite band: feet y ≈ 80–98% of frame height, x ≈ 2–80% of width.**
Counter base line sits at y≈76% (rear walk limit); benches occupy the
band's right edge (x > 80%). Center is generously clear — slot the main
conversation line at y ≈ 84–96%, x ≈ 10–75%.

### backgrounds/everquill-bg-market-row.png
Timber-framed houses closing the far side, covered well mid-frame, empty
stalls tucked far left/right, blank signboard, packed earth + cobbles.
**Usable sprite band: feet y ≈ 80–98%, clear across the FULL width.**
The well base bottoms out at y≈78% center (x ≈ 37–55%) — keep center
slots' feet below y=80%; left stall base reaches y≈74% at x < 19%. Slot
the main line at y ≈ 84–96%, any x.

## Batch 3 summary vs acceptance checklist

| Check | Result |
|---|---|
| Uncropped in frame | 15/15 committed sprites (auto-retry caught 4 in-flight framing fails) |
| Anatomy sane | 15/15 (quarryman needed 3 rolls to lose the dragon forelegs) |
| Proportions (4.75–5.25) | keeper ~5.1 + sister ~5.2 + rold ~5.0 + fenn ~5 + maren ~4.8 in band; elam + jorun ~4.6 borderline-low (read fine at 120 px, batch-1 traveler precedent) |
| Palette compliance | clean except: sister trim/emblem drift (3rd occurrence), grave flowers slightly saturated, jorun plate heart-shaped |
| Outline consistency | 15/15 |
| Shading in limits | PASS (light grain on keeper; nothing at batch-2 traveler level) |
| Silhouette at 120 px | 15/15 |
| Pose-lock | 15/15 |
| Transparent background | 15/15 verified post-clean (corners 0, semi-alpha ≤0.4%) |
| No UI/text/watermarks | 15/15 (board scraps + seal face + gravestone all blank) |
| Background §10 checklist | 2/2 PASS, band notes above |

**Exception carried (the only one): the scarred-traveler scar regen — 3/3
attempts failed the full checklist** (details above; batch-1 render stays
canonical). Everything else ships under George's standing approvals.
