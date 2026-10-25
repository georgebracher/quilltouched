/**
 * The Self screen (Sprint 4, The Self & The Social. Claude/design-UI).
 *
 * Who you are, as you know yourself. You KNOW your own build (unlike an NPC's
 * hidden true sheet), so aptitudes show. STANDING is your BELIEVED standing:
 * how you READ people and towns, never an objective fact (you cannot see inside
 * anyone; the true feeling is discoverable elsewhere, never shown here). Shown
 * as a word plus a diverging meter, never a raw number (George, 2026-07-15).
 *
 * Aptitudes ride an OPEN scale with no ceiling (the game is uncapped): a marker
 * on a track that fades off the right, so a high score reads as "well past
 * common, road still ahead", never "one off the cap". Tap a stat to learn what
 * it governs and what the numbers mean.
 *
 * Reads GET /api/self only. Proposes nothing, invents nothing. Vertical scroll
 * only, never sideways.
 */

import { useEffect, useState } from 'react'
import type { SelfResponse, SelfStanding } from './api'

const APTITUDE_ORDER = ['might', 'finesse', 'wits', 'will', 'presence', 'lore'] as const
type Aptitude = (typeof APTITUDE_ORDER)[number]

const APTITUDE_BLURB: Record<Aptitude, string> = {
  might: 'Raw physical force: lifting, striking, breaking, shrugging off a blow. Your might also sets how much harm you can take.',
  finesse: 'Precision and control: sleight of hand, balance, a true aim, fine craft.',
  wits: 'Quickness of mind and eye: noticing what others miss, reading a room, reacting in the moment.',
  will: 'Resolve and nerve: holding steady against fear, resisting a silver tongue, refusing to break.',
  presence: 'Force of personality: persuading, commanding, charming, cowing. The talker\'s stat.',
  lore: 'Learning and arcane insight: knowing things, researching the unknown, reading the world (and the Quill).',
}

// No ceiling. Common folk sit near 7 (two dice, average). Scores ride an OPEN
// scale that always leaves road ahead: asymptotic, so the marker never reaches
// the end and the track fades off the right with no cap.
const COMMON = 7
const scalePos = (value: number): number => (value / (value + 14)) * 100

function AptitudeScale({ value, large = false }: { value: number; large?: boolean }) {
  return (
    <span className={`self-scale${large ? ' self-scale--lg' : ''}`} aria-hidden="true">
      <span className="self-scale-track">
        <span className="self-scale-common" style={{ left: `${scalePos(COMMON)}%` }} />
        <span className="self-scale-mark" style={{ left: `${scalePos(value)}%` }} />
      </span>
    </span>
  )
}

/** A believed-standing meter: a diverging track, cold (left) to warm (right),
 *  filled from centre to the read. No number; the descriptor carries meaning. */
function StandingMeter({ value, band }: { value: number; band: number }) {
  const clamped = Math.max(-band, Math.min(band, value))
  const half = (Math.abs(clamped) / band) * 50
  const warm = clamped >= 0
  return (
    <span className="self-meter" aria-hidden="true">
      <span className="self-meter-track">
        <span className="self-meter-centre" />
        <span
          className={`self-meter-fill self-meter-fill--${warm ? 'warm' : 'cold'}`}
          style={warm ? { left: '50%', width: `${half}%` } : { right: '50%', width: `${half}%` }}
        />
      </span>
    </span>
  )
}

function StandingRow({ s }: { s: SelfStanding }) {
  return (
    <li className="self-standing">
      <span className="self-standing-name">{s.subject_name}</span>
      <span className="self-standing-read-row">
        <StandingMeter value={s.read} band={s.read_max} />
        <span className="self-standing-read">{s.descriptor}</span>
      </span>
    </li>
  )
}

/** Tap-a-stat explainer. Says what the aptitude governs AND what the numbers
 *  mean, including the point George wanted made loud: there is no cap. */
function AptitudeModal({
  apt,
  value,
  onClose,
}: {
  apt: Aptitude
  value: number
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="self-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`${apt}, explained`}
      onClick={onClose}
    >
      <div className="self-modal" onClick={(e) => e.stopPropagation()}>
        <header className="self-modal-head">
          <h3 className="self-modal-title">{apt}</h3>
          <span className="self-modal-score">{value}</span>
        </header>
        <p className="self-modal-blurb">{APTITUDE_BLURB[apt]}</p>
        <AptitudeScale value={value} large />
        <p className="self-modal-nocap">
          There is no ceiling. A common villager sits near {COMMON}, two dice on
          an ordinary day. You climb without limit. A score only says how you
          stand against what you face, and the scale runs on past dragons and
          further still.
        </p>
        <button type="button" className="self-modal-close" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  )
}

/** The summoned/chosen arrival framing (George, 2026-07-15). The seed origin
 *  gets in-fiction copy; the creation screen's arrival beat authors more. */
function originLine(origin: string): string {
  if (origin === 'quill_touched_stranger') {
    return (
      'The Quill wrote you into Harrowdown, pulled from somewhere else for a ' +
      'purpose no one will name. Chosen, says the Open Page. A blot in the ' +
      'margin, say the Blotted.'
    )
  }
  return origin.replace(/_/g, ' ')
}

export default function SelfScreen({ data }: { data: SelfResponse }) {
  const [openApt, setOpenApt] = useState<Aptitude | null>(null)
  const hasStanding = data.dispositions.length > 0 || data.standings.length > 0

  return (
    <main className="self-screen" aria-label="Self">
      <header className="self-head">
        <h2 className="self-name">{data.name}</h2>
        <p className="self-origin">{originLine(data.origin)}</p>
        <p className="self-condition">
          <span className="self-condition-wounds">{data.wounds}</span>
          <span className="self-sep"> · </span>
          <span className="self-condition-coin">⬥ {data.coin}</span>
        </p>
        {data.named_abilities.length > 0 && (
          <p className="self-titles">{data.named_abilities.join(' · ')}</p>
        )}
        {data.marks.length > 0 && (
          <p className="self-titles">{data.marks.join(' · ')}</p>
        )}
      </header>

      {/* Build. You know your own hand. Uncapped open scale; tap to learn. */}
      <section className="self-section" aria-label="Your build">
        <h3 className="self-section-title">
          Your hand<span className="self-section-note"> · you know your own</span>
        </h3>
        <ul className="self-aptitudes">
          {APTITUDE_ORDER.map((apt) => {
            const v = data.aptitudes[apt] ?? 0
            return (
              <li key={apt}>
                <button
                  type="button"
                  className="self-aptitude"
                  onClick={() => setOpenApt(apt)}
                  aria-label={`${apt}, ${v}. Tap to learn what it means.`}
                >
                  <span className="self-aptitude-name">{apt}</span>
                  <AptitudeScale value={v} />
                  <span className="self-aptitude-val">{v || '·'}</span>
                  <span className="self-aptitude-more" aria-hidden="true">?</span>
                </button>
              </li>
            )
          })}
        </ul>
        <p className="self-build-hint">Tap a stat to learn what it does. None of them cap.</p>
      </section>

      {/* Standing. BELIEVED, never the truth. */}
      <section className="self-section" aria-label="Your standing, as you read it">
        <h3 className="self-section-title">
          Standing<span className="self-section-note"> · as you read it</span>
        </h3>
        <p className="self-caveat">
          You cannot see inside anyone. These are your beliefs, and a belief can be wrong.
        </p>
        {hasStanding ? (
          <>
            {data.dispositions.length > 0 && (
              <ul className="self-standing-list">
                {data.dispositions.map((s) => (
                  <StandingRow key={s.subject_id} s={s} />
                ))}
              </ul>
            )}
            {data.standings.length > 0 && (
              <ul className="self-standing-list self-standing-list--towns">
                {data.standings.map((s) => (
                  <StandingRow key={s.subject_id} s={s} />
                ))}
              </ul>
            )}
          </>
        ) : (
          <p className="self-empty">You have made no mark on anyone yet.</p>
        )}
        <p className="self-renown">
          <span className="self-renown-label">The world:</span>{' '}
          <span className="self-renown-word">{data.renown_descriptor}</span>
        </p>
      </section>

      {openApt && (
        <AptitudeModal
          apt={openApt}
          value={data.aptitudes[openApt] ?? 0}
          onClose={() => setOpenApt(null)}
        />
      )}
    </main>
  )
}
