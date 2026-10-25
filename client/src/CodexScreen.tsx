/**
 * The Codex screen (Team D, Sprint 3, roadmap §3.8 — the deep screen).
 *
 * Fact cards from the player's Inquiry claims, filters (subject / source /
 * recency), contradiction badges (ENGINE-marked — see codex.ts::isContested,
 * never client-inferred), the hypothesis pinboard (pin 2+ cards + an
 * optional typed note -> a research-target chip that pre-seeds the Play
 * composer), and map-in-Codex v0 (known ground only, blank past the ridge).
 *
 * BOOKKEEPING, NOT SUGGESTIONS (isekai-playbook §3): this screen surfaces
 * what the engine recorded and lets the PLAYER correlate. It proposes no
 * links of its own; the only correlation it emits is the player's own note.
 *
 * This component owns its filter + pinboard state; the parent owns the codex
 * data fetch and the composer (via onSeedComposer). Scrolls vertically
 * within the play column — the page itself never scrolls.
 */

import { useMemo, useState } from 'react'
import type { CodexClaim, CodexResponse, Scene } from './api'
import {
  applyFilters,
  confidenceWord,
  contestedPartner,
  DEFAULT_FILTERS,
  extraValue,
  isContested,
  knownLocations,
  methodWord,
  researchTargetLabel,
  researchTargetText,
  sourceOptions,
  subjectLabel,
  subjectOptions,
  type CodexFilters,
  type Hypothesis,
} from './codex'

function CodexCard({
  claim,
  all,
  pinned,
  onTogglePin,
}: {
  claim: CodexClaim
  all: readonly CodexClaim[]
  pinned: boolean
  onTogglePin: (id: string) => void
}) {
  const contested = isContested(claim)
  const partner = contested ? contestedPartner(claim, all) : null
  return (
    <article className={`codex-card${pinned ? ' codex-card--pinned' : ''}`}>
      <header className="codex-card-head">
        <span className="codex-card-subject">{subjectLabel(claim)}</span>
        <div className="codex-card-badges">
          {contested && (
            <span className="codex-badge codex-badge--contested" title="The engine holds two versions">
              [contested]
            </span>
          )}
          {claim.journal_flag && (
            <span className="codex-badge codex-badge--journal" title="Inherited from a journal">
              [inherited]
            </span>
          )}
        </div>
      </header>

      <p className="codex-card-text">
        {claim.claim_text}
        {extraValue(claim) && <span className="codex-card-value"> ({extraValue(claim)})</span>}
      </p>

      {contested && (
        <p className="codex-card-contradiction">
          {partner
            ? `Contradicts: "${partner.claim_text}" (${partner.source})`
            : 'The record holds a conflicting account.'}
        </p>
      )}

      {/* Provenance stamp — source, when, how, evidence-consistency WORD.
          Never a confidence number. */}
      <p className="codex-card-prov">
        <span className="codex-prov-source">{claim.source}</span>
        <span className="codex-prov-sep"> · </span>
        <span className="codex-prov-when">[{claim.world_date}]</span>
        <span className="codex-prov-sep"> · </span>
        <span className="codex-prov-method">{methodWord(claim)}</span>
        <span className="codex-prov-sep"> · </span>
        <span className="codex-prov-conf">{confidenceWord(claim)}</span>
      </p>

      <button
        type="button"
        className="codex-pin"
        aria-pressed={pinned}
        onClick={() => onTogglePin(claim.claim_id)}
      >
        {pinned ? '✓ pinned' : 'pin to a hypothesis'}
      </button>
    </article>
  )
}

export default function CodexScreen({
  data,
  sceneLocation,
  onSeedComposer,
}: {
  data: CodexResponse
  sceneLocation: Scene['location'] | null
  onSeedComposer: (text: string) => void
}) {
  const [filters, setFilters] = useState<CodexFilters>(DEFAULT_FILTERS)
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(() => new Set())
  const [note, setNote] = useState('')
  const [framed, setFramed] = useState<Hypothesis | null>(null)

  const subjects = useMemo(() => subjectOptions(data.claims), [data.claims])
  const sources = useMemo(() => sourceOptions(data.claims), [data.claims])
  const visible = useMemo(() => applyFilters(data.claims, filters), [data.claims, filters])
  const places = useMemo(
    () => knownLocations(data.known_locations, sceneLocation),
    [data.known_locations, sceneLocation],
  )

  const pinnedClaims = useMemo(
    () => data.claims.filter((c) => pinnedIds.has(c.claim_id)),
    [data.claims, pinnedIds],
  )

  const togglePin = (id: string) => {
    setFramed(null) // pins changed — an old framing no longer describes them
    setPinnedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const frameHypothesis = () => {
    if (pinnedClaims.length < 2) return
    setFramed({ claims: pinnedClaims, note })
  }

  const seedFromChip = (h: Hypothesis) => {
    onSeedComposer(researchTargetText(h))
    // Leave the pins as-is; the player may want to keep correlating.
  }

  const clearPinboard = () => {
    setPinnedIds(new Set())
    setNote('')
    setFramed(null)
  }

  return (
    <main className="codex-screen" aria-label="Codex">
      <header className="codex-head">
        <h2 className="codex-title">Codex</h2>
        <span className="codex-count">
          {data.claims.length} claim{data.claims.length === 1 ? '' : 's'} of record
        </span>
      </header>

      {data.claims.length === 0 ? (
        <section className="system-frame">
          <p className="system-line">
            &lt;&lt;Nothing is written here yet. Research the world and the Inquiry fills.&gt;&gt;
          </p>
        </section>
      ) : (
        <>
          {/* --- filters --- */}
          <section className="codex-filters" aria-label="Filter the Inquiry">
            <label className="codex-filter">
              <span className="codex-filter-label">Subject</span>
              <select
                className="codex-select"
                value={filters.subject ?? ''}
                onChange={(e) =>
                  setFilters((f) => ({ ...f, subject: e.target.value || null }))
                }
              >
                <option value="">All subjects</option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="codex-filter">
              <span className="codex-filter-label">Source</span>
              <select
                className="codex-select"
                value={filters.source ?? ''}
                onChange={(e) =>
                  setFilters((f) => ({ ...f, source: e.target.value || null }))
                }
              >
                <option value="">All sources</option>
                {sources.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className="codex-order"
              onClick={() =>
                setFilters((f) => ({
                  ...f,
                  order: f.order === 'newest' ? 'oldest' : 'newest',
                }))
              }
            >
              {filters.order === 'newest' ? 'Newest first' : 'Oldest first'}
            </button>
          </section>

          {/* --- fact cards --- */}
          <section className="codex-cards" aria-label="Fact cards">
            {visible.length === 0 ? (
              <p className="codex-empty">No claims match this filter.</p>
            ) : (
              visible.map((c) => (
                <CodexCard
                  key={c.claim_id}
                  claim={c}
                  all={data.claims}
                  pinned={pinnedIds.has(c.claim_id)}
                  onTogglePin={togglePin}
                />
              ))
            )}
          </section>

          {/* --- map-in-Codex v0: known ground only --- */}
          <section className="codex-map" aria-label="Known ground">
            <h3 className="codex-map-title">Known ground</h3>
            <ul className="codex-map-list">
              {places.map((p) => (
                <li key={p.location_id} className="codex-map-place">
                  {p.name}
                  {p.region && <span className="codex-map-region">, {p.region}</span>}
                </li>
              ))}
            </ul>
            <p className="codex-map-edge">Beyond the ridge, unmapped.</p>
          </section>
        </>
      )}

      {/* --- hypothesis pinboard (sticky footer of the deep screen) --- */}
      {pinnedClaims.length > 0 && (
        <aside className="codex-pinboard" aria-label="Hypothesis pinboard">
          <div className="codex-pinboard-head">
            <span className="codex-pinboard-count">
              {pinnedClaims.length} pinned:{' '}
              {[...new Set(pinnedClaims.map((c) => subjectLabel(c)))].join(', ')}
            </span>
            <button type="button" className="codex-pinboard-clear" onClick={clearPinboard}>
              clear
            </button>
          </div>

          {pinnedClaims.length < 2 ? (
            <p className="codex-pinboard-hint">Pin one more card to form a hypothesis.</p>
          ) : framed ? (
            <button
              type="button"
              className="codex-research-chip"
              onClick={() => seedFromChip(framed)}
            >
              {researchTargetLabel(framed)} → compose
            </button>
          ) : (
            <>
              <textarea
                className="codex-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Your hunch (optional): what might connect these?"
                aria-label="Hypothesis note"
                rows={2}
                maxLength={280}
              />
              <button type="button" className="codex-frame" onClick={frameHypothesis}>
                Frame a research target
              </button>
            </>
          )}
        </aside>
      )}
    </main>
  )
}
