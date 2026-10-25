# Sprint 0 — Foundations & Decisions

Rules for every ticket: bounded scope, read `docs/roadmap.md` + relevant playbook sections before changing anything, summarize your plan before implementing, no scope creep. Build order is law: config → data → core → interface → integration. Verify each layer runs before calling it done.

DoD for the sprint: fresh clone → `make dev` works; every pipe real (API hello live on Railway, PWA shell calls it, Postgres migrated, R2 bucket exists); engine package skeleton with passing property tests; style bible v0 signed off by George.

## Team A — Engine & Rules
- **A0.1** `everquill_engine` Python package skeleton: pure Python 3.12, zero LLM/network imports. Modules: `dice` (seeded 2d6), `ladder` (Trivial→Impossible tiers + Guarded→Suicidal risk labels), `events` (append-only event types per roadmap §4 State Architecture). Property tests for dice determinism (same seed → same rolls) and band mapping monotonicity (bigger gap never lowers difficulty).
- **A0.2** Draft the event taxonomy doc (`docs/engine/events.md`): action, outcome, claim-written, deed, timer-started/completed, death-sealed. Reviewed by F before schema work.

## Team B — World & Canon
- **B0.1** Lore bible v0 skeleton (`docs/lore/`): file structure only + the spine sentence + System diction sheet + explicit-absences list (playbook §4 AVOID). No prose content yet.
- **B0.2** Magic cost-ledger format + one worked example law (resurrection's five laws from playbook §6) in machine-checkable YAML shape agreed with A.
- **B0.3** Quill cosmology one-pager: both churches' doctrine (working names Open Page / the Blotted), what each says about the Quill-touched, denominational death rites. DECIDED 2026-07-13: the mystery is BOTTOMLESS (no end state; escalation without ceiling; adjudicator never closes "what is the Quill") — write the one-pager on that basis.

## Team C — LLM Layer
- **C0.1** Intent/outcome JSON contracts drafted WITH Team A (schemas for parsed intent, outcome tier, state deltas). No prompts yet.
- **C0.2** Eval-set format + first 20 golden utterances (typed action → expected intent), including god-mode, dialogue-vs-action, and misparse-trap cases ("feint toward the dragon").

## Team D — Client
- **D0.1** Vite + React + TS PWA shell: boots, installable manifest, calls the hello API, renders the response. No screens, no mock data.

## Team E — Art & Sprites
- **E0.1** Style bible v0: flat-color LN style ~5 heads, named 20–30-color palette, locked prompt preamble template, pose-lock rules per entity class, acceptance checklist (playbook §4 A17). 10 style-test sprites via gpt-image-1 for George sign-off. Sub-$5 batch.

## Team F — Platform & Infra
- **F0.1** Repo hygiene: Makefile (`make dev`, `make test`), CI (pytest + tsc), pre-commit basics.
- **F0.2** Railway project: FastAPI hello service + volume-backed Postgres plugin (NEVER a bare container). Store the project token in the secret store and reference it from the project registry. `railway up --service` deploy documented.
- **F0.3** Cloudflare: create R2 bucket `everquill-media` (with the R2 admin token from the secret store); create Pages project `everquill` (deferred DNS — everquill.gitm.gg wired when there's something to serve).
- **F0.4** Postgres: event-log + projections schema v0 from A's taxonomy; migration runner; **restore drill** (dump → R2 → restore to scratch DB, documented).

## George
- **G0.1** Style bible sign-off (E0.1) — pending E's test sprites.
- ~~**G0.2** Quill lore call~~ DECIDED 2026-07-13: bottomless.
- ~~**G0.3** Data-layer research squad~~ GO given 2026-07-13; squads launched.
- ~~**G0.4**~~ DONE 2026-07-13: George created Railway project everquill + token; stored in the secret store, verified via GraphQL. F0.2 remote deploy UNBLOCKED — deploy api/ once committed.
- ~~**G0.5**~~ DONE 2026-07-13: created the `everquill` Cloudflare Pages project via the API, attached its subdomain and DNS. F0.3 fully complete (R2 + Pages + domain + DNS).
