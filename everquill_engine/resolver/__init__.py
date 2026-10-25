"""The Referee: canned intent + projected state → tier → roll → outcome + events.

Pure module (no persistence, no LLM, no I/O). One call —
:func:`resolve_intent` — takes an intent dict conforming to
docs/contracts/intent.schema.json plus the projected state, and returns
the events to append and the Chronicle-facing summary. The store
commits events + Tier-1 projections in ONE transaction; the outcome
contract dict is rendered FROM the committed event row afterwards
(:func:`outcome_contract`), so narration can only ever bind to what the
log already says.

Tier decision (roadmap §3.1):
  authored law override (sealed/impossible, from world content)
  → else action-shape rules (meta/dialogue/rest/train/movement/untargeted
    observation are no-roll shapes)
  → else band_for_gap(max target threat_band − acting aptitude).

HOPELESS always misses; the roll picks the failure flavor (ladder.py).
Every miss deposits at least one delta (intel fragment, scar, or
journal-line hook) — enforced structurally in :func:`_ensure_deposit`.
Trivial: no roll, narrate-only event.

ID convention at the contract boundary: world-content ids are dotted
('npc.dev.mara'); the intent/outcome schemas allow only
^[a-z][a-z0-9_]*$. Contract ids are the dotted id with dots replaced by
underscores; the resolver resolves incoming contract ids against the
scene roster (small, so collisions are detectable) and rejects
ambiguity. Teams C/F: always source target ids from the scene-manifest
roster, which carries both forms.
"""

from __future__ import annotations

from everquill_engine.intent import ACTION_TYPES
from everquill_engine.resolver.common import (
    CONFIRMATION_REQUIRED_FOR_RISK,
    CONVERSATION_PARTNER_FLAG,
    DEFAULT_STAT_FOR_ACTION,
    DISCOVERY_FLAG_PREFIX,
    HIDDEN_TAG,
    KNOWS_NAME_PREFIX,
    UNTARGETED_DIFFICULTY,
    WEAK_POINT_ROLL_BONUS,
    Resolution,
    ResolverError,
    contract_id,
    discovery_flag,
    entity_hidden,
    is_perceptible,
    knows_name_flag,
    perceived_entity_label,
)
from everquill_engine.resolver.contract import (
    outcome_contract,
)
from everquill_engine.resolver.referee import (
    resolve_intent,
)
from everquill_engine.resolver.tier import (
    UNADDRESSABLE_TARGET,
    TierDecision,
    confirmation_required,
    decide_tier,
)

__all__ = [
    "ACTION_TYPES",
    "CONFIRMATION_REQUIRED_FOR_RISK",
    "CONVERSATION_PARTNER_FLAG",
    "DEFAULT_STAT_FOR_ACTION",
    "DISCOVERY_FLAG_PREFIX",
    "HIDDEN_TAG",
    "KNOWS_NAME_PREFIX",
    "Resolution",
    "ResolverError",
    "TierDecision",
    "UNADDRESSABLE_TARGET",
    "UNTARGETED_DIFFICULTY",
    "WEAK_POINT_ROLL_BONUS",
    "confirmation_required",
    "contract_id",
    "decide_tier",
    "discovery_flag",
    "entity_hidden",
    "is_perceptible",
    "knows_name_flag",
    "outcome_contract",
    "perceived_entity_label",
    "resolve_intent",
]
