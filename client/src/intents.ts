/**
 * Canned intent catalogue — the composer's quick-pick chips (Team D;
 * authored Sprint 1, kept as suggestions beside the live free-text path
 * in Sprint 2 layout v2).
 *
 * Adapted from evals/golden-utterances.jsonl to Harrowdown's actual
 * scene entities (content/world/harrowdown.yaml). Every intent conforms
 * to intent.schema.json v1.3 in full. Rules honored:
 *
 * - Target ids are CONTRACT-form scene-entity ids; an intent is offered
 *   only when every target is present in the current GET /api/scene
 *   roster (fog-of-war honesty: never offer what the scene doesn't hold).
 * - Movement chips can be generated from GET /api/scene exits. This static
 *   catalogue still focuses on opening-room entity actions; dynamic exit chips
 *   belong with the scene composer.
 * - plausibility_hint never pre-judges (golden gu-002's rule): attempting
 *   is legal fiction; the engine owns the tier.
 * - These are hand-authored parses: tapping a chip sends the structured
 *   intent directly (no parser cost, no parse risk); the text box beside
 *   them goes through the live parser.
 *
 * Pure module (no React, no fetch, no import.meta.env) so it can be
 * driven headlessly for verification.
 */

import type { Intent, Scene } from './api'
import { shortLabel } from './render'

// Contract-form ids of the Drowned Ram's opening roster.
const MAREN = 'npc_harrowdown_maren_ostler'
const JORUN = 'npc_harrowdown_jorun_pike'
const SLIME = 'creature_harrowdown_ditch_slime'
const QUARRYMAN = 'creature_harrowdown_quarryman'

export interface CannedIntent {
  /** Stable key — also the retry identity for command_id reuse. */
  id: string
  /** The declaration as the player would speak it (transcript echo). A
   *  `{name}` stands for the first target as the player knows them: render
   *  through `chipLabel`, never directly (identity fog). */
  label: string
  /** Golden utterance(s) this adapts. */
  golden: string
  /** Kept in the catalogue but never offered as a chip. */
  hidden?: boolean
  intent: Intent
}

const base = {
  stat_hint: null,
  dialogue: null,
  plausibility_hint: 'plausible',
  duration_hint: null,
  ambiguity_flags: [],
  addressee: null,
  speech_act: null,
  topic_ids: [],
  transaction: null,
  invoked_law_ids: [],
  movement_scope: null,
} satisfies Partial<Intent>

// Spoken turns: one listener, plain statement unless the chip says otherwise.
const spoken = { addressee: 'person', speech_act: 'statement' } satisfies Partial<Intent>

export const CANNED_INTENTS: CannedIntent[] = [
  // --- generics: yourself / the room -------------------------------------
  {
    id: 'look-around',
    label: 'Look around',
    golden: 'gu-013/gu-035',
    intent: {
      ...base,
      action_type: 'observation',
      target_entity_ids: [],
      approach: 'a broad, unhurried scan of the taproom',
    },
  },
  {
    id: 'rest-night',
    label: 'Rest for the night',
    golden: 'gu-020',
    intent: {
      ...base,
      action_type: 'rest',
      target_entity_ids: [],
      approach: 'turn in for the night and let the hours pass',
      duration_hint: {
        mode: 'until_condition', text: 'until morning', until: 'dawn', amount: null, unit: null,
      },
    },
  },
  {
    id: 'wait-dusk',
    label: 'Wait until dusk',
    golden: 'gu-021',
    intent: {
      ...base,
      action_type: 'rest',
      target_entity_ids: [],
      approach: 'settle in and wait, letting the hours pass',
      duration_hint: {
        mode: 'until_condition', text: 'until dusk', until: 'dusk', amount: null, unit: null,
      },
    },
  },
  {
    // Not offered: training starts a timer, and the timer worker that ends
    // it was never built (audit 2026-10-24, claude #14), so the chip would
    // leave a timer that never completes. Typed training still resolves.
    id: 'train-evening',
    hidden: true,
    label: 'Train until evening',
    golden: 'gu-006/gu-031',
    intent: {
      ...base,
      action_type: 'train',
      target_entity_ids: [],
      approach: 'run drills in the yard behind the tavern until the light goes',
      stat_hint: 'finesse',
      duration_hint: {
        mode: 'until_condition', text: 'until evening', until: 'dusk', amount: null, unit: null,
      },
    },
  },
  {
    // De-spoilered 2026-07-14: the old label/approach named the wyvern +
    // Redcliff quarry the player hasn't discovered yet (playtest: this chip
    // "randomly spoke about the wyvern"). Now a generic local-news opener; if
    // there IS wyvern talk to surface, the engine reveals it — the chip never
    // hands over the mystery. Discovery-gated specific chips are the S4 fix.
    id: 'ask-around-quarryman',
    label: 'Ask around for local news',
    golden: 'gu-005 (adapted)',
    intent: {
      ...base,
      action_type: 'research',
      target_entity_ids: [],
      approach: "work the taproom for whatever has the town uneasy of late",
      stat_hint: 'lore',
    },
  },
  {
    id: 'whittle-hearth',
    label: 'Whittle by the hearth',
    golden: 'gu-016 (adapted)',
    intent: {
      ...base,
      action_type: 'craft',
      target_entity_ids: [],
      approach: 'idle whittling by the hearth, a fire-fork from a split of kindling',
    },
  },

  // --- Maren Ostler --------------------------------------------------------
  {
    id: 'ask-maren-quarry',
    label: 'Ask {name} about the quarry',
    golden: 'gu-008',
    intent: {
      ...base,
      ...spoken,
      action_type: 'dialogue',
      target_entity_ids: [MAREN],
      approach: 'polite inquiry about the Redcliff quarry and the road up to it',
      dialogue: { addressee_id: MAREN, quoted_speech: null },
      speech_act: 'question',
      topic_ids: [QUARRYMAN],
    },
  },
  {
    id: 'charm-maren',
    label: 'Charm {name} for road news',
    golden: 'gu-012/gu-015 (adapted)',
    intent: {
      ...base,
      ...spoken,
      action_type: 'social',
      target_entity_ids: [MAREN],
      approach: 'friendly patter and a penny on the bar for whatever the road brought in',
      stat_hint: 'presence',
    },
  },

  // --- Jorun Pike ----------------------------------------------------------
  {
    id: 'size-up-jorun',
    label: 'Size up {name}',
    golden: 'gu-047',
    intent: {
      ...base,
      action_type: 'observation',
      target_entity_ids: [JORUN],
      approach: 'read his stance and the ruined arm for what they say',
      stat_hint: 'wits',
    },
  },
  {
    // De-spoilered 2026-07-14: dropped the wyvern name (undiscovered) and the
    // once-per-asker meta. Still the scene's social/presence contest — the one
    // chip that actually rolls to open Jorun up.
    id: 'press-jorun',
    label: 'Press {name} to open up',
    golden: 'gu-026 (adapted)',
    intent: {
      ...base,
      ...spoken,
      action_type: 'social',
      target_entity_ids: [JORUN],
      approach: 'press him past his guard on whatever he carries',
      stat_hint: 'presence',
    },
  },
  {
    id: 'square-jorun',
    label: 'Square up to {name}',
    golden: 'gu-002 (adapted)',
    intent: {
      ...base,
      action_type: 'physical',
      target_entity_ids: [JORUN],
      approach: 'square up bare-handed against a C plate, twenty years carried',
      stat_hint: 'might',
    },
  },

  // --- the ditch slime -------------------------------------------------------
  {
    id: 'stomp-slime',
    label: 'Stomp the ditch slime',
    golden: 'gu-042 (adapted)',
    intent: {
      ...base,
      action_type: 'physical',
      target_entity_ids: [SLIME],
      approach: 'boot heel, quick, before it reaches the casks',
      stat_hint: 'might',
    },
  },
]

/**
 * A short form of a perceived name for a chip: a learned name as is ("Maren
 * Ostler"); a descriptor cut to its first phrase with a definite article
 * ("a wary man with a ruined left arm, his back to..." -> "the wary man").
 */
export function shortName(perceived: string): string {
  return shortLabel(perceived)
}

/** A chip's label for this scene, with `{name}` as the player knows them. */
export function chipLabel(ci: CannedIntent, scene: Scene): string {
  if (!ci.label.includes('{name}')) return ci.label
  const target = scene.entities.find((e) => e.id === ci.intent.target_entity_ids[0])
  return ci.label.replace('{name}', target ? shortName(target.name) : 'them')
}

/** Intents legal against the current scene: every target must be present. */
export function availableIntents(scene: Scene): CannedIntent[] {
  const present = new Set(scene.entities.map((e) => e.id))
  return CANNED_INTENTS.filter(
    (ci) => !ci.hidden && ci.intent.target_entity_ids.every((id) => present.has(id)),
  )
}

/**
 * Does this canned declaration roll dice? In this catalogue the two sets
 * coincide exactly with the stat-hint split: every stat-hinted intent is a
 * contested action shape, every unhinted one is trivial-tier (look/rest/
 * wait/whittle/polite dialogue). Client-side heuristic for ORDERING only —
 * the engine owns the tier.
 */
export function likelyRolls(ci: CannedIntent): boolean {
  return ci.intent.stat_hint !== null
}

/**
 * Quick-pick chips for the composer (layout v2): scene-legal intents,
 * ROLLED-ACTIONS FIRST — the S1 playtest lesson: first-session legibility
 * comes from seeing dice, so "look around" and other quiet verbs trail.
 * `targetFilter` (a tapped scene sprite) narrows to that entity's verbs
 * plus the untargeted generics.
 */
export function chipIntents(scene: Scene, targetFilter: string | null): CannedIntent[] {
  const available = availableIntents(scene).filter(
    (ci) =>
      targetFilter === null ||
      ci.intent.target_entity_ids.length === 0 ||
      ci.intent.target_entity_ids.includes(targetFilter),
  )
  const rolled = available.filter(likelyRolls)
  const quiet = available.filter((ci) => !likelyRolls(ci))
  return [...rolled, ...quiet]
}
