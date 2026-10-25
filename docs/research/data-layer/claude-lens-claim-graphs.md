# Claim Graphs with Provenance & Contradiction — Practical Report for Everquill

## Verdict on the committed architecture

The committed design (event-sourced canon + per-character claim store + deterministic context assembler) is sound and has strong precedent. The claim schema as specced is essentially **W3C PROV-lite plus Wikidata-style competing statements**, which are the two proven production patterns for exactly this problem. The closest game-sim precedent — Ryan et al.'s *Talk of the Town* knowledge framework ([AAAI 2015 paper](https://eis.ucsc.edu/papers/ryanEtAl_TowardCharactersWhoObserveTellMisrememberLie.pdf)) — independently converged on almost the same shape: beliefs with evidence lists, source/location/time metadata, predecessor pointers, and strength-weighted revision. Three refinements are needed: (1) the lifecycle needs a **contested** state between "contradicted" and "superseded", (2) **corroboration must require independent provenance roots** or rumors echo-chamber themselves into "corroborated", (3) "confidence = evidence consistency" alone can't break ties — use evidence-strength summation with per-method base weights.

---

## 1. Precedents worth stealing from

### Wikidata ranks — the production pattern for competing claims
Wikidata keeps **all competing statements** and annotates them with one of three ranks: preferred, normal, deprecated ([Help:Ranking](https://www.wikidata.org/wiki/Help:Ranking)). Key transferable lessons:

- **Deprecation, never deletion.** A debunked claim stays in the store, marked deprecated, with a machine-readable [reason for deprecated rank](https://www.wikidata.org/wiki/Property:P2241). Stated benefit: "allows other users to know not to re-add the value." Game translation: an NPC whose rumor was debunked keeps the deprecated claim row so lazy propagation doesn't re-ingest the same origin deed and resurrect the rumor.
- **"Truthy" queries read best-rank only.** Default queries return preferred-if-exists-else-normal, deprecated excluded ([SPARQL ranks reference](https://en.wikibooks.org/wiki/SPARQL/WIKIDATA_Qualifiers,_References_and_Ranks)). This is exactly what the Context Assembler should do: a best-rank filter per (believer, subject, predicate), never a scan of all historical claims.
- Multiple simultaneous preferred values are legal (genuine disagreement / multi-valued facts). Don't force a single winner where the fiction doesn't demand one.

### Talk of the Town — the game-sim precedent
Ryan, Summerville, Mateas & Wardrip-Fruin's framework ([paper PDF](https://eis.ucsc.edu/papers/ryanEtAl_TowardCharactersWhoObserveTellMisrememberLie.pdf), [overview](https://www.researchgate.net/publication/335746180_Simulating_Character_Knowledge_Phenomena_in_Talk_of_the_Town)) is the most-cited character-knowledge system with fallibility. Directly reusable mechanics:

- **Belief facet = value + predecessor pointer + evidence list + strength + accuracy flag.** The predecessor pointer "allows the system to track supplanted or forgotten character knowledge" — same as your superseded_by chain.
- **Evidence typology across four categories**: origination (reflection, observation, transference, confabulation, **lie**), propagation (statement, eavesdropping), deterioration (mutation), termination (forgetting). Every piece of evidence carries **source, location, time, strength**.
- **Belief revision rule**: adopt on first evidence; contradicting evidence is compared by strength; **weaker contradicting evidence is retained as a "candidate belief"** that accumulates until it outweighs the current one, at which point they swap and the loser becomes the candidate. This is the model your `contested` state should implement.
- **Lies are tracked as lies system-side while the recipient treats them as ordinary statements** — the exact true-sheet/known-sheet firewall you've committed to. The system "will still track that it was in fact a lie, to allow for the presentation of true knowledge trajectories after gameplay."
- Their errors (mutation/confabulation) are driven by hand-authored probability schemas per facet type. Yours must be seeded-deterministic instead — key the "corruption roll" to `(origin_event_id, hop_count, region_epoch)` so a rumor mutates identically on every recomputation. That upgrade is what makes lazy propagation cacheable and auditable.

### W3C PROV — take the triad, skip the spec
Full PROV is academic overkill ([PROV family overview](https://dl.acm.org/doi/10.1145/2452376.2452478), [practical healthcare extension](https://www.researchgate.net/publication/327270814_Practical_Extension_of_Provenance_to_Healthcare_Data_Based_on_the_W3C_PROV_Standard)). What survives contact with Postgres is the triad: **Entity** (the claim), **Activity** (the acquisition event: observed/was-told/read/inferred/inherited), **Agent** (observer + source). Your schema already has all three roles. Add only two PROV relations as FKs:
- `wasDerivedFrom` → `derived_from_claim_id` (rumor hops, journal inheritance)
- `wasInvalidatedBy` → `superseded_by_claim_id` + the event that did it

That plus `source_event_id` gives full provenance walks with plain recursive CTEs. No RDF, no PROV-O.

### Bitemporal — take the concept, skip the machinery
Bitemporal = valid time (when true in the world) vs transaction time (when recorded) ([overview](https://www.red-gate.com/simple-talk/databases/postgresql/saving-data-historically-with-temporal-tables-part-1-queries/), [survey](https://link.springer.com/article/10.1007/s42488-026-00162-x)). **Your event log already IS the transaction-time axis** — append-only log position is a perfect transaction timestamp. So bitemporal-lite for Everquill means only adding world-time columns to claims:

- `world_time_acquired` (game clock when the character learned it)
- `world_valid` (int8range of game ticks the *fact itself* covers — "the baron was at the mill on night 412") — nullable; most claims are about durable facts and don't need it

Do not adopt pg_bitemporal-style `EXCLUDE USING gist` machinery ([pattern description](https://www.pgedge.com/blog/looking-forward-to-postgres-19-its-about-time), [temporal PK explainer](https://lord.technology/2025/01/28/understanding-temporal-primary-keys.html)) except possibly on *projections* that must enforce non-overlap (e.g., "current holder of the title"). Claims are beliefs; overlapping and conflicting is their whole point.

The bitemporal payoff shows up in **journals**: a journal entry must snapshot the claim *as it stood at writing time* (log-position ≤ journal event), not the ancestor's final belief. An ancestor who later learned the truth but never updated the journal passes the wrong version to the heir. That is correct, dramatic, and free if you resolve journal contents against the event log.

---

## 2. Recommended claim lifecycle

Five states. Lifecycle transitions are themselves **events in the deed log** (claim_asserted, claim_corroborated, claim_contested, claim_superseded, claim_retracted), so the claim table stays a rebuildable projection — consistent with binding decision #1.

```
asserted ──(2nd INDEPENDENT source)──> corroborated
   │  │                                    │
   │  └──(conflicting claim, weaker)──> contested ──(challenger outweighs)──> superseded
   │                                       │  (of the loser; winner keeps/regains its state)
   └──(origin deed sealed as false /       │
       source formally recanted)──> retracted
```

- **asserted** — written from one acquisition event. Default state. Visible to Context Assembler.
- **corroborated** — ≥2 pieces of evidence with **distinct provenance roots** (see below). Higher salience weight in assembly; harder to supersede.
- **contested** — a live conflicting claim exists on the same (believer, subject, predicate) key but hasn't outweighed this one. **Both rows stay active**; store the challenger link. This is Talk of the Town's candidate-belief mechanic and it's the state that generates gameplay ("I've heard two versions of this"). The Context Assembler should surface contested pairs deliberately — it's narrator gold.
- **superseded** — outweighed. Row is never deleted (Wikidata deprecation rationale: prevents re-adoption from stale sources, preserves the audit trail). Set `superseded_by_claim_id`, `superseded_reason` (better_evidence | direct_observation | source_recanted | canon_sealed), and emit the event.
- **retracted** — terminal; the origin evidence itself was invalidated (e.g., canon sealed the deed as fabricated). Distinct from superseded because no replacement claim needs to exist.

**Strength model (refines "confidence = evidence consistency"):** each evidence link carries a base weight by acquisition method — direct observation > firsthand testimony > secondhand rumor > inherited journal > overheard — decayed by world-time age, summed per claim (Talk of the Town's exact mechanism, and it handles their Jack/Jill worked example: many stale observations lose to two fresh trustworthy reports). Consistency-only confidence cannot rank one strong observation against three weak rumors; strength summation can, and it stays fully deterministic.

**Corroboration independence rule (the fix most KBs miss):** store `provenance_root_event_id` (the origin deed) on every claim, propagated through every rumor hop. Corroboration requires evidence with **distinct roots**. Otherwise one lie told at a tavern reaches a character via three neighbors and self-upgrades to "corroborated" — the echo-chamber failure truth-discovery literature warns about ([truth discovery for conflicting linked data](https://arxiv.org/pdf/1509.00104)). Retelling can still legitimately raise the *believer's own commitment* (Talk of the Town models this, citing real psychology) — but that's strength, not corroboration status.

### Schema sketch

```sql
CREATE TABLE claim (
  claim_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  believer_id         bigint NOT NULL,          -- character who holds it
  subject_id          bigint NOT NULL,          -- entity the claim is about
  predicate           text   NOT NULL,          -- CONTROLLED vocabulary (enum-ish)
  value_text          text,
  value_num           numeric,
  value_range         numrange,
  world_valid         int8range,                -- game-tick validity of the FACT (nullable)
  world_time_acquired bigint NOT NULL,          -- game clock
  source_event_id     bigint NOT NULL REFERENCES event(event_id),   -- transaction time = log position
  provenance_root_event_id bigint NOT NULL,     -- origin deed; propagated across hops
  acquisition_method  text NOT NULL,            -- observed|told|overheard|read|inferred|inherited_journal
  source_agent_id     bigint,                   -- who told them (null for observation)
  derived_from_claim_id bigint REFERENCES claim(claim_id),  -- rumor hop / journal parent
  hop_count           smallint NOT NULL DEFAULT 0,
  strength            real NOT NULL,            -- cached sum of evidence weights (rebuildable)
  status              text NOT NULL DEFAULT 'asserted',  -- asserted|corroborated|contested|superseded|retracted
  contested_by_claim_id bigint,
  superseded_by_claim_id bigint,
  superseded_reason   text,
  journal_flag        boolean NOT NULL DEFAULT false      -- inheritance eligibility (set by journal event)
);

CREATE TABLE claim_evidence (                    -- corroboration links
  claim_id  bigint REFERENCES claim(claim_id),
  event_id  bigint REFERENCES event(event_id),
  root_event_id bigint NOT NULL,
  weight    real NOT NULL,
  PRIMARY KEY (claim_id, event_id)
);
```

Structured `predicate` + typed value columns is a deliberate constraint: it keeps contradiction **decidable in SQL** (same key, incompatible values, overlapping `world_valid`). Free-text claims would force LLM/NLI contradiction checking, which current practice shows is expensive, probabilistic, and unsuited to a deterministic engine ([RAG contradiction-detection survey](https://arxiv.org/html/2504.00180v1), [KB conflict-detection practice](https://www.usefini.com/guides/ai-knowledge-base-conflicting-answers)). Push fuzziness into the predicate vocabulary at design time, not runtime.

---

## 3. When contradiction detection should run

Split it by scope; both answers are needed and they're different:

**Within one mind: write-time, synchronous.** On claim insert, index-probe active claims on `(believer_id, subject_id, predicate)` with overlapping `world_valid`, compare strengths, apply the deterministic revision rule (adopt / contest / supersede), emit the lifecycle event. Rationale: at your volumes (low hundreds of events per heavy player-day; even 10k players is single-digit-millions/day) this is one indexed lookup per insert — negligible. Write-time detection keeps the claim graph *always current* for the Context Assembler, so reads stay cheap and deterministic. The literature frames this as write-time repair vs read-time consistent-query-answering ([inconsistency management overview](https://www.nature.com/research-intelligence/nri-topic-summaries/inconsistency-management-in-knowledge-bases-micro-179526)); read-time resolution exists to serve arbitrary ad-hoc queries over data you don't control — you control both sides, so pay the cost once at write.

**Across minds: read-time, scoped to the scene.** "The blacksmith and the innkeeper who are both present believe different things about the baron" is not a data error to repair — it's narrative material. Detect it in the Context Assembler as a per-turn query joining active claims of the entities in the scene manifest on (subject, predicate). Scene entity sets are small (≤ ~10), so this is a handful of index lookups per turn. Never run global cross-character sweeps; there is no consumer for that output.

**During lazy rumor propagation: write-time of the cache epoch.** When a region-epoch is computed, propagated claims run through the same per-mind write-time rule for each affected NPC. Because corruption rolls are seeded from `(root_event_id, hop_count, epoch)`, recomputing an epoch reproduces identical contradictions — cache-safe and auditable.

One scheduled job earns its keep: a **canon-sealing sweep** — when an event is sealed (a death, an exam result), a worker marks claims whose `provenance_root_event_id` is now contradicted-by-canon as contested/retracted for characters who *learn* of the sealing (via propagation, not omnisciently). Run it in the existing world-clock due-jobs worker; it's a propagation job, not a new mechanism.

---

## 4. Heir inheritance — journal-only filtering

Mechanics that keep the firewall clean:

1. **Journaling is an event.** `journal_written(character, [claim_ids], world_time)` in the deed log. It snapshots *claim identity + state at that log position*, and sets `journal_flag=true` on those rows. Only claims active at writing time can be journaled — a character can't journal a belief they no longer hold.
2. **On death, nothing copies automatically.** Death seals the character (binding decision #1). The estate holds journal events only.
3. **On inheritance, mint new claim rows for the heir**, one per journaled claim, resolved **as of the journal event's log position** (bitemporal payoff: the ancestor's later corrections don't leak unless journaled later):
   - `acquisition_method = 'inherited_journal'`, `source_agent_id = ancestor`, `derived_from_claim_id = ancestor's claim`, `provenance_root_event_id` carried through, `hop_count + 1`
   - `status = 'asserted'` — **lifecycle state does not inherit.** The ancestor's "corroborated" was earned by the ancestor's evidence; the heir holds a document, which is testimony. Base evidence weight = journal tier (below firsthand testimony). If the world has moved on, the heir discovers contradictions through play — which is the gameplay you want from the legacy system.
   - The heir's KNOWN sheet is built only from these new rows; the ancestor's non-journaled claims are reachable solely via provenance walks for audit/debug, and must be unserializable to the narrator path exactly like true sheets.
4. **Contested pairs:** if the ancestor journaled both versions ("some say X, but I saw Y"), inherit both rows and let the heir's write-time rule immediately mark them contested. If only one was journaled, only that one crosses — journals are curated, biased artifacts, and that's a feature.

This matches how PROV would model it (heir's claim `wasDerivedFrom` the journal entity, which `wasAttributedTo` the ancestor) with two FK columns instead of an ontology.

---

## 5. Indexing plan

Volumes are small (alpha: tens of players × hundreds of events/day; even 10k-player headroom is comfortably Postgres-single-node). Indexes here buy **turn-assembly latency**, not scale. Keep the set narrow — the claim table is append-heavy and every index taxes inserts.

```sql
-- Hot path: write-time contradiction probe + Context Assembler best-rank reads.
-- Partial = the "truthy" filter; superseded/retracted rows fall out of the index entirely.
CREATE INDEX claim_active_key ON claim (believer_id, subject_id, predicate)
  WHERE status IN ('asserted','corroborated','contested');

-- Top-K salient claims per believer (recency form; add a salience column later if scoring outgrows recency+strength)
CREATE INDEX claim_active_recent ON claim (believer_id, world_time_acquired DESC)
  WHERE status IN ('asserted','corroborated','contested');

-- Provenance walks (audit, sealing sweep, echo-chamber checks)
CREATE INDEX claim_by_root   ON claim (provenance_root_event_id);
CREATE INDEX claim_by_parent ON claim (derived_from_claim_id) WHERE derived_from_claim_id IS NOT NULL;

-- Inheritance path: only journaled claims, per character
CREATE INDEX claim_journaled ON claim (believer_id, world_time_acquired)
  WHERE journal_flag;

-- Time-ranged facts (whereabouts-class predicates) only — skip if few predicates use world_valid
CREATE INDEX claim_world_valid ON claim USING gist (subject_id, world_valid)
  WHERE world_valid IS NOT NULL;

-- Lazy propagation support on the event/deed log
CREATE INDEX event_by_region_time ON event (region_id, world_time);
-- Rumor cache: UNIQUE (region_id, epoch) on the cache table
```

Notes:
- **Statuses churn on indexed columns**, so the partial indexes see delete+insert on supersede. At your write rates this is irrelevant; if it ever isn't, move status into a separate thin `claim_status` table and keep `claim` truly append-only.
- **Prefer typed columns over jsonb** for values; add a GIN jsonb index only if genuinely ad-hoc predicates appear. B-tree beats GIN for every query the Context Assembler actually runs, and structured queries (not vector similarity) is already a binding decision — this is its schema-level enforcement.
- No `EXCLUDE` constraints on claims (conflicting overlap is the point); consider them only on canonical-projection tables like title-holders ([bitemporal exclusion pattern](https://www.pgedge.com/blog/looking-forward-to-postgres-19-its-about-time)).
- The lifecycle-as-events design means every index above is on a **projection** and can be rebuilt/reshaped from the log with zero data risk.

---

## 6. Challenges to the committed spec (evidence-backed)

1. **"Confidence = evidence consistency" is underspecified — adopt strength summation.** Talk of the Town's implemented, playtested model (strength = decayed sum of evidence weights, candidate-belief retention) resolves the cases consistency can't: fresh-strong vs stale-many, and lie-vs-observation ties. Keep confidence as a *derived* display value if you like, but make strength the decision variable.
2. **The lifecycle as stated ("contradicted" → "superseded") is missing the stable middle state.** Both Wikidata (multiple preferred/normal coexisting) and Talk of the Town (candidate beliefs) keep conflicting claims live indefinitely. If contradiction always races to supersession you lose "I've heard two stories" — the single richest narrative output of the whole claim system. Add `contested` as a first-class, potentially long-lived state.
3. **Corroboration needs the independent-roots rule** (`provenance_root_event_id`), or lazy propagation will manufacture corroborated falsehoods from a single lie. This is the one structural gap in the spec as written.
4. **Don't let contradiction detection drift toward semantic/LLM checking.** The KB-industry pattern of NLI/LLM contradiction scanning ([Fini](https://www.usefini.com/guides/ai-knowledge-base-conflicting-answers), [RAG validators](https://arxiv.org/html/2504.00180v1)) is nondeterministic and expensive — the opposite of the engine's contract. Enforce a closed predicate vocabulary at the intent-parsing boundary; the LLM parser maps free text into predicates, and contradiction stays a SQL equality-and-overlap problem.
5. **Bitemporal: resist the full pattern.** The event log is your transaction-time axis; adding SQL:2011/pg_bitemporal machinery would duplicate it. World-time columns on claims + journal snapshots resolved at log position give you every bitemporal query the game needs ("what did she believe when she wrote this?") for two columns' cost.

---

## Sources

- Ryan, Summerville, Mateas, Wardrip-Fruin — [Toward Characters Who Observe, Tell, Misremember, and Lie (AAAI EIS, PDF)](https://eis.ucsc.edu/papers/ryanEtAl_TowardCharactersWhoObserveTellMisrememberLie.pdf); [Simulating Character Knowledge Phenomena in Talk of the Town](https://www.researchgate.net/publication/335746180_Simulating_Character_Knowledge_Phenomena_in_Talk_of_the_Town); [Emily Short's commentary on Curating Simulated Storyworlds](https://emshort.blog/2019/05/28/curating-simulated-storyworlds-james-ryan-ch-6f/)
- Wikidata — [Help:Ranking](https://www.wikidata.org/wiki/Help:Ranking); [reason for deprecated rank (P2241)](https://www.wikidata.org/wiki/Property:P2241); [SPARQL: Qualifiers, References and Ranks](https://en.wikibooks.org/wiki/SPARQL/WIKIDATA_Qualifiers,_References_and_Ranks); [weaker logical status claims in Wikidata records](https://journals.sagepub.com/doi/10.3233/SW-243686)
- W3C PROV — [The W3C PROV family of specifications (EDBT tutorial)](https://dl.acm.org/doi/10.1145/2452376.2452478); [Practical extension of PROV to healthcare data](https://www.researchgate.net/publication/327270814_Practical_Extension_of_Provenance_to_Healthcare_Data_Based_on_the_W3C_PROV_Standard)
- Bitemporal — [PostgreSQL temporal tables (Simple Talk)](https://www.red-gate.com/simple-talk/databases/postgresql/saving-data-historically-with-temporal-tables-part-1-queries/); [Bitemporal databases systematic review (Springer)](https://link.springer.com/article/10.1007/s42488-026-00162-x); [Postgres temporal/bitemporal direction (pgEdge)](https://www.pgedge.com/blog/looking-forward-to-postgres-19-its-about-time); [Understanding temporal primary keys (Lord)](https://lord.technology/2025/01/28/understanding-temporal-primary-keys.html)
- Contradiction & truth discovery — [Inconsistency management in knowledge bases (Nature RI)](https://www.nature.com/research-intelligence/nri-topic-summaries/inconsistency-management-in-knowledge-bases-micro-179526); [Truth discovery for object conflicts in linked data (arXiv)](https://arxiv.org/pdf/1509.00104); [Contradiction detection in RAG systems (arXiv)](https://arxiv.org/html/2504.00180v1); [How AI knowledge bases detect conflicting answers (Fini)](https://www.usefini.com/guides/ai-knowledge-base-conflicting-answers); [Time-constraint KG conflict resolution (MDPI)](https://www.mdpi.com/2076-3417/9/20/4399)
- Belief revision in games — [Belief Revision Games (AAAI)](https://ojs.aaai.org/index.php/AAAI/article/view/9415); [NPC reputation via belief formation (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S1875952123000204)