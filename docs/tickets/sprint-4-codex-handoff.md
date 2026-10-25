# Sprint 4 — remaining work + the split

Branch `sprint-4-self-social`. Engine + API backbone done & verified.

**Division of labour (George, 2026-07-15):** **Claude = design/UI/UX + the
player-facing screens + specs/review/narrative. Codex = the actual coding**
(engine, API, delicate logic, parser + evals). This doc's first cut had it
backwards; corrected below. Stay inside your ticket; read before changing.

## Done
- **Waves 1–4 engine + GET /api/self** (Claude, this run): reputation projection,
  social resolution v2 (reputation eases the guard, scaled outcome deltas),
  guided-dice chargen primitives (`roll_pool`/`build_character`), `self_view`,
  `/api/self`. 413 engine + 102 API tests green; `make release-check` green.
- **Self view SCREEN** (Claude, design): `client/src/SelfScreen.tsx` — build +
  believed standing (word + diverging meter, no raw number), summoned/chosen
  origin. Wired to `/api/self`. Builds clean. **Preview artifact shipped.**

## Sprint 4 finish line vs parked (scope discipline, George 2026-07-15)
Sprint 4 DoD = talking can succeed + chosen charisma matters + earned reputation
changes the odds + self-inspection tells you who you are. Three are done
(reputation engine, social eases with reputation, Self view). **To FINISH the
sprint, only two things remain:**
- **X2** parser persuasion -> social (Codex) = "talking can succeed".
- **X3 + C2** chargen API + creation screen (Codex + Claude) = "chosen charisma".

**PARKED, post-Sprint-4, do NOT start until the two above ship** (these are good
ideas that would otherwise cause roadmap drift): **X1** two-layer reputation
(believed vs true; single-layer already satisfies the DoD, Self view already
frames standing as "believed" in copy), **C3** read-someone, the anti-cheese
progression system (`docs/design/progression-anti-cheese.md`), and the dropdown
refinement of **C1** (fold into C1 when discovery-gating happens, not before).

## Verification protocol (MANDATORY)
Test against a LOCAL scratch Postgres set to **UTC**, NEVER Railway (it wipes
George's live world). `pgrep -fl pytest` empty first; each lane its own scratch
DB. Gate: `make release-check` (point `DATABASE_URL` at local Postgres — it
makes its own per-suite scratch DBs, `PGTZ=UTC`). Client: `npm run build` + `npm run lint`.

---

# CODEX lane — the coding

## X1 — TWO-LAYER reputation: believed vs true  [POST-SPRINT-4, PARKED]
Do NOT start until X2 + X3 + C2 ship. Sprint 4's DoD is met by single-layer
reputation. This is reputation v2, a real upgrade for later, not current work.
Reputation is currently single-value; split it into two layers,
mirroring the game's true-sheet vs known-sheet / Chronicle vs Inquiry law:
- **true** — the NPC/town's ACTUAL feeling. Hidden from the player. **This is
  what the social difficulty reads** (`_difficulty_for` social), so false
  confidence bites: press a friend you don't actually have and it's harder than
  you expect.
- **believed** — the player's READ. What `/api/self` + the Self screen show
  (never the true value).
- Both are (actor, scope, subject) rows — extend the `reputation` projection
  with a `layer` dimension (or `true_value` + `believed_value` columns);
  migration + projector bump + fold, replay-safe (mirror migration 0014).
- **Movement:** a social outcome moves BOTH, but they can DIVERGE — `true` by
  the real result, `believed` by how the exchange SEEMED. Clean reads keep them
  together; a miss you misread (or an NPC's deception) splits them.
- **Discovery:** a "read someone" action (observation-family) pulls `believed`
  toward `true` on a hit; a bad read drifts it FURTHER wrong (reuse the existing
  causal wrong-intel rule — a failed glance reads one band too kindly).
- `self_view` already returns one value per row — keep it returning BELIEVED
  after the split (the Self screen stays correct with no client change).
- Design owner: Claude (spec above). Tests: divergence, difficulty-reads-true,
  read-someone convergence, replay equality.

## X2 — parser: persuasion/asks route to `social`, not `dialogue`
Playtest "couldn't break through by talking": free-text persuasion parses as
`dialogue` (no-roll) instead of `social` (a contest). The parser prompt is a
99.x%-eval-tuned artifact (`llm/EVAL-LOG.md`) — **do NOT edit blind**; iterate
via `llm/parser_eval.py`. Rule: talking to MOVE someone (persuade/convince/
press/ask-for) is `social`; pure info/roleplay is `dialogue`. Add worked
examples + golden utterances; keep all gates PASS, accuracy ≥ baseline; log the
run. The engine already rewards it (X-something: social reads + moves reputation).

## X3 — guided-dice chargen API flow
Engine primitives ready (`chargen.roll_pool` / `build_character`). Currently
claim auto-genesises via `roll_character`. Add: `GET /api/chargen/pool` (the 7
pool values) + `POST /api/chargen` (`{name, assignment}` → validate via
`build_character` → genesis with the guided event). **Keep an auto path so the
working claim/play flow George playtests never breaks.** Design of the SCREEN is
Claude's (C-side below); this is the API + wiring. Tests: pool → assign → self
reflects it; identity assignment == auto; bad assignment → 422.

---

# CLAUDE lane — design / UI

## C1 — composer actions: pill-row → single DROPDOWN (George, 2026-07-15)
The suggested-action pills currently slide side-to-side (horizontal scroll —
George wants ZERO horizontal movement). Replace the pill row with **one dropdown/
select of contextual actions** above the composer. Fold in discovery-gating: the
list only names an entity (NPC/place/creature) once the player has DISCOVERED it
(scene roster or a Codex claim); generic verbs always present. This is where the
staged chip de-spoiler finally DEPLOYS (`client/deploy.sh` — bakes VITE_API_BASE,
aborts if base-less; stale SW → private tab / bump `eq-shell-vN`). Keep the free-
text composer + voice as the primary path; the dropdown is the assist.

## C2 — guided-dice creation screen + the arrival beat
Design + build the creation screen (George's guided-dice mock): the rolled pool
shown, drag/assign each value to an aptitude, one reroll (the spare), confirm.
Then the **summoned/chosen arrival beat** (the Quill pulled you here; Open Page
says chosen, Blotted say a blot in the margin) feeding `origin`. Pairs with
Codex's X3 API. No horizontal scroll.

## C3 — "read someone" affordance (once X1 lands)
When two-layer reputation ships, surface the read on the Self screen / target
card: your belief may be wrong, and a "read them" action can correct it. Design
the tell (e.g. a faint "your read — last taken [when]" stamp; a way to invoke a
read). Small, but it's what makes the believed/true split legible to the player.

## Also pending (roadmap / audit)
Identity-as-claims (self-assertion writes a claim about the PC); timer worker;
account recovery (the incognito lockout). In `docs/tickets/sprint-4.md` + memory.
