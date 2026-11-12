"""Legacy B2 arithmetic and named-conflict parity regression tests.

The 'across' mechanism classification must never subtract guest pairs
within a registered family from the legacy reward or mixing penalty.
"""
from __future__ import annotations

import pytest

from seating_optimizer import GenericProblem, GenericRule, Guest, Problem, Rule, Table, Zone, solve_generic, solve_legacy


@pytest.mark.parametrize("polarity,expected", [("reward", 105), ("penalty", -35)])
@pytest.mark.parametrize("selected", [False, True])
def test_b2_parity_preserves_pairs_inside_single_registered_family(polarity, expected, selected):
    guests = [
        Guest(id=f"h{i}", name=f"Hebrew {i}", group_id="registration:1",
              attributes={"language": "Hebrew"})
        for i in range(7)
    ]
    guests.append(
        Guest(id="g", name="Greek", group_id="registration:1",
              attributes={"language": "Greek"})
    )
    parameters = {"attribute": "language", "effect": polarity}
    if selected:
        parameters["value"] = "Hebrew"
    legacy_problem = Problem(
        session_id="b2-within-golden",
        zones=[Zone(id="z", name="Z")],
        tables=[Table(id="T", zone_id="z", capacity=8)],
        guests=guests,
        rules=[Rule(id="language", shape="attribute_grouping", mode="soft",
                    weight=5, parameters=parameters)],
    )
    old = solve_legacy(legacy_problem)
    new = solve_generic(GenericProblem.from_v1(legacy_problem))
    assert old.status == new.status == "optimal"
    assert old.total_score == new.total_score == expected
    assert [(r.rule_id, r.points) for r in old.score_breakdown] == [
        (r.rule_id, r.points) for r in new.score_breakdown
    ] == [("language", expected)]
    assert all(
        g.group_id == "registration:1" for g in guests
    ), "Golden 21 reward pairs are internal to one party"


def test_conflicts_carry_stable_id_and_operator_visible_name():
    guests = [Guest(id="elder", name="Elder", group_id="family",
                    attributes={"age_layer": "Senior"})]
    tables = [
        Table(id="G", zone_id="ground", capacity=1),
        Table(id="U", zone_id="upper", capacity=1),
    ]
    rule = GenericRule(
        id="clan-upper-floor", name="Clan — upper floor only",
        engine="venue", mechanism="placement_by_criterion", mode="hard",
        zones=["upper"],
        criterion={"field": "age_layer", "op": "==", "value": "Senior"},
    )
    blocker = GenericRule(
        id="senior-ground", name="Seniors on ground",
        engine="venue", mechanism="placement_by_criterion", mode="hard",
        zones=["ground"],
        criterion={"field": "age_layer", "op": "==", "value": "Senior"},
    )
    plan = solve_generic(GenericProblem(
        session_id="named-conflict",
        guests=guests, zones=[Zone(id="ground", name="Ground"),
                              Zone(id="upper", name="Upper")],
        tables=tables, rules=[rule, blocker],
    ))
    assert plan.status == "infeasible", plan.message
    assert "rule:clan-upper-floor (Clan — upper floor only)" in plan.conflicting_constraints
