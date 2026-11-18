"""Regression: a restriction's permitted tables, not venue-wide maximum,
determine automatic adjacent split eligibility. Test both v1 and generic v2.
"""
from __future__ import annotations

from seating_optimizer import (
    FloorLayout, GenericProblem, GenericRule, Guest, Problem, Rule,
    SolverConfig, Table, TableDrawing, VenueLayout, Zone,
    solve, solve_generic,
)


def venue():
    return (
        [Zone(id="ground", name="Ground"), Zone(id="upper", name="Upper")],
        [
            Table(id="G", zone_id="ground", capacity=12),
            Table(id="U1", zone_id="upper", capacity=6, properties=["quiet"]),
            Table(id="U2", zone_id="upper", capacity=6, properties=["quiet"]),
        ],
        VenueLayout(floors=[
            FloorLayout(zone_id="ground", width=160, height=130,
                        tables=[TableDrawing(table_id="G", x=0, y=0, width=100, height=100)]),
            FloorLayout(zone_id="upper", width=250, height=130,
                        tables=[TableDrawing(table_id="U1", x=0, y=0, width=100, height=100),
                                TableDrawing(table_id="U2", x=102, y=0, width=100, height=100)]),
        ])
    )


def guest_list():
    # Only one member carries the hard need. All nine must use upper tables.
    return [Guest(id=f"c{i}", name=f"Clan {i}", group_id="clan",
                  attributes={"floor": "Upper"} if i == 0 else {}) for i in range(9)]


def check(plan):
    assert plan.status in ("optimal", "feasible"), plan.conflicting_constraints
    clan = [a for a in plan.assignments if a.group_id == "clan"]
    assert {a.table_id for a in clan} == {"U1", "U2"}
    assert sorted(gid for a in clan for gid in a.guest_ids) == sorted(g.id for g in guest_list())
    assert not any(a.table_id == "G" for a in clan)
    assert all(0 <= table.occupied <= table.capacity for table in plan.tables)


def test_legacy_hard_zone_uses_admissible_capacity_and_propagates_to_clan():
    zones, tables, layout = venue()
    plan = solve(Problem(
        session_id="legacy-zone", zones=zones, tables=tables, layout=layout,
        guests=guest_list(),
        rules=[Rule(id="upper-only", shape="zone_restriction", mode="hard",
                    parameters={"attribute": "floor", "value": "Upper", "zone": "upper"})],
        config=SolverConfig(time_limit_seconds=5, workers=2),
    ))
    check(plan)


def test_generic_hard_zone_uses_admissible_capacity_and_propagates_to_clan():
    zones, tables, layout = venue()
    plan = solve_generic(GenericProblem(
        session_id="generic-zone", zones=zones, tables=tables, layout=layout,
        guests=guest_list(),
        rules=[GenericRule(id="upper-only", name="Upper floor only",
                           engine="venue", mechanism="placement_by_criterion",
                           mode="hard", zones=["upper"],
                           criterion={"subject": "guest", "field": "floor",
                                      "op": "==", "value": "Upper"})],
        config=SolverConfig(time_limit_seconds=5, workers=2),
    ))
    check(plan)


def test_generic_hard_table_property_also_propagates_across_split_clan():
    zones, tables, layout = venue()
    plan = solve_generic(GenericProblem(
        session_id="generic-property", zones=zones, tables=tables, layout=layout,
        guests=guest_list(),
        rules=[GenericRule(id="quiet-tables", name="Quiet tables for guest",
                           engine="venue", mechanism="property_need",
                           mode="hard", property="quiet",
                           criterion={"subject": "guest", "field": "floor",
                                      "op": "==", "value": "Upper"})],
        config=SolverConfig(time_limit_seconds=5, workers=2),
    ))
    check(plan)
