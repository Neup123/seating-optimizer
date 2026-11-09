"""Adjacent-table hard cases: linked atomic clusters and lone oversized groups."""
from seating_optimizer import (
    FloorLayout, Guest, Problem, Rule, SolverConfig, Table, TableDrawing,
    VenueLayout, Zone, render, solve,
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
    assert len(table_ids) >= 2
    assert table_ids != {"A", "C"}  # a disconnected pair is forbidden
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


def test_lone_oversized_group_splits_across_adjacent_tables_with_real_guest_assignments():
    plan = solve(problem({"alpha": 5}, []))
    assert plan.status in ("optimal", "feasible"), plan.conflicting_constraints
    pieces = [a for a in plan.assignments if a.group_id == "alpha"]
    assert len(pieces) == 2
    tables_used = {a.table_id for a in pieces}
    assert tables_used in ({"A", "B"}, {"B", "C"})
    assert {guest_id for part in pieces for guest_id in part.guest_ids} == {
        f"alpha{i}" for i in range(5)}
    assert sum(len(part.guest_ids) for part in pieces) == 5
    assert all(part.guest_ids for part in pieces)
    assert all(
        any("split across adjacent tables" in reason.description
            and all(table_id in reason.description for table_id in tables_used)
            and "because no single table fits" in reason.description
            for reason in part.reasons)
        for part in pieces
    )
    assert sum(t.occupied for t in plan.tables) == 5
    assert all(0 <= t.occupied <= t.capacity for t in plan.tables)
    html = render(plan, "people-list-html")
    assert all(html.count(f'data-guest-id="alpha{i}"') == 1 for i in range(5))
    assert "split across adjacent tables" in render(plan, "table")


def test_lone_oversized_group_cannot_use_non_adjacent_tables_via_forbidden_middle():
    tables = [Table(id="A", zone_id="hall", capacity=4, properties=["accessible"]),
              Table(id="B", zone_id="hall", capacity=1),
              Table(id="C", zone_id="hall", capacity=4, properties=["accessible"])]
    p = problem({"alpha": 8}, [], tables=tables)
    # A--B--C are the drawn neighbours. Eight guests fit A+C in total,
    # but the hard need forbids B, so that non-adjacent pair is NOT valid.
    p.guests[0].attributes["mobility"] = "wheelchair"
    p.rules.append(Rule(id="access", shape="table_property_need", mode="hard",
                        parameters={"attribute": "mobility", "value": "wheelchair",
                                    "property": "accessible"}))
    plan = solve(p)
    assert plan.status == "infeasible"
    assert any("Party too large" in note and "adjacent-table" in note
               and "access" in note for note in plan.conflicting_constraints)


def test_lone_oversized_group_cannot_cross_floors():
    tables = [Table(id="A", zone_id="ground", capacity=4),
              Table(id="B", zone_id="upper", capacity=4)]
    layout = VenueLayout(floors=[
        FloorLayout(zone_id="ground", width=200, height=200,
                    tables=[TableDrawing(table_id="A", x=10, y=10, width=60, height=60)]),
        FloorLayout(zone_id="upper", width=200, height=200,
                    tables=[TableDrawing(table_id="B", x=10, y=10, width=60, height=60)]),
    ])
    p = Problem(session_id="meal", zones=[Zone(id="ground", name="Ground"),
                Zone(id="upper", name="Upper")], tables=tables,
                guests=[Guest(id=f"g{i}", name=f"Guest {i}", group_id="alpha")
                        for i in range(5)], layout=layout)
    plan = solve(p)
    assert plan.status == "infeasible"
    assert any("adjacent-table" in note for note in plan.conflicting_constraints)


def test_group_fitting_any_single_table_remains_atomic_even_if_adjacent_options_exist():
    plan = solve(problem({"alpha": 4}, []))
    assert plan.status in ("optimal", "feasible")
    assert len(plan.assignments) == 1
    assert plan.assignments[0].group_id == "alpha"
    assert len(plan.assignments[0].guest_ids) == 4
    assert not any("split across adjacent" in reason.description
                   for reason in plan.assignments[0].reasons)


def test_lone_group_split_preserves_hard_guest_needs_and_soft_pair_apart():
    tables = [Table(id="A", zone_id="hall", capacity=4, properties=["accessible"]),
              Table(id="B", zone_id="hall", capacity=4, properties=["accessible"]),
              Table(id="C", zone_id="hall", capacity=4)]
    p = problem({"alpha": 5, "beta": 1}, [], tables=tables)
    p.guests[0].attributes["mobility"] = "wheelchair"
    p.rules.extend([
        Rule(id="access", shape="table_property_need", mode="hard",
             parameters={"attribute": "mobility", "value": "wheelchair",
                         "property": "accessible"}),
        Rule(id="apart", shape="pair", mode="soft", weight=7,
             parameters={"left": "alpha", "right": "beta", "relation": "apart"}),
    ])
    plan = solve(p)
    assert plan.status in ("optimal", "feasible"), plan.conflicting_constraints
    table_sets = {}
    for entry in plan.assignments:
        table_sets.setdefault(entry.group_id, set()).add(entry.table_id)
    assert table_sets["alpha"] == {"A", "B"}
    assert not (table_sets["alpha"] & table_sets["beta"])
    assert next(item.points for item in plan.score_breakdown if item.rule_id == "apart") == 7
    assert abs(sum(a.points for a in plan.assignments) - plan.total_score) < 0.001


def test_hard_pin_still_binds_all_members_of_oversized_group():
    p = problem({"alpha": 5}, [
        Rule(id="pin", shape="pin", mode="hard",
             parameters={"target": "alpha0", "table": "A"}),
    ])
    plan = solve(p)
    assert plan.status == "infeasible"
    assert any("Party too large" in reason for reason in plan.conflicting_constraints)


def test_existing_linked_cluster_regression_keeps_groups_atomic():
    rules = [together("alpha", "beta"), together("beta", "gamma")]
    plan = solve(problem({"alpha": 2, "beta": 2, "gamma": 2}, rules))
    assert plan.status in ("optimal", "feasible"), plan.conflicting_constraints
    assert len(plan.assignments) == 3
    assert {a.group_id for a in plan.assignments} == {"alpha", "beta", "gamma"}
    assert all(len(a.guest_ids) == 2 for a in plan.assignments)
    assert len({a.table_id for a in plan.assignments}) > 1
    assert all(any("split across adjacent tables" in r.description for r in a.reasons)
               for a in plan.assignments)
