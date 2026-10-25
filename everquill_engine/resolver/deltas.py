"""Delta builders: the typed state changes an outcome commits (claims,
coin, harm, deposits)."""

from __future__ import annotations

from typing import Any

from everquill_engine.claims import acquisition_for_method
from everquill_engine.clock import (
    world_date,
)
from everquill_engine.resolver.common import (
    CONVERSATION_PARTNER_FLAG,
    DESPERATE_COUNTERATTACK_GAP_DIVISOR,
    _is_present_npc,
)
from everquill_engine.world import SALE_PRICE_REASONS, WorldContent, sold_here

# --- delta builders -----------------------------------------------------------


def _claim(
    subject: str,
    text: str,
    *,
    predicate: str,
    source: str,
    method: str,
    world_time: int,
    scope: str,
    confidence: str,
    value_text: str | None = None,
    observer: str | None = None,
    source_agent: str | None = None,
    layer: str = "inquiry",
) -> dict[str, Any]:
    """One typed claim delta (schema v2): a closed ``predicate``
    plus typed value columns ride alongside the narrator-facing prose;
    ``acquisition_method`` derives from the site's method label via the
    one shared mapping. Claim contents NEVER embed raw player text —
    player-authored words live (encrypted) in intent_parsed only, so
    crypto-shredding never has to chase derived canon."""
    return {
        "delta_type": "intel",
        "claim": {
            "subject_entity_id": subject,
            "predicate": predicate,
            "value_text": value_text,
            "value_num": None,
            "value_range": None,
            "world_valid": None,
            "claim_text": text,
            "layer": layer,
            "source": source,
            "observer": observer,
            "method": method,
            "acquisition_method": acquisition_for_method(method),
            "source_agent_id": source_agent,
            "world_date": world_date(world_time),
            "scope": scope,
            "confidence": confidence,
        },
    }


def _hp(entity_id: str, amount: int, cause: str | None) -> dict[str, Any]:
    return {"delta_type": "hp", "entity_id": entity_id, "amount": amount, "cause": cause}


def _flag(entity_id: str, key: str, value: Any) -> dict[str, Any]:
    return {"delta_type": "flag", "entity_id": entity_id, "flag_key": key, "value": value}


def _conversation_partner_delta(
    *,
    actor: dict[str, Any],
    action: str,
    targets: list[str],
    move_to: str | None,
    world: WorldContent,
    manifest: dict[str, dict[str, Any]],
    entity_states: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Stored-fact update for sticky conversation state.

    Set when a dialogue/social action addresses exactly one present NPC (other
    non-person targets may be involved). Clear only when movement actually
    changes location. No idle timeout: non-conversation turns and explicit room
    speech leave the partner intact, which keeps the rule replay-safe and easy
    to audit.
    """
    actor_id = actor["entity_id"]
    current = (actor.get("flags") or {}).get(CONVERSATION_PARTNER_FLAG)
    if action == "movement" and move_to is not None and current:
        return _flag(actor_id, CONVERSATION_PARTNER_FLAG, None)
    if action not in {"dialogue", "social"}:
        return None
    actor_flags = actor.get("flags") or {}
    npc_targets = [
        target
        for target in targets
        if _is_present_npc(
            target,
            actor_location=actor.get("location_id"),
            actor_flags=actor_flags,
            world=world,
            manifest=manifest,
            entity_states=entity_states,
        )
    ]
    if len(npc_targets) != 1:
        return None
    partner = npc_targets[0]
    if current == partner:
        return None
    return _flag(actor_id, CONVERSATION_PARTNER_FLAG, partner)


def _coin_delta(
    actor: dict[str, Any], amount: int, reason: str
) -> dict[str, Any] | None:
    """Clamp a Chronicle-exact spend at the actor's current coin.

    Folds remain append-only arithmetic. The resolver emits the bounded delta so
    projection never crosses below zero, even if the player tries to overpay.
    """
    spend = min(max(int(amount), 0), max(int(actor.get("coin") or 0), 0))
    if spend <= 0:
        return None
    return {
        "delta_type": "coin",
        "entity_id": actor["entity_id"],
        "amount": -spend,
        "reason": reason,
    }


def _transaction_coin_delta(
    *,
    intent: dict[str, Any],
    actor: dict[str, Any],
    world: WorldContent,
) -> dict[str, Any] | None:
    """Chronicle-exact coin for a declared purchase or coin hand-over.

    Reads only the closed ``transaction`` field. A buy is priced from the
    world's price table, only for goods the engine sells (``SALE_PRICE_REASONS``)
    and only where they are on sale (``SALE_PLACES``); anything else spends
    nothing. A give_coin hands
    over that many coins. Haggling, vendor stock and NPC receipt accounting are
    a later economy system.
    """
    if intent.get("action_type") not in {"social", "rest"}:
        return None
    transaction = intent.get("transaction")
    if not isinstance(transaction, dict):
        return None
    count = int(transaction["count"])
    if transaction["kind"] == "give_coin":
        return _coin_delta(actor, count, "coin given")
    price_key = transaction.get("price_key")
    reason = SALE_PRICE_REASONS.get(price_key) if isinstance(price_key, str) else None
    if reason is None or price_key not in sold_here(world, actor.get("location_id")):
        return None  # not a good the engine sells, or not sold where you stand
    unit_price = int(world.prices.get(price_key, 1))
    return _coin_delta(actor, unit_price * count, reason)


def _clamped_self_harm(sheet: dict[str, Any], amount: int) -> int:
    """Clamp harm at command time so hp never drops below 1 (death is a
    later sprint) — the FOLD must stay blind, so the clamp happens here
    and the stored delta already carries the applied amount."""
    hp = sheet["hp"]
    applied = max(1, hp - amount)  # amount is positive harm
    return applied - hp  # negative or 0


def _desperate_counterattack_harm(gap: int) -> int:
    """TUNABLE Slice-3 danger bite for DESPERATE physical confrontations."""
    return max(1, gap // DESPERATE_COUNTERATTACK_GAP_DIVISOR)
