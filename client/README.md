# Quilltouched client

Vite, React and TypeScript, played in a browser (desktop first, works on a phone). Every piece of
game state comes from the authed API; nothing is mocked.

## Commands

```bash
npm install        # once
npm run dev        # dev server on http://localhost:5173
npm run build      # tsc -b && vite build -> dist/
npm run lint       # oxlint
```

The API must be running too: see "Running it locally" in the root README (a throwaway Postgres,
invite codes in `EVERQUILL_INVITE_CODES`). The API's CORS allows `http://localhost:5173` by default;
another origin goes in `EVERQUILL_CORS_ORIGINS`. Typed actions and narration need a real
`ANTHROPIC_API_KEY` server-side; tapped suggestions work without one.

## Screens

- **Invite gate.** An invite code claims a world: `POST /api/claim` (guided mode), and the 256-bit
  device token is kept in localStorage (`eq_device_token`). A 401 anywhere clears it and returns
  here.
- **Creation.** The engine rolls a pool of seven values; the player places six on the aptitudes
  (one is a spare), names the character, and steps into Harrowdown. A 409 on submit means the
  character already exists (a retried submit), so the client enters play.
- **Play** (`src/App.tsx`, layout v3). Desktop: the scene and the actions on the left, the
  Chronicle down the right. Phone: scene, Chronicle and actions stacked over a bottom tab bar.
  - *Scene* (`src/scene-art.ts`): the background for the location type, and each entity standing
    on its authored slot. A figure's feet sit on the slot's foot line (measured per sprite from its
    alpha), sized by kind and depth, with a contact shadow. The player's own character is not
    drawn. An entity with no art, or art that fails to load, is shown as a name label. Tap a
    figure for its known card, and to narrow the suggestions to it.
  - *Chronicle*: the last few turns, the full Chronicle one tap away. System lines (assessment,
    dice, outcome) in monospace; narrator prose in serif; state changes folded behind
    "[n marks on the Chronicle]". Each turn can show **How this was decided**: the form the
    engine decided from (the parser's reading of typed words, or a tapped action's form), with
    the free-text approach and the hints marked as deciding nothing.
  - *Actions*: suggested actions and places as chips (rolled actions first; names as the player
    knows them, so "Ask the barkeep about the quarry" until you learn her name), then free text
    through the parser. A phone shows four chips until "More suggestions".
- **Character** (`src/SelfScreen.tsx`): your aptitudes on an open scale, and your standing as you
  read it.
- **Codex** (`src/CodexScreen.tsx`, `src/codex.ts`): your Inquiry claims as cards with provenance
  and a confidence word (never a number), contradiction badges from the data, filters, a
  hypothesis pinboard that seeds the composer, and the places you have stood.
- **Proceed?** A `pending_confirmation` response opens one System dialog; Proceed confirms under
  the same command id and the roll resolves inside it.

Durability: committed turns are cached per world in localStorage and reconciled against
`GET /api/turns` on load (paged forward from a watermark). The command in flight is kept too, so
a re-send after a lost response returns the committed turn instead of a second one.

## API base

The app fetches relative `/api/...` paths by default. For a separate API origin, bake it in at build
time: `VITE_API_BASE=https://<your-api-host> npm run build` (the bare origin, no `/api`).

## Verification

`scripts/smoke.ts` drives the real local API with the client's own modules: guided claim, creation
and its 409 retry, the scene and its art, a tapped action, a Proceed? probe, duplicate absorption,
`/api/turns`, the sealed shared world and a bad token. Add `EVERQUILL_SMOKE_PAID=1` when the API has
a real key to check typed text and narration too.

```bash
EVERQUILL_INVITE_CODE=<fresh code> node client/scripts/smoke.ts http://127.0.0.1:8000
```

Read the explicit `SMOKE PASSED` / `SMOKE FAILED` line, not the exit status alone.

## PWA

- `public/manifest.webmanifest`: standalone, SVG icon first.
- `public/sw.js`: app-shell service worker. It precaches only what every build has (the shell,
  manifest and SVG icon) and caches the PNG icons when present; `/api/*` is never intercepted;
  scene art is cached after first fetch. Bump `CACHE_NAME` on every deploy.
- `public/sprites/`, `public/backgrounds/`, `public/icons/`: art, not included in the public copy.
