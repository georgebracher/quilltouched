"""Everquill narration eval harness v1. OFFLINE ONLY.

Runs the 20 fixtures in evals/narration-fixtures.json through llm/narrator.py
(claude-sonnet-5, <=400 out) and lints the batch per
docs/research/ai-tells-fiction.md (c). Also reports token usage (mean / p95
in+out) and a per-turn cost projection (haiku parse + sonnet narrate).

Lints implemented (research-doc ids; thresholds adapted to a 20-piece batch):
  L1  banned-phrase regexes                       per-narration FAIL
  L2  cross-fixture content 3-gram / 4-gram tics  batch FAIL/WARN
  L3  hook-ending ratio (>25% of 20 = FAIL) + 3-consecutive FAIL
  L4  em-dash / ellipsis rates                    WARN -> corpus FAIL
  L6  sentence-length CV (pooled): <0.35 FAIL, <0.45 WARN
  L7  negative parallelism / rule-of-three        per-narration + corpus
  L8  emotion-naming ("mixture of X and Y" -> FAIL outright)
  C1  bind-to-dice: success words on a miss FAIL; failure words on strong_hit FAIL
  C2  entity names: mid-sentence proper nouns absent from fixture data FAIL
  C3  mechanics leakage: dice/roll/modifier vocabulary in prose FAIL
  C4  System markup ([ ], << >>) in prose FAIL
  C5  bare digits not present in fixture data WARN
  C6  injection canaries (per-fixture list) FAIL
  C7  trivial register: word cap per fixture checks FAIL
  C8  truncation: stop_reason != end_turn WARN
  C11 specific injury location unsupported by committed outcome/context FAIL

Usage:  .venv/bin/python llm/narrator_eval.py [--ids nf-01,...] [--tag label]
Budget: one full run = 20 sonnet-5 calls (~2.5-3k in / <=400 out each).
        HARD CAP 8 full runs this sprint — log every run in llm/EVAL-LOG.md.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assembler import assemble  # noqa: E402
from narration_gate import (  # noqa: E402 — the runtime gate is the single source
    FAILURE_WORDS,
    MARKUP,
    MECHANICS,
    STOPWORDS,
    SUCCESS_WORDS,
    allowed_facts,
    asserted_facts,
    sentences,
    specific_injury_violation,
    unknown_proper_nouns,
    unnegated,
    unsupported_npc_speech,
    words,
)
from narrator import MODEL, build_client, load_system_prompt, narrate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_PATH = REPO_ROOT / "evals" / "narration-fixtures.json"
RESULTS_DIR = REPO_ROOT / "llm" / "results"

OUTCOME_V = Draft202012Validator(
    json.loads((REPO_ROOT / "docs/contracts/outcome.schema.json").read_text())
)
CONTEXT_V = Draft202012Validator(
    json.loads((REPO_ROOT / "docs/contracts/narration_context.schema.json").read_text())
)

# ---- pricing (per MTok, standard rates; claude-api skill 2026-06) ----------
SONNET_IN, SONNET_OUT = 3.00, 15.00     # intro $2/$10 through 2026-08-31
HAIKU_IN, HAIKU_OUT = 1.00, 5.00
# measured haiku parse footprint (one real p9 call, 2026-07-13: prompt +
# roster + strict tool schema = 5859 in, 181 out)
HAIKU_PARSE_IN, HAIKU_PARSE_OUT = 5860, 180

# ---- L1 banned phrases (seed list from the research doc) --------------------
BANNED = [re.compile(p, re.IGNORECASE) for p in [
    r"shiver(s|ed)? (down|up|ran)", r"send(ing|s)? shivers",
    r"knuckles whiten", r"white-?knuckl",
    r"air (was|is|hung) (thick|heavy|charged)",
    r"barely above a whisper", r"voice barely",
    r"eyes? (sparkl|gleam|glint|twinkl|alight|glow)\w* with",
    r"a (mix|mixture) of \w+ and \w+",
    r"testament to", r"\btapestry\b",
    r"what (seemed|felt) like an eternity",
    r"couldn'?t help but", r"despite (him|her|them)sel",
    r"unspoken (tension|understanding)",
    r"heart (pound|hammer|race)\w* in (his|her|their) (chest|ears)",
    r"breath (hitch|caught)",
    r"little did", r"would (later|soon|come to) (prove|learn|regret)",
    r"dance as old as time", r"symphony of",
    r"something (stirred|coiled|shifted) (with)?in",
    r"in that moment", r"a (single|lone) tear",
    # the "X keeps [verb]-ing, unbothered" indifference construction — the
    # negated-attention tic's newest mutation (4x in George's live session).
    r"keeps? \w+ing,?\s*(?:\w+ing,?\s*)?unbothered", r"\bunbothered\b", r"\bunperturbed\b",
]]

NEG_PARALLEL = [re.compile(p, re.IGNORECASE) for p in [
    r"\bnot (just|merely|only|simply)\b.{0,50}\bbut\b",
    r"\bit was(n't| not) [^.]{0,40}[.;] It was\b",
    r"\bno longer\b.{0,30}\bbut\b",
]]
FORESHADOW = re.compile(
    r"\blittle did\b|\bwould (prove|come to)\b|\bfor now\b|\bnot yet\b", re.IGNORECASE
)
EMOTION_PAIR = re.compile(r"\b(a )?(mix|mixture) of \w+ and \w+", re.IGNORECASE)
HOOK_TAIL = re.compile(
    r"(waiting|watching|for now|not yet|something|whatever it was)\b[^.]*[.]?$",
    re.IGNORECASE,
)
HOOK_OPEN = re.compile(r"^(somewhere|far away|above|below|behind you)\b", re.IGNORECASE)


def is_hook_ending(text: str) -> bool:
    if text.rstrip().endswith(("...", "…", "?")):
        return True
    last = sentences(text)[-1] if sentences(text) else ""
    if HOOK_OPEN.search(last) or HOOK_TAIL.search(last):
        return True
    return bool(re.search(r",\s+\w+ing\s*\.$", last))  # trailing participial atmosphere


def fixture_vocab(fx: dict) -> set[str]:
    """Every word appearing anywhere in the fixture's data, lowercased."""
    blob = json.dumps(fx, ensure_ascii=False)
    return {w.lower() for w in words(blob)}


def content_ngrams(text: str, n: int) -> set[tuple]:
    ws = [w.lower() for w in words(text)]
    out = set()
    for i in range(len(ws) - n + 1):
        gram = tuple(ws[i:i + n])
        if all(g in STOPWORDS for g in gram):
            continue
        if sum(1 for g in gram if g not in STOPWORDS) < (2 if n == 3 else 2):
            continue
        out.add(gram)
    return out


def lint_one(fx: dict, text: str, stop_reason: str) -> tuple[list[str], list[str]]:
    fails, warns = [], []
    checks = fx.get("checks", {})
    outcome = fx["outcome"]

    for rx in BANNED:
        if rx.search(text):
            fails.append(f"L1 banned phrase: /{rx.pattern}/")
    np_hits = sum(1 for rx in NEG_PARALLEL if rx.search(text))
    if np_hits > 1:
        fails.append("L7 negative parallelism >1")
    elif np_hits == 1:
        warns.append("L7 negative parallelism x1")
    if EMOTION_PAIR.search(text):
        fails.append("L8 emotion pair (mixture of X and Y)")
    if FORESHADOW.search(text):
        fails.append("R5 foreshadowing phrase")
    if MECHANICS.search(text):
        fails.append("C3 mechanics vocabulary in prose")
    if MARKUP.search(text):
        fails.append("C4 System markup in prose")

    if outcome["outcome_tier"] == "miss" and unnegated(SUCCESS_WORDS, text):
        fails.append("C1 CRITICAL success-framing on a miss")
    if outcome["outcome_tier"] == "strong_hit" and unnegated(FAILURE_WORDS, text):
        fails.append("C1 failure-framing on a strong hit")

    unknown = unknown_proper_nouns(text, fixture_vocab(fx))
    if unknown:
        fails.append(f"C2 entity names outside context: {unknown}")

    # C9 unsupported NPC speech (turn-53 fabrication class; runtime gate G6).
    # Uses the assembled envelope so a monologue is judged against the real
    # scene roster and the same speech-license logic the runtime gate applies.
    monologue = unsupported_npc_speech(
        text, outcome, fx.get("action"), fx.get("_assembled_envelope"))
    if monologue is not None:
        snippet = monologue if len(monologue) <= 60 else monologue[:57] + "..."
        fails.append(f"C9 unsupported NPC speech (unaddressed NPC monologue): {snippet!r}")

    # C10 semantic outcome agreement (runtime gate G3(b); category contract kill-on-miss /
    # invented inventory-door). Same rule as narration_gate: the prose may
    # assert only outcome-facts the committed deltas license.
    licensed = allowed_facts(outcome)
    for fact, snippet in asserted_facts(text).items():
        if fact not in licensed:
            snip = snippet if len(snippet) <= 60 else snippet[:57] + "..."
            fails.append(f"C10 asserts unlicensed {fact} (no committed delta): {snip!r}")
    specific = specific_injury_violation(
        text, outcome, fx.get("_assembled_envelope"), fx.get("action")
    )
    if specific is not None:
        fails.append(f"C11 {specific}")

    digits = set(re.findall(r"\d+", text))
    known_digits = set(re.findall(r"\d+", json.dumps(fx)))
    stray = digits - known_digits
    if stray:
        warns.append(f"C5 bare digits not in fixture data: {sorted(stray)}")

    for canary in checks.get("canaries_absent", []):
        if canary.lower() in text.lower():
            fails.append(f"C6 canary present: {canary!r}")

    max_words = checks.get("max_words")
    n_words = len(words(text))
    if max_words:
        if n_words > int(max_words * 1.5):
            fails.append(
                f"C7 register: {n_words} words on a {checks['tier_class']} beat "
                f"(cap {max_words})"
            )
        elif n_words > max_words:
            warns.append(f"C7 register: {n_words} words > soft cap {max_words}")

    if stop_reason != "end_turn":
        warns.append(f"C8 stop_reason={stop_reason} (possible truncation)")
    return fails, warns


def lint_batch(results: list[dict]) -> tuple[list[str], list[str], dict]:
    fails, warns = [], []
    texts = [r["text"] for r in results]

    hooks = [is_hook_ending(t) for t in texts]
    ratio = sum(hooks) / len(hooks) if hooks else 0
    if ratio > 0.25:
        fails.append(f"L3 hook-ending ratio {ratio:.0%} > 25% ({sum(hooks)}/{len(hooks)})")
    for i in range(len(hooks) - 2):
        if hooks[i] and hooks[i + 1] and hooks[i + 2]:
            fails.append(f"L3 three consecutive hook endings at #{i}")
            break

    lens = [len(words(s)) for t in texts for s in sentences(t)]
    cv = (statistics.pstdev(lens) / statistics.mean(lens)) if lens and statistics.mean(lens) else 0
    if cv < 0.35:
        fails.append(f"L6 sentence-length CV {cv:.2f} < 0.35 (uniformity)")
    elif cv < 0.45:
        warns.append(f"L6 sentence-length CV {cv:.2f} < 0.45")
    band = sum(1 for L in lens if 10 <= L <= 22) / len(lens) if lens else 0
    if band > 0.75:
        warns.append(f"L6 {band:.0%} of sentences in the 10-22 word band")

    tri_docs: Counter = Counter()
    quad_total: Counter = Counter()
    for t in texts:
        for g in content_ngrams(t, 3):
            tri_docs[g] += 1
        ws = [w.lower() for w in words(t)]
        for i in range(len(ws) - 3):
            quad_total[tuple(ws[i:i + 4])] += 1
    for g, n in tri_docs.most_common(12):
        if n >= 3:
            fails.append(f"L2 3-gram tic in {n}/20 narrations: {' '.join(g)!r}")
        elif n == 2:
            warns.append(f"L2 3-gram in 2 narrations: {' '.join(g)!r}")
    for g, n in quad_total.items():
        if n >= 3 and not all(w in STOPWORDS for w in g):
            fails.append(f"L2 4-gram x{n}: {' '.join(g)!r}")

    dash = [t.count("—") + t.count(" - ") for t in texts]
    if statistics.mean(dash) > 0.6:
        fails.append(f"L4 em-dash corpus mean {statistics.mean(dash):.2f} > 0.6")
    elif any(d > 1 for d in dash):
        warns.append(f"L4 em-dash >1 in {sum(1 for d in dash if d > 1)} narrations")
    ell = [t.count("...") + t.count("…") for t in texts]
    if statistics.mean(ell) > 0.15:
        fails.append(f"L4 ellipsis corpus mean {statistics.mean(ell):.2f} > 0.15")

    np_total = sum(1 for t in texts for rx in NEG_PARALLEL if rx.search(t))
    if np_total / len(texts) > 0.15:
        fails.append(f"L7 negative-parallelism corpus mean {np_total/len(texts):.2f} > 0.15")

    stats = {"hook_ratio": ratio, "sentence_cv": cv, "band_10_22": band,
             "em_dash_mean": statistics.mean(dash) if dash else 0,
             "ellipsis_mean": statistics.mean(ell) if ell else 0}
    return fails, warns, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=str, default=None)
    ap.add_argument("--tag", type=str, default="narration")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    fixtures = json.loads(FIXTURES_PATH.read_text())["fixtures"]
    if args.ids:
        wanted = set(args.ids.split(","))
        fixtures = [f for f in fixtures if f["id"] in wanted]

    system_prompt = load_system_prompt()
    client = build_client()
    print(f"Narrating {len(fixtures)} fixtures on {MODEL} "
          f"({len(system_prompt)}-char prompt) ...", flush=True)
    t0 = time.time()

    def run_one(fx):
        env = assemble(fx["view"]).envelope
        assert not list(CONTEXT_V.iter_errors(env)), fx["id"]
        assert not list(OUTCOME_V.iter_errors(fx["outcome"])), fx["id"]
        fx["_assembled_envelope"] = env  # for the C9 NPC-speech lint (scene roster)
        res = narrate(client, env, fx["outcome"], fx["action"], system_prompt)
        return fx, res

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fx, res in pool.map(run_one, fixtures):
            results.append({"id": fx["id"], "text": res.text,
                            "input_tokens": res.input_tokens,
                            "output_tokens": res.output_tokens,
                            "stop_reason": res.stop_reason, "fixture": fx})
            sys.stdout.write(".")
            sys.stdout.flush()
    results.sort(key=lambda r: r["id"])
    print(f"\nDone in {time.time() - t0:.1f}s")

    per_fail = per_warn = 0
    for r in results:
        fails, warns = lint_one(r["fixture"], r["text"], r["stop_reason"])
        r["fails"], r["warns"] = fails, warns
        per_fail += bool(fails)
        per_warn += bool(warns)
        flag = "FAIL" if fails else ("warn" if warns else "ok  ")
        print(f"  [{flag}] {r['id']}  ({len(words(r['text']))}w, "
              f"in={r['input_tokens']}, out={r['output_tokens']})")
        for f in fails:
            print(f"        FAIL {f}")
        for w in warns:
            print(f"        warn {w}")

    batch_fails, batch_warns, stats = lint_batch(results)
    print("\n== Batch lints ==")
    for f in batch_fails:
        print(f"  FAIL {f}")
    for w in batch_warns:
        print(f"  warn {w}")
    print(f"  stats: {json.dumps(stats)}")

    ins = sorted(r["input_tokens"] for r in results)
    outs = sorted(r["output_tokens"] for r in results)
    p95 = lambda xs: xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]  # noqa: E731
    mean_in, mean_out = statistics.mean(ins), statistics.mean(outs)
    narr_cost = (mean_in * SONNET_IN + mean_out * SONNET_OUT) / 1e6
    parse_cost = (HAIKU_PARSE_IN * HAIKU_IN + HAIKU_PARSE_OUT * HAIKU_OUT) / 1e6
    print("\n== Cost accounting ==")
    print(f"  narrator ({MODEL}): input mean {mean_in:.0f} / p95 {p95(ins)}, "
          f"output mean {mean_out:.0f} / p95 {p95(outs)}")
    print(
        f"  narrate cost/turn:  ${narr_cost:.6f} "
        f"(standard rates ${SONNET_IN}/{SONNET_OUT} per MTok)"
    )
    print(
        f"  parse cost/turn:    ${parse_cost:.6f} "
        f"(haiku, {HAIKU_PARSE_IN} in / {HAIKU_PARSE_OUT} out measured)"
    )
    print(f"  PER-TURN TOTAL:     ${narr_cost + parse_cost:.6f}  "
          f"(~${1000 * (narr_cost + parse_cost):.2f} per 1k turns)")

    ok = per_fail == 0 and not batch_fails
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.tag}.json"
    out_path.write_text(json.dumps({
        "model": MODEL, "fixtures": len(results),
        "per_narration_failing": per_fail, "batch_fails": batch_fails,
        "batch_warns": batch_warns, "stats": stats,
        "usage": {"input_mean": mean_in, "input_p95": p95(ins),
                  "output_mean": mean_out, "output_p95": p95(outs)},
        "cost_per_turn_usd": narr_cost + parse_cost,
        "narrations": [{k: r[k] for k in ("id", "text", "input_tokens", "output_tokens",
                                          "stop_reason", "fails", "warns")} for r in results],
    }, indent=1, ensure_ascii=False))
    print(f"\nResults saved: {out_path.relative_to(REPO_ROOT)}")
    print(f"VERDICT: {'PASS' if ok else 'FAIL'} "
          f"({per_fail} narrations with FAILs, {len(batch_fails)} batch FAILs)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
