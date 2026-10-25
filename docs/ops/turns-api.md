# `/api/turns` + degrade signals — Team D client contract (Hardening Pass 1)

Audit #1 (canonical public-turn record) and audit #4 (degrade-not-block) added
client-visible surfaces. This is the contract Team D wires the Chronicle and the
System-voice degrade UI against. Wave-2 Team F (api) owns it.

## `GET /api/turns` — Chronicle reconnect / rebuild

Authed (`Authorization: Bearer <device_token>`). Serves the player's recent
CANONICAL public-turn records — the same canon the turn pipeline returned —
so a reload/reconnect rebuilds the visible history without re-resolving anything.

Query params:

- `limit` — max turns to return (default `50`, clamped to `1..200`), newest
  `limit`, returned **oldest-first** (render top-to-bottom, no re-sort).
- `since` — a `narration_event_id` watermark; returns the OLDEST `limit` turns
  strictly newer than it (incremental catch-up, paging forward). A full page means
  call again with the page's highest `narration_event_id`. Omit for the newest page.

Response:

```jsonc
{
  "world_id": "harrowdown--ab12cd34",
  "world_date": "Year 1, Quarterday Eve, evening bell",
  "turns": [
    {
      "command_id": "turn-abc123",          // the client's original turn id
      "outcome": { /* redacted public outcome contract (outcome.schema.json) */ },
      "narration": "The room answers you with woodsmoke and low voices.",
      "narration_meta": {
        "assembler_version": "1.0.0",
        "content_hash": "…",
        "model": "claude-sonnet-5",
        "gate": "canonical_record"
      },
      "narration_event_id": 412,             // the ?since= watermark to pass back
      "world_time": 930
    }
  ]
}
```

Notes:

- Only NARRATED turns appear. A turn whose narration failed or was degraded
  (paid budget spent) has no canonical record and is simply absent from history —
  its committed outcome is still canon and still served by `POST /api/action`
  replay, just without prose.
- `narration_event_id` is monotonic (append id). Persist the max you've seen and
  pass it as `?since=` to fetch only newer turns on reconnect.
- Each turn's `command_id` is stable and client-deterministic — use it to
  de-duplicate against turns already in the local Chronicle.

## Duplicate / retry of a NARRATED turn (`POST /api/action`)

A retry of a committed, narrated `command_id` now returns the SAME record WITH
its prose (audit #1 — never `narration:null` for a turn that was narrated):

```jsonc
{
  "absorbed": true,
  "outcome": { /* the redacted public outcome — identical to the first response */ },
  "narration": "…the same prose…",
  "narration_meta": { "gate": "canonical_record", "assembler_version": "…",
                      "content_hash": "…", "model": "…" },
  "system_note": null
}
```

A retry of a degraded/failed-narration turn stays `narration: null` (there is no
prose on record). The outcome is rebuilt from the committed event with the same
wound words (a kill stays `dispatched`), and a blocked move keeps its
`system_note`. A degraded turn's `NARRATION_RESTING` note does not come back on a
retry: nothing records whether the narration was skipped or failed.

## Degrade signals (audit #4 — "never meter the conversation")

The deterministic engine turn is NEVER blocked. Only the paid LLM layers degrade
when the daily turn cap / spend breaker is spent. Two client-visible shapes:

1. **Structured (tapped) intent over budget** — the turn STILL resolves (200):

   ```jsonc
   {
     "outcome": { /* the deed is canon */ },
     "narration": null,
     "narration_meta": { "gate": "degraded" },
     "system_note": "<<The Quill sets down its pen for now: your deed is written…>>"
   }
   ```

   Render `system_note` diegetically (System voice); the outcome is real.

2. **Free text over budget** — `429` with `Retry-After` and a body of
   `{"detail": {"message": <System line>, "code": <code>}}` (the paid parser can't
   run). The engine stays open to STRUCTURED actions — surface the
   tapped-suggestion affordance. Codes: `TURN_DAILY_DONE`, `INK_SPENT`,
   `INK_TYPED_REQUIRES_TAP` (budget spent until tomorrow) or `TURN_TOO_FAST`,
   `TURN_IN_FLIGHT` (wait a breath).

The engine is never metered, but any turn (structured or typed) gets `429`
`TURN_IN_FLIGHT` while the same account's previous turn is still resolving.
Keep the command id after any `429`, `502` or `504` and re-send under it: a turn
that did commit comes back as that turn, never as a second one.

## `narration_meta.gate` values

`pass` · `regenerated` · `fallback` — the live narration paths (gate outcome).
`degraded` — narration skipped, paid budget spent (`system_note` set).
`canonical_record` — served from the stored canon record (duplicate/`/api/turns`).
