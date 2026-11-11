"""Generic CP-SAT adjacency parity: named linked clusters and oversized parties."""
from __future__ import annotations

from seating_optimizer import (
    FloorLayout, GenericProblem, GenericRule, Guest, SolverConfig,
    Table, TableDrawing, VenueLayout, Zone, solve_generic,
)


def event(sizes, rules, *, draw=True):
    guests = [Guest(id=f"{gid}{j}", name=f"{gid} {j}", group_id=gid)
              for gid, count in sizes.items() for j in range(count)]
    tables = [Table(id=tid, zone_id="hall", capacity=4) for tid in ("A", "B", "C")]
    layout = (VenueLayout(floors=[
        FloorLayout(zone_id="hall", width=700, height=200, tables=[
            TableDrawing(table_id="A", x=10, y=10, width=60, height=60),
            TableDrawing(table_id="B", x=85, y=10, width=60, height=60),
            TableDrawing(table_id="C", x=500, y=10, width=60, height=60),
        ])
    ]) if draw else None)
    return GenericProblem(
        session_id="generic-adjacent", zones=[Zone(id="hall", name="Hall")],
        tables=tables, guests=guests, rules=rules, layout=layout,
        config=SolverConfig(time_limit_seconds=5, workers=1, random_seed=42),
    )


def linked(a, b, *, hard):
    return GenericRule(
        id=a + "-" + b, name="Together " + a + " " + b,
        engine="inter", mechanism="pair_relation", mode="hard" if hard else "soft",
        weight=None if hard else 7, polarity=None if hard else "reward",
        targets=[a, b], relation="together",
    )


def per_group(plan):
    return {a.group_id: a.table_id for a in plan.assignments}


def test_hard_named_pair_above_single_table_uses_connected_adjacent_whole_tables():
    result = solve_generic(event({"alpha": 3, "beta": 3},
                                 [linked("alpha", "beta", hard=True)]))
    assert result.status in ("optimal", "feasible"), result.conflicting_constraints
    places = per_group(result)
    assert places["alpha"] != places["beta"]
    assert {places["alpha"], places["beta"]} in ({"A", "B"}, {"B", "C"})
    assert result.total_score == 0


def test_transitive_linked_triple_forms_connected_cluster():
    result = solve_generic(event(
        {"alpha": 2, "beta": 2, "gamma": 2},
        [linked("alpha", "beta", hard=True),
         linked("beta", "gamma", hard=True)],
    ))
    assert result.status in ("optimal", "feasible"), result.conflicting_constraints
    places = set(per_group(result).values())
    assert len(places) >= 2
    assert places != {"A", "C"}


def test_soft_named_pair_no_geometry_never_awards_unachievable_bonus():
    result = solve_generic(event({"alpha": 3, "beta": 3},
                                 [linked("alpha", "beta", hard=False)],
                                 draw=False))
    assert result.status in ("optimal", "feasible"), result.message
    assert result.total_score == 0


def test_hard_named_pair_without_geometry_conflicts_by_instance_name():
    result = solve_generic(event({"alpha": 3, "beta": 3},
                                 [linked("alpha", "beta", hard=True)],
                                 draw=False))
    assert result.status == "infeasible", result.message
    assert "Together alpha beta" in result.conflicting_constraints


def test_single_oversized_family_uses_connected_tables_without_automatic_permission():
    result = solve_generic(event({"alpha": 5}, []))
    assert result.status in ("optimal", "feasible"), result.conflicting_constraints
    portions = [a for a in result.assignments if a.group_id == "alpha"]
    assert len(portions) == 2
    assert {a.table_id for a in portions} in ({"A", "B"}, {"B", "C"})
    assert sorted(g for a in portions for g in a.guest_ids) == [
        f"alpha{i}" for i in range(5)]
    assert result.total_score == 0
