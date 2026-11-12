"""Self-contained smoke checks for the external-corpus comparison harness.

Real test-230 data deliberately stays in the coordinator workspace.
"""
from __future__ import annotations

import json

from seating_optimizer.equivalence import (
    DEFAULT_CASES, Case, _compare, _expected, _case_problem,
    corpus_gate, small_random_gate,
)
from seating_optimizer.models import Plan, ScoreItem
from test_generic_engine_foundation import _legacy_instances


def test_random_legacy_vs_generic_without_hidden_objective_terms():
    small_random_gate(samples=20)


def test_external_corpus_directory_interface_with_synthetic_manifest(tmp_path):
    (tmp_path / "test-230").mkdir()
    (tmp_path / "test-230-rerun").mkdir()
    (tmp_path / "test-230" / "guests-216-control.csv").write_text(
        "Name,Size,Language\nA,1,Greek\nB,1,Hebrew\n", encoding="utf-8"
    )
    configuration = {
        "version": 1, "name": "Synthetic venue",
        "zones": [{"id": "z", "name": "Z"}],
        "tables": [{"id": "T", "zone_id": "z", "capacity": 2}],
    }
    (tmp_path / "test-230-rerun" / "venue-configuration.json").write_text(
        json.dumps(configuration), encoding="utf-8"
    )
    inventory = _legacy_instances()
    for record in inventory:
        record["enabled"] = False
    (tmp_path / "test-230-rerun" / "rules-listing.json").write_text(
        json.dumps({"rules": inventory}), encoding="utf-8"
    )
    (tmp_path / "test-230-rerun" / "verdicts-rerun.json").write_text(
        json.dumps({"verdicts": [{"id": f"v{i}", "status": "PASS"}
                                 for i in range(29)]}), encoding="utf-8"
    )
    (tmp_path / "equivalence-cases.json").write_text(
        json.dumps({"cases": [{
            "name": "synthetic-manifest", "guest_file": "test-230/guests-216-control.csv",
            "expected_status": "feasible", "score": 0, "seated": 2,
        }]}), encoding="utf-8"
    )
    assert corpus_gate(tmp_path) == 1


def test_default_corpus_cases_match_2026_11_11_rerun_driver():
    by_name = {case.name: case for case in DEFAULT_CASES}
    assert len(by_name) == 7
    assert by_name["run1-full-overcapacity"].guest_file == "test-230/guests-230.csv"
    assert by_name["run2-hard-conflict"].guest_file == "test-230/guests-216-control.csv"
    for key in ("run3-feasible", "demo-split", "demo-low-priority",
                "demo-direct-mark", "manual-unseat"):
        assert by_name[key].guest_file == "test-230/guests-216-split.csv"
        assert "clan-upper-floor" not in by_name[key].disabled
    assert by_name["run3-feasible"].enabled is None
    assert by_name["run3-feasible"].score == 2260  # reference ONLY
    assert by_name["demo-split"].time_limit_seconds == 15
    assert by_name["demo-split"].score == -1997596  # reference ONLY
    assert by_name["demo-low-priority"].allow_d1_difference
    assert (by_name["demo-low-priority"].legacy_seated,
            by_name["demo-low-priority"].generic_seated) == (189, 205)
    assert by_name["manual-unseat"].unseated_group_id == "registration:5"


def test_named_hard_rule_conflicts_accept_identifier_or_name():
    case = Case("run2", "unused.csv", "infeasible",
                conflict="clan-upper-floor")
    with_id = Plan(
        session_id="s", status="infeasible",
        conflicting_constraints=["rule:clan-upper-floor (Clan — upper floor only)"],
    )
    with_name = Plan(
        session_id="s", status="infeasible",
        conflicting_constraints=["Clan — upper floor only"],
    )
    _expected(case, with_id, engine="generic")
    # For a name-only diagnostic, a caller can opt for operator-friendly
    # wording by supplying the resolved display name as its expected token.
    case.conflict = "Clan — upper floor only"
    _expected(case, with_name, engine="generic")


def test_historical_2260_is_not_an_asserted_five_second_objective():
    case = Case("run3", "unused.csv", "feasible", seated=1,
                score=2260, breakdown={"hebrew-grouping": 2260})
    old = Plan(session_id="s", status="feasible", total_score=2240,
               score_breakdown=[ScoreItem(rule_id="hebrew-grouping", points=2240)],
               assignments=[])
    # A no-assignment stand-in intentionally proves that the reference score
    # is ignored, while the seated count is still a real condition.
    case.seated = None
    _expected(case, old, engine="legacy")


def test_d1_comparison_allows_its_deliberate_partial_plan_difference():
    from seating_optimizer.models import Assignment, PriorityMark
    def item(group_id):
        return Assignment(group_id=group_id, table_id="T",
                          guest_ids=[group_id], guest_names=[group_id],
                          guest_attributes=[{}])
    old = Plan(session_id="s", status="needs_review",
               total_score=10, assignments=[item("ordinary")])
    new = Plan(session_id="s", status="needs_review",
               total_score=20, assignments=[item("ordinary"), item("low")])
    case = Case("low", "unused.csv", "needs_review", allow_d1_difference=True)
    assert _compare(case, old, new) is None


def test_timed_incumbents_require_explicit_tolerance_for_search_noise():
    old = Plan(session_id="s", status="feasible", total_score=2240,
               score_breakdown=[ScoreItem(rule_id="language", points=2240)])
    new = Plan(session_id="s", status="feasible", total_score=2340,
               score_breakdown=[ScoreItem(rule_id="language", points=2340)])
    case = Case("run3", "unused.csv", "feasible", score=2260)
    import pytest
    with pytest.raises(AssertionError, match="objective delta"):
        _compare(case, old, new)
    assert _compare(case, old, new, score_tolerance=100) == 100
