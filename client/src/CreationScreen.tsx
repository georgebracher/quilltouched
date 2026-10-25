/**
 * Guided-dice creation screen + arrival beat (Sprint 4, Claude/design-UI).
 *
 * George's chargen decision: the seed rolls a pool of values (honest dice); the
 * PLAYER places six of them onto the six aptitudes, and one is a spare (the
 * "reroll" is simply choosing the spare over a base value). Then the isekai
 * arrival beat: summoned/chosen framing, the Quill pulled you into Harrowdown.
 *
 * Tap a value, tap a slot to place it; tap a filled slot to return it. No
 * horizontal scroll, no drag (finicky on phones). Wires to Codex's chargen API
 * (getChargenPool / postChargen); the parent owns the fetch + the commit.
 */

import { useMemo, useState } from 'react'
import type { ChargenPoolValue } from './api'

const APTITUDE_ORDER = ['might', 'finesse', 'wits', 'will', 'presence', 'lore'] as const
type Aptitude = (typeof APTITUDE_ORDER)[number]

const APTITUDE_HINT: Record<Aptitude, string> = {
  might: 'force and endurance',
  finesse: 'precision and aim',
  wits: 'perception and quickness',
  will: 'nerve and resolve',
  presence: 'charm and command',
  lore: 'learning and the arcane',
}

// Same open, uncapped scale the Self screen uses: common sits near 7, the track
// fades off the right, no ceiling.
const COMMON = 7
const scalePos = (v: number): number => (v / (v + 14)) * 100

type Placement = Record<Aptitude, number | null>
const EMPTY: Placement = {
  might: null, finesse: null, wits: null, will: null, presence: null, lore: null,
}

export default function CreationScreen({
  pool,
  onCommit,
  busy = false,
  fault = null,
}: {
  pool: ChargenPoolValue[] // seven: six base + one spare
  onCommit: (name: string, assignment: Record<string, number>) => void
  busy?: boolean
  fault?: string | null
}) {
  const [step, setStep] = useState<'place' | 'arrive'>('place')
  const [placed, setPlaced] = useState<Placement>(EMPTY)
  const [selected, setSelected] = useState<number | null>(null)
  const [name, setName] = useState('')

  const used = useMemo(
    () => new Set(Object.values(placed).filter((i): i is number => i !== null)),
    [placed],
  )
  const allPlaced = APTITUDE_ORDER.every((a) => placed[a] !== null)
  const valueOf = (idx: number) => pool.find((p) => p.index === idx)?.total ?? 0

  const tapChip = (idx: number) => {
    if (used.has(idx)) return
    setSelected((prev) => (prev === idx ? null : idx))
  }

  const tapSlot = (apt: Aptitude) => {
    if (placed[apt] !== null) {
      setPlaced((prev) => ({ ...prev, [apt]: null })) // return it to the pool
      return
    }
    if (selected !== null && !used.has(selected)) {
      setPlaced((prev) => ({ ...prev, [apt]: selected }))
      setSelected(null)
    }
  }

  const commit = () => {
    if (!allPlaced || busy) return
    const assignment: Record<string, number> = {}
    for (const a of APTITUDE_ORDER) assignment[a] = placed[a] as number
    onCommit(name.trim() || 'the Quill-touched', assignment)
  }

  if (step === 'arrive') {
    return (
      <main className="creation" aria-label="Your arrival">
        <section className="creation-arrival">
          <h2 className="creation-title">Your arrival</h2>
          <p className="creation-arrival-prose">
            You do not remember arriving. One moment you were elsewhere. The next,
            the smell of tallow and river-mud, a low room, a woman drying casks
            who has not yet looked up.
          </p>
          <p className="creation-arrival-prose">
            Ink dries on the back of your hand in a mark you have never seen. The
            Quill has written you into Harrowdown. Why, it does not say. The Open
            Page will call you chosen. The Blotted will call you a mistake in the
            margin. Neither of them knows yet. Neither do you.
          </p>
          <label className="creation-name">
            <span className="creation-name-label">What will they call you?</span>
            <input
              className="creation-name-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="a name"
              maxLength={40}
              autoComplete="off"
            />
          </label>
          {fault && <p className="creation-fault">[{fault}]</p>}
          <div className="creation-actions">
            <button
              type="button"
              className="creation-back"
              onClick={() => setStep('place')}
              disabled={busy}
            >
              Back
            </button>
            <button type="button" className="creation-go" onClick={commit} disabled={busy}>
              {busy ? 'Stepping through…' : 'Step into Harrowdown'}
            </button>
          </div>
        </section>
      </main>
    )
  }

  return (
    <main className="creation" aria-label="Build your character">
      <header className="creation-head">
        <h2 className="creation-title">The dice fall</h2>
        <p className="creation-lead">
          The Quill rolls your hand. You choose where each value falls. None of
          these cap, so a low start is only a slow start.
        </p>
      </header>

      {/* the rolled pool: place these onto the aptitudes below */}
      <section className="creation-pool" aria-label="Your rolled values">
        <ul className="creation-chips">
          {pool.map((p, i) => {
            const isSpare = i === pool.length - 1
            const isUsed = used.has(p.index)
            const isSel = selected === p.index
            return (
              <li key={p.index}>
                <button
                  type="button"
                  className={
                    'creation-chip' +
                    (isSpare ? ' creation-chip--spare' : '') +
                    (isUsed ? ' creation-chip--used' : '') +
                    (isSel ? ' creation-chip--sel' : '')
                  }
                  onClick={() => tapChip(p.index)}
                  disabled={isUsed}
                  aria-pressed={isSel}
                >
                  <span className="creation-chip-val">{p.total}</span>
                  {isSpare && <span className="creation-chip-tag">spare</span>}
                </button>
              </li>
            )
          })}
        </ul>
        <p className="creation-pool-hint">
          {selected !== null
            ? 'Now tap an aptitude to place it.'
            : 'Tap a value, then tap an aptitude. Tap a filled one to take it back.'}
        </p>
      </section>

      {/* the six aptitude slots */}
      <ul className="creation-slots">
        {APTITUDE_ORDER.map((apt) => {
          const idx = placed[apt]
          const filled = idx !== null
          const armed = selected !== null && !filled
          return (
            <li key={apt}>
              <button
                type="button"
                className={
                  'creation-slot' +
                  (filled ? ' creation-slot--filled' : '') +
                  (armed ? ' creation-slot--armed' : '')
                }
                onClick={() => tapSlot(apt)}
              >
                <span className="creation-slot-name">{apt}</span>
                <span className="creation-slot-hint">{APTITUDE_HINT[apt]}</span>
                {filled ? (
                  <span className="creation-slot-scale" aria-hidden="true">
                    <span className="creation-scale-track">
                      <span className="creation-scale-common" style={{ left: `${scalePos(COMMON)}%` }} />
                      <span className="creation-scale-mark" style={{ left: `${scalePos(valueOf(idx))}%` }} />
                    </span>
                  </span>
                ) : (
                  <span className="creation-slot-empty">tap to place</span>
                )}
                <span className="creation-slot-val">{filled ? valueOf(idx) : '·'}</span>
              </button>
            </li>
          )
        })}
      </ul>

      <div className="creation-actions">
        <button
          type="button"
          className="creation-go"
          onClick={() => setStep('arrive')}
          disabled={!allPlaced}
        >
          {allPlaced ? 'Continue' : 'Place all six to continue'}
        </button>
      </div>
    </main>
  )
}
