"""Run a paid eval script with its cost measured and a hard spend cap.

  .venv/bin/python -m llm.spend_cap --max-usd 2 -- llm/parser_eval.py --file evals/heldout-2.jsonl

Wraps the SDK's ``Messages.create`` in this process. Before a call goes out it
reserves that call's worst case: the request's size over-counted at three
characters a token, every input token priced as a cache write, plus
``max_tokens`` of output. A call whose reservation would take the spend plus
everything still reserved past the cap raises instead of going out, so the cap
holds from the first call and across a thread pool (audit 2026-10-24,
codex-004). When the response arrives its real cost replaces the reservation.
The measured total is printed when the script exits, whatever its exit code.
"""

from __future__ import annotations

import argparse
import atexit
import json
import runpy
import sys
import threading

from anthropic.resources.messages import Messages

#: USD per million tokens (input, output), first-party API rates. Cache reads
#: bill at 0.1x input and cache writes at 1.25x input.
PRICES_PER_MTOK = {
    "claude-haiku-4-5": (1.00, 5.00),
    # OpenRouter passes the provider's price through (llm/parser.OPENROUTER_MODELS).
    "anthropic/claude-haiku-4.5": (1.00, 5.00),
}


class SpendCapReached(RuntimeError):
    """The next call could take the run past its --max-usd cap."""


def worst_case_usd(kwargs: dict, price_in: float, price_out: float) -> float:
    """An upper bound on one call's cost from its request alone."""
    sent = {k: kwargs.get(k) for k in ("system", "messages", "tools")}
    input_tokens = len(json.dumps(sent, default=str)) // 3 + 1
    output_tokens = int(kwargs.get("max_tokens") or 4096)
    return (1.25 * input_tokens * price_in + output_tokens * price_out) / 1_000_000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("script")
    ap.add_argument("args", nargs=argparse.REMAINDER)
    a = ap.parse_args()

    lock = threading.Lock()
    totals = {"usd": 0.0, "calls": 0, "in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    state = {"reserved": 0.0}
    original = Messages.create

    def priced(self, *args, **kwargs):
        model = kwargs.get("model")
        if model not in PRICES_PER_MTOK:
            raise SpendCapReached(f"no price for model {model!r}; add it to PRICES_PER_MTOK")
        price_in, price_out = PRICES_PER_MTOK[model]
        worst = worst_case_usd(kwargs, price_in, price_out)
        with lock:
            if totals["usd"] + state["reserved"] + worst > a.max_usd:
                raise SpendCapReached(
                    f"spent ${totals['usd']:.4f} with ${state['reserved']:.4f} reserved; this "
                    f"call could cost ${worst:.4f}, past the ${a.max_usd:.2f} cap"
                )
            state["reserved"] += worst
        try:
            response = original(self, *args, **kwargs)
        except BaseException:
            with lock:
                state["reserved"] -= worst
            raise
        # A with_raw_response call returns a wrapper; its parse() holds the usage.
        u = response.usage if hasattr(response, "usage") else response.parse().usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        usd = (
            (u.input_tokens + 0.1 * cache_read + 1.25 * cache_write) * price_in
            + u.output_tokens * price_out
        ) / 1_000_000
        with lock:  # settle: the real cost replaces the reservation in one step
            state["reserved"] -= worst
            totals["usd"] += usd
            totals["calls"] += 1
            totals["in"] += u.input_tokens
            totals["out"] += u.output_tokens
            totals["cache_read"] += cache_read
            totals["cache_write"] += cache_write
        return response

    Messages.create = priced

    def report() -> None:
        calls = totals["calls"]
        per = totals["usd"] / calls if calls else 0.0
        print(
            f"\nSPEND: ${totals['usd']:.4f} over {calls} calls (${per:.5f} a call; "
            f"{totals['in']} input, {totals['out']} output, {totals['cache_read']} cache-read, "
            f"{totals['cache_write']} cache-write tokens; cap ${a.max_usd:.2f})"
        )

    atexit.register(report)
    sys.argv = [a.script, *a.args]
    try:
        runpy.run_path(a.script, run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
