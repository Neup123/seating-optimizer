"""Pure v2 expression, migration and scoring tests (no UI or CP-SAT shim).

The external test-230 corpus is deliberately NOT replaced by these tests.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from seating_optimizer.generic_rules import (
    Criterion, GenericRule, criterion_field_state, match_guest, mechanism_catalog,
    split_dominance_warnings,
)
from seating_optimizer.generic_evaluator import hard_violations, score_fixed_plan
from seating_optimizer.models import Guest, Table
from seating_optimizer.rule_migration import (
    LEGACY_SHAPES, migrate_configuration, migrate_instance, migrate_rules,
    reconstruct_v1_rules,
)


def guest(name: str, group: str, **attributes) -> Guest:
    return Guest(id=name, name=name, group_id=group, attributes=attributes)


def rule(engine: str, mechanism: str, *, id="r", mode="soft",
         weight=5, polarity="reward", **params) -> GenericRule:
    return GenericRule(id=id, engine=engine, mechanism=mechanism,
                       mode=mode, weight=weight if mode == "soft" else None,
                       polarity=polarity if mode == "soft" else None, **params)


def test_p1_moustache_solidarity_is_a_data_only_cross_family_criterion():
    people = [guest("a", "one", has_moustache=True),
              guest("b", "two", has_moustache=True),
              guest("c", "three", has_moustache=False)]
    table = [Table(id="T", zone_id="z", capacity=3)]
    r = rule("inter", "criterion_pairs", id="moustache",
             criterion={"subject": "guest", "field": "has_moustache", "op": "==",
                        "value": True, "scope": "across"})
    total, by_rule = score_fixed_plan(people, table, {p.id: "T" for p in people}, [r])
    assert total == 5 and by_rule == {"moustache": 5}
    # No secret points when the operator did not add a rule.
    assert score_fixed_plan(people, table, {p.id: "T" for p in people}, []) == (0, {})


def test_p2_age_at_least_65_needs_quiet_corner_and_pays_unmet_penalty():
    people = [guest("s", "senior", age="70"), guest("y", "young", age="30")]
    tables = [Table(id="T", zone_id="z", capacity=2),
              Table(id="Q", zone_id="z", capacity=2, properties=["quiet_corner"])]
    r = rule("venue", "property_need", id="quiet", polarity="penalty",
             criterion={"subject": "guest", "field": "age", "op": ">=", "value": 65},
             property="quiet_corner")
    assert score_fixed_plan(people, tables, {"s": "T", "y": "T"}, [r]) == (-5, {"quiet": -5})
    assert score_fixed_plan(people, tables, {"s": "Q", "y": "T"}, [r]) == (0, {"quiet": 0})
    assert criterion_field_state(people, Criterion(field="age", op=">=", value=65)).compatible


def test_p3_count_russian_guest_fact_drives_table_pattern():
    people = [guest("r", "R", language="Russian"),
              guest("h", "H", language="Hebrew")]
    tables = [Table(id="T", zone_id="z", capacity=2)]
    r = rule("inter", "table_pattern", id="one-russian", polarity="penalty",
             weight=2, conditions=[
                 {"fact": "count", "criterion": {"subject": "guest",
                   "field": "language", "op": "==", "value": "Russian"},
                  "op": "==", "value": 1},
             ])
    assert score_fixed_plan(people, tables, {"r": "T", "h": "T"}, [r]) == (
        -2, {"one-russian": -2})
    assert score_fixed_plan(people, tables, {"h": "T"}, [r]) == (0, {"one-russian": 0})


def test_section_13_golden_pair_arithmetic_and_split_extra_tables():
    people = [guest(f"h{i}", "hebrew", language="Hebrew") for i in range(7)]
    people.append(guest("greek", "other", language="Greek"))
    tables = [Table(id="A", zone_id="z", capacity=8)]
    placement = {g.id: "A" for g in people}
    inside = rule("intra", "own_attribute_grouping", id="within", weight=5,
                  criterion={"subject": "guest", "field": "language", "op": "==",
                             "scope": "within"})
    across = rule("inter", "criterion_pairs", id="cross", polarity="penalty", weight=5,
                  criterion={"subject": "guest", "field": "language", "op": "==",
                             "scope": "across"})
    assert score_fixed_plan(people, tables, placement, [inside]) == (21 * 5, {"within": 105})
    assert score_fixed_plan(people, tables, placement, [across]) == (-7 * 5, {"cross": -35})

    family = [guest(f"c{i}", "clan") for i in range(3)]
    parts = [Table(id=t, zone_id="z", capacity=1) for t in ("A", "B", "C")]
    split = rule("intra", "split_term", id="split", polarity="penalty", weight=20)
    assert score_fixed_plan(family, parts,
                            {f"c{i}": t for i, t in enumerate(("A", "B", "C"))},
                            [split]) == (-2 * 20, {"split": -40})


def test_comparison_ops_and_absent_columns_are_inert_but_visible():
    people = [guest("g", "G", age="68", language="Hebrew")]
    for op, value, expected in [
        ("==", "68", True), ("!=", "68", False), ("<", 65, False),
        ("<=", 68, True), (">", 65, True), (">=", 68, True),
        ("in", [60, 68, 70], True),
    ]:
        assert match_guest(people[0], Criterion(field="age", op=op, value=value)) is expected
    absent = Criterion(field="has_moustache", op="==", value=True)
    assert not match_guest(people[0], absent)
    state = criterion_field_state(people, absent)
    assert not state.observed and "matches no guests" in state.message
    state = criterion_field_state(people, Criterion(field="language", op=">=", value=65))
    assert state.observed and not state.compatible
    with pytest.raises(ValidationError):
        Criterion(field="age", op=">", value="senior")
    with pytest.raises(ValidationError):
        Criterion(field="age", op="in", value="senior")


def test_disabled_rule_bypasses_content_validation_but_reenable_checks():
    data = dict(id="off", engine="inter", mechanism="table_pattern",
                mode="soft", weight=-10, polarity=None,
                conditions=[{"fact": "unrecognised", "op": "?", "value": None}])
    off = GenericRule(**data, enabled=False)
    assert off.id == "off"
    with pytest.raises(ValidationError):
        GenericRule(**data, enabled=True)


def test_split_guard_never_changes_the_authored_weight():
    split = rule("intra", "split_term", polarity="penalty", weight=5)
    ordinary = rule("inter", "criterion_pairs", weight=25,
                    criterion={"field": "language", "op": "==", "scope": "across"})
    assert split_dominance_warnings([split, ordinary], guest_count=8, table_count=2)
    assert split.weight == 5
    assert not split_dominance_warnings([split.model_copy(update={"weight": 1000000}),
                                         ordinary], guest_count=8, table_count=2)


def _legacy_instances():
    """Synthetic coverage inventory; NOT the absent external test-230 listing."""
    defs = [
        ("attribute_grouping", "soft", 2, {"attribute": "language", "value": "Hebrew"}),
        ("zone_restriction", "hard", None, {"attribute": "age_layer", "value": "Senior", "zone": "ground"}),
        ("table_property_need", "hard", None, {"attribute": "mobility", "value": "wheelchair", "property": "accessible"}),
        ("pair", "hard", None, {"left": "A", "right": "B", "relation": "apart"}),
        ("capacity", "hard", None, {}),
        ("fill_efficiency", "soft", 1, {}),
        ("pin", "hard", None, {"target": "A", "table": "T"}),
        ("global_pattern", "soft", 2, {"enabled": True, "effect": "penalty",
                                      "conditions": [{"fact": "empty_seats", "op": "==", "value": 1}]}),
        ("split_penalty", "soft", 1000000, {}),
        ("small_group_priority", "soft", 1, {}),
        ("low_priority", "mark", None, {"selector": "size_below", "grade": 2, "threshold": 4}),
        ("tiered_placement", "staged", None, {"target": "A", "tiers": [{"zones": ["upper"]}, {"zones": ["ground"]}]}),
        ("zone_companionship", "soft", 2, {"exclude_groups": []}),
    ]
    assert len(defs) == len(LEGACY_SHAPES) == 13
    defs.extend([deepcopy(defs[i]) for i in (0, 1, 2, 3, 10)])
    return [
        {"id": f"instance-{i}", "name": f"Readable rule {i}",
         "description": f"Example {i}", "enabled": i < 6, "shape": shape,
         "mode": mode, "weight": weight, "parameters": params}
        for i, (shape, mode, weight, params) in enumerate(defs)
    ]


def test_all_13_shapes_and_18_synthetic_instances_migrate_reversibly():
    originals = _legacy_instances()
    converted, report = migrate_rules(originals)
    assert report["input_instances"] == 18
    assert report["migrated_instances"] == 17
    assert report["retired_instances"] == 1
    assert len(report["mapped_shapes"]) == 13
    assert report["retired"][0]["id"] == "instance-4"
    assert "Table.capacity" in report["retired"][0]["reason"]
    assert [r.id for r in converted] == [r["id"] for r in originals if r["shape"] != "capacity"]
    assert [r.name for r in converted] == [r["name"] for r in originals if r["shape"] != "capacity"]
    assert reconstruct_v1_rules(converted, report) == originals
    migrated, ledger = migrate_configuration({"version": 1, "name": "Event", "rules": originals})
    assert migrated["version"] == 2 and ledger == report
    assert len(migrated["rules"]) == 17
    assert {x["mechanism"] for x in migrated["rules"]}
    assert all(mechanism in {x["mechanism"] for x in mechanism_catalog()}
               for mechanism in {x["mechanism"] for x in migrated["rules"]})


def test_hard_diagnostics_use_rule_instance_display_name():
    g = [guest("s", "senior", age=72)]
    t = [Table(id="T", zone_id="upper", capacity=1)]
    r = rule("venue", "placement_by_criterion", id="seniors-ground",
             mode="hard", name="Seniors on ground",
             criterion={"field": "age", "op": ">=", "value": 65},
             zones=["ground"])
    assert hard_violations(g, t, {"s": "T"}, [r]) == ["Seniors on ground"]
