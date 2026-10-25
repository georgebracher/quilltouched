"""KnownState -> assembler-view adapter fixes (Hardening Pass 1).

No DB: exercises the pure adapter mapping and the token-cap enforcement.

- PerceivedEntity.category (the coarse ENTITY_CATEGORIES vocab) reaches the
  view, NOT the fine-grained authored `kind` (the gate/narrator contract).
- Real contradiction_ids pass through instead of the old hardcoded [].
- assemble_within_cap enforces the assembler's declared final token cap even
  when pinned constraint-class claims would otherwise bust it.
"""

from __future__ import annotations

from types import SimpleNamespace

from api import context
from llm.assembler import TOTAL_CAP, assemble


def test_scene_category_uses_the_coarse_vocab_not_the_kind():
    entity = SimpleNamespace(
        entity_id="npc_harrowdown_maren", name="Maren", kind="npc", category="person",
        portrait=None, conditions=(), slot_id=None, x_pct=None, y_pct=None,
    )
    scene = SimpleNamespace(
        location_id="loc_x", name="X", location_type=None, region=None,
        world_date="t", entities=(entity,),
    )
    known = SimpleNamespace(scene=lambda _pc: scene)
    out = context._scene_dict(known)
    # Category contract: 'person' (npc + character), never 'npc'.
    assert out["entities"][0]["category"] == "person"


def test_roster_text_includes_known_state_exits():
    scene = SimpleNamespace(
        location_id="loc_harrowdown_tavern",
        name="The Drowned Ram",
        world_date="t",
        entities=(),
        exits=(
            SimpleNamespace(
                id="loc_harrowdown_market_row",
                name="Market Row",
                carriage_days=0,
            ),
        ),
    )
    facts = SimpleNamespace(inventory={})
    known = SimpleNamespace(
        scene=lambda _pc: scene,
        chronicle_facts=lambda _pc: facts,
    )
    roster = context.roster_text(known)
    assert "- loc_harrowdown_market_row: Market Row (a road leads there)" in roster


def test_claims_pass_real_contradiction_ids_through():
    claim = SimpleNamespace(
        claim_id="c1", subject_entity_id="s", claim_text="the ballads say X",
        value_or_range=None, source="ballads", observer=None, method="rumor",
        world_date="d", scope="harrowdown", confidence="uncorroborated",
        journal_flag=False, contradiction_ids=("c2", "c3"),
    )
    known = SimpleNamespace(inquiry_claims=lambda _pc: (claim,))
    out = context._claims(known)
    # was hardcoded [] (contested feature inert); now the real live contesters.
    assert out[0]["claim"]["contradiction_ids"] == ["c2", "c3"]


def _min_view(claims: list) -> dict:
    return {
        "scene": {"location_id": "loc_x", "label_known": "X",
                  "world_time": "t", "entities": []},
        "known_sheets": [],
        "claims": claims,
        "active_clocks": [],
        "canon_excerpts": [],
        "atmosphere": [],
        "recent_subjects": {},
        "last_resolution": None,
    }


def _pinned_claim(cid: str, text: str) -> dict:
    return {
        "claim": {
            "claim_id": cid, "subject_entity_id": "loc_x", "claim_text": text,
            "value_or_range": None, "source": "s", "observer": None,
            "method": "witnessed", "world_date": "d", "scope": "harrowdown",
            "confidence": "uncorroborated", "corroboration_ids": [],
            "contradiction_ids": [], "inheritance_status": "original",
        },
        "meta": {"world_hours_ago": 1, "half_life_class": "gossip",
                 "constraint_class": True},
    }


def test_assemble_within_cap_enforces_the_declared_final_token_cap():
    # Six oversized PINNED constraint-class claims — the assembler admits pinned
    # claims unconditionally, so the raw envelope busts its own declared cap.
    big = "x" * 3000
    claims = [_pinned_claim(f"c_pin{i}", f"OATH {i}: {big}") for i in range(6)]
    view = _min_view(claims)

    raw = assemble(view)
    assert raw.receipt["total_tokens"] > TOTAL_CAP  # the bug the audit flagged

    capped = context.assemble_within_cap(view)
    # The adapter's hard post-condition — the cap is now ENFORCED.
    assert capped.receipt["total_tokens"] <= TOTAL_CAP
    assert capped.envelope["token_budget"]["max_tokens"] == TOTAL_CAP


def test_assemble_within_cap_is_a_noop_when_already_in_cap():
    view = _min_view([])
    capped = context.assemble_within_cap(view)
    assert capped.receipt["total_tokens"] <= TOTAL_CAP
    # byte-identical to a plain assemble when nothing needs trimming
    assert capped.content_hash == assemble(view).content_hash
