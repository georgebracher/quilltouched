# `knowledge_scope` — the source-scope field shape (Team B authors, Team A owns the loader)

Sprint 3 wave 1, Team A. A source entity (library / archive / sage / veteran /
board) carries a `knowledge_scope` in `content/world/*.yaml`. The loader
(`everquill_engine/world.py`) parses and validates it with `file:line` errors,
exactly like `true_sheet`; the resolver consumes it when a `research` action is
resolved at that source's location. **This is additive and OPTIONAL** — an
entity with no `knowledge_scope` is not a source, and research with no source
present falls back to the ambient (low-strength rumor) default. Team B fills in
the real scopes; the engine tolerates their absence.

## Shape

```yaml
entities:
  - id: npc.harrowdown.sister_odile
    name: Sister Odile
    kind: npc
    location: loc.harrowdown.chapel
    true_sheet: { ... }              # unchanged — engine-only
    common_knowledge: [ ... ]        # unchanged
    knowledge_scope:
      max_appraisal_tier: 2          # int >= 0 (default 0). The SOURCE's depth
                                     # cap: no success here reads deeper than this.
      subjects:                      # what this source can speak to accurately
        - subject: creature.harrowdown.quarryman   # a dotted entity id
          reveals:                   # authored FIELDS by appraisal tier (optional)
            - tier: 0                # surface descriptor
              predicate: common_knowledge
              value_text: a great winged shape over the scar
              claim_text: The parish rolls sketch a winged shape closing the quarry.
            - tier: 1                # category / band
              predicate: threat_assessed
              value_text: HOPELESS   # a BAND WORD, never a number
              claim_text: By the tallies it has killed every soul sent against it.
            - tier: 2                # the deep truth
              predicate: weak_point
              value_text: the old wound under its left wing
              claim_text: One margin-hand insists it favours a scar beneath its left wing.
          error:                     # the CONFIDENTLY-WRONG answer on a BAD roll
            predicate: threat_assessed
            value_text: RISKY        # the wrong value it insists on
            claim_text: The ballads swear it half-grown — the records believe them.
            distortion: ballad_inflation   # names the reusable error mechanism
      lead:                          # the pointer given for OUT-OF-SCOPE subjects
        to: loc.severwick.monastery  # a better source/location id (any string)
        claim_text: Nothing here on that — the burned province keeps the deep dragon-lore.
```

## Field rules (the loader enforces these)

- `max_appraisal_tier`: int `>= 0`. Optional (default `0`). Caps the depth any
  research success can reach at this source — a shallow source cannot surface a
  deep field even on a STRONG_HIT.
- `subjects`: optional list. Each entry:
  - `subject`: **required** non-empty string — the dotted id the source speaks
    to (an entity id, usually). Subjects are unique per scope.
  - `reveals`: optional list of `{tier, predicate, value_text, claim_text}`.
    - `tier`: int `>= 0`. The appraisal depth at which this field surfaces.
    - `predicate`: **must be a closed claim predicate** (`common_knowledge`,
      `threat_assessed`, `weak_point`, `personal_lesson`, … — the
      `everquill_engine.claims.PREDICATES` registry). A typo is a load error.
    - `value_text`: the revealed FIELD — a band WORD, a ranged estimate as
      prose, a named weak point. **Never an exact number** (there is no
      numeric slot here by design — roadmap §3.3).
    - `claim_text`: the narrator-facing prose of the finding.
    - A `weak_point` reveal is the deep truth that unlocks a knowledge-gated
      action (see below). Author it at your deepest tier.
  - `error`: optional `{predicate, value_text, claim_text, distortion}` — the
    ballads-lie mechanic. On a BAD research roll the source writes THIS claim,
    confidently, at HIGH strength (the source told you — weight 60). `distortion`
    names the reusable deterministic mechanism (`local_mistaken_for_universal`,
    `ballad_inflation`, `outdated`, `disguised_subject`, `transcription_error`,
    `corrupt_official`, `counterintelligence`, `insufficient_appraisal_tier`,
    `inherited_note_missing_qualifier`) and is stamped as the claim's `scope`.
- `lead`: optional `{to, claim_text}`. When a researcher asks this source about
  a subject it does NOT hold (not in `subjects`), it points them onward — one
  claim about `to`, scoped `lead` (the zero-authoring quest generator, §3.6).
  `to` may be any id, including an unauthored far place (distance is the drama).

## How the resolver uses it (so you can author to the mechanic)

- **Success** reveals the deepest authored reveal whose tier both the roll
  (STRONG_HIT → 2, HIT_WITH_COMPLICATION → 1) AND `max_appraisal_tier` reached.
  With no `reveals` authored the engine defaults: tier ≥ 1 → the true threat
  BAND word; tier 0 → a surface descriptor from `common_knowledge`.
- **Bad roll** (MISS) writes the `error` claim verbatim; with no `error`
  authored it defaults to a threat read one band too kind (reproducible).
- **Out-of-scope** subject → the `lead` pointer (or, with no `lead`, ambient).
- A held `weak_point` claim about a target turns a HOPELESS physical
  confrontation into a DESPERATE option and grants a named roll modifier — so a
  tier-2 `weak_point` reveal is the intel that makes an apex threat fightable.

## Confirm/deny loop (why exclusive predicates matter)

A confidently-wrong `threat_assessed` finding (told, 60) is SUPERSEDED by a
later direct observation (observed, 100) — the player re-checks and the Codex
corrects itself. Two sources with different wrong `threat_assessed` values
surface as a `contested` pair (narrator gold). Author your errors on exclusive
predicates (`threat_assessed`) when you want that loop; use `common_knowledge`
(accumulative) for facts that should coexist.
