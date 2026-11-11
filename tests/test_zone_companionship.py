"""Topic 6 / #70: only operator-authored zone-companionship rules penalize lone groups."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from seating_optimizer import Guest, Problem, Rule, SolverConfig, Table, Zone, solve
from seating_optimizer.api.app import app
from test_api_contract import validate


client = TestClient(app)


def guests(group: str, count: int, *, category: str = "") -> list[Guest]:
    return [
        Guest(id=f"{group}-{i}", name=f"{group} {i}", group_id=group,
              attributes={"category": category} if category else {})
        for i in range(count)
    ]


def companion(weight: int, *, excluded=(), rule_id: str = "companionship") -> Rule:
    return Rule(id=rule_id, shape="zone_companionship", mode="soft",
                weight=weight, parameters={"exclude_groups": list(excluded)})


def pin(group: str, table: str) -> Rule:
    return Rule(id=f"pin-{group}", shape="pin", mode="hard",
                parameters={"target": group, "table": table})


def make_problem(tables: list[Table], people: list[Guest], rules: list[Rule] | None = None,
                 *, splittable=()) -> Problem:
    zones = list(dict.fromkeys(table.zone_id for table in tables))
    return Problem(
        session_id="companionship-test",
        zones=[Zone(id=zone, name=zone) for zone in zones],
        tables=tables, guests=people, rules=rules or [],
        splittable_groups=list(splittable),
        config=SolverConfig(time_limit_seconds=5, workers=1, random_seed=42))


def fixed_lone(weight=9, *, excluded=(), include_rule=True):
    tables = [Table(id="A", zone_id="floor-a", capacity=4),
              Table(id="B", zone_id="floor-b", capacity=2)]
    people = guests("a1", 2) + guests("a2", 2) + guests("alone", 2)
    rules = [pin("a1", "A"), pin("a2", "A"), pin("alone", "B")]
    if include_rule:
        rules.append(companion(weight, excluded=excluded))
    return make_problem(tables, people, rules)


def entry(plan, rule_id="companionship"):
    return next(row for row in plan.score_breakdown if row.rule_id == rule_id)


def reasons(plan, gid, rule_id="companionship"):
    return [reason for assignment in plan.assignments if assignment.group_id == gid
            for reason in assignment.reasons if reason.rule_id == rule_id]


def test_lonely_group_penalized_only_when_another_zone_used():
    result = solve(fixed_lone(weight=13))
    assert result.status in ("optimal", "feasible")
    assert entry(result).points == -13
    assert result.total_score == -13
    assert sum(reason.points for reason in reasons(result, "alone")) == -13
    assert all(not reasons(result, gid) for gid in ("a1", "a2"))
    assert len([c for c in result.compromises if c.rule_id == "companionship"]) == 1
    assert result.compromises[0].lost_points == 13
    assert "floor-b" in result.compromises[0].description
    assert sum(a.points for a in result.assignments) == result.total_score


def test_solver_prefers_a_feasible_plan_without_a_lone_zone_over_a_soft_reward():
    tables = [Table(id="A", zone_id="floor-a", capacity=6),
              Table(id="B", zone_id="floor-b", capacity=2)]
    people = guests("a1", 2) + guests("a2", 2) + guests("alone", 2, category="lonely")
    small_reward = Rule(id="reward-floor-b", shape="zone_restriction", mode="soft",
                        weight=1, parameters={"attribute": "category",
                                              "value": "lonely", "zone": "floor-b"})
    baseline = solve(make_problem(tables, people, [small_reward]))
    assert baseline.total_score == 2
    assert next(a.table_id for a in baseline.assignments if a.group_id == "alone") == "B"

    result = solve(make_problem(tables, people, [small_reward, companion(10)]))
    assert result.status in ("optimal", "feasible")
    assert {a.table_id for a in result.assignments} == {"A"}
    assert result.total_score == 0
    assert entry(result).points == 0
    assert not reasons(result, "alone")
    assert not any(c.rule_id == "companionship" for c in result.compromises)


def test_seven_person_family_alone_while_other_floor_full_is_penalized():
    tables = [Table(id="A1", zone_id="floor-a", capacity=5),
              Table(id="A2", zone_id="floor-a", capacity=5),
              Table(id="B", zone_id="floor-b", capacity=7)]
    people = guests("family-one", 5) + guests("family-two", 5) + guests("family-seven", 7)
    result = solve(make_problem(tables, people, [companion(17)]))
    assert result.status in ("optimal", "feasible")
    assert next(a.table_id for a in result.assignments if a.group_id == "family-seven") == "B"
    assert len([a for a in result.assignments if a.table_id.startswith("A")]) == 2
    assert entry(result).points == -17
    assert result.total_score == -17
    assert sum(r.points for r in reasons(result, "family-seven")) == -17
    assert not reasons(result, "family-one")
    assert not reasons(result, "family-two")


def test_all_people_on_one_zone_or_one_used_zone_score_exactly_zero():
    people = guests("one", 2) + guests("two", 2)
    one_zone = make_problem([Table(id="A", zone_id="floor-a", capacity=4)],
                            people, [companion(37)])
    a = solve(one_zone)
    assert a.status in ("optimal", "feasible")
    assert a.total_score == 0
    assert entry(a).points == 0
    assert not any(c.rule_id == "companionship" for c in a.compromises)

    two_zones = make_problem([Table(id="A", zone_id="floor-a", capacity=4),
                              Table(id="B", zone_id="floor-b", capacity=4)],
                             people, [pin("one", "A"), pin("two", "A"), companion(37)])
    b = solve(two_zones)
    assert b.status in ("optimal", "feasible")
    assert b.total_score == 0
    assert entry(b).points == 0
    assert {a.table_id for a in b.assignments} == {"A"}


def test_explicit_exclusion_suppresses_penalty_without_removing_group_presence():
    result = solve(fixed_lone(weight=14, excluded=["alone"]))
    assert result.status in ("optimal", "feasible")
    assert entry(result).points == 0
    assert result.total_score == 0
    assert not reasons(result, "alone")
    assert not any(c.rule_id == "companionship" for c in result.compromises)
    # Exclusions do not change group population: when two zones each have
    # one group, excluding A still leaves B lonely.
    tables = [Table(id="A", zone_id="a", capacity=2),
              Table(id="B", zone_id="b", capacity=2)]
    people = guests("excluded", 2) + guests("other", 2)
    rules = [pin("excluded", "A"), pin("other", "B"),
             companion(14, excluded=["excluded"])]
    other = solve(make_problem(tables, people, rules))
    assert entry(other).points == -14
    assert reasons(other, "other")[0].points == -14
    assert not reasons(other, "excluded")


def test_weight_proportional_and_absent_instance_has_no_hidden_penalty():
    result_3 = solve(fixed_lone(weight=3))
    result_11 = solve(fixed_lone(weight=11))
    assert entry(result_3).points == -3
    assert entry(result_11).points == -11
    assert result_11.total_score * 3 == result_3.total_score * 11
    assert [a.table_id for a in result_3.assignments] == [a.table_id for a in result_11.assignments]
    absent = solve(fixed_lone(include_rule=False))
    assert absent.status in ("optimal", "feasible")
    assert absent.total_score == 0
    assert not [s for s in absent.score_breakdown if s.rule_id == "companionship"]
    assert not any(c.rule_id == "companionship" for c in absent.compromises)


def test_two_separate_lone_zones_charge_two_groups_not_one_event():
    tables = [Table(id="A", zone_id="floor-a", capacity=2),
              Table(id="B", zone_id="floor-b", capacity=2)]
    people = guests("left", 2) + guests("right", 2)
    rules = [pin("left", "A"), pin("right", "B"), companion(6)]
    plan = solve(make_problem(tables, people, rules))
    assert plan.status in ("optimal", "feasible")
    assert entry(plan).points == -12
    assert plan.total_score == -12
    assert reasons(plan, "left")[0].points == -6
    assert reasons(plan, "right")[0].points == -6
    assert len([c for c in plan.compromises if c.rule_id == "companionship"]) == 2
    assert sum(a.points for a in plan.assignments) == -12


def test_split_party_occupying_two_tables_on_same_floor_counts_as_one_group():
    tables = [Table(id="A1", zone_id="a", capacity=2),
              Table(id="A2", zone_id="a", capacity=2),
              Table(id="B", zone_id="b", capacity=2)]
    people = guests("big", 4) + guests("b1", 1) + guests("b2", 1)
    rules = [pin("b1", "B"), pin("b2", "B"), companion(7)]
    result = solve(make_problem(tables, people, rules, splittable=["big"]))
    assert result.status in ("optimal", "feasible"), result.message
    assert {a.table_id for a in result.assignments if a.group_id == "big"} == {"A1", "A2"}
    assert entry(result).points == -7
    assert result.total_score == -7
    assert sum(r.points for r in reasons(result, "big")) == -7
    assert len([c for c in result.compromises if c.rule_id == "companionship"]) == 1
    assert sum(a.points for a in result.assignments) == -7


@pytest.mark.parametrize("parameters", [
    {"exclude_groups": ["same", "same"]},
    {"exclude_groups": [""]},
    {"exclude_groups": "group"},
    {"exclude_groups": [7]},
    {"exclude_groups": [None]},
    {"exclude_groups": [], "zone": "a"},
])
def test_invalid_or_duplicate_instance_exclusions_rejected(parameters):
    with pytest.raises(ValidationError):
        Rule(id="bad", shape="zone_companionship", mode="soft",
             weight=2, parameters=parameters)


def test_unknown_excluded_group_is_rejected_before_optimization():
    p = fixed_lone(excluded=["not-registered"])
    with pytest.raises(ValueError, match="unknown excluded group"):
        solve(p)
    response = client.post("/v1/solve", json=p.model_dump(mode="json"))
    assert response.status_code == 422


def test_companionship_is_soft_only_and_requires_positive_instance_weight():
    with pytest.raises(ValidationError):
        Rule(id="hard-lonely", shape="zone_companionship", mode="hard", parameters={})
    with pytest.raises(ValidationError):
        Rule(id="no-weight", shape="zone_companionship", mode="soft", parameters={})
    with pytest.raises(ValidationError):
        Rule(id="zero-weight", shape="zone_companionship", mode="soft", weight=0, parameters={})


def test_api_and_static_openapi_document_the_new_rule_shape_and_score():
    catalog = client.get("/v1/rules/catalog")
    assert catalog.status_code == 200
    validate(catalog.json(), "RuleCatalog")
    shape = next(x for x in catalog.json()["shapes"] if x["shape"] == "zone_companionship")
    assert shape["default_mode"] == "soft"
    assert shape["default_weight"] == 2
    assert {f["kind"] for f in shape["fields"]} == {"group_exclusions"}

    request = fixed_lone(weight=12).model_dump(mode="json")
    validate(request, "Problem")
    response = client.post("/v1/solve", json=request)
    assert response.status_code == 200, response.text
    validate(response.json(), "Plan")
    assert next(x["points"] for x in response.json()["score_breakdown"]
                if x["rule_id"] == "companionship") == -12
    assert response.json()["total_score"] == -12
