/**
 * Chronicle durability (Team D, Hardening Pass 1 — audit #1 client half).
 *
 * The turn Chronicle is no longer session-only: the player-visible turn
 * blocks are cached in localStorage, keyed PER WORLD (`eq_chronicle:<world_id>`,
 * the token's world scope), so a reload/reconnect rebuilds the transcript
 * instead of flashing an empty history. On load we also GET /api/turns to
 * reconcile against canon (dedupe by command_id, ?since=<max narration_event_id>).
 *
 * Only NARRATED/committed turn blocks (`kind: 'action'`) are cached — faults
 * and transient System notes are session UI and are deliberately not durable.
 * Degraded turns (real outcome, no prose) ARE cached here because canon does
 * not serve them back (`/api/turns` returns only narrated turns); local cache
 * is their only durable home.
 *
 * This module owns ONLY the storage mechanics + shape. The Entry<->PersistedAction
 * mapping and the /api/turns merge live in App.tsx (they need React keys).
 */

import type { Assessment, Intent, Outcome } from './api'

/**
 * One durable turn block. Mirrors the `action` Entry variant in App.tsx minus
 * the ephemeral React `key` and the per-response `absorbed` flag (a duplicate
 * marker that is meaningless once reloaded). `eventId` is the turn's
 * `narration_event_id` when it came from canon (`/api/turns`), else null (a
 * live POST response carries no event id).
 */
export interface PersistedAction {
  label: string | null
  commandId: string
  outcome: Outcome
  assessment: Assessment | null
  narration: string | null
  systemNote: string | null
  gate: string | null
  eventId: number | null
  /** The committed form (parser output or a tapped action's); absent on
   *  turns cached before 2026-10-24 and on turns rebuilt from canon. */
  intent?: Intent | null
  /** True when the player typed the declaration (it went through the parser). */
  typed?: boolean
}

/** The fields mergeRecovered orders by; App.tsx's Entry satisfies it. */
export interface Ordered {
  kind: string
  commandId?: string
  eventId?: number | null
}

/**
 * Merge turns recovered from canon (/api/turns, oldest first) into the shown
 * Chronicle in canon order (audit 2026-10-24, claude-014). Entries already shown
 * learn their narration_event_id from `eventIds` (command id -> event id), so a
 * recovered turn lands before the first shown turn that canon placed after it,
 * not at the end. Turns already shown are not added twice. Entries without an
 * event id (notes, faults, unnarrated turns) keep their place. Pure.
 */
export function mergeRecovered<T extends Ordered>(
  prev: readonly T[],
  recovered: readonly T[],
  eventIds: ReadonlyMap<string, number>,
): T[] {
  const shown = prev.map((e) =>
    e.kind === 'action' && e.commandId && e.eventId == null && eventIds.has(e.commandId)
      ? { ...e, eventId: eventIds.get(e.commandId) }
      : e,
  )
  const have = new Set(shown.filter((e) => e.kind === 'action').map((e) => e.commandId))
  const adds = recovered
    .filter((e) => !have.has(e.commandId))
    .sort((a, b) => (a.eventId ?? 0) - (b.eventId ?? 0))
  if (adds.length === 0) return shown
  const out: T[] = []
  for (const e of shown) {
    while (adds.length > 0 && e.kind === 'action' && e.eventId != null && (adds[0].eventId ?? 0) < e.eventId) {
      out.push(adds.shift() as T)
    }
    out.push(e)
  }
  return [...out, ...adds]
}

export interface StoredChronicle {
  v: 1
  /** Max narration_event_id seen from /api/turns — the ?since= watermark. */
  since: number | null
  actions: PersistedAction[]
}

const KEY = (worldId: string): string => `eq_chronicle:${worldId}`
const MAX_ACTIONS = 300 // cap the cache; canon can always rebuild older turns

function isPersistedAction(x: unknown): x is PersistedAction {
  return (
    x !== null &&
    typeof x === 'object' &&
    typeof (x as PersistedAction).commandId === 'string' &&
    typeof (x as { outcome?: unknown }).outcome === 'object' &&
    (x as { outcome?: unknown }).outcome !== null
  )
}

/** Read the cached Chronicle for a world. Returns null on absence / bad shape /
 *  blocked storage — the caller then rebuilds from /api/turns. */
export function readChronicle(worldId: string): StoredChronicle | null {
  let raw: string | null
  try {
    raw = localStorage.getItem(KEY(worldId))
  } catch {
    return null // storage blocked (private mode)
  }
  if (!raw) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (
    parsed === null ||
    typeof parsed !== 'object' ||
    (parsed as { v?: unknown }).v !== 1 ||
    !Array.isArray((parsed as { actions?: unknown }).actions)
  ) {
    return null
  }
  const p = parsed as { since?: unknown; actions: unknown[] }
  const actions = p.actions.filter(isPersistedAction)
  const since = typeof p.since === 'number' ? p.since : null
  return { v: 1, since, actions }
}

export function writeChronicle(worldId: string, chronicle: StoredChronicle): void {
  const trimmed: StoredChronicle =
    chronicle.actions.length > MAX_ACTIONS
      ? { ...chronicle, actions: chronicle.actions.slice(-MAX_ACTIONS) }
      : chronicle
  try {
    localStorage.setItem(KEY(worldId), JSON.stringify(trimmed))
  } catch {
    // Storage full or blocked — the session continues; canon rebuilds on reload.
  }
}

export function clearChronicle(worldId: string): void {
  try {
    localStorage.removeItem(KEY(worldId))
  } catch {
    // nothing to clear
  }
}
