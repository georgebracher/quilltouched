"""Everquill context assembler v1. OFFLINE, DETERMINISTIC.

Produces narration_context.schema.json (v1.1) envelopes from a plain-dict
KnownStateView. Same view -> byte-identical envelope, always: integer
basis-point scoring, a total tiebreak order, fixed serialization, and a
sha256 content hash stamped into the envelope (synthesis 2.4; lorebook
teardown mechanics 1-10).

NO ENGINE IMPORTS. The assembler cannot see RefereeState by construction:
its input type (the view dict below) has no field where a true stat,
hidden motive, or difficulty could travel, and the output validates against
narration_context.schema.json (additionalProperties: false everywhere).

ADAPTER CONTRACT (for engine/API wiring)
------------------------------------------------
`assemble(view)` consumes ONLY this plain-dict shape. The engine's KnownState
surface (everquill_engine/views.py, not landed at time of writing) should be
adapted to it by a thin function in the API layer; the assembler itself never
imports engine modules (mirrors the static import lint in tests/test_known_boundary.py).

view = {
  "scene": {                       # the PERCEIVED scene (fog-of-warred)
    "location_id": str,            # snake_case (dotted world ids: use canonical_entity_id)
    "label_known": str | None,
    "world_time": str,             # Chronicle-exact calendar string
    "entities": [ {entity_id, label_known, category, position, state_tags}, ... ],
  },
  "known_sheets": [ {"entity_id": str,
                     "facts": [{"field": str, "value": str|num|bool}, ...]}, ... ],
  "claims": [                      # Inquiry-layer candidates, already pre-filtered by cheap SQL
    {"claim": <narration_context claim object>,   # the thin claim shape, verbatim
     "meta": {                                     # OPTIONAL salience metadata, all fields optional
        "world_hours_ago": int,          # age of acquisition in world-hours (recency R)
        "half_life_class": "gossip"|"sighting"|"biography"|"world_structure",
        "notoriety_band": int 0..10,     # write-time deed notoriety (N)
        "one_hop": bool,                 # linked to a scene entity via one typed edge (V=60)
        "scope_class": "scene"|"region"|None,   # V=80 / V=40
        "quest_target": bool,            # V=70
        "constraint_class": bool,        # oaths/prohibitions/promises/consequences — PINNED
     }}, ... ],
  "active_clocks": [ {"clock_id", "label", "due_world_time", "progress_text",
                      "due_world_hours": int|None,      # urgency for K + ordering (not serialized)
                      "refs": [entity_id, ...]},
                      # entities/locations the clock touches (not serialized)
                     ... ],
  "canon_excerpts": [ {"source_ref", "mode", "text"}, ... ],
  # deaths/oaths/verdicts binding this scene
  "atmosphere": [str, ...],
  # per-location sensory facts from world content, may be []
  "recent_subjects": { entity_id: turns_ago(1..3), ... },      # thread stickiness O
  "last_resolution": {event_id, action_summary, tier_resolved, outcome_tier, dice_total} | None,
}

Budget (synthesis 2.4 table, scaled to the current thin claim shape; section 6
— recent exchanges — is NOT part of this envelope: the narrator harness owns
the transcript slot and the API wires it):

  #  section              floor  cap    notes
  1  canon_excerpts        150   350    canon first, then atmosphere ("atmosphere:<loc>")
  2  scene_manifest        200   400    NEVER evicted (cap advisory)
  3  known_sheet_slices    300   650    entity_id ASC, facts field ASC
  4  salient_claims        400   750    flex: unused reserve from other sections flows here
  5  active_clocks         100   200    urgency ASC, clock_id ASC
  7  assembly (trace)      100   150    ALWAYS included, never evicted
  total cap 3100, target 2800.

Token estimation is the deterministic char-length estimator (len/4, ceil) over
each section's canonical JSON — pinned as tokenizer_version below so an
infrastructure change can never masquerade as a state change (teardown failure
mode 5).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

ASSEMBLER_VERSION = "1.0.0"
TOKENIZER_VERSION = "charlen4-v1"

# ---- budget table (tokens) -------------------------------------------------
SECTION_FLOORS = {"canon_excerpts": 150, "scene_manifest": 200,
                  "known_sheet_slices": 300, "salient_claims": 400,
                  "active_clocks": 100, "assembly": 100}
SECTION_CAPS = {"canon_excerpts": 350, "scene_manifest": 400,
                "known_sheet_slices": 650, "salient_claims": 750,
                "active_clocks": 200, "assembly": 150}
TOTAL_CAP = 3100
TARGET = 2800

# ---- scoring constants (integer basis points, 0..100 per term) -------------
# salience = 100*V + 60*N + 40*R + 40*K + 30*O - 50*D   (synthesis 2.4)
W_V, W_N, W_R, W_K, W_O, W_D = 100, 60, 40, 40, 30, 50

V_SUBJECT_PRESENT = 100
V_SCOPE_SCENE = 80
V_QUEST_TARGET = 70
V_ONE_HOP = 60
V_SCOPE_REGION = 40

HALF_LIFE_HOURS = {"gossip": 72, "sighting": 168, "biography": 2160,
                   "world_structure": None}  # None = infinite -> R = 100
DEFAULT_HALF_LIFE = 168

O_BY_TURNS_AGO = {1: 100, 2: 60, 3: 30}

CLOCK_HORIZON_HOURS = 48
PER_SUBJECT_CAP = 3  # pinned constraint-class claims are exempt (they bypass ranking)

# --- ambient source-lore suppression (turn-53 narration fabrication fix) -----
# A knowledge SOURCE's authored scope/lead content must NOT leak into scene
# narration just because the source is present. Two claim shapes are source
# artifacts, not ambient scene knowledge, and are delivered ONLY on the turn the
# player researches/queries them — where they arrive as a written claim delta on
# the committed OUTCOME (which the narrator already receives) and are rendered by
# the client as a Codex/research chip:
#   * scope == "lead": a directional pointer at a BETTER source/far place
#     (resolver.research._research_lead). It is never scene narration — a present source
#     must not volunteer "the deep dragon-lore lives in Severwick" into a scene
#     the player never asked it about.
#   * method == "source_records" about an OFF-SCENE subject: a research finding
#     whose subject is not perceptible here. A finding about a PRESENT creature
#     the player can see stays eligible (it is legitimately relevant); a finding
#     about an absent subject must not be promoted into ambient prose by a
#     one_hop / scope_class link back to the co-located source.
# The suppression is a deterministic pre-ranking filter (no floats, stable), so
# byte-stability and every tiebreak below are unchanged.
_LEAD_SCOPE = "lead"
_SOURCE_RECORDS_METHOD = "source_records"


def _ambient_suppressed(claim: dict, scene_entity_ids: set) -> str | None:
    """Reason string if this claim is source-scope lore that must not surface
    ambiently (only on its own research turn, via the outcome); else None."""
    if claim.get("scope") == _LEAD_SCOPE:
        return "source_lead_not_ambient"
    if (claim.get("method") == _SOURCE_RECORDS_METHOD
            and claim.get("subject_entity_id") not in scene_entity_ids):
        return "offscene_source_lore_not_ambient"
    return None

# category rank for the tiebreak chain: lower = firmer provenance, packs first
# on salience ties. Method string is matched by prefix.
CATEGORY_RANK = (("witnessed", 0), ("appraisal", 0), ("archive_research", 1),
                 ("inherited_journal", 2), ("rumor", 3))
DEFAULT_CATEGORY_RANK = 4

_DOTTED = re.compile(r"[^a-z0-9_]+")


def canonical_entity_id(raw: str) -> str:
    """Normalize world-content ids (loc.harrowdown.tavern) to the contracts'
    snake_case pattern (loc_harrowdown_tavern). Adapter helper — world YAML
    uses dotted ids; every schema in docs/contracts requires ^[a-z][a-z0-9_]*$.
    """
    return _DOTTED.sub("_", raw.strip().lower()).strip("_")


def atmosphere_from_world(world: dict, location_id: str) -> list[str]:
    """Pull the `atmosphere:` list for a location from parsed world-content
    YAML when present (content authors are adding the field this sprint). Accepts
    dotted or canonical location ids; returns [] when absent.
    """
    want = canonical_entity_id(location_id)
    for loc in (world or {}).get("locations", []) or []:
        if canonical_entity_id(str(loc.get("id", ""))) == want:
            atmo = loc.get("atmosphere") or []
            return [str(line) for line in atmo]
    return []


def stamp_content_hash(envelope: dict) -> dict:
    """``envelope`` with ``assembly.content_hash`` set to the sha256 of its
    canonical JSON (hash field blank while hashing). The API re-stamps after
    swapping ids for aliases, so the recorded hash names the context the
    narrator was actually sent (audit 2026-10-24, codex-005)."""
    out = {**envelope, "assembly": {**envelope["assembly"], "content_hash": ""}}
    digest = hashlib.sha256(canonical_json(out).encode("ascii")).hexdigest()
    out["assembly"]["content_hash"] = digest
    return out


def canonical_json(obj) -> str:
    """The single canonical serialization: sorted keys, compact separators,
    ascii-safe. Both the content hash and token estimates run over this."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def estimate_tokens(obj) -> int:
    s = canonical_json(obj)
    return (len(s) + 3) // 4  # ceil(len/4), integer only


def _int_recency(hours_ago, half_life_class) -> int:
    """Integer approximation of 100 * 2^(-age/half_life). Whole half-lives via
    right shift; linear interpolation inside the current half-life. No floats.
    """
    hl = HALF_LIFE_HOURS.get(half_life_class, DEFAULT_HALF_LIFE)
    if hl is None:
        return 100
    if hours_ago is None:
        return 0  # unknown age scores as stale (deterministic, conservative)
    age = max(0, int(hours_ago))
    n = age // hl
    if n >= 7:
        return 0
    hi = 100 >> n
    lo = 100 >> (n + 1)
    return hi - ((hi - lo) * (age % hl)) // hl


def _category_rank(method: str) -> int:
    m = (method or "").lower()
    for prefix, rank in CATEGORY_RANK:
        if m.startswith(prefix):
            return rank
    return DEFAULT_CATEGORY_RANK


@dataclass(frozen=True)
class AssembledContext:
    envelope: dict          # validates against narration_context.schema.json v1.1
    canonical: str          # canonical_json(envelope) — hash-stable bytes (ascii)
    content_hash: str       # == envelope["assembly"]["content_hash"]
    receipt: dict           # context receipt (teardown mechanic 10): NOT sent to the model


def _score_claim(entry: dict, scene_entity_ids: set, clock_refs_due: dict,
                 recent_subjects: dict) -> tuple[tuple, int]:
    """Return (sort_key, V). sort_key = (-salience, category_rank,
    world_hours_ago, claim_id): all integers + one string — a total order with
    no floats anywhere. V == 0 means NO structural relevance: the claim is
    ineligible outright (eligibility is boolean; salience only ranks —
    teardown 'relevance is not eligibility'). K clock-coupling counts as
    structural relevance in its own right.
    """
    claim = entry["claim"]
    meta = entry.get("meta") or {}
    subject = claim["subject_entity_id"]

    v_candidates = [0]
    if subject in scene_entity_ids:
        v_candidates.append(V_SUBJECT_PRESENT)
    if meta.get("scope_class") == "scene":
        v_candidates.append(V_SCOPE_SCENE)
    if meta.get("quest_target"):
        v_candidates.append(V_QUEST_TARGET)
    if meta.get("one_hop"):
        v_candidates.append(V_ONE_HOP)
    if meta.get("scope_class") == "region":
        v_candidates.append(V_SCOPE_REGION)
    v = max(v_candidates)

    n = max(0, min(10, int(meta.get("notoriety_band") or 0))) * 10
    r = _int_recency(meta.get("world_hours_ago"), meta.get("half_life_class"))
    k = clock_refs_due.get(subject, 0)
    o = O_BY_TURNS_AGO.get(recent_subjects.get(subject, 0), 0)
    # D (redundancy) is applied greedily during packing (exact-duplicate skip),
    # not in the static score — see _pack_claims.
    salience = W_V * v + W_N * n + W_R * r + W_K * k + W_O * o

    hours = meta.get("world_hours_ago")
    hours_key = int(hours) if hours is not None else 10**9  # unknown age sorts oldest
    return (-salience, _category_rank(claim["method"]), hours_key, claim["claim_id"]), max(v, k)


def _pack_claims(entries: list, budget: int, scene_entity_ids: set,
                 clock_refs_due: dict, recent_subjects: dict, receipt: list):
    """Deterministic greedy packing: pinned constraint-class claims first
    (bypass ranking, exempt from the per-subject cap, always survive), then
    ranked claims first-fit by rendered length under the flex budget with a
    per-subject cap and exact-duplicate redundancy skip (the D term).

    CONTESTED-PAIR CO-SURFACING: a claim's contradiction
    partners (`contradiction_ids`, the SQL-equality other-side of a contested
    (believer, subject, predicate) — claims.md) are co-surfaced whenever the
    claim itself is packed. Both halves of a contradiction therefore reach the
    narrator together, so it can voice the disagreement ("the ballads say X,
    the archivist doubts it") instead of only the side that happened to rank.
    Partners bypass the per-subject cap AND the structural-relevance gate (they
    are relevant *because* they contest a surfaced claim), respect only budget +
    the exact-duplicate skip, and are surfaced in a deterministic order (host
    packing order, then contradiction_id ASC) so the envelope stays byte-stable.
    """
    pinned, ranked = [], []
    for e in entries:
        (pinned if (e.get("meta") or {}).get("constraint_class") else ranked).append(e)

    id_map = {e["claim"]["claim_id"]: e for e in entries}

    keyed = []
    for e in ranked:
        suppressed = _ambient_suppressed(e["claim"], scene_entity_ids)
        if suppressed:
            receipt.append({"claim_id": e["claim"]["claim_id"], "accepted": False,
                            "reason": suppressed, "tokens": None, "salience": None})
            continue
        key, structural = _score_claim(e, scene_entity_ids, clock_refs_due, recent_subjects)
        if structural == 0:
            receipt.append({"claim_id": e["claim"]["claim_id"], "accepted": False,
                            "reason": "no_structural_relevance", "tokens": None, "salience": None})
            continue
        keyed.append((key, e))
    keyed.sort(key=lambda t: t[0])
    pinned.sort(key=lambda e: e["claim"]["claim_id"])  # stable order among pinned

    packed, used = [], 0
    seen_texts, per_subject, packed_ids = set(), {}, set()

    def _admit(c: dict, cost: int, reason: str, *, count_subject: bool, salience=None):
        nonlocal used
        packed.append(c)
        used += cost
        seen_texts.add((c["subject_entity_id"], c["claim_text"]))
        packed_ids.add(c["claim_id"])
        if count_subject:
            per_subject[c["subject_entity_id"]] = per_subject.get(c["subject_entity_id"], 0) + 1
        receipt.append({"claim_id": c["claim_id"], "accepted": True,
                        "reason": reason, "tokens": cost, "salience": salience})

    def _cosurface(seed: dict):
        """Pull in contradiction partners of `seed` (and transitively theirs),
        exempt from cap/relevance, bounded only by budget + dedup."""
        queue = [seed]
        while queue:
            cur = queue.pop(0)
            for pid in sorted(cur.get("contradiction_ids") or []):
                if pid in packed_ids or pid not in id_map:
                    continue
                partner = id_map[pid]["claim"]
                if _ambient_suppressed(partner, scene_entity_ids):
                    continue  # source lore never rides in ambiently, not even as a partner
                if (partner["subject_entity_id"], partner["claim_text"]) in seen_texts:
                    packed_ids.add(pid)  # duplicate text already surfaced
                    continue
                cost = estimate_tokens(partner)
                if used + cost > budget:
                    receipt.append({"claim_id": pid, "accepted": False,
                                    "reason": "contested_partner_budget", "tokens": cost,
                                    "salience": None})
                    continue
                _admit(partner, cost, "contested_partner", count_subject=False)
                queue.append(partner)

    for e in pinned:
        c = e["claim"]
        if c["claim_id"] in packed_ids:
            continue
        _admit(c, estimate_tokens(c), "pinned_constraint_class", count_subject=False)
        _cosurface(c)

    for key, e in keyed:
        c = e["claim"]
        if c["claim_id"] in packed_ids:  # already co-surfaced as a partner
            continue
        subject = c["subject_entity_id"]
        cost = estimate_tokens(c)
        if (subject, c["claim_text"]) in seen_texts:  # redundancy D
            receipt.append({"claim_id": c["claim_id"], "accepted": False,
                            "reason": "redundant_duplicate", "tokens": cost, "salience": -key[0]})
            continue
        if per_subject.get(subject, 0) >= PER_SUBJECT_CAP:
            receipt.append({"claim_id": c["claim_id"], "accepted": False,
                            "reason": "per_subject_cap", "tokens": cost, "salience": -key[0]})
            continue
        if used + cost > budget:
            receipt.append({"claim_id": c["claim_id"], "accepted": False,
                            "reason": "budget", "tokens": cost, "salience": -key[0]})
            continue  # first-fit: a smaller later claim may still fit
        _admit(c, cost, "ranked", count_subject=True, salience=-key[0])
        _cosurface(c)
    return packed, used


def assemble(view: dict) -> AssembledContext:
    """KnownStateView dict -> schema-valid, byte-stable NarrationContext."""
    receipt_claims: list = []
    scene_in = view["scene"]

    # -- 2. scene manifest: never evicted; entities in immutable id order -----
    scene = {
        "location_id": scene_in["location_id"],
        "label_known": scene_in.get("label_known"),
        "world_time": scene_in["world_time"],
        "entities": sorted(
            ({"entity_id": e["entity_id"], "label_known": e["label_known"],
              "category": e["category"], "position": e.get("position"),
              "state_tags": sorted(e.get("state_tags") or [])}
             for e in scene_in.get("entities", [])),
            key=lambda e: e["entity_id"]),
    }
    scene_entity_ids = {e["entity_id"] for e in scene["entities"]}
    scene_entity_ids.add(scene["location_id"])

    # -- 3. known sheets: entity_id ASC, facts field ASC, cap-trimmed ---------
    sheets, sheets_used = [], 0
    for slice_in in sorted(view.get("known_sheets", []), key=lambda s: s["entity_id"]):
        entry = {"entity_id": slice_in["entity_id"],
                 "facts": sorted(slice_in.get("facts", []),
                                 key=lambda f: (f["field"], canonical_json(f["value"])))}
        cost = estimate_tokens(entry)
        if sheets_used + cost > SECTION_CAPS["known_sheet_slices"]:
            continue  # atomic admission — never a truncated record (teardown 7)
        sheets.append(entry)
        sheets_used += cost

    # -- 5. active clocks: urgency ASC then clock_id ASC, cap-trimmed ---------
    clock_refs_due: dict = {}
    clocks_sorted = sorted(
        view.get("active_clocks", []),
        key=lambda c: (c.get("due_world_hours") if c.get("due_world_hours") is not None else 10**9,
                       c["clock_id"]))
    clocks, clocks_used = [], 0
    for c in clocks_sorted:
        due = c.get("due_world_hours")
        if due is not None and 0 <= int(due) <= CLOCK_HORIZON_HOURS:
            k = 100 - (100 * int(due)) // CLOCK_HORIZON_HOURS
            for ref in c.get("refs", []) or []:
                clock_refs_due[ref] = max(clock_refs_due.get(ref, 0), k)
        entry = {"clock_id": c["clock_id"], "label": c["label"],
                 "due_world_time": c.get("due_world_time"),
                 "progress_text": c.get("progress_text")}
        cost = estimate_tokens(entry)
        if clocks_used + cost > SECTION_CAPS["active_clocks"]:
            continue
        clocks.append(entry)
        clocks_used += cost

    # -- 1. canon excerpts: authored canon first, then atmosphere facts -------
    canon, canon_used = [], 0
    canon_in = sorted(view.get("canon_excerpts", []), key=lambda x: x["source_ref"])
    atmo_in = [{"source_ref": f"atmosphere:{scene['location_id']}", "mode": "quote",
                "text": line} for line in view.get("atmosphere", []) or []]
    for entry in canon_in + atmo_in:  # canon outranks atmosphere in the spill
        cost = estimate_tokens(entry)
        if canon_used + cost > SECTION_CAPS["canon_excerpts"]:
            continue
        canon.append(entry)
        canon_used += cost

    # -- 7. last-resolution trace: ALWAYS included --------------------------
    trace = view.get("last_resolution")
    if trace is not None:
        trace = {"event_id": trace["event_id"], "action_summary": trace["action_summary"],
                 "tier_resolved": trace["tier_resolved"], "outcome_tier": trace["outcome_tier"],
                 "dice_total": trace["dice_total"]}

    # -- 4. salient claims: flex section; unused reserve flows here ----------
    scene_used = estimate_tokens(scene)
    trace_used = estimate_tokens(trace) if trace else 0
    unused_reserve = sum(max(0, SECTION_FLOORS[s] - u) for s, u in
                         (("canon_excerpts", canon_used), ("scene_manifest", scene_used),
                          ("known_sheet_slices", sheets_used), ("active_clocks", clocks_used),
                          ("assembly", trace_used)))
    others_used = canon_used + scene_used + sheets_used + clocks_used + trace_used
    claims_budget = min(SECTION_CAPS["salient_claims"] + unused_reserve,
                        max(0, TOTAL_CAP - others_used))
    claims, claims_used = _pack_claims(
        view.get("claims", []), claims_budget, scene_entity_ids,
        clock_refs_due, view.get("recent_subjects", {}) or {}, receipt_claims)

    envelope = {
        "scene_manifest": scene,
        "known_sheet_slices": sheets,
        "salient_claims": claims,
        "active_clocks": clocks,
        "canon_excerpts": canon,
        "token_budget": {"max_tokens": TOTAL_CAP, "policy": "mixed"},
        "assembly": {"assembler_version": ASSEMBLER_VERSION,
                     "content_hash": "",
                     "last_resolution": trace},
    }
    envelope = stamp_content_hash(envelope)
    digest = envelope["assembly"]["content_hash"]
    canonical = canonical_json(envelope)

    receipt = {
        "assembler_version": ASSEMBLER_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "content_hash": digest,
        "section_tokens": {"canon_excerpts": canon_used, "scene_manifest": scene_used,
                           "known_sheet_slices": sheets_used, "salient_claims": claims_used,
                           "active_clocks": clocks_used, "assembly": trace_used},
        "claims_budget": claims_budget,
        "total_tokens": others_used + claims_used,
        "claims": receipt_claims,
    }
    return AssembledContext(envelope=envelope, canonical=canonical,
                            content_hash=digest, receipt=receipt)
