"""Fallback only for oversized together-linked sets of atomic groups."""
from seating_optimizer import (
    FloorLayout, Guest, Problem, Rule, SolverConfig, Table, TableDrawing,
    VenueLayout, Zone, solve,
)
from seating_optimizer.adjacency import neighbouring_tables


def problem(sizes, rules, *, max_capacity=4, layout=True, tables=None):
    tables = tables or [
        Table(id="A", zone_id="hall", capacity=max_capacity),
        Table(id="B", zone_id="hall", capacity=max_capacity),
        Table(id="C", zone_id="hall", capacity=max_capacity),
    ]
    zones = [Zone(id="hall", name="Hall")]
    floor = VenueLayout(floors=[FloorLayout(zone_id="hall", width=700, height=200, tables=[
        TableDrawing(table_id="A", x=10, y=10, width=60, height=60),
        TableDrawing(table_id="B", x=85, y=10, width=60, height=60),
        TableDrawing(table_id="C", x=500, y=10, width=60, height=60),
    ])]) if layout else None
    guests = [
        Guest(id=f"{group}{j}", name=f"{group} guest {j}", group_id=group)
        for group, size in sizes.items() for j in range(size)
    ]
    return Problem(session_id="meal", zones=zones, tables=tables, guests=guests,
                   rules=rules, layout=floor, config=SolverConfig(workers=1))


def together(left, right, *, hard=True):
    return Rule(id=f"{left}_{right}", shape="pair", mode="hard" if hard else "soft",
                weight=None if hard else 7,
                parameters={"left": left, "right": right, "relation": "together"})


def assigned(plan):
    return {item.group_id: item.table_id for item in plan.assignments}


def test_geometry_derives_nearest_neighbours_not_every_same_floor_pair():
    p = problem({"alpha": 1}, [])
    graph = neighbouring_tables(p.layout, p.tables)
    assert graph == {0: {1}, 1: {0, 2}, 2: {1}}


def test_hard_oversized_pair_falls_back_to_neighbour_tables():
    plan = solve(problem({"alpha": 3, "beta": 3}, [together("alpha", "beta")]))
    assert plan.status in ("feasible", "optimal"), plan.conflicting_constraints
    seats = assigned(plan)
    assert seats["alpha"] != seats["beta"]
    assert {seats["alpha"], seats["beta"]} in ({"A", "B"}, {"B", "C"})
    assert any("split across adjacent tables" in r.description for a in plan.assignments for r in a.reasons)


def test_transitive_three_group_party_uses_connected_adjacency():
    plan = solve(problem({"alpha": 2, "beta": 2, "gamma": 2},
                         [together("alpha", "beta"), together("beta", "gamma")]))
    assert plan.status in ("optimal", "feasible"), plan.conflicting_constraints
    table_ids = set(assigned(plan).values())
    assert len(table_ids) == 2
    assert table_ids in ({"A", "B"}, {"B", "C"})
    assert plan.total_score == 0


def test_single_table_placement_remains_mandatory_when_capacity_exists():
    tables = [Table(id="A", zone_id="hall", capacity=4),
              Table(id="B", zone_id="hall", capacity=4),
              Table(id="C", zone_id="hall", capacity=6)]
    plan = solve(problem({"alpha": 3, "beta": 3}, [together("alpha", "beta")],
                         tables=tables))
    assert plan.status in ("optimal", "feasible"), plan.conflicting_constraints
    assert assigned(plan) == {"alpha": "C", "beta": "C"}
    assert any("same table" in r.description for a in plan.assignments for r in a.reasons)


def test_soft_fallback_without_geometry_reports_not_achievable():
    plan = solve(problem({"alpha": 3, "beta": 3},
                         [together("alpha", "beta", hard=False)], layout=False))
    assert plan.status in ("optimal", "feasible"), plan.conflicting_constraints
    assert plan.total_score == 0
    assert any("not achievable" in c.description for c in plan.compromises)
    assert any(c.lost_points == 7 for c in plan.compromises)


def test_hard_oversized_cluster_without_geometry_reports_unachievable():
    plan = solve(problem({"alpha": 3, "beta": 3},
                         [together("alpha", "beta")], layout=False))
    assert plan.status == "infeasible"
    assert any("Not achievable" in item for item in plan.conflicting_constraints)


def test_atomic_oversized_group_still_fails_without_splitting_members():
    plan = solve(problem({"alpha": 5}, []))
    assert plan.status == "infeasible"
    assert any("atomic group" in c for c in plan.conflicting_constraints)
