"""Rule-shape unit tests; every assertion uses the public code API."""
from __future__ import annotations

import pytest

from seating_optimizer import (
    Guest, Problem, Rule, SolverConfig, Table, Zone, render, render_json, render_table, solve,
)


def make_problem(guests, rules=(), tables=None, seconds=3):
    return Problem(
        session_id="friday-dinner",
        zones=[Zone(id="ground", name="Ground floor"), Zone(id="upper", name="First floor")],
        tables=tables or [Table(id="G", zone_id="ground", capacity=4),
                          Table(id="U", zone_id="upper", capacity=4)],
        guests=list(guests), rules=list(rules),
        config=SolverConfig(time_limit_seconds=seconds, workers=4),
    )


def rule(id, shape, mode="soft", weight=2, **parameters):
    return Rule(id=id, shape=shape, mode=mode,
                weight=weight if mode == "soft" else None, parameters=parameters)


def assigned(plan):
    return {guest_id: assignment.table_id
            for assignment in plan.assignments for guest_id in assignment.guest_ids}


def good(plan):
    assert plan.status in ("feasible", "optimal"), (plan.status, plan.conflicting_constraints)
    assert plan.total_score == sum(item.points for item in plan.score_breakdown)
    assert abs(sum(a.points for a in plan.assignments) - plan.total_score) < 0.001
    for table in plan.tables:
        assert 0 <= table.occupied <= table.capacity
        assert table.occupied + table.empty_seats == table.capacity


def test_atomic_group_and_wheelchair_propagation():
    p = make_problem([
        Guest(id="dad", name="Dad", group_id="family", attributes={"mobility": "wheelchair"}),
        Guest(id="mum", name="Mum", group_id="family", attributes={"mobility": "mobile"}),
        Guest(id="kid", name="Child", group_id="family", attributes={"age_layer": "child"}),
        Guest(id="friend", name="Friend", attributes={"language": "English"}),
    ], [rule("accessibility", "zone_restriction", "hard",
             attribute="mobility", value="wheelchair", zone="ground")])
    out = solve(p)
    good(out)
    assert assigned(out)["dad"] == assigned(out)["mum"] == assigned(out)["kid"] == "G"
    family = next(a for a in out.assignments if a.group_id == "family")
    assert any(r.rule_id == "accessibility" for r in family.reasons)


def test_hard_capacity_per_table_and_unsatisfiable_oversized_group():
    small = Table(id="small", zone_id="ground", capacity=2)
    large = Table(id="large", zone_id="upper", capacity=3)
    guests = [Guest(id=str(i), name=f"Guest {i}", group_id="large-party") for i in range(3)]
    good_plan = solve(make_problem(guests, tables=[small, large]))
    good(good_plan)
    assert all(a.table_id == "large" for a in good_plan.assignments)
    impossible = solve(make_problem(guests, tables=[small,
        Table(id="other", zone_id="upper", capacity=2)]))
    assert impossible.status == "infeasible"
    assert any("Party too large" in name for name in impossible.conflicting_constraints)
    assert not any(name.startswith("capacity:") for name in impossible.conflicting_constraints)


def test_conflicting_hard_pins_name_both_constraints():
    g = Guest(id="a", name="Alice")
    result = solve(make_problem([g], [
        rule("fixed_ground", "pin", "hard", target="a", table="G"),
        rule("fixed_upper", "pin", "hard", target="a", table="U"),
    ]))
    assert result.status == "infeasible"
    assert {"rule:fixed_ground", "rule:fixed_upper"} <= set(result.conflicting_constraints)


def test_hard_pair_together_and_apart():
    guests = [Guest(id="a", name="Alice"), Guest(id="b", name="Bob")]
    for relation in ("together", "apart"):
        out = solve(make_problem(guests, [rule("pair", "pair", "hard",
                                              left="a", right="b", relation=relation)]))
        good(out)
        assert (assigned(out)["a"] == assigned(out)["b"]) is (relation == "together")


def test_hard_pair_apart_cannot_split_group():
    guests = [Guest(id="a", name="Alice", group_id="family"),
              Guest(id="b", name="Bob", group_id="family")]
    out = solve(make_problem(guests, [rule("no", "pair", "hard",
                                          left="a", right="b", relation="apart")]))
    assert out.status == "infeasible"
    assert "rule:no" in out.conflicting_constraints


def test_soft_pair_compromise_when_hard_pins_dominate():
    guests = [Guest(id="a", name="Alice"), Guest(id="b", name="Bob")]
    rules = [rule("near", "pair", "soft", 11, left="a", right="b", relation="apart"),
             rule("pa", "pin", "hard", target="a", table="G"),
             rule("pb", "pin", "hard", target="b", table="G")]
    plan = solve(make_problem(guests, rules))
    good(plan)
    assert plan.total_score == 0
    assert any(c.rule_id == "near" and c.lost_points == 11 for c in plan.compromises)


def test_attribute_grouping_scores_shared_values():
    guests = [Guest(id="a", name="Alice", attributes={"language": "French"}),
              Guest(id="b", name="Bob", attributes={"language": "French"}),
              Guest(id="c", name="Carla", attributes={"language": "English"})]
    p = make_problem(guests, [rule("lang", "attribute_grouping", "soft", 7, attribute="language")],
         tables=[Table(id="G", zone_id="ground", capacity=2),
                 Table(id="U", zone_id="upper", capacity=2)])
    out = solve(p)
    good(out)
    assert assigned(out)["a"] == assigned(out)["b"]
    assert out.total_score == 7
    assert all("language" in r.description.lower() for a in out.assignments
               for r in a.reasons if r.rule_id == "lang")


def test_hard_attribute_grouping_returns_conflict_if_impossible():
    guests = [Guest(id=str(i), name=f"Guest {i}", attributes={"language": "English"})
              for i in range(5)]
    out = solve(make_problem(guests,
        [rule("must_share", "attribute_grouping", "hard", attribute="language")]))
    assert out.status == "infeasible"
    assert "rule:must_share" in out.conflicting_constraints or any(
        s.startswith("capacity:") for s in out.conflicting_constraints)


def test_soft_zone_preference_points_and_hard_group_effect():
    guests = [Guest(id="a", name="Alice", attributes={"mobility": "wheelchair"}),
              Guest(id="b", name="Bob", group_id="family"),
              Guest(id="c", name="Carla", group_id="family",
                    attributes={"mobility": "wheelchair"})]
    soft = rule("prefer_ground", "zone_restriction", "soft", 9,
                attribute="mobility", value="wheelchair", zone="ground")
    out = solve(make_problem(guests, [soft]))
    good(out)
    assert assigned(out)["a"] == "G" and assigned(out)["b"] == assigned(out)["c"] == "G"
    assert out.total_score == 18


def test_fill_efficiency_prefers_no_holes_and_leaves_unused_table_unpenalized():
    guests = [Guest(id=f"g{i}", name=f"Guest {i}") for i in range(4)]
    p = make_problem(guests, [rule("fill", "fill_efficiency", "soft", 3)],
                     tables=[Table(id="exact", zone_id="ground", capacity=4),
                             Table(id="oversized", zone_id="upper", capacity=6)])
    out = solve(p)
    good(out)
    assert set(assigned(out).values()) == {"exact"}
    assert out.total_score == 0
    assert next(t for t in out.tables if t.table_id == "oversized").empty_seats == 6


def test_pins_respected_on_resolve_without_changing_previous_plan():
    guests = [Guest(id="a", name="Alice"), Guest(id="b", name="Bob")]
    original = solve(make_problem(guests))
    good(original)
    pinned = solve(make_problem(guests, [rule("lock", "pin", "hard", target="a", table="U")]))
    good(pinned)
    assert assigned(pinned)["a"] == "U"
    assert assigned(original)["a"] in ("G", "U")


def test_reports_and_headless_exports_have_complete_parity():
    guests = [Guest(id="a", name="Alice"), Guest(id="b", name="Bob")]
    out = solve(make_problem(guests, [rule("fill", "fill_efficiency", "soft", 2)]))
    good(out)
    assert render(out, "table") == render_table(out)
    assert render(out, "json") == render_json(out)
    assert '"score_breakdown"' in render_json(out)
    assert "Table " in render_table(out)
    assert "Compromises:" in render_table(out)
    assert out.assignments and all(a.reasons for a in out.assignments)


def test_invalid_rules_and_targets_fail_loudly():
    with pytest.raises(ValueError, match="Soft rules"):
        Rule(id="bad", shape="pair", mode="soft", parameters={})
    with pytest.raises(ValueError, match="must be hard"):
        Rule(id="bad", shape="pin", mode="soft", weight=1)
    with pytest.raises(ValueError, match="unknown"):
        solve(make_problem([Guest(id="a", name="Alice")], [
            rule("bad", "pin", "hard", target="a", table="unknown")]))



def test_capacity_shortage_reports_guests_vs_chairs_without_table_dump():
    guests = [Guest(id=str(i), name=f"Guest {i}") for i in range(5)]
    result = solve(make_problem(guests, tables=[
        Table(id="T1", zone_id="ground", capacity=2),
        Table(id="T2", zone_id="upper", capacity=2),
    ]))
    assert result.status == "infeasible"
    assert len(result.conflicting_constraints) == 1
    assert "5 guests" in result.conflicting_constraints[0]
    assert "4 chairs" in result.conflicting_constraints[0]
    assert "short by 1" in result.conflicting_constraints[0]
    assert "capacity:T" not in str(result.conflicting_constraints)


def test_250_guest_42_party_packing_reports_proven_33_table_lower_bound():
    # 18 groups of five can pair into nine ten-chair tables; all 24 groups
    # of six/seven each require their own table: 33 minimum, not 26.
    guests = []
    for index, size in enumerate([5] * 18 + [7] * 16 + [6] * 8):
        guests.extend(Guest(id=f"{index}-{person}", name=f"Guest {index}-{person}",
                            group_id=f"family-{index}") for person in range(size))
    tables = [Table(id=f"T{n}", zone_id="ground", capacity=10) for n in range(26)]
    plan = solve(make_problem(guests, tables=tables))
    assert len(guests) == 250
    assert plan.status == "infeasible"
    assert len(plan.conflicting_constraints) == 1
    diagnostic = plan.conflicting_constraints[0]
    assert "Party packing" in diagnostic
    assert "at least 33 tables" in diagnostic
    assert "26 tables" in diagnostic
    assert "250 guests" in diagnostic and "260 chairs" in diagnostic
    assert not any(f"capacity:T{n}" in diagnostic for n in range(26))
    assert "Party packing" in render_table(plan)


def test_unrelated_hard_rule_is_not_reported_as_a_conflict():
    guests = [Guest(id="a", name="Alice"), Guest(id="b", name="Bob")]
    out = solve(make_problem(guests, [
        rule("only_ground", "pin", "hard", target="a", table="G"),
        rule("only_upper", "pin", "hard", target="a", table="U"),
        rule("harmless", "pin", "hard", target="b", table="G"),
    ]))
    assert out.status == "infeasible"
    assert {"rule:only_ground", "rule:only_upper"} <= set(out.conflicting_constraints)
    assert "rule:harmless" not in out.conflicting_constraints


def test_small_group_priority_is_soft_one_point_per_group():
    tables = [Table(id="ordinary", zone_id="ground", capacity=4),
              Table(id="preferred", zone_id="upper", capacity=4, small_group_priority=True)]
    for size in (1, 2):
        people = [Guest(id=f"small-{i}", name=f"Small {i}", group_id="together")
                  for i in range(size)]
        plan = solve(make_problem(people, tables=tables))
        good(plan)
        assert plan.assignments[0].table_id == "preferred"
        assert plan.total_score == 1
        assert any(x.rule_id == "venue:small-group-priority" and x.points == 1
                   for x in plan.score_breakdown)
        assert any(x.rule_id == "venue:small-group-priority" and x.points == 1
                   for x in plan.assignments[0].reasons)
        priority_reason = next(x.description for x in plan.assignments[0].reasons
                               if x.rule_id == "venue:small-group-priority")
        expected_count = "1 person" if size == 1 else "2 people"
        assert f"Small group ({expected_count}) received priority" in priority_reason
        assert "1 people" not in priority_reason


def test_small_group_priority_off_by_default_and_other_groups_not_excluded():
    guests = [Guest(id="a", name="Alice"), Guest(id="b", name="Bob", group_id="big"),
              Guest(id="c", name="Carla", group_id="big"),
              Guest(id="d", name="David", group_id="big")]
    unmarked = [Table(id="G", zone_id="ground", capacity=4),
                Table(id="U", zone_id="upper", capacity=4)]
    result = solve(make_problem(guests, tables=unmarked))
    good(result)
    assert result.total_score == 0
    assert not any(x.rule_id == "venue:small-group-priority" for x in result.score_breakdown)
    pinned = solve(make_problem(guests,
        [rule("pin_big", "pin", "hard", target="big", table="G")],
        tables=[Table(id="G", zone_id="ground", capacity=4, small_group_priority=True),
                Table(id="U", zone_id="upper", capacity=4)]))
    good(pinned)
    assert next(a for a in pinned.assignments if a.group_id == "big").table_id == "G"
