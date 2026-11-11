"""CP-SAT integration proofs for generic mechanisms (not fixed-plan-only tests)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from seating_optimizer import (
    GenericProblem, GenericRule, Guest, ManualInstruction, SolverConfig,
    Table, Zone, solve, solve_generic,
)
from seating_optimizer.api.app import create_app


def g(name, family, **attributes):
    return Guest(id=name, name=name, group_id=family,
                 group_name=family, attributes=attributes)


def rule(id, engine, mechanism, mode="soft", weight=5,
         polarity="reward", **parameters):
    return GenericRule(
        id=id, name=id, engine=engine, mechanism=mechanism,
        mode=mode, weight=weight if mode == "soft" else None,
        polarity=polarity if mode == "soft" else None, **parameters,
    )


def scene(guests, tables, rules, *, instructions=None, splits=None):
    return GenericProblem(
        session_id="generic-system", zones=[
            Zone(id=z, name=z) for z in sorted({t.zone_id for t in tables})],
        guests=guests, tables=tables, rules=rules,
        manual_instructions=instructions or [], splittable_groups=splits or [],
        config=SolverConfig(time_limit_seconds=5, workers=1, random_seed=42),
    )


def where(plan):
    return {person: item.table_id for item in plan.assignments for person in item.guest_ids}


def test_p1_cp_sat_moustache_solidarity_is_data_only():
    guests = [g("one", "A", has_moustache=True),
              g("two", "B", has_moustache=True),
              g("three", "C", has_moustache=False)]
    tables = [Table(id="A", zone_id="z", capacity=2),
              Table(id="B", zone_id="z", capacity=2)]
    instance = rule("moustache", "inter", "criterion_pairs",
                    criterion={"subject": "guest", "field": "has_moustache",
                               "op": "==", "value": True, "scope": "across"})
    plan = solve(scene(guests, tables, [instance]), engine="generic")
    assert plan.status in ("optimal", "feasible"), plan.message
    assert where(plan)["one"] == where(plan)["two"]
    assert plan.total_score == 5
    assert [(s.rule_id, s.points) for s in plan.score_breakdown] == [("moustache", 5)]


def test_p2_cp_sat_numeric_senior_criterion_soft_penalty():
    guests = [g("old", "senior", age=75),
              g("young", "junior", age=24)]
    tables = [Table(id="quiet", zone_id="z", capacity=1, properties=["quiet_corner"]),
              Table(id="busy", zone_id="z", capacity=1)]
    need = rule("quiet", "venue", "property_need", polarity="penalty",
                criterion={"subject": "guest", "field": "age", "op": ">=",
                           "value": 65}, property="quiet_corner")
    plan = solve_generic(scene(guests, tables, [need]))
    assert plan.status == "optimal"
    assert where(plan)["old"] == "quiet"
    assert plan.total_score == 0

    pinned = rule("pin", "venue", "locked_assignment", mode="hard",
                  target="old", table="busy")
    forced = solve_generic(scene(guests, tables, [need, pinned]))
    assert forced.status in ("optimal", "feasible")
    assert where(forced)["old"] == "busy"
    assert forced.total_score == -5
    assert [(s.rule_id, s.points) for s in forced.score_breakdown] == [("quiet", -5)]


def test_p3_cp_sat_count_russian_per_table_pattern():
    guests = [g("r1", "R1", language="Russian"),
              g("r2", "R2", language="Russian"),
              g("en", "EN", language="English")]
    tables = [Table(id="A", zone_id="z", capacity=2),
              Table(id="B", zone_id="z", capacity=2)]
    pattern = rule("no-lone-russian", "inter", "table_pattern", polarity="penalty",
                   weight=2, conditions=[{"fact": "count", "op": "==", "value": 1,
                   "criterion": {"subject": "guest", "field": "language",
                                 "op": "==", "value": "Russian"}}])
    best = solve_generic(scene(guests, tables, [pattern]))
    assert best.status == "optimal", best.message
    assert where(best)["r1"] == where(best)["r2"]
    assert best.total_score == 0

    pin_one = rule("pin-one", "venue", "locked_assignment", mode="hard",
                   target="r1", table="A")
    pin_two = rule("pin-two", "venue", "locked_assignment", mode="hard",
                   target="r2", table="B")
    forced = solve_generic(scene(guests, tables, [pattern, pin_one, pin_two]))
    assert forced.status in ("optimal", "feasible"), forced.message
    assert forced.total_score == -4


def test_senior_age_layer_and_numeric_age_formulations_match():
    guests = [g("elder", "E", age=73, age_layer="Senior"),
              g("adult", "Y", age=27, age_layer="Adult")]
    tables = [Table(id="G", zone_id="ground", capacity=1),
              Table(id="U", zone_id="upper", capacity=1)]
    def restriction(criterion):
        return rule("seniors-ground-floor", "venue", "placement_by_criterion",
                    mode="hard", zones=["ground"], criterion=criterion)
    from_layer = solve_generic(scene(guests, tables, [
        restriction({"field": "age_layer", "op": "==", "value": "Senior"})]))
    from_age = solve_generic(scene(guests, tables, [
        restriction({"field": "age", "op": ">=", "value": 65})]))
    assert from_layer.status == from_age.status == "optimal"
    assert where(from_layer) == where(from_age) == {"elder": "G", "adult": "U"}
    assert from_layer.total_score == from_age.total_score == 0


def test_d1_two_same_grade_families_are_fitted_one_at_a_time():
    guests = [g(f"main{i}", "ordinary") for i in range(6)]
    guests += [g(f"first{i}", "first") for i in range(2)]
    guests += [g(f"second{i}", "second") for i in range(2)]
    tables = [Table(id="A", zone_id="z", capacity=6),
              Table(id="B", zone_id="z", capacity=2),
              Table(id="C", zone_id="z", capacity=1),
              Table(id="D", zone_id="z", capacity=1)]
    marks = [
        rule("first-low", "stage", "priority_mark", mode="mark",
             selector="direct", target="first", grade=2),
        rule("second-low", "stage", "priority_mark", mode="mark",
             selector="direct", target="second", grade=2),
    ]
    result = solve_generic(scene(guests, tables, marks))
    assert result.status == "needs_review"
    assert {a.group_id for a in result.assignments} == {"ordinary", "first"}
    assert [m.group_id for m in result.pending_groups] == ["second"]
    assert result.not_seated == []
    assert result.unseated_reasons[0].reason == "lack_of_space"
    assert result.unseated_reasons[0].status == "pending"


def test_d2_operator_unseat_is_distinct_from_pending():
    guests = [g("a", "A"), g("b", "B")]
    tables = [Table(id="A", zone_id="z", capacity=1)]
    instructions = [ManualInstruction(id="human", group_id="B", action="unseat")]
    result = solve_generic(scene(guests, tables, [], instructions=instructions))
    assert result.status == "optimal"
    assert [g.group_id for g in result.not_seated] == ["B"]
    assert [g.reason for g in result.unseated_reasons] == ["operator_decision"]
    assert result.unseated_reasons[0].status == "confirmed"
    assert where(result) == {"a": "A"}


def test_split_golden_minus_two_per_extra_table_and_validation_no_calibration():
    guests = [g(f"g{i}", "family") for i in range(3)]
    tables = [Table(id=f"T{i}", zone_id="z", capacity=1) for i in range(3)]
    split = rule("split", "intra", "split_term", polarity="penalty", weight=20)
    result = solve_generic(scene(guests, tables, [split], splits=["family"]))
    assert result.status == "optimal", result.message
    assert result.total_score == -40
    assert result.score_breakdown[0].points == -2 * 20
    assert split.weight == 20


def test_api_v2_solver_accepts_new_instances_and_keeps_v1_route():
    guests = [g("a", "A", age=72)]
    tables = [Table(id="T", zone_id="z", capacity=1,
                    properties=["quiet_corner"])]
    need = rule("quiet", "venue", "property_need", polarity="penalty",
                criterion={"field": "age", "op": ">=", "value": 65},
                property="quiet_corner")
    request = scene(guests, tables, [need])
    client = TestClient(create_app())
    result = client.post("/v2/solve", json=request.model_dump(mode="json"))
    assert result.status_code == 200, result.text
    assert result.json()["total_score"] == 0
    assert "unseated_reasons" in result.json()
    catalog = client.get("/v2/rules/catalog")
    assert catalog.status_code == 200
    assert any(item["mechanism"] == "criterion_pairs" for item in catalog.json())
    assert client.get("/v1/rules/catalog").status_code == 200
