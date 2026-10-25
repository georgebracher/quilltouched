"""Paid LLM spend: the daily cap, the per-command budget reservation, and the
cost estimate the ops endpoint reports."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from api import accounts as accounts_mod
from api import ratelimit, telemetry
from api.messages import INK_SPENT, INK_TYPED_REQUIRES_TAP, TURN_DAILY_DONE, TURN_TOO_FAST

#: When a usage-ledger write last failed (monotonic seconds), or None.
_ledger_failed_at: float | None = None
LEDGER_FAILURE_HOLD_S = 300


def note_ledger_failure() -> None:
    """Called by the gateway when an llm_usage row could not be written."""
    global _ledger_failed_at
    _ledger_failed_at = time.monotonic()


def ledger_failing() -> bool:
    """A usage write failed in the last few minutes: hold the paid layers."""
    return _ledger_failed_at is not None and (
        time.monotonic() - _ledger_failed_at < LEDGER_FAILURE_HOLD_S
    )


def _utc_seconds_to_midnight() -> int:
    return max(1, int(86400 - (time.time() % 86400)))


def _todays_spend_usd(conn) -> float:
    """Estimated global LLM spend since UTC midnight, from the llm_usage ledger."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT model,
                       sum(input_tokens)::bigint,
                       sum(output_tokens)::bigint,
                       sum(cache_read_input_tokens)::bigint,
                       sum(cache_creation_input_tokens)::bigint
                FROM public.llm_usage
                WHERE ts >= date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc'
                GROUP BY model
                """
            )
            rows = cur.fetchall()
    total = 0.0
    for model, in_tok, out_tok, cache_read, cache_write in rows:
        row = {
            "model": model,
            "input_tokens": int(in_tok),
            "output_tokens": int(out_tok),
            "cache_read_input_tokens": int(cache_read),
            "cache_creation_input_tokens": int(cache_write),
        }
        cost = _estimated_cost_usd(row)
        if cost is None:
            # A model missing from the price table must not read as free: the
            # breaker would sit at $0 after a model change (audit 2026-10-24,
            # k3 F4). Price it at the dearest known rate and say so.
            cost = _estimated_cost_usd(row, prices=_DEAREST_PRICES)
            telemetry.emit("unpriced_model", model=model, priced_as=_DEAREST_PRICES)
        total += cost
    return total


@dataclass(frozen=True, slots=True)
class _PaidBudget:
    """DEGRADE-NOT-BLOCK verdict for the PAID LLM layers only. The
    deterministic engine turn (parse-if-structured, beat, resolve, commit) is
    NEVER gated by this — only the free-text parser and the narrator degrade
    when the daily turn cap / global spend breaker is spent."""

    parse_allowed: bool     # the paid free-text parser may run
    narrate_allowed: bool   # the paid narrator may run
    block_line: str         # System-voice line when a paid layer is refused
    retry_after_s: int      # Retry-After for a paid-layer 429


def _cost_budget_status(conn, account: accounts_mod.Account) -> tuple[bool, str, int]:
    """READ-ONLY: is the paid-narration budget (daily turn cap + global spend
    breaker) still open? Returns (allowed, block_line, retry_after). No counter
    is incremented — safe to call at narration time and on the confirm
    continuation without re-charging the original command (the double-count
    fix)."""
    daily_cap = int(os.environ.get("EVERQUILL_DAILY_TURN_CAP", "500"))
    daily_count = ratelimit.peek(
        conn, f"turnday:{account.account_id}", window_seconds=86400
    )
    if daily_count > daily_cap:
        return False, TURN_DAILY_DONE, _utc_seconds_to_midnight()
    spend_cap = float(os.environ.get("EVERQUILL_DAILY_SPEND_CAP_USD", "20"))
    spent = _todays_spend_usd(conn)
    if spent >= spend_cap:
        telemetry.emit(
            "spend_cap_hit",
            account_id=account.account_id,
            spent_usd=round(spent, 4),
            cap_usd=spend_cap,
        )
        return False, INK_SPENT, _utc_seconds_to_midnight()
    return True, "", 0


def _reserve_paid_budget(
    conn, account: accounts_mod.Account, *, has_text: bool
) -> _PaidBudget:
    """Reserve this FRESH command's paid budget ONCE (budget is
    reserved atomically once per command, never re-charged by the confirm
    continuation). The engine turn is never blocked here; the returned flags
    gate only the paid layers:

    - The per-minute rate is a transient FLOOD guard on the paid free-text
      parser — checked (and reserved) only when ``has_text``, and it never
      touches a structured (tapped) turn.
    - The daily turn cap + global spend breaker are the paid-narration budget.
      The daily counter is reserved once here; a spent budget DEGRADES the
      paid layers (free text 429s to require a tapped action; narration is
      skipped) but the deterministic outcome always resolves.
    """
    # Transient flood guard on the paid parser, BEFORE reserving the daily slot
    # (a rejected free-text burst must not burn the day's budget).
    if has_text:
        per_min = int(os.environ.get("EVERQUILL_TURN_RATE_PER_MIN", "10"))
        minute = ratelimit.hit(
            conn, f"turn:{account.account_id}", limit=per_min, window_seconds=60
        )
        if not minute.allowed:
            return _PaidBudget(
                parse_allowed=False,
                narrate_allowed=False,
                block_line=TURN_TOO_FAST,
                retry_after_s=minute.retry_after_s,
            )

    # Reserve the daily paid-turn slot ONCE for this command.
    daily_cap = int(os.environ.get("EVERQUILL_DAILY_TURN_CAP", "500"))
    daily = ratelimit.hit(
        conn, f"turnday:{account.account_id}", limit=daily_cap, window_seconds=86400
    )
    spend_cap = float(os.environ.get("EVERQUILL_DAILY_SPEND_CAP_USD", "20"))
    spent = _todays_spend_usd(conn)
    # A ledger that cannot record spend cannot bound it: while writes fail, the
    # breaker reads as tripped instead of reading a falsely low total (k3-005).
    spend_ok = spent < spend_cap and not ledger_failing()
    if not spend_ok:
        telemetry.emit(
            "spend_cap_hit",
            account_id=account.account_id,
            spent_usd=round(spent, 4),
            cap_usd=spend_cap,
        )
    cost_ok = daily.allowed and spend_ok
    if not daily.allowed:
        block_line, retry = TURN_DAILY_DONE, daily.retry_after_s
    elif not spend_ok:
        block_line, retry = INK_SPENT, _utc_seconds_to_midnight()
    else:
        block_line, retry = INK_TYPED_REQUIRES_TAP, _utc_seconds_to_midnight()
    return _PaidBudget(
        # free text needs the paid parser AND the paid narrator; a structured
        # turn ignores parse_allowed entirely (it never calls the parser).
        parse_allowed=cost_ok,
        narrate_allowed=cost_ok,
        block_line=block_line,
        retry_after_s=retry,
    )


# USD per 1M tokens (input, output). Cache reads bill ~0.1x input, cache
# writes ~1.25x input. Sonnet-5 shown at standard price (intro pricing runs
# cheaper through 2026-08-31). Keep in sync with docs/ops/telemetry.md.
_PRICES_PER_MTOK = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
}


#: What an unpriced model is charged at in the spend breaker (fail closed).
_DEAREST_PRICES = max(_PRICES_PER_MTOK.values())


def _estimated_cost_usd(
    row: dict[str, Any], *, prices: tuple[float, float] | None = None
) -> float | None:
    prices = prices or _PRICES_PER_MTOK.get(row["model"])
    if prices is None:
        return None
    in_price, out_price = prices
    cost = (
        row["input_tokens"] * in_price
        + row["output_tokens"] * out_price
        + row["cache_read_input_tokens"] * in_price * 0.1
        + row["cache_creation_input_tokens"] * in_price * 1.25
    ) / 1_000_000
    return round(cost, 6)
