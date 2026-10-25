"""World-content loader: parse + validate ``content/world/*.yaml``.

The format is LOCKED by the original ticket (interface decision #3):
the engine owns this loader and validation; content authors write to it. Loader
errors are precise — every message carries ``file:line`` and, where one
exists, the offending ``id`` — because content authors iterate against these
messages without an engine developer in the loop.

Sections:
    locations:    required list (id, name, type, region, connections)
    entities:     required list (id, name, kind, location, true_sheet,
                  common_knowledge, portrait)
    prices:       optional map  {snake_case_key: non-negative int}
    rumor_seeds:  optional list [{deed, notoriety}]
    laws:         optional list — the engine extension for authored
                  sealed/impossible overrides (the resolver needs an
                  authored home for these per the original ticket; the
                  locked spec fixes the four sections above and is
                  silent on laws, so this is additive, documented in
                  docs/engine/stats.md and the sprint report).

TRUE SHEETS STAY HERE. Authored entities' aptitudes/threat bands are
config read by the resolver at decision time; they are never written to
the event log, projections, the client, or narrator context paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from everquill_engine.claims import PREDICATES as _CLAIM_PREDICATES

__all__ = [
    "WorldContentError",
    "Connection",
    "Location",
    "TrueSheet",
    "ScopeReveal",
    "ScopeError",
    "ScopeSubject",
    "ScopeLead",
    "KnowledgeScope",
    "WorldEntity",
    "RumorSeed",
    "Law",
    "WorldContent",
    "load_world",
    "APTITUDES",
    "LOADER_VERSION",
]

#: Version of this loader's interpretation of the world-content format.
#: Recorded in the genesis content_manifest event so a world
#: can prove which loader semantics governed its authored truth. Bump
#: when the loader changes how the same YAML bytes are interpreted.
LOADER_VERSION = "world-loader.v2"

#: LOCKED aptitude vocabulary (interface decision #1). Order matters:
#: it is the chargen roll order and the canonical serialization order.
APTITUDES: tuple[str, ...] = ("might", "finesse", "wits", "will", "presence", "lore")

LOCATION_TYPES = frozenset({"tavern", "guild_hall", "church", "road", "square", "shop"})
ENTITY_KINDS = frozenset({"npc", "creature", "item", "prop"})
LAW_TIERS = frozenset({"sealed", "impossible"})

#: Price keys a player can buy with a declared transaction, and the reason the
#: Chronicle coin line records. Only goods and services the engine fulfils are
#: sold (drink, food, a bed); other price-table rows (wages, weapons) are
#: reference prices until vendor stock exists, so buying them spends nothing.
SALE_PRICE_REASONS: dict[str, str] = {
    "ale_pint_copper": "drink",
    "meal_common_copper": "meal",
    "bread_loaf_copper": "bread",
    "inn_room_night_copper": "room",
}

#: Where each sold good is on sale, by location type: a purchase needs a
#: seller where you stand, so the parse can never buy a pint on the road.
SALE_PLACES: dict[str, frozenset[str]] = {
    "ale_pint_copper": frozenset({"tavern"}),
    "meal_common_copper": frozenset({"tavern"}),
    "bread_loaf_copper": frozenset({"tavern", "square", "shop"}),
    "inn_room_night_copper": frozenset({"tavern"}),
}


def sold_here(world: WorldContent, location_id: str | None) -> tuple[str, ...]:
    """The sold price keys on sale at ``location_id`` (by its type), in table order."""
    location = world.locations.get(location_id) if location_id else None
    kind = location.type if location is not None else None
    return tuple(
        key
        for key in SALE_PRICE_REASONS
        if key in world.prices and kind in SALE_PLACES.get(key, frozenset())
    )

_LOC_ID_RE = re.compile(r"^loc\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_ENTITY_ID_RE = re.compile(r"^(npc|creature|item|prop)\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class WorldContentError(ValueError):
    """A world-content file failed validation. Message: 'file:line: [id] why'."""


@dataclass(frozen=True, slots=True)
class Connection:
    to: str
    carriage_days: int


@dataclass(frozen=True, slots=True)
class Location:
    id: str
    name: str
    type: str
    region: str
    connections: tuple[Connection, ...] = ()


@dataclass(frozen=True, slots=True)
class TrueSheet:
    aptitudes: dict[str, int]
    threat_band: int
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScopeReveal:
    """One authored appraisal-tier field a source can reveal about a subject.

    Reveals are FIELDS, never numbers (roadmap §3.3 / playbook §5.7 — the
    Kumo appraisal model): a band WORD, a ranged estimate as prose, a named
    weak point. ``tier`` is the appraisal depth at which it surfaces; a
    research success reveals the deepest authored field the roll AND the
    source's ``max_appraisal_tier`` both reached. ``predicate`` is a closed
    claim predicate (``threat_assessed`` / ``common_knowledge`` /
    ``weak_point`` …). A ``weak_point`` reveal is what unlocks a
    knowledge-gated action downstream (resolver)."""

    tier: int
    predicate: str
    value_text: str
    claim_text: str


@dataclass(frozen=True, slots=True)
class ScopeError:
    """The confidently-WRONG answer a source gives on a BAD research roll —
    the ballads-lie mechanic (roadmap §3.3: wrong intel is CAUSAL, never
    random). Deterministic: same source, same subject, same wrong claim,
    every time. ``distortion`` names the reusable error mechanism
    (``local_mistaken_for_universal`` / ``ballad_inflation`` / ``outdated``
    / …) and is stamped as the claim's provenance scope."""

    predicate: str
    value_text: str
    claim_text: str
    distortion: str


@dataclass(frozen=True, slots=True)
class ScopeSubject:
    """A subject a source can speak to, with its authored reveals + error."""

    subject: str
    reveals: tuple[ScopeReveal, ...] = ()
    error: ScopeError | None = None

    def reveal_at(self, achieved_tier: int) -> ScopeReveal | None:
        """The deepest authored reveal whose tier the research reached."""
        candidates = [r for r in self.reveals if r.tier <= achieved_tier]
        return max(candidates, key=lambda r: r.tier) if candidates else None


@dataclass(frozen=True, slots=True)
class ScopeLead:
    """The pointer a source gives for a subject OUTSIDE its scope: 'nothing
    here — but the records you want are kept at <to>' (roadmap §3.6, the
    zero-authoring quest generator; distance IS the drama)."""

    to: str
    claim_text: str


@dataclass(frozen=True, slots=True)
class KnowledgeScope:
    """A source entity's research scope (roadmap §3.6). Content authors write it;
    the resolver consumes it. ``max_appraisal_tier`` caps how deep any
    success can read HERE (Kumo appraisal tiers); ``subjects`` are what the
    source can speak to accurately; a research subject NOT among them yields
    the ``lead`` pointer ('nothing here, but a lead')."""

    max_appraisal_tier: int = 0
    subjects: tuple[ScopeSubject, ...] = ()
    lead: ScopeLead | None = None

    def subject(self, subject_id: str) -> ScopeSubject | None:
        return next((s for s in self.subjects if s.subject == subject_id), None)


@dataclass(frozen=True, slots=True)
class WorldEntity:
    id: str
    name: str
    kind: str
    location: str
    true_sheet: TrueSheet
    descriptor: str | None = None
    common_knowledge: tuple[str, ...] = ()
    portrait: str | None = None
    knowledge_scope: KnowledgeScope | None = None


@dataclass(frozen=True, slots=True)
class RumorSeed:
    deed: str
    notoriety: float


@dataclass(frozen=True, slots=True)
class Law:
    """Authored tier override: forces SEALED or IMPOSSIBLE on matching intents.

    Matching (deterministic, resolver-side): the law applies when the
    intent's action_type is in ``action_types`` (empty = any) AND
    (any resolved target carries a tag in ``target_tags`` OR the parser
    named the law in the intent's closed ``invoked_law_ids`` field).
    ``invoke_phrases`` only describe the feat to the parser in the parse
    call's Laws list; the engine never matches them against player text.

    Who decides (George, 25 Oct 2026): the engine applies a law from the
    action type and the targets' tags; the parser's ``invoked_law_ids`` can
    only ADD a law, never lift one. A law with no ``target_tags`` (a feat with
    no target, like flying unaided) therefore exists only through that
    addition: if the parser misses it, the action resolves as it otherwise
    would. Anything a law must always guard belongs on a target tag.
    ``components`` follow the shape of docs/lore/laws-format.md; Sprint 1
    verifies components only as boolean flags on the actor's sheet (flag
    name == component_id), which is enough for fail-forward. Full predicate
    verification is a later sprint.

    ``irreversible`` (optional): marks the feat as one the
    commit beat must always confirm (interface decision 2 — the
    "irreversible flag" leg of the tier→confirmation table), regardless
    of the tier it resolves at.
    """

    law_id: str
    name: str
    tier: str
    action_types: tuple[str, ...] = ()
    target_tags: tuple[str, ...] = ()
    invoke_phrases: tuple[str, ...] = ()
    components: tuple[str, ...] = ()  # component_ids that must all verify
    on_attempt_incomplete: tuple[str, ...] = ()
    irreversible: bool = False


@dataclass(frozen=True, slots=True)
class WorldContent:
    source: str
    locations: dict[str, Location] = field(default_factory=dict)
    entities: dict[str, WorldEntity] = field(default_factory=dict)
    prices: dict[str, int] = field(default_factory=dict)
    rumor_seeds: tuple[RumorSeed, ...] = ()
    laws: tuple[Law, ...] = ()

    def entities_at(self, location_id: str) -> list[WorldEntity]:
        return [e for e in self.entities.values() if e.location == location_id]

    def sources_at(self, location_id: str) -> list[WorldEntity]:
        """Knowledge sources (entities carrying a ``knowledge_scope``) at a
        location, sorted by id for deterministic source selection."""
        return sorted(
            (
                e
                for e in self.entities.values()
                if e.location == location_id and e.knowledge_scope is not None
            ),
            key=lambda e: e.id,
        )


# --- YAML with line numbers -------------------------------------------------
# Values are wrapped in _Node(value, line) via a compose() walk so every
# validation error can say exactly where in the file it comes from.


@dataclass(frozen=True, slots=True)
class _Node:
    value: object
    line: int


def _wrap(node: yaml.Node, path: str) -> _Node:
    line = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        mapping: dict[str, _Node] = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, yaml.ScalarNode):
                raise WorldContentError(
                    f"{path}:{key_node.start_mark.line + 1}: mapping keys must be scalars"
                )
            mapping[str(_scalar(key_node))] = _wrap(value_node, path)
        return _Node(mapping, line)
    if isinstance(node, yaml.SequenceNode):
        return _Node([_wrap(item, path) for item in node.value], line)
    return _Node(_scalar(node), line)


def _scalar(node: yaml.ScalarNode) -> object:
    loader = yaml.SafeLoader("")
    return loader.construct_object(node, deep=True)


def _parse_with_lines(path: Path) -> _Node:
    text = path.read_text(encoding="utf-8")
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else 0
        raise WorldContentError(f"{path}:{line}: not valid YAML: {exc}") from exc
    if root is None:
        raise WorldContentError(f"{path}:1: file is empty")
    return _wrap(root, str(path))


# --- validation helpers ------------------------------------------------------


class _Ctx:
    """Carries the file path and the nearest enclosing id for error messages."""

    def __init__(self, path: str, owner_id: str | None = None) -> None:
        self.path = path
        self.owner_id = owner_id

    def fail(self, node: _Node, message: str) -> WorldContentError:
        prefix = f"{self.path}:{node.line}: "
        if self.owner_id:
            prefix += f"[{self.owner_id}] "
        return WorldContentError(prefix + message)

    def with_owner(self, owner_id: str) -> _Ctx:
        return _Ctx(self.path, owner_id)


def _need_map(ctx: _Ctx, node: _Node, what: str) -> dict[str, _Node]:
    if not isinstance(node.value, dict):
        raise ctx.fail(node, f"{what} must be a mapping")
    return node.value


def _need_list(ctx: _Ctx, node: _Node, what: str) -> list[_Node]:
    if not isinstance(node.value, list):
        raise ctx.fail(node, f"{what} must be a list")
    return node.value


def _need_str(ctx: _Ctx, node: _Node, what: str) -> str:
    if not isinstance(node.value, str) or not node.value.strip():
        raise ctx.fail(node, f"{what} must be a non-empty string")
    return node.value


def _need_int(ctx: _Ctx, node: _Node, what: str) -> int:
    if isinstance(node.value, bool) or not isinstance(node.value, int):
        raise ctx.fail(node, f"{what} must be an integer")
    return node.value


def _get(ctx: _Ctx, mapping: dict[str, _Node], owner: _Node, key: str) -> _Node:
    if key not in mapping:
        raise ctx.fail(owner, f"missing required key '{key}'")
    return mapping[key]


def _reject_unknown(ctx: _Ctx, mapping: dict[str, _Node], owner: _Node, allowed: set[str]) -> None:
    for key, node in mapping.items():
        if key not in allowed:
            raise ctx.fail(node, f"unknown key '{key}' (allowed: {', '.join(sorted(allowed))})")


def _str_list(ctx: _Ctx, node: _Node, what: str) -> tuple[str, ...]:
    return tuple(_need_str(ctx, item, f"{what} entry") for item in _need_list(ctx, node, what))


# --- section parsers ----------------------------------------------------------


def _parse_location(ctx: _Ctx, node: _Node) -> Location:
    mapping = _need_map(ctx, node, "location")
    id_node = _get(ctx, mapping, node, "id")
    loc_id = _need_str(ctx, id_node, "location id")
    ctx = ctx.with_owner(loc_id)
    if not _LOC_ID_RE.match(loc_id):
        raise ctx.fail(id_node, "location id must match 'loc.<region>.<slug>' (snake_case)")
    _reject_unknown(ctx, mapping, node, {"id", "name", "type", "region", "connections"})
    type_node = _get(ctx, mapping, node, "type")
    loc_type = _need_str(ctx, type_node, "type")
    if loc_type not in LOCATION_TYPES:
        raise ctx.fail(
            type_node, f"type '{loc_type}' not one of: {', '.join(sorted(LOCATION_TYPES))}"
        )
    connections: list[Connection] = []
    if "connections" in mapping:
        for conn_node in _need_list(ctx, mapping["connections"], "connections"):
            conn_map = _need_map(ctx, conn_node, "connection")
            _reject_unknown(ctx, conn_map, conn_node, {"to", "carriage_days"})
            to = _need_str(ctx, _get(ctx, conn_map, conn_node, "to"), "connection 'to'")
            days_node = _get(ctx, conn_map, conn_node, "carriage_days")
            days = _need_int(ctx, days_node, "carriage_days")
            if days < 0:
                raise ctx.fail(days_node, "carriage_days must be >= 0")
            connections.append(Connection(to=to, carriage_days=days))
    return Location(
        id=loc_id,
        name=_need_str(ctx, _get(ctx, mapping, node, "name"), "name"),
        type=loc_type,
        region=_need_str(ctx, _get(ctx, mapping, node, "region"), "region"),
        connections=tuple(connections),
    )


def _parse_true_sheet(ctx: _Ctx, node: _Node) -> TrueSheet:
    mapping = _need_map(ctx, node, "true_sheet")
    _reject_unknown(ctx, mapping, node, {"aptitudes", "threat_band", "tags"})
    apt_node = _get(ctx, mapping, node, "aptitudes")
    apt_map = _need_map(ctx, apt_node, "aptitudes")
    aptitudes: dict[str, int] = {}
    for key in APTITUDES:
        if key not in apt_map:
            raise ctx.fail(apt_node, f"aptitudes missing '{key}' (locked vocabulary)")
        aptitudes[key] = _need_int(ctx, apt_map[key], f"aptitude '{key}'")
    for key, extra in apt_map.items():
        if key not in APTITUDES:
            raise ctx.fail(
                extra,
                f"unknown aptitude '{key}' (locked vocabulary: {', '.join(APTITUDES)})",
            )
    tags: tuple[str, ...] = ()
    if "tags" in mapping:
        tags = _str_list(ctx, mapping["tags"], "tags")
    return TrueSheet(
        aptitudes=aptitudes,
        threat_band=_need_int(ctx, _get(ctx, mapping, node, "threat_band"), "threat_band"),
        tags=tags,
    )


def _parse_entity(ctx: _Ctx, node: _Node) -> WorldEntity:
    mapping = _need_map(ctx, node, "entity")
    id_node = _get(ctx, mapping, node, "id")
    entity_id = _need_str(ctx, id_node, "entity id")
    ctx = ctx.with_owner(entity_id)
    match = _ENTITY_ID_RE.match(entity_id)
    if not match:
        raise ctx.fail(
            id_node,
            "entity id must match '<kind>.<region>.<slug>' with kind in "
            "npc|creature|item|prop (snake_case)",
        )
    _reject_unknown(
        ctx,
        mapping,
        node,
        {
            "id", "name", "kind", "location", "true_sheet", "descriptor",
            "common_knowledge", "portrait", "knowledge_scope",
        },
    )
    kind_node = _get(ctx, mapping, node, "kind")
    kind = _need_str(ctx, kind_node, "kind")
    if kind not in ENTITY_KINDS:
        raise ctx.fail(kind_node, f"kind '{kind}' not one of: {', '.join(sorted(ENTITY_KINDS))}")
    if kind != match.group(1):
        raise ctx.fail(kind_node, f"kind '{kind}' does not match id prefix '{match.group(1)}'")
    portrait: str | None = None
    if "portrait" in mapping and mapping["portrait"].value is not None:
        portrait = _need_str(ctx, mapping["portrait"], "portrait")
    common: tuple[str, ...] = ()
    if "common_knowledge" in mapping:
        common = _str_list(ctx, mapping["common_knowledge"], "common_knowledge")
    descriptor: str | None = None
    if "descriptor" in mapping and mapping["descriptor"].value is not None:
        descriptor = _need_str(ctx, mapping["descriptor"], "descriptor")
    scope: KnowledgeScope | None = None
    if "knowledge_scope" in mapping:
        scope = _parse_knowledge_scope(ctx, mapping["knowledge_scope"])
    return WorldEntity(
        id=entity_id,
        name=_need_str(ctx, _get(ctx, mapping, node, "name"), "name"),
        kind=kind,
        location=_need_str(ctx, _get(ctx, mapping, node, "location"), "location"),
        true_sheet=_parse_true_sheet(ctx, _get(ctx, mapping, node, "true_sheet")),
        descriptor=descriptor,
        common_knowledge=common,
        portrait=portrait,
        knowledge_scope=scope,
    )


#: The closed claim-predicate vocabulary a scope reveal/error may name.
#: Sourced from the pure claims module so content authors get a load-time error on a
#: typo instead of a resolve-time one; the resolver's enforce_predicate is
#: still the write-boundary gate.
_SCOPE_PREDICATES = frozenset(_CLAIM_PREDICATES)


def _parse_scope_reveal(ctx: _Ctx, node: _Node) -> ScopeReveal:
    mapping = _need_map(ctx, node, "reveal")
    _reject_unknown(ctx, mapping, node, {"tier", "predicate", "value_text", "claim_text"})
    tier = _need_int(ctx, _get(ctx, mapping, node, "tier"), "reveal tier")
    if tier < 0:
        raise ctx.fail(mapping["tier"], "reveal tier must be >= 0")
    predicate = _need_str(ctx, _get(ctx, mapping, node, "predicate"), "reveal predicate")
    if predicate not in _SCOPE_PREDICATES:
        raise ctx.fail(
            mapping["predicate"],
            f"predicate '{predicate}' is not a closed claim predicate "
            f"({', '.join(sorted(_SCOPE_PREDICATES))})",
        )
    return ScopeReveal(
        tier=tier,
        predicate=predicate,
        value_text=_need_str(ctx, _get(ctx, mapping, node, "value_text"), "reveal value_text"),
        claim_text=_need_str(ctx, _get(ctx, mapping, node, "claim_text"), "reveal claim_text"),
    )


def _parse_scope_error(ctx: _Ctx, node: _Node) -> ScopeError:
    mapping = _need_map(ctx, node, "error")
    _reject_unknown(
        ctx, mapping, node, {"predicate", "value_text", "claim_text", "distortion"}
    )
    predicate = _need_str(ctx, _get(ctx, mapping, node, "predicate"), "error predicate")
    if predicate not in _SCOPE_PREDICATES:
        raise ctx.fail(
            mapping["predicate"],
            f"predicate '{predicate}' is not a closed claim predicate "
            f"({', '.join(sorted(_SCOPE_PREDICATES))})",
        )
    return ScopeError(
        predicate=predicate,
        value_text=_need_str(ctx, _get(ctx, mapping, node, "value_text"), "error value_text"),
        claim_text=_need_str(ctx, _get(ctx, mapping, node, "claim_text"), "error claim_text"),
        distortion=_need_str(ctx, _get(ctx, mapping, node, "distortion"), "error distortion"),
    )


def _parse_scope_subject(ctx: _Ctx, node: _Node) -> ScopeSubject:
    mapping = _need_map(ctx, node, "scope subject")
    _reject_unknown(ctx, mapping, node, {"subject", "reveals", "error"})
    subject = _need_str(ctx, _get(ctx, mapping, node, "subject"), "scope subject id")
    reveals: list[ScopeReveal] = []
    if "reveals" in mapping:
        for reveal_node in _need_list(ctx, mapping["reveals"], "reveals"):
            reveals.append(_parse_scope_reveal(ctx, reveal_node))
    error: ScopeError | None = None
    if "error" in mapping:
        error = _parse_scope_error(ctx, mapping["error"])
    return ScopeSubject(subject=subject, reveals=tuple(reveals), error=error)


def _parse_knowledge_scope(ctx: _Ctx, node: _Node) -> KnowledgeScope:
    mapping = _need_map(ctx, node, "knowledge_scope")
    _reject_unknown(ctx, mapping, node, {"max_appraisal_tier", "subjects", "lead"})
    max_tier = 0
    if "max_appraisal_tier" in mapping:
        max_tier = _need_int(ctx, mapping["max_appraisal_tier"], "max_appraisal_tier")
        if max_tier < 0:
            raise ctx.fail(mapping["max_appraisal_tier"], "max_appraisal_tier must be >= 0")
    subjects: list[ScopeSubject] = []
    seen: set[str] = set()
    if "subjects" in mapping:
        for subject_node in _need_list(ctx, mapping["subjects"], "subjects"):
            parsed = _parse_scope_subject(ctx, subject_node)
            if parsed.subject in seen:
                raise ctx.fail(subject_node, f"duplicate scope subject '{parsed.subject}'")
            seen.add(parsed.subject)
            subjects.append(parsed)
    lead: ScopeLead | None = None
    if "lead" in mapping:
        lead_map = _need_map(ctx, mapping["lead"], "lead")
        _reject_unknown(ctx, lead_map, mapping["lead"], {"to", "claim_text"})
        lead = ScopeLead(
            to=_need_str(ctx, _get(ctx, lead_map, mapping["lead"], "to"), "lead 'to'"),
            claim_text=_need_str(
                ctx, _get(ctx, lead_map, mapping["lead"], "claim_text"), "lead claim_text"
            ),
        )
    return KnowledgeScope(max_appraisal_tier=max_tier, subjects=tuple(subjects), lead=lead)


def _parse_law(ctx: _Ctx, node: _Node) -> Law:
    mapping = _need_map(ctx, node, "law")
    id_node = _get(ctx, mapping, node, "law_id")
    law_id = _need_str(ctx, id_node, "law_id")
    ctx = ctx.with_owner(law_id)
    if not re.match(r"^law\.[a-z][a-z0-9_]*$", law_id):
        raise ctx.fail(id_node, "law_id must match 'law.<slug>' (snake_case)")
    _reject_unknown(
        ctx,
        mapping,
        node,
        {
            "law_id",
            "name",
            "tier",
            "action_types",
            "target_tags",
            "invoke_phrases",
            "components",
            "on_attempt_incomplete",
            "irreversible",
        },
    )
    tier_node = _get(ctx, mapping, node, "tier")
    tier = _need_str(ctx, tier_node, "tier")
    if tier not in LAW_TIERS:
        raise ctx.fail(tier_node, f"tier '{tier}' not one of: {', '.join(sorted(LAW_TIERS))}")
    if tier == "sealed" and "components" not in mapping:
        raise ctx.fail(node, "sealed laws must declare components (docs/lore/laws-format.md)")

    def opt_list(key: str) -> tuple[str, ...]:
        return _str_list(ctx, mapping[key], key) if key in mapping else ()

    irreversible = False
    if "irreversible" in mapping:
        flag_node = mapping["irreversible"]
        if not isinstance(flag_node.value, bool):
            raise ctx.fail(flag_node, "irreversible must be a boolean")
        irreversible = flag_node.value

    law = Law(
        law_id=law_id,
        name=_need_str(ctx, _get(ctx, mapping, node, "name"), "name"),
        tier=tier,
        action_types=opt_list("action_types"),
        target_tags=opt_list("target_tags"),
        invoke_phrases=opt_list("invoke_phrases"),
        components=opt_list("components"),
        on_attempt_incomplete=opt_list("on_attempt_incomplete"),
        irreversible=irreversible,
    )
    if not (law.action_types or law.target_tags or law.invoke_phrases):
        raise ctx.fail(
            node, "law matches nothing: give action_types, target_tags or invoke_phrases"
        )
    return law


def load_world(path: str | Path) -> WorldContent:
    """Load + validate one world-content YAML file.

    Raises :class:`WorldContentError` with 'file:line: [id] why' messages.
    """
    file_path = Path(path)
    root = _parse_with_lines(file_path)
    ctx = _Ctx(str(file_path))
    top = _need_map(ctx, root, "world content")
    _reject_unknown(
        ctx, top, root, {"locations", "entities", "prices", "rumor_seeds", "laws"}
    )

    locations: dict[str, Location] = {}
    for loc_node in _need_list(ctx, _get(ctx, top, root, "locations"), "locations"):
        loc = _parse_location(ctx, loc_node)
        if loc.id in locations:
            raise ctx.with_owner(loc.id).fail(loc_node, "duplicate location id")
        locations[loc.id] = loc

    entities: dict[str, WorldEntity] = {}
    for ent_node in _need_list(ctx, _get(ctx, top, root, "entities"), "entities"):
        entity = _parse_entity(ctx, ent_node)
        if entity.id in entities:
            raise ctx.with_owner(entity.id).fail(ent_node, "duplicate entity id")
        if entity.location not in locations:
            raise ctx.with_owner(entity.id).fail(
                ent_node, f"location '{entity.location}' is not a location id in this file"
            )
        entities[entity.id] = entity

    for loc in locations.values():
        for conn in loc.connections:
            if conn.to not in locations:
                # Re-walk for the precise node line of the bad connection.
                raise WorldContentError(
                    f"{file_path}: [{loc.id}] connection to unknown location '{conn.to}'"
                )

    prices: dict[str, int] = {}
    if "prices" in top:
        for key, price_node in _need_map(ctx, top["prices"], "prices").items():
            if not _SNAKE_RE.match(key):
                raise ctx.fail(price_node, f"price key '{key}' must be snake_case")
            value = _need_int(ctx, price_node, f"price '{key}'")
            if value < 0:
                raise ctx.fail(price_node, f"price '{key}' must be >= 0")
            prices[key] = value

    rumor_seeds: list[RumorSeed] = []
    if "rumor_seeds" in top:
        for seed_node in _need_list(ctx, top["rumor_seeds"], "rumor_seeds"):
            seed_map = _need_map(ctx, seed_node, "rumor seed")
            _reject_unknown(ctx, seed_map, seed_node, {"deed", "notoriety"})
            notoriety_node = _get(ctx, seed_map, seed_node, "notoriety")
            notoriety = notoriety_node.value
            if isinstance(notoriety, bool) or not isinstance(notoriety, (int, float)):
                raise ctx.fail(notoriety_node, "notoriety must be a number")
            if notoriety < 0:
                raise ctx.fail(notoriety_node, "notoriety must be >= 0")
            rumor_seeds.append(
                RumorSeed(
                    deed=_need_str(ctx, _get(ctx, seed_map, seed_node, "deed"), "deed"),
                    notoriety=float(notoriety),
                )
            )

    laws: list[Law] = []
    if "laws" in top:
        for law_node in _need_list(ctx, top["laws"], "laws"):
            law = _parse_law(ctx, law_node)
            if any(existing.law_id == law.law_id for existing in laws):
                raise ctx.with_owner(law.law_id).fail(law_node, "duplicate law_id")
            laws.append(law)

    return WorldContent(
        source=str(file_path),
        locations=locations,
        entities=entities,
        prices=prices,
        rumor_seeds=tuple(rumor_seeds),
        laws=tuple(laws),
    )
