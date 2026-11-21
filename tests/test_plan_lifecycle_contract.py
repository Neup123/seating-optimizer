"""Plan statuses have explicit semantic invariants for both solver generations."""
import pytest
from pydantic import ValidationError

from seating_optimizer.models import (
    Plan, PriorityMark, Assignment, PLAN_TRANSITIONS,
    plan_capabilities, validate_plan_lifecycle,
)
from seating_optimizer.generic_solver import GenericPlan


def pending():
    return PriorityMark(group_id="family", group_name="Family", grade=1, guest_count=1)


def assignment():
    return Assignment(group_id="family", group_name="Family", table_id="T",
                      guest_ids=["p1"], guest_names=["Person"])


@pytest.mark.parametrize("klass", [Plan, GenericPlan])
def test_completed_plan_cannot_report_pending_groups(klass):
    with pytest.raises(ValidationError, match="completed plan cannot have pending"):
        klass(session_id="s", status="optimal", pending_groups=[pending()])


@pytest.mark.parametrize("klass", [Plan, GenericPlan])
def test_review_state_must_name_the_pending_group(klass):
    with pytest.raises(ValidationError, match="must identify pending"):
        klass(session_id="s", status="needs_review")
    p = klass(session_id="s", status="needs_review", pending_groups=[pending()])
    assert plan_capabilities(p) == dict(printable=False, reviewable=True,
                                        retryable=True, complete=False)


@pytest.mark.parametrize("klass", [Plan, GenericPlan])
def test_failed_or_unknown_plan_cannot_report_successful_seats_or_scores(klass):
    for status in ("unknown", "infeasible"):
        with pytest.raises(ValidationError, match="confirmed assignments"):
            klass(session_id="s", status=status, assignments=[assignment()])
        with pytest.raises(ValidationError, match="objective score"):
            klass(session_id="s", status=status, total_score=42)


def test_staged_status_mutation_must_be_revalidated():
    plan = Plan(session_id="s", status="optimal")
    plan.pending_groups = [pending()]
    with pytest.raises(ValidationError, match="completed plan"):
        validate_plan_lifecycle(plan)
    plan.status = "needs_review"
    assert validate_plan_lifecycle(plan).status == "needs_review"


def test_transition_contract_contains_required_states():
    for state in ("input_ready", "solving", "optimal", "feasible", "infeasible",
                  "unknown", "needs_review", "applied_manual_decision", "dirty_after_edit"):
        assert state in PLAN_TRANSITIONS
    assert "solving" in PLAN_TRANSITIONS["dirty_after_edit"]
    assert "applied_manual_decision" in PLAN_TRANSITIONS["needs_review"]


def test_api_exposes_same_status_capabilities_as_python_contract():
    from fastapi.testclient import TestClient
    from seating_optimizer.api.app import app
    from seating_optimizer.models import PLAN_SOLVE_STATUSES, status_capabilities
    response = TestClient(app).get("/v2/plan/status-capabilities")
    assert response.status_code == 200
    assert response.json() == {
        status: status_capabilities(status) for status in PLAN_SOLVE_STATUSES
    }
    assert response.json()["needs_review"]["reviewable"] is True
    assert response.json()["infeasible"]["printable"] is False
