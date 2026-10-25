# Everquill — Telemetry (Sprint 2 wave 2, Team F)

Structured JSON lines on stdout (one object per line), emitted by
`api/telemetry.py` and picked up verbatim by Railway logs. LLM cost rows are
ALSO persisted to `public.llm_usage` (migration 0007) so `GET /api/ops/usage`
can roll them up across restarts.

Filter live: `railway logs -n 200 --service everquill | grep '"kind":"llm_stage"'`

## Common fields

| Field | Type | Meaning |
|---|---|---|
| `ts` | string | UTC ISO-8601 (`2026-07-13T12:00:00Z`) |
| `kind` | string | Record type — one of the kinds below |

## `kind: "request"` — per-request timing (middleware)

| Field | Type | Meaning |
|---|---|---|
| `method` / `path` / `status` | | as before |
| `duration_ms` | float | Wall time through the whole stack |
| `turn` | object? | On `/api/action[/confirm]`: `command_id`, `world_id`, `status` (`pending`/`resolved`/`absorbed`), `absorbed`, `event_count`, `event_id`, `tier_resolved`, `outcome_tier` |

## `kind: "llm_stage"` — per-stage LLM cost (the per-turn cost telemetry)

One line per model call, mirrored into `public.llm_usage`.

| Field | Type | Meaning |
|---|---|---|
| `stage` | string | `parse` (haiku) or `narrate` (sonnet) |
| `model` | string | exact model id sent |
| `input_tokens` / `output_tokens` | int | uncached input / output |
| `cache_read_input_tokens` | int | tokens served from prompt cache (~0.1x price) — nonzero on the 2nd+ call proves the cache_control breakpoints work |
| `cache_creation_input_tokens` | int | tokens written to cache (~1.25x price) |
| `latency_ms` | int | wall time of the API call |
| `command_id` / `world_id` | string | which turn |

## `kind: "assemble"` — deterministic context assembly (no tokens billed)

`assembler_version`, `content_hash` (sha256 of the canonical envelope),
`context_tokens` (estimator), `latency_ms`, `command_id`, `world_id`,
`event_id`. TODO(A-team): decision 3 wants the prose + assembly provenance
stored as a narration EVENT bound to the outcome event id; folds currently
reject unknown event types, so this lives in telemetry until the store
offers a clean path.

## `kind: "narration_error"` / `"parse_error"`

Narration failure NEVER blocks the outcome (decision 3): the turn returns
`narration: null` and one of these lines records why (`stage`: `assemble` or
`narrate`, plus `error`). `parse_error` accompanies a 502 on free-text turns.

## `kind: "account_claimed"` / `"world_bootstrap"`

Accounts v1: claim events (account_id, world_id) and per-account world
bootstrap summaries (schema, migrations_applied, genesis/chargen applied,
content_drift).

## `kind: "bootstrap"` / `"startup"` / `"startup_warning"` / `"startup_error"` / `"contract_violation"`

Unchanged from Sprint 1 (legacy shared world + process lifecycle).

## GET /api/ops/usage — daily rollup

Auth: `Authorization: Bearer <EVERQUILL_OPS_TOKEN>` (env; keep the value in
your secret store). Returns per (day, stage, model): calls, token sums,
avg latency, and `estimated_cost_usd` computed from the price table in
`api/main.py` (`_PRICES_PER_MTOK` — haiku $1/$5, sonnet-5 $3/$15 per MTok;
cache reads 0.1x input, cache writes 1.25x input; sonnet intro pricing runs
cheaper through 2026-08-31, so estimates are conservative). Keep the table
in sync when models change.
