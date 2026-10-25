"""World-content loader: locked format accepted, errors precise (file/line/id)."""

from __future__ import annotations

import textwrap

import pytest

from everquill_engine.world import APTITUDES, WorldContentError, load_world
from tests.harness import FIXTURE_WORLD

VALID = textwrap.dedent(
    """\
    locations:
      - id: loc.test.tavern
        name: The Test Tavern
        type: tavern
        region: test
        connections: [{to: loc.test.square, carriage_days: 0}]
      - id: loc.test.square
        name: Test Square
        type: square
        region: test
    entities:
      - id: npc.test.anna
        name: Anna
        kind: npc
        location: loc.test.tavern
        true_sheet:
          aptitudes: {might: 5, finesse: 6, wits: 7, will: 8, presence: 9, lore: 10}
          threat_band: 6
          tags: [barkeep]
        common_knowledge: [Anna pours a fair measure.]
        portrait: null
    prices: {inn_night_copper: 6}
    rumor_seeds:
      - {deed: something happened, notoriety: 2}
    """
)


def _write(tmp_path, text):
    path = tmp_path / "region.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestValid:
    def test_dev_fixture_loads(self):
        world = load_world(FIXTURE_WORLD)
        assert "loc.dev.tavern" in world.locations
        assert len(world.entities) == 3
        assert world.prices["inn_night_copper"] == 6
        assert {law.law_id for law in world.laws} == {
            "law.hearth_oath",
            "law.unwritten_flight",
        }
        for entity in world.entities.values():
            assert set(entity.true_sheet.aptitudes) == set(APTITUDES)

    def test_full_spec_shape_loads(self, tmp_path):
        world = load_world(_write(tmp_path, VALID))
        assert world.locations["loc.test.tavern"].connections[0].to == "loc.test.square"
        assert world.entities["npc.test.anna"].true_sheet.threat_band == 6
        assert world.rumor_seeds[0].notoriety == 2.0

    def test_prices_and_rumors_optional(self, tmp_path):
        text = VALID.split("prices:")[0]
        world = load_world(_write(tmp_path, text))
        assert world.prices == {} and world.rumor_seeds == ()


class TestPreciseErrors:
    """Every message must carry file:line and, where one exists, the id."""

    def _fails(self, tmp_path, text, *needles):
        path = _write(tmp_path, text)
        with pytest.raises(WorldContentError) as exc:
            load_world(path)
        message = str(exc.value)
        assert str(path) in message
        for needle in needles:
            assert needle in message, f"{needle!r} not in error: {message}"
        return message

    def test_bad_location_type_has_line_and_id(self, tmp_path):
        bad = VALID.replace("type: square", "type: plaza")
        message = self._fails(tmp_path, bad, "[loc.test.square]", "plaza")
        line = int(message.split(":", 2)[1])
        assert line == 9  # the exact 'type: plaza' line

    def test_bad_id_pattern(self, tmp_path):
        self._fails(
            tmp_path, VALID.replace("id: npc.test.anna", "id: npc.Test.Anna"),
            "npc|creature|item|prop",
        )

    def test_kind_id_mismatch(self, tmp_path):
        self._fails(
            tmp_path, VALID.replace("kind: npc", "kind: prop"), "[npc.test.anna]",
            "does not match id prefix",
        )

    def test_missing_aptitude_names_the_key(self, tmp_path):
        self._fails(
            tmp_path,
            VALID.replace("might: 5, ", ""),
            "[npc.test.anna]",
            "missing 'might'",
        )

    def test_unknown_aptitude_rejected(self, tmp_path):
        self._fails(
            tmp_path,
            VALID.replace("lore: 10", "lore: 10, luck: 3"),
            "unknown aptitude 'luck'",
        )

    def test_unknown_entity_location(self, tmp_path):
        self._fails(
            tmp_path,
            VALID.replace("location: loc.test.tavern", "location: loc.test.nowhere"),
            "[npc.test.anna]",
            "loc.test.nowhere",
        )

    def test_connection_to_unknown_location(self, tmp_path):
        self._fails(
            tmp_path,
            VALID.replace("{to: loc.test.square, carriage_days: 0}",
                          "{to: loc.test.void, carriage_days: 1}"),
            "[loc.test.tavern]",
            "loc.test.void",
        )

    def test_unknown_top_level_key(self, tmp_path):
        self._fails(tmp_path, VALID + "\nquests: []\n", "unknown key 'quests'")

    def test_duplicate_entity_id(self, tmp_path):
        block = VALID[VALID.index("  - id: npc.test.anna"):VALID.index("prices:")]
        dup = VALID.replace("prices:", block + "prices:", 1)
        self._fails(tmp_path, dup, "duplicate entity id")

    def test_sealed_law_requires_components(self, tmp_path):
        law = textwrap.dedent(
            """\
            laws:
              - law_id: law.test
                name: Test Law
                tier: sealed
                invoke_phrases: [test]
            """
        )
        self._fails(tmp_path, VALID + law, "[law.test]", "components")

    def test_law_irreversible_flag_parses_and_defaults_false(self, tmp_path):
        """Optional irreversible flag (commit-beat leg 3)."""
        law = textwrap.dedent(
            """\
            laws:
              - law_id: law.test
                name: Test Law
                tier: impossible
                invoke_phrases: [test]
                irreversible: true
            """
        )
        world = load_world(_write(tmp_path, VALID + law))
        (parsed,) = world.laws
        assert parsed.irreversible is True
        world_default = load_world(
            _write(tmp_path, VALID + law.replace("\n    irreversible: true", ""))
        )
        assert world_default.laws[0].irreversible is False

    def test_law_irreversible_must_be_boolean(self, tmp_path):
        law = textwrap.dedent(
            """\
            laws:
              - law_id: law.test
                name: Test Law
                tier: impossible
                invoke_phrases: [test]
                irreversible: yes please
            """
        )
        self._fails(tmp_path, VALID + law, "[law.test]", "boolean")

    def test_not_yaml_reports_line(self, tmp_path):
        message = self._fails(tmp_path, "locations: [\n  {", "not valid YAML")
        assert ":2" in message or ":3" in message
