/**
 * Chronicle rendering — pure functions from the outcome contract to
 * transcript lines (Team D, Sprint 1).
 *
 * Diction rules (docs/lore/01-system-diction.md, BINDING):
 *   << >>  System voice addressing the player
 *   [ ]    System events (deltas, timers, titles)
 *   ???    unknown fields
 *   Ladder words / risk words, never percentages. Post-roll the
 *   Chronicle shows the dice and known modifiers in full.
 *
 * Everything rendered here comes from the outcome contract verbatim —
 * nothing is invented client-side. Pure module (no React, no fetch, no
 * import.meta.env) so it can be driven headlessly for verification.
 */

import type { Dice, Outcome, StateDelta } from './api'

/** {id -> how the player knows it}, from the scene's `labels`. */
export type Labels = ReadonlyMap<string, string>

const NO_LABELS: Labels = new Map()

/**
 * The display form of an id: its served label cut to a short phrase ("the wary
 * man"), `you` for the player. An NPC id with no label never prints (the id
 * spells the true name); other ids (items, a place not served) print as is.
 */
export function labelOf(labels: Labels, id: string): string {
  if (id === 'pc') return 'you'
  const label = labels.get(id)
  if (label !== undefined) return shortLabel(label)
  return id.startsWith('npc_') ? 'someone' : id
}

/** "a wary man with a ruined left arm, his back..." -> "the wary man". */
export function shortLabel(label: string): string {
  let s = label.split(',')[0].trim()
  const withAt = s.indexOf(' with ')
  if (withAt > 0) s = s.slice(0, withAt)
  return s.replace(/^an? /i, 'the ')
}

/** A flag key that ends in an id ("noticed_by_npc_...") reads in words. */
function flagWords(labels: Labels, key: string): string {
  const m = key.match(/^(.*?)((?:npc|creature|loc|item)_[a-z0-9_]+)$/)
  if (!m) return key.replace(/_/g, ' ')
  return `${m[1].replace(/_/g, ' ')}${labelOf(labels, m[2])}`
}

const cap = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1)
const signed = (n: number): string => (n >= 0 ? `+${n}` : `${n}`)

/** Pre-roll System assessment, e.g. `<<Assessment: ROUTINE — Guarded.>>` */
export function assessmentLine(outcome: Outcome): string {
  const tier = outcome.tier_resolved.toUpperCase()
  if (outcome.risk_label_shown) {
    return `<<Assessment: ${tier}, ${cap(outcome.risk_label_shown)}.>>`
  }
  return `<<Assessment: ${tier}.>>`
}

/** Post-roll dice line, e.g. `[2d6] 5 + 1 = 6  |  presence +1  ->  7` */
export function diceLine(dice: Dice): string {
  const [one, two] = dice.rolls
  const sum = one + two
  const mods = dice.modifiers.map((m) => `${m.label} ${signed(m.value)}`).join(', ')
  if (!mods) return `[2d6] ${one} + ${two} = ${sum}  ->  ${dice.total}`
  return `[2d6] ${one} + ${two} = ${sum}  |  ${mods}  ->  ${dice.total}`
}

/** Outcome tier as ladder words, or null when no roll occurred. */
export function outcomeLine(outcome: Outcome): string | null {
  if (outcome.outcome_tier === null) return null
  return `Outcome: ${outcome.outcome_tier.replace(/_/g, ' ').toUpperCase()}`
}

/** One terse [bracket] line per committed state delta. */
export function deltaLine(delta: StateDelta, labels: Labels = NO_LABELS): string {
  const name = (id: string) => labelOf(labels, id)
  switch (delta.delta_type) {
    case 'hp':
      return `[HP ${name(delta.entity_id)} ${signed(delta.amount)}${delta.cause ? `: ${delta.cause}` : ''}]`
    case 'wound_transition': {
      const word =
        delta.effect === 'dispatched' ? 'dispatched'
        : delta.effect === 'recovered' ? 'recovers'
        : 'wounded'
      return `[${cap(name(delta.entity_id))}: ${word}]`
    }
    case 'coin':
      return `[Coin ${name(delta.entity_id)} ${signed(delta.amount)}${delta.reason ? `, ${delta.reason}` : ''}]`
    case 'inventory':
      return `[Pack ${name(delta.entity_id)}: ${delta.op} ${delta.item_id} x${delta.quantity}]`
    case 'flag':
      return `[Flag ${name(delta.entity_id)}: ${flagWords(labels, delta.flag_key)} = ${String(delta.value)}]`
    case 'position':
      return `[Position ${name(delta.entity_id)}: ${delta.from_location_id ? name(delta.from_location_id) : '???'} -> ${name(delta.to_location_id)}]`
    case 'intel': {
      const c = delta.claim
      const value = c.value_or_range ? ` (${c.value_or_range})` : ''
      return `[Claim: "${c.claim_text}"${value}; ${c.method}, ${c.confidence}]`
    }
    case 'deed': {
      const witnessed = delta.witness_ids.length > 0 ? `, witnessed x${delta.witness_ids.length}` : ''
      return `[Deed: ${delta.description}; notoriety ${delta.notoriety}${witnessed}]`
    }
    case 'title':
      return `[Title Earned: ${delta.title}]`
    case 'clock':
      return `[Clock ${delta.clock_id}: +${delta.advance}]`
    case 'timer_started':
      return `[Timer (${delta.kind}): due world minute ${delta.due_world_time}]`
    case 'death_record':
      return `[Death Record: ${name(delta.entity_id)}: ${delta.cause}]`
    default:
      // Contract is closed (additionalProperties false); an unknown kind
      // means the contract moved ahead of this client. Render honestly.
      return `[${(delta as { delta_type: string }).delta_type}: ???]`
  }
}

/**
 * Collapsed delta summary for the compact transcript (layout v2): the
 * per-delta brackets fold behind one tappable line; tap expands to the
 * full deltaLine list.
 */
export function marksLine(deltaCount: number): string {
  return `[${deltaCount} mark${deltaCount === 1 ? '' : 's'} on the Chronicle]`
}

/** Full transcript block for one resolved action. Trivial = narrate-only. */
export function outcomeLines(outcome: Outcome, labels: Labels = NO_LABELS): string[] {
  const lines: string[] = [assessmentLine(outcome)]
  if (outcome.dice) lines.push(diceLine(outcome.dice))
  const tier = outcomeLine(outcome)
  if (tier) lines.push(tier)
  for (const delta of outcome.state_deltas) lines.push(deltaLine(delta, labels))
  if (!outcome.dice && !tier && outcome.state_deltas.length === 0) {
    lines.push('[The moment passes. No mark left on the Chronicle.]')
  }
  return lines
}

/** 422 detail -> System violation lines (string or {intent_schema_violations}). */
export function violationLines(detail: unknown): string[] {
  if (typeof detail === 'string') return [`[Violation: ${detail}]`]
  if (
    detail !== null &&
    typeof detail === 'object' &&
    'intent_schema_violations' in detail &&
    Array.isArray((detail as { intent_schema_violations: unknown }).intent_schema_violations)
  ) {
    return (detail as { intent_schema_violations: unknown[] }).intent_schema_violations.map(
      (v) => `[Violation: ${String(v)}]`,
    )
  }
  return [`[Violation: ${JSON.stringify(detail)}]`]
}
