"""DB-backed fixed-window rate limiting.

Documented choice: a FIXED WINDOW, not a token bucket. At alpha scale the
bucket's smoothness buys nothing; a fixed window is one atomic upsert per
hit (``INSERT .. ON CONFLICT DO UPDATE .. RETURNING``), race-free under
Postgres row locking across every worker, and its worst case — a 2x burst
straddling a window edge — is acceptable for turn/claim throttling. Windows
are ``floor(epoch / window) * window`` so day windows align to UTC midnight
and every process agrees on the boundary without clock coordination.

Storage: ``public.rate_limit`` (migration 0010) — global table, written by
``app_role`` (SELECT/INSERT/UPDATE only). Buckets in use:

- ``turn:<account_id>``     per-minute turn rate   (EVERQUILL_TURN_RATE_PER_MIN)
- ``turnday:<account_id>``  daily turn ceiling     (EVERQUILL_DAILY_TURN_CAP)
- ``claim:ip:<ip>``         invite-claim per-IP    (EVERQUILL_CLAIM_RATE_PER_MIN)
- ``claim:global``          invite-claim global    (EVERQUILL_CLAIM_RATE_GLOBAL_PER_MIN)

The helper opens its own short transaction; callers must not hold one
(the beat owns the top-level transaction later in the request).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["WindowVerdict", "hit", "peek"]


@dataclass(frozen=True, slots=True)
class WindowVerdict:
    allowed: bool
    count: int
    limit: int
    retry_after_s: int  # seconds until the current window rolls over


def hit(conn, bucket_key: str, *, limit: int, window_seconds: int) -> WindowVerdict:
    """Record one hit on ``bucket_key`` and say whether it fit the window.

    Counts first, then compares: a denied hit still increments (denied
    retries never help an abuser reach the next window with budget).
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.rate_limit (bucket_key, window_start, count)
                VALUES (
                    %(key)s,
                    to_timestamp(
                        floor(extract(epoch FROM now()) / %(win)s) * %(win)s
                    ),
                    1
                )
                ON CONFLICT (bucket_key, window_start)
                    DO UPDATE SET count = public.rate_limit.count + 1
                RETURNING
                    count,
                    ceil(extract(epoch FROM window_start) + %(win)s
                         - extract(epoch FROM now()))::int
                """,
                {"key": bucket_key, "win": window_seconds},
            )
            count, retry_after = cur.fetchone()
    return WindowVerdict(
        allowed=count <= limit,
        count=count,
        limit=limit,
        retry_after_s=max(1, int(retry_after)),
    )


def peek(conn, bucket_key: str, *, window_seconds: int) -> int:
    """The current count in ``bucket_key``'s live window WITHOUT incrementing.

    Read-only twin of :func:`hit`, for the degrade-not-block turn path
    (degrade-not-block): a continuation (``/api/action/confirm``) must be able to
    ask "is the paid-narration budget already spent for today?" without
    re-charging the original command's budget (the confirmation double-count
    fix). Returns 0 when this window has no row yet.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count FROM public.rate_limit
                WHERE bucket_key = %(key)s
                  AND window_start = to_timestamp(
                        floor(extract(epoch FROM now()) / %(win)s) * %(win)s
                  )
                """,
                {"key": bucket_key, "win": window_seconds},
            )
            row = cur.fetchone()
    return int(row[0]) if row is not None else 0
