"""Regression tests for operator-owned split and combination objective terms.

Scenarios mirror sections 11.1 and 11.2 of docs/scoring-principles.md.
The candidate placements are locked as test fixtures so the assertions
compare *scores of specific arrangements*, not solver search timing.
"""
from __future__ import annotations

from seating_optimizer import Guest, Problem, Rule, SolverConfig, Table, Zone, rule_catalog, solve


def split_rule(weight: int) -> Rule:
    return Rule(id="split", shape="split_penalty", mode="soft", weight=weight)


def score_of(plan, rule_id: str) -> int:
    assert plan.status in {"optimal", "feasible"}, plan.conflicting_constraints
    assert plan.total_score == sum(item.points for item in plan.score_breakdown)
    assert abs(plan.total_score - sum(a.points for a in plan.assignments)) < 0.001
    return next(item.points for item in plan.score_breakdown if item.rule_id == rule_id)


def _clan_fixture(clan_portions: list[int], other_party_tables: list[str], *,
                  with_split: bool = True, split_weight: int | None = None) -> Problem:
    """Four 14-chair and three 12-chair tables from scoring doc §11.1."""
    tables = [Table(id=f"U{i}", zone_id="upper", capacity=14 if i <= 4 else 12)
              for i in range(1, 8)]
    guests = [Guest(id=f"clan-{i}", name=f"Clan {i}", group_id="clan")
              for i in range(36)]
    locked = {}
    # The first six portions are distributed across U1..U6; for the
    # consolidated case the three 12-chair tables U5..U7 are used.
    used_tables = ["U5", "U6", "U7"] if len(clan_portions) == 3 else (
        ["U1", "U2", "U3", "U4", "U5", "U6"] if len(clan_portions) == 6 else [])
    assert sum(clan_portions) == 36
    assert len(used_tables) == len(clan_portions)
    guest_index = 0
    for table, portion in zip(used_tables, clan_portions):
        for _ in range(portion):
            locked[f"clan-{guest_index}"] = table
            guest_index += 1

    # Eleven intact other parties, 56 guests. Each list's table order is
    # chosen to fit the corresponding locked clan arrangement exactly.
    other_sizes = [8, 4, 2, 7, 7, 5, 5, 4, 5, 5, 4]
    assert len(other_party_tables) == len(other_sizes)
    for index, (size, table) in enumerate(zip(other_sizes, other_party_tables)):
        for person in range(size):
            guest_id = f"other-{index}-{person}"
            guests.append(Guest(id=guest_id, name=f"Other {index}/{person}",
                                group_id=f"other-{index}"))
            locked[guest_id] = table
    catalog = rule_catalog()
    default_weight = next(spec.default_weight for spec in catalog.shapes
                          if spec.shape == "split_penalty")
    weight = split_weight if split_weight is not None else default_weight
    assert weight is not None and weight > 0
    return Problem(
        session_id="clan-36", zones=[Zone(id="upper", name="Upper")],
        tables=tables, guests=guests,
        splittable_groups=["clan"], locked_guest_tables=locked,
        rules=[split_rule(weight)] if with_split else [],
        config=SolverConfig(time_limit_seconds=10, workers=2),
    )


def test_doc_11_1_consolidated_clan_strictly_beats_scatter_with_default_rule():
    # 12+12+12 on the 12-chair tables, other families occupying the 14s.
    consolidated = _clan_fixture(
        [12, 12, 12],
        ["U1", "U1", "U1", "U2", "U2", "U3", "U3", "U3", "U4", "U4", "U4"])
    # 9/3/6/3/3/12 on six tables, other groups filling every remainder:
    #  U1: clan9 + other5; U2: clan3 + 7+4; U3: clan6 + other8;
    #  U4: clan3 + 7+4; U5: clan3 + 5+4; U6: clan12; U7: 5+5+2.
    scattered = _clan_fixture(
        [9, 3, 6, 3, 3, 12],
        ["U3", "U2", "U7", "U4", "U2", "U1", "U5", "U4", "U7", "U7", "U5"])
    consolidated_plan, scatter_plan = solve(consolidated), solve(scattered)
    weight = split_rule(next(s.default_weight for s in rule_catalog().shapes
                             if s.shape == "split_penalty")).weight
    assert score_of(consolidated_plan, "split") == -(3 - 1) * weight
    assert score_of(scatter_plan, "split") == -(6 - 1) * weight
    assert consolidated_plan.total_score > scatter_plan.total_score
    assert all(t.occupied == t.capacity for t in consolidated_plan.tables)
    assert all(t.occupied == t.capacity for t in scatter_plan.tables)


def test_doc_11_1_two_way_split_beats_six_way_scatter_of_same_family():
    tables = [Table(id=f"T{i}", zone_id="z", capacity=6) for i in range(6)]
    guests = [Guest(id=f"g{i}", name=f"Member {i}", group_id="family")
              for i in range(12)]
    def candidate(portions: list[int], rules: list[Rule]):
        locked = {}
        i = 0
        for j, count in enumerate(portions):
            for _ in range(count):
                locked[f"g{i}"] = f"T{j}"
                i += 1
        return solve(Problem(session_id="portion-count", zones=[Zone(id="z", name="Z")],
            tables=tables, guests=guests, locked_guest_tables=locked,
            splittable_groups=["family"], rules=rules,
            config=SolverConfig(time_limit_seconds=5, workers=2)))
    w = 100
    two = candidate([6, 6], [split_rule(w)])
    six = candidate([2] * 6, [split_rule(w)])
    assert score_of(two, "split") == -w
    assert score_of(six, "split") == -5 * w
    assert two.total_score > six.total_score
    assert all(0 <= table.occupied <= table.capacity for table in six.tables)
    # Rule instances are optional and their weights affect the score,
    # not hard-coded solver preferences.
    assert candidate([2] * 6, []).total_score == 0
    assert score_of(candidate([2] * 6, [split_rule(7)]), "split") == -35


def test_doc_11_2_language_criterion_both_faces_score_actual_pairs():
    # One table holds seven Hebrew speakers and one Greek speaker.
    # Positive: C(7,2)*w = 21*w. Negative: 7 cross pairs = -7*w.
    guests = [Guest(id=f"h{i}", name=f"Hebrew {i}", group_id="hebrew",
                    attributes={"language": "Hebrew"}) for i in range(7)]
    guests.append(Guest(id="greek", name="Greek", group_id="greek",
                        attributes={"language": "Greek"}))
    w = 5
    def candidate(parameters: dict, *, enabled=True):
        rules = ([Rule(id="lang", shape="attribute_grouping", mode="soft",
                       weight=w, parameters={"attribute": "language", **parameters})]
                 if enabled else [])
        return solve(Problem(session_id="criterion", zones=[Zone(id="z", name="Z")],
            tables=[Table(id="T", zone_id="z", capacity=8)],
            guests=guests, rules=rules, config=SolverConfig(time_limit_seconds=3, workers=2)))
    positive_legacy = candidate({})
    positive_explicit = candidate({"effect": "reward"})
    negative = candidate({"effect": "penalty"})
    assert score_of(positive_legacy, "lang") == 21 * w
    assert score_of(positive_explicit, "lang") == 21 * w
    assert score_of(negative, "lang") == -7 * w
    assert negative.total_score == -35
    assert sum(c.lost_points for c in negative.compromises if c.rule_id == "lang") == 7 * w
    assert candidate({}, enabled=False).total_score == 0


def test_pattern_polarity_existing_and_catalog_exposes_new_terms():
    specs = {spec.shape: spec for spec in rule_catalog().shapes}
    assert specs["split_penalty"].modes == ["soft"]
    assert specs["split_penalty"].fields == []
    assert specs["split_penalty"].default_weight > 25
    choices = next(f.choices for f in specs["attribute_grouping"].fields if f.name == "effect")
    assert choices == ["reward", "penalty"]
    assert "effect" in {f.name for f in specs["global_pattern"].fields}


def test_soft_rule_validation_covers_split_polarity_and_criterion_direction():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Rule(id="bad", shape="split_penalty", mode="hard")
    with pytest.raises(ValidationError):
        Rule(id="bad", shape="split_penalty", mode="soft", weight=5,
             parameters={"attribute": "language"})
    with pytest.raises(ValidationError):
        Rule(id="bad", shape="attribute_grouping", mode="soft", weight=5,
             parameters={"attribute": "language", "effect": "invalid"})
