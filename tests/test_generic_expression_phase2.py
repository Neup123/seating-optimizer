"""Phase 2 expression proofs: P1–P4, scopes, numeric types and §13.

These are executable synthetic regressions. They are not substitutes for
the coordinator's external 29-verdict test-230 corpus.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from seating_optimizer import GenericProblem, GenericRule, Guest, Table, Zone, solve_generic
from seating_optimizer.api.app import create_app
from seating_optimizer.generic_evaluator import hard_violations, score_fixed_plan
from seating_optimizer.generic_rules import (
    Criterion, compare_value, criterion_field_state, match_family, split_dominance_warnings,
)
from seating_optimizer.rule_migration import migrate_instance


def person(identity, family, **attributes):
    return Guest(id=identity, name=identity, group_id=family, attributes=attributes)


def rule(identity, engine, mechanism, *, mode="soft", weight=5,
         polarity="reward", **data):
    return GenericRule(
        id=identity, engine=engine, mechanism=mechanism, mode=mode,
        weight=weight if mode == "soft" else None,
        polarity=polarity if mode == "soft" else None, **data,
    )


def scene(guests, tables, rules, **kwargs):
    return GenericProblem(
        session_id="phase2-expressions", guests=guests, tables=tables, rules=rules,
        zones=[Zone(id=z, name=z) for z in sorted({table.zone_id for table in tables})],
        **kwargs,
    )


def placement(plan):
    return {gid: assignment.table_id for assignment in plan.assignments
            for gid in assignment.guest_ids}


def test_p1_moustache_solidarity_only_pairs_selected_across_families():
    guests = [person("m1", "F1", has_moustache=True),
              person("m2", "F2", has_moustache=True),
              person("no", "F3", has_moustache=False)]
    tables = [Table(id="T", zone_id="z", capacity=2),
              Table(id="U", zone_id="z", capacity=2)]
    moustache = rule(
        "moustache", "inter", "criterion_pairs",
        criterion={"field": "has_moustache", "op": "==", "value": True,
                   "scope": "across"},
    )
    solved = solve_generic(scene(guests, tables, [moustache]))
    assert solved.status in ("optimal", "feasible")
    assert placement(solved)["m1"] == placement(solved)["m2"]
    assert solved.total_score == 5
    assert score_fixed_plan(guests, tables, placement(solved), [moustache])[0] == 5


@pytest.mark.parametrize("field,op,value", [
    ("age_layer", "==", "Senior"),
    ("age", ">=", 65),
])
def test_seniors_ground_floor_has_identical_solutions_in_both_forms(field, op, value):
    guests = [person("elder", "S", age=73, age_layer="Senior"),
              person("younger", "Y", age=27, age_layer="Adult")]
    tables = [Table(id="G", zone_id="ground", capacity=1),
              Table(id="U", zone_id="upper", capacity=1)]
    instance = rule(
        "seniors-ground-floor", "venue", "placement_by_criterion",
        mode="hard", zones=["ground"],
        criterion={"field": field, "op": op, "value": value},
    )
    result = solve_generic(scene(guests, tables, [instance]))
    assert result.status == "optimal", result.message
    assert placement(result) == {"elder": "G", "younger": "U"}
    assert result.total_score == 0


def test_p2_numeric_property_need_and_p3_count_criterion_are_real_solver_terms():
    guests = [person("r1", "A", language="Russian", age=75),
              person("r2", "B", language="Russian", age=25),
              person("e", "C", language="English", age=24)]
    tables = [Table(id="Q", zone_id="z", capacity=2, properties=["quiet_corner"]),
              Table(id="N", zone_id="z", capacity=2)]
    senior = rule(
        "quiet", "venue", "property_need", polarity="penalty",
        criterion={"field": "age", "op": ">=", "value": 65}, property="quiet_corner",
    )
    lone = rule(
        "no-lone-speaker", "inter", "table_pattern", weight=2, polarity="penalty",
        conditions=[{"fact": "count", "criterion": {
            "field": "language", "op": "==", "value": "Russian",
        }, "op": "==", "value": 1}],
    )
    result = solve_generic(scene(guests, tables, [senior, lone]))
    assert result.status == "optimal", result.message
    assert placement(result)["r1"] == "Q"
    assert placement(result)["r1"] == placement(result)["r2"]
    assert result.total_score == 0

    forced = {"r1": "N", "r2": "Q", "e": "Q"}
    assert score_fixed_plan(guests, tables, forced, [senior, lone]) == (
        -9, {"quiet": -5, "no-lone-speaker": -4})


def test_p4_family_youngest_age_hard_guard_applies_to_entire_family():
    guests = [person("toddler", "T", age="2"),
              person("parent", "T", age=34),
              person("older", "O", age=6)]
    tables = [Table(id="G", zone_id="ground", capacity=2),
              Table(id="U", zone_id="upper", capacity=1)]
    requirement = rule(
        "toddlers-ground", "venue", "placement_by_criterion", mode="hard",
        criterion={"field": "youngest_age(family)", "op": "<", "value": 3},
        zones=["ground"],
    )
    assert Criterion.model_validate(requirement.criterion).subject == "family"
    result = solve_generic(scene(guests, tables, [requirement]))
    assert result.status == "optimal", result.message
    assert placement(result) == {"toddler": "G", "parent": "G", "older": "U"}
    assert hard_violations(guests, tables, {
        "toddler": "U", "parent": "G", "older": "G",
    }, [requirement]) == ["toddlers-ground"]


@pytest.mark.parametrize("field,op,value,expected", [
    ("min(age)", "<", 3, True),
    ("youngest_age(family)", "<", 3, True),
    ("max(age)", ">=", 40, True),
    ("oldest_age(family)", ">", 39, True),
    ("any(age)", "==", 2, True),
    ("any(age)", ">", 42, False),
    ("any(age)", "in", [2, 6], True),
    ("party_size", "==", 3, True),
])
def test_family_aggregates_min_max_any_and_size(field, op, value, expected):
    members = [person("p", "F", age="40"), person("t", "F", age=2),
               person("a", "F", age=6)]
    c = Criterion(subject="family", field=field, op=op, value=value)
    assert match_family(members, c) is expected
    assert criterion_field_state(members, c).compatible


def test_in_type_validation_numeric_equality_and_absent_family_data():
    guest = person("x", "F", age="68.0", language="English")
    assert compare_value("68.0", "==", 68)
    assert compare_value("68.0", "==", "68")
    assert compare_value("100", "<", 65) is False
    assert compare_value("68", "in", [67, 68])
    assert criterion_field_state([guest], Criterion(field="age", op="in",
                                                   value=[65, 68])).compatible
    assert not criterion_field_state(
        [guest], Criterion(field="language", op=">=", value=65)).compatible
    missing = Criterion(field="min(age)", op="<", value=3)
    state = criterion_field_state([person("n", "N")], missing)
    assert not state.observed
    assert not match_family([person("n", "N")], missing)
    with pytest.raises(ValidationError):
        Criterion(field="age", op="in", value=[65, "Senior"])
    with pytest.raises(ValidationError):
        Criterion(field="age", op="in", value=65)
    with pytest.raises(ValidationError):
        Criterion(field="min(age)", op="==", value="child")


@pytest.mark.parametrize("mechanism", ["criterion_pairs", "own_attribute_grouping"])
def test_explicit_scopes_are_literal_for_both_pair_mechanisms(mechanism):
    guests = [person("a", "F", language="Hebrew"),
              person("b", "F", language="Hebrew"),
              person("c", "G", language="Hebrew")]
    tables = [Table(id="T", zone_id="z", capacity=3)]
    where = {g.id: "T" for g in guests}
    engine = "inter" if mechanism == "criterion_pairs" else "intra"
    def make(scope):
        criterion = {"field": "language", "op": "==", "value": "Hebrew"}
        if scope is not None:
            criterion["scope"] = scope
        return rule("pair", engine, mechanism, criterion=criterion)
    # Three total pairs, one within F, two across F/G.
    default = 3 if mechanism == "criterion_pairs" else 1
    assert score_fixed_plan(guests, tables, where, [make(None)])[0] == 5 * default
    for scope, count in [("within", 1), ("across", 2)]:
        instance = make(scope)
        assert score_fixed_plan(guests, tables, where, [instance])[0] == 5 * count
        assert solve_generic(scene(guests, tables, [instance])).total_score == 5 * count


def test_section_13_legacy_21_pairs_and_two_polarities_stay_intact():
    hebrew = [person(f"h{i}", "clan", language="Hebrew") for i in range(7)]
    greek = person("g", "clan", language="Greek")
    guests = hebrew + [greek]
    tables = [Table(id="T", zone_id="z", capacity=8)]
    mapping = {g.id: "T" for g in guests}
    for polarity, expected in (("reward", 21 * 7), ("penalty", -7 * 7)):
        legacy = {"id": "language", "shape": "attribute_grouping", "mode": "soft",
                  "weight": 7, "parameters": {
                      "attribute": "language", "effect": polarity, "value": "Hebrew"}}
        generic = migrate_instance(legacy)
        assert "scope" not in generic.criterion
        assert score_fixed_plan(guests, tables, mapping, [generic])[0] == expected
        assert solve_generic(scene(guests, tables, [generic])).total_score == expected


def test_clan_36_manual_chair_capacity_and_negative_split_points():
    guests = [person(f"c{i}", "clan") for i in range(36)]
    tables = [Table(id="G", zone_id="ground", capacity=18),
              Table(id="U", zone_id="upper", capacity=18)]
    split = rule("split", "intra", "split_term", weight=20, polarity="penalty")
    result = solve_generic(scene(guests, tables, [split], splittable_groups=["clan"]))
    assert result.status in ("optimal", "feasible"), result.message
    assert len(placement(result)) == 36
    assert result.total_score == -20
    assert result.not_seated == []
    assert sum(t.occupied for t in result.tables) == 36


def test_split_pool_guard_warns_and_never_changes_entered_weight_or_seats():
    split = rule("split", "intra", "split_term", weight=20, polarity="penalty")
    points = rule("language", "inter", "criterion_pairs", weight=8,
                  criterion={"field": "language", "value": "Hebrew"})
    assert split_dominance_warnings([split, points], guest_count=6, table_count=2)
    assert split.weight == 20
    assert not split_dominance_warnings([split.model_copy(update={"weight": 10**7}),
                                         points], guest_count=6, table_count=2)
    guests = [person("a", "A", language="Hebrew"),
              person("b", "B", language="Hebrew")]
    tables = [Table(id="T", zone_id="z", capacity=2)]
    result = solve_generic(scene(guests, tables, [split, points]))
    assert result.status == "optimal"
    assert any("Split weight 20" in text for text in result.validation_warnings)
    assert split.weight == 20


def test_v2_api_accepts_family_aggregate_and_rejects_wrong_numeric_field():
    client = TestClient(create_app())
    guests = [person("small", "F", age=2)]
    tables = [Table(id="G", zone_id="ground", capacity=1)]
    hard = rule("toddlers", "venue", "placement_by_criterion", mode="hard",
                zones=["ground"], criterion={
                    "field": "youngest_age(family)", "op": "<", "value": 3})
    payload = scene(guests, tables, [hard]).model_dump(mode="json")
    accepted = client.post("/v2/solve", json=payload)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] in ("optimal", "feasible")
    payload["rules"][0]["criterion"] = {"field": "age_layer", "op": "<", "value": 3}
    rejected = client.post("/v2/solve", json=payload)
    assert rejected.status_code == 200, rejected.text  # absent column: inert warning
    payload["guests"][0]["attributes"]["age_layer"] = "Toddler"
    rejected = client.post("/v2/solve", json=payload)
    assert rejected.status_code == 422, rejected.text
