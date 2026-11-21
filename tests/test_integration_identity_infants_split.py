"""Cross-PR acceptance: retained identity, lap infants, hard admissibility, lifecycle.

These cases exercise the combined production code paths. They do NOT cover
browser rendering, arbitrary venue geometry or merging into main.
"""
from __future__ import annotations

import pytest

from seating_optimizer import (
    FloorLayout, GenericProblem, GenericRule, Guest, Problem, Rule, SolverConfig,
    Table, TableDrawing, VenueLayout, Zone, import_registrations, solve, solve_generic,
)


def venue():
    zones = [Zone(id="ground", name="Ground"), Zone(id="upper", name="Upper")]
    tables = [
        Table(id="G", zone_id="ground", capacity=12),
        Table(id="U1", zone_id="upper", capacity=6),
        Table(id="U2", zone_id="upper", capacity=6),
    ]
    layout = VenueLayout(floors=[
        FloorLayout(zone_id="ground", width=160, height=130, tables=[
            TableDrawing(table_id="G", x=0, y=0, width=100, height=100)]),
        FloorLayout(zone_id="upper", width=250, height=130, tables=[
            TableDrawing(table_id="U1", x=0, y=0, width=100, height=100),
            TableDrawing(table_id="U2", x=102, y=0, width=100, height=100)]),
    ])
    return zones, tables, layout


def guests():
    return [
        Guest(id=f"c{i}", name=f"Clan {i}", group_id="clan",
              attributes={"floor": "Upper"} if i == 0 else {},
              requires_chair=i != 8)
        for i in range(9)
    ]


@pytest.mark.parametrize("engine", ["v1", "v2"])
def test_admissible_split_with_lap_infant_is_same_physical_capacity(engine):
    zones, tables, layout = venue()
    members = guests()
    if engine == "v1":
        problem = Problem(
            session_id="combined-v1", zones=zones, tables=tables, layout=layout,
            guests=members, rules=[Rule(
                id="upper-only", shape="zone_restriction", mode="hard",
                parameters={"attribute": "floor", "value": "Upper", "zone": "upper"})],
            config=SolverConfig(time_limit_seconds=5, workers=1))
        plan = solve(problem)
    else:
        problem = GenericProblem(
            session_id="combined-v2", zones=zones, tables=tables, layout=layout,
            guests=members, rules=[GenericRule(
                id="upper-only", name="Upper only", engine="venue",
                mechanism="placement_by_criterion", mode="hard", zones=["upper"],
                criterion={"subject": "guest", "field": "floor",
                           "op": "==", "value": "Upper"})],
            config=SolverConfig(time_limit_seconds=5, workers=1))
        plan = solve_generic(problem)

    assert plan.status in ("optimal", "feasible"), plan.message
    clan = [row for row in plan.assignments if row.group_id == "clan"]
    assert len(clan) >= 2, "8 physical seats need at least two admissible 6-chair tables"
    assert {row.table_id for row in clan} == {"U1", "U2"}
    assert {gid for row in clan for gid in row.guest_ids} == {g.id for g in members}
    assert sum(table.occupied for table in plan.tables) == 8
    assert all(0 <= table.occupied <= table.capacity for table in plan.tables)
    seats_by_guest = {gid: row.table_id for row in clan for gid in row.guest_ids}
    assert seats_by_guest["c8"] == seats_by_guest["c0"], "Lap infant follows chair-using member"


def test_reordered_import_preserves_identity_and_no_chair_semantics():
    a = import_registrations(
        b"Name,Size,Lap infants\nFamily One,3,1\nFamily Two,2,0\n", "a.csv")
    b = import_registrations(
        b"Name,Size,Lap infants\nNew Family,1,0\nFamily Two,2,0\nFamily One,3,1\n", "b.csv")
    assert not a.has_errors and not b.has_errors, (a.issues, b.issues)
    before = {g.name: (g.id, g.group_id, g.requires_chair) for g in a.guests}
    after = {g.name: (g.id, g.group_id, g.requires_chair) for g in b.guests}
    assert before.items() <= after.items()
    family = [g for g in b.guests if g.group_name == "Family One"]
    assert len(family) == 3 and sum(g.requires_chair for g in family) == 2
