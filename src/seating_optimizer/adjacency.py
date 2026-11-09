"""Derived neighbour graph and together-party clusters for hard-case placement.

No venue adjacency metadata is stored: geometry on each floor determines a
symmetric nearest-neighbour graph. No cross-floor edges can be created.
"""
from __future__ import annotations

from collections import defaultdict
from math import hypot

from .models import Rule, Table, TableDrawing, VenueLayout


def together_clusters(group_ids: list[str], lookup: dict[str, str], rules: list[Rule]
                     ) -> list[tuple[list[str], list[Rule]]]:
    """Connected components of together requests, including transitive chains."""
    parent = {gid: gid for gid in group_ids}

    def find(gid: str) -> str:
        while parent[gid] != gid:
            parent[gid] = parent[parent[gid]]
            gid = parent[gid]
        return gid

    for rule in rules:
        if rule.shape == "pair" and rule.parameters["relation"] == "together":
            left = find(lookup[rule.parameters["left"]])
            right = find(lookup[rule.parameters["right"]])
            parent[right] = left
    components: dict[str, list[str]] = defaultdict(list)
    for gid in group_ids:
        components[find(gid)].append(gid)
    result = []
    for ids in components.values():
        if len(ids) < 2:
            continue
        members = set(ids)
        linked = [rule for rule in rules if rule.shape == "pair"
                  and rule.parameters["relation"] == "together"
                  and lookup[rule.parameters["left"]] in members
                  and lookup[rule.parameters["right"]] in members]
        result.append((ids, linked))
    return result


def _gap(a: TableDrawing, b: TableDrawing) -> float:
    """Euclidean distance between the bounds of two drawn table shapes."""
    dx = max(0.0, a.x - b.x - b.width, b.x - a.x - a.width)
    dy = max(0.0, a.y - b.y - b.height, b.y - a.y - a.height)
    return hypot(dx, dy)


def neighbouring_tables(layout: VenueLayout | None, tables: list[Table]) -> dict[int, set[int]]:
    """Connect each drawing to its nearest drawn neighbour on the same floor.

    Nearest is derived from rectangle bounds; equal-distance ties all count.
    The graph is symmetric, and never joins drawings on different floors.
    No additional manual proximity or threshold field is needed.
    """
    graph = {j: set() for j in range(len(tables))}
    if layout is None:
        return graph
    index = {table.id: j for j, table in enumerate(tables)}
    for floor in layout.floors:
        drawings = [(index[d.table_id], d) for d in floor.tables if d.table_id in index]
        for i, a in drawings:
            distances = [(j, _gap(a, b)) for j, b in drawings if j != i]
            if not distances:
                continue
            shortest = min(distance for _, distance in distances)
            for j, distance in distances:
                if abs(distance - shortest) <= 1e-7:
                    graph[i].add(j)
                    graph[j].add(i)
    return graph


def largest_connected_capacity(graph: dict[int, set[int]], tables: list[Table]) -> int:
    """Upper bound for a connected cluster, not a claim that all groups pack."""
    seen = set()
    maximum = 0
    for start in graph:
        if start in seen:
            continue
        todo, capacity = [start], 0
        while todo:
            j = todo.pop()
            if j in seen:
                continue
            seen.add(j)
            capacity += tables[j].capacity
            todo.extend(graph[j] - seen)
        maximum = max(maximum, capacity)
    return maximum
