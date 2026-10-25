/**
 * Live smoke drive — Team D verification tool (not part of the app bundle).
 *
 * Sprint 2 (accounts v1 + typed loop): claims an account, then drives the
 * REAL local API using the client's own pure modules — canned intents
 * (src/intents.ts), Chronicle rendering (src/render.ts), sprite/background
 * mapping (src/scene-art.ts). Node runs them via native type stripping
 * (tsconfig pins erasableSyntaxOnly for exactly this).
 *
 * Usage: the API must be running against a throwaway database (README,
 * "Running it locally") with EVERQUILL_INVITE_CODES seeded, then:
 *
 *   EVERQUILL_INVITE_CODE=<fresh code> node client/scripts/smoke.ts [http://localhost:8000]
 *   EVERQUILL_DEVICE_TOKEN=<token>     node client/scripts/smoke.ts   # reuse an account
 *
 * Add EVERQUILL_SMOKE_PAID=1 when the API has a real ANTHROPIC_API_KEY: only
 * then are the typed action (parser) and narration prose checked, because
 * they spend money. Without it the engine path is checked and the paid
 * checks print a NOTE.
 *
 * Exercises: guided claim -> creation (lowest roll on might) -> authed scene
 * (slots + sprite mapping) -> structured canned action -> typed free-text
 * action (paid) -> a declaration against Jorun that raises the <<Proceed?>>
 * beat when this build is outmatched (confirmation is covered
 * deterministically in api/tests) -> duplicate absorption -> /api/turns ->
 * unauthed 410 -> bad-token 401. Prints explicit PASS/FAIL lines; read
 * those, never the pipe status.
 */

import { CANNED_INTENTS, chipLabel } from '../src/intents.ts'
import { outcomeLines } from '../src/render.ts'
import { backgroundFor, spriteFor } from '../src/scene-art.ts'

const BASE = process.argv[2] ?? 'http://localhost:8000'
const session = `smoke.${Date.now().toString(36)}`
let counter = 0
const nextId = () => `${session}:${++counter}`

const PAID = process.env.EVERQUILL_SMOKE_PAID === '1'
let failures = 0
function check(name: string, ok: boolean, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? ` — ${extra}` : ''}`)
  if (!ok) failures += 1
}

let TOKEN = process.env.EVERQUILL_DEVICE_TOKEN ?? ''

async function api(
  path: string,
  body?: unknown,
  token: string | null = TOKEN,
): Promise<{ status: number; json: unknown }> {
  const res = await fetch(`${BASE}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      accept: 'application/json',
      ...(body === undefined ? {} : { 'content-type': 'application/json' }),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  return { status: res.status, json: await res.json().catch(() => null) }
}

interface ActionBody {
  pending_confirmation: boolean
  command_id: string
  absorbed?: boolean
  assessment?: { summary?: string; world_minutes_cost?: number } | null
  outcome?: { event_id: string; dice: unknown; outcome_tier: string | null }
  narration?: string | null
}

function printResolved(label: string, body: ActionBody) {
  console.log(`\n> ${label}   (command_id ${body.command_id})`)
  for (const line of outcomeLines(body.outcome as never)) console.log(`  ${line}`)
  if (body.narration) console.log(`  — narration —\n  ${body.narration.replace(/\n/g, '\n  ')}`)
  else console.log('  (narration: null)')
}

// --- 1. claim an account (accounts v1) -----------------------------------------

if (!TOKEN) {
  const code = process.env.EVERQUILL_INVITE_CODE
  if (!code) {
    console.log('FAIL  no EVERQUILL_INVITE_CODE or EVERQUILL_DEVICE_TOKEN in env')
    process.exit(1)
  }
  const { status, json } = await api('/api/claim', { invite_code: code, mode: 'guided' }, null)
  check(
    'POST /api/claim',
    status === 200,
    `${status} ${JSON.stringify((json as { detail?: unknown })?.detail ?? '')}`,
  )
  if (status !== 200) process.exit(1)
  const claimed = json as { device_token: string; world_id: string; message: string }
  TOKEN = claimed.device_token
  console.log('--- claim response (token masked) ---')
  console.log(
    JSON.stringify({ ...claimed, device_token: `${claimed.device_token.slice(0, 6)}…` }, null, 2),
  )

  // Guided creation: place the rolled values, lowest on might, so the beat
  // probe below meets an outmatched build where the dice allow one.
  const poolRes = await api('/api/chargen/pool')
  check('GET /api/chargen/pool', poolRes.status === 200, `${poolRes.status}`)
  const values = (poolRes.json as { values: { index: number; total: number }[] }).values
  const order = ['might', 'lore', 'presence', 'will', 'finesse', 'wits']
  const byTotal = [...values].sort((a, b) => a.total - b.total || a.index - b.index)
  const assignment = Object.fromEntries(order.map((apt, i) => [apt, byTotal[i].index]))
  const made = await api('/api/chargen', { name: 'Smoke', assignment })
  check('POST /api/chargen creates the character', made.status === 200, `${made.status}`)
  const again = await api('/api/chargen', { name: 'Smoke', assignment })
  check('a second creation is refused 409 (the client enters play)', again.status === 409, `${again.status}`)
}

// --- 2. authed scene: slots + sprite/background mapping --------------------------

const sceneRes = await api('/api/scene')
check('GET /api/scene (Bearer)', sceneRes.status === 200, `${sceneRes.status}`)
const scene = sceneRes.json as {
  world: string
  world_date: string
  location: { name: string; type: string | null }
  entities: {
    id: string
    name: string
    kind: string
    conditions: string[]
    slot: { slot_id: string; x_pct: number; y_pct: number } | null
  }[]
}
console.log('--- scene response (verbatim) ---')
console.log(JSON.stringify(scene, null, 2))

check(
  'scene carries a location type with a mapped background',
  backgroundFor(scene.location.type) !== null,
  `${scene.location.type} -> ${backgroundFor(scene.location.type)}`,
)
const slotted = scene.entities.filter((e) => e.slot !== null)
check(
  'every scene entity holds a slot',
  slotted.length === scene.entities.length,
  `${slotted.length}/${scene.entities.length}`,
)
for (const e of scene.entities) {
  // Committed opening-room entities must map to real sprite art. The PC
  // (kind 'character') is not drawn: the scene is the player's own view.
  if (e.kind === 'character') continue
  const art = spriteFor(e.id, e.slot?.y_pct ?? 75)
  check(`art resolves for ${e.id}`, art !== null, art?.src ?? 'none')
}

// --- 3. structured canned action (no parser dependency) --------------------------

const canned = CANNED_INTENTS.find((c) => c.id === 'charm-maren')!
const cannedId = nextId()
{
  const { status, json } = await api('/api/action', {
    command_id: cannedId,
    intent: canned.intent,
  })
  const body = json as ActionBody
  check(
    'POST canned intent (charm-maren) resolves',
    status === 200 && !body.pending_confirmation,
    `${status}`,
  )
  if (status === 200 && !body.pending_confirmation) {
    printResolved(chipLabel(canned, scene as never), body)
    if (PAID) {
      check(
        'canned action carries narration prose',
        typeof body.narration === 'string' && body.narration.length > 0,
      )
    }
  }
}

// --- 4. typed free text through the live parser ----------------------------------

if (!PAID) {
  console.log('NOTE  typed text and narration skipped (set EVERQUILL_SMOKE_PAID=1 with a real key)')
} else {
  const text = 'ask the wary man what took his arm at the quarry'
  const { status, json } = await api('/api/action', { command_id: nextId(), text })
  const body = json as ActionBody
  check(
    'POST typed text parses + resolves',
    status === 200 && !body.pending_confirmation,
    `${status} ${JSON.stringify((json as { detail?: unknown })?.detail ?? '')}`,
  )
  if (status === 200 && !body.pending_confirmation) {
    printResolved(`"${text}"`, body)
    check(
      'typed action carries narration prose',
      typeof body.narration === 'string' && body.narration.length > 0,
    )
  }
}

// --- 5. the <<Proceed?>> beat: Dire-and-up pending -> confirm ---------------------

{
  // The tier is gap arithmetic on THIS account's aptitudes vs the target's
  // true sheet. Creation put the lowest roll on might, and Jorun (threat 6)
  // is in the room, so most builds are outmatched; a strong roll may not be.
  const square = CANNED_INTENTS.find((c) => c.id === 'square-jorun')!
  const candidates: { label: string; body: Record<string, unknown> }[] = [
    { label: chipLabel(square, scene as never), body: { intent: square.intent } },
  ]
  let beat: { commandId: string; text: string; body: ActionBody } | null = null
  for (const candidate of candidates) {
    const commandId = nextId()
    const { status, json } = await api('/api/action', { command_id: commandId, ...candidate.body })
    const body = json as ActionBody
    if (status === 200 && body.pending_confirmation) {
      beat = { commandId, text: candidate.label, body }
      break
    }
    const tier = body?.outcome
      ? (body.outcome as { tier_resolved?: string }).tier_resolved
      : undefined
    console.log(`  (no beat: "${candidate.label}" -> ${status}, pending=${body?.pending_confirmation}, tier=${tier})`)
  }
  if (beat === null) {
    console.log('NOTE  no beat for this build (not outmatched); confirmation is covered in api/tests')
  }
  if (beat) {
    console.log('--- beat assessment (verbatim) ---')
    console.log(JSON.stringify(beat.body.assessment, null, 2))
    const summary = beat.body.assessment?.summary ?? ''
    check('assessment summary ends with Proceed?>>', summary.includes('Proceed?>>'), summary)

    const { status, json } = await api('/api/action/confirm', { command_id: beat.commandId })
    const confirmed = json as ActionBody
    check(
      'POST /api/action/confirm resolves under the same command_id',
      status === 200 && !confirmed.pending_confirmation,
      `${status}`,
    )
    if (status === 200) {
      printResolved(`[confirmed] "${beat.text}"`, confirmed)
      const dice = confirmed.outcome?.dice as
        | { rolls: number[]; modifiers: { value: number }[]; total: number }
        | null
      check('confirmed outcome rolled honest dice', dice !== null)
      if (dice) {
        const sum = dice.rolls[0] + dice.rolls[1] + dice.modifiers.reduce((a, m) => a + m.value, 0)
        check('dice arithmetic (rolls + modifiers = total)', sum === dice.total, `${sum} vs ${dice.total}`)
      }
    }
  }
}

// --- 6. duplicate command_id -> idempotent absorption ------------------------------

{
  const { status, json } = await api('/api/action', { command_id: cannedId, intent: canned.intent })
  const body = json as ActionBody
  check(
    'duplicate command_id absorbed (200, absorbed=true)',
    status === 200 && body.absorbed === true,
    `${status}`,
  )
}

// --- 7. Chronicle rebuild endpoint ------------------------------------------------

{
  const { status, json } = await api('/api/turns?limit=50')
  const turns = (json as { turns?: { command_id: string }[] })?.turns ?? []
  check('GET /api/turns (reload rebuild)', status === 200, `${status}, ${turns.length} narrated`)
  if (PAID) {
    check('the narrated canned turn is in the rebuild', turns.some((t) => t.command_id === cannedId))
  }
}

// --- 8. the sealed shared world + bad tokens ---------------------------------------

{
  const { status, json } = await api(
    '/api/action',
    { command_id: nextId(), text: 'look around' },
    null,
  )
  check(
    'unauthed POST /api/action -> 410 (shared volume sealed)',
    status === 410,
    `${status} ${JSON.stringify((json as { detail?: unknown })?.detail ?? '')}`,
  )
}
{
  const { status } = await api('/api/scene', undefined, 'not-a-real-token')
  check('bad token -> 401 (client returns to onboarding)', status === 401, `${status}`)
}

console.log(failures === 0 ? '\nSMOKE PASSED' : `\nSMOKE FAILED (${failures})`)
process.exit(failures === 0 ? 0 : 1)
