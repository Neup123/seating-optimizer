"""Per-mechanism CP-SAT regression tests for the version-2 dispatch registry."""
from __future__ import annotations

import pytest

from seating_optimizer import (
    GenericProblem, GenericRule, Guest, Table, Zone, solve_generic,
    mechanism_catalog,
)
from seating_optimizer.generic_cp import BUILDERS
from seating_optimizer.generic_evaluator import SCORERS


def guest(i, group, **attrs):
    return Guest(id=i, name=i, group_id=group, attributes=attrs)


def rule(id, engine, mechanism, *, mode="soft", polarity="reward",
         weight=5, **data):
    return GenericRule(
        id=id, name=id, engine=engine, mechanism=mechanism, mode=mode,
        polarity=polarity if mode == "soft" else None,
        weight=weight if mode == "soft" else None, **data,
    )


def problem(guests, tables, rules, **data):
    return GenericProblem(
        session_id="mechanisms", zones=[
            Zone(id=z, name=z) for z in sorted({t.zone_id for t in tables})],
        tables=tables, guests=guests, rules=rules, **data,
    )


def place(plan):
    return {g: a.table_id for a in plan.assignments for g in a.guest_ids}


def test_registry_catalog_and_cp_builders_are_exhaustive():
    catalog = mechanism_catalog()
    identities = {(x["engine"], x["mechanism"]) for x in catalog}
    assert identities == set(BUILDERS) == set(SCORERS)
    assert len(identities) == 13


@pytest.mark.parametrize("polarity,expected", [("reward", 105), ("penalty", -35)])
def test_A3_within_family_pair_rule_both_faces(polarity, expected):
    guests = [guest(f"h{i}", "family", language="Hebrew") for i in range(7)]
    guests.append(guest("greek", "family", language="Greek"))
    tables = [Table(id="T", zone_id="z", capacity=8)]
    instance = rule("own-language", "intra", "own_attribute_grouping",
                    polarity=polarity,
                    criterion={"field": "language", "op": "==",
                               "scope": "within"})
    plan = solve_generic(problem(guests, tables, [instance]))
    assert plan.status == "optimal", plan.message
    assert plan.total_score == expected
    assert plan.score_breakdown[0].points == expected


@pytest.mark.parametrize("polarity,expected", [("reward", 15), ("penalty", 0)])
def test_B2_cross_family_grouping_faces_with_same_language(polarity, expected):
    guests = [guest(f"h{i}", f"family{i}", language="Hebrew") for i in range(3)]
    tables = [Table(id="T", zone_id="z", capacity=3)]
    instance = rule("across", "inter", "criterion_pairs",
                    polarity=polarity,
                    criterion={"field": "language", "op": "==", "scope": "across"})
    plan = solve_generic(problem(guests, tables, [instance]))
    assert plan.status == "optimal", plan.message
    assert plan.total_score == expected


def test_B1_pair_relation_hard_and_soft_modes():
    guests = [guest("a", "A"), guest("b", "B")]
    tables = [Table(id="T", zone_id="z", capacity=2),
              Table(id="U", zone_id="z", capacity=2)]
    together = rule("together", "inter", "pair_relation", mode="hard",
                    targets=["A", "B"], relation="together")
    plan = solve_generic(problem(guests, tables, [together]))
    assert plan.status == "optimal"
    assert place(plan)["a"] == place(plan)["b"]
    assert plan.total_score == 0
    apart = rule("apart", "inter", "pair_relation", mode="hard",
                 targets=["A", "B"], relation="apart")
    plan = solve_generic(problem(guests, tables, [apart]))
    assert plan.status == "optimal"
    assert place(plan)["a"] != place(plan)["b"]
    soft = rule("prefer-apart", "inter", "pair_relation",
                targets=["A", "B"], relation="apart", weight=5)
    plan = solve_generic(problem(guests, tables, [soft]))
    assert plan.status == "optimal"
    assert plan.total_score == 5


def test_B3_table_pattern_both_polarities():
    guests = [guest("a", "A")]
    tables = [Table(id="T", zone_id="z", capacity=2)]
    conditions = [{"fact": "groups_at_table", "op": "==", "value": 1},
                  {"fact": "empty_seats", "op": "==", "value": 1}]
    reward = rule("pattern-reward", "inter", "table_pattern",
                  polarity="reward", weight=3, conditions=conditions)
    penalty = rule("pattern-penalty", "inter", "table_pattern",
                   polarity="penalty", weight=3, conditions=conditions)
    plan = solve_generic(problem(guests, tables, [reward, penalty]))
    assert plan.status == "optimal"
    assert plan.total_score == 0
    assert {r.rule_id: r.points for r in plan.score_breakdown} == {
        "pattern-reward": 3, "pattern-penalty": -3}


def test_B4_companionship_two_occupied_zones_lone_groups_and_single_zone_exempt():
    guests = [guest("a", "A"), guest("b", "B")]
    tables = [Table(id="T", zone_id="ground", capacity=1),
              Table(id="U", zone_id="upper", capacity=1)]
    companion = rule("company", "inter", "companionship",
                     polarity="penalty", weight=2, exclusions=[])
    plan = solve_generic(problem(guests, tables, [companion]))
    assert plan.status == "optimal"
    assert plan.total_score == -4
    one_zone = [Table(id="T", zone_id="ground", capacity=1),
                Table(id="U", zone_id="ground", capacity=1)]
    plan = solve_generic(problem(guests, one_zone, [companion]))
    assert plan.status == "optimal"
    assert plan.total_score == 0


def test_C1_placement_soft_reward_and_hard_constraint():
    guests = [guest("elder", "E", age=72)]
    tables = [Table(id="Q", zone_id="quiet", capacity=1),
              Table(id="N", zone_id="noisy", capacity=1)]
    criterion = {"field": "age", "op": ">=", "value": 65}
    prefer = rule("prefer", "venue", "placement_by_criterion",
                  zones=["quiet"], criterion=criterion)
    plan = solve_generic(problem(guests, tables, [prefer]))
    assert plan.status == "optimal"
    assert plan.total_score == 5
    assert place(plan)["elder"] == "Q"
    require = rule("require", "venue", "placement_by_criterion", mode="hard",
                   zones=["quiet"], criterion=criterion)
    plan = solve_generic(problem(guests, tables, [require]))
    assert plan.status == "optimal"
    assert place(plan)["elder"] == "Q"
    assert plan.total_score == 0


def test_C2_tiered_placement_lexicographic_before_soft_scores():
    guests = [guest("a", "A")]
    tables = [Table(id="U", zone_id="upper", capacity=1),
              Table(id="G", zone_id="ground", capacity=1)]
    tier = rule("tiers", "venue", "tiered_placement", mode="staged",
                target="A", tiers=[{"zones": ["upper"]}, {"zones": ["ground"]}])
    attractive = rule("attractive", "venue", "placement_by_criterion", weight=25,
                      zones=["ground"], criterion={"field": "name", "op": "==", "value": "a"})
    plan = solve_generic(problem(guests, tables, [tier, attractive]))
    assert plan.status == "optimal", plan.message
    assert place(plan)["a"] == "U"
    assert plan.total_score == 0


def test_C5_holes_penalty_minimizes_empty_seats_only_at_used_tables():
    guests = [guest("a", "A")]
    tables = [Table(id="T", zone_id="z", capacity=2),
              Table(id="U", zone_id="z", capacity=3)]
    holes = rule("holes", "venue", "holes_term", polarity="penalty", weight=1)
    plan = solve_generic(problem(guests, tables, [holes]))
    assert plan.status == "optimal"
    assert place(plan)["a"] == "T"
    assert plan.total_score == -1


def test_C6_property_fit_scores_qualified_family_only():
    guests = [guest("a", "A"), guest("b", "A")]
    tables = [Table(id="T", zone_id="z", capacity=2,
                    small_group_priority=True),
              Table(id="U", zone_id="z", capacity=3)]
    instance = rule("fit", "venue", "property_fit", weight=1,
                    criterion={"subject": "family", "field": "party_size",
                               "op": "<=", "value": 2},
                    property="small_group_priority")
    plan = solve_generic(problem(guests, tables, [instance]))
    assert plan.status == "optimal", plan.message
    assert place(plan) == {"a": "T", "b": "T"}
    assert plan.total_score == 1


def test_hard_within_criterion_never_becomes_objective_points():
    guests = [guest("a", "A", language="Hebrew"),
              guest("b", "A", language="Hebrew")]
    tables = [Table(id="T", zone_id="z", capacity=2)]
    hard = GenericRule(id="own-hard", engine="intra", mechanism="own_attribute_grouping",
                       mode="hard", polarity="reward",
                       criterion={"field": "language", "op": "==", "scope": "within"})
    plan = solve_generic(problem(guests, tables, [hard]))
    assert plan.status == "optimal"
    assert plan.total_score == 0
    assert plan.score_breakdown == []


def test_absent_criterion_is_inert_and_reported_to_v2_client():
    guests = [guest("a", "A", language="Greek")]
    tables = [Table(id="T", zone_id="z", capacity=1)]
    rule_missing = rule("not-here", "inter", "criterion_pairs",
                        criterion={"field": "has_moustache", "op": "==",
                                   "value": True, "scope": "across"})
    plan = solve_generic(problem(guests, tables, [rule_missing]))
    assert plan.status == "optimal"
    assert plan.total_score == 0
    assert plan.validation_warnings and "absent" in plan.validation_warnings[0]
    assert plan.criterion_states[0]["observed"] is False
