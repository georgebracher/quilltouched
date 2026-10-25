"""Slot maps + deterministic assignment (interface decision 5)."""

from __future__ import annotations

import pytest

from everquill_engine.slots import (
    SLOTS_PATH,
    Slot,
    SlotContentError,
    assign_slots,
    load_slot_maps,
)

VALID_YAML = """
tavern:
  slots:
    - {slot_id: tavern_bar, x_pct: 64, y_pct: 72}
    - {slot_id: tavern_center, x_pct: 52, y_pct: 81}
    - {slot_id: tavern_left, x_pct: 37, y_pct: 88}
"""


@pytest.fixture()
def slot_file(tmp_path):
    path = tmp_path / "slots.yaml"
    path.write_text(VALID_YAML, encoding="utf-8")
    return path


class TestLoader:
    def test_valid_file_parses(self, slot_file):
        maps = load_slot_maps(slot_file)
        assert set(maps) == {"tavern"}
        assert [s.slot_id for s in maps["tavern"]] == [
            "tavern_bar", "tavern_center", "tavern_left",
        ]
        assert maps["tavern"][0] == Slot("tavern_bar", 64.0, 72.0)

    def test_absent_file_returns_empty_not_error(self, tmp_path):
        assert load_slot_maps(tmp_path / "nope.yaml") == {}

    def test_team_b_slots_yaml_parses_when_present(self):
        """The real content file (content authors write it in parallel). When it
        exists it must satisfy this loader — that IS the agreed format."""
        if not SLOTS_PATH.exists():
            pytest.skip("content/world/slots.yaml not authored yet")
        maps = load_slot_maps()
        assert maps, "slots.yaml exists but defines no slot maps"
        for slots in maps.values():
            assert slots

    @pytest.mark.parametrize("bad,match", [
        ("tavern:\n  slots: []\n", "non-empty list"),
        ("tavern:\n  slots:\n    - {slot_id: a_b, x_pct: 101, y_pct: 5}\n", "0..100"),
        ("tavern:\n  slots:\n    - {slot_id: A_b, x_pct: 1, y_pct: 5}\n", "snake_case"),
        ("tavern:\n  slots:\n    - {slot_id: a_b, x_pct: 1}\n", "exactly"),
        ("tavern:\n  spots:\n    - {slot_id: a_b, x_pct: 1, y_pct: 5}\n", "slots"),
        (
            "tavern:\n  slots:\n    - {slot_id: a_b, x_pct: 1, y_pct: 5}\n"
            "    - {slot_id: a_b, x_pct: 2, y_pct: 6}\n",
            "duplicate",
        ),
    ])
    def test_malformed_files_rejected_with_clear_message(self, tmp_path, bad, match):
        path = tmp_path / "slots.yaml"
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(SlotContentError, match=match):
            load_slot_maps(path)


class TestAssignment:
    MAPS = {
        "tavern": (
            Slot("tavern_bar", 64, 72),
            Slot("tavern_center", 52, 81),
            Slot("tavern_left", 37, 88),
        )
    }
    ENTITIES = ["npc.dev.hedda", "npc.dev.sorrel", "pc"]

    def test_assignment_is_deterministic_and_input_order_free(self):
        a = assign_slots("tavern", self.MAPS, self.ENTITIES)
        b = assign_slots("tavern", self.MAPS, list(reversed(self.ENTITIES)))
        assert a == b
        assert set(a) == set(self.ENTITIES)

    def test_same_scene_same_arrangement_distinct_slots(self):
        assignment = assign_slots("tavern", self.MAPS, self.ENTITIES)
        slot_ids = [s.slot_id for s in assignment.values()]
        assert len(slot_ids) == len(set(slot_ids))  # no slot shared

    def test_overflow_entities_get_none(self):
        crowd = self.ENTITIES + ["npc.dev.a", "npc.dev.b"]
        assignment = assign_slots("tavern", self.MAPS, crowd)
        assert sum(1 for s in assignment.values() if s is None) == 2
        assert sum(1 for s in assignment.values() if s is not None) == 3

    def test_absent_map_falls_back_to_stable_none(self):
        """File absent / type unmapped → slot_id null for everyone,
        stable ordering preserved (the client fallback contract)."""
        assignment = assign_slots("tavern", {}, self.ENTITIES)
        assert list(assignment) == sorted(self.ENTITIES)
        assert all(slot is None for slot in assignment.values())
        assert assign_slots(None, self.MAPS, self.ENTITIES) == {
            e: None for e in self.ENTITIES
        }

    def test_pinned_assignment_never_drifts(self):
        """Regression pin: hash-assignment for this exact scene must
        reproduce forever (same scene → same arrangement, any machine)."""
        assignment = assign_slots("tavern", self.MAPS, self.ENTITIES)
        assert {e: (s.slot_id if s else None) for e, s in assignment.items()} == {
            "npc.dev.hedda": "tavern_bar",
            "npc.dev.sorrel": "tavern_left",
            "pc": "tavern_center",
        }
