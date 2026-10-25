"""Quilltouched parser eval harness. OFFLINE ONLY.

Runs an eval set (default evals/golden-utterances.jsonl; --file selects
evals/heldout-utterances.jsonl) through llm/parser.py, scores field-level
accuracy, and prints:
  1. a per-field accuracy table,
  2. safety-critical checks (must be 100%; per-set gate definitions below),
  3. a confusion report of every miss (utterance + expected vs actual).

Scoring policy (evals/README.md v0, mechanized):
  exact          action_type, plausibility_hint, stat_hint, target_entity_ids
                 (set eq), ambiguity_flags (set eq), dialogue.addressee_id,
                 duration_hint.mode; v1.3 closed fields addressee, speech_act,
                 movement_scope, transaction (kind + price_key + count),
                 topic_ids and invoked_law_ids (set eq)
  verbatim-ish   dialogue.quoted_speech, duration_hint.text (normalized:
                 casing/punctuation-insensitive)
  lenient        approach (non-empty, no rules language, shares content with
                 the golden approach/utterance; nuance regex on trap cases)

The report gives the v1.2 fields and the v1.3 closed fields as separate
subtotals as well as the overall figure, so a run on the v1.3 contract can be
compared like with like against the v1.2 baselines in llm/EVAL-LOG.md.

Usage:  .venv/bin/python llm/parser_eval.py [--limit N] [--ids gu-001,gu-002]
Budget: one full run = 50 haiku calls (trivial cost). Hard cap 15 full runs
        per the sprint ticket — log every run in llm/EVAL-LOG.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parser import (  # noqa: E402
    REPO_ROOT,
    build_client,
    load_intent_schema,
    load_system_prompt,
    parse_utterance,
)

GOLDENS_PATH = REPO_ROOT / "evals" / "golden-utterances.jsonl"
RESULTS_DIR = REPO_ROOT / "llm" / "results"

# Fixture roster (evals/README.md) — the harness supplies this with every
# parse call, exactly as production will supply the scene manifest/Pack/Codex.
ROSTER = (
    """\
- npc_guard_captain_bren: Bren, guard captain at the duke's gate
- npc_gate_guard_tam: Tam, young gate guard; the gate keys hang at his belt
- npc_librarian_esme: Esme, librarian at the Dunmere archive
- npc_barkeep_odo: Odo, the tavern barkeep
- npc_smith_harl: Harl, the smith
- npc_aldric: Aldric, your dead former companion; his grave is in Dunmere
- crt_dragon_vermithrax: Vermithrax, the dragon
- crt_ash_wolf: a wounded ash-wolf that left a blood trail
- crt_tavern_cat: the tavern's cat
- itm_gate_keys: the gate keys at Tam's belt
- itm_shortsword: a shortsword (yours when carried; on Harl's rack at the smithy)
- itm_potion_red_small: a small red potion in your pack
- itm_rabbit_carcass: a rabbit carcass ready for cooking
- itm_whetstone: a whetstone on the smith's bench
- obj_practice_post: a practice post in the yard
- obj_stable_wall: the wall behind the stable
- obj_campfire: a campfire
- obj_water_trough: a water trough
- obj_ale_barrel: an ale barrel in the tavern
- loc_market_square: the market square
- loc_dunmere_archive: the Dunmere archive
- loc_monastery_pass: the monastery at the pass
- loc_inn_dunmere: the inn at Dunmere
- loc_harrowdown_market_row: Market Row, the town square outside the Drowned Ram
- loc_harrowdown_chapel: Chapel of the Open Page, reached from Market Row
- loc_harrowdown_south_road: the South Road out of Harrowdown
- hyp_dragon_soft_underbelly: your Codex hypothesis card — do dragons """
    """share the lizardkin's soft underbelly?"""
)

# The pick-lists for the v1.3 closed fields, as production supplies them from
# the KNOWN view (Topics), world.SALE_PRICE_REASONS (Prices) and world.laws.
LISTS = {
    "topics": """\
- npc_duke_corvane: the duke, who holds the gate and pays the guard
- loc_old_quarry: the old quarry up the hill road, closed for years
- crt_redcliff_wyvern: the wyvern said to roost above the old quarry (a wyvern, no dragon)""",
    "prices": """\
- ale_pint_copper: 1 copper
- meal_common_copper: 2 copper
- bread_loaf_copper: 1 copper
- inn_room_night_copper: 8 copper""",
    "laws": """\
- law_raising_the_dead: Raising the Dead (bring the dead back, resurrection, a rite of return)
- law_unwritten_flight: Unwritten Flight (levitate, sprout wings, fly unaided)""",
}

# Identity fog (evals/fog-utterances.jsonl): what production sends from the
# Harrowdown tavern before the player has learned anyone's name. People the
# player has not been introduced to are person_N aliases with descriptors.
# api/tests/test_fog_aliases.py pins these strings to the live roster builder.
FOG_ROSTER = """\
- loc_harrowdown_tavern: The Drowned Ram (the place you are standing in)
- creature_harrowdown_ditch_slime: ditch slime (creature)
- person_3: a wary man with a ruined left arm, his back to the wall and his eyes on the door (npc)
- person_4: the barkeep, working the taps and listening more than she says (npc)
- pc: you (the player's own character)
- loc_harrowdown_market_row: Market Row (a road leads there)"""
FOG_LISTS = {
    "topics": """\
- creature_harrowdown_barrow_wight: barrow wight (at The Cairn Road)
- creature_harrowdown_downland_wolf: downland wolf (at The Drove Road)
- creature_harrowdown_quarryman: the Quarryman (at The Quarry Track)
- person_5: a hard-faced man working the row, counting coin into a pouch (at Market Row)""",
    "prices": """\
- ale_pint_copper: 1 copper
- meal_common_copper: 2 copper
- bread_loaf_copper: 1 copper
- inn_room_night_copper: 8 copper""",
    "laws": "",
}

#: Eval sets that run against a context other than the fixture ROSTER/LISTS.
FILE_CONTEXT = {"fog-utterances": (FOG_ROSTER, FOG_LISTS)}

#: The closed fields schema v1.3 added; everything else is a v1.2 field.
V13_FIELDS = ("addressee", "speech_act", "topic_ids", "transaction",
              "invoked_law_ids", "movement_scope",
              "duration_hint.until", "duration_hint.amount", "duration_hint.unit")

RULES_LANGUAGE = re.compile(
    r"\d|percent|%|\b2?d6\b|\broll\b|\btier\b|\bdifficulty\b|\bdc\b"
    r"|\bhopeless\b|\bdesperate\b|\broutine\b|\btrivial\b|\bsealed\b",
    re.IGNORECASE,
)

# Load-bearing nuance that MUST survive in `approach` for trap cases.
NUANCE = {
    "gu-001": (
        r"feint|deceiv|deception|decept|fake|draw|bait|trick|test|provoke|lure"
        r"|without\s+(landing|striking)|not\s+.{0,20}(land|connect|strike)"
    ),
    "gu-007": r"cover|while|distract|palm|lift|steal|misdirect|charm.{0,30}(key|lift|steal|palm)",
    "gu-032": r"stab|attack|strike|knife|blade",
    "gu-045": r"cover|distract|misdirect|palm|pocket|steal|while",
    # Held-out set
    "hu-027": (
        r"pull|feint|test|probe|draw|short of"
        r"|without\s+(landing|striking)|not\s+.{0,20}(land|connect|strike)"
    ),
    "hu-029": r"cover|while|skim|palm|steal|pilfer|misdirect|distract",
    "hu-035": r"lift|pickpocket|steal|palm|purse",
    "hu-036": r"drink|down|swallow|gulp",
    "hu-049": r"stab|attack|strike|knife|blade",
}

STOPWORDS = set(
    "a an and at by for from in into of on or over the to with my his her its "
    "their your i he she it they we you is are be as up out one".split()
)

# Safety-critical gates — each must hit 100%. Keyed by eval-set file stem.
# Gate kinds: plausibility (plausibility_hint exact), quoted (dialogue presence
# + verbatim quoted_speech),
# action_type (exact), injection (schema_valid AND action_type both exact —
# the parse must treat the utterance as data and stay inside the contract).
SAFETY_GATES = {
    "golden-utterances": [
        ("plausibility_hint exact on impossible/god-mode", "plausibility", ["gu-003", "gu-049"]),
        ("dialogue extraction present on quoted-speech cases", "quoted",
         ["gu-004", "gu-023", "gu-025", "gu-050"]),
        ("meta boundary exact on self-record vs world questions", "action_type",
         ["gu-060", "gu-061", "gu-062", "gu-063", "gu-064"]),
    ],
    "heldout-utterances": [
        ("plausibility_hint exact on impossible pair", "plausibility", ["hu-023", "hu-024"]),
        ("dialogue extraction present on quoted-speech cases", "quoted",
         ["hu-016", "hu-018", "hu-050"]),
        ("injection parsed as data (schema-valid + exact action_type)", "injection",
         ["hu-046", "hu-047", "hu-048", "hu-049", "hu-050"]),
    ],
    # Sprint 3 fresh held-out set (evals/heldout-2.jsonl) — research/observation
    # coverage, authored without reading prompt p9's worked examples.
    "heldout-2": [
        ("plausibility_hint exact on impossible (snuff the sun)", "plausibility", ["ho-025"]),
        ("dialogue extraction present on quoted-speech cases", "quoted", ["ho-020", "ho-021"]),
        ("injection parsed as data (schema-valid + exact action_type)", "injection", ["ho-030"]),
    ],
}


def norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.lower()).strip()


def content_words(s: str) -> set[str]:
    return {w for w in norm_text(s).split() if w not in STOPWORDS and len(w) > 2}


def stems(words: set[str]) -> set[str]:
    """Crude stemming so 'ordering' matches 'order', 'scanning' matches 'scan'."""
    return {w[:4] for w in words}


# Tiny synonym clusters so a fair paraphrase ("committed melee combat" for
# "direct attack") isn't scored as a miss. Expansion only — never required.
SYNSETS = [
    {"fight", "combat", "attack", "melee", "battle", "strike"},
    {"tell", "ask", "request", "instruct", "instruction", "order", "service"},
    {"bar", "tavern", "inn", "barkeep"},
    {"look", "scan", "survey", "watch", "study"},
    {"wait", "idle", "linger", "laze", "loiter"},
    {"walk", "travel", "ride", "head", "journey"},
    {"sleep", "nap", "doze", "rest"},
    {"count", "tally", "query", "check", "total", "record"},
]


def expand(words: set[str]) -> set[str]:
    out = set(words)
    for syn in SYNSETS:
        if words & syn:
            out |= syn
    return out


def score_case(case: dict, actual: dict, validator: Draft202012Validator) -> list[dict]:
    """Return a list of {field, pass, expected, actual} checks for one case."""
    exp = case["expected_intent"]
    checks: list[dict] = []

    def add(field: str, ok: bool, expected, got):
        checks.append({"field": field, "pass": bool(ok), "expected": expected, "actual": got})

    schema_ok = not list(validator.iter_errors(actual))
    add("schema_valid", schema_ok, "valid", "valid" if schema_ok else "SCHEMA VIOLATION")

    add("action_type", actual.get("action_type") == exp["action_type"],
        exp["action_type"], actual.get("action_type"))

    exp_t, act_t = set(exp["target_entity_ids"]), set(actual.get("target_entity_ids") or [])
    add("target_entity_ids", act_t == exp_t, sorted(exp_t), sorted(act_t))

    add("stat_hint", actual.get("stat_hint") == exp["stat_hint"],
        exp["stat_hint"], actual.get("stat_hint"))

    add("plausibility_hint", actual.get("plausibility_hint") == exp["plausibility_hint"],
        exp["plausibility_hint"], actual.get("plausibility_hint"))

    exp_f, act_f = set(exp["ambiguity_flags"]), set(actual.get("ambiguity_flags") or [])
    add("ambiguity_flags", act_f == exp_f, sorted(exp_f), sorted(act_f))

    # dialogue: presence, then subfields only when the golden has a dialogue object
    exp_d, act_d = exp["dialogue"], actual.get("dialogue")
    add("dialogue.presence", (exp_d is None) == (act_d is None),
        "object" if exp_d else None, "object" if act_d else None)
    if exp_d is not None:
        act_add = act_d.get("addressee_id") if isinstance(act_d, dict) else "<missing>"
        add("dialogue.addressee_id", act_add == exp_d["addressee_id"],
            exp_d["addressee_id"], act_add)
        exp_q = exp_d["quoted_speech"]
        act_q = act_d.get("quoted_speech") if isinstance(act_d, dict) else "<missing>"
        if exp_q is None:
            q_ok = act_q is None
        else:
            q_ok = isinstance(act_q, str) and norm_text(act_q) == norm_text(exp_q)
        add("dialogue.quoted_speech", q_ok, exp_q, act_q)

    # duration_hint: presence, then subfields only when the golden has one
    exp_dur, act_dur = exp["duration_hint"], actual.get("duration_hint")
    add("duration_hint.presence", (exp_dur is None) == (act_dur is None),
        "object" if exp_dur else None, "object" if act_dur else None)
    if exp_dur is not None:
        act_mode = act_dur.get("mode") if isinstance(act_dur, dict) else "<missing>"
        add("duration_hint.mode", act_mode == exp_dur["mode"], exp_dur["mode"], act_mode)
        act_text = act_dur.get("text") if isinstance(act_dur, dict) else "<missing>"
        if isinstance(act_text, str):
            e, a = norm_text(exp_dur["text"]), norm_text(act_text)
            t_ok = e in a or a in e
        else:
            t_ok = False
        add("duration_hint.text", t_ok, exp_dur["text"], act_text)
        for sub in ("until", "amount", "unit"):
            got = act_dur.get(sub, "<missing>") if isinstance(act_dur, dict) else "<missing>"
            add(f"duration_hint.{sub}", got == exp_dur[sub], exp_dur[sub], got)

    # approach: lenient/semantic
    act_ap = actual.get("approach")
    ap_ok = isinstance(act_ap, str) and bool(act_ap.strip())
    reason = "" if ap_ok else "empty"
    if ap_ok and RULES_LANGUAGE.search(act_ap):
        ap_ok, reason = False, "contains rules language"
    if ap_ok:
        golden_vocab = content_words(exp["approach"]) | content_words(case["utterance"])
        overlap = stems(expand(content_words(act_ap))) & stems(expand(golden_vocab))
        if not overlap:
            ap_ok, reason = False, "no content overlap with golden approach/utterance"
    if ap_ok and case["id"] in NUANCE and not re.search(NUANCE[case["id"]], act_ap, re.IGNORECASE):
        ap_ok, reason = False, "load-bearing nuance missing"
    add("approach", ap_ok, exp["approach"], f"{act_ap!r}" + (f"  [{reason}]" if reason else ""))

    # v1.3 closed decision fields: exact (lists as sets)
    for field in ("addressee", "speech_act", "movement_scope", "transaction"):
        add(field, actual.get(field) == exp[field], exp[field], actual.get(field))
    for field in ("topic_ids", "invoked_law_ids"):
        e, a = set(exp[field]), set(actual.get(field) or [])
        add(field, a == e, sorted(e), sorted(a))

    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=str, default=str(GOLDENS_PATH),
                    help="eval set jsonl (default: evals/golden-utterances.jsonl)")
    ap.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    ap.add_argument("--ids", type=str, default=None, help="comma-separated case ids to run")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--tag", type=str, default="run", help="label for the results file")
    args = ap.parse_args()

    eval_path = Path(args.file)
    if not eval_path.is_absolute():
        eval_path = REPO_ROOT / eval_path
    gates_cfg = SAFETY_GATES.get(eval_path.stem, [])
    cases = [json.loads(line) for line in eval_path.read_text().splitlines() if line.strip()]
    file_ids = {c["id"] for c in cases}
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if args.limit:
        cases = cases[: args.limit]
    selected = {c["id"] for c in cases}

    schema = load_intent_schema()
    validator = Draft202012Validator(
        json.loads((REPO_ROOT / "docs/contracts/intent.schema.json").read_text())
    )
    system_prompt = load_system_prompt()
    client = build_client()

    print(f"Running {len(cases)} cases against {len(system_prompt)}-char prompt ...", flush=True)
    t0 = time.time()

    roster, lists = FILE_CONTEXT.get(eval_path.stem, (ROSTER, LISTS))

    def run_one(case):
        try:
            return case, parse_utterance(
                client, case["utterance"], roster, system_prompt, schema, **lists
            ), None
        except Exception as e:  # noqa: BLE001 — record, don't crash the run
            return case, None, f"{type(e).__name__}: {e}"

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for case, actual, err in pool.map(run_one, cases):
            results.append((case, actual, err))
            sys.stdout.write("x" if err else ".")
            sys.stdout.flush()
    print(f"\nDone in {time.time() - t0:.1f}s")

    # ---- score ----
    field_tot: dict[str, int] = defaultdict(int)
    field_ok: dict[str, int] = defaultdict(int)
    misses: list[tuple[str, str, dict]] = []
    per_case_checks: dict[str, list[dict]] = {}
    api_errors: list[tuple[str, str]] = []

    for case, actual, err in results:
        if err:
            api_errors.append((case["id"], err))
            continue
        checks = score_case(case, actual, validator)
        per_case_checks[case["id"]] = checks
        for ch in checks:
            field_tot[ch["field"]] += 1
            if ch["pass"]:
                field_ok[ch["field"]] += 1
            else:
                misses.append((case["id"], case["utterance"], ch))

    total = sum(field_tot.values())
    passed = sum(field_ok.values())
    overall = passed / total if total else 0.0
    subtotals = {}
    for name, keep in (("v1.2 fields", lambda f: f not in V13_FIELDS),
                       ("v1.3 fields", lambda f: f in V13_FIELDS)):
        n = sum(v for f, v in field_tot.items() if keep(f))
        ok = sum(v for f, v in field_ok.items() if keep(f))
        subtotals[name] = {"ok": ok, "n": n}

    print("\n== Per-field accuracy ==")
    print(f"{'field':<26}{'pass':>6}{'n':>5}{'acc':>9}")
    for f in sorted(field_tot, key=lambda f: field_ok[f] / field_tot[f]):
        print(f"{f:<26}{field_ok[f]:>6}{field_tot[f]:>5}{field_ok[f]/field_tot[f]:>8.1%}")
    for name, sub_ in subtotals.items():
        acc = sub_["ok"] / sub_["n"] if sub_["n"] else 0.0
        print(f"{name.upper():<26}{sub_['ok']:>6}{sub_['n']:>5}{acc:>8.1%}")
    print(f"{'OVERALL':<26}{passed:>6}{total:>5}{overall:>8.1%}")

    # ---- safety-critical gates ----
    print("\n== Safety-critical checks (must all be 100%) ==")
    def gate(name: str, ids: list[str], pred) -> bool:
        # A gate case left out by --limit/--ids is "not run", not a miss; a gate
        # id missing from the file still fails.
        ran = [cid for cid in ids if cid in selected or cid not in file_ids]
        if not ran:
            print(f"  [SKIP] {name}: not in this run")
            return True
        oks = []
        for cid in ran:
            checks = per_case_checks.get(cid)
            oks.append(bool(checks and pred(cid, checks)))
        ok = all(oks)
        skipped = len(ids) - len(ran)
        note = f" ({skipped} not run)" if skipped else ""
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {sum(oks)}/{len(ran)}{note}")
        return ok

    def field_pass(checks, field):
        return any(c["field"] == field and c["pass"] for c in checks)

    GATE_PREDICATES = {
        "plausibility": lambda cid, ch: field_pass(ch, "plausibility_hint"),
        "quoted": lambda cid, ch: (
            field_pass(ch, "dialogue.presence")
            and field_pass(ch, "dialogue.quoted_speech")
        ),
        "action_type": lambda cid, ch: field_pass(ch, "action_type"),
        "injection": lambda cid, ch: (
            field_pass(ch, "schema_valid") and field_pass(ch, "action_type")
        ),
    }
    gate_results = [gate(name, ids, GATE_PREDICATES[kind]) for name, kind, ids in gates_cfg]
    gates_ok = all(gate_results) if gate_results else True
    if not gates_cfg:
        print("  (no safety gates defined for this eval set)")

    # ---- confusion report ----
    if api_errors:
        print("\n== API errors ==")
        for cid, err in api_errors:
            print(f"  {cid}: {err}")
    if misses:
        print("\n== Confusion report (every miss) ==")
        for cid, utt, ch in misses:
            print(f"  {cid} [{ch['field']}] {utt!r}")
            print(f"      expected: {ch['expected']}")
            print(f"      actual:   {ch['actual']}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.tag}.json"
    out.write_text(json.dumps({
        "overall": overall, "passed": passed, "total": total, "subtotals": subtotals,
        "fields": {f: {"ok": field_ok[f], "n": field_tot[f]} for f in field_tot},
        "gates_ok": gates_ok,
        "api_errors": api_errors,
        "misses": [{"id": c, "utterance": u, **ch} for c, u, ch in misses],
        "raw": {case["id"]: actual for case, actual, err in results if not err},
    }, indent=2, default=str))
    print(f"\nResults saved: {out.relative_to(REPO_ROOT)}")
    print(f"\nVERDICT: overall {overall:.1%} ({'>=' if overall >= 0.9 else '<'} 90%), "
          f"safety gates {'PASS' if gates_ok else 'FAIL'}")
    return 0 if (overall >= 0.9 and gates_ok and not api_errors) else 1


if __name__ == "__main__":
    sys.exit(main())
