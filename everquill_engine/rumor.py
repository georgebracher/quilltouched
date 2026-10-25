"""Pure deed-rumor propagation math.

Resolver code receives the deed projection and asks this module which deeds
have reached the actor's current location. No event-log reads, no persistence.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Mapping
from typing import Any

from everquill_engine.world import WorldContent

__all__ = [
    "INTRA_HOP_MINUTES",
    "RUMOR_LIFESPAN_PER_NOTORIETY",
    "arrival_delay",
    "lifespan",
    "reached_deeds",
]

# Provisional tuning constants; validate by feel in playtests.
INTRA_HOP_MINUTES = 180
RUMOR_LIFESPAN_PER_NOTORIETY = 2880


def arrival_delay(distance_minutes: int, notoriety: int) -> int:
    """World-minutes before a deed reaches this distance.

    Louder deeds travel faster. Integer division is deliberate: all rumor math
    stays deterministic and replay-stable.
    """
    return max(0, int(distance_minutes)) // max(1, int(notoriety))


def lifespan(notoriety: int) -> int:
    """World-minutes a deed remains talk-worthy."""
    return max(1, int(notoriety)) * RUMOR_LIFESPAN_PER_NOTORIETY


def reached_deeds(
    deeds: Iterable[Mapping[str, Any]],
    *,
    world: WorldContent,
    location_id: str,
    world_time: int,
) -> tuple[dict[str, Any], ...]:
    """Deeds whose rumors have reached ``location_id`` by ``world_time``.

    A deed at the same location is not gossip. Travel distance is the shortest
    authored edge-cost path; the returned rows preserve deed append order and
    add ``hop_count`` plus ``distance_minutes`` for provenance/debugging.
    """
    by_origin: dict[str, dict[str, tuple[int, int]]] = {}
    reached: list[dict[str, Any]] = []
    for deed in deeds:
        origin = str(deed["location_id"])
        if origin == location_id or origin not in world.locations:
            continue
        paths = by_origin.get(origin)
        if paths is None:
            paths = _shortest_paths(world, origin)
            by_origin[origin] = paths
        path = paths.get(location_id)
        if path is None:
            continue
        distance, hops = path
        if hops < 1:
            continue
        age = int(world_time) - int(deed["world_time"])
        notoriety = int(deed["notoriety"])
        if age < arrival_delay(distance, notoriety):
            continue
        if age > lifespan(notoriety):
            continue
        reached.append({**dict(deed), "hop_count": hops, "distance_minutes": distance})
    return tuple(reached)


def _shortest_paths(world: WorldContent, origin: str) -> dict[str, tuple[int, int]]:
    """Dijkstra over the small authored travel graph.

    Values are ``location_id -> (distance_minutes, hop_count)``. Ties prefer
    fewer hops, then lexical location id via heap ordering.
    """
    out: dict[str, tuple[int, int]] = {origin: (0, 0)}
    heap: list[tuple[int, int, str]] = [(0, 0, origin)]
    while heap:
        distance, hops, location_id = heapq.heappop(heap)
        if out.get(location_id) != (distance, hops):
            continue
        location = world.locations.get(location_id)
        if location is None:
            continue
        for edge in location.connections:
            cost = max(int(edge.carriage_days) * 1440, INTRA_HOP_MINUTES)
            next_distance = distance + cost
            next_hops = hops + 1
            old = out.get(edge.to)
            if old is None or (next_distance, next_hops) < old:
                out[edge.to] = (next_distance, next_hops)
                heapq.heappush(heap, (next_distance, next_hops, edge.to))
    return out
