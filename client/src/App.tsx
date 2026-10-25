import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  clearDeviceToken,
  deviceToken,
  getChargenPool,
  getCodex,
  getScene,
  getSelf,
  getTurns,
  postActionConfirm,
  postActionIntent,
  postActionRaw,
  postActionText,
  postChargen,
  postClaim,
  storeDeviceToken,
  type ActionResolved,
  type Assessment,
  type ChargenPoolValue,
  type CodexResponse,
  type Intent,
  type Scene,
  type SceneEntity,
  type SceneExit,
  type SelfResponse,
  type StatusFacts,
  type TurnRecord,
} from './api'
import { mergeRecovered, readChronicle, writeChronicle, type PersistedAction } from './chronicle'
import CodexScreen from './CodexScreen'
import CreationScreen from './CreationScreen'
import SelfScreen from './SelfScreen'
import { chipIntents, chipLabel, type CannedIntent } from './intents'
import { backgroundFor, spriteFor } from './scene-art'
import {
  assessmentLine,
  deltaLine,
  diceLine,
  labelOf,
  marksLine,
  outcomeLine,
  violationLines,
} from './render'

/**
 * Play screen layout v3 (2026-10-24, desktop first). A top bar (place, coin,
 * date, active timer; screen tabs on desktop) over a grid of three areas:
 *
 *   - Scene — location background by type, figures standing on their authored
 *     slots' foot line, scaled by kind and depth, with contact shadows. The
 *     player's own character is not drawn; an entity with no art is a name
 *     label. Tap = target pre-select + known-card popover.
 *   - Chronicle — the last few action blocks; System lines in monospace,
 *     narrator prose in serif, deltas folded behind [n marks on the
 *     Chronicle]; full Chronicle one tap away.
 *   - Actions — suggested actions and places as tappable chips (rolled
 *     actions first, S1 lesson), then live free text through the parser.
 *
 * Desktop: scene and actions on the left, the Chronicle down the right.
 * Phone: scene, Chronicle, actions stacked, screen tabs in a bottom bar.
 *
 * Accounts v1: onboarding claims an invite code -> device token in
 * localStorage; 401 anywhere returns to onboarding. `<<Proceed?>>` beat:
 * pending_confirmation renders a System dialog — Proceed confirms under
 * the SAME command_id; declining dismisses (the moment expires
 * server-side, diegetically).
 */

type Entry =
  | {
      key: number
      kind: 'action'
      /** The player's declared text. null on a turn recovered purely from
       *  canon (/api/turns carries no command text) — the block then renders
       *  without a declaration line. */
      label: string | null
      commandId: string
      outcome: ActionResolved['outcome']
      assessment: Assessment | null
      narration: string | null
      absorbed: boolean
      /** System-voice line on a paid-layer degrade (audit #4); null otherwise. */
      systemNote: string | null
      /** narration_meta.gate ('pass' | 'degraded' | 'canonical_record' | ...). */
      gate: string | null
      /** narration_event_id when from canon; null on a live POST response. */
      eventId: number | null
      /** The committed form; null when rebuilt from canon or an older cache. */
      intent: Intent | null
      /** True when the declaration was typed and went through the parser. */
      typed: boolean
    }
  | { key: number; kind: 'fault'; label: string | null; lines: string[] }
  | { key: number; kind: 'note'; lines: string[] }

// --- Chronicle durability (audit #1 client half) ------------------------------
// Only committed turn blocks are cached; faults/transient notes are session UI.

function serializeActions(entries: Entry[]): PersistedAction[] {
  const out: PersistedAction[] = []
  for (const e of entries) {
    if (e.kind !== 'action') continue
    out.push({
      label: e.label,
      commandId: e.commandId,
      outcome: e.outcome,
      assessment: e.assessment,
      narration: e.narration,
      systemNote: e.systemNote,
      gate: e.gate,
      eventId: e.eventId,
      intent: e.intent,
      typed: e.typed,
    })
  }
  return out
}

function writeStoredChronicle(worldId: string, since: number | null, entries: Entry[]): void {
  writeChronicle(worldId, { v: 1, since, actions: serializeActions(entries) })
}

type Phase = 'onboarding' | 'loading' | 'chargen' | 'fault' | 'play'

type RailScreen = 'play' | 'character' | 'codex'

/** Codex fetch lifecycle. `stub` = the endpoint is not built yet (prod);
 *  `fault` = a real error we can retry. */
type CodexPhase = 'idle' | 'loading' | 'ready' | 'stub' | 'fault'

/** Omit that distributes over a union (plain Omit collapses variant props). */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never

interface RetryTicket {
  /** `canned:<id>` or `text:<utterance>` — retry identity for command_id reuse. */
  signature: string
  commandId: string
}

// The in-flight command survives a reload: if a turn committed but its response
// was lost, re-sending the same declaration reuses its command_id and the
// server returns the committed turn instead of resolving it again with fresh
// dice (audit 2026-10-24, k3 F2).
const INFLIGHT_KEY = 'eq_inflight'

function readInflight(): RetryTicket | null {
  try {
    const raw = localStorage.getItem(INFLIGHT_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : null
    if (
      parsed !== null &&
      typeof parsed === 'object' &&
      typeof (parsed as RetryTicket).signature === 'string' &&
      typeof (parsed as RetryTicket).commandId === 'string'
    ) {
      return parsed as RetryTicket
    }
  } catch {
    // storage blocked or corrupt: no ticket
  }
  return null
}

function writeInflight(ticket: RetryTicket | null): void {
  try {
    if (ticket) localStorage.setItem(INFLIGHT_KEY, JSON.stringify(ticket))
    else localStorage.removeItem(INFLIGHT_KEY)
  } catch {
    // storage blocked: the ticket lives for this page load only
  }
}

interface PendingBeat {
  commandId: string
  label: string
  assessment: Assessment
  typed: boolean
}

interface Placed {
  entity: SceneEntity
  x: number
  y: number
}

/**
 * Slot placement (interface decision 5): slotted entities stand at their
 * authored anchor (x_pct/y_pct = the bottom-center foot line). Entities
 * without a slot (no slot map for this location type, or slots ran out)
 * spread across the foreground band deterministically by scene order.
 * Sorted by y so DOM order IS painter's order (lower feet paint in front).
 */
function placeEntities(sceneEntities: SceneEntity[]): Placed[] {
  // The scene is the player's own view: their character is not in it.
  const entities = sceneEntities.filter((e) => e.id !== PLAYER_ID)
  const unslotted = entities.filter((e) => e.slot === null)
  const spread = (i: number) =>
    unslotted.length === 1 ? 50 : 25 + (i * 50) / (unslotted.length - 1)
  const placed: Placed[] = [
    ...entities
      .filter((e) => e.slot !== null)
      .map((e) => ({ entity: e, x: e.slot!.x_pct, y: e.slot!.y_pct })),
    ...unslotted.map((e, i) => ({ entity: e, x: spread(i), y: 91 })),
  ]
  return placed.sort((a, b) => a.y - b.y)
}

/** Suggestions a phone shows before "More suggestions" (desktop shows all). */
const PHONE_CHIPS = 4

/** The API's 503 detail for a claimed world whose character is not created yet. */
const NO_CHARACTER_YET = 'world not initialized (no PC yet)'

/** Shown when the browser refused to store the device key (private mode, full quota). */
const TOKEN_NOT_KEPT =
  '<<This browser will not keep your key. The volume stays open while this tab does.>>'

/** The scene manifest's id for the player's own character. */
const PLAYER_ID = 'pc'

const RAIL_TABS: { id: RailScreen; label: string }[] = [
  { id: 'play', label: 'Play' },
  { id: 'character', label: 'Character' },
  { id: 'codex', label: 'Codex' },
]

// --- typewriter: the Quill's response should appear as if written, not dumped -
// (George's note). Reveals `text` at a steady rate on the LATEST turn only;
// older turns render whole. Tap the prose to reveal it all at once.
const _TYPE_CHARS_PER_TICK = 3
const _TYPE_TICK_MS = 16

function useTypewriter(
  text: string | null,
  animate: boolean,
  onReveal?: () => void,
): { shown: string; done: boolean; reveal: () => void } {
  const full = text ?? ''
  // Reduced motion: the prose appears whole, no ticking reveal.
  const still =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  animate = animate && !still
  const [count, setCount] = useState(animate ? 0 : full.length)
  useEffect(() => {
    if (!animate) {
      setCount(full.length)
      return
    }
    setCount(0)
    let i = 0
    const id = setInterval(() => {
      i = Math.min(full.length, i + _TYPE_CHARS_PER_TICK)
      setCount(i)
      onReveal?.()
      if (i >= full.length) clearInterval(id)
    }, _TYPE_TICK_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [full, animate])
  return {
    shown: full.slice(0, count),
    done: count >= full.length,
    reveal: () => setCount(full.length),
  }
}

// --- the workings: the form the engine decided from ---------------------------

/**
 * The committed form behind one turn, for the curious (and the case study):
 * what the parser read the typed words as, or the form a tapped action sends.
 * Closed fields are what the engine decides from; the approach and the hints
 * are shown as what they are, free text and advice it never branches on.
 */
function Workings({
  intent,
  typed,
  names,
}: {
  intent: Intent
  typed: boolean
  names: ReadonlyMap<string, string>
}) {
  const name = (id: string) => labelOf(names, id)
  const list = (ids: string[]) => (ids.length > 0 ? ids.map(name).join(', ') : null)
  const tx = intent.transaction
  const rows: [string, string | null][] = [
    ['action', intent.action_type],
    ['aimed at', list(intent.target_entity_ids)],
    ['speaking to', intent.addressee === 'room' ? 'the room' : intent.addressee === 'person' ? 'one person' : null],
    ['speech', intent.speech_act],
    ['asking about', list(intent.topic_ids)],
    [
      'coin',
      tx === null
        ? null
        : tx.kind === 'buy'
          ? `buys ${tx.count} × ${tx.price_key ?? '?'}`
          : `hands over ${tx.count} coin`,
    ],
    ['invokes', list(intent.invoked_law_ids)],
    ['moving', intent.movement_scope === 'here' ? 'within this place' : intent.movement_scope === 'away' ? 'elsewhere' : null],
    ['words said', intent.dialogue?.quoted_speech ? `"${intent.dialogue.quoted_speech}"` : null],
    ['time', intent.duration_hint ? intent.duration_hint.text : null],
    ['flags', intent.ambiguity_flags.length > 0 ? intent.ambiguity_flags.join(', ') : null],
  ]
  return (
    <div className="workings">
      <p className="workings-lead">
        {typed
          ? 'The parser read your words into this form. It cannot say whether you succeed: there is no field for that.'
          : 'A tapped action sends this form as written, with no parser.'}
      </p>
      <dl className="workings-form">
        {rows
          .filter(([, value]) => value !== null)
          .map(([label, value]) => (
            <div className="workings-row" key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        <div className="workings-row workings-row--advice">
          <dt>approach</dt>
          <dd>
            &ldquo;{intent.approach}&rdquo; <em>free text for the narrator; decides nothing</em>
          </dd>
        </div>
        <div className="workings-row workings-row--advice">
          <dt>hints</dt>
          <dd>
            {intent.stat_hint ?? 'no stat'}, {intent.plausibility_hint.replace(/_/g, ' ')}{' '}
            <em>advice the engine ignores</em>
          </dd>
        </div>
      </dl>
      <p className="workings-lead">
        The engine decided the rest, from these fields and true stats you never see.
      </p>
    </div>
  )
}

// --- one resolved action in the Chronicle -------------------------------------

function TurnBlock({
  entry,
  names,
  expandedByDefault = false,
  isLatest = false,
}: {
  entry: Extract<Entry, { kind: 'action' }>
  names: ReadonlyMap<string, string>
  expandedByDefault?: boolean
  isLatest?: boolean
}) {
  const [marksOpen, setMarksOpen] = useState(expandedByDefault)
  const [workingsOpen, setWorkingsOpen] = useState(false)
  const tailRef = useRef<HTMLSpanElement | null>(null)
  // Only the newest turn types in; re-mounts of older turns render whole.
  const typed = useTypewriter(entry.narration, isLatest && !expandedByDefault, () => {
    tailRef.current?.scrollIntoView({ block: 'nearest' })
  })
  const o = entry.outcome
  const tier = outcomeLine(o)
  const quiet = !o.dice && !tier && o.state_deltas.length === 0
  // Paid-layer degrade (audit #4): the deed committed but the Quill was over
  // budget for prose. Show the System's line (or a diegetic fallback) — never
  // a broken-looking empty turn. Never typed: degrade carries no prose.
  const degraded = entry.gate === 'degraded'
  const systemNote = entry.systemNote ?? (degraded ? '<<The Quill sets down its pen for now. The deed is written all the same.>>' : null)
  return (
    <article className="turn">
      {entry.label && <p className="turn-declared">{entry.label}</p>}
      {!entry.label && (
        <p className="turn-line turn-absorbed">[The Chronicle holds this turn.]</p>
      )}
      {entry.absorbed && (
        <p className="turn-line turn-absorbed">
          [Duplicate command absorbed: the Chronicle already holds event {o.event_id}]
        </p>
      )}
      <p className="turn-line turn-system">{entry.assessment?.summary ?? assessmentLine(o)}</p>
      {o.dice && <p className="turn-line turn-dice">{diceLine(o.dice)}</p>}
      {tier && (
        <p className={`turn-line turn-outcome turn-outcome--${o.outcome_tier}`}>{tier}</p>
      )}
      {systemNote && <p className="turn-line turn-degrade">{systemNote}</p>}
      {entry.narration && (
        <p
          className={`turn-narration${typed.done ? '' : ' turn-narration--typing'}`}
          onClick={typed.done ? undefined : typed.reveal}
          title={typed.done ? undefined : 'Tap to reveal'}
          // Busy while typing, so assistive tech reads the finished prose once.
          aria-busy={!typed.done}
        >
          {typed.shown}
          <span ref={tailRef} aria-hidden="true" />
        </p>
      )}
      {o.state_deltas.length > 0 &&
        (marksOpen ? (
          <div>
            {o.state_deltas.map((delta, i) => (
              <p className="turn-line turn-delta" key={i}>
                {deltaLine(delta, names)}
              </p>
            ))}
          </div>
        ) : (
          <button type="button" className="turn-marks" onClick={() => setMarksOpen(true)}>
            {marksLine(o.state_deltas.length)}
          </button>
        ))}
      {quiet && !entry.narration && !systemNote && (
        <p className="turn-line turn-delta">[The moment passes. No mark left on the Chronicle.]</p>
      )}
      {entry.intent && (
        <>
          <button
            type="button"
            className="workings-toggle"
            aria-expanded={workingsOpen}
            onClick={() => setWorkingsOpen((open) => !open)}
          >
            {workingsOpen ? 'Hide the workings' : 'How this was decided'}
          </button>
          {workingsOpen && <Workings intent={entry.intent} typed={entry.typed} names={names} />}
        </>
      )}
    </article>
  )
}

function FaultBlock({ entry }: { entry: Extract<Entry, { kind: 'fault' }> }) {
  return (
    <article className="turn turn--fault" role="alert">
      {entry.label && <p className="turn-declared">{entry.label}</p>}
      {entry.lines.map((line, i) => (
        <p className="turn-line turn-fault-line" key={i}>
          {line}
        </p>
      ))}
    </article>
  )
}

function NoteBlock({ entry }: { entry: Extract<Entry, { kind: 'note' }> }) {
  return (
    <article className="turn turn--note">
      {entry.lines.map((line, i) => (
        <p className="turn-line turn-system" key={i}>
          {line}
        </p>
      ))}
    </article>
  )
}

/** Outcome of a send attempt — drives when the composer is safe to clear. */
type SendKind = 'resolved' | 'pending' | 'failed' | 'busy'

// --- 429s from /api/action (audit #4) -------------------------------------------
// A 429 carries a `code`: the paid parser over budget (free text only; tapped
// play stays open) or TURN_IN_FLIGHT, another turn of this account still
// resolving, which can hit a tapped action too. The retry ticket is kept either
// way. Render the System's line diegetically.

const DEGRADE_CODE_LINES: Record<string, string> = {
  // The server's own lines (api/messages.py), pinned by api/tests/test_api_no_db.py.
  TURN_IN_FLIGHT: '<<The Quill is still writing your last action. A moment.>>',
  TURN_TOO_FAST: '<<The Quill outpaces you. A breath, then declare again.>>',
  TURN_DAILY_DONE: '<<The Quill has written enough of you for one day. Return tomorrow.>>',
  INK_SPENT: '<<The ink is spent for today. The Quill resumes tomorrow.>>',
  INK_TYPED_REQUIRES_TAP:
    "<<The Quill's ink runs thin for free hand today. Tap a suggested action and the deed still resolves.>>",
  CLAIM_THROTTLED: '<<The Quill will not be rushed. Try again shortly.>>',
}

function degradeLines(detail: unknown): string[] {
  let line: string | null = null
  let code: string | null = null
  if (typeof detail === 'string') {
    line = detail
  } else if (detail !== null && typeof detail === 'object') {
    const d = detail as Record<string, unknown>
    if (typeof d.message === 'string') line = d.message
    else if (typeof d.detail === 'string') line = d.detail
    else if (typeof d.system_note === 'string') line = d.system_note
    if (typeof d.code === 'string') code = d.code
  }
  if (!line) line = (code && DEGRADE_CODE_LINES[code]) || '<<The Quill rests its ink for now.>>'
  const transient = code === 'TURN_TOO_FAST' || code === 'TURN_IN_FLIGHT'
  const affordance = transient
    ? '[A breath, then speak again, or tap a suggested action.]'
    : '[Tap a suggested action: the engine still hears a tapped deed.]'
  return [line, affordance]
}

export default function App() {
  const [phase, setPhase] = useState<Phase>(() => (deviceToken() ? 'loading' : 'onboarding'))
  const [scene, setScene] = useState<Scene | null>(null)
  const [sceneFault, setSceneFault] = useState<string | null>(null)
  const [entries, setEntries] = useState<Entry[]>([])
  // The latest entries for callbacks that must not re-create on every turn.
  const entriesRef = useRef<Entry[]>(entries)
  entriesRef.current = entries
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null)
  const [composerText, setComposerText] = useState('')
  const [busy, setBusy] = useState(false)
  const [pendingBeat, setPendingBeat] = useState<PendingBeat | null>(null)
  const [railScreen, setRailScreen] = useState<RailScreen>('play')
  const [historyOpen, setHistoryOpen] = useState(false)
  // Phone shows two rows of suggestions until the player asks for the rest.
  const [chipsOpen, setChipsOpen] = useState(false)
  // Entities whose sprite failed to load (the public copy ships no art): they
  // fall back to a name label, like entities with no art at all.
  const [brokenArt, setBrokenArt] = useState<ReadonlySet<string>>(new Set())

  // Chronicle durability (audit #1): the current world's storage key + a
  // hydration gate so we never persist an empty transcript over a real one
  // before it has been restored. `since` is the max narration_event_id seen
  // from /api/turns — the ?since= watermark. It is BOTH state (so a bump
  // re-persists even when no new turn blocks were added) and a ref (so
  // reconcile can read the current value without a stale closure).
  const [worldId, setWorldId] = useState<string | null>(null)
  const [hydrated, setHydrated] = useState(false)
  const [since, setSince] = useState<number | null>(null)
  const sinceRef = useRef<number | null>(null)

  // Codex screen (railScreen === 'codex') — fetched on entry, kept fresh.
  const [codex, setCodex] = useState<CodexResponse | null>(null)
  const [codexPhase, setCodexPhase] = useState<CodexPhase>('idle')
  const [codexFault, setCodexFault] = useState<string | null>(null)

  // Self screen (railScreen === 'character') — fetched on entry, kept fresh.
  const [self, setSelf] = useState<SelfResponse | null>(null)
  const [selfPhase, setSelfPhase] = useState<CodexPhase>('idle')
  const [selfFault, setSelfFault] = useState<string | null>(null)

  // Onboarding state
  const [inviteCode, setInviteCode] = useState('')
  const [claimBusy, setClaimBusy] = useState(false)
  const [claimFault, setClaimFault] = useState<string | null>(null)

  // Guided-dice creation (phase 'chargen'): the rolled pool + commit lifecycle.
  const [pool, setPool] = useState<ChargenPoolValue[] | null>(null)
  const [chargenBusy, setChargenBusy] = useState(false)
  const [chargenFault, setChargenFault] = useState<string | null>(null)

  const keyRef = useRef(0)
  const sessionRef = useRef(
    `web.${Date.now().toString(36)}.${Math.random().toString(36).slice(2, 8)}`,
  )
  const counterRef = useRef(0)
  const pendingRetryRef = useRef<RetryTicket | null>(readInflight())
  const setRetry = (ticket: RetryTicket | null) => {
    pendingRetryRef.current = ticket
    writeInflight(ticket)
  }
  const transcriptRef = useRef<HTMLElement | null>(null)
  const composerInputRef = useRef<HTMLInputElement | null>(null)

  const nextCommandId = () => `${sessionRef.current}:${++counterRef.current}`

  /** Advance the ?since= watermark in both ref (reads) and state (persist). */
  const bumpSince = useCallback((value: number | null) => {
    sinceRef.current = value
    setSince(value)
  }, [])

  /** Retries after 409/network reuse the same command_id (server absorbs). */
  const takeCommandId = (signature: string) => {
    const retry = pendingRetryRef.current
    return retry && retry.signature === signature ? retry.commandId : nextCommandId()
  }

  const append = useCallback((entry: DistributiveOmit<Entry, 'key'>) => {
    setEntries((prev) => [...prev, { ...entry, key: ++keyRef.current } as Entry])
  }, [])

  // --- auth loss (401): the token is gone server-side ---------------------------

  const authLoss = useCallback(() => {
    clearDeviceToken()
    writeInflight(null)
    // Drop the durability gate FIRST: emptying `entries` below must not persist
    // an empty transcript over the (account-scoped) cached Chronicle.
    setHydrated(false)
    setWorldId(null)
    bumpSince(null)
    setScene(null)
    setEntries([])
    setPendingBeat(null)
    setSelectedTarget(null)
    setHistoryOpen(false)
    setRailScreen('play')
    setCodex(null)
    setCodexPhase('idle')
    setCodexFault(null)
    setSelf(null)
    setSelfPhase('idle')
    setSelfFault(null)
    setPool(null)
    setChargenBusy(false)
    setChargenFault(null)
    setClaimFault('<<The Quill does not know this hand. Speak a fresh word.>>')
    setPhase('onboarding')
  }, [bumpSince])

  // --- Chronicle reconnect (audit #1) --------------------------------------------

  /**
   * Rebuild the Chronicle from canon on load/reconnect. GET
   * /api/turns?since=<watermark>, merge oldest-first, dedupe by command_id,
   * advance the watermark. The local cache has already been shown; this fills
   * any turns the cache is missing (response-loss, cross-device, cold cache)
   * and never re-sorts. Non-401 failures are non-fatal — the cache stands.
   */
  const reconcileTurns = useCallback(
    async () => {
      // With a watermark the API pages FORWARD from it (oldest first), so a
      // full page means more to fetch. Without one it returns the newest page.
      const PAGE = 200
      const turns: TurnRecord[] = []
      // A cold cache pages forward from the start, not just the newest page.
      let cursor = sinceRef.current ?? 0
      for (let page = 0; page < 20; page++) {
        const res = await getTurns({ since: cursor, limit: PAGE })
        if (!res.ok) {
          if (res.status === 401) authLoss()
          if (turns.length === 0) return // keep the local cache; retry next load
          break
        }
        turns.push(...res.body.turns)
        if (res.body.turns.length < PAGE) break
        cursor = Math.max(cursor, ...res.body.turns.map((x) => x.narration_event_id))
      }
      // The lost turn the ticket was holding is on record now: a fresh tap of
      // the same action is a new action, not that one (audit codex-002).
      const ticket = pendingRetryRef.current
      if (ticket && turns.some((t) => t.command_id === ticket.commandId)) setRetry(null)
      let maxSince = sinceRef.current ?? 0
      for (const t of turns) {
        if (t.narration_event_id > maxSince) maxSince = t.narration_event_id
      }
      // Functional updater → React guarantees fresh `prev`, so dedupe is exact
      // regardless of when the restore above flushed.
      setEntries((prev) => {
        const additions: Entry[] = []
        for (const t of turns) {
          additions.push({
            key: ++keyRef.current,
            kind: 'action',
            label: null, // a canon record carries no player command text
            commandId: t.command_id,
            outcome: t.outcome,
            assessment: null,
            narration: t.narration,
            absorbed: false,
            systemNote: null,
            gate: t.narration_meta?.gate ?? null,
            eventId: t.narration_event_id,
            intent: null,
            typed: false,
          })
        }
        const eventIds = new Map(turns.map((t): [string, number] => [t.command_id, t.narration_event_id]))
        // In canon order, not appended at the end (claude-014); no duplicates.
        return mergeRecovered(prev, additions, eventIds)
      })
      if (turns.length > 0 && maxSince !== (sinceRef.current ?? 0)) {
        // A watermark bump re-persists via the effect even when every turn was
        // already cached (all deduped) — so the next reconnect fetches only
        // strictly-newer turns rather than the full window again.
        bumpSince(maxSince)
      }
    },
    [authLoss, bumpSince],
  )

  // --- guided creation (chargen) ---------------------------------------------

  const loadPool = useCallback(async () => {
    const res = await getChargenPool()
    if (res.ok) {
      setPool(res.body.values)
      setChargenFault(null)
      setPhase('chargen')
    } else if (res.status === 401) {
      authLoss()
    } else {
      setSceneFault(
        typeof res.detail === 'string' ? res.detail : `HTTP ${res.status || 'unreachable'}`,
      )
      setPhase('fault')
    }
  }, [authLoss])

  // --- scene -----------------------------------------------------------------

  const loadScene = useCallback(async () => {
    setPhase('loading')
    const res = await getScene()
    if (res.ok) {
      const wid = res.body.world
      setScene(res.body)
      setSceneFault(null)
      // Restore the cached Chronicle for THIS world BEFORE the transcript shows
      // — a reload must not flash an empty history (audit #1). Only restore
      // when there are cached turn blocks, so a fresh claim's welcome note is
      // not clobbered by an empty restore.
      const stored = readChronicle(wid)
      if (stored) {
        bumpSince(stored.since)
        if (stored.actions.length > 0) {
          setEntries(
            stored.actions.map((a) => ({
              key: ++keyRef.current,
              kind: 'action' as const,
              label: a.label,
              commandId: a.commandId,
              outcome: a.outcome,
              assessment: a.assessment,
              narration: a.narration,
              absorbed: false,
              systemNote: a.systemNote,
              gate: a.gate,
              eventId: a.eventId,
              intent: a.intent ?? null,
              typed: a.typed ?? false,
            })),
          )
        }
      }
      setWorldId(wid)
      setHydrated(true)
      setPhase('play')
      void reconcileTurns()
    } else if (res.status === 401) {
      authLoss()
    } else if (res.status === 503 && res.detail === NO_CHARACTER_YET) {
      // Guided claim not yet completed — no character. Resume creation. Any
      // other 503 (content drift, insecure runtime, database down) is a fault.
      void loadPool()
    } else {
      setSceneFault(
        typeof res.detail === 'string' ? res.detail : `HTTP ${res.status || 'unreachable'}`,
      )
      setPhase('fault')
    }
  }, [authLoss, bumpSince, reconcileTurns, loadPool])

  // Commit a placed build -> the world genesises the PC -> into play.
  const commitChargen = useCallback(
    async (name: string, assignment: Record<string, number>) => {
      setChargenBusy(true)
      setChargenFault(null)
      const res = await postChargen(name, assignment)
      if (res.ok || res.status === 409) {
        // 409 = the character already exists: a retried commit whose first
        // response was lost. The world has it, so enter play.
        setChargenBusy(false)
        void loadScene()
      } else if (res.status === 401) {
        authLoss()
      } else {
        setChargenFault(
          typeof res.detail === 'string' ? res.detail : `HTTP ${res.status || 'unreachable'}`,
        )
        setChargenBusy(false)
      }
    },
    [authLoss, loadScene],
  )

  useEffect(() => {
    if (deviceToken()) void loadScene()
  }, [loadScene])

  // Persist the Chronicle whenever it (or the watermark) changes — but only
  // after hydration, so a fresh mount's empty `entries` never overwrites the
  // cached transcript before loadScene has restored it (audit #1).
  useEffect(() => {
    if (!hydrated || worldId === null) return
    writeStoredChronicle(worldId, since, entries)
  }, [entries, since, hydrated, worldId])

  /** Post-action refresh: keep the screen, note the fault in the Chronicle. */
  const refreshScene = useCallback(async () => {
    const res = await getScene()
    if (res.ok) {
      setScene(res.body)
    } else if (res.status === 401) {
      authLoss()
    } else {
      append({
        kind: 'fault',
        label: null,
        lines: ['<<The Quill does not answer.>>', '[Scene refresh failed]'],
      })
    }
  }, [append, authLoss])

  // --- Codex (Sprint 3) ----------------------------------------------------------

  /** Fetch the player's Inquiry claims. 404/501 = endpoint unavailable:
   *  an honest stub, never invented data. */
  const loadCodex = useCallback(async () => {
    setCodexPhase('loading')
    setCodexFault(null)
    const res = await getCodex()
    if (res.ok) {
      setCodex(res.body)
      setCodexPhase('ready')
    } else if (res.status === 401) {
      authLoss()
    } else if (res.status === 404 || res.status === 501) {
      setCodexPhase('stub')
    } else {
      setCodexFault(
        typeof res.detail === 'string' ? res.detail : `HTTP ${res.status || 'unreachable'}`,
      )
      setCodexPhase('fault')
    }
  }, [authLoss])

  // Fetch on entering the Codex tab (fresh each visit — cheap at alpha,
  // and research done between visits shows up).
  useEffect(() => {
    if (railScreen === 'codex' && phase === 'play') void loadCodex()
  }, [railScreen, phase, loadCodex])

  /** Fetch the Self view. 503 = no character yet (pre-genesis) → honest stub. */
  const loadSelf = useCallback(async () => {
    setSelfPhase('loading')
    setSelfFault(null)
    const res = await getSelf()
    if (res.ok) {
      setSelf(res.body)
      setSelfPhase('ready')
    } else if (res.status === 401) {
      authLoss()
    } else if (res.status === 503) {
      setSelfPhase('stub')
    } else {
      setSelfFault(
        typeof res.detail === 'string' ? res.detail : `HTTP ${res.status || 'unreachable'}`,
      )
      setSelfPhase('fault')
    }
  }, [authLoss])

  // Fetch on entering the Character tab (fresh each visit — standing you earned
  // between visits shows up).
  useEffect(() => {
    if (railScreen === 'character' && phase === 'play') void loadSelf()
  }, [railScreen, phase, loadSelf])

  /** Pinboard -> composer: a framed research target pre-seeds the Play
   *  composer as free text (goes through the parser like any typed action). */
  const seedComposer = useCallback((text: string) => {
    setComposerText(text)
    setRailScreen('play')
    // Focus after the Play zones mount.
    requestAnimationFrame(() => composerInputRef.current?.focus())
  }, [])

  // --- onboarding (accounts v1) --------------------------------------------------

  const submitClaim = async (e: FormEvent) => {
    e.preventDefault()
    const code = inviteCode.trim()
    if (!code || claimBusy) return
    setClaimBusy(true)
    setClaimFault(null)
    const res = await postClaim(code, 'guided')
    if (res.ok) {
      const kept = storeDeviceToken(res.body.device_token)
      setInviteCode('')
      append({ kind: 'note', lines: [res.body.message] })
      if (!kept) append({ kind: 'note', lines: [TOKEN_NOT_KEPT] })
      void loadPool()
    } else {
      // 403/409 carry the API's System-voice lines verbatim, a 429 the same
      // line inside {message, code}; render them so.
      const d = res.detail as { message?: unknown } | string | null
      setClaimFault(
        typeof d === 'string'
          ? d
          : d && typeof d.message === 'string'
            ? d.message
            : `[HTTP ${res.status || 'unreachable'}]`,
      )
    }
    setClaimBusy(false)
  }

  // --- action send path ---------------------------------------------------------

  const handleFailure = useCallback(
    (label: string | null, status: number, detail: unknown, retry: RetryTicket | null) => {
      if (status === 401) {
        authLoss()
        return
      }
      if (status === 429) {
        // A paid-layer degrade or a turn still in flight: NOT a fault. Keep the
        // ticket: nothing new committed under this id, and if the earlier send
        // of it did commit, re-sending returns that turn instead of a second
        // one (audit 2026-10-24, claude #3).
        setRetry(retry)
        append({ kind: 'note', lines: degradeLines(detail) })
        return
      }
      if (status === 409) {
        setRetry(retry)
        append({
          kind: 'fault',
          label,
          lines: [
            '<<Another hand moved the Chronicle first.>>',
            '[Retry: commit the same declaration again. It will be heard once.]',
          ],
        })
      } else if (status === 422) {
        setRetry(null)
        append({ kind: 'fault', label, lines: ['<<Refused.>>', ...violationLines(detail)] })
      } else if (status === 410) {
        // The moment has passed for this id: a fresh declaration needs a fresh id.
        setRetry(null)
        append({
          kind: 'fault',
          label,
          lines: [typeof detail === 'string' ? detail : `<<Refused.>> [HTTP ${status}]`],
        })
      } else if (status === 502) {
        // The Quill mis-hears you (nothing committed), or a proxy lost a
        // response that may have committed: either way the same id is safe.
        setRetry(retry)
        append({
          kind: 'fault',
          label,
          lines: [typeof detail === 'string' ? detail : `<<Refused.>> [HTTP ${status}]`],
        })
      } else if (status === 500 || status === 503 || status === 504 || status === 0) {
        // Outcome unknown: the engine may have committed before the error, so
        // the same id is the only safe re-send (audit codex-001, third run).
        setRetry(retry)
        append({
          kind: 'fault',
          label,
          lines: [
            '<<The Quill does not answer.>>',
            ...(typeof detail === 'string' ? [`[${detail}]`] : []),
          ],
        })
      } else {
        setRetry(null)
        append({
          kind: 'fault',
          label,
          lines: [
            '<<The record refuses the command.>>',
            `[HTTP ${status}${typeof detail === 'string' ? `: ${detail}` : ''}]`,
          ],
        })
      }
    },
    [append, authLoss],
  )

  const recordResolved = useCallback(
    async (label: string, commandId: string, body: ActionResolved, typed: boolean) => {
      // A re-send answered from canon is the turn already shown: no second block.
      if (entriesRef.current.some((e) => e.kind === 'action' && e.commandId === commandId)) {
        await refreshScene()
        return
      }
      append({
        kind: 'action',
        label,
        commandId,
        outcome: body.outcome,
        assessment: body.assessment,
        narration: body.narration,
        absorbed: body.absorbed,
        systemNote: body.system_note ?? null,
        gate: body.narration_meta?.gate ?? null,
        eventId: null, // a live POST response carries no narration_event_id
        intent: body.intent,
        typed,
      })
      await refreshScene()
    },
    [append, refreshScene],
  )

  const sendAction = useCallback(
    async (
      label: string,
      signature: string,
      send: (commandId: string) => ReturnType<typeof postActionText>,
    ): Promise<SendKind> => {
      if (busy) return 'busy'
      const commandId = takeCommandId(signature)
      setBusy(true)
      setRetry({ signature, commandId }) // a lost response can be re-sent as-is
      try {
        const res = await send(commandId)
        let kind: SendKind
        const typed = signature.startsWith('text:')
        if (res.ok) {
          if (res.body.pending_confirmation) {
            // <<Proceed?>> beat (interface decision 2): nothing resolved yet. The
            // ticket stays, so a re-tap after a reload brings this beat back
            // rather than a new one (audit codex-006).
            setPendingBeat({ commandId, label, assessment: res.body.assessment, typed })
            kind = 'pending'
          } else {
            setRetry(null)
            await recordResolved(label, commandId, res.body, typed)
            kind = 'resolved'
          }
        } else {
          handleFailure(label, res.status, res.detail, { signature, commandId })
          kind = 'failed'
        }
        return kind
      } finally {
        setBusy(false) // never leave the composer frozen, whatever threw
      }
    },
    // takeCommandId reads refs only — stable by construction, not a dep.
    [busy, handleFailure, recordResolved],
  )

  const sendTyped = (e: FormEvent) => {
    e.preventDefault()
    const text = composerText.trim()
    if (!text) return
    // Composer-loss fix (audit P2): DON'T clear on send. Clear only once the
    // typed action has committed AND the field still holds that exact text —
    // so an in-flight request, a failure, a 429 degrade, or a declined
    // <<Proceed?>> beat all preserve the text for retry, and new typing while
    // the Quill writes is never clobbered.
    void sendAction(text, `text:${text}`, (id) => postActionText(id, text)).then((kind) => {
      if (kind === 'resolved') setComposerText((prev) => (prev.trim() === text ? '' : prev))
    })
  }

  const sendCanned = (ci: CannedIntent) => {
    // Structured quick-picks never touch the composer (the player may be
    // mid-sentence there); the engine path is always available, even degraded.
    // The phone's opened list folds away so the story shows again.
    setChipsOpen(false)
    const label = scene ? chipLabel(ci, scene) : ci.label
    void sendAction(label, `canned:${ci.id}`, (id) => postActionIntent(id, ci.intent))
  }

  // Travel to a scene exit (movement). Sends a structured movement intent to the
  // authored destination — no parsing, no guessing where you can go.
  const sendGo = (exit: SceneExit) => {
    const intent: Intent = {
      action_type: 'movement',
      target_entity_ids: [exit.id],
      approach: `travel to ${exit.name}`,
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
      movement_scope: 'away',
    }
    setChipsOpen(false)
    void sendAction(`Go to ${exit.name}`, `go:${exit.id}`, (id) => postActionIntent(id, intent))
  }

  // --- <<Proceed?>> beat ---------------------------------------------------------

  const confirmBeat = async () => {
    if (!pendingBeat || busy) return
    setBusy(true)
    try {
      const res = await postActionConfirm(pendingBeat.commandId)
      let keepBeat = false
      if (res.ok && !res.body.pending_confirmation) {
        setRetry(null)
        await recordResolved(pendingBeat.label, pendingBeat.commandId, res.body, pendingBeat.typed)
        // The beat committed — clear the composer only if it still holds the
        // typed declaration (canned beats never match, so their text is safe).
        setComposerText((prev) => (prev.trim() === pendingBeat.label ? '' : prev))
      } else if (!res.ok) {
        // A lost or not-yet answer keeps the beat: Proceed again re-sends the same
        // id, and a confirm that did commit is answered from canon (codex-006).
        keepBeat = [0, 409, 429, 500, 502, 503, 504].includes(res.status)
        handleFailure(pendingBeat.label, res.status, res.detail, keepBeat ? pendingRetryRef.current : null)
      }
      if (!keepBeat) setPendingBeat(null)
    } finally {
      setBusy(false)
    }
  }

  /** Declining just dismisses — the moment expires diegetically, server-side. */
  const declineBeat = () => {
    setRetry(null)
    setPendingBeat(null)
  }

  // --- dev-only console helper (409/422 drills; never in prod builds) -------------

  const devPost = useCallback(
    async (body: unknown) => {
      const res = await postActionRaw(body)
      if (res.ok && !res.body.pending_confirmation) {
        const commandId =
          body && typeof body === 'object' && 'command_id' in body
            ? String((body as { command_id: unknown }).command_id)
            : '(raw)'
        await recordResolved('(dev) raw command', commandId, res.body, false)
      } else if (!res.ok) {
        handleFailure('(dev) raw command', res.status, res.detail, null)
      }
      return res
    },
    [recordResolved, handleFailure],
  )

  useEffect(() => {
    if (!import.meta.env.DEV) return
    const w = window as unknown as { __eq?: unknown }
    w.__eq = {
      post: devPost,
      fault: (status: number, detail?: unknown) =>
        handleFailure('(dev) synthetic fault', status, detail ?? null, null),
    }
    return () => {
      delete w.__eq
    }
  }, [devPost, handleFailure])

  // --- transcript autoscroll -------------------------------------------------------

  useEffect(() => {
    const el = transcriptRef.current
    if (!el) return
    // Land on the TOP of the newest turn (not the absolute bottom) so a long
    // response reads from its first line — the typewriter then follows the
    // typing tail into view. (George: "appear as if typed, not a dump I have
    // to scroll back up".) While the Quill is writing, hold position.
    if (busy) {
      el.scrollTop = el.scrollHeight
      return
    }
    const turns = el.querySelectorAll<HTMLElement>('.turn')
    const last = turns[turns.length - 1]
    if (last) el.scrollTop = Math.max(0, last.offsetTop - el.offsetTop - 8)
    else el.scrollTop = el.scrollHeight
  }, [entries, busy])

  // --- onboarding / boot screens ------------------------------------------------------

  if (phase === 'onboarding') {
    return (
      <div className="app">
        <header className="masthead">
          <h1>QUILLTOUCHED</h1>
          <p className="masthead-tagline">The System records what you know, not what is true.</p>
        </header>
        <main className="boot">
          <section className="system-frame">
            <p className="system-line">
              &lt;&lt;An unclaimed volume waits. Speak the word that opens it.&gt;&gt;
            </p>
            <form className="claim-form" onSubmit={submitClaim}>
              <input
                className="claim-input"
                type="text"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                placeholder="invite code"
                aria-label="Invite code"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
              <button
                type="submit"
                className="system-action"
                disabled={claimBusy || inviteCode.trim() === ''}
              >
                {claimBusy ? 'Claiming…' : 'Claim your volume'}
              </button>
            </form>
            {claimFault && (
              <p className="system-detail claim-fault" role="alert">
                {claimFault}
              </p>
            )}
          </section>
        </main>
      </div>
    )
  }

  if (phase === 'chargen') {
    return (
      <div className="app app--creation">
        <CreationScreen
          pool={pool ?? []}
          onCommit={commitChargen}
          busy={chargenBusy}
          fault={chargenFault}
        />
      </div>
    )
  }

  if (phase !== 'play' || scene === null) {
    return (
      <div className="app">
        <header className="masthead">
          <h1>QUILLTOUCHED</h1>
        </header>
        <main className="boot">
          {phase === 'loading' ? (
            <section className="system-frame" aria-busy="true">
              <p className="system-line">&lt;&lt;Seeking the Quill&hellip;&gt;&gt;</p>
            </section>
          ) : (
            <section className="system-frame system-frame--fault" role="alert">
              <p className="system-line">&lt;&lt;The Quill does not answer.&gt;&gt;</p>
              {sceneFault && <p className="system-detail">[{sceneFault}]</p>}
              <button type="button" className="system-action" onClick={() => void loadScene()}>
                Seek again
              </button>
            </section>
          )}
        </main>
      </div>
    )
  }

  // --- play screen (layout v3) ---------------------------------------------------------

  const chips = chipIntents(scene, selectedTarget)
  const exits = selectedTarget === null ? (scene.exits ?? []) : []
  const placed = placeEntities(scene.entities)
  const selectedEntity = scene.entities.find((e) => e.id === selectedTarget) ?? null
  const background = backgroundFor(scene.location.type)
  const compact = entries.slice(-4)
  // The newest action entry types in (useTypewriter); older ones render whole.
  const latestActionKey = [...entries].reverse().find((e) => e.kind === 'action')?.key
  const isCodex = railScreen === 'codex'
  const isCharacter = railScreen === 'character'
  // How the player knows each id (marks, workings): the server's labels, then
  // what this scene shows. Rendered through labelOf, never as a raw id.
  const names: ReadonlyMap<string, string> = new Map([
    ...Object.entries(scene.labels ?? {}),
    [scene.location.id, scene.location.name],
    ...scene.entities.map((e): [string, string] => [e.id, e.name]),
    ...(scene.exits ?? []).map((x): [string, string] => [x.id, x.name]),
  ])

  // Status facts: from scene.facts; without them the bar shows date only.
  const facts: StatusFacts | null = scene.facts ?? null
  const activeTimer = facts && facts.active_timers.length > 0 ? facts.active_timers[0] : null
  const extraTimers = facts ? Math.max(0, facts.active_timers.length - 1) : 0

  const tapEntity = (entityId: string) => {
    setSelectedTarget((prev) => (prev === entityId ? null : entityId))
  }

  const tabs = (where: 'top' | 'bottom') => (
    <nav className={`tabs tabs--${where}`} aria-label="Screens">
      {RAIL_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className="tab"
          aria-current={railScreen === tab.id ? 'page' : undefined}
          onClick={() => setRailScreen(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )

  return (
    <div className="app app--play">
      {/* Top bar. Date is Chronicle-exact; coin + active timer render from
          scene.facts when the API exposes them — numbers are never invented. */}
      <header className="topbar">
        <div className="topbar-place">
          <h1 className="place-name">{scene.location.name}</h1>
          <p className="place-facts">
            {facts?.coin != null && <span className="fact-coin">{facts.coin} copper</span>}
            <span className="fact-date">{scene.world_date}</span>
            {activeTimer && (
              <span className="fact-timer">
                {activeTimer.label ?? activeTimer.kind}, due {activeTimer.due_world_date}
                {extraTimers > 0 ? ` (+${extraTimers})` : ''}
              </span>
            )}
          </p>
        </div>
        {tabs('top')}
      </header>

      <div className="screen">
        {isCodex ? (
          codexPhase === 'ready' && codex ? (
            <CodexScreen
              data={codex}
              sceneLocation={scene.location}
              onSeedComposer={seedComposer}
            />
          ) : (
            <main className="codex-screen codex-screen--boot">
              <header className="codex-head">
                <h2 className="codex-title">Codex</h2>
              </header>
              {codexPhase === 'loading' || codexPhase === 'idle' ? (
                <section className="system-frame" aria-busy="true">
                  <p className="system-line">&lt;&lt;Reading the Inquiry&hellip;&gt;&gt;</p>
                </section>
              ) : codexPhase === 'stub' ? (
                <section className="system-frame">
                  <p className="system-line">
                    &lt;&lt;The System has not yet indexed this page.&gt;&gt;
                  </p>
                </section>
              ) : (
                <section className="system-frame system-frame--fault" role="alert">
                  <p className="system-line">&lt;&lt;The Quill does not answer.&gt;&gt;</p>
                  {codexFault && <p className="system-detail">[{codexFault}]</p>}
                  <button
                    type="button"
                    className="system-action"
                    onClick={() => void loadCodex()}
                  >
                    Seek again
                  </button>
                </section>
              )}
            </main>
          )
        ) : isCharacter ? (
          selfPhase === 'ready' && self ? (
            <SelfScreen data={self} />
          ) : (
            <main className="self-screen self-screen--boot">
              <header className="self-head">
                <h2 className="self-name">Self</h2>
              </header>
              {selfPhase === 'loading' || selfPhase === 'idle' ? (
                <section className="system-frame" aria-busy="true">
                  <p className="system-line">&lt;&lt;Taking your own measure&hellip;&gt;&gt;</p>
                </section>
              ) : selfPhase === 'stub' ? (
                <section className="system-frame">
                  <p className="system-line">
                    &lt;&lt;You are not yet written into the world.&gt;&gt;
                  </p>
                </section>
              ) : (
                <section className="system-frame system-frame--fault" role="alert">
                  <p className="system-line">&lt;&lt;The Quill does not answer.&gt;&gt;</p>
                  {selfFault && <p className="system-detail">[{selfFault}]</p>}
                  <button
                    type="button"
                    className="system-action"
                    onClick={() => void loadSelf()}
                  >
                    Seek again
                  </button>
                </section>
              )}
            </main>
          )
        ) : (
          <div className="play-grid">
            {/* Scene: perceived manifest only (fog-of-war honest). Figures
                stand on their slot's foot line, scaled by kind and depth. */}
            <section
              className="scene-canvas"
              aria-label={`Scene: ${scene.location.name}`}
              onClick={(e) => {
                if (e.target === e.currentTarget) setSelectedTarget(null)
              }}
            >
              <div
                className="scene-stage"
                style={background ? { backgroundImage: `url(${background})` } : undefined}
                onClick={(e) => {
                  if (e.target === e.currentTarget) setSelectedTarget(null)
                }}
              >
                {placed.map(({ entity, x, y }) => {
                  const art = brokenArt.has(entity.id) ? null : spriteFor(entity.id, y)
                  return art ? (
                    <span
                      key={`shadow:${entity.id}`}
                      className="sprite-shadow"
                      style={{ left: `${x}%`, top: `${y}%`, width: `${art.widthPct * 0.45}%` }}
                      aria-hidden="true"
                    />
                  ) : null
                })}
                {placed.map(({ entity, x, y }) => {
                  const dispatched = entity.conditions.includes('dispatched')
                  const art = brokenArt.has(entity.id) ? null : spriteFor(entity.id, y)
                  const pressed = selectedTarget === entity.id
                  if (!art) {
                    // No art for this entity yet: a name label, never a
                    // placeholder figure.
                    return (
                      <button
                        key={entity.id}
                        type="button"
                        className={`entity-label${dispatched ? ' entity-label--dispatched' : ''}`}
                        style={{ left: `${x}%`, top: `${y}%` }}
                        aria-pressed={pressed}
                        onClick={() => tapEntity(entity.id)}
                      >
                        {entity.name}
                      </button>
                    )
                  }
                  return (
                    <button
                      key={entity.id}
                      type="button"
                      className={`sprite${dispatched ? ' sprite--dispatched' : ''}`}
                      style={{
                        left: `${x}%`,
                        top: `${y}%`,
                        width: `${art.widthPct}%`,
                        transform: `translate(-50%, -${art.foot * 100}%)`,
                      }}
                      aria-pressed={pressed}
                      aria-label={entity.name}
                      onClick={() => tapEntity(entity.id)}
                    >
                      <img
                        className="sprite-img"
                        src={art.src}
                        alt=""
                        draggable={false}
                        onError={() =>
                          setBrokenArt((prev) => new Set(prev).add(entity.id))
                        }
                      />
                      {dispatched && <span className="sprite-tag">dispatched</span>}
                    </button>
                  )
                })}
              </div>
              {selectedEntity && (
                <aside className="known-card" role="status">
                  <p className="known-name">{selectedEntity.name}</p>
                  <p className="known-kind">{selectedEntity.kind}</p>
                  <p className="known-conditions">
                    {selectedEntity.conditions.length > 0
                      ? selectedEntity.conditions.join(', ')
                      : 'no conditions of record'}
                  </p>
                </aside>
              )}
            </section>

            {/* Chronicle: the last few blocks, the full Chronicle a tap away. */}
            <main className="transcript" ref={transcriptRef} aria-live="polite">
              {entries.length > compact.length && (
                <button
                  type="button"
                  className="chronicle-open"
                  onClick={() => setHistoryOpen(true)}
                >
                  Open the full Chronicle ({entries.length} entries)
                </button>
              )}
              {entries.length === 0 && (
                <p className="transcript-empty">
                  The Chronicle of this volume opens with your first declaration.
                </p>
              )}
              {compact.map((entry) =>
                entry.kind === 'action' ? (
                  <TurnBlock
                    entry={entry}
                    key={entry.key}
                    names={names}
                    isLatest={entry.key === latestActionKey}
                  />
                ) : entry.kind === 'fault' ? (
                  <FaultBlock entry={entry} key={entry.key} />
                ) : (
                  <NoteBlock entry={entry} key={entry.key} />
                ),
              )}
              {busy && <p className="turn-waiting">&lt;&lt;The Quill is writing&hellip;&gt;&gt;</p>}
            </main>

            {/* Actions: suggestions as chips (rolled actions first), places to
                go, then live free text. */}
            <footer className="composer">
              {selectedEntity && (
                <p className="chips-for">
                  With {selectedEntity.name}
                  <button
                    type="button"
                    className="chips-for-clear"
                    onClick={() => setSelectedTarget(null)}
                    aria-label="Show all suggestions"
                  >
                    ×
                  </button>
                </p>
              )}
              {(chips.length > 0 || exits.length > 0) && (
                <div
                  className={`chips${chipsOpen ? '' : ' chips--collapsed'}`}
                  role="group"
                  aria-label="Suggested actions and places to go"
                >
                  {chips.map((ci, i) => (
                    <button
                      key={ci.id}
                      type="button"
                      className={`suggestion-chip${i >= PHONE_CHIPS ? ' suggestion-chip--extra' : ''}`}
                      disabled={busy}
                      onClick={() => sendCanned(ci)}
                    >
                      {chipLabel(ci, scene)}
                    </button>
                  ))}
                  {exits.map((ex) => (
                    <button
                      key={ex.id}
                      type="button"
                      className="suggestion-chip suggestion-chip--go suggestion-chip--extra"
                      disabled={busy}
                      onClick={() => sendGo(ex)}
                    >
                      Go to {ex.name}
                      {ex.carriage_days > 0
                        ? `, ${ex.carriage_days} day${ex.carriage_days > 1 ? 's' : ''}`
                        : ''}
                    </button>
                  ))}
                </div>
              )}
              {chips.length + exits.length > PHONE_CHIPS && (
                <button
                  type="button"
                  className="chips-more"
                  onClick={() => setChipsOpen((open) => !open)}
                >
                  {chipsOpen ? 'Fewer suggestions' : 'More suggestions'}
                </button>
              )}
              <form className="composer-row" onSubmit={sendTyped}>
                <input
                  ref={composerInputRef}
                  className="composer-freetext"
                  type="text"
                  value={composerText}
                  onChange={(e) => setComposerText(e.target.value)}
                  placeholder="Or say what you do…"
                  aria-label="Declare your action"
                  maxLength={2000}
                  autoCapitalize="sentences"
                />
                {composerText !== '' && (
                  <button
                    type="button"
                    className="composer-clear"
                    onClick={() => setComposerText('')}
                    disabled={busy}
                    aria-label="Clear the box"
                    title="Clear"
                  >
                    ×
                  </button>
                )}
                <button
                  type="submit"
                  className="composer-commit"
                  disabled={busy || composerText.trim() === ''}
                >
                  Send
                </button>
              </form>
            </footer>
          </div>
        )}
      </div>

      {tabs('bottom')}

      {/* <<Proceed?>> beat — one dialog per commitment; the roll resolves inside it. */}
      {pendingBeat && (
        <div className="modal-scrim" role="presentation">
          <div className="system-frame beat-dialog" role="dialog" aria-modal="true">
            <p className="system-line">{pendingBeat.assessment.summary}</p>
            {pendingBeat.assessment.world_minutes_cost > 0 && (
              <p className="system-detail">
                [Cost: {pendingBeat.assessment.world_minutes_cost} world-minutes]
              </p>
            )}
            <p className="system-detail">
              [The moment holds only until you act. Do something else first and it passes.]
            </p>
            <div className="beat-actions">
              <button
                type="button"
                className="system-action"
                disabled={busy}
                onClick={() => void confirmBeat()}
                // The dialog takes focus on open, so a keyboard player lands
                // on the choice it asks for (claude P3 #32).
                autoFocus
              >
                Proceed
              </button>
              <button
                type="button"
                className="system-action system-action--decline"
                disabled={busy}
                onClick={declineBeat}
              >
                Think better of it
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Full Chronicle — simple scroll modal over everything. */}
      {historyOpen && (
        <div className="modal-scrim" role="presentation" onClick={() => setHistoryOpen(false)}>
          <div
            className="chronicle-modal"
            role="dialog"
            aria-modal="true"
            aria-label="The full Chronicle"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="chronicle-head">
              <h2 className="chronicle-title">The Chronicle</h2>
              <button
                type="button"
                className="chronicle-close"
                onClick={() => setHistoryOpen(false)}
              >
                Close
              </button>
            </header>
            <div className="chronicle-scroll">
              {entries.map((entry) =>
                entry.kind === 'action' ? (
                  <TurnBlock entry={entry} key={entry.key} names={names} expandedByDefault />
                ) : entry.kind === 'fault' ? (
                  <FaultBlock entry={entry} key={entry.key} />
                ) : (
                  <NoteBlock entry={entry} key={entry.key} />
                ),
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
