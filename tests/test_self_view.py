"""The Self view.

Investigate yourself and get back who you are — your own build (you know it,
unlike an NPC's hidden true sheet) and your EARNED standing, resolved to names
and narrative descriptors. Pure over the Tier-1 fold.
"""

from __future__ import annotations

from everquill_engine.folds import FoldState
from everquill_engine.views import self_view


def _sheet(**over):
    base = {
        "entity_id": "pc", "name": "Ash", "origin": "quill_touched_stranger",
        "aptitudes": {"might": 7, "finesse": 6, "wits": 8, "will": 7,
                      "presence": 11, "lore": 9},
        "hp": 11, "hp_max": 11, "coin": 30, "location_id": "loc.harrowdown.tavern",
        "inventory": {}, "flags": {}, "titles": [], "last_event_id": 1,
    }
    base.update(over)
    return base


def _state():
    st = FoldState()
    st.characters["pc"] = _sheet()
    st.manifest["npc.harrowdown.jorun_pike"] = {
        "entity_id": "npc.harrowdown.jorun_pike", "name": "Jorun Pike",
        "location_id": "loc.harrowdown.tavern", "kind": "npc", "region": None,
        "common_knowledge": [], "portrait": None, "last_event_id": 1,
    }
    return st


def _rep(st, scope, subject, value):
    st.reputation[f"pc::{scope}::{subject}"] = {
        "actor_id": "pc", "scope": scope, "subject_id": subject,
        "value": value, "last_event_id": 1,
    }


class TestSelfView:
    def test_none_without_a_sheet(self):
        assert self_view(FoldState(), "pc") is None

    def test_surfaces_own_build(self):
        me = self_view(_state(), "pc")
        assert me.name == "Ash"
        assert me.origin == "quill_touched_stranger"
        assert me.aptitudes["presence"] == 11  # the player knows their own build
        assert me.wounds  # a WORD, never a raw hp number
        assert me.marks == ()

    def test_surfaces_persistent_marks_from_public_mark_flags(self):
        st = _state()
        st.characters["pc"]["flags"] = {
            "scar_turn_3": "spared by the Quarryman",
            "marked_turn_4": "marked by ash",
            "journal_hook_turn_5": "hidden hook",
        }
        me = self_view(st, "pc")
        assert me.marks == ("marked by ash", "spared by the Quarryman")

    def test_disposition_named_from_the_manifest_and_described(self):
        st = _state()
        st.characters["pc"]["flags"]["knows_name_npc_harrowdown_jorun_pike"] = True
        _rep(st, "disposition", "npc.harrowdown.jorun_pike", 2)
        me = self_view(st, "pc")
        assert len(me.dispositions) == 1
        d = me.dispositions[0]
        assert d.subject_name == "Jorun Pike"
        assert d.value == 2 and d.descriptor == "warm to you"

    def test_disposition_keeps_an_unlearned_name_fogged(self):
        st = _state()
        _rep(st, "disposition", "npc.harrowdown.jorun_pike", 2)
        me = self_view(st, "pc")
        assert me.dispositions[0].subject_name != "Jorun Pike"

    def test_unknown_npc_name_is_humanized(self):
        st = _state()
        _rep(st, "disposition", "npc.dev.hedda", -1)  # not in the manifest
        me = self_view(st, "pc")
        assert me.dispositions[0].subject_name == "Hedda"
        assert me.dispositions[0].descriptor == "wary of you"

    def test_standing_and_renown(self):
        st = _state()
        _rep(st, "standing", "loc.harrowdown", 3)
        _rep(st, "renown", "", 5)
        me = self_view(st, "pc")
        assert me.standings[0].subject_name == "Harrowdown"
        assert me.standings[0].descriptor == "esteemed here"
        assert me.renown == 5 and me.renown_descriptor == "widely spoken of"

    def test_dispositions_sorted_warmest_first(self):
        st = _state()
        _rep(st, "disposition", "npc.a", -1)
        _rep(st, "disposition", "npc.b", 3)
        _rep(st, "disposition", "npc.c", 1)
        me = self_view(st, "pc")
        assert [d.value for d in me.dispositions] == [3, 1, -1]
