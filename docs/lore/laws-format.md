# Component Laws — Machine-Checkable Format (B0.2)

Scope: the YAML shape for sealed-tier component laws (roadmap §3.2) plus one worked example (resurrection, playbook §6). Sealed feats are component requirement lists, never quest chains: the engine checks components against state, and **any route that assembles them counts** — including routes we never authored.

## Schema

```yaml
law_id: string            # stable snake_case id, e.g. law.resurrection
name: string              # diegetic name
tier: sealed              # always "sealed" — no other tier uses laws
components:               # ALL must verify at attempt time
  - component_id: string  # stable id within the law
    description: string   # player-legible, no numbers, safe to surface in KNOWN
    satisfiable_by:       # OPEN list — canonical examples, never an enumeration
      - string
    verification: string  # the state fact the engine checks: a deterministic
                          # predicate over the event log / projections
costs:                    # engine-enforced deductions when the feat resolves;
  - string                # entries reference 03-magic-cost-ledger
on_attempt_incomplete:    # fail-forward consequences when attempted with any
  - string                # component unverified — fiction reacts, deed logged,
                          # something noticed you. Never a silent no-op.
```

### Field rules

1. **`verification` is engine-checkable or it doesn't ship.** A deterministic predicate over committed state — never narrator judgment, never a prompt. Sprint 0 writes these as precise English; they get formalized against Team A's event taxonomy (`docs/engine/events.md`) when A0.2 lands.
2. **`satisfiable_by` is open by construction.** It lists canonical routes, not all routes. Out-of-band creativity ("does World-Tree sap count as a soul anchor?") escalates to the adjudicator; the ruling is committed to the precedent ledger and, if accepted, **appended** to `satisfiable_by` as permanent canon. Precedents only ever add routes; they never remove or narrow `verification`.
3. **`costs` are deductions, not requirements.** Components must *verify* before the feat resolves; costs are what the engine *takes* when it does. A thing can be both (a staked life is a verified component and a consumed cost) — list it in both places.
4. **`on_attempt_incomplete` is fail-forward, always.** An attempt with unmet components is still a deed: logged, witnessed, rumor-seeded, and it draws attention. Consequences here are the authored floor, not a cap — the narrator may add texture, never subtract state.
5. **One special case is reserved:** the adjudicator treats "prove what the Quill is" as permanently unsatisfiable. Component laws may gate *revelations* about the Quill, never the final answer (`06-quill-cosmology.md`, hard rule).

## Worked example — resurrection

The playbook's five laws (identity · memory · vessel · passage · power) are modeled as **five components of one sealed law**. Diegetically they are spoken of as "the Five Laws of Return"; in data they are one law so the engine has a single attempt-point to verify against. `satisfiable_by` entries below are v0 canon seeds — Sprint 1 (starter laws) and Sprint 4 (hardening) expand them.

```yaml
law_id: law.resurrection
name: The Five Laws of Return
tier: sealed
components:
  - component_id: identity
    description: The dead must be anchored — something made before death that says, without doubt, who they were.
    satisfiable_by:
      - a soul anchor crafted before death
      - a true-name record sealed by a Skill Church appraisal ceremony
    verification: an anchor-class entity bound to the dead PC's entity id exists,
      with provenance timestamp earlier than the death-sealed event
  - component_id: memory
    description: Who they were must survive somewhere outside the grave — in ink or in a living mind.
    satisfiable_by:
      - the dead's own journal, intact and legible
      - a living person who witnessed the dead across years, present at the rite
    verification: at least one memory-bearing entity (journal linked to the dead,
      or witness NPC with sufficient shared-deed history) is present at the rite
      location at attempt time
  - component_id: vessel
    description: There must be a body to come back to.
    satisfiable_by:
      - the dead's own corpse, preserved against rot
      - a crafted vessel, made willing and empty
    verification: a vessel-class entity at the rite location whose condition state
      meets the preservation threshold
  - component_id: passage
    description: A way across — a place where the veil is thin, during its thin season, and the dead willing to walk it.
    satisfiable_by:
      - a named veil-thin site during its recurring thin window
    verification: rite location carries the veil-thin attribute AND the world clock
      falls inside that site's thin window AND the dead's willingness flag is true
      (set by the dead in life, or established through the anchor — never assumed)
  - component_id: power
    description: The crossing is paid for. A life offered in exchange is the known price.
    satisfiable_by:
      - a life willingly offered in exchange
    verification: a qualifying offered-life stake is committed at the rite before
      the attempt resolves
costs:
  - the offered life (the power stake is consumed — engine-enforced, irreversible)
  - the vessel's preservation (spent whether or not a better vessel is ever found)
  - the site's thin window closes for this attempt (next window is a real wait on the world clock)
  - forbidden-knowledge exposure accrued researching the Laws (per the exposure track — skips never bypass it)
  - attention: entities that watch the veil now know your name
on_attempt_incomplete:
  - the rite fails forward — the crossing does not open, and no stake is taken
  - the attempt is a deed: logged with location and witnesses, rumor-seeded
  - '[Rite Attempted: The Five Laws of Return — INCOMPLETE] is written to the Chronicle'
  - exposure accrues as if the research had succeeded
  - something on the far side of the veil noticed the knock; an attention clock starts
  - the veil-thin site is marked by the attempt — locals remember who came asking
```

**Canon notes (binding, from roadmap §3.7):** resurrection is known early, achieved endgame, and **never rewinds** — the heir's deeds stay real; the resurrected returns displaced by all elapsed history. A difficult reunion, not a loaded save. "Within a season" (roadmap §3.2's early sketch) is modeled as the *passage* thin-window, which recurs — so a long-dead PC can still return; they wait for the veil, not the calendar of their death.
