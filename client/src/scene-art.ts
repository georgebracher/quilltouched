/**
 * Scene art mapping — backgrounds by location type, sprites by entity id
 * (Team D, Sprint 2, layout v2).
 *
 * Sprite PNGs are copied verbatim from assets/sprites/ (Team E's
 * gen-at-commit pipeline output) into public/sprites/, KEEPING their
 * dotted-id filenames. The sprite manifest (assets/sprites/manifest.json)
 * keys art by DOTTED entity id (`npc.harrowdown.maren_ostler`); the scene
 * manifest carries CONTRACT ids (`npc_harrowdown_maren_ostler`).
 *
 * ID conversion is deliberately ONE-WAY: the engine's rule is
 * dotted -> contract via '.' -> '_' (everquill_engine/resolver.py
 * contract_id). The reverse is AMBIGUOUS — entity names legally contain
 * underscores (maren_ostler), so a contract id cannot be split back into
 * dots. The lookup below is therefore built in the safe direction only:
 * every known dotted id is converted to its contract form at module load.
 *
 * Entities with no art are drawn as a name label, never a grey placeholder
 * figure; the player's own character is not drawn (the scene is their view).
 *
 * Pure module (no React, no fetch, no import.meta.env) so it can be
 * driven headlessly for verification.
 */

/**
 * Per-sprite art metrics, keyed by DOTTED id (assets/sprites/manifest.json).
 * The PNGs are 1024x1024 with transparent padding, so the image box is not the
 * figure: `top`/`foot` are the visible content's top and bottom as fractions of
 * the image height (measured from the alpha channel), and `height` is how tall
 * the figure stands in the scene as a fraction of the background's height at
 * the bar-front depth (y 75%). People are ~0.36 there; vermin and small things
 * are scaled to match, so a ditch slime is not person-sized. Keep in sync when
 * Team E commits new sprites (and copy the PNG).
 */
const SPRITE_ART: Readonly<Record<string, { top: number; foot: number; height: number }>> = {
  'creature.harrowdown.barrow_wight': { top: 0.05, foot: 0.95, height: 0.38 },
  'creature.harrowdown.cairn_rat': { top: 0.17, foot: 0.88, height: 0.06 },
  'creature.harrowdown.chalk_adder': { top: 0.2, foot: 0.81, height: 0.05 },
  'creature.harrowdown.ditch_slime': { top: 0.22, foot: 0.79, height: 0.1 },
  'creature.harrowdown.downland_wolf': { top: 0.07, foot: 0.94, height: 0.18 },
  'creature.harrowdown.quarryman': { top: 0.05, foot: 0.95, height: 0.6 },
  'item.harrowdown.marriage_seal': { top: 0.06, foot: 0.91, height: 0.05 },
  'npc.harrowdown.elam_ferrier': { top: 0.05, foot: 0.96, height: 0.36 },
  'npc.harrowdown.fenn_bracey': { top: 0.07, foot: 0.95, height: 0.36 },
  'npc.harrowdown.jorun_pike': { top: 0.08, foot: 0.92, height: 0.37 },
  'npc.harrowdown.maren_ostler': { top: 0.02, foot: 0.97, height: 0.34 },
  'npc.harrowdown.rold_tanner': { top: 0.03, foot: 0.98, height: 0.37 },
  'npc.harrowdown.sister_odile': { top: 0.04, foot: 0.95, height: 0.35 },
  'prop.harrowdown.guild_board': { top: 0.04, foot: 0.96, height: 0.42 },
  'prop.harrowdown.reyla_grave': { top: 0.06, foot: 0.93, height: 0.18 },
}

export interface SpriteArt {
  src: string
  /** Image box width as a percentage of the stage width at this depth. */
  widthPct: number
  /** The visible foot line as a fraction of the image box height. */
  foot: number
}

const ART_BY_CONTRACT_ID: ReadonlyMap<
  string,
  { dotted: string; top: number; foot: number; height: number }
> = new Map(
  Object.entries(SPRITE_ART).map(([dotted, m]) => [
    dotted.replace(/\./g, '_'), // the engine's contract_id rule, applied forward
    { dotted, ...m },
  ]),
)

/** Stage height over width for the 1536x1024 backgrounds. */
const STAGE_H_OVER_W = 1024 / 1536

/**
 * Sprite for a CONTRACT-form entity id standing at depth `yPct` (its slot's
 * foot line), or null when no art exists. Nearer figures (larger y) draw
 * larger, in proportion to their distance down the floor.
 */
export function spriteFor(contractEntityId: string, yPct: number): SpriteArt | null {
  const art = ART_BY_CONTRACT_ID.get(contractEntityId)
  if (!art) return null
  const depth = yPct / 75
  const widthPct = ((art.height * STAGE_H_OVER_W) / (art.foot - art.top)) * 100 * depth
  return { src: `/sprites/${art.dotted}.png`, widthPct, foot: art.foot }
}

/**
 * Location type -> background file. Only three backgrounds exist (Team E
 * batches 2-3): tavern interior, guild hall interior, and Market Row —
 * which IS Harrowdown's `square` (content/world/harrowdown.yaml:
 * loc.harrowdown.market_row, type square; docs/art/style-tests.md band
 * notes). church / shop / road have no art yet: those types return null
 * and the canvas renders the vellum-dark fallback.
 */
const BACKGROUND_BY_TYPE: Readonly<Record<string, string>> = {
  tavern: '/backgrounds/everquill-bg-tavern-interior.png',
  guild_hall: '/backgrounds/everquill-bg-guild-hall-interior.png',
  square: '/backgrounds/everquill-bg-market-row.png',
}

export function backgroundFor(locationType: string | null): string | null {
  if (locationType === null) return null
  return BACKGROUND_BY_TYPE[locationType] ?? null
}

/**
 * Backgrounds are authored 1536x1024. Slot x_pct/y_pct are measured
 * against the FULL background composition (content/world/slots.yaml keeps
 * x within 33-68 precisely so a portrait center-crop never cuts a slotted
 * sprite) — so the renderer pins sprites to a stage that preserves this
 * aspect and center-crops horizontally inside the canvas.
 */
export const STAGE_ASPECT = '1536 / 1024'
