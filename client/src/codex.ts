/**
 * Codex logic — pure functions over the GET /api/codex surface (Team D,
 * Sprint 3). Filtering, contested detection, confidence-word formatting,
 * the known-locations merge, and the hypothesis → research-target seed.
 *
 * Design law (isekai-playbook §3, roadmap §3.8): the Codex does
 * BOOKKEEPING, never suggestions. It renders what the ENGINE marked
 * (contested pairs, provenance, confidence) and lets the PLAYER correlate.
 * Nothing here infers a connection between claims — the only "connection"
 * the client forms is the one the player types into a hypothesis note.
 *
 * Pure module (no React, no fetch, no import.meta.env) so it can be driven
 * headlessly for verification, exactly like render.ts / intents.ts.
 */

import type { CodexClaim, CodexLocation, Scene } from './api'

// --- filters ------------------------------------------------------------------

export interface CodexFilters {
  /** subject_entity_id, or null for all subjects. */
  subject: string | null
  /** exact source string, or null for all sources. */
  source: string | null
  /** recency = sort order over claim_id (ULIDs sort chronologically). */
  order: 'newest' | 'oldest'
}

export const DEFAULT_FILTERS: CodexFilters = {
  subject: null,
  source: null,
  order: 'newest',
}

export interface SubjectOption {
  id: string
  label: string
}

/** Distinct subjects present in the claim set, for the subject filter. */
export function subjectOptions(claims: readonly CodexClaim[]): SubjectOption[] {
  const seen = new Map<string, string>()
  for (const c of claims) {
    if (!seen.has(c.subject_entity_id)) {
      seen.set(c.subject_entity_id, subjectLabel(c))
    }
  }
  return [...seen.entries()]
    .map(([id, label]) => ({ id, label }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

/** Distinct sources present in the claim set, for the source filter. */
export function sourceOptions(claims: readonly CodexClaim[]): string[] {
  return [...new Set(claims.map((c) => c.source))].sort((a, b) => a.localeCompare(b))
}

/**
 * Apply the active filters. Subject/source are exact-match; `order` sorts by
 * claim_id, which is a ULID — lexicographic order IS chronological, so
 * newest-first needs no world_date parsing (world_date is "Day N, HH:MM",
 * not lexically sortable across day 2 vs day 10).
 */
export function applyFilters(
  claims: readonly CodexClaim[],
  filters: CodexFilters,
): CodexClaim[] {
  const kept = claims.filter(
    (c) =>
      (filters.subject === null || c.subject_entity_id === filters.subject) &&
      (filters.source === null || c.source === filters.source),
  )
  kept.sort((a, b) =>
    filters.order === 'newest'
      ? b.claim_id.localeCompare(a.claim_id)
      : a.claim_id.localeCompare(b.claim_id),
  )
  return kept
}

// --- contested (ENGINE-marked, never inferred) --------------------------------

/**
 * A card is contested iff the ENGINE said so. Two live claims that conflict
 * on an exclusive predicate arrive pointing at each other
 * (`contested_by_claim_id`) with `status === 'contested'` — see
 * docs/engine/claims.md. This reads those fields ONLY; it never compares
 * claim_text or values to invent a contradiction.
 */
export function isContested(claim: CodexClaim): boolean {
  return claim.status === 'contested' || claim.contested_by_claim_id !== null
}

/** The claim this one is contested against, if it is present in the set. */
export function contestedPartner(
  claim: CodexClaim,
  all: readonly CodexClaim[],
): CodexClaim | null {
  if (claim.contested_by_claim_id === null) return null
  return all.find((c) => c.claim_id === claim.contested_by_claim_id) ?? null
}

// --- display helpers ----------------------------------------------------------

/** A subject's KNOWN label. With none served, a prettified id, except for a
 *  person, whose id spells the true name: they read as "someone". */
export function subjectLabel(claim: CodexClaim): string {
  if (claim.subject_label) return claim.subject_label
  return claim.subject_entity_id.startsWith('npc_')
    ? 'someone'
    : prettifyContractId(claim.subject_entity_id)
}

/**
 * Prettify a contract id for display when no KNOWN label was served:
 * strips the `kind_world_` prefix and title-cases the remainder.
 * `creature_harrowdown_chalk_adder` -> "Chalk Adder".
 */
export function prettifyContractId(contractId: string): string {
  const parts = contractId.split('_')
  const tail = parts.length > 2 ? parts.slice(2) : parts
  return tail
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ')
}

/** Confidence rendered as words (never a number): `strongly_corroborated`
 *  -> "strongly corroborated". */
/**
 * The claim's value, when it adds something the sentence does not already say.
 * Many claims carry their sentence as the value too, which the card showed
 * twice; compared ignoring case, punctuation and spacing.
 */
export function extraValue(claim: CodexClaim): string | null {
  const value = claim.value_or_range
  if (!value) return null
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
  return norm(claim.claim_text).includes(norm(value)) ? null : value
}

export function confidenceWord(claim: CodexClaim): string {
  return claim.confidence.replace(/_/g, ' ')
}

/** The acquisition method as a short phrase for the provenance line. */
export function methodWord(claim: CodexClaim): string {
  return claim.method.replace(/_/g, ' ')
}

// --- map-in-Codex v0 ----------------------------------------------------------

/**
 * Known ground = the endpoint's known_locations UNION the location the
 * player is standing in right now (always known — it comes from the real
 * scene manifest). Deduped by location_id, name-sorted. Everything else is
 * "blank past the ridge" and is simply not rendered.
 */
export function knownLocations(
  fromCodex: readonly CodexLocation[],
  sceneLocation: Scene['location'] | null,
): CodexLocation[] {
  const byId = new Map<string, CodexLocation>()
  for (const loc of fromCodex) byId.set(loc.location_id, loc)
  if (sceneLocation && !byId.has(sceneLocation.id)) {
    byId.set(sceneLocation.id, {
      location_id: sceneLocation.id,
      name: sceneLocation.name,
      region: sceneLocation.region,
    })
  }
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name))
}

// --- hypothesis pinboard ------------------------------------------------------

export interface Hypothesis {
  /** The pinned claims (2+). */
  claims: CodexClaim[]
  /** The player's optional typed note — THEIR correlation, never the client's. */
  note: string
}

/**
 * The research target a hypothesis seeds into the Play composer. This lists
 * the subjects the PLAYER pinned (bookkeeping) and appends the PLAYER's own
 * note (their hypothesis). It asserts NO connection of its own — the client
 * never proposes a correlation; it only transcribes the player's pins + note
 * into a research phrasing the parser will read as a research action.
 */
export function researchTargetText(hypothesis: Hypothesis): string {
  const subjects = [
    ...new Set(hypothesis.claims.map((c) => subjectLabel(c))),
  ]
  const subjectPhrase =
    subjects.length === 0
      ? 'this matter'
      : subjects.length === 1
        ? subjects[0]
        : `${subjects.slice(0, -1).join(', ')} and ${subjects[subjects.length - 1]}`
  const note = hypothesis.note.trim()
  return note
    ? `Search the records about ${subjectPhrase}: ${note}`
    : `Search the records about ${subjectPhrase}`
}

/** A short label for the research-target chip. */
export function researchTargetLabel(hypothesis: Hypothesis): string {
  const subjects = [...new Set(hypothesis.claims.map((c) => subjectLabel(c)))]
  const head = subjects.slice(0, 2).join(' + ')
  const more = subjects.length > 2 ? ` +${subjects.length - 2}` : ''
  return `Research: ${head}${more}`
}
