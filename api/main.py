"""Quilltouched API v2 — accounts + the full turn pipeline.

    GET  /api/hello                open: liveness + lore
    GET  /healthz                  open: platform health probe
    POST /api/claim                {invite_code} -> {device_token} (accounts v1)
                                   optional {mode:"guided"} defers character
                                   creation to /api/chargen
    GET  /api/chargen/pool         authed guided-dice pool: 7 {index,total}
    POST /api/chargen              authed guided character placement
    GET  /api/scene                perceived scene (+ status-strip `facts`:
                                   coin + active timers); Bearer -> YOUR world,
                                   unauthed -> the legacy shared world (read-only)
    GET  /api/codex                authed: the player's Inquiry claims as fact
                                   cards (KnownState only, no true values) +
                                   known locations
    POST /api/hypothesis           authed: {claim_ids, note} -> research-target
                                   suggestions (C's evaluate_hypothesis)
    POST /api/action               structured intent OR {text} -> parse -> beat ->
                                   resolve -> assemble -> narrate (decision 3),
                                   binding the prose to its outcome as canon
    POST /api/action/confirm       {command_id} -> resolve a pending <<Proceed?>> beat
    GET  /api/ops/usage            daily LLM cost rollup (EVERQUILL_OPS_TOKEN)

Design laws enforced here:
- True sheets NEVER serialize: every read goes through the KnownState surface
  (docs/engine/known-state.md); this module cannot import the referee surface
  (static lint, tests/test_known_boundary.py — KNOWN_DEBT now empty).
- The engine referees everything: the parser only classifies the utterance,
  the narrator only renders the committed outcome contract. Narration failure
  never blocks the outcome (canon never waits — locked decision 3).
- Player text is untrusted data everywhere (locked decision 4): it travels to
  the parser under a data heading and to the narrator inside JSON literals.
- Accounts v1 (locked decision 1): per-account worlds in per-account Postgres
  schemas; the old shared world stays readable but takes no new actions (410).

Ops behavior:
- Starts clean with no DATABASE_URL: /healthz stays 200, game endpoints 503
  (unauthed POST /api/action is 410 before any DB work — auth is checked first).
- Startup runs apply_migrations on the admin connection (idempotent) — this is
  how 0006/0007 reach the live DB — then bootstraps the legacy public-schema
  world. Account schemas migrate + bootstrap on first authenticated call.
- Telemetry: structured JSON lines per request + per LLM stage
  (docs/ops/telemetry.md).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from api import accounts as accounts_mod
from api import context as context_mod
from api import llm_gateway, ratelimit, telemetry
from api.bootstrap import PC_ID, bootstrap, starting_location
from api.budget import (
    _DEAREST_PRICES,
    _cost_budget_status,
    _estimated_cost_usd,
    _reserve_paid_budget,
)
from api.intents import (
    _check_intent_bytes,
    _clamp_parsed_intent,
    _committed_intent,
    _intent_errors,
    _probe_command_state,
    _stored_intent,
    _stored_outcome_row,
    _validate_command_id,
    _validated_contract,
)
from api.messages import (
    CLAIM_THROTTLED,
    CODE_FOR_429_LINE,
    MOMENT_PASSED,
    NARRATION_RESTING,
    SHARED_WORLD_SEALED,
    TURN_IN_FLIGHT,
)
from api.middleware import (
    BODY_MAX_BYTES,
    BodySizeLimitMiddleware,
)
from api.presenters import (
    _codex_claim,
    _known_locations,
    _scene_response,
    _self_response,
    _subject_labels,
)
from api.state import read_chargen_status, read_known_state, read_self
from everquill_engine import security
from everquill_engine.beat import (
    BeatIntentMismatchError,
    ConfirmationExpiredError,
    NoPendingConfirmationError,
    assess_or_execute,
)
from everquill_engine.beat import confirm as beat_confirm
from everquill_engine.chargen import build_character, chargen_events, roll_pool
from everquill_engine.db import REPO_ROOT, connect, resolve_database_url
from everquill_engine.resolver import ResolverError, contract_id, outcome_contract
from everquill_engine.store import (
    ConcurrencyError,
    execute_command,
    migrate_and_rebuild,
    narrate_outcome,
    public_turn,
    recent_public_turns,
)
from everquill_engine.views import outcome_public
from everquill_engine.world import WorldContent, load_world
from llm import codex, narration_gate
from llm.assembler import stamp_content_hash

# --- config ---------------------------------------------------------------------

DEFAULT_WORLD_FILE = "content/world/harrowdown.yaml"


def _world_path() -> Path:
    raw = os.environ.get("EVERQUILL_WORLD", DEFAULT_WORLD_FILE)
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _seed() -> int:
    return int(os.environ.get("EVERQUILL_SEED", "42"))


# --- app state ------------------------------------------------------------------


#: Seconds a failed engine bootstrap waits before the next attempt.
BOOTSTRAP_BACKOFF_S = 10


class _EngineState:
    """Lazily-established engine readiness (world content + migrated DB +
    bootstrapped LEGACY world in the public schema)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.world: WorldContent | None = None
        self.world_id: str | None = None
        self.world_error: str | None = None
        self.bootstrapped = False
        # Monotonic time of the last failed bootstrap: requests and /readyz polls
        # wait out BOOTSTRAP_BACKOFF_S instead of re-running migrations against
        # a database that is down (k3-006).
        self.bootstrap_failed_at: float | None = None
        self.runtime_role_warned = False
        self.content_drift: dict[str, Any] | None = None
        # Fail-closed readiness: None = secure (or dev-lenient);
        # a string = the InsecureRuntimeError reason -> readiness 503s.
        self.secure_error: str | None = None
        self.secure_checked = False

    def load_world_content(self) -> None:
        if self.world is not None:
            return
        path = _world_path()
        try:
            self.world = load_world(path)
            self.world_id = path.stem
            self.world_error = None
        except Exception as exc:  # WorldContentError carries file:line:[id]
            self.world_error = str(exc)
            telemetry.emit("startup_error", component="world_loader", error=str(exc))

    def admin_url(self) -> str | None:
        return resolve_database_url()

    def runtime_url(self) -> str | None:
        app_url = os.environ.get("APP_DATABASE_URL")
        if app_url:
            return app_url
        fallback = self.admin_url()
        if fallback and not self.runtime_role_warned:
            self.runtime_role_warned = True
            telemetry.emit(
                "startup_warning",
                component="db",
                warning=(
                    "APP_DATABASE_URL not set — falling back to DATABASE_URL (table "
                    "owner). The event-table REVOKE does not bind the owner; set "
                    "APP_DATABASE_URL to the app_role connection for append-only "
                    "enforcement (migrations/0004_app_role.sql)."
                ),
            )
        return fallback

    def ensure_bootstrap(self) -> None:
        """Migrations + legacy-world genesis/chargen, once per process."""
        if self.bootstrapped:
            return
        with self.lock:
            if self.bootstrapped:
                return
            admin = self.admin_url()
            if admin is None or self.world is None:
                return
            failed_at = self.bootstrap_failed_at
            if failed_at is not None and time.monotonic() - failed_at < BOOTSTRAP_BACKOFF_S:
                raise RuntimeError("the last bootstrap failed moments ago; retrying shortly")
            try:
                with connect(admin) as conn:
                    applied = migrate_and_rebuild(conn)
                    summary = bootstrap(conn, self.world, _seed())
                    # Hashes of the legacy env invite codes join the
                    # invite table (idempotent; claim() also seeds lazily).
                    invites_seeded = accounts_mod.seed_env_invites(conn)
            except Exception:
                self.bootstrap_failed_at = time.monotonic()
                raise
            self.bootstrap_failed_at = None
            telemetry.emit(
                "bootstrap",
                migrations_applied=applied,
                env_invites_seeded=invites_seeded,
                **summary,
            )
            self.content_drift = summary["content_drift"]
            if self.content_drift and os.environ.get("EVERQUILL_ALLOW_CONTENT_DRIFT") == "1":
                telemetry.emit(
                    "startup_warning",
                    component="bootstrap",
                    warning="CONTENT DRIFT overridden by EVERQUILL_ALLOW_CONTENT_DRIFT=1 "
                    "— rulings may not match this world's committed canon (dev only)",
                    drift=self.content_drift,
                )
                self.content_drift = None
            elif self.content_drift:
                telemetry.emit(
                    "startup_warning",
                    component="bootstrap",
                    warning="MEDIUM-7 content drift on the LEGACY world: the configured "
                    "world YAML no longer matches the hash committed at genesis — "
                    "legacy reads will 503 (per-account worlds bootstrap their own "
                    "manifest and are unaffected unless they drift too)",
                    drift=self.content_drift,
                )
            if summary["content_manifest_missing"]:
                telemetry.emit(
                    "startup_warning",
                    component="bootstrap",
                    warning="this world predates content manifests — authored-content "
                    "drift cannot be verified",
                )
            self.bootstrapped = True

    def check_secure(self, *, force: bool = False) -> str | None:
        """THE fail-closed production readiness gate. Returns the
        InsecureRuntimeError reason when ``EVERQUILL_REQUIRE_SECURE=1`` and a
        precondition is unmet (``EVERQUILL_MASTER_KEY`` absent/malformed, or the
        RUNTIME connection can bypass the append-only grants — owner/superuser),
        else None. A no-op (None) in dev (unset). Cached; a transient DB error
        leaves it unchecked so a later request retries."""
        if not security.require_secure():
            self.secure_error = None
            self.secure_checked = True
            return None
        if self.secure_checked and not force:
            return self.secure_error
        url = self.runtime_url()
        if url is None:
            return self.secure_error  # verify once the runtime DB is present
        try:
            with connect(url) as conn:
                security.assert_secure_startup(conn)
            self.secure_error = None
            self.secure_checked = True
        except security.InsecureRuntimeError as exc:
            self.secure_error = str(exc)
            self.secure_checked = True
            telemetry.emit("startup_error", component="secure_check", error=str(exc))
        except Exception as exc:  # transient — do not cache a config verdict
            telemetry.emit("startup_warning", component="secure_check", warning=str(exc))
        return self.secure_error


ENGINE = _EngineState()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    ENGINE.load_world_content()
    db_present = ENGINE.admin_url() is not None
    if not db_present:
        telemetry.emit(
            "startup_warning",
            component="db",
            warning=(
                "DATABASE_URL not set (env or repo-root .env) — starting without a "
                "database; game endpoints will return 503 until one appears."
            ),
        )
    else:
        try:
            ENGINE.ensure_bootstrap()
        except Exception as exc:
            # Never crash-loop the service on a transient DB failure: start
            # degraded, retry lazily per request.
            telemetry.emit("startup_error", component="bootstrap", error=str(exc))
    # Fail-closed readiness: verify the secure preconditions once
    # at startup. In require-secure mode a failure makes readiness (and every
    # game endpoint) 503 until it is fixed — never fail-open.
    secure_error = ENGINE.check_secure()
    telemetry.emit(
        "startup",
        world=ENGINE.world_id,
        world_error=ENGINE.world_error,
        db="present" if db_present else "absent",
        bootstrapped=ENGINE.bootstrapped,
        runtime_role="app_role" if os.environ.get("APP_DATABASE_URL") else "owner_fallback",
        require_secure=security.require_secure(),
        secure_error=secure_error,
        invite_codes=len(accounts_mod.invite_codes()),
    )
    yield


app = FastAPI(title="Quilltouched API", lifespan=_lifespan)


# --- request body size limit — ASGI-level, before FastAPI parses -------


app.add_middleware(BodySizeLimitMiddleware, max_bytes=BODY_MAX_BYTES)

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    # Comma-separated browser origins allowed to call the API; the default is
    # the local vite dev server only. A hosted client adds its own origin here.
    allow_origins=[
        o.strip()
        for o in os.environ.get("EVERQUILL_CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "authorization"],
)


# --- telemetry middleware ---------------------------------------------------------


@app.middleware("http")
async def _request_telemetry(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        telemetry.emit(
            "request",
            method=request.method,
            path=request.url.path,
            status=500,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise
    record: dict[str, Any] = {
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    turn = getattr(request.state, "turn", None)
    if turn is not None:
        record["turn"] = turn
    telemetry.emit("request", **record)
    return response


# --- shared guards ----------------------------------------------------------------


def _require_engine() -> tuple[WorldContent, str]:
    """World content + a runtime DB url + migrated public schema, or 503."""
    if ENGINE.world is None:
        ENGINE.load_world_content()
    if ENGINE.world is None:
        raise HTTPException(
            status_code=503,
            detail=f"world content unavailable: {ENGINE.world_error or 'not loaded'}",
        )
    url = ENGINE.runtime_url()
    if url is None:
        raise HTTPException(
            status_code=503,
            detail="no database configured (DATABASE_URL / APP_DATABASE_URL unset)",
        )
    if not ENGINE.bootstrapped:
        try:
            ENGINE.ensure_bootstrap()
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail=f"database not ready: {exc}"
            ) from exc
    if not ENGINE.bootstrapped:
        raise HTTPException(status_code=503, detail="database not ready")
    # Fail-closed readiness: refuse to serve if the secure
    # preconditions are unmet in require-secure mode (no fail-open DEK storage,
    # no owner-authority runtime connection).
    secure_error = ENGINE.check_secure()
    if secure_error is not None:
        raise HTTPException(
            status_code=503, detail=f"readiness: insecure runtime — {secure_error}"
        )
    return ENGINE.world, url


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        return token or None
    return None


def _require_account(conn, token: str) -> accounts_mod.Account:
    account = accounts_mod.authenticate(conn, token)
    if account is None:
        raise HTTPException(status_code=401, detail="unknown device token")
    return account


def _enter_account_world(conn, account: accounts_mod.Account, world: WorldContent) -> None:
    """Bootstrap (idempotent, cached) + pin the connection to the account schema."""
    admin = ENGINE.admin_url()
    if admin is None:
        raise HTTPException(status_code=503, detail="no admin database connection")
    summary = accounts_mod.ensure_world_ready(account, world, admin)
    if summary.get("content_drift"):
        raise HTTPException(
            status_code=503,
            detail="authored content drift: the world YAML no longer matches the "
            "hash committed at this world's genesis (MEDIUM-7)",
        )
    accounts_mod.set_search_path(conn, account.schema)


def _check_world_id(world: Any, expected: str) -> None:
    if not isinstance(world, str) or not world:
        raise HTTPException(status_code=422, detail="world must be a non-empty string")
    if world != expected:
        raise HTTPException(
            status_code=404,
            detail=f"unknown world {world!r} (this token's world is {expected!r})",
        )


# --- rate, concurrency + spend controls ----------------------


#: A character's name, as the creation screen allows it.
CHARACTER_NAME_MAX = 40


def _system_429(line: str, retry_after_s: int) -> HTTPException:
    """429 in the System voice, always with Retry-After, and a machine code so
    the client can tell a breath from a spent day (audit 2026-10-24, k3 F6)."""
    return HTTPException(
        status_code=429,
        detail={"message": line, "code": CODE_FOR_429_LINE.get(line, "THROTTLED")},
        headers={"Retry-After": str(max(1, int(retry_after_s)))},
    )


def _turn_lock_key(account_id: str) -> int:
    """Stable signed-64 advisory-lock key for one account's turn pipeline."""
    digest = hashlib.sha256(f"everquill.turnlock.{account_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _acquire_turn_lock(conn, account_id: str) -> bool:
    """ONE in-flight turn per account: session advisory try-lock.
    Also single-flights concurrent first submissions of one command
    — the loser 429s, retries, and hits the stored result."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_turn_lock_key(account_id),))
            return bool(cur.fetchone()[0])


def _release_turn_lock(conn, account_id: str) -> None:
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_turn_lock_key(account_id),))
    except Exception:
        pass  # session teardown (connection close) releases advisory locks anyway


def _client_ip(request: Request) -> str:
    """The address the nearest trusted proxy saw. Each proxy appends to
    X-Forwarded-For, so the left end is whatever the client typed; with N trusted
    hops (Railway's edge is one) the real address is the Nth entry from the right.
    Zero hops ignores the header (direct exposure, local runs)."""
    try:
        hops = max(0, int(os.environ.get("EVERQUILL_TRUSTED_PROXY_HOPS", "1")))
    except ValueError:  # a typo must not 500 every claim; Railway's edge is one hop
        hops = 1
    entries = [e.strip() for e in request.headers.get("x-forwarded-for", "").split(",")]
    entries = [e for e in entries if e]
    if hops > 0 and len(entries) >= hops:
        return entries[-hops]
    return request.client.host if request.client else "unknown"


def _enforce_claim_gates(conn, request: Request) -> None:
    """Fixed-window per-IP + global throttles on the public claim endpoint.
    Uniform System-voice 429 — no distinction that helps guessing."""
    per_ip = int(os.environ.get("EVERQUILL_CLAIM_RATE_PER_MIN", "5"))
    verdict = ratelimit.hit(
        conn, f"claim:ip:{_client_ip(request)}", limit=per_ip, window_seconds=60
    )
    if not verdict.allowed:
        raise _system_429(CLAIM_THROTTLED, verdict.retry_after_s)
    global_per_min = int(os.environ.get("EVERQUILL_CLAIM_RATE_GLOBAL_PER_MIN", "30"))
    verdict = ratelimit.hit(conn, "claim:global", limit=global_per_min, window_seconds=60)
    if not verdict.allowed:
        raise _system_429(CLAIM_THROTTLED, verdict.retry_after_s)


# --- open endpoints ----------------------------------------------------------------


@app.get("/api/hello")
def hello() -> dict[str, str]:
    return {
        "service": "quilltouched",
        "status": "alive",
        "message": "<<The Quill acknowledges you.>>",
    }


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


@app.get("/readyz", response_class=PlainTextResponse)
def readyz() -> PlainTextResponse:
    """Readiness (distinct from /healthz liveness): 503 when the fail-closed
    secure gate refuses this runtime — missing master key or an
    owner/superuser runtime connection under EVERQUILL_REQUIRE_SECURE=1. 200
    otherwise (including dev, where the gate is a lenient no-op)."""
    if ENGINE.admin_url() is not None and not ENGINE.bootstrapped:
        try:
            ENGINE.ensure_bootstrap()
        except Exception:  # readiness reports, never crashes
            pass
    error = ENGINE.check_secure()
    if error is not None:
        return PlainTextResponse(f"not ready: {error}", status_code=503)
    return PlainTextResponse("ready")


# --- accounts ----------------------------------------------------------------------


@app.post("/api/claim")
def claim(request: Request, body: Annotated[dict[str, Any], Body()]):
    unknown = set(body) - {"invite_code", "mode"}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown fields: {', '.join(sorted(unknown))} "
                "(body is {invite_code, mode?})"
            ),
        )
    invite_code = body.get("invite_code")
    if not isinstance(invite_code, str) or not invite_code.strip():
        raise HTTPException(status_code=422, detail="invite_code must be a non-empty string")
    mode = body.get("mode", accounts_mod.AUTO_CHARGEN_MODE)
    if not isinstance(mode, str) or mode not in accounts_mod.CHARGEN_MODES:
        raise HTTPException(
            status_code=422,
            detail="mode must be 'auto' or 'guided' when provided",
        )

    _, url = _require_engine()
    with connect(url) as conn:
        _enforce_claim_gates(conn, request)
        try:
            account, device_token = accounts_mod.claim(conn, invite_code, chargen_mode=mode)
        except accounts_mod.InviteCodeError:
            # UNIFORM for unknown AND already-claimed codes:
            # a distinct used-code status was a validity oracle.
            raise HTTPException(
                status_code=403,
                detail="<<The Quill does not know that word.>>",
            ) from None
    return {
        "device_token": device_token,
        "account_id": account.account_id,
        "world_id": account.world_id,
        "message": "<<A fresh volume is opened in your name. This device holds its key.>>",
    }


class _ChargenAlreadyExists(Exception):
    """Control-flow marker: guided chargen was requested after character_created."""


class _BadChargenAssignment(Exception):
    """Control-flow marker carrying build_character's validation message."""

    def __init__(self, detail: str) -> None:
        self.detail = detail


def _require_bearer(request: Request, endpoint: str) -> str:
    token = _bearer_token(request)
    if token is None:
        raise HTTPException(
            status_code=401,
            detail=f"Authorization: Bearer <token> required for {endpoint}",
        )
    return token


def _assignment_body(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="assignment must be an object")
    assignment: dict[str, int] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            raise HTTPException(status_code=422, detail="assignment keys must be strings")
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise HTTPException(
                status_code=422,
                detail="assignment values must be integer pool indexes",
            )
        assignment[key] = raw
    return assignment


@app.get("/api/chargen/pool")
def chargen_pool(request: Request):
    """Authed guided-dice pool for this account's world.

    Returns 503 once character_created exists, including ordinary auto-claimed
    worlds. The response intentionally excludes die faces; the fixed client
    contract only needs assignable index + total.
    """
    world_content, url = _require_engine()
    token = _require_bearer(request, "/api/chargen/pool")
    with connect(url) as conn:
        account = _require_account(conn, token)
        _enter_account_world(conn, account, world_content)
        status = read_chargen_status(conn, world_content, PC_ID)
        if status.character_exists:
            raise HTTPException(status_code=503, detail="character already created")
        values = [
            {"index": value.index, "total": value.total}
            for value in roll_pool(status.seed, PC_ID)
        ]
        return {"world": account.world_id, "values": values}


@app.post("/api/chargen")
def chargen(request: Request, body: Annotated[dict[str, Any], Body()]):
    """Append guided character_created exactly once.

    Idempotency choice: after character_created exists, a repeat POST returns
    409 Conflict. The fixed store command id (chargen:pc) also absorbs duplicate
    append races so the event can only land once.
    """
    token = _require_bearer(request, "/api/chargen")
    unknown = set(body) - {"name", "assignment"}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown fields: {', '.join(sorted(unknown))} "
                "(body is {name, assignment})"
            ),
        )
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=422, detail="name must be a non-empty string")
    # The name is canon for good (chargen happens once) and reaches the parser
    # and narrator, so it gets the client's own limits here too (audit
    # 2026-10-24, claude #5): 40 characters, no control characters.
    if any(not ch.isprintable() for ch in name):  # newlines and tabs included
        raise HTTPException(
            status_code=422,
            detail=f"name must be at most {CHARACTER_NAME_MAX} printable characters",
        )
    name = " ".join(name.split())
    if len(name) > CHARACTER_NAME_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"name must be at most {CHARACTER_NAME_MAX} printable characters",
        )
    assignment = _assignment_body(body.get("assignment"))

    world_content, url = _require_engine()
    with connect(url) as conn:
        account = _require_account(conn, token)
        _enter_account_world(conn, account, world_content)
        start = starting_location(world_content)

        def chargen_fn(state):
            if state.world is None:
                raise ValueError("genesis must land before chargen")
            if PC_ID in state.characters:
                raise _ChargenAlreadyExists
            try:
                rolled = build_character(
                    state.world["seed"],
                    PC_ID,
                    name=name.strip(),
                    assignment=assignment,
                )
            except ValueError as exc:
                raise _BadChargenAssignment(str(exc)) from exc
            return chargen_events(
                rolled,
                location_id=start.id,
                region=start.region,
                world_time=state.world["world_time"],
            )

        try:
            result = execute_command(conn, f"chargen:{PC_ID}", chargen_fn)
        except _ChargenAlreadyExists:
            raise HTTPException(status_code=409, detail="character already created") from None
        except _BadChargenAssignment as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from None
        if result.absorbed:
            raise HTTPException(status_code=409, detail="character already created")
        return {"world_id": account.world_id}


# --- scene ---------------------------------------------------------------------------


@app.get("/api/scene")
def scene(request: Request, world: str | None = None):
    """Perceived scene manifest (KnownState surface — no sheets, no stats).

    With a Bearer token: YOUR world. Without one: the legacy shared world,
    which stays readable for now (interface decision 1)."""
    world_content, url = _require_engine()
    token = _bearer_token(request)

    with connect(url) as conn:
        if token is not None:
            account = _require_account(conn, token)
            if world is not None:
                _check_world_id(world, account.world_id)
            _enter_account_world(conn, account, world_content)
            known = read_known_state(conn, world_content)
            return _scene_response(known, account.world_id)

        # Legacy shared world (public schema): read-only.
        if world is None:
            raise HTTPException(status_code=422, detail="world query parameter required")
        _check_world_id(world, ENGINE.world_id or "")
        if ENGINE.content_drift is not None:
            raise HTTPException(
                status_code=503,
                detail="authored content drift on the legacy world (MEDIUM-7)",
            )
        known = read_known_state(conn, world_content)
        return _scene_response(known, world)


# --- the Codex: Inquiry fact cards + hypothesis pinboard --------------------


@app.get("/api/self")
def self_endpoint(request: Request, world: str | None = None):
    """The player's Self view (The Self & The Social): their own build
    (they know it) plus their EARNED standing — disposition per known NPC,
    standing per town, renown — each with a legible descriptor. Per-account, so
    a Bearer token is required."""
    world_content, url = _require_engine()
    token = _bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="authentication required for /api/self")
    with connect(url) as conn:
        account = _require_account(conn, token)
        if world is not None:
            _check_world_id(world, account.world_id)
        _enter_account_world(conn, account, world_content)
        me = read_self(conn, world_content, PC_ID)
        if me is None:
            raise HTTPException(status_code=503, detail="world not initialized (no PC yet)")
        return _self_response(me, account.world_id)


@app.get("/api/codex")
def codex_view(request: Request, subject: str | None = None, source: str | None = None):
    """The player's Inquiry claims as Codex fact cards (KnownState surface —
    no true values) plus the locations the player has seen. Authed only.

    Optional `subject`/`source` filters (client sends them as a forward hook;
    the client also filters locally, so ignoring them would be harmless) are
    applied server-side here: `subject` matches subject_entity_id, `source`
    is a case-insensitive substring of the provenance source."""
    world_content, url = _require_engine()
    token = _bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")

    with connect(url) as conn:
        account = _require_account(conn, token)
        _enter_account_world(conn, account, world_content)
        known = read_known_state(conn, world_content)
        labels = _subject_labels(known)
        claims = known.inquiry_claims(PC_ID, subject)
        if source:
            needle = source.lower()
            claims = tuple(c for c in claims if needle in (c.source or "").lower())
        return {
            "world_id": account.world_id,
            "world_date": known.world_date,
            "claims": [_codex_claim(c, labels) for c in claims],
            "known_locations": _known_locations(conn, world_content, known),
        }


@app.post("/api/hypothesis")
def hypothesis(request: Request, body: Annotated[dict[str, Any], Body()]):
    """Pin >=1 Inquiry claim ids (+ an optional note) -> research-target
    suggestions (C's pure `codex.evaluate_hypothesis`). Authed. Stateless:
    the pinboard lives in the client; this resolves which subject a fresh
    Inquiry would confirm/deny and pre-seeds the composer text. Claim ids the
    player does not hold are ignored (no existence oracle)."""
    token = _bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")
    unknown = set(body) - {"world", "claim_ids", "note"}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown fields: {', '.join(sorted(unknown))} "
            "(body is {world?, claim_ids, note?})",
        )
    claim_ids = body.get("claim_ids")
    if (
        not isinstance(claim_ids, list)
        or not claim_ids
        or not all(isinstance(c, str) for c in claim_ids)
    ):
        raise HTTPException(
            status_code=422, detail="claim_ids must be a non-empty list of claim id strings"
        )
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise HTTPException(status_code=422, detail="note must be a string or omitted")

    world_content, url = _require_engine()
    with connect(url) as conn:
        account = _require_account(conn, token)
        if body.get("world") is not None:
            _check_world_id(body["world"], account.world_id)
        _enter_account_world(conn, account, world_content)
        known = read_known_state(conn, world_content)
        by_id = {c.claim_id: c for c in known.inquiry_claims(PC_ID)}
        # preserve the player's pin order; drop ids they do not hold
        pinned = [by_id[cid] for cid in claim_ids if cid in by_id]
        pinned_dicts = [
            {
                "claim_id": c.claim_id,
                "subject_entity_id": c.subject_entity_id,
                "claim_text": c.claim_text,
                "source": c.source,
                "world_date": c.world_date,
                "confidence": c.confidence,
                # C's helper reads a list; the engine links contested pairs both ways
                "contradiction_ids": (
                    [c.contested_by_claim_id] if c.contested_by_claim_id else []
                ),
            }
            for c in pinned
        ]
        labels = _subject_labels(known)
        evaluation = codex.evaluate_hypothesis(pinned_dicts, labels=labels)

    target = evaluation["research_target"]
    research_targets: list[dict[str, Any]] = []
    if target is not None:
        research_targets.append(
            {
                "label": labels.get(target, target),
                "seed_text": evaluation["suggested_prompt"],
            }
        )
    return {"research_targets": research_targets}


# --- the turn pipeline ----------------------------------------------------------------


def _narrate_turn(
    conn,
    account: accounts_mod.Account,
    world_content: WorldContent,
    contract: dict[str, Any],
    intent: dict | None,
    command_id: str,
) -> tuple[str | None, dict[str, Any]]:
    """Post-commit synchronous narration (decision 3). Never raises.

    Every narration passes the deterministic admissibility gate
    (llm/narration_gate.py) before it is returned. On a gate failure: log,
    ONE re-narrate attempt with the violations as quoted data in a correction,
    then deterministic fallback prose built from the committed outcome.
    A hard LLM failure on the FIRST attempt keeps decision-3 behavior
    (outcome ships with narration null)."""
    meta: dict[str, Any] = {}
    try:
        t0 = time.perf_counter()
        known = read_known_state(conn, world_content)
        last = context_mod.last_resolution_trace(conn, int(contract["event_id"]))
        view = context_mod.build_view(
            known, world_path=_world_path(), last_resolution=last
        )
        assembled = context_mod.assemble_within_cap(view)
        assemble_ms = int((time.perf_counter() - t0) * 1000)
        meta = {
            "assembler_version": assembled.receipt["assembler_version"],
            "content_hash": assembled.content_hash,
        }
        # The prose is bound to its outcome as canon in
        # `_resolved_response` (store.narrate_outcome), after this returns —
        # here we only surface assembler_version + content_hash in telemetry.
        telemetry.emit(
            "assemble",
            command_id=command_id,
            world_id=account.world_id,
            event_id=contract["event_id"],
            latency_ms=assemble_ms,
            context_tokens=assembled.receipt["total_tokens"],
            **meta,
        )
    except Exception as exc:
        telemetry.emit(
            "narration_error",
            command_id=command_id,
            world_id=account.world_id,
            stage="assemble",
            error=f"{type(exc).__name__}: {exc}",
        )
        return None, meta

    if _plain_narrator():
        # No model: the engine's own plain account, recorded like any narration.
        meta["gate"] = "plain"
        return narration_gate.fallback_prose(contract, pc_id=PC_ID), meta

    # The narrator sees unlearned people by alias only, never an id that
    # spells their name; the gate checks the prose against the same payloads.
    aliases = context_mod.fogged_aliases(known, world_content)
    envelope = stamp_content_hash(
        context_mod.alias_payload(assembled.envelope, aliases)
    )
    meta["content_hash"] = envelope["assembly"]["content_hash"]
    unlearned = context_mod.unlearned_names(world_content, aliases)
    told = context_mod.alias_payload(contract, aliases)
    action = context_mod.alias_payload(context_mod.action_slice(intent or {}), aliases)
    violations: tuple[str, ...] = ()
    for attempt in (1, 2):
        if attempt == 1:
            prose, usage, err = llm_gateway.narrate_outcome(envelope, told, action)
        else:
            prose, usage, err = llm_gateway.narrate_outcome(
                envelope,
                told,
                action,
                corrective=narration_gate.corrective_line(violations),
            )
        if usage is not None:
            telemetry.emit(
                "llm_stage",
                command_id=command_id,
                world_id=account.world_id,
                **usage.as_fields(),
            )
            llm_gateway.record_usage(
                conn,
                usage,
                account_id=account.account_id,
                world_id=account.world_id,
                command_id=command_id,
            )
        if err is not None:
            telemetry.emit(
                "narration_error",
                command_id=command_id,
                world_id=account.world_id,
                stage="narrate",
                error=err,
            )
        if usage is not None:
            meta["model"] = usage.model  # recorded on the canonical turn record
        if prose is None:
            if attempt == 1:
                return None, meta  # pure LLM failure — decision 3, no fallback
            break  # retry after a gate failure died too -> fallback
        violations = narration_gate.check_narration(
            prose, outcome=told, envelope=envelope, action=action,
            unlearned_names=unlearned,
        )
        if not violations:
            meta["gate"] = "pass" if attempt == 1 else "regenerated"
            return prose, meta
        telemetry.emit(
            "narration_gate",
            command_id=command_id,
            world_id=account.world_id,
            event_id=contract["event_id"],
            attempt=attempt,
            violations=list(violations),
        )

    meta["gate"] = "fallback"
    meta["gate_violations"] = list(violations)
    return narration_gate.fallback_prose(contract, pc_id=PC_ID), meta


def _plain_narrator() -> bool:
    """``EVERQUILL_NARRATOR=plain``: narrate every turn with the engine's plain
    account (narration_gate.fallback_prose) and never call the model. Free, so
    the paid-layer budget does not gate it. For keyless local runs and the
    browser check, which then exercises recorded turns and /api/turns."""
    return os.environ.get("EVERQUILL_NARRATOR", "").strip().lower() == "plain"


def _wounds_after(known, contract: dict[str, Any]) -> dict[str, str]:
    """Post-resolution wound WORDS for entities named in the contract's hp
    deltas, so the public outcome can distinguish a kill (`dispatched`) from a
    wound. Reads only KnownState-safe words — never a raw hp number."""
    try:
        scene = known.scene(PC_ID)
    except KeyError:
        return {}
    conditions = {e.entity_id: set(e.conditions) for e in scene.entities}
    out: dict[str, str] = {}
    for delta in contract.get("state_deltas", []):
        if delta.get("delta_type") == "hp":
            entity = delta.get("entity_id")
            if "dispatched" in conditions.get(entity, ()):
                out[entity] = "dispatched"
    return out


def _dispatched_now(
    conn, world_content: WorldContent, contract: dict[str, Any]
) -> dict[str, str]:
    """``dispatched`` for every entity in the contract's hp deltas that is dead
    now, read from entity_state rather than the current scene, so a retry made
    after the player moved on still reads a kill as a kill."""
    targets = {
        d.get("entity_id") for d in contract.get("state_deltas", []) if d.get("delta_type") == "hp"
    }
    dotted = {contract_id(e): e for e in world_content.entities if contract_id(e) in targets}
    if not dotted:
        return {}
    # Killed BY THIS TURN: dead now, and this outcome was the last event to
    # touch it (nothing changes a body's hp afterwards), so a turn that only
    # wounded still reads "wounded" after a later kill (third audit F12).
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT entity_id FROM entity_state WHERE entity_id = ANY(%s) AND hp <= 0"
            " AND updated_from_event_id = %s",
            (list(dotted.values()), int(contract["event_id"])),
        )
        dead = {row[0] for row in cur.fetchall()}
    return {cid: "dispatched" for cid, eid in dotted.items() if eid in dead}


def _insert_test_turn_capture(
    conn,
    *,
    account: accounts_mod.Account,
    command_id: str,
    kind: str,
    world_time: int,
    source_utterance: str | None,
    committed_intent: dict[str, Any] | None,
    contract: dict[str, Any],
    narration: str | None,
    system_note: str | None,
) -> None:
    from psycopg.types.json import Jsonb

    intent = committed_intent if isinstance(committed_intent, dict) else {}
    target_entity_ids = intent.get("target_entity_ids")
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO public.test_turn_capture
                (world_id, command_id, kind, world_time, utterance, action_type,
                 target_entity_ids, approach, pending_confirmation, tier_resolved,
                 outcome_tier, state_deltas, narration, system_note)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                account.world_id,
                command_id,
                kind,
                world_time,
                source_utterance,
                intent.get("action_type"),
                Jsonb(target_entity_ids) if target_entity_ids is not None else None,
                intent.get("approach"),
                False,
                contract.get("tier_resolved"),
                contract.get("outcome_tier"),
                Jsonb(contract.get("state_deltas", [])),
                narration,
                system_note,
            ),
        )


def _resolved_response(
    conn,
    account: accounts_mod.Account,
    world_content: WorldContent,
    command_id: str,
    result,
    intent: dict | None,
    *,
    narrate_allowed: bool,
    turn_kind: str,
    source_utterance: str | None = None,
) -> JSONResponse:
    outcome_row = result.append_result.event_rows[result.resolution.outcome_event_index]
    raw = outcome_contract(outcome_row)
    # The client and the narrator see ONLY the redacted public view;
    # exact hp/internal flags remain in the canonical event server-side.
    known = read_known_state(conn, world_content)  # post-resolution image
    contract = _validated_contract(
        conn, outcome_public(raw, wounds_after=_wounds_after(known, raw)), command_id
    )
    committed_intent = _committed_intent(result.append_result.event_rows, intent)

    # DEGRADE-NOT-BLOCK: the deed already committed above. Narration
    # is the PAID layer — when the daily/spend budget is spent we skip it (no
    # assemble, no model call) and ship the outcome with narration:null + a
    # System note. The engine turn never waited on the budget.
    system_note: str | None = None
    if contract.get("movement_blocked"):
        narration, narration_meta = None, {"gate": "movement_blocked"}
        system_note = contract.get("system_note")
        telemetry.emit(
            "narration_movement_blocked",
            command_id=command_id,
            world_id=account.world_id,
            event_id=contract["event_id"],
        )
    elif narrate_allowed or _plain_narrator():
        narration, narration_meta = _narrate_turn(
            conn, account, world_content, contract, committed_intent, command_id
        )
    else:
        narration, narration_meta = None, {"gate": "degraded"}
        system_note = NARRATION_RESTING
        telemetry.emit(
            "narration_degraded",
            command_id=command_id,
            world_id=account.world_id,
            event_id=contract["event_id"],
        )

    # Narration-as-canon + canonical public-turn record: bind the
    # prose to its committed outcome AND persist the complete player-visible turn
    # (redacted outcome + prose + assembler meta) keyed by the TURN command_id.
    # Idempotent by narrate:<outcome ulid> — a re-narration is absorbed, so the
    # record survives response loss and a retry serves the SAME record (never a
    # re-resolved outcome). Guarded on content_hash so a narrator/gate failure
    # (narration None) records nothing rather than a half-bound entry.
    if narration is not None and narration_meta.get("content_hash"):
        try:
            narrate_outcome(
                conn,
                character_id=PC_ID,
                outcome_event_id=outcome_row["id"],
                outcome_event_ulid=outcome_row["event_ulid"],
                world_time=outcome_row["world_time"],
                prose=narration,
                assembler_version=narration_meta["assembler_version"],
                content_hash=narration_meta["content_hash"],
                location_id=outcome_row.get("location_id"),
                model=narration_meta.get("model"),
                turn_command_id=command_id,      # The client's turn id
                public_outcome=contract,         # The redacted outcome
            )
        except Exception as exc:  # canon never waits on the audit append
            telemetry.emit(
                "narration_error",
                command_id=command_id,
                world_id=account.world_id,
                stage="narrate_canon",
                error=f"{type(exc).__name__}: {exc}",
            )

    response_body = {
        "pending_confirmation": False,
        "absorbed": False,
        "world_id": account.world_id,
        "command_id": command_id,
        "intent": committed_intent,
        "assessment": asdict(result.assessment) if result.assessment else None,
        "outcome": contract,
        "narration": narration,
        "narration_meta": narration_meta or None,
        "system_note": system_note,
    }

    if account.test_capture:
        try:
            _insert_test_turn_capture(
                conn,
                account=account,
                command_id=command_id,
                kind=turn_kind,
                world_time=outcome_row["world_time"],
                source_utterance=source_utterance,
                committed_intent=committed_intent,
                contract=contract,
                narration=response_body["narration"],
                system_note=response_body["system_note"],
            )
        except Exception as exc:  # test capture never blocks the turn
            telemetry.emit(
                "test_turn_capture_error",
                command_id=command_id,
                world_id=account.world_id,
                error=f"{type(exc).__name__}: {exc}",
            )

    return JSONResponse(response_body)


def _absorbed_response(
    conn,
    account: accounts_mod.Account,
    world_content: WorldContent,
    store_command_id: str,
    command_id: str,
) -> JSONResponse:
    """Answer a duplicate/retry from CANON. If the turn was narrated,
    serve the canonical public-turn record WITH its prose — a retry after
    response loss returns the SAME record, never a re-resolved outcome and never
    ``narration: null`` for a turn that was in fact narrated. If no narration was
    recorded (LLM failure or a degraded paid layer), fall back to the committed
    outcome event with ``narration: null`` (the deed is still canon)."""
    record = public_turn(conn, command_id)
    if record is not None and record.get("public_outcome") is not None:
        contract = _validated_contract(conn, dict(record["public_outcome"]), command_id)
        return JSONResponse({
            "pending_confirmation": False,
            "absorbed": True,
            "world_id": account.world_id,
            "command_id": command_id,
            "intent": _stored_intent(conn, store_command_id),
            "assessment": None,
            "outcome": contract,
            "narration": record["prose"],       # The SAME prose, not null
            "narration_meta": {
                "assembler_version": record["assembler_version"],
                "content_hash": record["content_hash"],
                "model": record["model"],
                "gate": "canonical_record",
            },
            "system_note": None,
        })

    outcome_row = _stored_outcome_row(conn, store_command_id)
    if outcome_row is None:
        raise HTTPException(
            status_code=409,
            detail="command_id was already used but no outcome is on record",
        )
    # Rebuild the public view the first response served (audit 2026-10-24,
    # claude #17), reading deaths from entity state rather than the current
    # scene (claude-013) and only those this turn caused (F12). A degraded or
    # failed narration leaves no record of which, so only the movement-blocked
    # note comes back.
    raw = outcome_contract(outcome_row)
    contract = _validated_contract(
        conn,
        outcome_public(raw, wounds_after=_dispatched_now(conn, world_content, raw)),
        command_id,
    )
    return JSONResponse({
        "pending_confirmation": False,
        "absorbed": True,
        "world_id": account.world_id,
        "command_id": command_id,
        # Duplicates answer with the STORED parsed intent — the
        # canon record, never the retry's redeclaration.
        "intent": _stored_intent(conn, store_command_id),
        "assessment": None,
        "outcome": contract,
        "narration": None,  # no narration on record (LLM failure / degraded)
        "narration_meta": None,
        "system_note": contract.get("system_note") if contract.get("movement_blocked") else None,
    })


def _pending_stored_response(
    account: accounts_mod.Account,
    command_id: str,
    store_command_id: str,
    pending: dict[str, Any],
) -> JSONResponse:
    """A duplicate submission while a <<Proceed?>> beat is pending: answer
    from the STORED row (stored intent, stored assessment) without paying
    for a parse. Mirrors beat.py's idempotent-repeat shape
    (assessment.command_id carries the store-namespaced id, like the beat)."""
    return JSONResponse({
        "pending_confirmation": True,
        "world_id": account.world_id,
        "command_id": command_id,
        "intent": pending["intent"],
        "assessment": {
            "command_id": store_command_id,
            "character_id": pending["character_id"],
            "tier": pending["tier"],
            "risk_label": pending["risk_label"],
            "confirmation_required": True,
            "world_minutes_cost": pending["world_minutes_cost"],
            "created_world_time": pending["created_world_time"],
            "expires_world_time": pending["expires_world_time"],
            "summary": "<<Assessment stands. Proceed?>>",
        },
    })


def _turn_telemetry(request: Request, command_id: str, account, result, contract=None):
    turn: dict[str, Any] = {
        "command_id": command_id,
        "world_id": account.world_id,
        "status": result.status if result is not None else "error",
    }
    if result is not None and result.append_result is not None:
        turn["absorbed"] = result.append_result.absorbed
        turn["event_count"] = len(result.append_result.event_rows)
    if contract is not None:
        turn["event_id"] = contract["event_id"]
        turn["tier_resolved"] = contract["tier_resolved"]
        turn["outcome_tier"] = contract["outcome_tier"]
    request.state.turn = turn


@app.post("/api/action")
def action(request: Request, body: Annotated[dict[str, Any], Body()]):
    """The turn pipeline: validate -> (parse) -> beat -> resolve -> narrate.

    Body: {command_id, intent} for structured intents (canned suggestions),
    or {command_id, text} for typed free text (parser p9, haiku, temp 0,
    strict tool). ``world`` optional; must match the token's world.
    Dire-and-up intents return {pending_confirmation: true, assessment}
    without resolving — POST /api/action/confirm commits them.
    """
    token = _bearer_token(request)
    if token is None:
        # The old unauthed shared world takes no new actions (decision 1).
        raise HTTPException(status_code=410, detail=SHARED_WORLD_SEALED)

    unknown = set(body) - {"world", "command_id", "intent", "text"}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown fields: {', '.join(sorted(unknown))} "
            "(body is {world?, command_id, intent | text})",
        )
    if "command_id" not in body:
        raise HTTPException(status_code=422, detail="missing field: command_id")
    command_id = _validate_command_id(body["command_id"])
    has_intent, has_text = "intent" in body, "text" in body
    if has_intent == has_text:
        raise HTTPException(
            status_code=422,
            detail="send exactly one of: intent (structured) or text (free text)",
        )

    world_content, url = _require_engine()

    with connect(url) as conn:
        account = _require_account(conn, token)
        if body.get("world") is not None:
            _check_world_id(body["world"], account.world_id)
        _enter_account_world(conn, account, world_content)

        # --- one in-flight turn per account (single-flight) ---
        if not _acquire_turn_lock(conn, account.account_id):
            raise _system_429(TURN_IN_FLIGHT, 2)
        try:
            store_command_id = f"action:{command_id}"

            # --- probe BEFORE any paid parse: duplicates answer
            # from storage — stored outcome or stored pending assessment,
            # with the STORED parsed intent — and skip every gate below.
            state, pending = _probe_command_state(conn, store_command_id)
            if state == "committed":
                response = _absorbed_response(
                    conn, account, world_content, store_command_id, command_id
                )
                request.state.turn = {
                    "command_id": command_id,
                    "world_id": account.world_id,
                    "status": "absorbed",
                    "probe": True,
                }
                return response
            if state == "pending":
                request.state.turn = {
                    "command_id": command_id,
                    "world_id": account.world_id,
                    "status": "pending",
                    "probe": True,
                }
                return _pending_stored_response(
                    account, command_id, store_command_id, pending
                )
            if state == "expired":
                raise HTTPException(status_code=410, detail=MOMENT_PASSED)

            # --- cheap validation first, so a malformed request never spends a
            # paid turn (audit 2026-10-24, k3 F7). A parsed intent is validated
            # again after the parse, below.
            if has_text:
                text = body["text"]
                if not isinstance(text, str) or not text.strip():
                    raise HTTPException(
                        status_code=422, detail="text must be a non-empty string"
                    )
                if len(text) > 2000:
                    raise HTTPException(
                        status_code=422, detail="text too long (max 2000 chars)"
                    )
            else:
                _check_intent_bytes(body["intent"])
                schema_errors = _intent_errors(body["intent"])
                if schema_errors:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "intent_schema_violations": schema_errors,
                            "intent": body["intent"],
                        },
                    )

            # --- fresh command: reserve the PAID budget ONCE.
            # Degrade-not-block: this never gates the deterministic engine —
            # a structured (tapped) intent ALWAYS resolves. Only the paid
            # layers degrade: free text needs the paid parser, so it 429s to
            # require a tapped action when the budget is spent; narration is
            # skipped later (narration:null + System note) via narrate_allowed.
            budget = _reserve_paid_budget(conn, account, has_text=has_text)
            if has_text and not budget.parse_allowed:
                raise _system_429(budget.block_line, budget.retry_after_s)

            # --- stage: parse (only for free text; structured intents skip it) ---
            if has_text:
                source_utterance = text.strip()
                known = read_known_state(conn, world_content)
                try:
                    aliases = context_mod.fogged_aliases(known, world_content)
                    roster = context_mod.roster_text(known, world_content, aliases)
                    lists = context_mod.parse_lists(known, world_content, aliases)
                except KeyError:
                    raise HTTPException(
                        status_code=503, detail="world not initialized (no PC yet)"
                    ) from None
                def parse_once(correction: str | None = None) -> dict[str, Any]:
                    try:
                        parsed, parse_usage = llm_gateway.parse_free_text(
                            source_utterance, roster, lists,
                            **({"correction": correction} if correction else {}),
                        )
                    except llm_gateway.ParseInputTooLarge as exc:
                        telemetry.emit(
                            "parse_error", command_id=command_id,
                            world_id=account.world_id, error=str(exc),
                        )
                        raise HTTPException(
                            status_code=422,
                            detail="<<The declaration overflows the page. Say less.>>",
                        ) from None
                    except llm_gateway.ParseFailure as exc:
                        telemetry.emit(
                            "parse_error", command_id=command_id,
                            world_id=account.world_id, error=str(exc),
                        )
                        if exc.usage is not None:  # billed even though it failed
                            llm_gateway.record_usage(
                                conn, exc.usage, account_id=account.account_id,
                                world_id=account.world_id, command_id=command_id,
                            )
                        raise HTTPException(
                            status_code=502,
                            detail="<<The Quill mis-hears you. Say it again, or tap a "
                            "suggested action.>>",
                        ) from None
                    telemetry.emit(
                        "llm_stage", command_id=command_id, world_id=account.world_id,
                        **parse_usage.as_fields(),
                    )
                    llm_gateway.record_usage(
                        conn, parse_usage, account_id=account.account_id,
                        world_id=account.world_id, command_id=command_id,
                    )
                    parsed = context_mod.unalias_intent(parsed, aliases)
                    return _clamp_parsed_intent(parsed, command_id, account.world_id)

                intent = parse_once()
                violations = _intent_errors(intent)
                if violations:
                    # A provider that does not enforce the strict tool schema
                    # (OpenRouter, 25 Oct 2026: about one parse in 75) can return a
                    # field outside the contract. Ask once more, saying what was
                    # wrong, before refusing the player.
                    telemetry.emit(
                        "parse_schema_retry", command_id=command_id,
                        world_id=account.world_id, violations=violations[:3],
                    )
                    intent = parse_once(
                        "Your previous answer broke the output contract: "
                        + json.dumps(violations[:5])
                        + ". Answer again with every field inside the schema."
                    )
            else:
                intent = body["intent"]
                source_utterance = None

            _check_intent_bytes(intent)  # Byte cap BEFORE schema work
            schema_errors = _intent_errors(intent)
            if schema_errors:
                raise HTTPException(
                    status_code=422,
                    detail={"intent_schema_violations": schema_errors, "intent": intent},
                )

            # --- stage: beat (assess -> auto-commit | pending confirmation) ---
            try:
                result = assess_or_execute(
                    conn, store_command_id, intent,
                    world=world_content, character_id=PC_ID,
                )
            except ConfirmationExpiredError:
                raise HTTPException(status_code=410, detail=MOMENT_PASSED) from None
            except BeatIntentMismatchError as exc:
                # This command_id is bound to a different pending
                # action. Return the STORED intent (what confirmation will
                # actually resolve), never the retry's redeclaration.
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "intent_mismatch",
                        "message": "this command was already assessed for a different "
                        "action: confirm the standing assessment, or declare again "
                        "under a fresh command_id",
                        "stored_intent": exc.stored_intent,
                    },
                ) from None
            except ResolverError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except ConcurrencyError:
                raise HTTPException(
                    status_code=409,
                    detail="concurrent writer advanced the stream twice — retry",
                ) from None
            except ValueError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

            if result.status == "pending":
                _turn_telemetry(request, command_id, account, result)
                return JSONResponse({
                    "pending_confirmation": True,
                    "world_id": account.world_id,
                    "command_id": command_id,
                    # The intent BOUND to this pending beat (the one
                    # confirmation resolves), never the retry's redeclaration.
                    "intent": result.stored_intent or intent,
                    "assessment": asdict(result.assessment),
                })
            if result.status == "absorbed":
                response = _absorbed_response(
                    conn, account, world_content, store_command_id, command_id
                )
                _turn_telemetry(request, command_id, account, result)
                return response

            # --- resolved: outcome contract + synchronous narration (decision 3) ---
            response = _resolved_response(
                conn, account, world_content, command_id, result, intent,
                narrate_allowed=budget.narrate_allowed,
                turn_kind="action",
                source_utterance=source_utterance,
            )
            contract = outcome_public(outcome_contract(
                result.append_result.event_rows[result.resolution.outcome_event_index]
            ))
            _turn_telemetry(request, command_id, account, result, contract)
            return response
        finally:
            _release_turn_lock(conn, account.account_id)


@app.post("/api/action/confirm")
def action_confirm(request: Request, body: Annotated[dict[str, Any], Body()]):
    """Resolve a pending <<Proceed?>> beat under its ORIGINAL command_id.

    Dice draw now, against then-current counters (roll resolves inside the
    dialog). Expired beats 410 — never a stale resolution.
    """
    token = _bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")

    unknown = set(body) - {"world", "command_id"}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown fields: {', '.join(sorted(unknown))} (body is {{command_id}})",
        )
    if "command_id" not in body:
        raise HTTPException(status_code=422, detail="missing field: command_id")
    command_id = _validate_command_id(body["command_id"])

    world_content, url = _require_engine()

    with connect(url) as conn:
        account = _require_account(conn, token)
        if body.get("world") is not None:
            _check_world_id(body["world"], account.world_id)
        _enter_account_world(conn, account, world_content)

        # --- one in-flight turn per account ---
        if not _acquire_turn_lock(conn, account.account_id):
            raise _system_429(TURN_IN_FLIGHT, 2)
        try:
            store_command_id = f"action:{command_id}"

            # Duplicate confirms answer from storage and skip the gates.
            state, _pending = _probe_command_state(conn, store_command_id)
            if state == "committed":
                response = _absorbed_response(
                    conn, account, world_content, store_command_id, command_id
                )
                request.state.turn = {
                    "command_id": command_id,
                    "world_id": account.world_id,
                    "status": "absorbed",
                    "probe": True,
                }
                return response

            # A fresh confirm resolves the ORIGINAL command: the
            # deterministic resolution ALWAYS runs — never blocked, and NEVER
            # re-charges the daily budget (the declaring /api/action already
            # reserved it once; the confirm double-count is gone). Only the
            # paid narrator degrades: a READ-ONLY budget check, no increment.
            narrate_ok, _line, _retry = _cost_budget_status(conn, account)

            try:
                result = beat_confirm(conn, store_command_id, world=world_content)
            except NoPendingConfirmationError:
                raise HTTPException(
                    status_code=404,
                    detail="no pending confirmation for this command: declare the "
                    "action first (POST /api/action)",
                ) from None
            except ConfirmationExpiredError:
                raise HTTPException(status_code=410, detail=MOMENT_PASSED) from None
            except ResolverError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except ConcurrencyError:
                raise HTTPException(
                    status_code=409,
                    detail="concurrent writer advanced the stream twice — retry",
                ) from None
            except ValueError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

            if result.status == "absorbed":
                response = _absorbed_response(
                    conn, account, world_content, store_command_id, command_id
                )
                _turn_telemetry(request, command_id, account, result)
                return response

            response = _resolved_response(
                conn, account, world_content, command_id, result, None,
                narrate_allowed=narrate_ok,
                turn_kind="confirm",
                source_utterance=None,
            )
            contract = outcome_public(outcome_contract(
                result.append_result.event_rows[result.resolution.outcome_event_index]
            ))
            _turn_telemetry(request, command_id, account, result, contract)
            return response
        finally:
            _release_turn_lock(conn, account.account_id)


# --- the Chronicle read (public-turn record client half) ---------------------------------------


@app.get("/api/turns")
def turns(request: Request, since: int | None = None, limit: int = 50):
    """The player's recent canonical public-turn records for a client Chronicle
    reconnect/rebuild. Authed. Each record is the SAME canon the
    turn pipeline served — redacted public outcome + prose + assembler meta —
    so a reload rebuilds the visible history without re-resolving anything.

    Query: ``limit`` (default 50, max 200) newest turns, oldest-first;
    ``since`` (a ``narration_event_id`` watermark) returns the oldest ``limit``
    turns strictly newer than it, for an incremental catch-up: a full page
    means call again with the new watermark. Returns ``{world_id,
    world_date, turns: [...]}`` — turn shape documented in docs/ops/turns-api.md
    (client contract). A turn with no narration on record (LLM failure /
    degraded) has no canonical record and is simply absent from the history."""
    token = _bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")
    limit = max(1, min(int(limit), 200))

    world_content, url = _require_engine()
    with connect(url) as conn:
        account = _require_account(conn, token)
        _enter_account_world(conn, account, world_content)
        # read_known_state owns a top-level transaction (execute_command); take
        # the world_date FIRST, then the read-only recent_public_turns query
        # (which leaves an implicit tx the closing connection rolls back).
        known = read_known_state(conn, world_content)
        records = recent_public_turns(
            conn, PC_ID, limit, since=int(since) if since is not None else None
        )
    return {
        "world_id": account.world_id,
        "world_date": known.world_date,
        "turns": [_turn_record_response(r, command_id=r["turn_command_id"]) for r in records],
    }


def _turn_record_response(record: dict[str, Any], *, command_id: str) -> dict[str, Any]:
    """One canonical public-turn record -> the client Chronicle line shape
    (client contract, docs/ops/turns-api.md). ``narration_event_id`` is the
    watermark the client passes back as ``?since=`` for incremental catch-up."""
    return {
        "command_id": record["turn_command_id"],
        "outcome": record["public_outcome"],
        "narration": record["prose"],
        "narration_meta": {
            "assembler_version": record["assembler_version"],
            "content_hash": record["content_hash"],
            "model": record["model"],
            "gate": "canonical_record",
        },
        "narration_event_id": record["narration_event_id"],
        "world_time": record["world_time"],
    }


# --- ops ------------------------------------------------------------------------------


@app.get("/api/ops/usage")
def ops_usage(request: Request, days: int = 30):
    """Daily LLM cost rollup (stage x model). Auth: EVERQUILL_OPS_TOKEN."""
    expected = os.environ.get("EVERQUILL_OPS_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="EVERQUILL_OPS_TOKEN not configured")
    token = _bearer_token(request)
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="ops token required")
    days = max(1, min(days, 365))

    _, url = _require_engine()
    with connect(url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT (ts AT TIME ZONE 'utc')::date AS day, stage, model,
                           count(*) AS calls,
                           sum(input_tokens)::bigint,
                           sum(output_tokens)::bigint,
                           sum(cache_read_input_tokens)::bigint,
                           sum(cache_creation_input_tokens)::bigint,
                           round(avg(latency_ms))::int
                    FROM public.llm_usage
                    WHERE ts >= now() - make_interval(days => %s)
                    GROUP BY 1, 2, 3
                    ORDER BY 1 DESC, 2, 3
                    """,
                    (days,),
                )
                rows = cur.fetchall()
    days_out = []
    for r in rows:
        row = {
            "day": str(r[0]),
            "stage": r[1],
            "model": r[2],
            "calls": r[3],
            "input_tokens": int(r[4]),
            "output_tokens": int(r[5]),
            "cache_read_input_tokens": int(r[6]),
            "cache_creation_input_tokens": int(r[7]),
            "avg_latency_ms": r[8],
        }
        cost = _estimated_cost_usd(row)
        # Same rule as the spend breaker: an unpriced model is priced at the
        # dearest known rate, flagged, never counted as free (audit claude-008).
        row["priced_as_dearest"] = cost is None
        row["estimated_cost_usd"] = (
            cost if cost is not None else _estimated_cost_usd(row, prices=_DEAREST_PRICES)
        )
        days_out.append(row)
    total = round(sum(r["estimated_cost_usd"] for r in days_out), 6)
    return {"days": days, "rollup": days_out, "estimated_total_usd": total}
