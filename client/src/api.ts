/**
 * API layer — the ONLY place the client talks to the server (Team D, Sprint 2).
 *
 * Endpoints (Team F, api/main.py):
 *   POST /api/claim            {invite_code} -> {device_token, account_id, world_id, message}
 *   GET  /api/scene            perceived scene manifest (Bearer -> YOUR world)
 *   POST /api/action           {command_id, intent | text} -> resolved outcome
 *                              + narration, OR {pending_confirmation, assessment}
 *   POST /api/action/confirm   {command_id} -> resolve a pending <<Proceed?>> beat
 *   GET  /api/codex            authed — the player's Inquiry claims as fact
 *                              cards (KnownState only, no true values) —
 *                              Team F, Sprint 3. See CodexResponse below.
 *
 * Accounts v1 (locked interface decision 1): every game call carries
 * `Authorization: Bearer <device_token>`. The token lives in localStorage
 * — it is the ONLY key to the account's world. A 401 means the server no
 * longer knows the token: the app clears it and returns to onboarding.
 * The `world` body/query field is deliberately never sent: the token IS
 * the world scope (account world ids are `harrowdown--<prefix>`).
 *
 * Types mirror docs/contracts/intent.schema.json (v1.1),
 * docs/contracts/outcome.schema.json, and api/main.py response shapes
 * verbatim. The client renders ONLY what these contracts carry — no
 * invented fields, no client-side rules.
 *
 * Base URL: relative /api by default (Vite dev proxy / same-origin prod).
 * VITE_API_BASE (BARE origin, no /api suffix — client paths already
 * include /api/...) overrides for split-origin deploys.
 */

const API_BASE = (
  (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
).replace(/\/+$/, '')

// --- device token (accounts v1) -----------------------------------------------

const TOKEN_KEY = 'eq_device_token'

// Held in memory as well, so a browser that refuses storage (private mode, full
// quota) keeps the volume for this tab instead of 401-ing a burned invite.
let heldToken: string | null = null

export function deviceToken(): string | null {
  if (heldToken) return heldToken
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null // storage blocked (private mode): the app stays on onboarding
  }
}

/** False when the browser would not keep it: the volume lasts this tab only. */
export function storeDeviceToken(token: string): boolean {
  heldToken = token
  try {
    localStorage.setItem(TOKEN_KEY, token)
    return true
  } catch {
    return false
  }
}

export function clearDeviceToken(): void {
  heldToken = null
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // nothing to clear
  }
}

// --- intent contract (intent.schema.json v1.1) ------------------------------

export type ActionType =
  | 'physical'
  | 'social'
  | 'movement'
  | 'observation'
  | 'research'
  | 'craft'
  | 'train'
  | 'dialogue'
  | 'rest'
  | 'meta'

export type StatHint = 'might' | 'finesse' | 'wits' | 'will' | 'presence' | 'lore'

export interface IntentDialogue {
  addressee_id: string | null
  quoted_speech: string | null
}

export interface IntentDurationHint {
  mode: 'until_condition' | 'explicit'
  text: string // the player's words, for the narrator; never bound
  until: 'dawn' | 'midday' | 'dusk' | 'midnight' | null
  amount: number | null
  unit: 'minute' | 'hour' | 'day' | null
}

export interface Intent {
  action_type: ActionType
  target_entity_ids: string[]
  approach: string
  stat_hint: StatHint | null
  dialogue: IntentDialogue | null
  plausibility_hint: 'plausible' | 'dubious' | 'impossible_in_fiction'
  duration_hint: IntentDurationHint | null
  ambiguity_flags: string[]
  // v1.3 closed decision fields: the engine reads these, never the approach text.
  addressee: 'room' | 'person' | null
  speech_act: 'question' | 'introduction' | 'statement' | null
  topic_ids: string[]
  transaction: IntentTransaction | null
  invoked_law_ids: string[]
  movement_scope: 'here' | 'away' | null
}

export interface IntentTransaction {
  kind: 'buy' | 'give_coin'
  price_key: string | null
  count: number
}

// --- accounts (POST /api/claim) ------------------------------------------------

export interface ClaimResponse {
  device_token: string
  account_id: string
  world_id: string
  message: string
}

// --- scene manifest (GET /api/scene) ----------------------------------------

export interface SceneSlot {
  slot_id: string
  x_pct: number
  y_pct: number
}

export interface SceneEntity {
  id: string
  name: string
  kind: string // npc | creature | item | prop | character (fog-of-war: render whatever arrives)
  conditions: string[] // externally visible only (dispatched, wounded, ...)
  portrait: string | null
  slot: SceneSlot | null // null = no slot map for this location type / slots ran out
}

export interface SceneExit {
  id: string
  name: string
  carriage_days: number
}

/**
 * One running world-clock timer, surfaced for the status strip (zone 1).
 * `due_world_date` is the Chronicle rendering of the timer's world_due
 * (`clock.world_date(world_due)`), so the client shows "Day N, HH:MM"
 * and NEVER a raw minute count. `label` is Team A/B's fictional-progress
 * phrase ("cataloguing", "on the road") when authored — null otherwise.
 */
export interface ActiveTimer {
  timer_id: string
  kind: string // research | travel | craft | rest | ...
  label: string | null
  due_world_date: string
}

/**
 * Chronicle-exact status facts for the header (roadmap §3.8 zone 1).
 * These are KnownState.ChronicleFacts values — coin is EXACT (numerals
 * allowed in the Chronicle), never a true-sheet number. Serve this on
 * GET /api/scene as `facts` (preferred) or a GET /api/facts of the same
 * shape (Team A/F, Sprint 3). `coin: null` = the surface does not expose
 * it yet; the strip then shows date only and invents nothing.
 */
export interface StatusFacts {
  coin: number | null
  active_timers: ActiveTimer[]
}

export interface Scene {
  world: string
  world_date: string
  location: { id: string; name: string; type: string | null; region: string | null }
  entities: SceneEntity[]
  exits?: SceneExit[]
  /** Optional (Sprint 3): coin + active timers for the status strip.
   *  Absent until Team A/F wire it — the strip renders date only. */
  facts?: StatusFacts
  /** {id -> how the player knows it}: an NPC's descriptor until its name is
   *  learned, places and things by name, `you` for the player. Render every id
   *  through this (render.ts labelOf); an id itself can spell a true name. */
  labels?: Record<string, string>
}

// --- outcome contract (outcome.schema.json) ----------------------------------

export interface DiceModifier {
  label: string
  value: number
}

export interface Dice {
  rolls: number[]
  modifiers: DiceModifier[]
  total: number
}

export interface Claim {
  subject_entity_id: string
  claim_text: string
  value_or_range: string | null
  layer: 'chronicle' | 'inquiry'
  source: string
  observer: string | null
  method: string
  world_date: string
  scope: string
  confidence: 'uncorroborated' | 'consistent' | 'strongly_corroborated'
}

// --- codex contract (GET /api/codex) ----------------------------------------

/**
 * One Inquiry-layer claim as a Codex fact card. Mirrors
 * `everquill_engine/views.py::InquiryClaim` (docs/engine/claims.md) — the
 * KnownState surface, so it carries NO true-sheet value, only what the
 * player has learned and where it came from.
 *
 * Rendering laws honoured by the Codex screen:
 *   - `confidence` is a WORD (evidence-consistency display value). The
 *     numeric `strength` basis points are DELIBERATELY not on this type —
 *     the Codex never shows a confidence number.
 *   - contested is ENGINE-MARKED, never client-inferred: a card shows a
 *     contradiction badge iff `status === 'contested'` or
 *     `contested_by_claim_id !== null` (the engine emits both ways when it
 *     seats two conflicting claims). The client never invents connections.
 *   - `subject_label` is the KNOWN name of the subject (Team F: from the
 *     KnownState scene/roster). null → the client prettifies the id.
 */
export interface CodexClaim {
  claim_id: string
  subject_entity_id: string // contract form
  subject_label: string | null
  claim_text: string
  value_or_range: string | null
  source: string
  observer: string | null // contract form when an entity id
  method: string // acquisition method, human phrase
  world_date: string // when acquired (Chronicle "Day N, HH:MM")
  scope: string
  confidence: string // WORD only (uncorroborated | consistent | strongly_corroborated | ...)
  status: string // asserted | corroborated | contested (superseded/retracted never served)
  journal_flag: boolean // inherited from a journal
  predicate: string // closed vocabulary (observed_statement, threat_assessed, ...)
  hop_count: number
  contested_by_claim_id: string | null
}

/**
 * A place the player KNOWS (map-in-Codex v0). Everything not in this list
 * is "blank past the ridge" — the client renders no unknown geography.
 * Team F populates from travel claims / scene history; [] until wired (the
 * current scene location is always merged in client-side as known).
 */
export interface CodexLocation {
  location_id: string
  name: string
  region: string | null
}

export interface CodexResponse {
  world_id: string
  world_date: string
  claims: CodexClaim[]
  known_locations: CodexLocation[]
}

// --- self view (GET /api/self) ----------------------------------------------

/**
 * One line of the player's standing (Sprint 4, The Self view). This is the
 * player's BELIEVED standing — how they read a person or a town — NOT an
 * objective fact (you cannot see inside anyone's head; a read can be wrong,
 * and the true feeling is discoverable, never shown here). `value` drives the
 * meter ONLY; the screen never prints the raw number (George: words + a meter).
 */
export interface SelfStanding {
  scope: 'disposition' | 'standing'
  subject_id: string // contract form
  subject_name: string // resolved display name
  read: number // the word's place on its scale (meter fill), never the raw value
  read_max: number // the scale's reach either side of neutral
  descriptor: string // the read: 'warm to you', 'esteemed here', ...
}

/**
 * The player's Self view (GET /api/self) — who they are as they know
 * themselves. The player KNOWS their own build (unlike an NPC's hidden true
 * sheet), so `aptitudes` are shown. Standing is BELIEVED (see SelfStanding).
 */
export interface SelfResponse {
  world: string
  character_id: string
  name: string
  origin: string
  aptitudes: Record<string, number>
  hp: number
  hp_max: number
  wounds: string // a WORD, never a raw hp number
  coin: number
  named_abilities: string[]
  marks: string[]
  dispositions: SelfStanding[] // per known person, warmest first
  standings: SelfStanding[] // per town
  renown: number
  renown_descriptor: string
}

export type StateDelta =
  | { delta_type: 'hp'; entity_id: string; amount: number; cause: string | null }
  | { delta_type: 'wound_transition'; entity_id: string; effect: 'wounded' | 'recovered' | 'dispatched' }
  | { delta_type: 'coin'; entity_id: string; amount: number; reason: string | null }
  | {
      delta_type: 'inventory'
      entity_id: string
      item_id: string
      op: 'add' | 'remove'
      quantity: number
    }
  | { delta_type: 'flag'; entity_id: string; flag_key: string; value: boolean | string | number }
  | {
      delta_type: 'position'
      entity_id: string
      from_location_id: string | null
      to_location_id: string
    }
  | { delta_type: 'intel'; claim: Claim }
  | {
      delta_type: 'deed'
      actor_entity_id: string
      description: string
      location_id: string
      witness_ids: string[]
      notoriety: number
      world_date: string
    }
  | { delta_type: 'title'; entity_id: string; title: string; deed_ref: string | null }
  | { delta_type: 'clock'; clock_id: string; advance: number }
  | { delta_type: 'timer_started'; timer_id: string; kind: string; due_world_time: string }
  | {
      delta_type: 'death_record'
      entity_id: string
      cause: string
      location_id: string
      witness_ids: string[]
      body_disposition: string | null
      journal_disposition: string | null
      rumor_seeds: string[]
      world_date: string
    }

export interface Outcome {
  event_id: string
  tier_resolved:
    | 'trivial'
    | 'routine'
    | 'risky'
    | 'desperate'
    | 'hopeless'
    | 'sealed'
    | 'impossible'
  risk_label_shown: 'guarded' | 'perilous' | 'dire' | 'desperate' | 'suicidal' | null
  outcome_tier: 'strong_hit' | 'hit_with_complication' | 'miss' | null
  dice: Dice | null
  state_deltas: StateDelta[]
  narration_constraints: string[]
  system_note?: string | null
  movement_blocked?: boolean
}

// --- turn pipeline responses (POST /api/action, /api/action/confirm) -----------

/** The pre-roll System read (everquill_engine/beat.py Assessment, verbatim). */
export interface Assessment {
  command_id: string
  character_id: string
  tier: string
  risk_label: string | null
  confirmation_required: boolean
  world_minutes_cost: number
  created_world_time: number | null
  expires_world_time: number | null
  summary: string // the System dialog line — rendered VERBATIM
}

/**
 * Assembler/gate metadata on a resolved turn (Hardening Pass 1). `gate` is the
 * narration path outcome — `pass` | `regenerated` | `fallback` (live prose),
 * `movement_blocked` / `degraded` (narration skipped, `system_note` set), or
 * `canonical_record` (served from the stored canon on duplicate/reconnect).
 */
export interface NarrationMeta {
  assembler_version?: string
  content_hash?: string
  model?: string
  gate?: string
}

export interface ActionResolved {
  pending_confirmation: false
  absorbed: boolean
  world_id: string
  command_id: string
  intent: Intent | null
  assessment: Assessment | null
  outcome: Outcome
  narration: string | null // narrator prose bound to the outcome; null on narrator failure / degrade
  narration_meta: NarrationMeta | null
  /**
   * System-voice line on a deterministic no-narration path: null normally; set
   * (with `narration: null`) when the deterministic deed still committed but the
   * paid narrator was skipped, e.g. over budget or blocked movement.
   * Rendered diegetically — the deed is real, the Quill merely rests its pen.
   */
  system_note?: string | null
}

export interface ActionPending {
  pending_confirmation: true
  world_id: string
  command_id: string
  intent: Intent
  assessment: Assessment
}

export type ActionResponse = ActionResolved | ActionPending

// --- Chronicle reconnect (GET /api/turns) -------------------------------------

/**
 * One CANONICAL public-turn record (audit #1). The same canon the turn
 * pipeline returned, served for reconnect/reload so the Chronicle rebuilds
 * without re-resolving. Only NARRATED turns appear here — a degraded/failed
 * turn has no canon record and is absent (its outcome is still canon via the
 * /api/action replay, just without prose). See docs/ops/turns-api.md.
 */
export interface TurnRecord {
  command_id: string // stable, client-deterministic — the dedupe key
  outcome: Outcome
  narration: string | null
  narration_meta: NarrationMeta | null // gate === 'canonical_record' here
  narration_event_id: number // monotonic append id — persist the max as ?since=
  world_time: number
}

export interface TurnsResponse {
  world_id: string
  world_date: string
  turns: TurnRecord[] // oldest-first — render top-to-bottom, no re-sort
}

// --- transport ----------------------------------------------------------------

/** status 0 = network unreachable (fetch threw). detail = FastAPI's `detail`. */
export type ApiResult<T> = { ok: true; body: T } | { ok: false; status: number; detail: unknown }

async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  const token = deviceToken()
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: {
        accept: 'application/json',
        ...(init?.body ? { 'content-type': 'application/json' } : {}),
        ...(token ? { authorization: `Bearer ${token}` } : {}),
      },
      ...init,
    })
  } catch {
    return { ok: false, status: 0, detail: null }
  }
  let parsed: unknown = null
  try {
    parsed = await res.json()
  } catch {
    // non-JSON body (proxy error page etc.) — keep null
  }
  if (!res.ok) {
    const detail =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? (parsed as { detail: unknown }).detail
        : parsed
    return { ok: false, status: res.status, detail }
  }
  return { ok: true, body: parsed as T }
}

export function postClaim(
  inviteCode: string,
  mode?: 'auto' | 'guided',
): Promise<ApiResult<ClaimResponse>> {
  const body: Record<string, unknown> = { invite_code: inviteCode }
  if (mode) body.mode = mode
  return request<ClaimResponse>('/api/claim', { method: 'POST', body: JSON.stringify(body) })
}

export function getScene(): Promise<ApiResult<Scene>> {
  return request<Scene>('/api/scene')
}

/**
 * The player's Inquiry claims as fact cards (Team F, Sprint 3). Filters are
 * applied client-side over the full set (the volume is tiny at alpha); the
 * optional query params below are a forward hook if F wants to filter
 * server-side — harmless when ignored. 404/501 = endpoint not built yet.
 */
export function getCodex(params?: {
  subject?: string
  source?: string
}): Promise<ApiResult<CodexResponse>> {
  const qs = new URLSearchParams()
  if (params?.subject) qs.set('subject', params.subject)
  if (params?.source) qs.set('source', params.source)
  const suffix = qs.toString() ? `?${qs}` : ''
  return request<CodexResponse>(`/api/codex${suffix}`)
}

/**
 * Recent canonical public-turn records for Chronicle reconnect/rebuild
 * (audit #1). Pass the persisted max `narration_event_id` as `?since=` for an
 * incremental catch-up (only strictly-newer turns); omit it for a full rebuild.
 * Turns arrive oldest-first; dedupe against the local cache by `command_id`.
 */
export function getTurns(params?: {
  since?: number | null
  limit?: number
}): Promise<ApiResult<TurnsResponse>> {
  const qs = new URLSearchParams()
  if (params?.since != null) qs.set('since', String(params.since))
  if (params?.limit != null) qs.set('limit', String(params.limit))
  const suffix = qs.toString() ? `?${qs}` : ''
  return request<TurnsResponse>(`/api/turns${suffix}`)
}

/**
 * The player's Self view (Sprint 4): own build + believed standing. Authed.
 * 503 before genesis (no character yet); 401 without a token.
 */
export function getSelf(): Promise<ApiResult<SelfResponse>> {
  return request<SelfResponse>('/api/self')
}

// --- guided-dice chargen (GET /api/chargen/pool, POST /api/chargen) ----------
// Contract shared with Codex's chargen API (ticket X3). The seed rolls a pool;
// the PLAYER places six of the values onto the six aptitudes (one is a spare).

/** One assignable pool value. `index` is the stable pool slot; `total` is the
 *  2d6 result the player places onto an aptitude. */
export interface ChargenPoolValue {
  index: number
  total: number
}

export interface ChargenPool {
  world: string
  /** Seven values: six base plus one spare. */
  values: ChargenPoolValue[]
}

/** Result of committing a build: the world is now genesised and playable. */
export interface ChargenResult {
  world_id: string
}

export function getChargenPool(): Promise<ApiResult<ChargenPool>> {
  return request<ChargenPool>('/api/chargen/pool')
}

/** Commit a placement. `assignment` maps each aptitude to a pool index. */
export function postChargen(
  name: string,
  assignment: Record<string, number>,
): Promise<ApiResult<ChargenResult>> {
  return request<ChargenResult>('/api/chargen', {
    method: 'POST',
    body: JSON.stringify({ name, assignment }),
  })
}

export function postActionIntent(
  commandId: string,
  intent: Intent,
): Promise<ApiResult<ActionResponse>> {
  return postActionRaw({ command_id: commandId, intent })
}

export function postActionText(
  commandId: string,
  text: string,
): Promise<ApiResult<ActionResponse>> {
  return postActionRaw({ command_id: commandId, text })
}

export function postActionConfirm(commandId: string): Promise<ApiResult<ActionResponse>> {
  return request<ActionResponse>('/api/action/confirm', {
    method: 'POST',
    body: JSON.stringify({ command_id: commandId }),
  })
}

/** Raw body variant — used by the dev-only console helper (422/409 drills). */
export function postActionRaw(body: unknown): Promise<ApiResult<ActionResponse>> {
  return request<ActionResponse>('/api/action', { method: 'POST', body: JSON.stringify(body) })
}
